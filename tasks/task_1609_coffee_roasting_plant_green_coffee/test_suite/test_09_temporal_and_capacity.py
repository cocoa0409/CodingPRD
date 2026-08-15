"""Resource temporal overlap and aggregate-capacity boundary tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_shipment,
    create_counterparty,
    create_fixed_contract,
    set_clock,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["trader_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]


class TestDeliveryWindowInclusive:
    def test_shipment_arrival_within_delivery_window_inclusive(self, api):
        """PRD §3.4: "Two booking validations run in order: first the
        delivery-window check — `scheduled_arrival` must fall within the
        contract's delivery window, inclusive of both
        `delivery_window_start` and `delivery_window_end`, otherwise
        `ERR_DELIVERY_WINDOW_VIOLATION`"

        Design: Difficulty/resource_temporal_overlap/shipment_arrival_within_delivery_window_inclusive
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-DW", legal_name="Window Co")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-DW", total_lbs=10000,
            fixed_price=2.00,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T23:59:59Z",
        )
        # 1 second BEFORE window opens -> rejected
        resp = api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-EARLY", "planned_lbs": 1000,
             "scheduled_arrival": "2026-08-31T23:59:59Z"},
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_VIOLATION)
        # Exactly AT delivery_window_start -> accepted (inclusive lower bound)
        ok1 = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-AT-START", "planned_lbs": 1000,
             "scheduled_arrival": "2026-09-01T00:00:00Z"},
            LOGISTICS,
        ), 201)
        assert ok1["id"]
        # Exactly AT delivery_window_end -> accepted (inclusive upper bound)
        ok2 = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-AT-END", "planned_lbs": 1000,
             "scheduled_arrival": "2026-09-30T23:59:59Z"},
            LOGISTICS,
        ), 201)
        assert ok2["id"]
        # 1 second AFTER window closes -> rejected
        resp2 = api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-LATE", "planned_lbs": 1000,
             "scheduled_arrival": "2026-10-01T00:00:00Z"},
            LOGISTICS,
        )
        validate_error(resp2, ApiErrorId.ERR_DELIVERY_WINDOW_VIOLATION)

    def test_shipment_arrival_inside_window_accepted(self, api):
        """PRD §3.4: "first the delivery-window check — `scheduled_arrival`
        must fall within the contract's delivery window, inclusive of
        both `delivery_window_start` and `delivery_window_end`, otherwise
        `ERR_DELIVERY_WINDOW_VIOLATION`"

        Design: Difficulty/resource_temporal_overlap/shipment_arrival_within_delivery_window_inclusive
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-DW2", legal_name="Window Co 2")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-DW2", total_lbs=5000,
            fixed_price=2.00,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T23:59:59Z",
        )
        # Strictly interior timestamp is accepted
        ok = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-MID", "planned_lbs": 1000,
             "scheduled_arrival": "2026-09-15T12:00:00Z"},
            LOGISTICS,
        ), 201)
        assert ok["transit_status"] == "BOOKED"


class TestContractAggregateCapacity:
    def test_contract_aggregate_capacity_overlap(self, api):
        """PRD §3.4: "then the aggregate capacity check — the new
        `planned_lbs` plus the summed `planned_lbs` of the contract's
        sibling shipments that are not `CANCELLED` must not exceed the
        contract's `total_lbs`, otherwise `ERR_CONTRACT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/contract_aggregate_capacity_overlap
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-AGG", legal_name="Aggregate Co")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-AGG", total_lbs=5000,
            fixed_price=2.00,
        )
        # First shipment: 4000 lbs (fits)
        book_shipment(contract["id"], shipment_ref="SH-AGG-1",
                       planned_lbs=4000,
                       scheduled_arrival="2026-09-15T00:00:00Z")
        # Second: 1000 more — cumulative 5000 == total_lbs (at-capacity allowed)
        ok = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-AGG-OK", "planned_lbs": 1000,
             "scheduled_arrival": "2026-09-20T00:00:00Z"},
            LOGISTICS,
        ), 201)
        assert ok["id"]
        # Third: 1 more lb — cumulative 5001 > total_lbs -> rejected
        resp = api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-AGG-OVER", "planned_lbs": 1,
             "scheduled_arrival": "2026-09-22T00:00:00Z"},
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_CAPACITY_EXCEEDED)

    def test_contract_aggregate_capacity_cancelled_sibling_does_not_count(
            self, api):
        """PRD §3.4: "then the aggregate capacity check — the new
        `planned_lbs` plus the summed `planned_lbs` of the contract's
        sibling shipments that are not `CANCELLED` must not exceed the
        contract's `total_lbs`, otherwise
        `ERR_CONTRACT_CAPACITY_EXCEEDED`."
        PRD §3.4: "A booking can be cancelled only before it ships —
        `BOOKED` to `CANCELLED`"

        Design: Difficulty/resource_temporal_overlap/contract_aggregate_capacity_overlap
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-AGG2", legal_name="Agg2")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-AGG2", total_lbs=5000,
            fixed_price=2.00,
        )
        sh1 = book_shipment(contract["id"], shipment_ref="SH-A2-1",
                             planned_lbs=4000,
                             scheduled_arrival="2026-09-15T00:00:00Z")
        # Cancel the first shipment so its planned_lbs no longer counts.
        validate_success(api.cancel_shipment(sh1["id"], LOGISTICS))
        # Now 5000 more fits exactly against total_lbs.
        ok = validate_success(api.create_shipment(
            contract["id"],
            {"shipment_ref": "SH-A2-2", "planned_lbs": 5000,
             "scheduled_arrival": "2026-09-20T00:00:00Z"},
            LOGISTICS,
        ), 201)
        assert ok["id"]
