"""Peak windows and clock advance + offer timeout sweep (§2.10)."""
from __future__ import annotations

import datetime as _dt

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


@test("peak detection: 11:00-13:00 UTC is peak")
def t():
    from app.peak import is_peak_time
    assert is_peak_time(_dt.datetime(2025, 5, 24, 11, 0, tzinfo=_dt.timezone.utc)) is True
    assert is_peak_time(_dt.datetime(2025, 5, 24, 12, 59, tzinfo=_dt.timezone.utc)) is True
    assert is_peak_time(_dt.datetime(2025, 5, 24, 13, 0, tzinfo=_dt.timezone.utc)) is False


@test("peak detection: 18:00-20:00 UTC is peak")
def t():
    from app.peak import is_peak_time
    assert is_peak_time(_dt.datetime(2025, 5, 24, 18, 0, tzinfo=_dt.timezone.utc)) is True
    assert is_peak_time(_dt.datetime(2025, 5, 24, 19, 30, tzinfo=_dt.timezone.utc)) is True
    assert is_peak_time(_dt.datetime(2025, 5, 24, 20, 0, tzinfo=_dt.timezone.utc)) is False


@test("peak detection: off-peak times")
def t():
    from app.peak import is_peak_time
    assert is_peak_time(_dt.datetime(2025, 5, 24, 9, 0, tzinfo=_dt.timezone.utc)) is False
    assert is_peak_time(_dt.datetime(2025, 5, 24, 14, 0, tzinfo=_dt.timezone.utc)) is False
    assert is_peak_time(_dt.datetime(2025, 5, 24, 22, 0, tzinfo=_dt.timezone.utc)) is False


@test("placement with peak injected: is_peak=true and final fee adds 200")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
    # Patch clock to peak window
    from app.clock import clock
    # Snapshot current; advance to next 11:30 UTC
    real_now = _dt.datetime.now(_dt.timezone.utc)
    target = real_now.replace(hour=12, minute=0, second=0, microsecond=0)
    if target <= real_now:
        target += _dt.timedelta(days=1)
    delta = (target - real_now).total_seconds()
    clock.advance(delta)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    assert o["is_peak"] is True
    # solo at 0 km, peak = 300 + 200 = 500
    assert o["provisional_delivery_fee_cents"] == 500


@test("/api/_clock/advance with seconds=60 sweeps OFFERED assignment to REJECTED")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider1 = make_rider(c, phone="R1", online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    assert a["status"] == "OFFERED"
    # Advance clock past 60 seconds
    s, b = c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 61})
    assert s == 200
    assert b["data"]["swept_assignments"] == 1
    a2 = store.assignments[a["id"]]
    assert a2["status"] == "REJECTED"


@test("offer timeout sweep redispatches to next rider")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider1 = make_rider(c, phone="R1", online=True)
    rider2 = make_rider(c, phone="R2", online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    first_offer = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    first_rider = first_offer["rider_id"]
    other_rider = rider2["id"] if first_rider == rider1["id"] else rider1["id"]
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 61})
    # New OFFERED assignment now targets the other rider
    new_off = [x for x in store.assignments.values() if x["order_id"] == o["id"] and x["status"] == "OFFERED"]
    assert len(new_off) == 1
    assert new_off[0]["rider_id"] == other_rider


@test("/api/_clock/advance with negative seconds -> ERR_VALIDATION")
def t():
    c = Client()
    expect_err(c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": -10}),
               "ERR_VALIDATION", http=422)


@test("/api/_clock/advance non-admin -> ERR_FORBIDDEN")
def t():
    c = Client()
    expect_err(c.post("/api/_clock/advance", role="Customer", user_id="c1", body={"seconds": 5}),
               "ERR_FORBIDDEN", http=403)


@test("promised_delivery_time = placement + 45 minutes")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    from app.store import store
    actual = store.orders[o["id"]]
    placed = _dt.datetime.fromisoformat(actual["created_at"].replace("Z", "+00:00"))
    promised = _dt.datetime.fromisoformat(o["promised_delivery_time"].replace("Z", "+00:00"))
    delta = (promised - placed).total_seconds()
    assert 44 * 60 <= delta <= 46 * 60, f"delta={delta}"
