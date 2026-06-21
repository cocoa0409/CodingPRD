"""Booking metering, overtime billing, disposal-fee accrual, the final-invoice
dual variant, and the SCHEDULED fork to COMPLETED vs CANCELLED
(PRD §3.9, §3.10).

Difficulty: boundary_precision_check (overtime), dual_variant_calc
(final invoice), non_linear_state_machine (complete vs cancel).
Corner: disposal fee rounding.
"""
from test_helpers import (
    validate_success,
    api_client,
    create_service_area,
    create_crew,
    create_equipment,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    accept_estimate,
    current_version,
    create_booking,
    finalize_booking,
    record_disposal_ticket,
    finalize_disposal_ticket,
    setup_scheduled_with_crew,
    TEST_USERS,
)


def _scheduled_hourly_with_crew(crew_rate=9000):
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=crew_rate)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    return area, wo, tree, crew


# ─── boundary_precision_check / booking_overtime_8_hour_boundary ───


def test_booking_billed_cost_at_8_hours_no_overtime(api):
    """PRD §3.9: "the regular portion is the lesser of the actual hours and 8,
    and the overtime portion is whatever exceeds 8 (zero if none)." PRD §3.9:
    "The boundary is exact: 8.0 hours produces no overtime, while 8.001 hours
    puts a sliver into the overtime band."

    Design: Difficulty/boundary_precision_check/booking_overtime_8_hour_boundary
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-13T08:00:00Z", end_at="2026-07-13T16:00:00Z",
    )
    finalized = finalize_booking(bk["id"], 8.0)
    assert finalized["billed_cost_cents"] == 72000   # 9000 * 8


def test_booking_billed_cost_above_8_hours_enters_overtime(api):
    """PRD §3.9: "Hours are then split at an overtime threshold of 8 hours:
    the regular portion is the lesser of the actual hours and 8, and the
    overtime portion is whatever exceeds 8 (zero if none)." PRD §3.9: "The
    regular hours are billed at the resolved rate and the overtime hours are
    billed at 1.5 times that rate, and the combined amount is rounded half-up
    exactly once to a whole number of cents"

    Design: Difficulty/boundary_precision_check/booking_overtime_8_hour_boundary
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-20T08:00:00Z", end_at="2026-07-20T16:30:00Z",
    )
    # 8.5h: 9000*8 (regular) + 9000*1.5*0.5 (overtime) = 72000 + 6750 = 78750.
    # Whole cents at every step, so the result is unambiguous regardless of
    # the implementation's rounding substrate — overtime above 8h is exercised.
    finalized = finalize_booking(bk["id"], 8.5)
    assert finalized["billed_cost_cents"] == 78750


# ─── dual_variant_calc / final_invoice_per_job_frozen_vs_hourly_metered ───


def test_hourly_final_invoice_sums_metered_actuals_with_hazard_surcharge(api):
    """PRD §3.10: "For an `HOURLY` work order the invoice is built from
    chronological actuals: it is the `labor_cost_accrued_cents` plus the
    `disposal_cost_accrued_cents` plus a hazard surcharge computed over those
    accruals." PRD §3.10: "That hazard surcharge takes the sum of the labor
    and disposal accruals, multiplies it by the hazard percentage drawn from
    the work order's `hazard_level` — twenty percent for `SEVERE`, ten percent
    for `MODERATE`, zero otherwise — and rounds half-up to whole cents."

    Design: Difficulty/dual_variant_calc/final_invoice_per_job_frozen_vs_hourly_metered
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)
    equip = create_equipment(area["id"], kind="CHIPPER", name="Chip-1",
                             hourly_rate_cents=15000, mobilization_buffer_minutes=0)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, has_visible_decay=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    bk_crew = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-01T09:00:00Z", end_at="2026-07-01T19:00:00Z",
    )
    bk_equip = create_booking(
        wo["id"], "EQUIPMENT", equipment_id=equip["id"],
        start_at="2026-07-02T09:00:00Z", end_at="2026-07-02T15:00:00Z",
    )
    finalize_booking(bk_crew["id"], 10)    # 9000*8 + 9000*1.5*2 = 72000+27000 = 99000
    finalize_booking(bk_equip["id"], 6)    # 15000*6 = 90000 -> labor 189000
    ticket = record_disposal_ticket(wo["id"], debris_tons=4)
    finalize_disposal_ticket(wo["id"], ticket["id"])   # 4*8000 = 32000
    completed = validate_success(
        api.complete_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert completed["labor_cost_accrued_cents"] == 189000
    assert completed["disposal_cost_accrued_cents"] == 32000
    assert completed["hazard_level"] == "MODERATE"
    # (189000+32000) + round_half_up(221000*0.10)=22100 -> 243100
    assert completed["final_invoice_cents"] == 243100
    assert completed["status"] == "COMPLETED"


def test_per_job_final_invoice_freezes_accepted_estimate_price(api):
    """PRD §3.10: "For a `PER_JOB` work order the invoice is forward-looking:
    it is exactly the accepted estimate's `total_cents`, the frozen contract
    price, and the actual labor and disposal accruals are ignored entirely."

    Design: Difficulty/dual_variant_calc/final_invoice_per_job_frozen_vs_hourly_metered
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Oak", dbh_inches=25)   # med tier REMOVAL 95000, LOW hazard
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issued = issue_estimate(wo["id"], est["id"])
    assert issued["total_cents"] == 95000
    accept_estimate(wo["id"], est["id"])
    completed = validate_success(
        api.complete_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert completed["final_invoice_cents"] == 95000
    assert completed["status"] == "COMPLETED"


# ─── non_linear_state_machine / work_order_branch_scheduled... ───


def test_scheduled_branches_to_completed_with_invoice(api):
    """PRD §3.10: "Completing the work order moves it `SCHEDULED` →
    `COMPLETED`" PRD §3.10: "On completion the server computes
    `final_invoice_cents` and increments the work order's `version` by one."

    Design: Difficulty/non_linear_state_machine/work_order_branch_scheduled_to_completed_vs_cancelled
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)
    wo = create_work_order(area["id"], pricing_mode="HOURLY", site_address="5 Cedar St")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, has_visible_decay=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-01T09:00:00Z", end_at="2026-07-01T19:00:00Z",
    )
    finalize_booking(bk["id"], 10)   # 9000*8 + 9000*1.5*2 = 72000+27000 = 99000 labor
    ticket = record_disposal_ticket(wo["id"], debris_tons=4)
    finalize_disposal_ticket(wo["id"], ticket["id"])   # 4*8000 = 32000 disposal
    completed = validate_success(
        api.complete_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert completed["status"] == "COMPLETED"
    # MODERATE hazard (dbh 20 -> 30 + decay 20 = score 50): (99000+32000) +
    # round_half_up(131000*0.10)=13100 -> 144100.
    assert completed["final_invoice_cents"] == 144100


def test_scheduled_branches_to_cancelled_zeroes_invoice_and_releases(api):
    """PRD §3.10: "Cancelling drives a full unwind as side effects: every
    `RESERVED` booking is released, freeing that resource's calendar window;
    every `RECORDED` disposal ticket is voided; every `DRAFT` or `ISSUED`
    estimate is superseded; `final_invoice_cents` is set to 0; the work order
    moves to `CANCELLED`; and the work order's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/work_order_branch_scheduled_to_completed_vs_cancelled
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)
    wo = create_work_order(area["id"], pricing_mode="HOURLY", site_address="6 Cedar St")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, has_visible_decay=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T19:00:00Z",
    )
    cancelled = validate_success(
        api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["final_invoice_cents"] == 0
    bk_after = validate_success(
        api.get_booking(bk["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert bk_after["status"] == "RELEASED"


# ─── Corner / disposal_fee_rounded_per_ton ──────────────


def test_disposal_fee_rounded_and_accrued_on_finalize(api):
    """PRD §3.9: "finalization computes `fee_cents` as the `debris_tons`
    multiplied by the service area's `disposal_fee_cents_per_ton`, rounded
    half-up to whole cents, adds it to the work order's
    `disposal_cost_accrued_cents`, and increments the work order's `version`
    by one."

    Design: Corner/calculations/disposal_fee_rounded_per_ton
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    ticket = record_disposal_ticket(wo["id"], debris_tons=3.5)
    finalized = validate_success(
        api.finalize_disposal_ticket(wo["id"], ticket["id"],
                                     TEST_USERS["finance_clerk_headers"]), 200,
    )
    assert finalized["fee_cents"] == 28000    # round_half_up(3.5 * 8000)
    assert finalized["status"] == "FINALIZED"
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["disposal_cost_accrued_cents"] == 28000
