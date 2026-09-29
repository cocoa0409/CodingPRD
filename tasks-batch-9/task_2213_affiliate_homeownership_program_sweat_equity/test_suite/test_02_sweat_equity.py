"""The four-step sweat equity ledger: claim, verify, credit, reverse."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import COORDINATOR, CREW_LEAD, make_applicant_headers


def _selected_family(api, **program_overrides):
    """A selected household with one applicant member and the clock at 2026-08-05."""
    program = X.setup_program(api, **program_overrides)
    built = X.setup_selected_household(api, program["id"])
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    return program, built["household"], built["members"][0]


def test_each_entry_rounds_its_own_weighted_product_to_two_decimals(api):
    """Weighted hours are rounded per entry, before anything is summed.

    "Third — and this is the step whose ordering matters most — the entry's gross
    weighted hours are `hours_claimed` multiplied by `credit_weight` and
    **rounded half-up to two decimal places immediately**, before any allowance
    comparison and before any ledger addition."

    "`OTHER_AFFILIATE` work carries 0.75", so 1.75 hours weigh 1.3125 raw and
    credit 1.31 apiece. "Sixth, `hours_credited` is the smallest of the gross
    weighted hours, the remaining category room, and the remaining family room,
    and `capped_hours` records the difference" — the other three categories are
    uncapped, so nothing is capped here.

    Design: Difficulty/combinatorial_formula/sweat_equity_round_per_entry_before_summation
    """
    _program, household, member = _selected_family(api)
    applicant = make_applicant_headers(household["id"])

    credited = []
    for _ in range(3):
        entry = validate_success(
            api.create_entry(
                F.entry_payload(
                    household["id"],
                    member["id"],
                    category=C.CATEGORY_OTHER_AFFILIATE,
                    hours_claimed=1.75,
                    work_date="2026-08-04T00:00:00.000Z",
                ),
                headers=applicant,
            ),
            201,
        )
        assert entry["credit_weight"] is None
        assert entry["hours_credited"] is None
        assert entry["capped_hours"] == 0
        validate_success(api.verify_entry(entry["id"], F.verification_payload(), headers=COORDINATOR))
        credited.append(validate_success(api.credit_entry(entry["id"], headers=COORDINATOR)))

    for entry in credited:
        assert entry["status"] == C.ENTRY_CREDITED
        assert entry["credit_weight"] == 0.75
        assert entry["hours_credited"] == 1.31
        assert entry["capped_hours"] == 0.0


def test_the_household_ledger_sums_the_already_rounded_entries(api):
    """The ledger totals 3.93 hours, not the 3.94 a single final rounding gives.

    "Three separate 1.75-hour `OTHER_AFFILIATE` entries therefore credit 1.31
    hours each for a household total of 3.93, not the 3.94 that summing the raw
    products and rounding once at the end would produce; per-entry rounding is
    the specification and sum-first rounding is wrong."

    "The member's `credited_hours_to_date` rises by the credited hours. The
    household's `sweat_equity_credited_hours` rises by the same amount, its
    `family_member_credited_hours` is recomputed, and `sweat_equity_satisfied` is
    re-derived as whether `sweat_equity_credited_hours` has reached
    `sweat_equity_required_hours`." The worker is the `APPLICANT`, and "members
    who are the applicant or co-applicant are exempt from this allowance
    entirely", so the family-scoped total stays at zero.

    Design: Difficulty/combinatorial_formula/sweat_equity_round_per_entry_before_summation
    """
    _program, household, member = _selected_family(api)
    applicant = make_applicant_headers(household["id"])

    for _ in range(3):
        entry = validate_success(
            api.create_entry(
                F.entry_payload(
                    household["id"],
                    member["id"],
                    category=C.CATEGORY_OTHER_AFFILIATE,
                    hours_claimed=1.75,
                    work_date="2026-08-04T00:00:00.000Z",
                ),
                headers=applicant,
            ),
            201,
        )
        X.verify_hours(api, entry["id"], headers=COORDINATOR)
        X.credit_hours(api, entry["id"])

    member_row = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    assert member_row["credited_hours_to_date"] == 3.93

    household_row = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert household_row["sweat_equity_credited_hours"] == 3.93
    assert household_row["family_member_credited_hours"] == 0.0
    assert household_row["sweat_equity_required_hours"] == 12.0
    assert household_row["sweat_equity_satisfied"] is False


def test_one_credit_advances_the_partnership_and_the_readiness_dimensions_together(api):
    """A satisfying credit moves both dimensions in a single request.

    "If the household's `selection_status` is `SELECTED` and its credited hours
    are now above zero, it advances `SELECTED → PARTNERSHIP_ACTIVE`; the first
    credited hour is what turns a selected family into an active partner. If the
    household's `partnership_readiness` is `EDUCATION_COMPLETE` and the
    requirement has just been satisfied, readiness advances
    `EDUCATION_COMPLETE → CLOSING_READY`".

    "`sweat_equity_satisfied` is re-derived as whether
    `sweat_equity_credited_hours` has reached `sweat_equity_required_hours` —
    equality satisfies the requirement", and 12.00 credited hours land exactly on
    the 12.00-hour requirement.

    Design: Difficulty/non_linear_state_machine/household_parallel_dimensions_readiness_regresses_alone
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    enrollment = X.setup_completed_education(api, household["id"])
    assert enrollment["status"] == C.ENROLLMENT_COMPLETED
    before = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert before["selection_status"] == C.SELECTION_SELECTED
    assert before["partnership_readiness"] == C.READINESS_EDUCATION_COMPLETE

    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    entry = X.setup_credited_entry(
        api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z"
    )
    assert entry["hours_credited"] == 12.0
    assert entry["credit_weight"] == 1.0

    after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert after["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert after["partnership_readiness"] == C.READINESS_CLOSING_READY
    assert after["sweat_equity_credited_hours"] == 12.0
    assert after["sweat_equity_satisfied"] is True


def test_a_reversal_regresses_readiness_alone_and_leaves_the_partnership_active(api):
    """The readiness cycle is independent of the selection dimension.

    "Once `sweat_equity_satisfied` falls back to false because credited hours
    have dropped below the requirement, a household sitting at `CLOSING_READY`
    regresses `CLOSING_READY → EDUCATION_COMPLETE`, and every
    `CLEARED_TO_CLOSE` mortgage of that household regresses to `APPROVED`. The
    `EDUCATION_COMPLETE ↔ CLOSING_READY` cycle is entirely independent of the
    selection dimension, which does not move during it."

    "The reversal moves the original `CREDITED → REVERSED` and creates a **new**
    entry in `CREDITED` status whose `reversal_of_entry_id` points at the
    original", and the pair "nets to exactly 0.00".

    Design: Difficulty/non_linear_state_machine/household_parallel_dimensions_readiness_regresses_alone
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    enrollment = X.setup_completed_education(api, household["id"])
    X.advance_clock(api, "2026-08-05T00:00:00.000Z")
    entry = X.setup_credited_entry(
        api, household["id"], member["id"], hours_claimed=12.0, work_date="2026-08-04T00:00:00.000Z"
    )
    peak = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert peak["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert peak["partnership_readiness"] == C.READINESS_CLOSING_READY

    reversed_entry = validate_success(
        api.reverse_entry(entry["id"], F.reversal_payload(), headers=COORDINATOR)
    )
    assert reversed_entry["status"] == C.ENTRY_REVERSED

    after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert after["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert after["partnership_readiness"] == C.READINESS_EDUCATION_COMPLETE
    assert after["sweat_equity_credited_hours"] == 0.0
    assert after["sweat_equity_satisfied"] is False

    still_complete = validate_success(api.get_enrollment(enrollment["id"], headers=COORDINATOR))
    assert still_complete["status"] == C.ENROLLMENT_COMPLETED


def test_the_identity_that_claimed_an_entry_cannot_verify_it(api):
    """Verification is the segregation-of-duties gate on the ledger.

    "Either way the acting identity is stamped onto `verified_by_user_id`, and
    either way the acting identity must differ from `claimed_by_user_id`."

    A claim opens "with `claimed_by_user_id` stamped from the acting
    `X-User-ID`", so the coordinator who filed the claim is refused and a
    different identity succeeds.

    Design: Corner/validations/the_claimant_of_an_entry_cannot_verify_it
    """
    _program, household, member = _selected_family(api)
    entry = X.claim_hours(
        api, household["id"], member["id"], hours_claimed=6.0, work_date="2026-08-04T00:00:00.000Z"
    )
    assert entry["claimed_by_user_id"] == "fsc-1"
    assert entry["verified_by_user_id"] is None
    assert entry["status"] == C.ENTRY_CLAIMED

    validate_error(
        api.verify_entry(entry["id"], F.verification_payload(), headers=COORDINATOR),
        E.ERR_SELF_VERIFICATION_FORBIDDEN,
        403,
    )
    unchanged = validate_success(api.get_entry(entry["id"], headers=COORDINATOR))
    assert unchanged["status"] == C.ENTRY_CLAIMED
    assert unchanged["verified_by_user_id"] is None

    verified = validate_success(api.verify_entry(entry["id"], F.verification_payload(), headers=CREW_LEAD))
    assert verified["status"] == C.ENTRY_VERIFIED
    assert verified["verified_by_user_id"] == "cm-1"


def test_a_claim_names_a_member_of_its_own_household(api):
    """A claim cannot post one family's hours onto another family's ledger.

    "Two checks guard the claim: the named member must belong to the same
    household as the entry and must still be `ACTIVE`, or the claim is refused
    with `ERR_MEMBER_NOT_ACTIVE`".

    Design: Corner/validations/an_entry_member_must_belong_to_the_named_household
    """
    program = X.setup_program(api)
    first = X.setup_selected_household(api, program["id"])
    other_household = X.setup_household(api, program["id"], household_name="Bakari")
    stranger = X.add_member(api, other_household["id"], full_name="Nina Bakari")

    response = api.create_entry(
        F.entry_payload(
            first["household"]["id"], stranger["id"], hours_claimed=6.0, work_date="2026-08-01T00:00:00.000Z"
        ),
        headers=COORDINATOR,
    )

    validate_error(response, E.ERR_MEMBER_NOT_ACTIVE, 409)
    ledger = validate_success(api.list_entries({"household_id": first["household"]["id"]}, headers=COORDINATOR))
    assert ledger == []


def test_a_work_date_after_the_clock_or_before_the_household_is_refused(api):
    """The work date must sit inside the household's own lifetime.

    "the `work_date` must be at or before the logical clock's present instant and
    at or after the household record's own `created_at`, or the claim is refused
    with `ERR_WORK_DATE_OUT_OF_RANGE`."

    The household is created at the initial clock instant of
    2026-08-01T00:00:00Z, so a claim for July work and a claim dated after the
    clock are both out of range while the clock instant itself is accepted.

    Design: Corner/validations/a_work_date_after_the_logical_clock_is_refused
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]

    future = api.create_entry(
        F.entry_payload(household["id"], member["id"], hours_claimed=4.0, work_date="2026-08-02T00:00:00.000Z"),
        headers=COORDINATOR,
    )
    validate_error(future, E.ERR_WORK_DATE_OUT_OF_RANGE, 422)

    before_intake = api.create_entry(
        F.entry_payload(household["id"], member["id"], hours_claimed=4.0, work_date="2026-07-31T00:00:00.000Z"),
        headers=COORDINATOR,
    )
    validate_error(before_intake, E.ERR_WORK_DATE_OUT_OF_RANGE, 422)

    at_the_clock = validate_success(
        api.create_entry(
            F.entry_payload(household["id"], member["id"], hours_claimed=4.0, work_date=C.INITIAL_CLOCK),
            headers=COORDINATOR,
        ),
        201,
    )
    assert at_the_clock["status"] == C.ENTRY_CLAIMED

    X.advance_clock(api, "2026-08-02T00:00:00.000Z")
    now_in_range = validate_success(
        api.create_entry(
            F.entry_payload(household["id"], member["id"], hours_claimed=4.0, work_date="2026-08-02T00:00:00.000Z"),
            headers=COORDINATOR,
        ),
        201,
    )
    assert now_in_range["status"] == C.ENTRY_CLAIMED


def test_credit_refuses_a_child_and_restricts_a_sixteen_year_old_to_two_categories(api):
    """The age waterfall runs first, before any weight is derived.

    "First, the member's age at the work date is computed as the whole number of
    years between `birth_date` and `work_date`, taking 365.25 days to the year
    and discarding the fraction. A member under 16 at that date cannot earn
    credit at all and the request is refused with
    `ERR_MEMBER_INELIGIBLE_FOR_CREDIT`; a member who is 16 or 17 counts as a
    minor, and a minor may only earn credit in the `RESTORE_STORE` or `ADVOCACY`
    categories ... so any other category from a minor is refused with
    `ERR_MINOR_CATEGORY_NOT_ALLOWED`."

    Design: Corner/validations/credit_age_floor_and_minor_category_restriction_at_credit_time
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(
        api,
        program["id"],
        member_specs=[
            {},
            {"full_name": "Kai Alvarez", "relationship": C.RELATIONSHIP_DEPENDENT,
             "birth_date": "2011-09-01T00:00:00.000Z", "is_adult_occupant": False},
            {"full_name": "Luz Alvarez", "relationship": C.RELATIONSHIP_DEPENDENT,
             "birth_date": "2009-01-15T00:00:00.000Z", "is_adult_occupant": False},
        ],
    )
    household = built["household"]
    child, minor = built["members"][1], built["members"][2]

    child_entry = X.claim_hours(
        api, household["id"], child["id"], category=C.CATEGORY_CONSTRUCTION, hours_claimed=4.0
    )
    X.verify_hours(api, child_entry["id"])
    validate_error(
        api.credit_entry(child_entry["id"], headers=COORDINATOR),
        E.ERR_MEMBER_INELIGIBLE_FOR_CREDIT,
        422,
    )

    minor_construction = X.claim_hours(
        api, household["id"], minor["id"], category=C.CATEGORY_CONSTRUCTION, hours_claimed=4.0
    )
    X.verify_hours(api, minor_construction["id"])
    validate_error(
        api.credit_entry(minor_construction["id"], headers=COORDINATOR),
        E.ERR_MINOR_CATEGORY_NOT_ALLOWED,
        422,
    )

    minor_allowed = X.claim_hours(
        api, household["id"], minor["id"], category=C.CATEGORY_RESTORE_STORE, hours_claimed=4.0
    )
    X.verify_hours(api, minor_allowed["id"])
    credited = validate_success(api.credit_entry(minor_allowed["id"], headers=COORDINATOR))
    assert credited["status"] == C.ENTRY_CREDITED
    assert credited["credit_weight"] == 0.5
    assert credited["hours_credited"] == 2.0

    ledger = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert ledger["sweat_equity_credited_hours"] == 2.0
    assert ledger["family_member_credited_hours"] == 2.0


def test_a_rejected_entry_is_resubmitted_by_the_family_and_clears_its_verifier(api):
    """Correction is the family's own pathway and reopens the claim.

    "A `REJECTED` decision requires its `rejection_reason` to be present, moves
    the entry `CLAIMED → REJECTED`, and sets `hours_credited` to 0 rather than
    leaving it null. A rejected claim is not the end of the story: the family —
    and only the family, acting as `Applicant` on its own household — may correct
    and resubmit it, overwriting `hours_claimed` and `work_date` from the new
    payload, clearing `verified_by_user_id` back to null, and returning the entry
    `REJECTED → CLAIMED`."

    Design: Corner/state_machines/rejected_entry_resubmit_overwrites_hours_and_clears_verifier
    """
    _program, household, member = _selected_family(api)
    entry = X.claim_hours(
        api, household["id"], member["id"], hours_claimed=8.0, work_date="2026-08-04T00:00:00.000Z"
    )

    rejected = validate_success(api.verify_entry(entry["id"], F.rejection_payload(), headers=CREW_LEAD))
    assert rejected["status"] == C.ENTRY_REJECTED
    assert rejected["hours_credited"] == 0
    assert rejected["verified_by_user_id"] == "cm-1"

    applicant = make_applicant_headers(household["id"])
    corrected = validate_success(
        api.resubmit_entry(
            entry["id"], F.resubmit_payload(3.5, "2026-08-03T00:00:00.000Z"), headers=applicant
        )
    )
    assert corrected["status"] == C.ENTRY_CLAIMED
    assert corrected["hours_claimed"] == 3.5
    assert corrected["work_date"].startswith("2026-08-03T00:00:00")
    assert corrected["verified_by_user_id"] is None

    verified = X.verify_hours(api, entry["id"])
    assert verified["status"] == C.ENTRY_VERIFIED
    credited = X.credit_hours(api, entry["id"])
    assert credited["hours_credited"] == 3.5


def test_the_advocacy_allowance_fills_then_refuses_the_next_entry(api):
    """A category allowance credits what fits, then refuses a zero-credit entry.

    "Homebuyer-education hours cap at 25.00 hours per household and advocacy
    hours cap at 10.00; the other three categories are uncapped."

    "Sixth, `hours_credited` is the smallest of the gross weighted hours, the
    remaining category room, and the remaining family room, and `capped_hours`
    records the difference between the gross figure and what was actually
    credited ... An entry that would credit exactly zero hours is refused with
    `ERR_CATEGORY_CREDIT_CAP_REACHED`."

    Advocacy weighs 0.50, so 12-hour claims gross 6.00 apiece: the first two
    credit 6.00 and then 4.00 with 2.00 capped, and the third has no room left.

    Design: Corner/calculations/advocacy_category_allowance_fills_then_refuses_the_next_entry
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]

    first = X.setup_credited_entry(
        api, household["id"], member["id"], category=C.CATEGORY_ADVOCACY, hours_claimed=12.0
    )
    assert first["credit_weight"] == 0.5
    assert first["hours_credited"] == 6.0
    assert first["capped_hours"] == 0.0

    second = X.setup_credited_entry(
        api, household["id"], member["id"], category=C.CATEGORY_ADVOCACY, hours_claimed=12.0
    )
    assert second["hours_credited"] == 4.0
    assert second["capped_hours"] == 2.0

    ledger = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert ledger["sweat_equity_credited_hours"] == 10.0
    assert ledger["sweat_equity_satisfied"] is False
    assert ledger["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert ledger["partnership_readiness"] == C.READINESS_NOT_READY

    third = X.claim_hours(
        api, household["id"], member["id"], category=C.CATEGORY_ADVOCACY, hours_claimed=12.0
    )
    X.verify_hours(api, third["id"])
    validate_error(
        api.credit_entry(third["id"], headers=COORDINATOR), E.ERR_CATEGORY_CREDIT_CAP_REACHED, 422
    )
    untouched = validate_success(api.get_entry(third["id"], headers=COORDINATOR))
    assert untouched["status"] == C.ENTRY_VERIFIED
    assert untouched["capped_hours"] == 0

    unchanged = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert unchanged["sweat_equity_credited_hours"] == 10.0


def test_a_minor_earns_exactly_half_the_category_weight(api):
    """The minor multiplier halves the weight and the credited hours with it.

    "Work in `CONSTRUCTION`, `RESTORE_STORE`, or `HOMEOWNER_EDUCATION` carries
    full weight of 1.00; `OTHER_AFFILIATE` work carries 0.75; `ADVOCACY` carries
    0.50. A minor's weight is then halved. The product is rounded half-up to two
    decimal places, so an adult on advocacy work earns a weight of 0.50 and a
    17-year-old on the same work earns 0.25."

    A member born 2009-09-01 is 16 at a 2026-08-01 work date, so 8 hours of
    `RESTORE_STORE` work weigh 0.50 and credit 4.00 hours, which still fits the
    six-hour family allowance of a twelve-hour requirement.

    Design: Corner/calculations/minor_multiplier_halves_the_category_weight_for_a_sixteen_year_old
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(
        api,
        program["id"],
        member_specs=[
            {},
            {"full_name": "Nia Alvarez", "relationship": C.RELATIONSHIP_DEPENDENT,
             "birth_date": "2009-09-01T00:00:00.000Z", "is_adult_occupant": False},
        ],
    )
    household, minor = built["household"], built["members"][1]

    credited = X.setup_credited_entry(
        api, household["id"], minor["id"], category=C.CATEGORY_RESTORE_STORE, hours_claimed=8.0
    )
    assert credited["credit_weight"] == 0.5
    assert credited["hours_credited"] == 4.0
    assert credited["capped_hours"] == 0.0

    minor_row = validate_success(api.get_member(minor["id"], headers=COORDINATOR))
    assert minor_row["credited_hours_to_date"] == 4.0

    household_row = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert household_row["sweat_equity_credited_hours"] == 4.0
    # A DEPENDENT draws on the family allowance, unlike the applicant.
    assert household_row["family_member_credited_hours"] == 4.0


def test_the_family_allowance_lands_exactly_on_its_cap_then_refuses(api):
    """The family allowance is half the frozen requirement, truncated.

    "any member whose `relationship` is something other than `APPLICANT` or
    `CO_APPLICANT` draws against an aggregate allowance of half the household's
    frozen `sweat_equity_required_hours`, truncated to a whole number of hours —
    150 hours against a 300-hour requirement, 175 against 350."

    "A family-scoped entry arriving with zero family room left is refused
    outright with `ERR_FAMILY_CREDIT_CAP_REACHED`."

    With a twelve-hour requirement the family allowance is 6 hours, so a 6-hour
    construction entry by an extended-family member lands exactly on it and the
    next 2-hour entry finds zero room. `CONSTRUCTION` carries no category
    ceiling, so the exhausted bucket is unambiguously the family one, while the
    applicant is exempt and still credits normally.

    Design: Corner/validations/family_allowance_lands_exactly_on_the_cap_then_refuses
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(
        api,
        program["id"],
        member_specs=[
            {},
            {"full_name": "Tio Alvarez", "relationship": C.RELATIONSHIP_EXTENDED_FAMILY,
             "birth_date": "1995-02-02T00:00:00.000Z", "is_adult_occupant": False},
        ],
    )
    household, applicant_member, relative = built["household"], built["members"][0], built["members"][1]
    assert household["sweat_equity_required_hours"] == 12.0

    credited = X.setup_credited_entry(api, household["id"], relative["id"], hours_claimed=6.0)
    assert credited["credit_weight"] == 1.0
    assert credited["hours_credited"] == 6.0
    assert credited["capped_hours"] == 0.0

    at_the_cap = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert at_the_cap["family_member_credited_hours"] == 6.0
    assert at_the_cap["sweat_equity_credited_hours"] == 6.0
    assert at_the_cap["sweat_equity_satisfied"] is False

    blocked = X.claim_hours(api, household["id"], relative["id"], hours_claimed=2.0)
    X.verify_hours(api, blocked["id"])
    validate_error(
        api.credit_entry(blocked["id"], headers=COORDINATOR), E.ERR_FAMILY_CREDIT_CAP_REACHED, 422
    )
    untouched = validate_success(api.get_entry(blocked["id"], headers=COORDINATOR))
    assert untouched["status"] == C.ENTRY_VERIFIED

    exempt = X.setup_credited_entry(api, household["id"], applicant_member["id"], hours_claimed=6.0)
    assert exempt["hours_credited"] == 6.0
    final = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert final["sweat_equity_credited_hours"] == 12.0
    assert final["family_member_credited_hours"] == 6.0


def test_crediting_requires_a_verified_entry(api):
    """Credit is only reachable from the verified state.

    "Crediting is where hours actually land, and it belongs exclusively to the
    `FamilyServicesCoordinator`. The entry must be `VERIFIED` and the household
    must be `SELECTED` or `PARTNERSHIP_ACTIVE`."

    Design: Corner/endpoints/crediting_is_conditional_on_the_entry_having_been_verified
    """
    _program, household, member = _selected_family(api)
    entry = X.claim_hours(
        api, household["id"], member["id"], hours_claimed=6.0, work_date="2026-08-04T00:00:00.000Z"
    )

    validate_error(api.credit_entry(entry["id"], headers=COORDINATOR), E.ERR_TRANSITION_NOT_ALLOWED, 409)
    still_claimed = validate_success(api.get_entry(entry["id"], headers=COORDINATOR))
    assert still_claimed["status"] == C.ENTRY_CLAIMED
    assert still_claimed["hours_credited"] is None

    rejected_entry = X.claim_hours(
        api, household["id"], member["id"], hours_claimed=6.0, work_date="2026-08-04T00:00:00.000Z"
    )
    validate_success(api.verify_entry(rejected_entry["id"], F.rejection_payload(), headers=CREW_LEAD))
    validate_error(api.credit_entry(rejected_entry["id"], headers=COORDINATOR), E.ERR_TRANSITION_NOT_ALLOWED, 409)

    X.verify_hours(api, entry["id"])
    credited = validate_success(api.credit_entry(entry["id"], headers=COORDINATOR))
    assert credited["status"] == C.ENTRY_CREDITED
    assert credited["hours_credited"] == 6.0


def test_a_credit_is_visible_in_its_own_response_and_in_the_very_next_read(api):
    """Every cascade completes inside the request that caused it.

    "A successful credit then cascades four hops, all inside the same request."
    "Each row touched along the way — entry, member, household, and any
    application — has its `version` incremented by 1."

    Design: Corner/consistency_model/a_credit_is_visible_in_its_own_response_and_in_the_very_next_read
    """
    _program, household, member = _selected_family(api)
    member_before = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    household_before = validate_success(api.get_household(household["id"], headers=COORDINATOR))

    entry = X.claim_hours(
        api, household["id"], member["id"], hours_claimed=6.0, work_date="2026-08-04T00:00:00.000Z"
    )
    X.verify_hours(api, entry["id"])
    credited = validate_success(api.credit_entry(entry["id"], headers=COORDINATOR))

    assert credited["status"] == C.ENTRY_CREDITED
    assert credited["hours_credited"] == 6.0

    entry_read = validate_success(api.get_entry(entry["id"], headers=COORDINATOR))
    assert entry_read["hours_credited"] == credited["hours_credited"]
    assert entry_read["version"] == credited["version"]

    member_after = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    assert member_after["credited_hours_to_date"] == 6.0
    assert member_after["version"] == member_before["version"] + 1

    household_after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert household_after["sweat_equity_credited_hours"] == 6.0
    assert household_after["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE
    assert household_after["version"] == household_before["version"] + 1

    listed = validate_success(api.list_entries({"household_id": household["id"]}, headers=COORDINATOR))
    assert [row["id"] for row in listed] == [entry["id"]]
    assert listed[0]["status"] == C.ENTRY_CREDITED
