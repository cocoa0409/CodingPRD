"""Final PRD-gap sweep — uniqueness, length bounds, and explicitly-listed branches."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _deliver_solo(c, *, item_price=1000):
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=item_price)
    cust = make_customer(c, lat=0.0, lng=0.0)
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


@test("PRD §3.3: rider phone must be unique across all riders")
def t():
    c = Client()
    make_rider(c, phone="555-0001", online=False)
    s, b = c.post("/api/riders", role="PlatformAdmin",
                  body={"name": "R2", "phone": "555-0001"})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("PRD §3.1: restaurant name>120 chars rejected with ERR_VALIDATION")
def t():
    c = Client()
    long_name = "X" * 121
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": long_name, "address": "a", "lat": 0.0, "lng": 0.0})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("PRD §3.1: restaurant name exactly 120 chars accepted")
def t():
    c = Client()
    name = "X" * 120
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": name, "address": "a", "lat": 0.0, "lng": 0.0})
    assert s == 201 and b["data"]["name"] == name


@test("PRD §3.11: SETTLED fines are not waivable")
def t():
    c = Client()
    # Create a fine via late delivery (tier 1)
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
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
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 50 * 60})  # 5 min late
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    fine = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"][0]
    # Force SETTLED state, then attempt waive
    fine["settlement_status"] = "SETTLED"
    expect_err(c.post(f"/api/fines/{fine['id']}/waive", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("PRD §3.11: WAIVED fines cannot be re-waived")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    # Force trust_score low to trigger ABUSIVE_RETURN fine on approve
    from app.store import store
    store.customers[cust["id"]]["trust_score"] = 0.4
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
           body={"approved_refund_cents": 500})
    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 1
    fid = fines[0]["id"]
    s, b = c.post(f"/api/fines/{fid}/waive", role="PlatformAdmin")
    assert s == 200
    # Second waive fails
    expect_err(c.post(f"/api/fines/{fid}/waive", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("PRD §3.9: return reject from ESCALATED state is allowed")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs1")
    s, b = c.post(f"/api/returns/{ret['id']}/reject", role="CustomerService", user_id="cs1")
    assert s == 200 and b["data"]["status"] == "REJECTED"


@test("PRD §3.6: SUSPENDED rider excluded from dispatch candidate pool")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
    # Suspend the only rider; dispatch must fail because pool is empty.
    from app.store import store
    r = store.riders[rider["id"]]
    r["on_time_rate"] = 0.2  # breach threshold
    c.post(f"/api/riders/{rider['id']}/suspend", role="PlatformAdmin")
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    # No assignment should exist because the suspended rider is excluded
    offers = [x for x in store.assignments.values() if x["order_id"] == o["id"]]
    assert len(offers) == 0
    # Explicit /dispatch also fails
    expect_err(c.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("PRD §2.10: is_peak frozen at placement -> final_delivery_fee uses placement-time is_peak")
def t():
    c = Client()
    # Nudge clock into the 11:00-13:00 UTC peak window before placing the order.
    # Use advance() since LogicalClock exposes only relative motion.
    from app.clock import clock
    import datetime as _dt
    now = clock.now()
    target_peak = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if target_peak <= now:
        target_peak += _dt.timedelta(days=1)
    c.post("/api/_clock/advance", role="PlatformAdmin",
           body={"seconds": int((target_peak - now).total_seconds())})
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.01, lng=0.0)  # ~1.11 km -> ceil=2 bands
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    assert o["is_peak"] is True, o
    # Provisional = 300 + 120*ceil(distance_km) + 200 (peak). With ~1.1 km -> 2 bands -> 740
    expected_peak_fee = 300 + 120 * 2 + 200
    assert o["provisional_delivery_fee_cents"] == expected_peak_fee, o
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    # Advance past the peak window: +5 hours -> 17:00 UTC (off-peak).
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 5 * 3600})
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    # Final fee uses frozen is_peak=true even though we're now off-peak
    assert ob["data"]["final_delivery_fee_cents"] == expected_peak_fee, ob["data"]


@test("PRD §3.7: explicit RouteGroup-of-one scenario carries no discount")
def t():
    c = Client()
    rest, cust, rider, o, a = _deliver_solo(c, item_price=1000)
    # Solo delivery: route_group_id should be null and final fee equals solo fee
    from app.store import store
    a2 = store.assignments[a["id"]]
    assert a2.get("route_group_id") in (None, "")
    # Final fee equals provisional (no discount)
    assert a2["final_delivery_fee_cents"] == o["provisional_delivery_fee_cents"]


@test("PRD §3.10: PlatformAdmin opens WO; opened_by_role recorded as CUSTOMER_SERVICE per enum")
def t():
    c = Client()
    # PRD §3.10 enum lists CUSTOMER, RIDER, RESTAURANT, CUSTOMER_SERVICE only.
    # A PlatformAdmin opener maps to CUSTOMER_SERVICE.
    s, b = c.post("/api/work-orders", role="PlatformAdmin",
                  body={"category": "OTHER"})
    assert s == 201
    assert b["data"]["opened_by_role"] == "CUSTOMER_SERVICE"


@test("PRD §3.10: CustomerService opens a WorkOrder with opened_by_role=CUSTOMER_SERVICE")
def t():
    c = Client()
    s, b = c.post("/api/work-orders", role="CustomerService", user_id="cs1",
                  body={"category": "OTHER"})
    assert s == 201
    assert b["data"]["opened_by_role"] == "CUSTOMER_SERVICE"


@test("PRD §3.1: name uniqueness applies only among ACTIVE restaurants")
def t():
    c = Client()
    # Register a restaurant; it starts PENDING_APPROVAL. Register another with same name -> OK?
    # PRD says "unique among active restaurants" — so two PENDING with same name should be fine,
    # but once one is ACTIVE, the other duplicate attempt must fail.
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Same", "address": "a", "lat": 0.0, "lng": 0.0})
    r1 = b["data"]
    # Approve r1 (-> ACTIVE)
    c.post(f"/api/restaurants/{r1['id']}/approve", role="PlatformAdmin")
    # Now try to register r2 with the same name — must fail
    expect_err(c.post("/api/restaurants", role="PlatformAdmin",
                      body={"name": "Same", "address": "b", "lat": 0.0, "lng": 0.0}),
               "ERR_VALIDATION", http=422)
