"""Clock advance + 60s offer-timeout sweep."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def run(suite):
    def advance_requires_admin():
        c = Client()
        s, _ = c.post("/api/_clock/advance", {"seconds": 1}, role="Customer", user_id="x")
        assert s == 403

    def offer_timeout_sweep():
        c, ids = setup_basics()
        rider = register_rider(c)
        # Place + start-preparing -> assignment OFFERED
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        aid = next(a["id"] for a in store.assignments.values()
                   if a["order_id"] == oid and a["status"] == "OFFERED")
        # Advance > 60s
        s, body = c.post("/api/_clock/advance", {"seconds": 61},
                         role="PlatformAdmin", user_id="op")
        assert s == 200
        assert body["data"]["swept_offers"] >= 1
        # The original assignment should be REJECTED
        s, a = c.get(f"/api/assignments/{aid}",
                     role="PlatformAdmin", user_id="op")
        assert a["data"]["status"] == "REJECTED"
        # A fresh offer should not exist because there's only one rider and they were the candidate
        # for this order. After their rejection, dispatch finds no candidate (same rider still excluded
        # only if it has a live assignment for this order; since the old one is REJECTED, they could
        # be re-offered). PRD says the system never re-offers an order to a rider who already holds it
        # — meaning "still holds" via OFFERED/ACCEPTED/PICKED_UP. REJECTED is not a live holding.
        # So a new OFFERED should exist targeting the same rider.
        new = [a for a in store.assignments.values()
               if a["order_id"] == oid and a["status"] == "OFFERED"]
        assert len(new) == 1

    def advance_below_60s_does_not_sweep():
        c, ids = setup_basics()
        rider = register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        s, body = c.post("/api/_clock/advance", {"seconds": 30},
                         role="PlatformAdmin", user_id="op")
        assert body["data"]["swept_offers"] == 0

    suite.case("/api/_clock/advance restricted to PlatformAdmin", advance_requires_admin)
    suite.case("clock advance > 60s sweeps OFFERED -> REJECTED + redispatch", offer_timeout_sweep)
    suite.case("advance < 60s leaves OFFERED alone", advance_below_60s_does_not_sweep)
