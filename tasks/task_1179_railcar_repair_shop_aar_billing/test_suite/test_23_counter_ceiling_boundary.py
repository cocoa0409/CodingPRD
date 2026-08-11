"""Aggregate counter-bill ceiling: exactly at the cap is allowed, one cent
over is rejected."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    authorize_current_wo, build_work_order, counter_item,
    create_brc_for_current_wo, file_counter_bill, make_car_owner_rep_headers,
    run_wo_to_completed, setup_shop_ctx, submit_current_brc, submit_current_wo,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]

_DEFECTS = [
    {"aar_defect_code": "AAR-9001", "defect_group": "OTHER",
     "cause_code": "WEAR", "severity": "MINOR", "location": "A-end"},
    {"aar_defect_code": "AAR-9002", "defect_group": "OTHER",
     "cause_code": "WEAR", "severity": "MINOR", "location": "B-end"},
]


def _two_line_submitted_brc() -> dict:
    """Two J-INSPECT-MINOR lines at 3000 each -> submitted_total 6000, so the
    aggregate cap is floor(0.60 x 6000) == 3600."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-INSPECT-MINOR", description="Minor inspection labor",
                    labor_rate_cents_per_hour=3333, mobile_labor_rate_cents_per_hour=4000,
                    standard_labor_hours=0.9, mobile_trip_surcharge_cents=0,
                    mobile_eligible=True)
    add_car_with_inspection(ctx, car_number="1313", defects=_DEFECTS)
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


def test_counter_exactly_at_aggregate_cap_allowed():
    """PRD §3.8: "the sum of `total_countered_cents` over all `ACCEPTED`
    counter-bills on the card, plus all `OPEN` or `REBUTTED` ones, plus this
    bill's own total, must be less than or equal to the floor of 0.60
    multiplied by `submitted_total_cents` — landing exactly at the cap is
    allowed".

    Design: Difficulty/boundary_precision_check/counter_ceiling_exact_cap_allowed_plus_one_rejected
    """
    ctx = _two_line_submitted_brc()
    bl1, bl2 = ctx["brc_lines"][0]["id"], ctx["brc_lines"][1]["id"]
    cb = file_counter_bill(ctx, [
        counter_item(bl1, 3000, "line1 full dispute"),
        counter_item(bl2, 600, "line2 partial"),
    ])
    assert cb["status"] == "OPEN"
    assert cb["total_countered_cents"] == 3600, (
        "exactly floor(0.60 x 6000) is allowed by the inclusive <=")
    accepted = validate_success(api_client.accept_counter_bill(cb["id"], BILLING))
    assert accepted["status"] == "ACCEPTED"


def test_one_cent_over_aggregate_cap_rejected():
    """PRD §3.8: "landing exactly at the cap is allowed — and a breach is
    rejected with `ERR_COUNTER_BILL_EXCEEDS_CEILING`."
    PRD §3.7: "The `net_settled_cents` anchors the card: the submitted total
    minus the sum of accepted counter credits, recomputed whenever credits
    land."

    Design: Difficulty/boundary_precision_check/counter_ceiling_exact_cap_allowed_plus_one_rejected
    """
    ctx = _two_line_submitted_brc()
    bl1, bl2 = ctx["brc_lines"][0]["id"], ctx["brc_lines"][1]["id"]
    cb = file_counter_bill(ctx, [
        counter_item(bl1, 3000, "line1 full dispute"),
        counter_item(bl2, 600, "line2 partial"),
    ])
    validate_success(api_client.accept_counter_bill(cb["id"], BILLING))

    resp = api_client.create_counter_bill(
        ctx["brc"]["id"], {"items": [counter_item(bl2, 1, "one cent over")]},
        make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_COUNTER_BILL_EXCEEDS_CEILING, expected_status=409)

    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["net_settled_cents"] == 2400, (
        "6000 - 3600; the rejected counter changes nothing")
