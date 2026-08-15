"""Restock shipments: lead-time boundary, stock sufficiency, segregation of
duties at receive, allocation upserts, show-to-show routing, and the
dispatch/cancel compensation pair."""
from test_helpers import (
    ApiErrorId,
    TM1,
    TM2,
    cancel_shipment,
    create_product,
    create_shipment,
    create_show,
    create_tour,
    dispatch_shipment,
    generate_allocations,
    get_allocation,
    get_product,
    get_shipment,
    is_iso8601_timestamp,
    list_allocations,
    receive_shipment,
    set_clock,
    validate_error,
)


class TestLeadTimeBoundary:
    def _two_shipment_world(self, api):
        tour = create_tour(name="BP2 Tour")
        far = create_show(tour["id"], city="Mesa", venue_name="BP2 Far Hall",
                          show_date="2026-08-03T00:00:00Z")
        near = create_show(tour["id"], city="Mesa", venue_name="BP2 Near Hall",
                           show_date="2026-08-02T23:59:59Z")
        product = create_product(tour["id"], sku="BP2-TEE", name="BP2 Tee",
                                 base_price_cents=4000,
                                 initial_stock_by_size={"OS": 1000})
        sh_far = create_shipment(tour["id"], far["id"], product["id"], 10)
        sh_near = create_shipment(tour["id"], near["id"], product["id"], 10)
        return tour, far, near, product, sh_far, sh_near

    def test_exactly_48h_lead_dispatches(self, api):
        """PRD §3.3: "The shipment must be `DRAFT` (otherwise
        `ERR_SHIPMENT_NOT_DRAFT`), and the destination show's `show_date` must
        lie at least 48 hours after the dispatch instant read from the logical
        clock — exactly 48 hours is permitted, anything tighter fails with
        `ERR_LEAD_TIME_VIOLATION`."
        PRD §2.6: "Before any clock-setting call has been made, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."
        PRD §3.3: "On dispatch the source is decremented — warehouse stock for
        a warehouse origin, or the origin show's allocation `quantity_allocated`
        for a show origin — and the shipment records `dispatched_by_user_id` and
        a `dispatched_at` stamp taken from the logical clock."

        Design: Difficulty/boundary_precision_check/lead_time_exactly_48h_boundary
        """
        _tour, _far, _near, _product, sh_far, _sh_near = \
            self._two_shipment_world(api)

        dispatched = dispatch_shipment(sh_far["id"])
        assert dispatched["status"] == "DISPATCHED", (
            "exactly 48h of lead is permitted: the boundary is inclusive")
        assert is_iso8601_timestamp(dispatched["dispatched_at"])
        assert dispatched["dispatched_at"].startswith("2026-08-01T00:00:00"), (
            "dispatched_at is stamped from the default logical clock")
        assert dispatched["dispatched_by_user_id"] == "tm-1"

    def test_one_second_inside_the_buffer_rejected(self, api):
        """PRD §3.3: "The shipment must be `DRAFT` (otherwise
        `ERR_SHIPMENT_NOT_DRAFT`), and the destination show's `show_date` must
        lie at least 48 hours after the dispatch instant read from the logical
        clock — exactly 48 hours is permitted, anything tighter fails with
        `ERR_LEAD_TIME_VIOLATION`."
        PRD §2.6: "Before any clock-setting call has been made, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."

        Design: Difficulty/boundary_precision_check/lead_time_exactly_48h_boundary
        """
        _tour, _far, _near, _product, _sh_far, sh_near = \
            self._two_shipment_world(api)

        resp = api.dispatch_shipment(sh_near["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)
        assert get_shipment(sh_near["id"])["status"] == "DRAFT"


class TestDispatchBufferViolation:
    def _world_with_clock_moved(self, api):
        tour = create_tour(name="TO2 Tour")
        show = create_show(tour["id"], city="Bend", venue_name="TO2 Hall",
                           show_date="2026-08-06T12:00:00Z")
        product = create_product(tour["id"], sku="TO2-TEE", name="TO2 Tee",
                                 base_price_cents=4000,
                                 initial_stock_by_size={"OS": 1000})
        shipment = create_shipment(tour["id"], show["id"], product["id"], 10)
        set_clock("2026-08-05T12:00:00Z")
        return tour, show, product, shipment

    def test_24h_buffer_rejected(self, api):
        """PRD §3.3: "The shipment must be `DRAFT` (otherwise
        `ERR_SHIPMENT_NOT_DRAFT`), and the destination show's `show_date` must
        lie at least 48 hours after the dispatch instant read from the logical
        clock — exactly 48 hours is permitted, anything tighter fails with
        `ERR_LEAD_TIME_VIOLATION`."
        PRD §2.6: "A test-driving capability,
        `POST /merch/_clock/set_current_utc`, advances the logical clock to the
        instant supplied in `to_iso8601`; it is available to all four roles and
        returns the standard success envelope with an empty data object."

        Design: Difficulty/resource_temporal_overlap/dispatch_buffer_violation_inside_48h
        """
        _tour, _show, _product, shipment = self._world_with_clock_moved(api)

        resp = api.dispatch_shipment(shipment["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)

    def test_rejected_dispatch_leaves_stock_unchanged(self, api):
        """PRD §3.3: "Stock is checked against the source: for a `WAREHOUSE`
        origin, every line must fit within the product's
        `warehouse_stock_by_size` for that size, failing with
        `ERR_INSUFFICIENT_STOCK`; for a `SHOW` origin, every line must fit
        within the origin allocation's `quantity_on_hand` for that product and
        size, failing with `ERR_INSUFFICIENT_ALLOCATION`. On dispatch the source
        is decremented — warehouse stock for a warehouse origin, or the origin
        show's allocation `quantity_allocated` for a show origin — and the
        shipment records `dispatched_by_user_id` and a `dispatched_at` stamp
        taken from the logical clock."
        PRD §3.3: "The shipment must be `DRAFT` (otherwise
        `ERR_SHIPMENT_NOT_DRAFT`), and the destination show's `show_date` must
        lie at least 48 hours after the dispatch instant read from the logical
        clock — exactly 48 hours is permitted, anything tighter fails with
        `ERR_LEAD_TIME_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/dispatch_buffer_violation_inside_48h
        """
        _tour, _show, product, shipment = self._world_with_clock_moved(api)

        resp = api.dispatch_shipment(shipment["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_VIOLATION)

        assert get_shipment(shipment["id"])["status"] == "DRAFT"
        assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 1000, (
            "a rejected dispatch decrements nothing")


def test_warehouse_dispatch_beyond_stock_rejected(api):
    """PRD §3.3: "Stock is checked against the source: for a `WAREHOUSE` origin,
    every line must fit within the product's `warehouse_stock_by_size` for that
    size, failing with `ERR_INSUFFICIENT_STOCK`; for a `SHOW` origin, every line
    must fit within the origin allocation's `quantity_on_hand` for that product
    and size, failing with `ERR_INSUFFICIENT_ALLOCATION`."

    Design: Corner/validations/warehouse_dispatch_beyond_stock_rejected
    """
    tour = create_tour(name="VA3 Tour")
    show = create_show(tour["id"], city="Dickinson", venue_name="VA3 Hall",
                       show_date="2026-08-10T20:00:00Z")
    product = create_product(tour["id"], sku="VA3-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 5})
    shipment = create_shipment(tour["id"], show["id"], product["id"], 10)

    resp = api.dispatch_shipment(shipment["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)

    assert get_shipment(shipment["id"])["status"] == "DRAFT"
    assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 5


def test_shipment_receive_from_draft_rejected(api):
    """PRD §3.3: "The shipment must be `DISPATCHED` (otherwise
    `ERR_SHIPMENT_NOT_DISPATCHED`), the receiving user's `X-User-ID` must differ
    from `dispatched_by_user_id` under the segregation-of-duties rule of §2.8,
    and the destination show must still be `SCHEDULED` or `OPEN` (otherwise
    `ERR_INVALID_SHOW_STATE`)."
    PRD §3.3: "For each line, the destination show's allocation for that product
    and size is upserted — created when absent — and its `quantity_allocated`
    incremented by the line quantity, and the shipment records
    `received_by_user_id`."

    Design: Corner/state_machines/shipment_receive_from_draft_rejected
    """
    tour = create_tour(name="SM5 Tour")
    show = create_show(tour["id"], city="Merced", venue_name="SM5 Hall",
                       show_date="2026-08-10T20:00:00Z")
    product = create_product(tour["id"], sku="SM5-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 1000})
    shipment = create_shipment(tour["id"], show["id"], product["id"], 10)

    resp = api.receive_shipment(shipment["id"], TM2)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DISPATCHED)

    rows = list_allocations({"show_id": show["id"]})
    assert rows == [], "nothing is upserted by a rejected receive"


def test_receive_by_dispatching_user_rejected_sod(api):
    """PRD §2.8: "The same `X-User-ID` may not stand on both sides of any pair:
    the verifier of a seller session must differ from that session's seller; the
    finalizer of a settlement must differ from the accountant recorded in the
    settlement's `reconciled_by_user_id`; and the receiver of a shipment must
    differ from the user recorded in `dispatched_by_user_id`. Violating any of
    the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.3: "For each line, the destination show's allocation for that product
    and size is upserted — created when absent — and its `quantity_allocated`
    incremented by the line quantity, and the shipment records
    `received_by_user_id`."

    Design: Corner/validations/receive_by_dispatching_user_rejected_sod
    """
    tour = create_tour(name="VA6 Tour")
    show = create_show(tour["id"], city="Spearfish", venue_name="VA6 Hall",
                       show_date="2026-08-10T20:00:00Z")
    product = create_product(tour["id"], sku="VA6-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 1000})
    shipment = create_shipment(tour["id"], show["id"], product["id"], 10)
    dispatch_shipment(shipment["id"])

    resp = api.receive_shipment(shipment["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    received = receive_shipment(shipment["id"], TM2)
    assert received["status"] == "RECEIVED"
    assert received["received_by_user_id"] == "tm-2"
    allocations = list_allocations({"show_id": show["id"],
                                    "product_id": product["id"]})
    assert len(allocations) == 1
    assert allocations[0]["quantity_allocated"] == 10


def test_receive_creates_missing_destination_allocation(api):
    """PRD §3.3: "For each line, the destination show's allocation for that
    product and size is upserted — created when absent — and its
    `quantity_allocated` incremented by the line quantity, and the shipment
    records `received_by_user_id`."
    PRD §3.3: "On dispatch the source is decremented — warehouse stock for a
    warehouse origin, or the origin show's allocation `quantity_allocated` for
    a show origin — and the shipment records `dispatched_by_user_id` and a
    `dispatched_at` stamp taken from the logical clock."

    Design: Corner/complexity_layers/receive_creates_missing_destination_allocation
    """
    tour = create_tour(name="CC3 Tour")
    show = create_show(tour["id"], city="Logan", venue_name="CC3 Hall",
                       show_date="2026-08-10T20:00:00Z")
    product = create_product(tour["id"], sku="CC3-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 1000})
    shipment = create_shipment(tour["id"], show["id"], product["id"], 10)
    dispatch_shipment(shipment["id"])

    received = receive_shipment(shipment["id"], TM2)
    assert received["status"] == "RECEIVED"

    allocations = list_allocations({"show_id": show["id"],
                                    "product_id": product["id"]})
    assert len(allocations) == 1, "the receive upsert creates the row"
    assert allocations[0]["size"] == "OS"
    assert allocations[0]["quantity_allocated"] == 10
    assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 990


def test_show_to_show_transfer_moves_units(api):
    """PRD §3.3: "On dispatch the source is decremented — warehouse stock for a
    warehouse origin, or the origin show's allocation `quantity_allocated` for
    a show origin — and the shipment records `dispatched_by_user_id` and a
    `dispatched_at` stamp taken from the logical clock."
    PRD §3.3: "For each line, the destination show's allocation for that product
    and size is upserted — created when absent — and its `quantity_allocated`
    incremented by the line quantity, and the shipment records
    `received_by_user_id`."

    Design: Corner/complexity_layers/show_to_show_transfer_moves_units
    """
    tour = create_tour(name="CC4 Tour")
    src = create_show(tour["id"], city="Provo", venue_name="CC4 One",
                      show_date="2026-08-10T20:00:00Z")
    dst = create_show(tour["id"], city="Orem", venue_name="CC4 Two",
                      show_date="2026-08-12T20:00:00Z")
    product = create_product(tour["id"], sku="CC4-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 0})
    src_allocation = generate_allocations(src["id"], product["id"], 100)[0]
    shipment = create_shipment(tour["id"], dst["id"], product["id"], 30,
                               origin_type="SHOW", origin_show_id=src["id"])

    dispatch_shipment(shipment["id"])
    assert get_allocation(src_allocation["id"])["quantity_allocated"] == 70, (
        "the origin show's allocation is decremented at dispatch")
    assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 0, (
        "warehouse stock is untouched by a show-to-show move")

    receive_shipment(shipment["id"], TM2)
    dst_allocations = list_allocations({"show_id": dst["id"],
                                        "product_id": product["id"]})
    assert len(dst_allocations) == 1
    assert dst_allocations[0]["quantity_allocated"] == 30
    assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 0


class TestDispatchThenCancelRestoresStock:
    def _dispatched_world(self, api):
        tour = create_tour(name="CI2 Tour")
        show = create_show(tour["id"], city="Redding", venue_name="CI2 Hall",
                           show_date="2026-08-10T20:00:00Z")
        product = create_product(tour["id"], sku="CI2-TEE", name="CI2 Tee",
                                 base_price_cents=4000,
                                 initial_stock_by_size={"OS": 1000})
        shipment = create_shipment(tour["id"], show["id"], product["id"], 100)
        dispatch_shipment(shipment["id"])
        return tour, show, product, shipment

    def test_cancel_restores_warehouse_stock(self, api):
        """PRD §3.3: "Cancelling works from `DRAFT` or `DISPATCHED`; cancelling
        a dispatched shipment performs a compensating restore, returning every
        line's units to the source — warehouse stock for a warehouse origin,
        origin allocations for a show origin."
        PRD §3.3: "A product's `warehouse_stock_by_size` for a given size is its
        `initial_stock_by_size` entry, minus the units of that size on
        `WAREHOUSE`-origin shipments now in `DISPATCHED` or `RECEIVED` status (a
        draft-then-cancelled shipment never decremented anything, while a
        dispatched-then-cancelled one decremented and was then restored), minus
        the units consumed by `FULFILLED` online orders (a `REGULAR` product's
        own size quantity, or for a `BUNDLE` each component's OS stock at
        `qty_per_bundle` times the order quantity; `PLACED` and `CANCELLED`
        orders consume nothing), plus the units credited back by `RETURN` lines
        at show close-out."

        Design: Difficulty/compensating_invariant/dispatch_then_cancel_restores_warehouse_stock
        """
        _tour, _show, product, shipment = self._dispatched_world(api)
        assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 900, (
            "dispatch decremented 100")

        cancelled = cancel_shipment(shipment["id"])
        assert cancelled["status"] == "CANCELLED"
        assert get_product(product["id"])["warehouse_stock_by_size"]["OS"] == 1000, (
            "the compensation restores the full 100 units")

    def test_cancelled_shipment_creates_no_destination_allocations(self, api):
        """PRD §3.3: "For each line, the destination show's allocation for that
        product and size is upserted — created when absent — and its
        `quantity_allocated` incremented by the line quantity, and the shipment
        records `received_by_user_id`."
        PRD §3.3: "Cancelling works from `DRAFT` or `DISPATCHED`; cancelling a
        dispatched shipment performs a compensating restore, returning every
        line's units to the source — warehouse stock for a warehouse origin,
        origin allocations for a show origin."

        Design: Difficulty/compensating_invariant/dispatch_then_cancel_restores_warehouse_stock
        """
        _tour, show, _product, shipment = self._dispatched_world(api)

        cancel_shipment(shipment["id"])

        rows = list_allocations({"show_id": show["id"]})
        assert rows == [], (
            "the destination allocation is created only at receive, which never happened")
