"""
Validation surfaces: single-occupancy roles, temporal bounds, aggregate capacity,
conditionally required fields and the ladder that decides which refusal is reported.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    fixtures as fx,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_two_decimal_places,
)
from test_helpers.factories import (
    background_result_payload,
    conversion_window_payload,
    evidence_payload,
    exam_result_payload,
    organizer_payload,
    qualification_waiver_payload,
    regulatory_filing_payload,
    subscription_payload,
)
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BACKGROUND_PENDING,
    CATEGORY_MANAGEMENT,
    COMPOSITION_DEFICIENT,
    COMPOSITION_FORMING,
    COMPOSITION_MET,
    CONDITION_EVIDENCE_SUBMITTED,
    CONDITION_OPEN,
    DIMENSION_FINGERPRINT,
    EXAM_OUTCOME_PASSED,
    FILING_CONDITIONALLY_APPROVED,
    FILING_DRAFT,
    FINDING_FINANCIAL_CRIME,
    FINDING_NONE,
    FINGERPRINT_CLEARED,
    FINGERPRINT_FLAGGED,
    PLAN_DRAFT,
    PLAN_SUBMITTED,
    QUALIFICATION_DISQUALIFIED,
    QUALIFICATION_PENDING,
    QUALIFICATION_QUALIFIED,
    QUALIFICATION_WAIVER_GRANTED,
    ROLE_ON_BOARD_DIRECTOR,
    ROLE_ON_BOARD_PROPOSED_CEO,
    SCENARIO_ADVERSE,
    STAGE_PRE_OPENING,
    WINDOW_RESERVED,
)

_UNUSED_EXAM_ID = "00000000-0000-0000-0000-0000000000ff"


# ---------------------------------------------------------------------------
# Corner / validations
# ---------------------------------------------------------------------------
def test_a_second_chief_executive_is_refused_while_a_second_director_is_welcome(
    api, composition_met_group
):
    """
    The four key officer chairs hold one occupant each, so a second chief executive is turned
    away and nothing at all is written — the head count and the composite are exactly as they
    were. The same person seated as an ordinary director is admitted, because that chair has
    no occupancy limit: the board grows to six, gains a fourth independent member, and its
    average falls to 65.00 as the new seat's 31 points enter the sum while the composition
    verdict holds.

    PRD: "`role_on_board` is one of `PROPOSED_CEO`, `PROPOSED_CFO`, `PROPOSED_CRO`, `PROPOSED_CCO`, `DIRECTOR` or `INVESTOR_ONLY`; the four key officer roles are single-occupancy within a group, so seating a second `PROPOSED_CFO` alongside an existing one is refused with `ERR_OFFICER_ROLE_ALREADY_FILLED`, while `DIRECTOR` and `INVESTOR_ONLY` may be held by any number of organizers."
    PRD: "Otherwise, each eligible organizer's already-rounded integer `qualification_subscore` is what enters the sum — the integer rounding has already happened at the organizer level and the persisted integer is authoritative — the sum is divided by the number of eligible organizers, and only that quotient is rounded, half up, to two decimal places."

    Design: Corner/validations/validation_second_proposed_ceo_is_rejected
    """
    world = composition_met_group

    validate_error(
        api.create_organizer(
            world["group_id"],
            organizer_payload(
                full_name="Adaeze Obi",
                role_on_board=ROLE_ON_BOARD_PROPOSED_CEO,
                is_independent=True,
                affiliation_code="IND_E",
                banking_years=9,
                regulatory_experience_score=74,
            ),
            COUNSEL_HEADERS,
        ),
        "ERR_OFFICER_ROLE_ALREADY_FILLED",
        expected_status=409,
    )
    refused = fx.read_group(api, world["group_id"])
    assert_fields_equal(refused, organizer_count=5)
    assert_two_decimal_places(
        refused["management_composite_score"], 71.80, "management_composite_score"
    )

    director = get_success_data(
        api.create_organizer(
            world["group_id"],
            organizer_payload(
                full_name="Adaeze Obi",
                role_on_board=ROLE_ON_BOARD_DIRECTOR,
                is_independent=True,
                affiliation_code="IND_E",
                banking_years=5,
                regulatory_experience_score=60,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        director,
        role_on_board=ROLE_ON_BOARD_DIRECTOR,
        qualification_subscore=31,
        qualification_status=QUALIFICATION_PENDING,
    )

    seated = fx.read_group(api, world["group_id"])
    assert_fields_equal(
        seated,
        organizer_count=6,
        independent_organizer_count=4,
        composition_status=COMPOSITION_MET,
    )
    assert_two_decimal_places(
        seated["management_composite_score"], 65.00, "management_composite_score"
    )


def test_a_migration_window_may_start_exactly_now_but_not_a_second_ago(api):
    """
    The lower bound on a migration slot is inclusive. One second before the clock is in the
    past and is refused without the contract's calendar changing at all, while the very same
    instant as the clock is accepted and books a two-day outage — 48.00 hours to the second.

    PRD: "The end must be strictly after the start, so a zero-length window is refused with `ERR_WINDOW_END_NOT_AFTER_START` (HTTP 422), and the start must be at or after the current logical clock, so a window starting exactly now is fine but one starting a second ago is refused with `ERR_WINDOW_START_IN_PAST` (HTTP 422)."
    PRD: "`duration_hours` is derived as the elapsed seconds between the two instants divided by 3600 and rounded half up to two decimal places, and it may not exceed 72.00 hours — a three-day outage is the ceiling, so exactly 72.00 hours is accepted and 72.01 is refused with `ERR_WINDOW_TOO_LONG` (HTTP 422)."
    PRD: "On success the window begins in `RESERVED`, the contract's `active_window_count` is recomputed as the number of its `RESERVED` or `CONFIRMED` windows — counting all occupants, not merely the overlapping ones — and the contract's `version` increments by one."

    Design: Corner/validations/validation_window_start_exactly_at_the_clock_is_accepted
    """
    world = fx.open_group(api)
    contract_id = fx.signed_core_vendor(api, world)
    version = fx.contract_version(api, contract_id)

    validate_error(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id, version, "2026-07-31T23:59:59Z", "2026-08-02T00:00:00Z"
            ),
            COUNSEL_HEADERS,
        ),
        "ERR_WINDOW_START_IN_PAST",
        expected_status=422,
    )
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=0)

    window = get_success_data(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id, version, "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z"
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(window, status=WINDOW_RESERVED)
    assert window["window_start_utc"].startswith("2026-08-01T00:00:00"), (
        f"the window must open at the clock instant: {window['window_start_utc']!r}"
    )
    assert_two_decimal_places(window["duration_hours"], 48.00, "duration_hours")
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=1)


def test_the_wrong_caller_is_told_so_before_anybody_looks_for_the_examination(api):
    """
    Recording an examination result belongs to the chartering examiner alone. Counsel asking
    for an examination that does not exist is stopped in the authorization band, so the
    refusal names the role and never reveals that the identifier is unknown. The same call
    from the examiner reaches the existence band and gets the examination's own not-found
    code. Neither attempt moves the project.

    PRD: "Checks are therefore evaluated in a fixed ladder of bands, and the first failing check in the earliest band wins; later bands are not evaluated at all."
    PRD: "If the role is declared but is not among the roles authorized for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD: "The thirteen not-found codes are `ERR_GROUP_NOT_FOUND`, `ERR_ORGANIZER_NOT_FOUND`, `ERR_BUSINESS_PLAN_NOT_FOUND`, `ERR_STRESS_SCENARIO_NOT_FOUND`, `ERR_CAPITAL_RAISE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_CONDITION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_VENDOR_CONTRACT_NOT_FOUND`, `ERR_CONVERSION_WINDOW_NOT_FOUND`, `ERR_EXAM_NOT_FOUND` and `ERR_DEVIATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/validations/validation_role_check_outranks_unknown_exam_not_found
    """
    world = fx.pre_opening_group(api)

    role_refusal = validate_error(
        api.record_exam_result(
            _UNUSED_EXAM_ID, exam_result_payload(EXAM_OUTCOME_PASSED, 0), COUNSEL_HEADERS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    assert role_refusal["error_id"] != "ERR_EXAM_NOT_FOUND", (
        "the authorization band must be reported before anything is looked up"
    )

    validate_error(
        api.record_exam_result(
            _UNUSED_EXAM_ID,
            exam_result_payload(EXAM_OUTCOME_PASSED, 0),
            CHARTERING_EXAMINER_HEADERS,
        ),
        "ERR_EXAM_NOT_FOUND",
        expected_status=404,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_PRE_OPENING)


def test_a_regulator_may_not_be_handed_a_plan_that_is_still_an_internal_draft(api):
    """
    A draft plan is not evidence: preparing a filing against one is refused and no filing row
    is created at all. Submitting the plan changes nothing about the filing request except
    that the plan is now a real submission, and the identical call then succeeds — a fresh
    draft filing, no information rounds, no conditions, pinned to the very plan that had been
    rejected a moment earlier.

    PRD: "The pinned plan must belong to the same group as the filing and must be in `SUBMITTED` or `PINNED` status: a `DRAFT` plan that has never been submitted, or a `SUPERSEDED` plan that has been replaced, cannot be put in front of a regulator, and the attempt is refused with `ERR_PINNED_PLAN_NOT_SUBMITTED`."
    PRD: "Submission is the moment the plan stops being an internal draft, and it is performed by a `LeadOrganizer` on a `DRAFT` plan, moving `status` from `DRAFT` to `SUBMITTED` and incrementing the plan's `version` by one."

    Design: Corner/validations/validation_pinned_plan_must_be_submitted_before_filing_creation
    """
    world = fx.composition_met_group(api)
    plan_id = fx.add_business_plan(api, world)
    fx.add_stress_scenario(
        api,
        plan_id,
        SCENARIO_ADVERSE,
        credit_loss_rate_bps=60,
        nim_compression_bps=15,
        expense_overrun_cents=0,
    )
    assert_fields_equal(fx.read_plan(api, plan_id), status=PLAN_DRAFT)

    payload = regulatory_filing_payload(world["group_id"], plan_id, AUTHORITY_CHARTERING)
    validate_error(
        api.create_regulatory_filing(payload, COUNSEL_HEADERS),
        "ERR_PINNED_PLAN_NOT_SUBMITTED",
        expected_status=409,
    )
    _, meta = validate_paginated(
        api.list_regulatory_filings(COUNSEL_HEADERS, params={"group_id": world["group_id"]})
    )
    assert meta["total_count"] == 0, (
        f"no filing may have been prepared, found {meta['total_count']}"
    )

    submitted = validate_success(
        api.submit_business_plan(plan_id, world["lead_headers"]), expected_status=200
    )
    assert_fields_equal(submitted, status=PLAN_SUBMITTED)

    filing = get_success_data(
        api.create_regulatory_filing(payload, COUNSEL_HEADERS), expected_status=201
    )
    assert_fields_equal(
        filing,
        status=FILING_DRAFT,
        pinned_business_plan_id=plan_id,
        info_request_round=0,
        condition_total_count=0,
    )


def test_evidence_arriving_at_the_stroke_of_the_deadline_is_already_late(
    api, conditionally_approved_group
):
    """
    The deadline is exclusive. With the clock advanced to the exact instant a management
    condition was due, the remediation package is refused and the condition is left as it
    was — still open, no reference stored, no adjudication recorded, because a refused
    submission is not an audit event. A sibling condition with room left on its clock takes
    the identical package and moves sideways into the submitted state. Neither condition
    blocks pre-opening, so the filing's posture is two conditions with no open blockers and
    its approval intact.

    PRD: "The current logical clock must be strictly before `deadline_utc`; a submission at exactly the deadline instant is late and is refused with `ERR_CONDITION_DEADLINE_PASSED` (HTTP 409)."
    PRD: "A new condition begins with `status` `OPEN`, `evidence_reference` null and `adjudication_count` 0, then the parent filing's four posture fields are recomputed and the filing's `version` increments by one."
    PRD: "On success `status` becomes `EVIDENCE_SUBMITTED` and `evidence_reference` is overwritten with the supplied value, so it always reflects the most recent submission."

    Design: Corner/validations/validation_evidence_at_exactly_the_deadline_is_rejected
    """
    world = conditionally_approved_group
    late = fx.add_condition(
        api,
        world["f_ca"],
        "MGMT-BIO-REFRESH",
        CATEGORY_MANAGEMENT,
        False,
        deadline_utc="2026-09-01T00:00:00Z",
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    validate_error(
        api.submit_condition_evidence(
            late,
            evidence_payload("DOC-MGMT-BIO-REFRESH-PACKET-001"),
            COUNSEL_HEADERS,
        ),
        "ERR_CONDITION_DEADLINE_PASSED",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_condition(api, late),
        status=CONDITION_OPEN,
        evidence_reference=None,
        adjudication_count=0,
    )

    in_time = fx.add_condition(
        api,
        world["f_ca"],
        "MGMT-BIO-REFRESH-2",
        CATEGORY_MANAGEMENT,
        False,
        deadline_utc="2026-12-01T00:00:00Z",
    )
    submitted = validate_success(
        api.submit_condition_evidence(
            in_time,
            evidence_payload("DOC-MGMT-BIO-REFRESH-PACKET-002"),
            COUNSEL_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(
        submitted,
        status=CONDITION_EVIDENCE_SUBMITTED,
        evidence_reference="DOC-MGMT-BIO-REFRESH-PACKET-002",
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        status=FILING_CONDITIONALLY_APPROVED,
        condition_total_count=2,
        open_blocking_condition_count=0,
    )


def test_the_share_ceiling_is_measured_against_the_whole_book_not_one_order(api):
    """
    Two perfectly valid orders take the book to 4,900,000 of the 5,000,000 shares on offer.
    A third for 150,000 is individually unremarkable and still refused, because the guard adds
    the request to what is already pledged; the book is left untouched by the refusal. Exactly
    the remaining 100,000 is accepted and fills the offering to its ceiling, priced at the
    offering's 1000 cents a share, with none of it inside escrow yet.

    PRD: "The offering's share ceiling is an **aggregate** check: the raise's current `subscribed_shares` plus the requested `shares` must not exceed `max_shares`, so each individual subscription can be perfectly valid while the collection overflows, and the overflowing one is refused with `ERR_OFFERING_OVERSUBSCRIBED`."
    PRD: "It is the marketing view of the raise and is always greater than or equal to the cleared basis; it is what the oversubscription guard measures against `max_shares`."

    Design: Corner/validations/validation_subscription_that_overflows_max_shares_is_rejected
    """
    world = fx.bare_open_raise(api)
    fx.add_subscription(api, world["raise_id"], "Harbor Trust LP", 3_000_000)
    fx.add_subscription(api, world["raise_id"], "Puget Founders Fund", 1_900_000)
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        subscribed_shares=4_900_000,
        pledged_gross_cents=4_900_000_000,
    )

    validate_error(
        api.create_subscription(
            subscription_payload(
                world["raise_id"], subscriber_name="Cedar Ridge Trust", shares=150_000
            ),
            ESCROW_AGENT_HEADERS,
        ),
        "ERR_OFFERING_OVERSUBSCRIBED",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        subscribed_shares=4_900_000,
        pledged_gross_cents=4_900_000_000,
    )

    tail = get_success_data(
        api.create_subscription(
            subscription_payload(
                world["raise_id"], subscriber_name="Cedar Ridge Trust", shares=100_000
            ),
            ESCROW_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(tail, shares=100_000, amount_cents=100_000_000)
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        subscribed_shares=5_000_000,
        pledged_gross_cents=5_000_000_000,
        cleared_escrow_cents=0,
    )


def test_a_finding_category_is_demanded_only_when_the_outcome_is_adverse(api):
    """
    A clean fingerprint needs no explanation: it is recorded with the finding category left at
    its default and earns the organizer his twenty-five integrity points, though the unresolved
    credit dimension keeps his standing pending. An adverse fingerprint without a category is
    a schema failure, and nothing at all is written — the dimension is still awaiting a result,
    so the same call can be retried. Retried with a category it lands, and the flag disqualifies
    the officer outright even though credit has never been looked at.

    PRD: "An adverse outcome — `FLAGGED` on the fingerprint dimension or `ADVERSE` on the credit dimension — must be accompanied by an `adverse_finding_type` that is supplied and is not `NONE`; omitting it, or passing `NONE`, is rejected with `ERR_ADVERSE_FINDING_TYPE_REQUIRED` (HTTP 422)."
    PRD: "Both background dimensions start at `PENDING` — `fingerprint_state` at `PENDING` and `credit_state` at `PENDING` — with `adverse_finding_type` at `NONE`, `waiver_granted` false and `waiver_rationale` null."
    PRD: "The integrity component contributes a weighted twenty-five percent of one hundred — that is, twenty-five points — when and only when `fingerprint_state` is `CLEARED`, and contributes nothing otherwise."
    PRD: "The ordering has a visible consequence: an organizer with an adverse finding is `DISQUALIFIED` even if the other dimension has not yet been resolved, and a waiver overrides an adverse finding without erasing it."

    Design: Corner/validations/validation_adverse_finding_type_required_only_for_flagged_outcome
    """
    world = fx.seated_group(api, seats=2, clear=False)

    cleared = validate_success(
        api.record_background_result(
            world["o1"],
            background_result_payload(
                dimension=DIMENSION_FINGERPRINT, outcome=FINGERPRINT_CLEARED
            ),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(
        cleared,
        fingerprint_state=FINGERPRINT_CLEARED,
        adverse_finding_type=FINDING_NONE,
        qualification_subscore=68,
        qualification_status=QUALIFICATION_PENDING,
    )

    validate_error(
        api.record_background_result(
            world["o2"],
            background_result_payload(
                dimension=DIMENSION_FINGERPRINT, outcome=FINGERPRINT_FLAGGED
            ),
            CHARTERING_EXAMINER_HEADERS,
        ),
        "ERR_ADVERSE_FINDING_TYPE_REQUIRED",
        expected_status=422,
    )
    assert_fields_equal(
        get_success_data(api.get_organizer(world["o2"], COUNSEL_HEADERS)),
        fingerprint_state=BACKGROUND_PENDING,
        adverse_finding_type=FINDING_NONE,
    )

    flagged = validate_success(
        api.record_background_result(
            world["o2"],
            background_result_payload(
                dimension=DIMENSION_FINGERPRINT,
                outcome=FINGERPRINT_FLAGGED,
                adverse_finding_type=FINDING_FINANCIAL_CRIME,
            ),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(
        flagged,
        fingerprint_state=FINGERPRINT_FLAGGED,
        credit_state=BACKGROUND_PENDING,
        adverse_finding_type=FINDING_FINANCIAL_CRIME,
        qualification_subscore=51,
        qualification_status=QUALIFICATION_DISQUALIFIED,
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        organizer_count=2,
        composition_status=COMPOSITION_FORMING,
    )


def test_a_waiver_asks_whether_it_applies_before_it_asks_what_the_finding_was(api):
    """
    Three organizers, three answers. The qualified chief executive is not disqualified at all,
    so the request never reaches the finding bar and reports inapplicability. The director whose
    fingerprint came back flagged for financial crime is squarely disqualified, reaches the bar
    and is stopped there — his finding survives the refusal untouched. The director who is
    merely too weak on the numbers, with both dimensions clean and a subscore of 34, is
    rehabilitated: his standing changes and his subscore does not, since a waiver rewrites
    standing rather than merit. One disqualified organizer remains, so the board stays deficient
    and the average of 61.33 is exactly where it was.

    PRD: "The waiver is available only when the organizer's `qualification_status` is `DISQUALIFIED` and `waiver_granted` is still false; on any other standing, or on a second waiver attempt, the request is refused with `ERR_WAIVER_NOT_APPLICABLE`."
    PRD: "These two checks are ordered — the applicability check sits in the target-row-state band and the finding bar sits in the safety band, so an organizer who is not disqualified at all and who also carries a financial-crime finding reports `ERR_WAIVER_NOT_APPLICABLE`."
    PRD: "One finding category is non-waivable: when `adverse_finding_type` is `FINANCIAL_CRIME`, the waiver is barred with `ERR_WAIVER_BARRED_BY_FINDING` regardless of how high the subscore is."
    PRD: "A granted waiver sets `waiver_granted` to true, stores the supplied `waiver_rationale`, and moves `qualification_status` to `WAIVER_GRANTED`."

    Design: Corner/validations/validation_waiver_applicability_is_checked_before_the_finding_bar
    """
    world = fx.seated_group(api, seats=4, clear=True)
    flagged_director = fx.seat_organizer(
        api, world["group_id"], fx.CANONICAL_ORGANIZERS[4]
    )
    get_success_data(
        api.record_background_result(
            flagged_director,
            background_result_payload(
                dimension=DIMENSION_FINGERPRINT,
                outcome=FINGERPRINT_FLAGGED,
                adverse_finding_type=FINDING_FINANCIAL_CRIME,
            ),
            CHARTERING_EXAMINER_HEADERS,
        )
    )
    weak_director = fx.seat_organizer(
        api,
        world["group_id"],
        {
            "full_name": "Ingrid Solberg",
            "role_on_board": ROLE_ON_BOARD_DIRECTOR,
            "is_independent": True,
            "affiliation_code": "IND_D",
            "banking_years": 1,
            "regulatory_experience_score": 20,
        },
    )
    fx.clear_background(api, weak_director)
    assert_fields_equal(
        get_success_data(api.get_organizer(weak_director, COUNSEL_HEADERS)),
        qualification_subscore=34,
        qualification_status=QUALIFICATION_DISQUALIFIED,
    )
    before = fx.read_group(api, world["group_id"])
    assert_two_decimal_places(
        before["management_composite_score"], 61.33, "management_composite_score"
    )

    validate_error(
        api.grant_qualification_waiver(
            world["o1"], qualification_waiver_payload(), CHARTERING_EXAMINER_HEADERS
        ),
        "ERR_WAIVER_NOT_APPLICABLE",
        expected_status=409,
    )
    assert_fields_equal(
        get_success_data(api.get_organizer(world["o1"], COUNSEL_HEADERS)),
        waiver_granted=False,
        qualification_status=QUALIFICATION_QUALIFIED,
    )

    validate_error(
        api.grant_qualification_waiver(
            flagged_director, qualification_waiver_payload(), CHARTERING_EXAMINER_HEADERS
        ),
        "ERR_WAIVER_BARRED_BY_FINDING",
        expected_status=409,
    )
    assert_fields_equal(
        get_success_data(api.get_organizer(flagged_director, COUNSEL_HEADERS)),
        waiver_granted=False,
        qualification_status=QUALIFICATION_DISQUALIFIED,
        adverse_finding_type=FINDING_FINANCIAL_CRIME,
    )

    waived = validate_success(
        api.grant_qualification_waiver(
            weak_director, qualification_waiver_payload(), CHARTERING_EXAMINER_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        waived,
        waiver_granted=True,
        qualification_status=QUALIFICATION_WAIVER_GRANTED,
        qualification_subscore=34,
        fingerprint_state=FINGERPRINT_CLEARED,
    )

    after = fx.read_group(api, world["group_id"])
    assert_fields_equal(
        after, organizer_count=6, composition_status=COMPOSITION_DEFICIENT
    )
    assert_two_decimal_places(
        after["management_composite_score"], 61.33, "management_composite_score"
    )
