"""Warranty lifecycle and the callback claim loop: prorated payout by defect
type (PEEL vs HOT_TIRE), the cyclic NEEDS_INFO<->SUBMITTED revision loop,
covered-defect enforcement, and coverage-window expiry.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success, validate_error,
    make_customer_headers, set_clock,
    setup_cured_project, setup_submitted_claim, file_claim,
)

AGENT = TEST_USERS["warranty_agent_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/warranty_peel_vs_hot_tire_payout_diverge
# ===========================================================================
def _approve_claim_credit(defect_type):
    """Cured METALLIC project (covered 827507), claim filed at 60 months elapsed,
    approved. Returns prorated_credit_cents."""
    # METALLIC HEAVY sqft600 crack30 PEAK estimate==final == 827507.
    h = setup_submitted_claim(
        defect_type=defect_type,
        family="METALLIC", sku="METALLIC", install_season="PEAK",
        crew_metallic=True, crew_capacity=1000,
        assessment_kwargs={
            "measured_sqft": 600, "oil_stain_pct": 100, "crack_density": 50,
            "crack_linear_ft": 30, "spalling": False, "moisture_pct": 0,
        },
        as_measured_sqft=600, as_measured_crack_ft=30,
        install_date="2026-05-10T09:00:00Z",
        # METALLIC vehicle_traffic_ok_at = install_end(17:00) + 96h = 05-14T17:00.
        cure_instant="2026-05-14T17:00:00Z",
        claim_instant="2031-05-14T17:00:00Z",   # 60 whole months later
    )
    assert h["warranty"]["covered_install_price_cents"] == 827507, (
        f"covered expected 827507, got {h['warranty']['covered_install_price_cents']}"
    )
    reviewed = validate_success(
        api_client.review_claim(h["claim"]["id"], {"action": "APPROVE"}, AGENT)
    )
    return reviewed["prorated_credit_cents"]


def test_peel_claim_full_prorated_payout():
    """PRD §3.7: "The defect factor is 1.00 for a `PEEL` claim - peel and
    delamination are treated as a full-coat failure and pay the full prorated
    amount".

    Design: Difficulty/dual_variant_calc/warranty_peel_vs_hot_tire_payout_diverge
    """
    credit = _approve_claim_credit("PEEL")
    assert credit == 551671, f"PEEL payout expected 551671 (factor 1.00, 60mo), got {credit}"


def test_hot_tire_claim_half_prorated_payout():
    """PRD §3.7: "and 0.50 for a `HOT_TIRE` claim, since a hot-tire lift is a
    localized cosmetic defect; for the same covered price and the same elapsed
    months a hot-tire claim therefore pays exactly half what a peel claim pays."

    Design: Difficulty/dual_variant_calc/warranty_peel_vs_hot_tire_payout_diverge
    """
    credit = _approve_claim_credit("HOT_TIRE")
    assert credit == 275836, f"HOT_TIRE payout expected 275836 (factor 0.50, 60mo), got {credit}"


# ===========================================================================
# Difficulty/non_linear_state_machine/warranty_claim_cyclic_revision_loop
# ===========================================================================
def test_claim_revision_rounds_increment_per_resubmit_loop():
    """PRD §3.7: "The homeowner then **resubmits**, moving the claim from
    `NEEDS_INFO` back to `SUBMITTED` and incrementing `revision_rounds` by 1 to
    count the callback round - this `NEEDS_INFO -> SUBMITTED` loop may repeat as
    many times as the back-and-forth requires."

    Design: Difficulty/non_linear_state_machine/warranty_claim_cyclic_revision_loop
    """
    h = setup_submitted_claim(defect_type="PEEL")
    cust_headers = make_customer_headers(h["customer"]["id"])
    claim_id = h["claim"]["id"]
    # loop 1
    validate_success(api_client.review_claim(claim_id, {"action": "REQUEST_INFO"}, AGENT))
    validate_success(api_client.resubmit_claim(claim_id, cust_headers))
    # loop 2
    validate_success(api_client.review_claim(claim_id, {"action": "REQUEST_INFO"}, AGENT))
    final = validate_success(api_client.resubmit_claim(claim_id, cust_headers))
    assert final["revision_rounds"] == 2, f"expected 2 loops, got {final['revision_rounds']}"
    assert final["status"] == "SUBMITTED", f"expected SUBMITTED after resubmit, got {final['status']}"


def test_claim_approvable_after_revision_loops():
    """PRD §3.7: "Approving a `SUBMITTED` claim moves it to `APPROVED`".

    Design: Difficulty/non_linear_state_machine/warranty_claim_cyclic_revision_loop
    """
    h = setup_submitted_claim(defect_type="PEEL")
    cust_headers = make_customer_headers(h["customer"]["id"])
    claim_id = h["claim"]["id"]
    validate_success(api_client.review_claim(claim_id, {"action": "REQUEST_INFO"}, AGENT))
    validate_success(api_client.resubmit_claim(claim_id, cust_headers))
    validate_success(api_client.review_claim(claim_id, {"action": "REQUEST_INFO"}, AGENT))
    validate_success(api_client.resubmit_claim(claim_id, cust_headers))
    approved = validate_success(api_client.review_claim(claim_id, {"action": "APPROVE"}, AGENT))
    assert approved["status"] == "APPROVED", f"expected APPROVED after loops, got {approved['status']}"


# ===========================================================================
# Corner/state_machines/approve_other_defect_not_covered
# ===========================================================================
def test_approve_other_defect_rejected():
    """PRD §3.7: "an `OTHER` defect cannot be approved for payout and an approval
    attempt on one is rejected with `ERR_DEFECT_NOT_COVERED`."

    Design: Corner/state_machines/approve_other_defect_not_covered
    """
    h = setup_submitted_claim(defect_type="OTHER")
    resp = api_client.review_claim(h["claim"]["id"], {"action": "APPROVE"}, AGENT)
    validate_error(resp, "ERR_DEFECT_NOT_COVERED")


# ===========================================================================
# Corner/state_machines/claim_after_coverage_expired_rejected
# ===========================================================================
def test_claim_after_coverage_expired_rejected():
    """PRD §3.7: "Filing is allowed only while the warranty is `ACTIVE` and the
    logical clock is still within the coverage window - that is, the current
    instant is strictly before `coverage_start_at` plus `term_months`; a claim
    filed after coverage has lapsed is rejected with `ERR_COVERAGE_EXPIRED`."

    Design: Corner/state_machines/claim_after_coverage_expired_rejected
    """
    # FLAKE cure at 2026-05-13T17:00; advance 181 months past coverage start.
    h = setup_cured_project(
        install_date="2026-05-10T09:00:00Z", cure_instant="2026-05-13T17:00:00Z"
    )
    set_clock("2041-06-13T17:00:00Z")  # 181 months > 180 term
    resp = api_client.create_claim(
        h["warranty"]["id"], {"defect_type": "PEEL"},
        make_customer_headers(h["customer"]["id"]),
    )
    validate_error(resp, "ERR_COVERAGE_EXPIRED")
