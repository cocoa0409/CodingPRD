"""Dual-variant margin / exposure reconciliation and derived-field lifecycle.

Translates Difficulty/dual_variant_calc and the derived-field reconciliation
corner. Every test builds its own state from scratch.
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_active_placement, setup_issued_invoice_one_timesheet,
    create_and_approve_timesheet,
    make_account_manager_headers,
)

AM = make_account_manager_headers()


def test_placement_projected_margin_fixed_at_creation(api):
    """PRD 3.6: "the `projected_weekly_margin_cents` is the difference between
    `bill_rate_cents` and `pay_rate_cents` multiplied by `standard_weekly_hours`."

    Provisional variant on the placement: bill 12000, pay 8000, 40h ->
    (12000 - 8000) * 40 == 160000.

    Design: Difficulty/dual_variant_calc/placement_margin_provisional_vs_actual
    """
    scen = setup_active_placement()
    pl = scen["placement"]
    assert pl["projected_weekly_margin_cents"] == 160000, (
        f"projected_weekly_margin_cents should be 160000, got {pl['projected_weekly_margin_cents']}"
    )


def test_actual_margin_diverges_from_projected_after_overtime_timesheet(api):
    """PRD 3.6: "On the `SUBMITTED → APPROVED` transition, the just-approved
    timesheet's `margin_cents` is added to the placement's `actual_margin_cents`."
    PRD 3.6: "the actual margin and the projected margin diverge whenever realized
    hours differ from the planned `standard_weekly_hours`."

    Approving one 45h timesheet (bill 12000, pay 8000): bill =
    round_half_up(40*12000 + 5*12000*1.5) = 570000; pay = 40*8000 + 5*8000*1.5 =
    380000; margin = 190000. Actual (190000) != projected (160000).

    Design: Difficulty/dual_variant_calc/placement_margin_provisional_vs_actual
    """
    scen = setup_active_placement()
    pl = scen["placement"]
    create_and_approve_timesheet(
        pl["id"], scen["candidate"]["id"], scen["client"]["id"],
        "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", 45)
    refreshed = validate_success(api.get_placement(pl["id"], scen["recruiter"]))
    assert refreshed["actual_margin_cents"] == 190000, (
        f"actual_margin_cents should be 190000 after a 45h approval, got {refreshed['actual_margin_cents']}"
    )
    assert refreshed["projected_weekly_margin_cents"] == 160000
    assert refreshed["actual_margin_cents"] != refreshed["projected_weekly_margin_cents"], (
        "actual and projected margins must diverge when realized hours != standard hours"
    )


def test_open_exposure_is_forward_projection_of_standard_hours(api):
    """PRD 2.9: "The `open_exposure_cents` figure is forward-looking: it is the sum
    of `projected_weekly_bill_cents` across the client's placements whose
    `assignment_status` is `ACTIVE`."

    One ACTIVE placement (bill 12000, 40h) -> open_exposure_cents == 480000.

    Design: Difficulty/dual_variant_calc/client_exposure_projected_vs_outstanding
    """
    scen = setup_active_placement()
    client = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert client["open_exposure_cents"] == 480000, (
        f"open_exposure_cents should be 480000, got {client['open_exposure_cents']}"
    )


def test_outstanding_balance_diverges_from_open_exposure_after_issue(api):
    """PRD 2.9: "The `outstanding_balance_cents` figure is realized: it is the sum
    of `total_cents` across the client's invoices whose `status` is `ISSUED`."
    PRD 2.9: "These two figures diverge in practice because the projection uses
    planned `standard_weekly_hours` while issued invoices reflect the realized
    hours actually worked."

    One ACTIVE placement (open_exposure 480000) with a 40h timesheet billed and the
    invoice ISSUED. The invoice total (480000 subtotal, tier-0, fee 7200) is 487200,
    so outstanding_balance_cents == 487200 != open_exposure_cents 480000.

    Design: Difficulty/dual_variant_calc/client_exposure_projected_vs_outstanding
    """
    scen = setup_issued_invoice_one_timesheet(hours=40)
    client = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert client["open_exposure_cents"] == 480000, (
        f"open_exposure_cents should be 480000, got {client['open_exposure_cents']}"
    )
    assert client["outstanding_balance_cents"] == 487200, (
        f"outstanding_balance_cents should be 487200, got {client['outstanding_balance_cents']}"
    )
    assert client["open_exposure_cents"] != client["outstanding_balance_cents"], (
        "projected exposure and realized outstanding balance must diverge"
    )


def test_open_exposure_reconciles_across_start_then_end(api):
    """PRD 2.9: "it is recomputed whenever such a placement is created, started, or ended."
    PRD 3.5: "Starting the engagement recomputes the client's `open_exposure_cents`,
    because the placement's `projected_weekly_bill_cents` now counts toward active exposure."
    PRD 3.5: "First, the client's `open_exposure_cents` is recomputed, removing this
    placement's projected weekly bill."

    Exposure is 480000 after ACTIVE start, back to 0 after the assignment ENDs.

    Design: Corner/cross_cutting_complexity_layers/derived_open_exposure_after_start_then_end
    """
    scen = setup_active_placement()
    after_active = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert after_active["open_exposure_cents"] == 480000, (
        f"open_exposure_cents should be 480000 while ACTIVE, got {after_active['open_exposure_cents']}"
    )
    get_success_data(api.patch_placement(
        scen["placement"]["id"], {"target_assignment_status": "ENDED"}, scen["recruiter"]))
    after_ended = validate_success(api.get_client(scen["client"]["id"], scen["recruiter"]))
    assert after_ended["open_exposure_cents"] == 0, (
        f"open_exposure_cents should be 0 after the assignment ends, got {after_ended['open_exposure_cents']}"
    )
