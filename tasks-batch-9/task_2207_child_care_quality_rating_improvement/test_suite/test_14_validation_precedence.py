"""Relative precedence between two simultaneously-failing checks on one request.

Every scenario in this file arranges a request on which *two* independent guards
would each reject, then pins which one the contract requires to be reported.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_enrolled_provider,
    create_reliable_observer,
    declare_domains,
    documentation_for,
    make_provider_headers,
    offer_grant,
    open_cycle,
    build_rating_spine,
    schedule_visit,
    set_clock,
    submit_self_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    verify_self_assessment,
)

ADMIN = TEST_USERS["admin_headers"]

#: A rating cycle id that the empty database never mints and no setup here creates.
MISSING_CYCLE_ID = "00000000-0000-4000-8000-0000000000ff"

#: Five domains of equal weight 0.20 summing to exactly 1.00, every block minimum
#: at 1 point so no block gate interferes with the guard under test.
EQUAL_WEIGHT_DOMAINS = [
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 1,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": True,
        "min_composite_for_block": 3.00,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 20,
        "block_min_points": 1,
        "weight": 0.20,
        "observation_linked": False,
    },
]

POINTS = {
    "LEARNING_ENVIRONMENT": 10,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 8,
    "ADMINISTRATION": 6,
    "CHILD_ASSESSMENT": 7,
}


def _docs_verified_cycle(legal_name, county_code):
    """Enrolled provider whose INITIAL cycle has been walked to DOCS_VERIFIED.

    Assumes the five standard domains are already declared.
    """
    provider = create_enrolled_provider(
        legal_name=legal_name,
        county_code=county_code,
        region_code="URBAN",
        licensed_capacity=50,
        active_staff_fte=10.00,
        weekly_onsite_cap_hours=12.0,
    )
    cycle = open_cycle(provider["id"])
    self_assessment = submit_self_assessment(
        provider["id"], cycle["id"], claimed=POINTS, documentation=documentation_for()
    )
    verify_self_assessment(self_assessment["id"], verified=POINTS)
    return provider, cycle


def test_provider_awarding_a_draft_cycle_is_refused_on_role_not_on_cycle_state(api):
    """PRD §2.7: "Second, role authorization: the acting role must appear in the target
    endpoint's permitted-role list, or the request fails with `ERR_FORBIDDEN_ROLE` and
    HTTP 403."
    PRD §2.7: "Tenth, the target resource's own state must be one from which the requested
    transition is declared, producing the state-family code for that entity —
    `ERR_PROVIDER_STATE_INVALID`, `ERR_CYCLE_STATE_INVALID`, `ERR_VISIT_STATE_INVALID`,
    `ERR_APPEAL_STATE_INVALID`, `ERR_DISPUTE_STATE_INVALID`, `ERR_GRANT_NOT_OPEN`,
    `ERR_EXPENDITURE_STATE_INVALID`, `ERR_ALLOCATION_STATE_INVALID`,
    `ERR_SESSION_STATE_INVALID`, or `ERR_CLAIM_STATE_INVALID` — each with HTTP 409."
    PRD §3.5: "Issuing the award is an administrator action against a cycle sitting in
    `OBSERVATION_FINALIZED`, and it carries a `score_variant` input recording which variant
    produced the tier."

    Design: Difficulty/priority_pair_validation_conflict/award_by_forbidden_role_beats_cycle_state
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Bright Start Center",
        county_code="C001",
        region_code="URBAN",
        licensed_capacity=60,
        active_staff_fte=12.00,
        weekly_onsite_cap_hours=12.0,
    )
    cycle = open_cycle(provider["id"])
    assert cycle["status"] == "DRAFT", f"cycle must open in DRAFT, got {cycle['status']}"

    forbidden = api.award_cycle(
        cycle["id"], {"score_variant": "FINAL"}, make_provider_headers(provider["id"])
    )
    error = validate_error(forbidden, "ERR_FORBIDDEN_ROLE", 403)
    assert error["error_id"] != "ERR_CYCLE_STATE_INVALID", (
        "role authorization is step two of the rejection ladder and must pre-empt the "
        "step-ten cycle-state check"
    )

    # The state check really was live: the identical call from the permitted role
    # reaches step ten and reports the cycle-state failure instead.
    state_refusal = api.award_cycle(cycle["id"], {"score_variant": "FINAL"}, ADMIN)
    validate_error(state_refusal, "ERR_CYCLE_STATE_INVALID", 409)

    unchanged = validate_success(api.get_rating_cycle(cycle["id"], ADMIN))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["awarded_tier"] is None
    assert unchanged["awarded_on"] is None


def test_missing_rating_cycle_path_is_refused_before_the_visit_body_is_schema_checked(api):
    """PRD §2.7: "Third, path existence: every path-templated resource must resolve, left
    to right, producing one of the 404 family codes described above."
    PRD §2.7: "Only then does the request body itself come under scrutiny. Sixth, body
    schema and range checking on every creating or acting request produces `ERR_VALIDATION`
    with HTTP 422: required fields must be present, enum-typed fields must carry a declared
    member, integers must respect their declared minimums, a subscale score must lie between
    1.0 and 7.0 inclusive and sit exactly on a half-point step, weights and fractional
    shares must lie inside their declared bounds, a service month must match the
    four-digit-year-hyphen-two-digit-month form, a secondary observer must differ from the
    lead observer, child-day maps may carry only the three declared age-band keys, and a
    claimed-points map must supply all five domain codes with no value above that domain's
    point ceiling."
    PRD §2.6: "An unresolvable `rating_cycle_id`, `self_assessment_id`,
    `observation_visit_id`, or `observation_score_id` — whether it arrived in the path or in
    a request body — yields `ERR_RATING_ARTIFACT_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/path_not_found_beats_body_schema_on_visit_scheduling
    """
    set_clock("2026-08-01T00:00:00Z")
    observer = create_reliable_observer("Obs Alpha", anchor_agreement_pct=92.00,
                                        certified_until="2027-06-30")

    response = api.create_observation_visit(
        MISSING_CYCLE_ID,
        {
            # Same observer in both slots AND window_end before window_start: two
            # independent step-six schema violations that must never be reported.
            "lead_observer_id": observer["id"],
            "secondary_observer_id": observer["id"],
            "window_start": "2026-08-10T13:00:00Z",
            "window_end": "2026-08-10T09:00:00Z",
        },
        ADMIN,
    )
    error = validate_error(response, "ERR_RATING_ARTIFACT_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_VALIDATION", (
        "path existence is step three and must pre-empt step-six body schema checking"
    )

    visits, meta = validate_paginated(api.list_observation_visits(ADMIN))
    assert len(visits) == 0, f"no visit may have been created, got {visits}"
    assert meta["total_count"] == 0


def test_lapsed_lead_observer_is_refused_on_reliability_not_on_schedule_conflict(api):
    """PRD §3.4: "Two safety rules then apply, in order. The reliability rule requires that
    every observer named on the visit be in `RELIABLE` standing with a
    `reliability_certified_until` date on or after the calendar date of `window_start`; a
    `LAPSED`, `RETIRED`, or `PROVISIONAL` observer, or one whose certification ends before
    the visit begins, is refused with `ERR_OBSERVER_NOT_RELIABLE` and HTTP 422."
    PRD §3.4: "The occupation rule is then checked independently for the lead observer and
    for the secondary observer."
    PRD §3.4: "A violation of either the overlap test or the same-provider buffer is
    `ERR_OBSERVER_SCHEDULE_CONFLICT` with HTTP 409."
    PRD §2.7: "After this eleven-step ladder, the domain-specific rules run: the
    observation-safety family, then the referential family, then the temporal family, then
    the business-constraint family, then the fiscal family, in that order."

    Design: Difficulty/priority_pair_validation_conflict/observer_reliability_beats_schedule_conflict
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_domains(EQUAL_WEIGHT_DOMAINS)
    observer = create_reliable_observer("Obs Alpha", anchor_agreement_pct=92.00,
                                        certified_until="2027-06-30")

    # Provider B books the observer for 09:00..17:00 on 2026-08-10.
    _provider_b, cycle_b = _docs_verified_cycle("Provider B Center", "C002")
    visit_b = schedule_visit(
        cycle_b["id"], observer["id"], "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z"
    )
    assert visit_b["status"] == "SCHEDULED"

    # Provider A is ready to schedule, so the cycle-state check cannot fire.
    _provider_a, cycle_a = _docs_verified_cycle("Provider A Center", "C001")

    # The observer lapses only after visit B was booked, so visit B stays in the
    # occupation candidate set while the reliability rule now also fails.
    validate_success(api.certify_observer(observer["id"], {"decision": "LAPSE"}, ADMIN))
    lapsed, _meta = validate_paginated(api.list_observers(ADMIN, params={"status": "LAPSED"}))
    assert [row["id"] for row in lapsed] == [observer["id"]]

    response = api.create_observation_visit(
        cycle_a["id"],
        {
            "lead_observer_id": observer["id"],
            "window_start": "2026-08-10T13:00:00Z",
            "window_end": "2026-08-10T21:00:00Z",
        },
        ADMIN,
    )
    error = validate_error(response, "ERR_OBSERVER_NOT_RELIABLE", 422)
    assert error["error_id"] != "ERR_OBSERVER_SCHEDULE_CONFLICT", (
        "the observation-safety family runs before the temporal family, so the lapsed "
        "observer must be reported rather than the overlapping window"
    )

    cycle_a_now = validate_success(api.get_rating_cycle(cycle_a["id"], ADMIN))
    assert cycle_a_now["status"] == "DOCS_VERIFIED"
    visits, _meta = validate_paginated(
        api.list_observation_visits(ADMIN, params={"rating_cycle_id": cycle_a["id"]})
    )
    assert len(visits) == 0, f"no visit may have been created for cycle A, got {visits}"

    # The temporal conflict really was live: restoring reliability lets the request
    # reach the occupation rule, which then rejects the same overlapping window.
    validate_success(
        api.certify_observer(
            observer["id"],
            {"decision": "CERTIFY", "anchor_agreement_pct": 92.00,
             "certified_until": "2027-06-30"},
            ADMIN,
        )
    )
    conflict = api.create_observation_visit(
        cycle_a["id"],
        {
            "lead_observer_id": observer["id"],
            "window_start": "2026-08-10T13:00:00Z",
            "window_end": "2026-08-10T21:00:00Z",
        },
        ADMIN,
    )
    validate_error(conflict, "ERR_OBSERVER_SCHEDULE_CONFLICT", 409)


def test_expenditure_against_an_offered_grant_reports_state_not_funds_exhausted(api):
    """PRD §3.8: "Six checks apply, in this order: the stale-version comparison described in
    §2.5, yielding `ERR_STALE_VERSION`; the grant's disbursement state, which must be `OPEN`
    and otherwise yields `ERR_GRANT_NOT_OPEN` with HTTP 409; the compliance hold, which
    refuses submission with `ERR_GRANT_COMPLIANCE_HOLD` and HTTP 409 while the compliance
    dimension sits at `FINDING_ISSUED`, since a finding must be remediated first; the spend
    deadline, which requires the `invoice_date` to be on or before the `spend_deadline` and
    the logical clock date likewise to be on or before it at submission time, and otherwise
    yields `ERR_GRANT_SPEND_DEADLINE_PASSED` with HTTP 422; the category ceiling; and
    finally the grant balance."
    PRD §3.8: "The grant balance check requires `amount_cents` to be no greater than
    `available_cents`; a submission consuming exactly the remaining availability is accepted
    and leaves `available_cents` at 0, while a larger one is refused with
    `ERR_GRANT_FUNDS_EXHAUSTED` and HTTP 422."
    PRD §3.8: "The grant is created in `OFFERED` with `compliance_status` at `COMPLIANT`,
    with `committed_cents`, `reimbursed_cents`, `available_cents`, and
    `recovery_amount_cents` all at 0, and with an empty `category_spend_cents` map."

    Design: Difficulty/priority_pair_validation_conflict/grant_not_open_beats_funds_exhausted
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        domains=EQUAL_WEIGHT_DOMAINS,
        provider_overrides={
            "legal_name": "Grant Test Center",
            "county_code": "C001",
            "region_code": "URBAN",
            "licensed_capacity": 60,
            "active_staff_fte": 12.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        credentials=[],
        claimed=POINTS,
        verified=POINTS,
        raw_score=4.0,
    )
    cycle = ctx["cycle"]
    assert cycle["weighted_total"] == pytest.approx(37.00, abs=0.005), (
        f"weighted_total must be 37.00, got {cycle['weighted_total']}"
    )
    assert cycle["awarded_tier"] == 1, f"awarded_tier must be 1, got {cycle['awarded_tier']}"

    grant = offer_grant(ctx["provider"]["id"], cycle["id"], 1_000_000, "2027-06-30")
    assert grant["status"] == "OFFERED"
    assert grant["available_cents"] == 0
    assert grant["committed_cents"] == 0

    response = api.create_expenditure(
        grant["id"],
        {
            "category": "EQUIPMENT",
            "amount_cents": 50_000,
            "invoice_date": "2026-08-15",
            "expected_grant_version": grant["version"],
        },
        make_provider_headers(ctx["provider"]["id"]),
    )
    error = validate_error(response, "ERR_GRANT_NOT_OPEN", 409)
    assert error["error_id"] != "ERR_GRANT_FUNDS_EXHAUSTED", (
        "the disbursement-state check is the second of the six ordered checks and must "
        "pre-empt the grant balance check even though available_cents is 0"
    )
    assert error["error_id"] != "ERR_STALE_VERSION", (
        "expected_grant_version was current, so the stale-version check cannot fire"
    )

    after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert after["status"] == "OFFERED"
    assert after["available_cents"] == 0
    assert after["committed_cents"] == 0
    lines, meta = validate_paginated(
        api.list_grant_expenditures(ADMIN, params={"improvement_grant_id": grant["id"]})
    )
    assert len(lines) == 0, f"no expenditure line may exist, got {lines}"
    assert meta["total_count"] == 0
