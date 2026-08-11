"""Responsibility decision table: first-match precedence of shared_split."""
from test_helpers import (
    TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    build_work_order, setup_shop_ctx, submit_current_wo, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]


def _shared_split_scenario() -> dict:
    """A COUPLER wear-group defect priced by a shared_split entry: Rule 2 must
    fire before the Rule 4 wear-group rule."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-COUPLER-LUBE", description="Coupler lubrication",
                    labor_rate_cents_per_hour=6000, mobile_labor_rate_cents_per_hour=7000,
                    standard_labor_hours=1.0, mobile_trip_surcharge_cents=20000,
                    mobile_eligible=True, shared_split=True)
    add_car_with_inspection(ctx, car_number="3003", defects=[{
        "aar_defect_code": "AAR-5002", "defect_group": "COUPLER",
        "cause_code": "WEAR", "severity": "MINOR", "location": "coupler"}])
    build_work_order(ctx, lines=[{"job_code": "J-COUPLER-LUBE"}])
    submit_current_wo(ctx)
    return ctx


def test_shared_split_beats_wear_group_at_line_level():
    """PRD §2.8: "Financial responsibility is decided per repair line at
    submission time by an ordered decision table; the first rule that matches
    wins and no later rule is consulted".
    PRD §2.8: "**Rule 2** — if the price master entry the line resolved to has
    `shared_split` true, responsibility is `SHARED` with an `owner_pct` of 50,
    regardless of any defect-group consideration."

    Design: Difficulty/combinatorial_formula/responsibility_shared_split_precedes_wear_group
    """
    ctx = _shared_split_scenario()
    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["responsible_party"] == "SHARED", (
        "Rule 2 shared_split fires before the Rule 4 COUPLER wear-group rule")
    assert line["owner_pct"] == 50
    assert line["estimate_total_cents"] == 6000, "1.0 standard hour at 6000c/h"


def test_shared_split_rolls_up_to_work_order_owner_majority():
    """PRD §2.8: "the owner's aggregate is the sum of line
    `estimate_total_cents` over every line whose `owner_pct` is at least 50;
    the handling line's aggregate is the remainder of the estimate total; the
    party holding the larger aggregate becomes the work order's
    `responsible_party`, and a tie resolves to `OWNER`."
    PRD §3.3: "Submission moves `auth_status` from `DRAFT` to
    `PENDING_AUTHORIZATION`".

    Design: Difficulty/combinatorial_formula/responsibility_shared_split_precedes_wear_group
    """
    ctx = _shared_split_scenario()
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["responsible_party"] == "OWNER", (
        "the single SHARED-50 line counts its 6000 toward the owner aggregate; "
        "6000 versus 0 is an owner majority")
    assert wo["owner_share_pct"] == 50, "half the estimate total is owner-responsible money"
    assert wo["auth_status"] == "PENDING_AUTHORIZATION"
