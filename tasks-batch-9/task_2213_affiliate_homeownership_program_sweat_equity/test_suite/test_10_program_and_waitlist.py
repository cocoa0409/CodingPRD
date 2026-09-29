"""Program posture, pool stewardship, committee arithmetic, and the waitlist selector."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import (
    ADMIN,
    APPROVER,
    COMMITTEE_ALICE,
    COMMITTEE_BRUNO,
    COORDINATOR,
    OFFICER,
    make_headers,
)

_HIGGINS = {
    "household_name": "Higgins",
    "household_size": 3,
    "current_bedroom_count": 2,
    "habitability_deficiency_count": 1,
    "self_reported_annual_income_cents": 3_200_000,
    "self_reported_housing_cost_cents": 120_000,
    "monthly_debt_payment_cents": 80_000,
    "credit_score": 640,
    "on_time_housing_payment_months": 6,
}
_LOWELL = dict(_HIGGINS, household_name="Lowell", habitability_deficiency_count=0)


def _waitlisted(api, program_id, overrides, member_name, birth_date):
    """A household whose final composite lands between the two decision thresholds."""
    built = X.setup_selected_household(
        api,
        program_id,
        household_overrides=overrides,
        member_specs=[{"full_name": member_name, "birth_date": birth_date}],
    )
    return built["household"]


def _thin_pool_underwriting(api):
    """An underwritten file whose silent second is larger than the whole pool."""
    program = X.setup_program(api, subsidy_pool_cents=1_000_000)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    assert application["silent_second_amount_cents"] == 1_950_000
    return program, application


def _suspend(api, program_id, memo="Board-ordered suspension pending audit"):
    return validate_success(
        api.adjust_subsidy_pool(
            program_id,
            F.pool_adjustment_payload(C.POOL_ACTION_SUSPEND, X.program_version(api, program_id), memo=memo),
            headers=ADMIN,
        )
    )


def _resume(api, program_id, memo="Audit closed; intake resumes"):
    return validate_success(
        api.adjust_subsidy_pool(
            program_id,
            F.pool_adjustment_payload(C.POOL_ACTION_RESUME, X.program_version(api, program_id), memo=memo),
            headers=ADMIN,
        )
    )


def test_a_frozen_program_answers_before_the_thin_pool_does(api):
    """One approve breaks two rules and the lower position names the error.

    "An approval on a suspended program whose remaining subsidy is *also* too
    small fails both the frozen-program check at position 12 and the
    subsidy-capacity check at position 38; the answer is `ERR_PROGRAM_FROZEN`,
    never `ERR_SUBSIDY_POOL_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_program_priority_12_beats_subsidy_exhaustion_priority_38
    """
    program, application = _thin_pool_underwriting(api)

    frozen = _suspend(api, program["id"])
    assert frozen["status"] == C.PROGRAM_STATUS_SUSPENDED
    assert frozen["program_posture"] == C.POSTURE_FROZEN
    assert frozen["subsidy_available_cents"] == 1_000_000

    validate_error(
        api.approve_application(
            application["id"],
            F.approval_payload(X.program_version(api, program["id"])),
            headers=APPROVER,
        ),
        E.ERR_PROGRAM_FROZEN,
        409,
    )

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["status"] == C.APP_UNDERWRITING
    assert reread["silent_second_amount_cents"] == 1_950_000

    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["status"] == C.PROGRAM_STATUS_SUSPENDED
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 1_000_000


def test_resuming_the_program_uncovers_the_fiscal_refusal_underneath(api):
    """The losing rule was genuinely violated, not merely absent.

    "`RESUME_PROGRAM` flips `status` back to `ACTIVE` and re-derives the posture
    from the available balance." With the freeze gone the identical approve call
    reaches position 38, where "the silent second must fit inside the program's
    `subsidy_available_cents` ... or the approval is refused with
    `ERR_SUBSIDY_POOL_EXHAUSTED`".

    Design: Difficulty/priority_pair_validation_conflict/frozen_program_priority_12_beats_subsidy_exhaustion_priority_38
    """
    program, application = _thin_pool_underwriting(api)
    _suspend(api, program["id"])

    resumed = _resume(api, program["id"])
    assert resumed["status"] == C.PROGRAM_STATUS_ACTIVE
    assert resumed["program_posture"] == C.POSTURE_OPEN
    assert resumed["subsidy_available_cents"] == 1_000_000

    validate_error(
        api.approve_application(
            application["id"],
            F.approval_payload(X.program_version(api, program["id"])),
            headers=APPROVER,
        ),
        E.ERR_SUBSIDY_POOL_EXHAUSTED,
        409,
    )

    reread = validate_success(api.get_application(application["id"], headers=OFFICER))
    assert reread["status"] == C.APP_UNDERWRITING
    reread_program = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert reread_program["subsidy_committed_cents"] == 0
    assert reread_program["subsidy_available_cents"] == 1_000_000


def test_a_frozen_parent_program_stops_the_screening_of_its_household(api):
    """The dependent write is refused for a reason that lives entirely on the parent.

    "With `action` of `SUSPEND_PROGRAM` the program's `status` flips to
    `SUSPENDED`, which immediately re-derives `program_posture` to `FROZEN` and
    stops intake, hour crediting, construction scheduling, and every money
    movement across the program." Screening is one of those stopped writes:
    "The program must not be frozen."

    Design: Difficulty/cross_entity_state_dependency/household_screening_blocked_while_parent_program_posture_is_frozen
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    submitted = X.submit_household(api, household["id"])
    assert submitted["selection_status"] == C.SELECTION_SUBMITTED
    assert submitted["documentation_status"] == C.DOC_SUBMITTED

    frozen = _suspend(api, program["id"])
    assert frozen["status"] == C.PROGRAM_STATUS_SUSPENDED
    assert frozen["program_posture"] == C.POSTURE_FROZEN

    validate_error(
        api.screen_household(household["id"], F.screen_payload(), headers=COORDINATOR),
        E.ERR_PROGRAM_FROZEN,
        409,
    )

    reread = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    # The household side never moved: it is still awaiting its verification pass.
    assert reread["selection_status"] == C.SELECTION_SUBMITTED
    assert reread["score_basis"] is None
    assert reread["need_score"] is None
    assert reread["ability_to_pay_score"] is None


def test_resuming_the_parent_lets_the_identical_screen_call_through(api):
    """Only the parent moved, and the same call now writes the preliminary scores.

    "Screening also produces the household's first scores, computed on the
    **preliminary basis**, which reads the family's self-reported figures and
    ignores the verified ones even when they have just been written in the same
    request."

    Design: Difficulty/cross_entity_state_dependency/household_screening_blocked_while_parent_program_posture_is_frozen
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    X.submit_household(api, household["id"])
    _suspend(api, program["id"])
    validate_error(
        api.screen_household(household["id"], F.screen_payload(), headers=COORDINATOR),
        E.ERR_PROGRAM_FROZEN,
        409,
    )

    resumed = _resume(api, program["id"])
    assert resumed["status"] == C.PROGRAM_STATUS_ACTIVE
    assert resumed["program_posture"] == C.POSTURE_OPEN

    screened = validate_success(
        api.screen_household(household["id"], F.screen_payload(), headers=COORDINATOR)
    )
    assert screened["selection_status"] == C.SELECTION_SCREENING
    assert screened["documentation_status"] == C.DOC_VERIFIED
    assert screened["score_basis"] == C.BASIS_PRELIMINARY
    # Self-reported 3,600,000 a year: 40 for cost burden, 30 for crowding, 30 for deficiencies.
    assert screened["need_score"] == 100
    assert screened["ability_to_pay_score"] == 100
    assert screened["ami_pct"] == 0.6


def test_the_willingness_mean_follows_the_surviving_reviews_to_the_empty_set(api):
    """Two, one, then none: the divisor tracks the rows and the empty set is null.

    "`willingness_score` is the mean of the `score` values of the effective
    willingness reviews, rounded half-up to two decimal places, and is null when
    there are no effective willingness reviews at all — which is what makes the
    composite null immediately after a retraction removes the last one."

    Design: Difficulty/boundary_precision_check/willingness_review_set_two_then_one_then_empty_collection_edge
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]
    for reviewer in (COMMITTEE_ALICE, COMMITTEE_BRUNO):
        for dimension in (C.DIMENSION_NEED, C.DIMENSION_ABILITY):
            validate_success(
                api.create_review(F.review_payload(household_id, dimension, 80), headers=reviewer), 201
            )
    alice_willingness = validate_success(
        api.create_review(
            F.review_payload(
                household_id,
                C.DIMENSION_WILLINGNESS,
                90,
                documented_reason="Attended every orientation",
            ),
            headers=COMMITTEE_ALICE,
        ),
        201,
    )
    bruno_willingness = validate_success(
        api.create_review(
            F.review_payload(
                household_id,
                C.DIMENSION_WILLINGNESS,
                70,
                documented_reason="Two rescheduled meetings",
            ),
            headers=COMMITTEE_BRUNO,
        ),
        201,
    )

    with_two = validate_success(api.get_household(household_id, headers=ADMIN))
    assert with_two["willingness_score"] == 80.0
    assert with_two["need_score"] == 100

    retracted_bruno = validate_success(
        api.retract_review(
            bruno_willingness["id"],
            F.retraction_payload(retraction_reason="Score keyed against the wrong household"),
            headers=COMMITTEE_BRUNO,
        )
    )
    assert retracted_bruno["status"] == C.REVIEW_RETRACTED

    with_one = validate_success(api.get_household(household_id, headers=ADMIN))
    # The divisor fell with the set: the surviving 90 is the whole mean.
    assert with_one["willingness_score"] == 90.0

    retracted_alice = validate_success(
        api.retract_review(
            alice_willingness["id"],
            F.retraction_payload(retraction_reason="Committee reopened the willingness interview"),
            headers=COMMITTEE_ALICE,
        )
    )
    assert retracted_alice["status"] == C.REVIEW_RETRACTED

    with_none = validate_success(api.get_household(household_id, headers=ADMIN))
    assert with_none["willingness_score"] is None
    assert with_none["composite_selection_score"] is None
    assert with_none["score_basis"] == C.BASIS_PRELIMINARY


def test_an_emptied_willingness_dimension_drops_quorum_and_blocks_the_decision(api):
    """Retraction is invisible to quorum too, so the vote cannot be taken.

    "Quorum is met only when, for each of the three dimensions `NEED`, `ABILITY`,
    and `WILLINGNESS` independently, the number of distinct `reviewer_user_id`
    values among that dimension's effective reviews is at least the program's
    `committee_quorum`." Falling short is fatal to the vote: "Quorum must be met
    on all three dimensions or the decision is refused with
    `ERR_COMMITTEE_QUORUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/willingness_review_set_two_then_one_then_empty_collection_edge
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]
    reviews = X.file_review_set(api, household_id)
    willingness = [r for r in reviews if r["dimension"] == C.DIMENSION_WILLINGNESS]
    assert len(willingness) == 2

    for review in willingness:
        validate_success(
            api.retract_review(
                review["id"],
                F.retraction_payload(retraction_reason="Committee reopened the willingness interview"),
                headers=make_headers(review["reviewer_user_id"], "SelectionCommitteeMember"),
            )
        )

    validate_error(
        api.record_selection_decision(
            household_id,
            F.selection_decision_payload(
                decision_minutes="Attempted vote with no surviving willingness review"
            ),
            headers=ADMIN,
        ),
        E.ERR_COMMITTEE_QUORUM_NOT_MET,
        409,
    )

    reread = validate_success(api.get_household(household_id, headers=ADMIN))
    # NEED and ABILITY still hold quorum, so only the willingness dimension failed.
    assert reread["selection_status"] == C.SELECTION_COMMITTEE_REVIEW
    assert reread["score_basis"] == C.BASIS_PRELIMINARY
    assert reread["willingness_score"] is None
    assert reread["composite_selection_score"] is None


def test_crediting_then_reversing_returns_the_hour_counter_to_zero(api):
    """The forward hop really moves the counter, and the reversal restores it exactly.

    "The household's `sweat_equity_credited_hours` must always equal the sum of
    `hours_credited` over that household's entries in `CREDITED` or `REVERSED`
    status, rounded to two decimals, and each member's `credited_hours_to_date`
    must equal the same sum restricted to that member."

    Design: Difficulty/compensating_invariant/invariant_sweat_equity_hours_credit_then_reverse_nets_to_zero
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    assert household["sweat_equity_required_hours"] == 12.0
    assert household["sweat_equity_credited_hours"] == 0.0
    assert household["family_member_credited_hours"] == 0.0
    assert household["sweat_equity_satisfied"] is False
    assert household["selection_status"] == C.SELECTION_SELECTED

    X.advance_clock(api, "2026-08-03T00:00:00.000Z")
    entry = X.claim_hours(
        api,
        household["id"],
        member["id"],
        hours_claimed=6.0,
        work_date="2026-08-02T09:00:00.000Z",
    )
    X.verify_hours(api, entry["id"])
    assert validate_success(api.get_member(member["id"], headers=COORDINATOR))["credited_hours_to_date"] == 0.0

    credited = X.credit_hours(api, entry["id"])
    assert credited["credit_weight"] == 1.0
    assert credited["hours_credited"] == 6.0
    assert credited["capped_hours"] == 0.0

    mid_household = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert mid_household["sweat_equity_credited_hours"] == 6.0
    # An APPLICANT member never draws on the family allowance.
    assert mid_household["family_member_credited_hours"] == 0.0
    assert mid_household["sweat_equity_satisfied"] is False
    mid_member = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    assert mid_member["credited_hours_to_date"] == 6.0

    validate_success(
        api.reverse_entry(
            entry["id"],
            F.reversal_payload(reversal_reason="Timesheet duplicated the Sunday crew log"),
            headers=COORDINATOR,
        )
    )

    after_household = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert after_household["sweat_equity_credited_hours"] == 0.0
    assert after_household["family_member_credited_hours"] == 0.0
    assert after_household["sweat_equity_satisfied"] is False
    after_member = validate_success(api.get_member(member["id"], headers=COORDINATOR))
    assert after_member["credited_hours_to_date"] == 0.0


def test_the_reversal_nets_against_a_mirror_row_and_leaves_the_status_alone(api):
    """Nothing is deleted: the pair sums to zero and the state dimension does not move.

    "Reversal ... does not edit the original row's `hours_credited`; instead it
    writes a mirror `SweatEquityEntry` for the same household, member, category
    and `work_date`, with `hours_claimed` of 0, `hours_credited` of the negative
    of the original credited hours, `credit_weight` copied from the original,
    status `CREDITED`, and `reversal_of_entry_id` pointing at the reversed row.
    The original moves `CREDITED → REVERSED` and keeps its positive
    `hours_credited`."

    Design: Difficulty/compensating_invariant/invariant_sweat_equity_hours_credit_then_reverse_nets_to_zero
    """
    program = X.setup_program(api)
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    X.advance_clock(api, "2026-08-03T00:00:00.000Z")
    entry = X.claim_hours(
        api,
        household["id"],
        member["id"],
        hours_claimed=6.0,
        work_date="2026-08-02T09:00:00.000Z",
    )
    X.verify_hours(api, entry["id"])
    X.credit_hours(api, entry["id"])
    mid = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert mid["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE

    validate_success(
        api.reverse_entry(
            entry["id"],
            F.reversal_payload(reversal_reason="Timesheet duplicated the Sunday crew log"),
            headers=COORDINATOR,
        )
    )

    original = validate_success(api.get_entry(entry["id"], headers=COORDINATOR))
    assert original["status"] == C.ENTRY_REVERSED
    assert original["hours_credited"] == 6.0

    mirrors, mirror_meta = validate_paginated(
        api.list_entries({"reversal_of_entry_id": entry["id"]}, headers=COORDINATOR)
    )
    assert mirror_meta["total_count"] == 1
    mirror = mirrors[0]
    assert mirror["status"] == C.ENTRY_CREDITED
    assert mirror["hours_credited"] == -6.0
    assert mirror["credit_weight"] == 1.0
    assert mirror["hours_claimed"] == 0.0
    assert mirror["reversal_of_entry_id"] == entry["id"]
    assert mirror["member_id"] == member["id"]
    assert mirror["category"] == C.CATEGORY_CONSTRUCTION

    ledger, _ = validate_paginated(api.list_entries({"household_id": household["id"]}, headers=COORDINATOR))
    booked = [row for row in ledger if row["status"] in (C.ENTRY_CREDITED, C.ENTRY_REVERSED)]
    assert round(sum(row["hours_credited"] for row in booked), 2) == 0.0

    after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    # The counter was compensated; the selection dimension it had advanced was not.
    assert after["selection_status"] == C.SELECTION_PARTNERSHIP_ACTIVE


def test_the_willingness_mean_is_rounded_before_the_composite_weights_it(api):
    """Two roundings compose without drifting a cent.

    "When a willingness figure exists, `composite_selection_score` is 0.40 times
    `need_score` plus 0.35 times `ability_to_pay_score` plus 0.25 times
    `willingness_score`, rounded half-up to two decimal places."

    The stored mean of 70 and 85 is 77.5, so the weighted sum is exactly 90.375
    and half-up rounding lands on 90.38 rather than 90.37.

    Design: Corner/calculations/willingness_mean_rounds_to_two_decimals_before_the_composite
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]
    for reviewer, willingness in ((COMMITTEE_ALICE, 70), (COMMITTEE_BRUNO, 85)):
        for dimension in (C.DIMENSION_NEED, C.DIMENSION_ABILITY):
            validate_success(
                api.create_review(F.review_payload(household_id, dimension, 80), headers=reviewer), 201
            )
        validate_success(
            api.create_review(
                F.review_payload(household_id, C.DIMENSION_WILLINGNESS, willingness), headers=reviewer
            ),
            201,
        )

    decided = validate_success(
        api.record_selection_decision(
            household_id,
            F.selection_decision_payload(
                decision_minutes="Committee minutes 2026-08-01: willingness split 70 and 85"
            ),
            headers=ADMIN,
        )
    )

    assert decided["score_basis"] == C.BASIS_FINAL
    assert decided["willingness_score"] == 77.5
    # Verified 3,000,000: cost burden 0.4 gives 30, crowding 30, deficiencies 30.
    assert decided["need_score"] == 90
    assert decided["ability_to_pay_score"] == 100
    assert decided["composite_selection_score"] == 90.38
    assert decided["selection_status"] == C.SELECTION_SELECTED


def test_the_selector_takes_the_top_rank_then_the_rest_then_refuses(api):
    """A ranked partial draw, clamped to the pool and erroring only when it is empty.

    "That pool is ranked by `composite_selection_score` from highest to lowest,
    ties broken by `need_score` from highest to lowest ... The number actually
    promoted is the smallest of the requested `promote_count`, the capacity, and
    the size of the ranked pool, and the promoted households are the first that
    many rows of the ranking. ... An empty eligible pool is refused with
    `ERR_NO_ELIGIBLE_WAITLIST_HOUSEHOLD`."

    Design: Corner/calculations/waitlist_selector_ranks_by_composite_and_stops_at_the_requested_count
    """
    program = X.setup_program(api)
    site_a = X.setup_ready_site(api, program["id"], parcel_number="P-1001", street_address="12 Cedar Ln")
    site_b = X.setup_ready_site(api, program["id"], parcel_number="P-1002", street_address="14 Cedar Ln")
    high = _waitlisted(api, program["id"], _HIGGINS, "Mara Higgins", "1986-01-20T00:00:00.000Z")
    low = _waitlisted(api, program["id"], _LOWELL, "Ivan Lowell", "1987-04-04T00:00:00.000Z")
    assert high["selection_status"] == C.SELECTION_WAITLISTED
    assert high["composite_selection_score"] == 61.75
    assert low["selection_status"] == C.SELECTION_WAITLISTED
    assert low["composite_selection_score"] == 55.75

    first = validate_success(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=1), headers=ADMIN)
    )
    assert isinstance(first, list)
    assert len(first) == 1
    assert first[0]["id"] == high["id"]
    assert first[0]["selection_status"] == C.SELECTION_SELECTED

    still_waiting = validate_success(api.get_household(low["id"], headers=COORDINATOR))
    # The lower composite was ranked second and left behind.
    assert still_waiting["selection_status"] == C.SELECTION_WAITLISTED

    second = validate_success(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=5), headers=ADMIN)
    )
    assert len(second) == 1
    assert second[0]["id"] == low["id"]
    assert second[0]["selection_status"] == C.SELECTION_SELECTED

    for site_id in (site_a["id"], site_b["id"]):
        # Promotion does not claim a site, so capacity stayed at two throughout.
        assert validate_success(api.get_build_site(site_id, headers=ADMIN))["assigned_household_id"] is None

    validate_error(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=1), headers=ADMIN),
        E.ERR_NO_ELIGIBLE_WAITLIST_HOUSEHOLD,
        409,
    )


def test_a_bulk_promotion_beyond_capacity_promotes_only_what_fits(api):
    """The shortfall is skipped, not reported as a failure and not rolled back.

    "Capacity is the number of the program's build sites whose `readiness_status`
    is `READY_TO_BUILD` and whose `assigned_household_id` is still null ... The
    number actually promoted is the smallest of the requested `promote_count`, the
    capacity, and the size of the ranked pool."

    Design: Corner/endpoints/bulk_promotion_is_clamped_by_site_capacity_without_a_partial_error
    """
    program = X.setup_program(api)
    X.setup_ready_site(api, program["id"])
    high = _waitlisted(api, program["id"], _HIGGINS, "Mara Higgins", "1986-01-20T00:00:00.000Z")
    low = _waitlisted(api, program["id"], _LOWELL, "Ivan Lowell", "1987-04-04T00:00:00.000Z")

    promoted = validate_success(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=2), headers=ADMIN)
    )
    assert len(promoted) == 1
    assert promoted[0]["id"] == high["id"]
    assert promoted[0]["selection_status"] == C.SELECTION_SELECTED
    assert promoted[0]["composite_selection_score"] == 61.75

    skipped = validate_success(api.get_household(low["id"], headers=COORDINATOR))
    assert skipped["selection_status"] == C.SELECTION_WAITLISTED
    assert skipped["composite_selection_score"] == 55.75

    rows, meta = validate_paginated(
        api.list_households(
            {"program_id": program["id"], "selection_status": C.SELECTION_WAITLISTED}, headers=ADMIN
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == low["id"]


def test_a_site_short_of_ready_is_not_capacity_at_all(api):
    """An eligible family and an almost-ready site still means zero capacity.

    "Capacity is the number of the program's build sites whose `readiness_status`
    is `READY_TO_BUILD` and whose `assigned_household_id` is still null; sites
    under a safety hold or already under construction do not count. ... a
    non-empty pool with zero ready-and-unassigned site capacity is refused with
    `ERR_NO_READY_SITE_CAPACITY`."

    Design: Corner/validations/waitlist_promotion_without_ready_site_capacity_is_refused
    """
    program = X.setup_program(api)
    site = X.setup_env_cleared_site(api, program["id"])
    assert site["readiness_status"] == C.SITE_ENV_CLEARED
    household = _waitlisted(api, program["id"], _HIGGINS, "Mara Higgins", "1986-01-20T00:00:00.000Z")
    assert household["selection_status"] == C.SELECTION_WAITLISTED

    validate_error(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=1), headers=ADMIN),
        E.ERR_NO_READY_SITE_CAPACITY,
        409,
    )
    waiting = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert waiting["selection_status"] == C.SELECTION_WAITLISTED
    assert waiting["composite_selection_score"] == 61.75

    cleared = X.advance_site(api, site["id"], C.STEP_UTILITIES)
    assert cleared["readiness_status"] == C.SITE_READY_TO_BUILD
    assert cleared["assigned_household_id"] is None

    promoted = validate_success(
        api.promote_waitlist(program["id"], F.waitlist_promotion_payload(promote_count=1), headers=ADMIN)
    )
    assert len(promoted) == 1
    assert promoted[0]["id"] == household["id"]
    assert promoted[0]["selection_status"] == C.SELECTION_SELECTED


def test_a_reduction_stops_at_the_committed_floor_and_may_land_exactly_on_it(api):
    """The floor under a sweep is the obligations, not zero.

    "A reduction that would leave `subsidy_pool_cents` below the sum of
    `subsidy_committed_cents` and `subsidy_disbursed_cents` breaks the
    conservation identity of §2.10 and is refused with
    `ERR_POOL_BELOW_OBLIGATIONS`."

    Design: Corner/validations/a_pool_reduction_cannot_dip_below_committed_obligations
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    household = X.setup_selected_household(api, program["id"])["household"]
    application = X.setup_underwritten_application(api, household["id"], site["id"])
    X.approve_application(api, application["id"], program["id"])

    before = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert before["subsidy_pool_cents"] == 5_000_000
    assert before["subsidy_committed_cents"] == 1_950_000
    assert before["subsidy_disbursed_cents"] == 0
    assert before["subsidy_available_cents"] == 3_050_000
    assert (
        before["subsidy_pool_cents"]
        == before["subsidy_available_cents"] + before["subsidy_committed_cents"] + before["subsidy_disbursed_cents"]
    )

    validate_error(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_REDUCE,
                before["version"],
                delta_cents=3_500_000,
                memo="Sweeping too much capital back to the general fund",
            ),
            headers=ADMIN,
        ),
        E.ERR_POOL_BELOW_OBLIGATIONS,
        409,
    )

    unchanged = validate_success(api.get_program(program["id"], headers=ADMIN))
    assert unchanged["subsidy_pool_cents"] == 5_000_000
    assert unchanged["subsidy_committed_cents"] == 1_950_000
    assert unchanged["subsidy_available_cents"] == 3_050_000
    # A refused adjustment is not a write, so the version did not move.
    assert unchanged["version"] == before["version"]

    swept = validate_success(
        api.adjust_subsidy_pool(
            program["id"],
            F.pool_adjustment_payload(
                C.POOL_ACTION_REDUCE,
                unchanged["version"],
                delta_cents=3_050_000,
                memo="Sweeping exactly the uncommitted balance",
            ),
            headers=ADMIN,
        )
    )
    assert swept["subsidy_pool_cents"] == 1_950_000
    assert swept["subsidy_committed_cents"] == 1_950_000
    assert swept["subsidy_disbursed_cents"] == 0
    assert swept["subsidy_available_cents"] == 0
    assert swept["program_posture"] == C.POSTURE_SUBSIDY_RESTRICTED
    assert (
        swept["subsidy_pool_cents"]
        == swept["subsidy_available_cents"] + swept["subsidy_committed_cents"] + swept["subsidy_disbursed_cents"]
    )
