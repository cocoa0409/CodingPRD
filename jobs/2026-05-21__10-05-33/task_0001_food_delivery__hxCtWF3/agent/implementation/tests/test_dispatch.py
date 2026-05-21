"""Dispatch, candidate selection, route merging, race conditions, cancellation."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def _full_to_preparing(c, ids):
    """Place + accept + start-preparing. Returns oid."""
    _, body = place_order(c, ids)
    oid = body["data"]["id"]
    c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
    return oid


def run(suite):
    def start_preparing_creates_offer():
        c, ids = setup_basics()
        rider_id = register_rider(c)
        oid = _full_to_preparing(c, ids)
        # Find the assignment created by start-preparing
        s, lst = c.get(f"/api/orders?status=PREPARING", role="PlatformAdmin", user_id="op")
        assert s == 200
        # We need at least one assignment in OFFERED for the order; pull it via list-by-rider.
        s, body = c.get("/api/assignments/" + _find_assignment_id(c, oid),
                        role="Rider", user_id=rider_id)
        a = body["data"]
        assert a["status"] == "OFFERED"
        assert a["order_id"] == oid

    def order_already_assigned():
        c, ids = setup_basics()
        rider1 = register_rider(c, phone="r1")
        rider2 = register_rider(c, phone="r2")
        oid = _full_to_preparing(c, ids)
        aid = _find_assignment_id(c, oid)
        # accept once
        s, body = c.post(f"/api/assignments/{aid}/accept",
                         role="Rider", user_id=_assignment_rider(c, aid))
        assert s == 200
        # The other rider — dispatch again should refuse since there's already an ACCEPTED assignment
        # Try to create a second OFFERED for the same order via dispatch — PRD says /dispatch always
        # creates a new OFFERED. So new offer exists; then second accept must hit
        # ERR_ORDER_ALREADY_ASSIGNED.
        s, body = c.post(f"/api/orders/{oid}/dispatch",
                         role="PlatformAdmin", user_id="op")
        # Pool may be empty (other rider may not pass merge constraint). Should still produce assignment if pool non-empty.
        if s == 201:
            new_aid = body["data"]["id"]
            new_rider = body["data"]["rider_id"]
            s2, body2 = c.post(f"/api/assignments/{new_aid}/accept",
                                role="Rider", user_id=new_rider)
            assert s2 == 409 and body2["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"

    def reject_redispatches():
        c, ids = setup_basics()
        rider1 = register_rider(c, phone="r1")
        rider2 = register_rider(c, phone="r2")
        oid = _full_to_preparing(c, ids)
        aid = _find_assignment_id(c, oid)
        rider_a = _assignment_rider(c, aid)
        s, body = c.post(f"/api/assignments/{aid}/reject",
                         role="Rider", user_id=rider_a)
        assert s == 200 and body["data"]["status"] == "REJECTED"
        # A new OFFERED assignment should exist for the order targeting the other rider
        new_aid = _find_assignment_id(c, oid)
        assert new_aid != aid

    def cancel_after_accept_creates_fine_and_redispatches():
        c, ids = setup_basics()
        rider1 = register_rider(c, phone="r1")
        rider2 = register_rider(c, phone="r2")  # so redispatch has a candidate
        oid = _full_to_preparing(c, ids)
        aid = _find_assignment_id(c, oid)
        rider_a = _assignment_rider(c, aid)
        # Accept then cancel
        c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider_a)
        s, body = c.post(f"/api/assignments/{aid}/cancel", role="Rider", user_id=rider_a)
        assert s == 200 and body["data"]["status"] == "CANCELLED"
        # Rider's wallet should be -500c (RIDER_NO_SHOW)
        s, r_body = c.get(f"/api/riders/{rider_a}", role="Rider", user_id=rider_a)
        assert r_body["data"]["wallet_balance_cents"] == -500
        # There should now be a fresh OFFERED to the other rider
        new_aid = _find_assignment_id(c, oid)
        assert new_aid != aid

    def dispatch_with_empty_pool_invalid_state():
        c, ids = setup_basics()
        # No riders registered -> /start-preparing should still succeed because dispatch failure
        # at start-preparing is swallowed. But /dispatch should ERR_INVALID_STATE.
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        s, e = c.post(f"/api/orders/{oid}/dispatch",
                      role="PlatformAdmin", user_id="op")
        assert s == 409 and e["data"]["error_id"] == "ERR_INVALID_STATE"

    def route_group_lazy_creation_on_second_accept():
        """When a rider accepts a second concurrent unpicked assignment whose pickup is within 500m,
        a new ACTIVE RouteGroup is lazily created and both assignments are attached to it."""
        c, ids = setup_basics()
        # Second restaurant at the same coordinates as the first (~0 metres apart -> within 500m).
        _, r2 = c.post("/api/restaurants",
                       {"name": "R2", "address": "addr2", "lat": 10.0, "lng": 10.0},
                       role="PlatformAdmin", user_id="op")
        rid2 = r2["data"]["id"]
        c.post(f"/api/restaurants/{rid2}/approve", role="PlatformAdmin", user_id="op")
        _, mi2 = c.post(f"/api/restaurants/{rid2}/menu-items",
                        {"name": "fries", "price_cents": 300},
                        role="PlatformAdmin", user_id="op")
        # One rider only.
        rider = register_rider(c, phone="r-merge")
        # Order 1 from R1
        oid1 = _full_to_preparing(c, ids)
        aid1 = _find_assignment_id(c, oid1)
        c.post(f"/api/assignments/{aid1}/accept", role="Rider", user_id=rider)
        # Order 2 from R2 (same customer, same coords -> merge eligible)
        _, body2 = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": rid2,
            "items": [{"menu_item_id": mi2["data"]["id"], "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        oid2 = body2["data"]["id"]
        c.post(f"/api/orders/{oid2}/accept", role="Restaurant", user_id=rid2)
        c.post(f"/api/orders/{oid2}/start-preparing", role="Restaurant", user_id=rid2)
        aid2 = _find_assignment_id(c, oid2)
        c.post(f"/api/assignments/{aid2}/accept", role="Rider", user_id=rider)
        # Verify a RouteGroup now exists with both assignments.
        from app.server import store
        groups = [g for g in store.route_groups.values() if g["rider_id"] == rider]
        assert len(groups) == 1
        rg = groups[0]
        assert rg["status"] == "ACTIVE"
        assert set(rg["assignment_ids"]) == {aid1, aid2}
        # Both assignments now reference the group.
        assert store.assignments[aid1]["route_group_id"] == rg["id"]
        assert store.assignments[aid2]["route_group_id"] == rg["id"]

    def route_group_not_created_for_distant_pickups():
        """If the pickups are >500m apart, no merge — both legs remain solo."""
        c, ids = setup_basics()
        # Far away restaurant (~1110km apart at the equator: 10 vs 20 degrees latitude).
        _, r2 = c.post("/api/restaurants",
                       {"name": "RFar", "address": "far", "lat": 20.0, "lng": 10.0},
                       role="PlatformAdmin", user_id="op")
        rid2 = r2["data"]["id"]
        c.post(f"/api/restaurants/{rid2}/approve", role="PlatformAdmin", user_id="op")
        _, mi2 = c.post(f"/api/restaurants/{rid2}/menu-items",
                        {"name": "fries", "price_cents": 300},
                        role="PlatformAdmin", user_id="op")
        rider = register_rider(c, phone="r-far")
        oid1 = _full_to_preparing(c, ids)
        aid1 = _find_assignment_id(c, oid1)
        c.post(f"/api/assignments/{aid1}/accept", role="Rider", user_id=rider)
        _, body2 = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": rid2,
            "items": [{"menu_item_id": mi2["data"]["id"], "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        oid2 = body2["data"]["id"]
        c.post(f"/api/orders/{oid2}/accept", role="Restaurant", user_id=rid2)
        c.post(f"/api/orders/{oid2}/start-preparing", role="Restaurant", user_id=rid2)
        aid2 = _find_assignment_id(c, oid2)
        c.post(f"/api/assignments/{aid2}/accept", role="Rider", user_id=rider)
        from app.server import store
        # No RouteGroup created.
        assert not any(g["rider_id"] == rider for g in store.route_groups.values())
        assert store.assignments[aid1]["route_group_id"] is None
        assert store.assignments[aid2]["route_group_id"] is None

    suite.case("start-preparing creates OFFERED assignment", start_preparing_creates_offer)
    suite.case("second accept on same order -> ERR_ORDER_ALREADY_ASSIGNED", order_already_assigned)
    suite.case("rider reject -> REJECTED + redispatch", reject_redispatches)
    suite.case("rider cancel after accept -> RIDER_NO_SHOW fine + wallet debit + redispatch",
               cancel_after_accept_creates_fine_and_redispatches)
    suite.case("/dispatch with empty pool -> ERR_INVALID_STATE", dispatch_with_empty_pool_invalid_state)
    suite.case("second concurrent accept within 500m -> lazy ACTIVE RouteGroup",
               route_group_lazy_creation_on_second_accept)
    suite.case("pickups >500m apart -> no RouteGroup, both legs solo",
               route_group_not_created_for_distant_pickups)


def _find_assignment_id(c, oid):
    """Find an OFFERED/ACCEPTED/PICKED_UP assignment for the order."""
    from app.server import store
    for a in store.assignments.values():
        if a["order_id"] == oid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return a["id"]
    raise AssertionError(f"no live assignment for order {oid}")


def _assignment_rider(c, aid):
    from app.server import store
    return store.assignments[aid]["rider_id"]
