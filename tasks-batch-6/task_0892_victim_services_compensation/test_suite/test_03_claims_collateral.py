"""Claim filing, assessment variants, collateral offset, and overlap rules
(PRD §2.9, §3.3, §3.4, §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_claim,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
INTAKE = TEST_USERS["intake_counselor_headers"]
ADJ = TEST_USERS["adjudicator_headers"]


# --------------------------------------------------------------------------
# Corner — claim create validation & not-found
# --------------------------------------------------------------------------
def test_create_claim_invalid_enum_category_returns_validation(api):
    """PRD §3.3: "each naming the owning `case_id` and a benefit `category` — one of
    `MEDICAL`, `LOST_WAGE`, `FUNERAL`, or `MENTAL_HEALTH`."
    PRD §2.9: "then the remaining business constraints, and finally field-level shape
    validation (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/create_claim_invalid_enum_category_returns_validation
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    resp = api.create_claim(
        {"case_id": case["id"], "category": "DENTAL", "claimed_amount_cents": 100000}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_claim_nonexistent_case_returns_not_found(api):
    """PRD §2.9: "the existence of any foreign-key references carried in the body; an
    unresolved reference yields the resource-specific not-found error (for example ...
    `ERR_CASE_NOT_FOUND` ... each HTTP 404)."

    Design: Corner/entities/create_claim_nonexistent_case_returns_not_found
    """
    resp = api.create_claim(
        {"case_id": NON_EXISTENT_UUID, "category": "MEDICAL", "claimed_amount_cents": 100000}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value)


def test_claim_submit_twice_returns_invalid_state(api):
    """PRD §2.9: "Every state-changing operation on an existing resource is a
    transition request that carries a `to_status` naming the target state; a
    `to_status` that is not reachable from the resource's current state is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/claim_submit_twice_returns_invalid_state
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=500000)
    fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    resp = api.transition_claim(claim["id"], {"to_status": "SUBMITTED"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_claims_by_case_paginated(api):
    """PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object, where `total_count` is the count of records
    matching the query before pagination and `has_more` indicates whether records
    remain beyond the current page."

    Design: Corner/endpoints/list_claims_by_case_paginated
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    for amt in (100000, 200000, 300000):
        fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=amt)
    resp = api.list_claims(ADJ, params={"case_id": case["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


# --------------------------------------------------------------------------
# Corner — collateral terminal-state lockdown
# --------------------------------------------------------------------------
def test_collateral_confirm_after_waived_returns_invalid_state(api):
    """PRD §3.4: "Both `CONFIRMED` and `WAIVED` are terminal states for a collateral
    source."
    PRD §2.9: "a `to_status` that is not reachable from the resource's current state
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/collateral_confirm_after_waived_returns_invalid_state
    """
    program = fx.make_program(api)
    case = fx.make_case(api, program["id"])
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=500000)
    cs = fx.make_collateral_source(api, claim["id"], source_type="AUTO_INSURANCE", amount_cents=100000)
    fx.collateral_transition(api, cs["id"], "WAIVED")
    resp = api.transition_collateral_source(cs["id"], {"to_status": "CONFIRMED"}, ADJ)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Difficulty — dual_variant_calc: provisional vs final net on the Claim
# --------------------------------------------------------------------------
def _medical_claim_with_two_collateral(api):
    """Eligible case; MEDICAL claim claimed=2,000,000; two DECLARED collateral
    sources (s1 HEALTH_INSURANCE 500,000, s2 EMPLOYER_BENEFIT 300,000); claim SUBMITTED.
    Returns (case, claim, submitted_claim, cs1, cs2)."""
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=2000000)
    cs1 = fx.make_collateral_source(api, claim["id"], source_type="HEALTH_INSURANCE", amount_cents=500000)
    cs2 = fx.make_collateral_source(api, claim["id"], source_type="EMPLOYER_BENEFIT", amount_cents=300000)
    submitted = fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    return case, claim, submitted, cs1, cs2


def test_claim_provisional_net_counts_declared_and_confirmed(api):
    """PRD §3.3: "The **collateral offset** (`collateral_offset_cents`) is the sum of
    `amount_cents` over the claim's collateral sources whose status is counted for the
    current variant; at submission time (the provisional variant) both `DECLARED` and
    `CONFIRMED` collateral sources are counted. The **net claim** (`net_claim_cents`)
    is the assessed base minus that offset, floored at 0 so it can never go negative."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_net
    """
    _, _, submitted, _, _ = _medical_claim_with_two_collateral(api)
    assert submitted["collateral_offset_cents"] == 800000
    assert submitted["net_claim_cents"] == 1200000


def test_claim_final_net_counts_confirmed_only(api):
    """PRD §3.5: "The collateral offset is likewise recomputed, but under the final
    variant **only** `CONFIRMED` collateral sources are counted — `DECLARED` and
    `WAIVED` sources are excluded — and the net claim is again the assessed base minus
    that offset, floored at 0."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_net
    """
    _, claim, _, cs1, cs2 = _medical_claim_with_two_collateral(api)
    fx.claim_transition(api, claim["id"], "UNDER_REVIEW")
    fx.collateral_transition(api, cs1["id"], "CONFIRMED")
    fx.collateral_transition(api, cs2["id"], "WAIVED")
    approved = fx.claim_transition(api, claim["id"], "APPROVED", verified_amount_cents=2000000)
    assert approved["collateral_offset_cents"] == 500000
    assert approved["net_claim_cents"] == 1500000


# --------------------------------------------------------------------------
# Difficulty — combinatorial_formula: lost-wage round-per-week then multiply
# --------------------------------------------------------------------------
def _submitted_lost_wage_claim(api):
    """Eligible case; LOST_WAGE claim weekly_wage=100,001, num_weeks=3,
    period [2026-01-01,2026-01-22); SUBMITTED. Returns submitted claim."""
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program, crime_type="DUI")
    claim = fx.make_claim(api, case["id"], "LOST_WAGE",
                          weekly_wage_cents=100001, num_weeks=3,
                          disability_start_date="2026-01-01", disability_end_date="2026-01-22")
    return fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")


def test_lost_wage_assessed_base_rounds_per_week_then_multiplies(api):
    """PRD §3.3: "the weekly benefit equals the gross weekly wage multiplied by the
    wage-replacement rate of 0.6667, capped at a weekly maximum of 120000 cents (that
    is, $1,200.00 per week), and this weekly benefit is rounded to a whole number of
    cents using round-half-up **before** it is multiplied by the number of weeks —
    rounding per week and then multiplying, never the reverse."

    Design: Difficulty/combinatorial_formula/lost_wage_round_per_week_then_multiply
    """
    submitted = _submitted_lost_wage_claim(api)
    # round_half_up(100001 * 0.6667) = 66671; 66671 * 3 = 200013.
    assert submitted["assessed_base_cents"] == 200013


def test_lost_wage_provisional_net_equals_base_without_collateral(api):
    """PRD §3.3: "The **net claim** (`net_claim_cents`) is the assessed base minus
    that offset, floored at 0 so it can never go negative."

    Design: Difficulty/combinatorial_formula/lost_wage_round_per_week_then_multiply
    """
    submitted = _submitted_lost_wage_claim(api)
    assert submitted["net_claim_cents"] == 200013


# --------------------------------------------------------------------------
# Difficulty — resource_temporal_overlap: LOST_WAGE half-open periods
# --------------------------------------------------------------------------
def test_adjacent_wage_periods_accepted(api):
    """PRD §3.3: "overlap is judged on the half-open interval, so two periods that
    merely touch at an endpoint (one ending exactly where the next begins) do not
    overlap, whereas any shared interior instant does."

    Design: Difficulty/resource_temporal_overlap/lost_wage_half_open_periods_adjacent_ok_overlap_rejected
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program, crime_type="DUI")
    claim1 = fx.make_claim(api, case["id"], "LOST_WAGE", weekly_wage_cents=100000, num_weeks=4,
                           disability_start_date="2026-01-01", disability_end_date="2026-02-01")
    fx.claim_transition(api, claim1["id"], "SUBMITTED", role="IntakeCounselor")
    claim2 = fx.make_claim(api, case["id"], "LOST_WAGE", weekly_wage_cents=100000, num_weeks=4,
                           disability_start_date="2026-02-01", disability_end_date="2026-03-01")
    submitted2 = fx.claim_transition(api, claim2["id"], "SUBMITTED", role="IntakeCounselor")
    assert submitted2["status"] == "SUBMITTED"


def test_overlapping_wage_period_rejected(api):
    """PRD §3.3: "For a lost-wage claim, the system additionally checks that its
    disability period does not overlap any other non-`DENIED` lost-wage claim on the
    same case ... An overlap is rejected with `ERR_WAGE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lost_wage_half_open_periods_adjacent_ok_overlap_rejected
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program, crime_type="DUI")
    claim1 = fx.make_claim(api, case["id"], "LOST_WAGE", weekly_wage_cents=100000, num_weeks=4,
                           disability_start_date="2026-01-01", disability_end_date="2026-02-01")
    fx.claim_transition(api, claim1["id"], "SUBMITTED", role="IntakeCounselor")
    claim3 = fx.make_claim(api, case["id"], "LOST_WAGE", weekly_wage_cents=100000, num_weeks=4,
                           disability_start_date="2026-01-15", disability_end_date="2026-02-15")
    resp = api.transition_claim(claim3["id"], {"to_status": "SUBMITTED"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_WAGE_PERIOD_OVERLAP.value)


# --------------------------------------------------------------------------
# Difficulty — resource_temporal_overlap: collateral CLOSED periods
# --------------------------------------------------------------------------
def test_touching_collateral_endpoints_rejected(api):
    """PRD §3.4: "Confirming a source (`DECLARED → CONFIRMED`) is permitted only when
    no other already-`CONFIRMED` collateral source of the **same** `source_type` on
    the same claim has a closed coverage interval that overlaps this one; because both
    intervals are closed, sources that share even a single boundary date are considered
    overlapping. A conflicting confirmation is rejected with
    `ERR_COLLATERAL_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/collateral_closed_periods_touching_endpoint_rejected
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1000000)
    cs1 = fx.make_collateral_source(api, claim["id"], source_type="HEALTH_INSURANCE",
                                    amount_cents=200000,
                                    coverage_start_date="2026-01-01", coverage_end_date="2026-02-01")
    fx.collateral_transition(api, cs1["id"], "CONFIRMED")
    cs2 = fx.make_collateral_source(api, claim["id"], source_type="HEALTH_INSURANCE",
                                    amount_cents=150000,
                                    coverage_start_date="2026-02-01", coverage_end_date="2026-03-01")
    resp = api.transition_collateral_source(cs2["id"], {"to_status": "CONFIRMED"}, ADJ)
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_PERIOD_OVERLAP.value)


def test_disjoint_collateral_periods_confirm_succeeds(api):
    """PRD §3.4: "Confirming a source (`DECLARED → CONFIRMED`) is permitted only when
    no other already-`CONFIRMED` collateral source of the **same** `source_type` on
    the same claim has a closed coverage interval that overlaps this one ..."

    Design: Difficulty/resource_temporal_overlap/collateral_closed_periods_touching_endpoint_rejected
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1000000)
    cs1 = fx.make_collateral_source(api, claim["id"], source_type="HEALTH_INSURANCE",
                                    amount_cents=200000,
                                    coverage_start_date="2026-01-01", coverage_end_date="2026-01-31")
    fx.collateral_transition(api, cs1["id"], "CONFIRMED")
    cs2 = fx.make_collateral_source(api, claim["id"], source_type="HEALTH_INSURANCE",
                                    amount_cents=150000,
                                    coverage_start_date="2026-02-01", coverage_end_date="2026-02-28")
    confirmed = validate_success(api.transition_collateral_source(cs2["id"], {"to_status": "CONFIRMED"}, ADJ))
    assert confirmed["status"] == "CONFIRMED"


# --------------------------------------------------------------------------
# Difficulty — cross_entity_state_dependency: claim approve requires ELIGIBLE case
# --------------------------------------------------------------------------
def test_claim_approve_blocked_when_case_not_eligible(api):
    """PRD §3.5: "Approving a claim (`UNDER_REVIEW → APPROVED`) requires that the
    parent `VictimCase` be in `status` `ELIGIBLE`; if the case is not eligible, the
    approval is rejected with `ERR_CASE_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_case_eligible
    """
    program = fx.make_program(api)
    _, case = fx.make_under_review_case(api, program=program)  # never determined ELIGIBLE
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=500000)
    fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    fx.claim_transition(api, claim["id"], "UNDER_REVIEW")
    resp = api.transition_claim(claim["id"], {"to_status": "APPROVED", "verified_amount_cents": 500000}, ADJ)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ELIGIBLE.value)


def test_claim_approve_succeeds_when_case_eligible(api):
    """PRD §3.5: "Approving a claim (`UNDER_REVIEW → APPROVED`) requires that the
    parent `VictimCase` be in `status` `ELIGIBLE`; if the case is not eligible, the
    approval is rejected with `ERR_CASE_NOT_ELIGIBLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_case_eligible
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=500000)
    fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    fx.claim_transition(api, claim["id"], "UNDER_REVIEW")
    approved = validate_success(
        api.transition_claim(claim["id"], {"to_status": "APPROVED", "verified_amount_cents": 500000}, ADJ)
    )
    assert_claim(approved)
    assert approved["status"] == "APPROVED"
