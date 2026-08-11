"""Storage-in-transit and the re-weigh program (PRD 2.9, 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_warehouse_occupancy_invariant,
    create_warehouse,
    deliver_order,
    get_order,
    get_statement_for_order,
    in_transit_additional_order,
    set_clock,
    setup_delivered_order,
    setup_in_transit_order,
    setup_sit_order,
    validate_error,
    validate_paginated,
    get_success_data,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


# ---------------------------------------------------------------------------
# SIT cycle: IN_TRANSIT -> IN_SIT -> OUT_FOR_DELIVERY -> DELIVERED
# ---------------------------------------------------------------------------
def test_order_transit_sit_cycle_warehouse_ledger(api):
    """PRD section 2.9: "A warehouse's `occupied_cwt` is a ledger equal at all
    times to the sum of `stored_weight_cwt` over that warehouse's lots whose
    status is `IN_STORAGE`. The ledger is synchronized on every check-in (the
    lot's stored hundredweight is added), on every release (the stored
    hundredweight is subtracted as a compensating entry), and on every
    permanent-storage conversion (likewise subtracted)."
    PRD section 3.5: "A successful check-in creates a `SITLot` in `IN_STORAGE`
    with `stored_weight_cwt` set to that hundredweight and `checked_in_at` stamped
    from the logical clock, adds the stored hundredweight to the warehouse ledger
    per §2.9 (bumping the warehouse's `version`), and moves the order from
    `IN_TRANSIT` to `IN_SIT` with its `version` bumped."

    Design: Difficulty/non_linear_state_machine/order_transit_sit_redelivery_cycle
    """
    ctx = setup_sit_order(actual_weight_lbs=9600)
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "IN_SIT", "order looped off the linear pipeline into storage"
    warehouse = get_success_data(api.get_warehouse(ctx["warehouse"]["id"], ADMIN))
    assert warehouse["occupied_cwt"] == 96, "ceil(9600/100) added at check-in"

    set_clock("2026-06-15T10:00:00Z")
    lot = get_success_data(api.release_sit_lot(ctx["lot"]["id"], ctx["dest_h"]))
    # 5 whole days stored: 5 * 96 cwt * 250 cents.
    assert lot["accrued_storage_cents"] == 120000, (
        f"accrual must be 5 days * 96 cwt * 250, got {lot['accrued_storage_cents']}"
    )
    assert lot["status"] == "RELEASED"
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "OUT_FOR_DELIVERY"
    warehouse = get_success_data(api.get_warehouse(ctx["warehouse"]["id"], ADMIN))
    assert warehouse["occupied_cwt"] == 0, "compensating release subtracts the same 96"


def test_order_transit_sit_cycle_billing_axis_advances(api):
    """PRD section 3.5: "Otherwise the release moves the lot to `RELEASED` with
    `released_at` stamped from the clock and the accrual frozen, subtracts the
    stored hundredweight from the warehouse ledger as a compensating entry
    (warehouse `version` bumped), and moves the order from `IN_SIT` to
    `OUT_FOR_DELIVERY` with its `version` bumped."
    PRD section 3.7: "Delivery is completed by the destination agent through four
    gates evaluated in this written order: the order is `IN_TRANSIT` or
    `OUT_FOR_DELIVERY` (from any other state, `ERR_TRANSITION_NOT_ALLOWED`); no
    SIT lot on the order is still `IN_STORAGE` (else `ERR_SHIPMENT_IN_STORAGE` —
    recall that a `CONVERTED_PERMANENT` lot does not block); no re-weigh request
    on the order is still `REQUESTED` (else `ERR_REWEIGH_PENDING`, and the
    customer must cancel the pending request first — a performed-but-unapplied
    re-weigh does not block and instead expires in the cascade below); and the
    payload's `collected_at_delivery_cents` equals the freshly recomputed
    `delivery_amount_due_cents` (a mismatch is `ERR_DELIVERY_PAYMENT_MISMATCH`,
    HTTP 422)."

    Design: Difficulty/non_linear_state_machine/order_transit_sit_redelivery_cycle
    """
    ctx = setup_sit_order(actual_weight_lbs=9600)
    set_clock("2026-06-15T10:00:00Z")
    get_success_data(api.release_sit_lot(ctx["lot"]["id"], ctx["dest_h"]))

    delivered = deliver_order(ctx)  # collects the recomputed lawful amount
    assert delivered["status"] == "DELIVERED", "delivery from OUT_FOR_DELIVERY must succeed"
    assert delivered["billing_status"] == "FINAL_BILLED", (
        "the independent billing axis advanced through the SIT detour"
    )
    statement = get_statement_for_order(ctx["order"]["id"])
    assert statement["status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# SIT day-180 boundary
# ---------------------------------------------------------------------------
def _setup_lot_checked_in():
    return setup_sit_order(actual_weight_lbs=9600, warehouse_capacity=500)


def test_sit_day_179_still_in_storage(api):
    """PRD section 3.5: "A lot's `days_stored` is the count of whole days between
    `checked_in_at` and `released_at` — or, while the lot is still stored, the
    current logical clock — discarding any partial day; a same-day release
    therefore shows zero days. Billable days are `days_stored` capped at 180. The
    lot's `accrued_storage_cents` is `stored_weight_cwt` times the tariff's
    `sit_daily_rate_cents_per_cwt` times the billable days, computed live at read
    time while the lot is `IN_STORAGE` and frozen at release or conversion."
    PRD section 3.5: "Whenever a lot's `days_stored` reaches 180 — the limit is
    re-evaluated on any read or mutation of the lot, and again whenever the
    logical clock is set — the lot auto-converts from `IN_STORAGE` to
    `CONVERTED_PERMANENT`: its accrual is frozen at the 180-day cap, the warehouse
    ledger subtracts the stored hundredweight (bumping the warehouse's `version`),
    and the lot's `version` is bumped."

    Design: Difficulty/boundary_precision_check/sit_day_180_auto_conversion_boundary
    """
    ctx = _setup_lot_checked_in()
    # checked_in_at 2026-06-10T10:00:00Z -> day 179 is 2026-12-06T10:00:00Z.
    set_clock("2026-12-06T10:00:00Z")
    lot = get_success_data(api.get_sit_lot(ctx["lot"]["id"], ADMIN))
    assert lot["status"] == "IN_STORAGE", "day 179 is still below the 180-day limit"
    assert lot["days_stored"] == 179
    assert lot["accrued_storage_cents"] == 4296000, (
        f"179 * 96 * 250 = 4296000, got {lot['accrued_storage_cents']}"
    )


def test_sit_day_180_auto_converts_and_release_rejected(api):
    """PRD section 3.5: "Whenever a lot's `days_stored` reaches 180 — the limit is
    re-evaluated on any read or mutation of the lot, and again whenever the
    logical clock is set — the lot auto-converts from `IN_STORAGE` to
    `CONVERTED_PERMANENT`: its accrual is frozen at the 180-day cap, the warehouse
    ledger subtracts the stored hundredweight (bumping the warehouse's `version`),
    and the lot's `version` is bumped."
    PRD section 3.5: "Release for final delivery is the destination agent's act,
    and the day-limit rule is evaluated first: if the lot has reached 180 days it
    converts to `CONVERTED_PERMANENT` and the release is rejected with
    `ERR_LOT_NOT_IN_STORAGE`; a lot already `RELEASED` or previously converted
    fails the same way."

    Design: Difficulty/boundary_precision_check/sit_day_180_auto_conversion_boundary
    """
    ctx = _setup_lot_checked_in()
    # day 180 is 2026-12-07T10:00:00Z; setting the clock re-evaluates the limit.
    set_clock("2026-12-07T10:00:00Z")
    lot = get_success_data(api.get_sit_lot(ctx["lot"]["id"], ADMIN))
    assert lot["status"] == "CONVERTED_PERMANENT", "day 180 reaches the cap and converts"
    assert lot["accrued_storage_cents"] == 4320000, (
        f"accrual frozen at the 180-day cap 180 * 96 * 250, got {lot['accrued_storage_cents']}"
    )

    resp = api.release_sit_lot(ctx["lot"]["id"], ctx["dest_h"])
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_IN_STORAGE)

    warehouse = get_success_data(api.get_warehouse(ctx["warehouse"]["id"], ADMIN))
    assert warehouse["occupied_cwt"] == 0, "conversion releases the warehouse capacity"


# ---------------------------------------------------------------------------
# Warehouse occupancy ledger
# ---------------------------------------------------------------------------
def test_warehouse_occupancy_checkin_adds_stored_weight(api):
    """PRD section 2.9: "A warehouse's `occupied_cwt` is a ledger equal at all
    times to the sum of `stored_weight_cwt` over that warehouse's lots whose
    status is `IN_STORAGE`. The ledger is synchronized on every check-in (the
    lot's stored hundredweight is added), on every release (the stored
    hundredweight is subtracted as a compensating entry), and on every
    permanent-storage conversion (likewise subtracted)."

    Design: Difficulty/compensating_invariant/warehouse_occupancy_checkin_release_roundtrip
    """
    ctx = setup_in_transit_order(actual_weight_lbs=9600)
    warehouse = create_warehouse(capacity_cwt=500)
    before = get_success_data(api.get_warehouse(warehouse["id"], ADMIN))
    assert before["occupied_cwt"] == 0

    lot = get_success_data(
        api.create_sit_lot(ctx["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx["hauling_h"])
    )
    assert lot["stored_weight_cwt"] == 96
    after = get_success_data(api.get_warehouse(warehouse["id"], ADMIN))
    assert after["occupied_cwt"] == 96, "check-in adds exactly ceil(9600/100)"

    lots, _meta = validate_paginated(
        api.list_sit_lots(ADMIN, params={"warehouse_id": warehouse["id"], "status": "IN_STORAGE"})
    )
    assert_warehouse_occupancy_invariant(after, lots)


def test_warehouse_occupancy_release_roundtrip_returns_to_zero(api):
    """PRD section 2.9: "A warehouse's `occupied_cwt` is a ledger equal at all
    times to the sum of `stored_weight_cwt` over that warehouse's lots whose
    status is `IN_STORAGE`. The ledger is synchronized on every check-in (the
    lot's stored hundredweight is added), on every release (the stored
    hundredweight is subtracted as a compensating entry), and on every
    permanent-storage conversion (likewise subtracted)."

    Design: Difficulty/compensating_invariant/warehouse_occupancy_checkin_release_roundtrip
    """
    ctx = setup_sit_order(actual_weight_lbs=9600)
    mid = get_success_data(api.get_warehouse(ctx["warehouse"]["id"], ADMIN))
    assert mid["occupied_cwt"] == 96

    get_success_data(api.release_sit_lot(ctx["lot"]["id"], ctx["dest_h"]))
    end = get_success_data(api.get_warehouse(ctx["warehouse"]["id"], ADMIN))
    assert end["occupied_cwt"] == 0, (
        "check-in (+96) paired with its compensating release (-96) returns to zero drift"
    )
    lots, _meta = validate_paginated(
        api.list_sit_lots(ADMIN, params={"warehouse_id": ctx["warehouse"]["id"], "status": "IN_STORAGE"})
    )
    assert_warehouse_occupancy_invariant(end, lots)


# ---------------------------------------------------------------------------
# Aggregate (not pairwise) warehouse capacity
# ---------------------------------------------------------------------------
def _setup_three_in_transit_orders():
    """One warehouse (140 cwt) and three IN_TRANSIT orders of 96, 40, 40 cwt.
    All three orders share ctx1's published tariff: PRD 2.8 rejects a second
    published tariff whose window intersects the first."""
    ctx1 = setup_in_transit_order(actual_weight_lbs=9600)
    warehouse = create_warehouse(capacity_cwt=140)
    ctx2 = in_transit_additional_order(ctx1, actual_weight_lbs=4000, estimated_weight_lbs=4000)
    ctx3 = in_transit_additional_order(ctx1, actual_weight_lbs=4000, estimated_weight_lbs=4000)
    return warehouse, ctx1, ctx2, ctx3


def test_warehouse_aggregate_capacity_allows_coexistence(api):
    """PRD section 3.5: "The warehouse must be `ACTIVE` (else
    `ERR_WAREHOUSE_INACTIVE`) and must have aggregate room: its `occupied_cwt`
    plus the shipment's hundredweight — the order's `actual_weight_lbs` divided by
    100 with any remainder rounded up — must not exceed its `capacity_cwt`, or the
    check-in is rejected with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/warehouse_aggregate_capacity_not_pairwise
    """
    warehouse, ctx1, ctx2, _ctx3 = _setup_three_in_transit_orders()
    lot1 = get_success_data(
        api.create_sit_lot(ctx1["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx1["hauling_h"])
    )
    lot2 = get_success_data(
        api.create_sit_lot(ctx2["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx2["hauling_h"])
    )
    assert lot1["status"] == "IN_STORAGE" and lot2["status"] == "IN_STORAGE", (
        "lots coexist over the same days — coexistence is limited only by the running sum"
    )
    warehouse_after = get_success_data(api.get_warehouse(warehouse["id"], ADMIN))
    assert warehouse_after["occupied_cwt"] == 136, "96 + 40 = 136 <= 140"


def test_warehouse_aggregate_capacity_breach_rejected(api):
    """PRD section 3.5: "The warehouse must be `ACTIVE` (else
    `ERR_WAREHOUSE_INACTIVE`) and must have aggregate room: its `occupied_cwt`
    plus the shipment's hundredweight — the order's `actual_weight_lbs` divided by
    100 with any remainder rounded up — must not exceed its `capacity_cwt`, or the
    check-in is rejected with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/warehouse_aggregate_capacity_not_pairwise
    """
    warehouse, ctx1, ctx2, ctx3 = _setup_three_in_transit_orders()
    get_success_data(
        api.create_sit_lot(ctx1["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx1["hauling_h"])
    )
    get_success_data(
        api.create_sit_lot(ctx2["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx2["hauling_h"])
    )

    resp = api.create_sit_lot(
        ctx3["order"]["id"], {"warehouse_id": warehouse["id"]}, ctx3["hauling_h"]
    )
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED)

    warehouse_after = get_success_data(api.get_warehouse(warehouse["id"], ADMIN))
    assert warehouse_after["occupied_cwt"] == 136, (
        "the rejected check-in must not partially occupy the warehouse"
    )


# ---------------------------------------------------------------------------
# Re-weigh program
# ---------------------------------------------------------------------------
def test_reweigh_apply_recomputes_delivery_cap(api):
    """PRD section 3.5: "On apply, the order's `authoritative_weight_ticket_id`
    switches to the resulting ticket, `actual_weight_lbs` is recomputed, the
    final-charges-and-cap computation of §3.7 is re-run so that
    `delivery_amount_due_cents` is refreshed with the one-hundred-ten-percent cap
    re-evaluated against the new net weight, the order's `version` is bumped, and
    the request becomes `APPLIED` (terminal)."
    PRD section 3.5: "Performance takes the same scale payload as an original
    weighment — `scale_location`, `weighed_at`, `tare_weight_lbs`, and
    `gross_weight_lbs` — and produces a `WeightTicket` whose `ticket_kind` is
    `REWEIGH`, whose `reweigh_request_id` names the request, and whose
    `supersedes_ticket_id` names the order's currently authoritative ticket as
    evidence lineage."

    Design: Corner/calculations/reweigh_apply_recomputes_delivery_cap
    """
    ctx = setup_in_transit_order(actual_weight_lbs=9600)
    original_ticket = ctx["ticket"]
    request = get_success_data(
        api.create_reweigh_request(ctx["order"]["id"], {"requested_by_role": "CUSTOMER"}, ctx["cust_h"])
    )

    performed = get_success_data(
        api.perform_reweigh(
            request["id"],
            {
                "scale_location": "SCALE-02",
                "weighed_at": "2026-06-12T09:00:00Z",
                "tare_weight_lbs": 14000,
                "gross_weight_lbs": 22400,
            },
            ctx["hauling_h"],
        )
    )
    assert performed["status"] == "PERFORMED"

    applied = get_success_data(api.apply_reweigh(request["id"], ctx["cust_h"]))
    assert applied["status"] == "APPLIED"

    tickets, meta = validate_paginated(
        api.list_weight_tickets(ADMIN, params={"reweigh_request_id": request["id"]})
    )
    assert meta["total_count"] == 1
    reweigh_ticket = tickets[0]
    assert reweigh_ticket["ticket_kind"] == "REWEIGH"
    assert reweigh_ticket["net_weight_lbs"] == 8400
    assert reweigh_ticket["supersedes_ticket_id"] == original_ticket["id"]

    order = get_order(ctx["order"]["id"])
    assert order["actual_weight_lbs"] == 8400
    assert order["authoritative_weight_ticket_id"] == reweigh_ticket["id"]
    # 84 cwt at 1200 miles: 453600 + 45360 = 498960, below the 522720 cap.
    assert order["delivery_amount_due_cents"] == 498960, (
        f"cap re-evaluated against the new weight, got {order['delivery_amount_due_cents']}"
    )


def test_reweigh_once_per_order(api):
    """PRD section 3.5: "Two uniqueness limits apply: at most one non-terminal
    re-weigh request may exist on an order at a time, and at most one re-weigh may
    ever reach `APPLIED` on an order; either violation is rejected with
    `ERR_REWEIGH_ALREADY_USED`."

    Design: Corner/validations/reweigh_once_per_order
    """
    ctx = setup_in_transit_order(
        actual_weight_lbs=8000, estimated_weight_lbs=8000, mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
    )
    request = get_success_data(
        api.create_reweigh_request(ctx["order"]["id"], {"requested_by_role": "CUSTOMER"}, ctx["cust_h"])
    )
    get_success_data(
        api.perform_reweigh(
            request["id"],
            {
                "scale_location": "SCALE-02",
                "weighed_at": "2026-06-12T09:00:00Z",
                "tare_weight_lbs": 14000,
                "gross_weight_lbs": 21900,
            },
            ctx["hauling_h"],
        )
    )
    get_success_data(api.apply_reweigh(request["id"], ctx["cust_h"]))

    resp = api.create_reweigh_request(
        ctx["order"]["id"], {"requested_by_role": "CUSTOMER"}, ctx["cust_h"]
    )
    validate_error(resp, ApiErrorId.ERR_REWEIGH_ALREADY_USED)


def test_performed_reweigh_expires_at_delivery(api):
    """PRD section 3.5: "A re-weigh that was performed but never applied never
    blocks delivery: the delivery cascade flips it to `EXPIRED` and the original
    weight stands."
    PRD section 3.7: "Hop one: the order's single `RevenueStatement` is created in
    `PROVISIONAL` with the revenue waterfall of §3.8 computed and its share fields
    written, and every `PERFORMED` re-weigh request on the order flips to
    `EXPIRED`."

    Design: Corner/validations/performed_reweigh_expires_at_delivery
    """
    ctx = setup_in_transit_order(
        actual_weight_lbs=8000, estimated_weight_lbs=8000, mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
    )
    request = get_success_data(
        api.create_reweigh_request(ctx["order"]["id"], {"requested_by_role": "CUSTOMER"}, ctx["cust_h"])
    )
    get_success_data(
        api.perform_reweigh(
            request["id"],
            {
                "scale_location": "SCALE-02",
                "weighed_at": "2026-06-12T09:00:00Z",
                "tare_weight_lbs": 14000,
                "gross_weight_lbs": 23000,
            },
            ctx["hauling_h"],
        )
    )

    delivered = deliver_order(ctx)
    assert delivered["status"] == "DELIVERED", "the PERFORMED re-weigh must not block delivery"
    assert delivered["final_charges_cents"] == 396000, (
        "the original 8000 lbs governed (re-weigh never applied)"
    )
    assert delivered["actual_weight_lbs"] == 8000

    request_after = get_success_data(api.get_reweigh_request(request["id"], ADMIN))
    assert request_after["status"] == "EXPIRED"


def test_requested_reweigh_blocks_delivery_until_cancelled(api):
    """PRD section 3.7: "no re-weigh request on the order is still `REQUESTED`
    (else `ERR_REWEIGH_PENDING`, and the customer must cancel the pending request
    first — a performed-but-unapplied re-weigh does not block and instead expires
    in the cascade below)"
    PRD section 3.5: "A request still `REQUESTED` may be cancelled by the customer
    or the booking agent, landing in `CANCELLED`."

    Design: Corner/validations/requested_reweigh_blocks_delivery_until_cancelled
    """
    ctx = setup_in_transit_order(
        actual_weight_lbs=8000, estimated_weight_lbs=8000, mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
    )
    request = get_success_data(
        api.create_reweigh_request(ctx["order"]["id"], {"requested_by_role": "CUSTOMER"}, ctx["cust_h"])
    )

    resp = api.deliver_order(
        ctx["order"]["id"], {"collected_at_delivery_cents": 396000}, ctx["dest_h"]
    )
    validate_error(resp, ApiErrorId.ERR_REWEIGH_PENDING)
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "IN_TRANSIT", "the blocked delivery must not move the order"

    cancelled = get_success_data(api.cancel_reweigh(request["id"], ctx["cust_h"]))
    assert cancelled["status"] == "CANCELLED"

    delivered = deliver_order(ctx)
    assert delivered["status"] == "DELIVERED", "after the cancel the identical deliver succeeds"
