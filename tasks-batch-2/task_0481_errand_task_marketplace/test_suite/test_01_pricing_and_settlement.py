"""Pricing: quote estimate vs final settlement, quarter-hour rounding, fixed pricing.

Translates difficulty queue (dual_variant_calc, combinatorial_formula) and corner
queue (calculations.fixed_category_quote, consistency_model settlement) instances.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_booking_payload, create_claim_payload, create_complete_payload,
    create_fixed_category_payload, create_review_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_offered_booking, claim_booking, drive_to_in_progress,
    create_in_progress_booking,
)

DISP = TEST_USERS["dispatcher_headers"]


def test_estimate_vs_final_labor_diverge(api):
    """PRD §3.5: "First, hourly billing uses the claimed tasker's personal hourly_rate_cents,
    not the category default rate that seeded the quote."
    PRD §3.2: "the estimated labor is the category's default_hourly_rate_cents multiplied by
    the client-supplied estimated_hours, then truncated down to whole cents".

    Design: Difficulty/dual_variant_calc/estimate_vs_final_labor_diverges_on_booking_pricing
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Hourly Help", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Tess Tasker", "hourly_rate_cents": 5000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T13:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    offered = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                     estimated_hours=2.0)
    assert offered["estimated_labor_cents"] == 8000

    claim_booking(offered["id"], tk)
    drive_to_in_progress(offered["id"], tk)
    completed = get_success_data(api.complete_booking(
        offered["id"], create_complete_payload(actual_hours=2.0, tip_cents=500),
        make_tasker_headers(tk)))
    assert completed["status"] == "COMPLETED"

    settlements = validate_success(api.get_settlement(offered["id"], DISP), 200)
    s = settlements[0]
    assert s["final_labor_cents"] == 10000
    assert s["final_service_fee_cents"] == 1500
    assert s["total_charged_cents"] == 12000
    assert s["tasker_payout_cents"] == 10500


def test_final_settlement_quarter_hour_round_up(api):
    """PRD §3.5: "the reported actual_hours is divided by 0.25, rounded up to the next whole
    number, and multiplied back by 0.25 to give the billed hours."
    PRD §3.5: "The final_service_fee_cents is fifteen percent of final_labor_cents, truncated
    down to whole cents."

    Design: Difficulty/combinatorial_formula/final_settlement_quarter_hour_rounding_order_mode_b
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Quarter Hourly", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Quinn", "hourly_rate_cents": 5000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T13:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tk,
                                    "2026-06-25T10:00:00Z", estimated_hours=2.0)
    get_success_data(api.complete_booking(
        bk["id"], create_complete_payload(actual_hours=2.1), make_tasker_headers(tk)))

    s = validate_success(api.get_settlement(bk["id"], DISP), 200)[0]
    assert s["final_labor_cents"] == 11250
    assert s["final_service_fee_cents"] == 1687
    assert s["tip_cents"] == 0
    assert s["total_charged_cents"] == 12937


def test_settlement_visible_immediately_after_complete(api):
    """PRD §3.5: "The tasker_payout_cents is the final labor plus the full tip — the tasker
    keeps all of the labor and all of the tip, while the platform retains the service fee."
    PRD §3.5: "Completing the booking also recomputes the tasker's counts: completed_booking_count
    rises by one and active_booking_count falls by one."

    Design: Corner/consistency_model/settlement_visible_in_same_complete_chain
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Imm Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Imm Tasker", "hourly_rate_cents": 5000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tk,
                                    "2026-06-25T10:00:00Z", estimated_hours=2.0)
    get_success_data(api.complete_booking(
        bk["id"], create_complete_payload(actual_hours=2.0, tip_cents=500),
        make_tasker_headers(tk)))

    s = validate_success(api.get_settlement(bk["id"], DISP), 200)[0]
    assert s["final_labor_cents"] == 10000
    assert s["tasker_payout_cents"] == 10500

    tasker = validate_success(api.get_tasker(tk, DISP), 200)
    assert tasker["completed_booking_count"] == 1


def test_fixed_category_quote_uses_fixed_price(api):
    """PRD §3.2: "For a fixed category, the estimated labor is simply the category's
    fixed_price_cents."
    PRD §3.2: "The estimated service fee is then fifteen percent of that estimated labor,
    truncated down to whole cents, and the estimated total is the estimated labor plus the
    estimated service fee."

    Design: Corner/calculations/fixed_category_quote_uses_fixed_price
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", DISP))
    cat = get_success_data(api.create_category(
        create_fixed_category_payload(name="Fixed Cat", fixed_price_cents=5000,
                                      default_duration_minutes=90), DISP))
    cl = get_success_data(api.create_client({"full_name": "Fixed Client"}, DISP))
    # estimated_hours is ignored for FIXED; omit it.
    bk_payload = create_booking_payload(cl["id"], cat["id"], "2026-06-26T10:00:00Z")
    bk_payload.pop("estimated_hours", None)
    bk = get_success_data(api.create_booking(bk_payload, make_client_headers(cl["id"])))

    offered = validate_success(api.offer_booking(bk["id"], make_client_headers(cl["id"])), 200)
    assert offered["estimated_labor_cents"] == 5000
    assert offered["estimated_service_fee_cents"] == 750
    assert offered["estimated_total_cents"] == 5750
