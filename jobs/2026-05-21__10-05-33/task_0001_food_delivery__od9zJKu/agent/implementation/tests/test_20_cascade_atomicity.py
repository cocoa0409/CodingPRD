"""Cascade atomicity & version increments (§2.8)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


@test("delivery cascade: order, restaurant, rider all bump version")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    initial_order_v = o["version"]
    s, rb = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    initial_rest_v = rb["data"]["version"]
    s, rrb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    initial_rider_v = rrb["data"]["version"]
    # Walk to delivery
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    # All versions must have increased
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["version"] > initial_order_v
    s, rb = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    assert rb["data"]["version"] > initial_rest_v
    s, rrb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rrb["data"]["version"] > initial_rider_v


@test("Assignment, RouteGroup, Fine carry id+created_at but NO version field in response")
def t():
    c = Client()
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
    a_id = [x["id"] for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    s, b = c.get(f"/api/assignments/{a_id}", role="PlatformAdmin")
    assert "version" not in b["data"]
    assert "updated_at" not in b["data"]
    assert "id" in b["data"] and "created_at" in b["data"]


@test("Standard envelope: meta carries api_request_id, api_request_timestamp; response_type=object")
def t():
    c = Client()
    rest = make_restaurant(c, name="E1")
    s, b = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    assert s == 200
    meta = b["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert "T" in meta["api_request_timestamp"]
    assert b["response_type"] == "object"


@test("Standard envelope: list -> response_type=array, meta has limit/offset/total_count/has_more")
def t():
    c = Client()
    s, b = c.get("/api/restaurants", role="PlatformAdmin")
    assert s == 200
    assert b["response_type"] == "array"
    for k in ("limit", "offset", "total_count", "has_more"):
        assert k in b["meta"], f"missing meta key {k}"


@test("Error envelope: data has error_id + message; response_type=error")
def t():
    c = Client()
    s, b = c.get("/api/restaurants/nope", role="PlatformAdmin")
    assert s == 404
    assert b["response_type"] == "error"
    assert "error_id" in b["data"] and "message" in b["data"]


@test("Aborted cascade leaves no partial commit (OCC fail on PATCH)")
def t():
    c = Client()
    rest = make_restaurant(c, name="ABC")
    addr_before = rest["address"]
    # Force OCC failure
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"address": "Should Not Apply", "version": 999})
    assert s == 409
    # Verify address is unchanged
    s, rb = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    assert rb["data"]["address"] == addr_before


@test("late delivery cascade: order updated, fine created, rider wallet debited, bonus_tier maybe shifts")
def t():
    c = Client()
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
    # Advance 80 minutes from placement -> 80-45=35 min late, triggers tier 3
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 80 * 60})
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["minutes_late"] >= 31
    # Tier 3 fine: amount = min(final_fee, 1500) + 500 = min(300,1500)+500 = 800
    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 800
    # Wallet = +300 fee - 800 fine = -500
    s, rb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rb["data"]["wallet_balance_cents"] == -500


@test("Rider suspend requires breached thresholds")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    # Both default rates start at 1.0 - should fail suspend
    expect_err(c.post(f"/api/riders/{rider['id']}/suspend", role="PlatformAdmin"),
               "ERR_SUSPEND_CRITERIA_NOT_MET", http=422)


@test("Rider suspend allowed when on_time_rate < 0.70")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    # Inject low on_time_rate
    from app.store import store
    r = store.riders[rider["id"]]
    r["on_time_rate"] = 0.5
    s, b = c.post(f"/api/riders/{rider['id']}/suspend", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"


@test("Rider suspend allowed when acceptance_rate < 0.50")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    from app.store import store
    r = store.riders[rider["id"]]
    r["acceptance_rate"] = 0.3
    s, b = c.post(f"/api/riders/{rider['id']}/suspend", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"
