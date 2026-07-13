"""Warranty coverage variant selection (FULL vs PRORATED) and expiry rejection."""
from test_helpers import validate_success, validate_error
from test_helpers.fixtures import set_clock, new_intersection, new_device


# ── Difficulty: FULL vs PRORATED payout for same replacement_cost ────────────
def test_warranty_full_coverage_pays_full_replacement_cost(api, utility_coordinator_headers):
    """PRD §3.8: "If the age is at most 12 months, the claim's `coverage_variant`
    is `FULL` and the `payout_amount` is the device's full `replacement_cost`,
    rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/warranty_full_vs_prorated_payout
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="STREETLIGHT", criticality="LOW",
                        model="LEDX", installed_at="2025-03-01T00:00:00Z",
                        replacement_cost=1000.00)  # age 12 months -> FULL
    res = api.create_warranty_claim(
        {"device_id": device["id"], "defect_description": "LED flicker"},
        utility_coordinator_headers)
    claim = validate_success(res, 201)
    assert claim["coverage_variant"] == "FULL"
    assert claim["payout_amount"] == 1000.00


def test_warranty_prorated_coverage_depreciates_payout(api, utility_coordinator_headers):
    """PRD §3.8: "Otherwise — for an age greater than 12 months but not exceeding
    60 — the `coverage_variant` is `PRORATED` and the `payout_amount` is the
    straight-line depreciated value: the `replacement_cost` multiplied by the
    remaining term, that is by 60 minus the age in months, then divided by 60,
    rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/warranty_full_vs_prorated_payout
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="STREETLIGHT", criticality="LOW",
                        model="LEDX", installed_at="2023-09-01T00:00:00Z",
                        replacement_cost=1000.00)  # age 30 months -> PRORATED
    res = api.create_warranty_claim(
        {"device_id": device["id"], "defect_description": "LED flicker"},
        utility_coordinator_headers)
    claim = validate_success(res, 201)
    assert claim["coverage_variant"] == "PRORATED"
    # 1000 * (60 - 30) / 60 = 500.00
    assert claim["payout_amount"] == 500.00


# ── Corner: warranty age beyond term rejected ────────────────────────────────
def test_warranty_expired_rejected(api, utility_coordinator_headers):
    """PRD §3.8: "The age in whole calendar months is measured from the device's
    `installed_at` to the current clock. If that age exceeds 60 months the claim is
    refused with `ERR_WARRANTY_EXPIRED`, since the device is past its warranty
    term."

    Design: Corner/calculations/warranty_expired_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    inter = new_intersection()
    device = new_device(inter["id"], device_type="STREETLIGHT", criticality="LOW",
                        model="L9", installed_at="2019-01-01T00:00:00Z",
                        replacement_cost=1000.00)  # ~86 months old
    res = api.create_warranty_claim(
        {"device_id": device["id"], "defect_description": "old failure"},
        utility_coordinator_headers)
    validate_error(res, "ERR_WARRANTY_EXPIRED", expected_status=409)
