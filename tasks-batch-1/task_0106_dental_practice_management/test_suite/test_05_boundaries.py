"""Numeric and calendar-month boundary precision (>= edges).

Difficulty queue A: boundary_precision_check instances.
"""
from test_helpers import (
    setup_practice,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    create_claim,
    attach_and_submit,
    adjudicate_claim,
    setup_adjudicated_claim,
    set_clock,
    validate_success,
    get_success_data,
    TEST_USERS,
)
from test_helpers import api_client

BILL = TEST_USERS["billing_headers"]


# ─── boundary_precision_check / annual_max_reached_at_exactly_max_uses_ge ──────

def test_annual_max_reached_trips_at_exactly_max():
    """PRD §3.8: "The coverage's `annual_max_reached` is true exactly when that sum
    has reached or exceeded the plan's `annual_maximum_cents`; reaching the maximum
    exactly trips it."

    A BASIC claim fee=130000 adjudicates to carrier_paid exactly 100000 == the max,
    so annual_benefit_used == 100000 and annual_max_reached == true (>= boundary).

    Design: Difficulty/boundary_precision_check/annual_max_reached_at_exactly_max_uses_ge
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 130_000, category="BASIC", cdt_code="D2395",
                                       tooth_number=18, document_ref="ref://x5",
                                       attachment_type="XRAY")
    assert claim["carrier_paid_cents"] == 100000
    cov = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov["annual_benefit_used_cents"] == 100000
    assert cov["annual_max_reached"] is True


def test_annual_max_not_reached_just_below_max():
    """PRD §3.8: "The coverage's `annual_max_reached` is true exactly when that sum
    has reached or exceeded the plan's `annual_maximum_cents`".

    The X-1 side of the boundary: a BASIC claim paying 36000 (well under the 100000
    max) leaves annual_benefit_used == 36000 and annual_max_reached == false.

    Design: Difficulty/boundary_precision_check/annual_max_reached_at_exactly_max_uses_ge
    """
    ctx = setup_practice()
    _, claim = setup_adjudicated_claim(ctx, 50_000, category="BASIC", cdt_code="D2393",
                                       tooth_number=20, document_ref="ref://x5b",
                                       attachment_type="XRAY")
    # gross = floor((50000-5000)*80/100) = 36000; under max.
    assert claim["carrier_paid_cents"] == 36000
    cov = validate_success(api_client.get_patient_coverage(ctx["coverage"]["id"], BILL))
    assert cov["annual_benefit_used_cents"] == 36000
    assert cov["annual_max_reached"] is False


# ─── boundary_precision_check / waiting_period_met_at_exactly_twelve_months ────

def test_major_waiting_period_met_at_exactly_twelve_months():
    """PRD §3.5: "the procedure is eligible only if the number of whole months
    between the coverage's `coverage_start_date` and the current date is at least
    the plan's `major_waiting_period_months`".
    PRD §3.5: "In both gates, reaching exactly the threshold counts as eligible."

    Coverage start 2025-01-01, waiting=12; clock 2026-01-01 => exactly 12 whole
    months, so the MAJOR predetermination is created (PENDING, no
    ERR_WAITING_PERIOD_NOT_MET) and snapshots the 90000 fee.

    Design: Difficulty/boundary_precision_check/waiting_period_met_at_exactly_twelve_months_uses_ge
    """
    ctx = setup_practice(
        plan_overrides={"major_waiting_period_months": 12, "frequency_limit_months": 6},
        coverage_overrides={"coverage_start_date": "2025-01-01"},
    )
    patient, provider, coverage = ctx["patient"], ctx["provider"], ctx["coverage"]
    clin = ctx["clinician_headers"]
    set_clock("2026-01-01T00:00:00Z")
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8}, clin))
    pred = get_success_data(api_client.create_predetermination(
        {"treatment_plan_item_id": item["id"], "patient_coverage_id": coverage["id"]}, BILL))
    assert pred["status"] == "PENDING"
    assert pred["submitted_fee_cents"] == 90000


def test_major_waiting_period_not_met_just_below_twelve_months():
    """PRD §3.5: "the procedure is eligible only if the number of whole months
    between the coverage's `coverage_start_date` and the current date is at least
    the plan's `major_waiting_period_months`".
    PRD §3.5: "If either gate fails, the request is rejected with
    `ERR_WAITING_PERIOD_NOT_MET`."

    The X-1 side: at 11 whole months of coverage (clock 2025-12-01) the MAJOR
    waiting gate fails, rejecting the predetermination with
    ERR_WAITING_PERIOD_NOT_MET.

    Design: Difficulty/boundary_precision_check/waiting_period_met_at_exactly_twelve_months_uses_ge
    """
    from test_helpers import validate_error, ApiErrorId
    ctx = setup_practice(
        plan_overrides={"major_waiting_period_months": 12, "frequency_limit_months": 6},
        coverage_overrides={"coverage_start_date": "2025-01-01"},
    )
    patient, provider, coverage = ctx["patient"], ctx["provider"], ctx["coverage"]
    clin = ctx["clinician_headers"]
    set_clock("2025-12-01T00:00:00Z")
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8}, clin))
    resp = api_client.create_predetermination(
        {"treatment_plan_item_id": item["id"], "patient_coverage_id": coverage["id"]}, BILL)
    validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_NOT_MET.value)
