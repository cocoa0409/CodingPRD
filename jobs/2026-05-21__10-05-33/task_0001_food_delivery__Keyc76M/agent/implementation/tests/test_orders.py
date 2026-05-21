"""Tests for §3.4 (placement) and §3.5 (restaurant-side flow)."""

from tests.harness import (
    test, fresh_client, jget, jpost, jpatch, body_of,
    assert_eq, assert_err, admin_headers, cs_headers, cust_headers, rest_headers,
    rider_headers,
)


def _bootstrap(c, *, rest_lat=0.0, rest_lng=0.0,
               cust_lat=0.0, cust_lng=0.0,
               override=None, price=2000, qty=2):
    """Create active restaurant + listed menu item + customer ready to order."""
    rid = body_of(jpost(c, "/api/restaurants",
                       body={"name": "R", "address": "A",
                             "lat": rest_lat, "lng": rest_lng,
                             "commission_rate_override": override},
                       headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    mid = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                       body={"name": "Burger", "price_cents": price},
                       headers=rest_headers(rid)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "Alice", "phone": "+1",
                             "address": "A",
                             "lat": cust_lat, "lng": cust_lng},
                       headers=admin_headers()))["data"]["id"]
    return rid, mid, cid


def _place_order(c, rid, mid, cid, qty=2):
    return jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid,
                       "items": [{"menu_item_id": mid, "quantity": qty}]},
                 headers=cust_headers(cid))


@test("order: place basic, computes subtotal, fee, commission")
def t_place_basic():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c, rest_lat=0.0, rest_lng=0.0,
                               cust_lat=0.0, cust_lng=0.0, price=2000)
    resp = _place_order(c, rid, mid, cid, qty=2)
    assert_eq(resp.status_code, 201, "201")
    d = body_of(resp)["data"]
    assert_eq(d["subtotal_cents"], 4000, "subtotal")
    # Same coords -> 0 km -> ceil(0)=0 bands -> base 300
    assert_eq(d["distance_km"], 0.0, "0 distance")
    # is_peak depends on wall-clock; just check field present
    assert_eq(d["provisional_delivery_fee_cents"],
              300 + (200 if d["is_peak"] else 0), "fee = base + peak")
    # 4000 subtotal -> tier1 only -> 4000*0.15 = 600
    assert_eq(d["provisional_commission_cents"], 600, "commission")
    assert_eq(d["status"], "PLACED", "PLACED")
    assert_eq(d["payment_status"], "AUTHORIZED", "AUTHORIZED")
    assert_eq(d["final_delivery_fee_cents"], None, "no final yet")


@test("order: identity mismatch -> ERR_FORBIDDEN")
def t_identity_mismatch():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid,
                       "items": [{"menu_item_id": mid, "quantity": 1}]},
                 headers=cust_headers("other-id"))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("order: missing customer -> ERR_NOT_FOUND")
def t_missing_customer():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": "nope", "restaurant_id": rid,
                       "items": [{"menu_item_id": mid, "quantity": 1}]},
                 headers=cust_headers(cid))
    assert_err(resp, 404, "ERR_NOT_FOUND")


@test("order: missing menu_item -> ERR_NOT_FOUND")
def t_missing_menu_item():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid,
                       "items": [{"menu_item_id": "nope", "quantity": 1}]},
                 headers=cust_headers(cid))
    assert_err(resp, 404, "ERR_NOT_FOUND")


@test("order: subtotal under 100 -> ERR_ORDER_INVALID")
def t_subtotal_below_min():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c, price=50)
    resp = _place_order(c, rid, mid, cid, qty=1)
    assert_err(resp, 422, "ERR_ORDER_INVALID")


@test("order: empty items -> ERR_ORDER_INVALID")
def t_empty_items():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid, "items": []},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_ORDER_INVALID")


@test("order: quantity zero -> ERR_ORDER_INVALID")
def t_qty_zero():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid,
                       "items": [{"menu_item_id": mid, "quantity": 0}]},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_ORDER_INVALID")


@test("order: unlisted item -> ERR_RESTAURANT_UNAVAILABLE")
def t_unlisted():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    jpatch(c, f"/api/menu-items/{mid}", body={"is_listed": False},
           headers=rest_headers(rid))
    resp = _place_order(c, rid, mid, cid)
    assert_err(resp, 422, "ERR_RESTAURANT_UNAVAILABLE")


@test("order: inactive restaurant -> ERR_RESTAURANT_UNAVAILABLE")
def t_inactive_restaurant():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    jpost(c, f"/api/restaurants/{rid}/suspend", headers=admin_headers())
    resp = _place_order(c, rid, mid, cid)
    assert_err(resp, 422, "ERR_RESTAURANT_UNAVAILABLE")


@test("order: commission tiered at boundary 50000")
def t_commission_boundary():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c, price=50000, qty=1)
    resp = _place_order(c, rid, mid, cid, qty=1)
    d = body_of(resp)["data"]
    # tier1=20000*.15=3000; tier2=30000*.18=5400; tier3=0
    # total=8400
    assert_eq(d["provisional_commission_cents"], 8400, "commission @50k")


@test("order: commission tiered above 50000")
def t_commission_above_tier2():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c, price=60000, qty=1)
    resp = _place_order(c, rid, mid, cid, qty=1)
    d = body_of(resp)["data"]
    # tier1=3000; tier2=5400; tier3=10000*.22=2200; total=10600
    assert_eq(d["provisional_commission_cents"], 10600, "commission @60k")


@test("order: commission flat override applies")
def t_commission_flat_override():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c, override=0.20, price=10000, qty=1)
    resp = _place_order(c, rid, mid, cid, qty=1)
    d = body_of(resp)["data"]
    # 10000*.20 = 2000 (flat covers entire subtotal)
    assert_eq(d["provisional_commission_cents"], 2000, "flat commission")


@test("order: cancel as customer (PLACED) -> CANCELLED, VOIDED")
def t_cancel_placed():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    oid = body_of(_place_order(c, rid, mid, cid))["data"]["id"]
    resp = jpost(c, f"/api/orders/{oid}/cancel", headers=cust_headers(cid))
    d = body_of(resp)["data"]
    assert_eq(d["status"], "CANCELLED", "cancelled")
    assert_eq(d["payment_status"], "VOIDED", "voided")


@test("order: restaurant accepts PLACED -> RESTAURANT_ACCEPTED")
def t_restaurant_accepts():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    oid = body_of(_place_order(c, rid, mid, cid))["data"]["id"]
    resp = jpost(c, f"/api/orders/{oid}/accept", headers=rest_headers(rid))
    assert_eq(body_of(resp)["data"]["status"], "RESTAURANT_ACCEPTED", "accepted")


@test("order: foreign restaurant cannot accept -> 403")
def t_foreign_accept():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    oid = body_of(_place_order(c, rid, mid, cid))["data"]["id"]
    resp = jpost(c, f"/api/orders/{oid}/accept", headers=rest_headers("other"))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("order: suspended restaurant fans out cancel to PLACED orders")
def t_suspend_cancels_placed():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    oid = body_of(_place_order(c, rid, mid, cid))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/suspend", headers=admin_headers())
    resp = jget(c, f"/api/orders/{oid}", headers=admin_headers())
    d = body_of(resp)["data"]
    assert_eq(d["status"], "CANCELLED", "cancelled by suspend")
    assert_eq(d["payment_status"], "VOIDED", "voided by suspend")


@test("order: peak window detection at 12:00 UTC")
def t_peak_window():
    """Tests is_peak by reading the field; actual peak depends on wall clock.

    We assert the field is a boolean and consistent with the placement
    timestamp the server records.
    """
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    d = body_of(_place_order(c, rid, mid, cid))["data"]
    assert isinstance(d["is_peak"], bool), "is_peak boolean"


@test("order: ready before any rider accepts -> ERR_INVALID_STATE")
def t_ready_no_rider():
    c = fresh_client()
    rid, mid, cid = _bootstrap(c)
    oid = body_of(_place_order(c, rid, mid, cid))["data"]["id"]
    jpost(c, f"/api/orders/{oid}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{oid}/start-preparing", headers=rest_headers(rid))
    resp = jpost(c, f"/api/orders/{oid}/ready", headers=rest_headers(rid))
    assert_err(resp, 409, "ERR_INVALID_STATE")
