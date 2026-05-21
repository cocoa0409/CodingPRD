"""Tests for §3.2 (Customer Accounts), §3.3 (Rider Lifecycle and Bonus Standing)."""
from __future__ import annotations

from .harness import test


@test("customer: register initializes credit_balance_cents=0 and trust_score=1.0")
def t1(ctx):
    c = ctx.register_customer()
    assert c["credit_balance_cents"] == 0
    assert c["trust_score"] == 1.0


@test("customer: phone uniqueness")
def t2(ctx):
    ctx.register_customer(phone="555-0001")
    s, b = ctx.post("/api/customers", role="PlatformAdmin", user_id="a",
                    json_body={"name": "Dup", "phone": "555-0001",
                                "address": "x", "lat": 1, "lng": 2})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("rider: register starts OFFLINE/BRONZE")
def t3(ctx):
    r = ctx.register_rider()
    assert r["status"] == "OFFLINE"
    assert r["bonus_tier"] == "BRONZE"
    assert r["wallet_balance_cents"] == 0
    assert r["on_time_rate"] == 1.0
    assert r["acceptance_rate"] == 1.0
    assert r["rating"] == 5.0


@test("rider: go-online OFFLINE → AVAILABLE")
def t4(ctx):
    r = ctx.register_rider()
    s, b = ctx.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"])
    assert s == 200 and b["data"]["status"] == "AVAILABLE"


@test("rider: go-online when AVAILABLE → ERR_INVALID_STATE")
def t5(ctx):
    r = ctx.register_rider()
    ctx.go_online(r)
    s, b = ctx.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("rider: identity mismatch on go-online → ERR_FORBIDDEN")
def t6(ctx):
    r1 = ctx.register_rider(name="R1", phone="p1")
    r2 = ctx.register_rider(name="R2", phone="p2")
    s, b = ctx.post(f"/api/riders/{r2['id']}/go-online", role="Rider", user_id=r1["id"])
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN"


@test("rider: go-offline succeeds when no active assignment")
def t7(ctx):
    r = ctx.register_rider()
    ctx.go_online(r)
    s, b = ctx.post(f"/api/riders/{r['id']}/go-offline", role="Rider", user_id=r["id"])
    assert s == 200 and b["data"]["status"] == "OFFLINE"


@test("rider: suspend rejected when metrics ok → ERR_SUSPEND_CRITERIA_NOT_MET")
def t8(ctx):
    r = ctx.register_rider()
    ctx.go_online(r)
    s, b = ctx.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin", user_id="a")
    assert s == 422 and b["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"


@test("rider: suspend allowed when acceptance_rate < 0.5")
def t9(ctx):
    r = ctx.register_rider()
    ctx.go_online(r)
    with ctx.app.config["STORE"].lock:
        ctx.app.config["STORE"].riders[r["id"]]["acceptance_rate"] = 0.49
    s, b = ctx.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin", user_id="a")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"


@test("rider: suspend allowed when on_time_rate < 0.70")
def t10(ctx):
    r = ctx.register_rider()
    ctx.go_online(r)
    with ctx.app.config["STORE"].lock:
        ctx.app.config["STORE"].riders[r["id"]]["on_time_rate"] = 0.69
    s, b = ctx.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin", user_id="a")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"


@test("rider: suspend requires AVAILABLE → ERR_INVALID_STATE for OFFLINE")
def t11(ctx):
    r = ctx.register_rider()
    s, b = ctx.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin", user_id="a")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("bonus tier: 0.900 → PLATINUM, 0.800 → GOLD, 0.700 → SILVER boundaries")
def t12(ctx):
    from app.bonus import recompute_bonus_tier
    # Construct rider dicts directly.
    def tier(on_time, accept, rating):
        r = {"on_time_rate": on_time, "acceptance_rate": accept, "rating": rating, "bonus_tier": "BRONZE"}
        recompute_bonus_tier(r)
        return r["bonus_tier"]
    # 0.6*1 + 0.3*1 + 0.1*5/5 = 1.0 → PLATINUM
    assert tier(1.0, 1.0, 5.0) == "PLATINUM"
    # Construct a score of exactly 0.900: 0.6*1.0 + 0.3*1.0 + 0.1*0.0 = 0.9 → PLATINUM
    assert tier(1.0, 1.0, 0.0) == "PLATINUM"
    # Score of exactly 0.800: 0.6 * (4/3) is 0.8 — keep it simple:
    # 0.6*x + 0.3*x + 0.1*x/5 = score → use on_time/accept/rating equally.
    # Solve: on_time=accept=0.8, rating=4 → 0.48 + 0.24 + 0.08 = 0.8 → GOLD
    assert tier(0.8, 0.8, 4.0) == "GOLD"
    # 0.700: on_time=accept=0.7, rating=3.5 → 0.42 + 0.21 + 0.07 = 0.7 → SILVER
    assert tier(0.7, 0.7, 3.5) == "SILVER"
    # Below: 0.6, 0.6, 3.0 → 0.36 + 0.18 + 0.06 = 0.6 → BRONZE
    assert tier(0.6, 0.6, 3.0) == "BRONZE"


@test("customer: register requires role PlatformAdmin or CustomerService")
def t13(ctx):
    s, b = ctx.post("/api/customers", role="Rider", user_id="x",
                    json_body={"name": "n", "phone": "p", "address": "a", "lat": 1, "lng": 2})
    assert s == 403


@test("rider: rider can read only self")
def t14(ctx):
    r1 = ctx.register_rider(phone="p1")
    r2 = ctx.register_rider(phone="p2")
    s, b = ctx.get(f"/api/riders/{r1['id']}", role="Rider", user_id=r1["id"])
    assert s == 200
    s, b = ctx.get(f"/api/riders/{r2['id']}", role="Rider", user_id=r1["id"])
    assert s == 403


@test("rider: go-offline blocked by live OFFERED assignment → ERR_INVALID_STATE")
def t15(ctx):
    rest = ctx.make_active_restaurant(lat=40.0, lng=-74.0)
    mi = ctx.add_menu_item(rest["id"], price_cents=500)
    cust = ctx.register_customer(lat=40.01, lng=-74.01)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    ctx.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    r = ctx.register_rider(); ctx.go_online(r)
    ctx.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    # Rider now has an OFFERED assignment but is still AVAILABLE.
    s, b = ctx.post(f"/api/riders/{r['id']}/go-offline", role="Rider", user_id=r["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"
