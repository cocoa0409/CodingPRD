"""Pinned rounding order: per-component, per-line, then summed."""
from test_helpers import (
    TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    authorize_current_wo, build_work_order, create_brc_for_current_wo,
    run_wo_to_completed, setup_shop_ctx, submit_current_wo,
    submit_current_brc, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]

_MINOR_DEFECTS = [
    {"aar_defect_code": "AAR-9001", "defect_group": "OTHER",
     "cause_code": "WEAR", "severity": "MINOR", "location": "A-end"},
    {"aar_defect_code": "AAR-9002", "defect_group": "OTHER",
     "cause_code": "WEAR", "severity": "MINOR", "location": "B-end"},
]


def _two_minor_line_brc() -> dict:
    """Two J-INSPECT-MINOR lines at 3333c/h, each finished at 0.9 actual hours:
    0.9 x 3333 = 2999.7 -> 3000 per line, so the card must total 6000."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-INSPECT-MINOR", description="Minor inspection labor",
                    labor_rate_cents_per_hour=3333, mobile_labor_rate_cents_per_hour=4000,
                    standard_labor_hours=0.9, mobile_trip_surcharge_cents=0,
                    mobile_eligible=True)
    add_car_with_inspection(ctx, car_number="4004", defects=_MINOR_DEFECTS)
    build_work_order(ctx, lines=[
        {"job_code": "J-INSPECT-MINOR", "defect_index": 0},
        {"job_code": "J-INSPECT-MINOR", "defect_index": 1},
    ])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    run_wo_to_completed(ctx, actual_hours=0.9)
    create_brc_for_current_wo(ctx)
    submit_current_brc(ctx)
    return ctx


def test_per_line_final_labor_rounded_half_up():
    """PRD §2.7: "The line's `final_labor_cents` is its `actual_labor_hours`
    multiplied by that rate, rounded half up to whole cents".

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
    """
    ctx = _two_minor_line_brc()
    for rl in ctx["wo_lines"]:
        line = validate_success(api_client.get_repair_line(rl["id"], ADMIN))
        assert line["final_labor_cents"] == 3000, (
            "0.9 actual hours x 3333c/h = 2999.7 rounds half up to 3000 per line")
        assert line["final_total_cents"] == 3000


def test_brc_total_sums_per_line_rounded_amounts():
    """PRD §3.7: "Card totals are aggregated with a pinned rounding order — per
    component, per line, then summed; never sum-then-round."
    PRD §3.7: "The `net_settled_cents` anchors the card: the submitted total
    minus the sum of accepted counter credits, recomputed whenever credits
    land."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
    """
    ctx = _two_minor_line_brc()
    brc = ctx["brc"]
    assert brc["submitted_total_cents"] == 6000, (
        "3000 + 3000 per-line; sum-then-round would have produced 5999")
    assert brc["owner_total_cents"] == 6000, "both lines are owner-responsible by default"
    assert brc["handling_line_total_cents"] == 0
    assert brc["net_settled_cents"] == 6000, "no credits yet"
    assert brc["status"] == "SUBMITTED"
