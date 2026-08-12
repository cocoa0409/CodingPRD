"""Transitive cascades: authorize -> reserve -> reorder flip; counter accept
-> line credit -> BRC net -> BRC status."""
from test_helpers import (
    TEST_USERS, api_client, assert_part_quantity_invariant, authorize_current_wo,
    counter_item, file_counter_bill, scenario_authorized_wo,
    scenario_submitted_brc, add_car_with_inspection, add_price_entry,
    build_work_order, setup_shop_ctx, submit_current_wo,
    make_car_owner_rep_headers, run_wo_to_completed, create_brc_for_current_wo,
    submit_current_brc, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def _low_stock_authorized_scenario() -> dict:
    """Part on_hand 3 / threshold 2; one line plans 1 unit; submitted."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx)
    from test_helpers import add_part
    part = add_part(ctx, key="low", part_number="L-400", description="Hose clamp kit",
                    unit_price_cents=1000, on_hand_qty=3, reorder_threshold=2)
    add_car_with_inspection(ctx, car_number="8008")
    build_work_order(ctx, lines=[{
        "job_code": "J-AIR-HOSE",
        "planned_parts": [{"part_item_id": part["id"], "quantity": 1}],
    }])
    submit_current_wo(ctx)
    return ctx


def test_authorize_cascades_line_status_and_reservation():
    """PRD §3.4: "A successful authorization stamps `authorized_at` from the
    logical clock, moves `auth_status` to `AUTHORIZED`, cascades every line
    `ESTIMATED` → `AUTHORIZED` and every referenced finding `ESTIMATED` →
    `AUTHORIZED`, reserves all planned parts by increasing each part's
    `reserved_qty`".

    Design: Difficulty/transitive_cascade/authorize_reserve_reorder_flip_chain
    """
    ctx = _low_stock_authorized_scenario()
    authorize_current_wo(ctx)
    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["status"] == "AUTHORIZED", "hop 1: the line is cascaded by authorize"
    part = validate_success(api_client.get_part(ctx["parts"]["low"]["id"], ADMIN))
    assert part["reserved_qty"] == 1, "hop 2: the reservation is created by authorization"
    assert part["on_hand_qty"] == 3, "reservation does not consume stock"
    assert_part_quantity_invariant(part)


def test_authorize_reservation_flips_part_to_reorder_needed():
    """PRD §3.4: "recomputes each touched part's `status` — which may flip
    `ACTIVE` → `REORDER_NEEDED` when availability falls to the threshold".
    PRD §2.9: "otherwise `REORDER_NEEDED` when `available_qty` is less than or
    equal to `reorder_threshold` — equality counts".

    Design: Difficulty/transitive_cascade/authorize_reserve_reorder_flip_chain
    """
    ctx = _low_stock_authorized_scenario()
    part_before = validate_success(api_client.get_part(ctx["parts"]["low"]["id"], ADMIN))
    assert part_before["status"] == "ACTIVE"
    authorize_current_wo(ctx)
    part = validate_success(api_client.get_part(ctx["parts"]["low"]["id"], ADMIN))
    assert part["available_qty"] == 2, "3 on hand minus 1 reserved"
    assert part["status"] == "REORDER_NEEDED", (
        "hop 3: available 2 <= threshold 2 flips the part at the inclusive boundary")


def _two_line_brc_with_counter() -> dict:
    """Two 3000-cent lines (6000 total) submitted; a 2400 counter filed on the
    first line and still open."""
    defects = [
        {"aar_defect_code": "AAR-9001", "defect_group": "OTHER",
         "cause_code": "WEAR", "severity": "MINOR", "location": "A-end"},
        {"aar_defect_code": "AAR-9002", "defect_group": "OTHER",
         "cause_code": "WEAR", "severity": "MINOR", "location": "B-end"},
    ]
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-INSPECT-MINOR", description="Minor inspection labor",
                    labor_rate_cents_per_hour=3333, mobile_labor_rate_cents_per_hour=4000,
                    standard_labor_hours=0.9, mobile_trip_surcharge_cents=0,
                    mobile_eligible=True)
    add_car_with_inspection(ctx, car_number="9009", defects=defects)
    build_work_order(ctx, lines=[
        {"job_code": "J-INSPECT-MINOR", "defect_index": 0},
        {"job_code": "J-INSPECT-MINOR", "defect_index": 1},
    ])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    run_wo_to_completed(ctx, actual_hours=0.9)
    create_brc_for_current_wo(ctx)
    submit_current_brc(ctx)
    cb = file_counter_bill(ctx, [counter_item(ctx["brc_lines"][0]["id"], 2400,
                                              "hour count disputed")])
    ctx["cb"] = cb
    return ctx


def test_counter_accept_cascades_credit_and_net():
    """PRD §3.8: "Accepting a counter-bill — from either `OPEN` or `REBUTTED` —
    moves it to `ACCEPTED` and runs a three-hop cascade: first each item's
    amount is added to its card line's `accepted_credit_cents` (starting from
    zero); then the card's `net_settled_cents` is recomputed as
    `submitted_total_cents` minus the sum of accepted credits".

    Design: Difficulty/transitive_cascade/counter_accept_credit_chain
    """
    ctx = _two_line_brc_with_counter()
    validate_success(api_client.accept_counter_bill(ctx["cb"]["id"], BILLING))
    brc_line = validate_success(api_client.get_brc_line(ctx["brc_lines"][0]["id"], ADMIN))
    assert brc_line["accepted_credit_cents"] == 2400, "hop 1: credit lands on the line"
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["net_settled_cents"] == 3600, "hop 2: 6000 - 2400 recomputed"
    assert brc["submitted_total_cents"] == 6000, "credits never rewrite the submitted total"


def test_counter_accept_returns_brc_to_submitted():
    """PRD §3.8: "and finally, when no active counters remain, the card returns
    `DISPUTED` → `SUBMITTED`."

    Design: Difficulty/transitive_cascade/counter_accept_credit_chain
    """
    ctx = _two_line_brc_with_counter()
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "DISPUTED", "the open counter holds the card in dispute"
    validate_success(api_client.accept_counter_bill(ctx["cb"]["id"], BILLING))
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "SUBMITTED", (
        "hop 3: resolving the last active counter flips the card back")
