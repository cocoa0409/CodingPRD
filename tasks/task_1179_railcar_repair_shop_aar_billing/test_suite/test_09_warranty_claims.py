"""Warranty claim windows, eligibility checks, and the appeal cycle."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    assign_slot_current_wo, authorize_current_wo, build_work_order,
    complete_current_wo, create_warranty_claim_payload, file_warranty_claim,
    make_car_owner_rep_headers, make_quality_inspector_headers,
    qa_current_wo, scenario_submitted_brc, set_clock, setup_shop_ctx,
    start_current_wo, submit_current_wo, validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]
QI = "qi-1"

_WINDOW_QUOTE = ("the claim must land no later than the work order's "
                 "`completed_at` plus the shop's `warranty_days` — the boundary day "
                 "itself is included, and anything later is rejected with "
                 "`ERR_WARRANTY_WINDOW_EXPIRED`")


def test_warranty_window_duplicate_group_precedence():
    """PRD §3.9: "the claim must land no later than the work order's
    `completed_at` plus the shop's `warranty_days` — the boundary day itself is
    included, and anything later is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`;
    the referenced repair line must be `FINALIZED` and the
    `failure_defect_group` must match the original defect's `defect_group`,
    with either violation rejected as `ERR_WARRANTY_NOT_APPLICABLE`; and no
    other claim on the same line may be `FILED` or `VALIDATED`, else
    `ERR_WARRANTY_CLAIM_ACTIVE`."
    PRD §2.12: "twelfth the temporal rules (`ERR_SLOT_OVERLAP`,
    `ERR_SLOT_IN_PAST`, `ERR_PRICE_WINDOW_OVERLAP`,
    `ERR_COUNTER_BILL_WINDOW_CLOSED`, `ERR_WARRANTY_WINDOW_EXPIRED`, all 409);
    thirteenth the business constraints".

    Design: Corner/validations/warranty_window_duplicate_group_precedence
    """
    ctx = setup_shop_ctx(shop_overrides={"warranty_days": 90})
    add_price_entry(ctx)  # J-AIR-HOSE 1.5h
    add_price_entry(ctx, job_code="J-INSPECT-MINOR", description="Minor inspection labor",
                    labor_rate_cents_per_hour=3333, mobile_labor_rate_cents_per_hour=4000,
                    standard_labor_hours=0.9, mobile_trip_surcharge_cents=0,
                    mobile_eligible=True)
    add_price_entry(ctx, job_code="J-DOOR-FIX", description="Door track repair",
                    labor_rate_cents_per_hour=7000, mobile_labor_rate_cents_per_hour=8000,
                    standard_labor_hours=1.0, mobile_trip_surcharge_cents=15000,
                    mobile_eligible=True)
    add_car_with_inspection(ctx, car_number="6003", defects=[
        {"aar_defect_code": "AAR-1204", "defect_group": "AIR_HOSE",
         "cause_code": "WEAR", "severity": "MAJOR", "location": "A-end"},
        {"aar_defect_code": "AAR-9001", "defect_group": "OTHER",
         "cause_code": "WEAR", "severity": "MINOR", "location": "B-end"},
        {"aar_defect_code": "AAR-7001", "defect_group": "DOOR",
         "cause_code": "WEAR", "severity": "MINOR", "location": "plug door"},
    ])
    build_work_order(ctx, lines=[
        {"job_code": "J-AIR-HOSE", "defect_index": 0},
        {"job_code": "J-INSPECT-MINOR", "defect_index": 1},
        {"job_code": "J-DOOR-FIX", "defect_index": 2},
    ])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    set_clock("2026-05-02T14:00:00Z")
    complete_current_wo(ctx, actual_hours=[1.5, 0.9, 1.0])
    set_clock("2026-05-02T15:00:00Z")
    qa_current_wo(ctx, result="PASS")  # completed_at = 2026-05-02T15:00:00Z
    rl1, rl2, rl3 = [rl["id"] for rl in ctx["wo_lines"]]
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])

    set_clock("2026-05-03T09:00:00Z")
    wc1 = file_warranty_claim(ctx, rl1, failure_defect_group="AIR_HOSE",
                              claimed_rework_cost_cents=5000,
                              description="hose leak recurred")
    assert wc1["status"] == "FILED"

    # Duplicate active claim on the same line, still inside the window.
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(rl1, failure_defect_group="AIR_HOSE",
                                      claimed_rework_cost_cents=3000,
                                      description="duplicate while active"), owner)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_CLAIM_ACTIVE, expected_status=409)

    # Group mismatch on a different line, still inside the window.
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(rl3, failure_defect_group="WHEELSET",
                                      claimed_rework_cost_cents=3000,
                                      description="group mismatch"), owner)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_APPLICABLE, expected_status=409)

    # Boundary-inclusive filing at exactly completed_at + 90 days.
    set_clock("2026-07-31T15:00:00Z")
    wc2 = file_warranty_claim(ctx, rl2, failure_defect_group="OTHER",
                              claimed_rework_cost_cents=2000,
                              description="boundary day claim")
    assert wc2["status"] == "FILED", "the boundary day itself is included"

    # One hour past the boundary: the temporal check outranks the
    # duplicate-claim constraint in the PRD's fixed validation order.
    set_clock("2026-07-31T16:00:00Z")
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(rl2, failure_defect_group="OTHER",
                                      claimed_rework_cost_cents=1000,
                                      description="expired and duplicate"), owner)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED, expected_status=409)


def test_warranty_deny_appeal_then_honor_cycle():
    """PRD §3.9: "the original filer — matched by `filed_by_id` — may appeal a
    `DENIED` claim, moving it back to `FILED` with an optional `note` and
    incrementing `appeal_count`".
    PRD §3.9: "The credit is the smaller of two amounts: the repair line's
    `final_total_cents` minus the card line's `accepted_credit_cents` and minus
    any `warranty_credit_cents` previously honored on that line, on the one
    hand; and the claim's `claimed_rework_cost_cents` on the other."
    PRD §3.9: "The honored credit is added to the card line's
    `warranty_credit_cents` when a card line exists for the repair line, and it
    splits between the ledgers by the line's `owner_pct`".

    Design: Corner/errors/warranty_deny_appeal_then_honor_cycle
    """
    ctx = scenario_submitted_brc(actual_hours=1.5)  # final 13500, no parts
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    qi = make_quality_inspector_headers(QI)

    validate_success(api_client.accept_billing_repair_card(ctx["brc"]["id"], owner))
    owner_now = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner_now["outstanding_balance_cents"] == 13500

    rl_id = ctx["wo_lines"][0]["id"]
    bl_id = ctx["brc_lines"][0]["id"]
    wc = file_warranty_claim(ctx, rl_id, failure_defect_group="AIR_HOSE",
                             claimed_rework_cost_cents=8000,
                             description="hose blew again")
    validate_success(api_client.deny_warranty_claim(
        wc["id"], {"reason": "insufficient evidence"}, qi))

    appealed = validate_success(api_client.appeal_warranty_claim(
        wc["id"], {"note": "photos attached"}, owner))
    assert appealed["status"] == "FILED"
    assert appealed["appeal_count"] == 1

    validate_success(api_client.validate_warranty_claim(wc["id"], qi))
    honored = validate_success(api_client.honor_warranty_claim(wc["id"], BILLING))
    assert honored["status"] == "HONORED"
    assert honored["credit_cents"] == 8000, "min(13500 - 0 - 0, 8000)"

    brc_line = validate_success(api_client.get_brc_line(bl_id, ADMIN))
    assert brc_line["warranty_credit_cents"] == 8000
    owner_now = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner_now["outstanding_balance_cents"] == 5500, (
        "13500 posted at acceptance minus the 8000 owner share of the credit")
