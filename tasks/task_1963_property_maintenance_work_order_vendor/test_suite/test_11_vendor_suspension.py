"""Vendor suspension cascade (three links deep) and reinstate semantics."""
from test_helpers import (
    TEST_USERS,
    create_part,
    create_property,
    create_resident,
    create_vendor,
    create_work_order,
    dispatch_to_vendor,
    get_part,
    get_work_order,
    make_vendor_headers,
    reserve_part,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_vendor_with_assigned_order_and_reservation(api):
    """Vendor V assigned to a work order (10:00-12:00); part (stock 5, reorder 2)
    has 3 units reserved on that order, leaving on_hand 2 / reserved 3 / LOW_STOCK."""
    prop = create_property("Cascade Property")
    resident = create_resident(prop["id"], unit_number="107", full_name="R Seven",
                               email="r7@x.com")
    vendor = create_vendor(prop["id"], company_name="V Co", trade="PLUMBING",
                           insurance_valid_until="2027-01-01T00:00:00Z")
    part = create_part(prop["id"], sku="PIPE-1", name="Pipe",
                       unit_cost_cents=100, reorder_level=2, initial_stock=5)
    wo = create_work_order(prop["id"], resident["id"], category="PLUMBING",
                           priority="ROUTINE", description="Vendor job")
    dispatch_to_vendor(wo["id"], vendor["id"])
    line = reserve_part(wo["id"], part["id"], 3, make_vendor_headers(vendor["id"]))
    mid = get_part(part["id"])
    assert (mid["quantity_on_hand"], mid["reserved_quantity"]) == (2, 3)
    assert mid["restock_status"] == "LOW_STOCK", "2 <= reorder_level 2 before the cascade"
    return {"property": prop, "resident": resident, "vendor": vendor,
            "part": part, "work_order": wo, "line": line}


class TestVendorSuspendCascade:
    def test_suspend_reverts_assigned_orders_and_clears_assignment(self, api):
        """PRD §3.8: "Suspending requires the vendor to be `ACTIVE`; the transition to `SUSPENDED` fires a three-link cascade across the vendor's book of work. Every work order currently `ASSIGNED` to this vendor reverts to `TRIAGED` with its assignment fields cleared — `assignment_type`, `assigned_vendor_id`, the scheduled window, `entry_authorization`, and `notice_posted_at` all become null — while its `first_responded_at` is retained, because the response SLA was already earned or breached at the original dispatch."

        Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth3
        """
        ctx = _setup_vendor_with_assigned_order_and_reservation(api)
        resp = api.vendor_event(
            ctx["vendor"]["id"],
            {"event_type": "SUSPEND", "reason": "lapsed paperwork"},
            MANAGER,
        )
        vendor = validate_success(resp, 200)
        assert vendor["status"] == "SUSPENDED"

        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["status"] == "TRIAGED", "cascade link 1: ASSIGNED -> TRIAGED"
        assert wo["assigned_vendor_id"] is None
        assert wo["assignment_type"] is None
        # The original first-response stamp is retained through the cascade.
        assert wo["first_responded_at"] is not None

    def test_suspend_releases_reservations_and_restores_stock(self, api):
        """PRD §3.8: "Each reverted work order's still-`RESERVED` part lines move to `RELEASED`, restoring each part's `quantity_on_hand` and reducing its `reserved_quantity` by the released amounts, with `restock_status` recomputed per part — which may flip a part from `LOW_STOCK` back to `IN_STOCK`."

        Design: Difficulty/transitive_cascade/vendor_suspend_cascade_depth3
        """
        ctx = _setup_vendor_with_assigned_order_and_reservation(api)
        validate_success(
            api.vendor_event(ctx["vendor"]["id"], {"event_type": "SUSPEND"}, MANAGER),
            200,
        )
        line = validate_success(
            api.get_work_order_part(ctx["line"]["id"], MANAGER), 200
        )
        assert line["status"] == "RELEASED", "cascade link 2: RESERVED -> RELEASED"

        part = get_part(ctx["part"]["id"])
        assert part["quantity_on_hand"] == 5, "cascade link 3: stock restored"
        assert part["reserved_quantity"] == 0
        assert part["restock_status"] == "IN_STOCK", "5 > 2 lifts the part back"


class TestVendorReinstate:
    def test_reinstate_does_not_restore_reverted_assignments(self, api):
        """PRD §3.8: "Reinstating requires the vendor to be `SUSPENDED` and returns it to `ACTIVE`. Nothing is auto-restored: work orders that reverted to `TRIAGED` stay triaged and require a fresh dispatch, subject to all the usual gates including the now-current insurance check."

        Design: Corner/state_machines/vendor_reinstate_does_not_restore_assignments
        """
        ctx = _setup_vendor_with_assigned_order_and_reservation(api)
        validate_success(
            api.vendor_event(ctx["vendor"]["id"], {"event_type": "SUSPEND"}, MANAGER),
            200,
        )
        resp = api.vendor_event(ctx["vendor"]["id"], {"event_type": "REINSTATE"}, MANAGER)
        vendor = validate_success(resp, 200)
        assert vendor["status"] == "ACTIVE"

        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["status"] == "TRIAGED", "no auto-restore to ASSIGNED"
        assert wo["assigned_vendor_id"] is None
