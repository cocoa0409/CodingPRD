"""Coverage for remaining PRD branches & error paths."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _deliver_solo(c, *, item_price=1000, distance_lat=0.0, distance_lng=0.0):
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=item_price)
    cust = make_customer(c, lat=distance_lat, lng=distance_lng)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    return rest, cust, rider, o, a


@test("PATCH restaurant cannot change name (immutable)")
def t():
    c = Client()
    rest = make_restaurant(c, name="Orig")
    # Send a name field - should be ignored or rejected. Per PRD: 'name' is immutable.
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"name": "Renamed"})
    # Name stays "Orig"
    assert b["data"]["name"] == "Orig"


@test("placement payment_status=AUTHORIZED at placement-time side effect")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert b["data"]["payment_status"] == "AUTHORIZED"


@test("delivery moves payment_status to CAPTURED unconditionally")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["payment_status"] == "CAPTURED"


@test("rider returns to AVAILABLE after final solo delivery")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, rb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rb["data"]["status"] == "AVAILABLE"


@test("late fine tier 3 with fee>=1500 clamps to 1500+500=2000")
def t():
    c = Client()
    # Long distance (~5.5 km): solo fee = 300 + 120*6 = 1020; not high enough.
    # We need solo fee >= 1500 -> need ceil(km) >= 10 -> 9.0001 km ~> 0.081 lat
    # Or use peak too: 300 + 120*ceil + 200. 1500-500=1000, /120=8.33, ceil=9.
    # With peak=200, 300+120*ceil+200 >= 1500 -> 120*ceil >= 1000 -> ceil >= 9 -> distance > 8.0 km
    # Easier: forcibly set is_peak after placement won't help; use distance 9.5 km off-peak: 300+120*10=1500.
    # 0.086 lat ~ 9.55 km
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.086, lng=0.0)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    assert o["provisional_delivery_fee_cents"] >= 1500, o
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 80 * 60})  # 35 late
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    # min(fee, 1500) + 500 = 1500 + 500 = 2000
    assert len(fines) == 1
    assert fines[0]["amount_cents"] == 2000, fines[0]


@test("approved_refund < subtotal -> payment_status=PARTIALLY_REFUNDED")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
           body={"approved_refund_cents": 500})
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["payment_status"] == "PARTIALLY_REFUNDED"


@test("Return reason=LATE accepted")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "LATE", "requested_refund_cents": 200})
    assert s == 201 and b["data"]["reason"] == "LATE"


@test("Return reason=OTHER accepted")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "OTHER", "requested_refund_cents": 100})
    assert s == 201 and b["data"]["reason"] == "OTHER"


@test("Rider opens WO with opened_by_role=RIDER")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    s, b = c.post("/api/work-orders", role="Rider", user_id=rider["id"],
                  body={"category": "RIDER_BEHAVIOR"})
    assert s == 201
    assert b["data"]["opened_by_role"] == "RIDER"
    assert b["data"]["opened_by_id"] == rider["id"]


@test("Restaurant opens WO with opened_by_role=RESTAURANT")
def t():
    c = Client()
    rest = make_restaurant(c)
    s, b = c.post("/api/work-orders", role="Restaurant", user_id=rest["id"],
                  body={"category": "RESTAURANT_BEHAVIOR"})
    assert s == 201
    assert b["data"]["opened_by_role"] == "RESTAURANT"


@test("WO with related_return in REJECTED status: resolve allowed")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/reject", role="CustomerService", user_id="cs1")
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "FOOD_QUALITY", "related_return_id": ret["id"]})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    s, b = c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
                  body={"resolution_notes": "Closed"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"


@test("GET /api/assignments/{id} returns Assignment with correct projection")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    s, b = c.get(f"/api/assignments/{a['id']}", role="PlatformAdmin")
    assert s == 200
    assert b["data"]["id"] == a["id"]
    assert b["data"]["status"] == "OFFERED"


@test("GET /api/returns/{id} accessible to customer who owns the order")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "OTHER", "requested_refund_cents": 100})
    ret = b["data"]
    s, b = c.get(f"/api/returns/{ret['id']}", role="Customer", user_id=cust["id"])
    assert s == 200 and b["data"]["id"] == ret["id"]


@test("Restaurant accept race vs customer cancel: first-writer wins")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    # Cancel first
    s, _ = c.post(f"/api/orders/{o['id']}/cancel", role="Customer", user_id=cust["id"])
    assert s == 200
    # Then accept should fail
    expect_err(c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"]),
               "ERR_INVALID_STATE", http=409)


@test("PlatformAdmin can edit menu-item price")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    s, b = c.patch(f"/api/menu-items/{mi['id']}", role="PlatformAdmin",
                   body={"price_cents": 2500})
    assert s == 200 and b["data"]["price_cents"] == 2500


@test("Order list filter by rider_id")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    s, b = c.get("/api/orders", role="PlatformAdmin", query={"rider_id": rider["id"]})
    assert any(x["id"] == o["id"] for x in b["data"])


@test("restaurant list filter by status=ACTIVE")
def t():
    c = Client()
    make_restaurant(c, name="A")
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Pending", "address": "x", "lat": 0, "lng": 0})
    s, b = c.get("/api/restaurants", role="Customer", user_id="anyone",
                 query={"status": "ACTIVE"})
    assert all(r["status"] == "ACTIVE" for r in b["data"])
    assert len(b["data"]) == 1


@test("distance_km rounded to 1 decimal place")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c, lat=0.01, lng=0.01)  # ~1.57 km
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    d = b["data"]["distance_km"]
    # Verify 1-decimal: only one digit after the decimal point
    assert round(d, 1) == d, d
    assert 1.4 <= d <= 1.7


@test("rider tie-break created_at desc: newest rider wins among AVAILABLE peers")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    r1 = make_rider(c, phone="R1", online=True)
    r2 = make_rider(c, phone="R2", online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    # r2 is newer (created after r1) so should win
    assert a["rider_id"] == r2["id"], f"expected newest rider {r2['id']}, got {a['rider_id']}"


@test("dispatch tier-2 fallback to AVAILABLE when no merge-eligible ON_DELIVERY rider")
def t():
    c = Client()
    # Single rider, on a route that's too far from the new order's restaurant
    rest1 = make_restaurant(c, name="A", lat=0.0, lng=0.0)
    rest2 = make_restaurant(c, name="B", lat=0.5, lng=0.5)  # ~70 km away
    mi1 = make_menu_item(c, rest1["id"])
    mi2 = make_menu_item(c, rest2["id"])
    cust = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
    # Order 1 at rest1, rider accepts
    s, b = place_order(c, customer=cust, restaurant=rest1,
                       items=[{"menu_item_id": mi1["id"], "quantity": 1}])
    o1 = b["data"]
    c.post(f"/api/orders/{o1['id']}/accept", role="Restaurant", user_id=rest1["id"])
    c.post(f"/api/orders/{o1['id']}/start-preparing", role="Restaurant", user_id=rest1["id"])
    from app.store import store
    a1 = [x for x in store.assignments.values() if x["order_id"] == o1["id"]][0]
    c.post(f"/api/assignments/{a1['id']}/accept", role="Rider", user_id=rider["id"])
    # Order 2 at far rest2: rider is ON_DELIVERY but NOT merge-eligible.
    # Per PRD they still go in the candidate pool (just not tier 0) and dispatch should pick them.
    cust2 = make_customer(c, phone="P2", lat=0.5, lng=0.5)
    s, b = place_order(c, customer=cust2, restaurant=rest2,
                       items=[{"menu_item_id": mi2["id"], "quantity": 1}])
    o2 = b["data"]
    c.post(f"/api/orders/{o2['id']}/accept", role="Restaurant", user_id=rest2["id"])
    c.post(f"/api/orders/{o2['id']}/start-preparing", role="Restaurant", user_id=rest2["id"])
    a2 = [x for x in store.assignments.values() if x["order_id"] == o2["id"] and x["status"] == "OFFERED"][0]
    # Single rider, must pick them despite ON_DELIVERY
    assert a2["rider_id"] == rider["id"]


@test("rider excluded from re-offer for an order they already held")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/reject", role="Rider", user_id=rider["id"])
    # No other rider available -> redispatch should fail (the only rider was excluded)
    new_offers = [x for x in store.assignments.values() if x["order_id"] == o["id"] and x["status"] == "OFFERED"]
    assert len(new_offers) == 0  # no fresh offer because the only candidate was excluded
