"""ISA monthly-obligation calculation, threshold boundary, cap-straddle clamp,
and the dual-view projection vs chronological-actual divergence.

Translates difficulty `combinatorial_formula`, `boundary_precision_check`,
`dual_variant_calc` (ISA half) and corner `calculations` instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    create_income_report_payload,
    setup_graduated_isa,
    file_and_settle,
)

SERVICING = TEST_USERS["servicing_officer_headers"]


def test_monthly_payment_min_share_cap_with_threshold_branch():
    """PRD §3.8: "the system multiplies `gross_income_cents` by `income_share_pct` and rounds that product half-up to whole cents (the multiply happens first and the share fraction is never rounded on its own), then clamps the result to the contract's current `remaining_cap_cents` so the obligation is the smaller of the rounded share and the remaining cap."
    PRD §3.8: "When the computed `obligation_cents` is greater than zero, the report spawns a **Payment** in `PENDING` collection status, and the report's `payment_id` back-pointer is set to that payment; when the obligation is zero, no payment is created and `payment_id` stays null."

    Design: Difficulty/combinatorial_formula/monthly_payment_min_share_cap_with_threshold_branch
    """
    _, _, enrollment, isa = setup_graduated_isa(email="formula@example.com")
    # gross 600000 * 0.17 = 102000; remaining cap 3000000 -> obligation 102000.
    resp = api_client.create_income_report(
        create_income_report_payload(isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 600_000),
        SERVICING,
    )
    report = validate_success(resp, 201)
    assert report["obligation_cents"] == 102_000
    pay = get_success_data(api_client.get_payment(report["payment_id"], SERVICING))
    assert pay["amount_cents"] == 102_000
    assert pay["collection_status"] == "PENDING"


def test_monthly_payment_multiply_then_round_half_up():
    """PRD §3.8: "the system multiplies `gross_income_cents` by `income_share_pct` and rounds that product half-up to whole cents (the multiply happens first and the share fraction is never rounded on its own), then clamps the result to the contract's current `remaining_cap_cents` so the obligation is the smaller of the rounded share and the remaining cap."
    PRD §2.7: "the result is rounded to the nearest whole cent using the round-half-up rule (a value exactly halfway between two cents rounds up to the larger)."

    Design: Difficulty/combinatorial_formula/monthly_payment_min_share_cap_with_threshold_branch
    """
    _, _, enrollment, isa = setup_graduated_isa(email="roundup@example.com")
    # gross 400050 * 0.17 = 68008.50 cents -> round_half_up -> 68009.
    resp = api_client.create_income_report(
        create_income_report_payload(isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 400_050),
        SERVICING,
    )
    report = validate_success(resp, 201)
    assert report["obligation_cents"] == 68_009, "68008.50 rounds half-up to 68009"


def test_income_at_threshold_yields_zero_obligation():
    """PRD §3.8: "if the reported `gross_income_cents` is at or below the contract's `income_threshold_cents`, the obligation is zero; the floor is inclusive, so income exactly equal to the threshold owes nothing."
    PRD §3.8: "when the obligation is zero, no payment is created and `payment_id` stays null."

    Design: Difficulty/boundary_precision_check/income_at_threshold_yields_zero_obligation
    """
    _, _, enrollment, isa = setup_graduated_isa(email="threshold@example.com")
    # threshold is 400000; file exactly at threshold.
    resp = api_client.create_income_report(
        create_income_report_payload(isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 400_000),
        SERVICING,
    )
    report = validate_success(resp, 201)
    assert report["obligation_cents"] == 0, "income == threshold uses <= so obligation is 0"
    assert report.get("payment_id") is None, "no payment created when obligation is 0"


def test_income_just_above_threshold_yields_positive_obligation():
    """PRD §3.8: "if the reported `gross_income_cents` is at or below the contract's `income_threshold_cents`, the obligation is zero; the floor is inclusive, so income exactly equal to the threshold owes nothing."
    PRD §3.8: "the system multiplies `gross_income_cents` by `income_share_pct` and rounds that product half-up to whole cents (the multiply happens first and the share fraction is never rounded on its own), then clamps the result to the contract's current `remaining_cap_cents` so the obligation is the smaller of the rounded share and the remaining cap."

    Design: Difficulty/boundary_precision_check/income_at_threshold_yields_zero_obligation
    """
    _, _, enrollment, isa = setup_graduated_isa(email="abovethresh@example.com")
    # gross 500000 (> 400000 threshold) * 0.17 = 85000.
    resp = api_client.create_income_report(
        create_income_report_payload(isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 500_000),
        SERVICING,
    )
    report = validate_success(resp, 201)
    assert report["obligation_cents"] == 85_000, "500000 * 0.17 = 85000"
    assert report["payment_id"], "a payment is spawned when obligation > 0"


def test_monthly_payment_cap_straddle_clamps_obligation():
    """PRD §3.8: "then clamps the result to the contract's current `remaining_cap_cents` so the obligation is the smaller of the rounded share and the remaining cap. This clamp guarantees `amount_paid_cents` can never overshoot `cap_cents`."

    Design: Corner/calculations/monthly_payment_cap_straddle_clamps_obligation
    """
    _, _, enrollment, isa = setup_graduated_isa(email="straddle@example.com")
    isa_id = isa["id"]
    # First settle 2950000 (gross 17352941 * 0.17 = 2950000.0) -> remaining_cap 50000.
    file_and_settle(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 17_352_941)
    mid = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert mid["remaining_cap_cents"] == 50_000
    # Now gross 600000 -> raw 102000, clamped to remaining 50000.
    resp = api_client.create_income_report(
        create_income_report_payload(isa_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 600_000),
        SERVICING,
    )
    report = validate_success(resp, 201)
    assert report["obligation_cents"] == 50_000, "obligation clamped to remaining cap"


def test_isa_projection_vs_chronological_actual_diverge():
    """PRD §3.11: "The forward-looking view is `projected_payoff_cents`, a computed estimate of the eventual total assuming the student's latest reported income repeats every remaining month."
    PRD §3.11: "The projection is then `amount_paid_cents` plus the per-month figure times the remaining months, with the whole sum capped at `cap_cents` — the projection is the smaller of `cap_cents` and that running total, so it can reach the cap early."

    Design: Difficulty/dual_variant_calc/isa_projection_vs_chronological_actual_diverge
    """
    _, _, enrollment, isa = setup_graduated_isa(email="project@example.com")
    isa_id = isa["id"]
    # Two 600000 reports, both settled -> amount_paid 204000, payments_made_count 2.
    file_and_settle(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 600_000)
    file_and_settle(isa_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 600_000)
    # per_month = 600000*0.17 = 102000; remaining months = 24 - 2 = 22.
    # projected = 204000 + 102000*22 = 2448000 (< cap 3000000).
    proj = validate_success(
        api_client.get_isa_projection(isa_id, SERVICING, params={"variant": "PROJECTED"}), 200
    )
    assert proj["amount_paid_cents"] == 204_000
    assert proj["projected_payoff_cents"] == 2_448_000
    assert proj["projected_payoff_cents"] != proj["amount_paid_cents"]


def test_isa_projection_at_least_chronological_actual():
    """PRD §3.11: "The projected figure is always at least the chronological `amount_paid_cents`."

    Design: Difficulty/dual_variant_calc/isa_projection_vs_chronological_actual_diverge
    """
    _, _, enrollment, isa = setup_graduated_isa(email="project2@example.com")
    isa_id = isa["id"]
    file_and_settle(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 600_000)
    file_and_settle(isa_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 600_000)
    data = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert data["projected_payoff_cents"] >= data["amount_paid_cents"]
    assert data["projected_payoff_cents"] == 2_448_000
