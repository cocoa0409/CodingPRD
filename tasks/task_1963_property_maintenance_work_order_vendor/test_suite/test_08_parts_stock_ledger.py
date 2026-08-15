"""Stock ledger: reserve/release rules, boundaries, cross-property scope, and
the compensating invariant on quantity_on_hand + reserved_quantity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_part,
    create_property,
    create_resident,
    create_technician,
    create_work_order,
    dispatch_in_house,
    get_part,
    make_technician_headers,
    reserve_part,
    setup_assigned_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestReserveRules:
    def test_reserve_exceeding_stock_rejected(self, api):
        """PRD §3.6: "The part must belong to the same property as the work order, and its `quantity_on_hand` must be at least the requested quantity — taking the last unit on the shelf is allowed; a shortfall, a foreign-property part, or an invalid quantity is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409)."

        Design: Corner/validations/reserve_exceeding_stock_rejected
        """
        bundle = setup_assigned_work_order("Stock2 Property", unit_number="407")
        part = create_part(bundle["property"]["id"], sku="SCR-1", name="Screw",
                           unit_cost_cents=10, reorder_level=0, initial_stock=2)
        resp = api.reserve_part(
            bundle["work_order"]["id"],
            {"part_id": part["id"], "quantity": 3},
            make_technician_headers(bundle["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PART_INSUFFICIENT_STOCK)
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 2
        assert after["reserved_quantity"] == 0

    def test_reserve_exact_on_hand_boundary(self, api):
        """PRD §3.6: "The part must belong to the same property as the work order, and its `quantity_on_hand` must be at least the requested quantity — taking the last unit on the shelf is allowed; a shortfall, a foreign-property part, or an invalid quantity is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409)."

        Design: Corner/validations/reserve_exact_on_hand_boundary
        """
        bundle = setup_assigned_work_order("Exact Property", unit_number="408")
        part = create_part(bundle["property"]["id"], sku="BLT-1", name="Bolt",
                           unit_cost_cents=20, reorder_level=0, initial_stock=2)
        tech = make_technician_headers(bundle["technician"]["id"])
        # Equality allowed: reserving exactly the 2 units on hand succeeds.
        line = reserve_part(bundle["work_order"]["id"], part["id"], 2, tech)
        assert line["status"] == "RESERVED"
        assert line["line_total_cents"] == 40, "2 * 20 snapshot"
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 0
        assert after["reserved_quantity"] == 2
        # One more unit exceeds the now-empty shelf.
        resp = api.reserve_part(
            bundle["work_order"]["id"], {"part_id": part["id"], "quantity": 1}, tech
        )
        validate_error(resp, ApiErrorId.ERR_PART_INSUFFICIENT_STOCK)

    def test_reserve_part_from_other_property_rejected(self, api):
        """PRD §2.11: "A part reserved against a work order must be stocked by the same property as the work order; a reservation request naming a part from a different property is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409)."

        Design: Corner/validations/reserve_part_from_other_property_rejected
        """
        prop_a = create_property("Prop A")
        prop_b = create_property("Prop B")
        resident = create_resident(prop_a["id"], unit_number="409", full_name="R Cross",
                                   email="rcross@x.com")
        tech = create_technician(prop_a["id"], trade="PLUMBING")
        foreign_part = create_part(prop_b["id"], sku="X-1", name="Foreign part",
                                   unit_cost_cents=100, reorder_level=0, initial_stock=10)
        wo = create_work_order(prop_a["id"], resident["id"],
                               description="Cross-property job")
        dispatch_in_house(wo["id"], tech["id"])
        resp = api.reserve_part(
            wo["id"],
            {"part_id": foreign_part["id"], "quantity": 1},
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PART_INSUFFICIENT_STOCK)
        assert get_part(foreign_part["id"])["quantity_on_hand"] == 10

    def test_reserve_zero_quantity_rejected(self, api):
        """PRD §3.6: "The reservation payload names a `part_id` and a `quantity` of at least 1."
        PRD §3.6: "The part must belong to the same property as the work order, and its `quantity_on_hand` must be at least the requested quantity — taking the last unit on the shelf is allowed; a shortfall, a foreign-property part, or an invalid quantity is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409)."

        Note: the PRD routes an invalid quantity to ERR_PART_INSUFFICIENT_STOCK (409);
        this test asserts the PRD-stated outcome for the zero-quantity edge.

        Design: Corner/validations/reserve_zero_quantity_rejected
        """
        bundle = setup_assigned_work_order("Zero Property", unit_number="415")
        part = create_part(bundle["property"]["id"], sku="NUT-1", name="Nut",
                           unit_cost_cents=5, reorder_level=0, initial_stock=10)
        resp = api.reserve_part(
            bundle["work_order"]["id"],
            {"part_id": part["id"], "quantity": 0},
            make_technician_headers(bundle["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PART_INSUFFICIENT_STOCK)
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 10
        assert after["reserved_quantity"] == 0


class TestRestockReconciliation:
    def test_restock_status_flips_low_on_reserve(self, api):
        """PRD §2.8: "After every ledger event, the part's `restock_status` is recomputed: it is `LOW_STOCK` whenever `quantity_on_hand` is less than or equal to the part's `reorder_level` (equality counts as low stock), and `IN_STOCK` otherwise."
        PRD §2.8: "The recomputation can flip the status in either direction — a release or a purchase receipt can lift a part back to `IN_STOCK`, and a reservation can push it down to `LOW_STOCK`."

        Design: Corner/complexity_layers/restock_status_reconciles_on_reserve
        """
        bundle = setup_assigned_work_order("Restock Property", unit_number="703")
        part = create_part(bundle["property"]["id"], sku="VLV-2", name="Valve",
                           unit_cost_cents=500, reorder_level=2, initial_stock=5)
        assert part["restock_status"] == "IN_STOCK", "5 > 2 at creation"
        reserve_part(
            bundle["work_order"]["id"], part["id"], 4,
            make_technician_headers(bundle["technician"]["id"]),
        )
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 1
        assert after["reserved_quantity"] == 4
        assert after["restock_status"] == "LOW_STOCK", "1 <= 2 after reserving 4"


class TestReserveReleaseInvariant:
    def _setup_reserved(self, api):
        bundle = setup_assigned_work_order("Stock Property", unit_number="117")
        part = create_part(bundle["property"]["id"], sku="GSK-1", name="Gasket",
                           unit_cost_cents=250, reorder_level=0, initial_stock=5)
        line = reserve_part(
            bundle["work_order"]["id"], part["id"], 3,
            make_technician_headers(bundle["technician"]["id"]),
        )
        return bundle, part, line

    def test_reserve_debits_on_hand_into_reserved(self, api):
        """PRD §2.8: "A reservation decreases `quantity_on_hand` and increases `reserved_quantity` by the reserved amount."

        Design: Difficulty/compensating_invariant/part_reserve_release_conserves_stock
        """
        _, part, _ = self._setup_reserved(api)
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 2
        assert after["reserved_quantity"] == 3
        assert after["quantity_on_hand"] + after["reserved_quantity"] == 5, (
            "reserve conserves on_hand + reserved at the initial stock level"
        )

    def test_release_reverses_reserve_exactly(self, api):
        """PRD §2.8: "A release reverses a reservation exactly, so a reserve followed by its compensating release leaves the sum of `quantity_on_hand` plus `reserved_quantity` unchanged."

        Design: Difficulty/compensating_invariant/part_reserve_release_conserves_stock
        """
        bundle, part, line = self._setup_reserved(api)
        tech = make_technician_headers(bundle["technician"]["id"])
        resp = api.release_part(bundle["work_order"]["id"], line["id"], {}, tech)
        released = validate_success(resp, 200)
        assert released["status"] == "RELEASED"
        after = get_part(part["id"])
        assert after["quantity_on_hand"] == 5
        assert after["reserved_quantity"] == 0
        assert after["quantity_on_hand"] + after["reserved_quantity"] == 5


class TestCancelReleasesReservedParts:
    def test_cancel_from_assigned_releases_reservations(self, api):
        """PRD §3.5: "Cancelling from `ASSIGNED` carries a release cascade: every work-order-part line still `RESERVED` moves to `RELEASED`, each released line's quantity is added back to its part's `quantity_on_hand` and subtracted from `reserved_quantity`, and each affected part's `restock_status` is recomputed; the assignment fields are cleared."

        Design: Corner/endpoints/cancel_releases_reserved_parts
        """
        bundle = setup_assigned_work_order("Cxl Property", unit_number="505")
        part = create_part(bundle["property"]["id"], sku="CLP-1", name="Clamp",
                           unit_cost_cents=30, reorder_level=0, initial_stock=3)
        line = reserve_part(
            bundle["work_order"]["id"], part["id"], 2,
            make_technician_headers(bundle["technician"]["id"]),
        )
        mid = get_part(part["id"])
        assert (mid["quantity_on_hand"], mid["reserved_quantity"]) == (1, 2)

        resp = api.cancel_work_order(
            bundle["work_order"]["id"], {"reason": "resident unavailable"}, DISPATCHER
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

        line_after = validate_success(
            api.get_work_order_part(line["id"], MANAGER), 200
        )
        assert line_after["status"] == "RELEASED"
        part_after = get_part(part["id"])
        assert part_after["quantity_on_hand"] == 3
        assert part_after["reserved_quantity"] == 0
