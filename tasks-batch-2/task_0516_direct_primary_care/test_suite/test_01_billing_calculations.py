"""Billing calculations: the insurance-vs-DPC invoice split and the member's
monthly share (individual / annual / sponsored). PRD §3.7, §3.8.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_completed_visit, setup_active_member, setup_sponsored_active_member,
    make_provider_headers, make_member_headers,
    complete_visit_payload, ADMIN,
)

# Service lines used by the dual-variant invoice tests:
# OFFICE_VISIT (DPC-covered) 1x12000, XRAY 1x9000, LAB_SPECIAL 2x2500.
# gross = 12000 + 9000 + 5000 = 26000 ; non-DPC = 9000 + 5000 = 14000.
DUAL_LINES = [
    {"service_code": "OFFICE_VISIT", "units": 1, "unit_charge_cents": 12000},
    {"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000},
    {"service_code": "LAB_SPECIAL", "units": 2, "unit_charge_cents": 2500},
]


def _invoice(ctx):
    prov_h = make_provider_headers(ctx["provider"]["id"])
    return validate_success(api_client.invoice_visit(ctx["visit"]["id"], prov_h), 201)


def test_invoice_split_cash_member_owes_full_non_dpc(api):
    """PRD §3.7: "When the member is not insured (the cash/DPC variant),
    `insurance_billed_cents` is zero and the member's `member_responsibility_cents`
    is the full non-DPC charge at full price."
    PRD §3.7: "The gross charge, `gross_charge_cents`, is the sum over all service
    lines of that line's `units` multiplied by its `unit_charge_cents`."

    Design: Difficulty/dual_variant_calc/invoice_split_cash_vs_insurance_diverge
    """
    ctx = setup_completed_visit(
        DUAL_LINES, member_overrides={"has_insurance": False},
        practice_overrides={"dpc_covered_service_codes": ["OFFICE_VISIT"],
                            "insurance_coinsurance_pct": 0.20})
    inv = _invoice(ctx)
    assert inv["gross_charge_cents"] == 26000
    assert inv["member_responsibility_cents"] == 14000
    assert inv["insurance_billed_cents"] == 0


def test_invoice_split_insured_member_owes_coinsurance_only(api):
    """PRD §3.7: "When the member is insured (the coinsurance variant), the non-DPC
    charge is routed to insurance — `insurance_billed_cents` equals the non-DPC
    portion — and the member owes only coinsurance on it: the non-DPC lines are
    first summed into the non-DPC total, then that single aggregate total is
    multiplied by the practice's `insurance_coinsurance_pct`, and that product is
    rounded half up exactly once to a whole number of cents to yield
    `member_responsibility_cents`. The rounding is applied once on the aggregated
    non-DPC total, never per line, so for the same `service_lines` the insured
    member's responsibility is strictly smaller than the uninsured member's."

    Design: Difficulty/dual_variant_calc/invoice_split_cash_vs_insurance_diverge
    """
    ctx = setup_completed_visit(
        DUAL_LINES, member_overrides={"has_insurance": True},
        practice_overrides={"dpc_covered_service_codes": ["OFFICE_VISIT"],
                            "insurance_coinsurance_pct": 0.20})
    inv = _invoice(ctx)
    # round_half_up(14000 * 0.20) = 2800
    assert inv["member_responsibility_cents"] == 2800
    assert inv["insurance_billed_cents"] == 14000


def test_member_share_monthly_individual_is_full_fee(api):
    """PRD §3.8: "For a `MONTHLY` plan, the period fee is simply the base fee,
    charged every 30-day period."
    PRD §3.8: "when there is no sponsoring seat, the member's share equals the
    full period fee."

    Design: Difficulty/dual_variant_calc/monthly_share_individual_vs_annual_sponsored_diverge
    """
    ctx = setup_active_member(
        member_overrides={"plan_type": "MONTHLY"},
        practice_overrides={"monthly_fee_cents": 15000, "annual_fee_discount_pct": 0.15})
    membership = get_success_data(api_client.get_membership(ctx["membership"]["id"], ADMIN))
    assert membership["member_share_cents"] == 15000


def test_member_share_annual_prepaid_sponsored_diverges(api):
    """PRD §3.8: "For an `ANNUAL_PREPAID` plan, the system first computes a
    discounted annual total by multiplying the base fee by twelve and then by one
    minus the practice's `annual_fee_discount_pct`, rounding that result half up to
    a whole number of cents; this discounted annual total is the period fee, charged
    once up front for the entire year."
    PRD §3.8: "when the membership has a non-null `employer_seat_id`, the employer's
    covered amount is the period fee multiplied by the employer's `sponsorship_pct`,
    rounded half up to whole cents, and the member's share is the period fee minus
    that covered amount; when there is no sponsoring seat, the member's share equals
    the full period fee."

    Design: Difficulty/dual_variant_calc/monthly_share_individual_vs_annual_sponsored_diverge
    """
    # annual_total = round(15000*12*(1-0.15)) = round(153000) = 153000.
    # employer_covers = round(153000*0.60) = 91800 ; member_share = 61200.
    ctx = setup_sponsored_active_member(sponsorship_pct=0.60, plan_type="ANNUAL_PREPAID")
    membership = get_success_data(api_client.get_membership(ctx["membership"]["id"], ADMIN))
    assert membership["member_share_cents"] == 61200


def test_invoice_coinsurance_sum_then_round_aggregate(api):
    """PRD §3.7: "the non-DPC lines are first summed into the non-DPC total, then
    that single aggregate total is multiplied by the practice's
    `insurance_coinsurance_pct`, and that product is rounded half up exactly once
    to a whole number of cents to yield `member_responsibility_cents`. The rounding
    is applied once on the aggregated non-DPC total, never per line, so for the same
    `service_lines` the insured member's responsibility is strictly smaller than the
    uninsured member's."

    Design: Difficulty/combinatorial_formula/invoice_coinsurance_sum_then_round_mode_b
    """
    # Three non-DPC lines of 4445 each -> non-DPC total 13335.
    # round_half_up(13335 * 0.20) = round(2667.0) = 2667.
    lines = [
        {"service_code": "LAB_A", "units": 1, "unit_charge_cents": 4445},
        {"service_code": "LAB_B", "units": 1, "unit_charge_cents": 4445},
        {"service_code": "LAB_C", "units": 1, "unit_charge_cents": 4445},
    ]
    ctx = setup_completed_visit(
        lines, member_overrides={"has_insurance": True},
        practice_overrides={"dpc_covered_service_codes": ["OFFICE_VISIT"],
                            "insurance_coinsurance_pct": 0.20})
    inv = _invoice(ctx)
    assert inv["gross_charge_cents"] == 13335
    assert inv["insurance_billed_cents"] == 13335
    assert inv["member_responsibility_cents"] == 2667


def test_invoice_coinsurance_billed_equals_non_dpc_total(api):
    """PRD §3.7: "When the member is insured (the coinsurance variant), the non-DPC
    charge is routed to insurance — `insurance_billed_cents` equals the non-DPC
    portion — and the member owes only coinsurance on it."
    PRD §3.7: "The non-DPC portion is the gross charge minus the DPC-covered
    portion."

    Design: Difficulty/combinatorial_formula/invoice_coinsurance_sum_then_round_mode_b
    """
    # Three non-DPC lines of 4445 each -> non-DPC total 13335; all lines are non-DPC
    # so gross == insurance_billed == 13335.
    lines = [
        {"service_code": "LAB_A", "units": 1, "unit_charge_cents": 4445},
        {"service_code": "LAB_B", "units": 1, "unit_charge_cents": 4445},
        {"service_code": "LAB_C", "units": 1, "unit_charge_cents": 4445},
    ]
    ctx = setup_completed_visit(
        lines, member_overrides={"has_insurance": True},
        practice_overrides={"dpc_covered_service_codes": ["OFFICE_VISIT"],
                            "insurance_coinsurance_pct": 0.20})
    inv = _invoice(ctx)
    assert inv["gross_charge_cents"] == 13335
    assert inv["insurance_billed_cents"] == 13335


def test_member_share_annual_discount_applied_before_sponsorship(api):
    """PRD §3.8: "The named rounding steps — the discounted annual total, then the
    employer's covered amount — are each applied half up in that order; for a
    sponsored annual plan the discount is applied (and rounded) before sponsorship
    is applied (and rounded)."

    Design: Difficulty/combinatorial_formula/annual_sponsored_discount_before_sponsorship_mode_c
    """
    # annual_total = round(15000*12*0.85) = 153000 ; employer_covers = round(153000*0.60) = 91800.
    # member_share = 153000 - 91800 = 61200. Sponsorship-before-discount would differ.
    ctx = setup_sponsored_active_member(sponsorship_pct=0.60, plan_type="ANNUAL_PREPAID")
    membership = get_success_data(api_client.get_membership(ctx["membership"]["id"], ADMIN))
    assert membership["member_share_cents"] == 61200


def test_member_share_annual_discounted_total_full_year(api):
    """PRD §3.8: "For an `ANNUAL_PREPAID` plan, the system first computes a
    discounted annual total by multiplying the base fee by twelve and then by one
    minus the practice's `annual_fee_discount_pct`, rounding that result half up to
    a whole number of cents; this discounted annual total is the period fee, charged
    once up front for the entire year."

    Design: Difficulty/combinatorial_formula/annual_sponsored_discount_before_sponsorship_mode_c
    """
    # Unsponsored ANNUAL_PREPAID: member_share == discounted annual total ==
    # round(15000*12*0.85) = 153000 (no employer reduction).
    ctx = setup_active_member(member_overrides={"plan_type": "ANNUAL_PREPAID"},
                              practice_overrides={"monthly_fee_cents": 15000,
                                                  "annual_fee_discount_pct": 0.15})
    membership = get_success_data(api_client.get_membership(ctx["membership"]["id"], ADMIN))
    assert membership["member_share_cents"] == 153000
