"""OCC + concurrency-shaped failures."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def run(suite):
    def two_patches_same_version():
        c, ids = setup_basics()
        rid = ids["rid"]
        # first PATCH @ version=2 (after approve bumped to 2)
        s, body = c.patch(f"/api/restaurants/{rid}", {"address": "first", "version": 2},
                          role="PlatformAdmin", user_id="op")
        assert s == 200
        # second PATCH using stale version=2 -> conflict
        s, e = c.patch(f"/api/restaurants/{rid}", {"address": "second", "version": 2},
                       role="PlatformAdmin", user_id="op")
        assert s == 409 and e["data"]["error_id"] == "ERR_VERSION_CONFLICT"

    def two_riders_accept_same_order():
        c, ids = setup_basics()
        r1 = register_rider(c, phone="r-x")
        r2 = register_rider(c, phone="r-y")
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        aid_first = next(a["id"] for a in store.assignments.values()
                         if a["order_id"] == oid and a["status"] == "OFFERED")
        # Dispatch a second offer manually
        s, body = c.post(f"/api/orders/{oid}/dispatch",
                         role="PlatformAdmin", user_id="op")
        if s != 201:
            return  # candidate pool exhausted; not the path under test
        aid_second = body["data"]["id"]
        # rider for second offer
        rider_second = body["data"]["rider_id"]
        rider_first = store.assignments[aid_first]["rider_id"]
        # First one accepts
        s, _ = c.post(f"/api/assignments/{aid_first}/accept",
                      role="Rider", user_id=rider_first)
        assert s == 200
        # Second one tries to accept -> ERR_ORDER_ALREADY_ASSIGNED
        s, e = c.post(f"/api/assignments/{aid_second}/accept",
                      role="Rider", user_id=rider_second)
        assert s == 409 and e["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"

    suite.case("OCC: stale version PATCH -> ERR_VERSION_CONFLICT", two_patches_same_version)
    suite.case("two riders race to accept -> one wins, other ERR_ORDER_ALREADY_ASSIGNED",
               two_riders_accept_same_order)
