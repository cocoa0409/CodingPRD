"""Fines: scoped list/read, waive reverses ledger."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def _create_no_show_fine(c, ids):
    """Drive an assignment to ACCEPTED then cancel to mint a RIDER_NO_SHOW fine. Returns (rider_id, fine_id)."""
    rider = register_rider(c, phone="r-fines-a")
    # Need a 2nd rider so cancellation's redispatch can still find a candidate (not required)
    register_rider(c, phone="r-fines-b")
    _, body = place_order(c, ids)
    oid = body["data"]["id"]
    c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
    from app.server import store
    aid = next(a["id"] for a in store.assignments.values()
               if a["order_id"] == oid and a["status"] == "OFFERED")
    accepting_rider = store.assignments[aid]["rider_id"]
    c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=accepting_rider)
    c.post(f"/api/assignments/{aid}/cancel", role="Rider", user_id=accepting_rider)
    fid = next(f["id"] for f in store.fines.values()
               if f["reason"] == "RIDER_NO_SHOW" and f["subject_id"] == accepting_rider)
    return accepting_rider, fid


def run(suite):
    def list_scoped_to_own_for_rider():
        c, ids = setup_basics()
        r1, _ = _create_no_show_fine(c, ids)
        # Another fine for a different rider
        c2, ids2 = setup_basics()
        r2, _ = _create_no_show_fine(c2, ids2)
        # r1 must not see r2's fines
        s, body = c.get("/api/fines", role="Rider", user_id=r1)
        assert s == 200
        for f in body["data"]:
            assert f["subject_id"] == r1

    def waive_reverses_wallet_debit():
        c, ids = setup_basics()
        rider, fid = _create_no_show_fine(c, ids)
        s, body = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        wallet_before = body["data"]["wallet_balance_cents"]
        s, body = c.post(f"/api/fines/{fid}/waive",
                         role="CustomerService", user_id="cs-1")
        assert s == 200 and body["data"]["settlement_status"] == "WAIVED"
        s, body = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        assert body["data"]["wallet_balance_cents"] == wallet_before + 500

    def cannot_waive_settled():
        c, ids = setup_basics()
        rider, fid = _create_no_show_fine(c, ids)
        from app.server import store
        store.fines[fid]["settlement_status"] = "SETTLED"
        s, e = c.post(f"/api/fines/{fid}/waive",
                      role="CustomerService", user_id="cs-1")
        assert s == 409

    def rider_cannot_query_other_rider():
        c, ids = setup_basics()
        rider, fid = _create_no_show_fine(c, ids)
        # Try to query with a different rider as the X-User-ID + explicit subject_id pointing at our rider
        s, e = c.get(f"/api/fines?subject_id={rider}",
                     role="Rider", user_id="other-rider")
        assert s == 403

    def restaurant_fine_settles_on_settle():
        """A restaurant fine in PENDING moves to SETTLED when /settle clears that restaurant's balance."""
        c, ids = setup_basics()
        from app.services.fines import create_fine
        f = create_fine("RESTAURANT", ids["rid"], "RESTAURANT_STOCKOUT", 300)
        fid = f["id"]
        from app.server import store
        assert store.fines[fid]["settlement_status"] == "PENDING"
        # Settle the restaurant — clears pending_settlement_cents and graduates the fine to SETTLED.
        s, _ = c.post(f"/api/restaurants/{ids['rid']}/settle",
                      role="PlatformAdmin", user_id="op")
        assert s == 200
        assert store.fines[fid]["settlement_status"] == "SETTLED"

    suite.case("rider sees only own fines on /api/fines", list_scoped_to_own_for_rider)
    suite.case("waive PENDING -> WAIVED + ledger reversed", waive_reverses_wallet_debit)
    suite.case("waive SETTLED -> ERR_INVALID_STATE", cannot_waive_settled)
    suite.case("rider cannot query another rider's fines", rider_cannot_query_other_rider)
    suite.case("restaurant fine -> SETTLED when /settle clears balance",
               restaurant_fine_settles_on_settle)
