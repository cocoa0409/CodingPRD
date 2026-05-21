"""Tests for §3.6 route merging."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err, admin_headers, cust_headers, rest_headers, rider_headers,
)


def _setup_two_restaurants_one_rider(c, sep_meters=200):
    """Build two restaurants near each other, one rider, one customer.

    Two km roughly equals 0.018 degrees of lat at the equator. 200 m ≈ 0.0018.
    """
    deg = sep_meters / 1000.0 / 111.0  # km/deg latitude ≈ 111
    r1 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "A", "address": "x",
                            "lat": 0.0, "lng": 0.0},
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r1}/approve", headers=admin_headers())
    r2 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "B", "address": "y",
                            "lat": deg, "lng": 0.0},
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r2}/approve", headers=admin_headers())
    m1 = body_of(jpost(c, f"/api/restaurants/{r1}/menu-items",
                      body={"name": "I1", "price_cents": 2000},
                      headers=rest_headers(r1)))["data"]["id"]
    m2 = body_of(jpost(c, f"/api/restaurants/{r2}/menu-items",
                      body={"name": "I2", "price_cents": 3000},
                      headers=rest_headers(r2)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "z", "lat": 0.5, "lng": 0.5},
                       headers=admin_headers()))["data"]["id"]
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+9"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))
    return r1, r2, m1, m2, cid, rrid


def _place_and_dispatch(c, rid, mid, cid):
    order = body_of(jpost(c, "/api/orders",
                          body={"customer_id": cid, "restaurant_id": rid,
                                "items": [{"menu_item_id": mid, "quantity": 1}]},
                          headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    return order


def _find_offer(c, oid):
    import state
    cands = [a for a in state.STORE.assignments.values()
             if a["order_id"] == oid and a["status"] == "OFFERED"]
    return cands[0] if cands else None


@test("merge: second acceptance within 500m creates RouteGroup")
def t_merge_creates_rg():
    c = fresh_client()
    r1, r2, m1, m2, cid, rrid = _setup_two_restaurants_one_rider(c, sep_meters=200)
    o1 = _place_and_dispatch(c, r1, m1, cid)
    off1 = _find_offer(c, o1["id"])
    jpost(c, f"/api/assignments/{off1['id']}/accept",
          headers=rider_headers(rrid))
    o2 = _place_and_dispatch(c, r2, m2, cid)
    off2 = _find_offer(c, o2["id"])
    jpost(c, f"/api/assignments/{off2['id']}/accept",
          headers=rider_headers(rrid))
    a1 = body_of(jget(c, f"/api/assignments/{off1['id']}",
                      headers=rider_headers(rrid)))["data"]
    a2 = body_of(jget(c, f"/api/assignments/{off2['id']}",
                      headers=rider_headers(rrid)))["data"]
    assert a1["route_group_id"] is not None, "a1 in route group"
    assert_eq(a1["route_group_id"], a2["route_group_id"], "same group")


@test("merge: second pickup farther than 500m stays solo")
def t_solo_when_far():
    c = fresh_client()
    r1, r2, m1, m2, cid, rrid = _setup_two_restaurants_one_rider(c, sep_meters=2000)
    o1 = _place_and_dispatch(c, r1, m1, cid)
    off1 = _find_offer(c, o1["id"])
    jpost(c, f"/api/assignments/{off1['id']}/accept",
          headers=rider_headers(rrid))
    o2 = _place_and_dispatch(c, r2, m2, cid)
    off2 = _find_offer(c, o2["id"])
    jpost(c, f"/api/assignments/{off2['id']}/accept",
          headers=rider_headers(rrid))
    a1 = body_of(jget(c, f"/api/assignments/{off1['id']}",
                      headers=rider_headers(rrid)))["data"]
    a2 = body_of(jget(c, f"/api/assignments/{off2['id']}",
                      headers=rider_headers(rrid)))["data"]
    assert a1["route_group_id"] is None, "a1 solo"
    assert a2["route_group_id"] is None, "a2 solo"


@test("merge: discount applied on merged delivery (25% floored)")
def t_merge_discount():
    """We use a customer far enough from both restaurants so the solo fee
    becomes large enough for the discount to be testable."""
    c = fresh_client()
    # Customer ≈ 5 km away from restaurants
    deg = 5.0 / 111.0
    r1 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "A", "address": "x",
                            "lat": 0.0, "lng": 0.0},
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r1}/approve", headers=admin_headers())
    r2 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "B", "address": "y",
                            "lat": 0.0005, "lng": 0.0},  # ~55m offset
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r2}/approve", headers=admin_headers())
    m1 = body_of(jpost(c, f"/api/restaurants/{r1}/menu-items",
                      body={"name": "I", "price_cents": 1500},
                      headers=rest_headers(r1)))["data"]["id"]
    m2 = body_of(jpost(c, f"/api/restaurants/{r2}/menu-items",
                      body={"name": "I", "price_cents": 1500},
                      headers=rest_headers(r2)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "z", "lat": deg, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+9"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))

    o1 = _place_and_dispatch(c, r1, m1, cid)
    off1 = _find_offer(c, o1["id"])
    jpost(c, f"/api/assignments/{off1['id']}/accept",
          headers=rider_headers(rrid))
    o2 = _place_and_dispatch(c, r2, m2, cid)
    off2 = _find_offer(c, o2["id"])
    jpost(c, f"/api/assignments/{off2['id']}/accept",
          headers=rider_headers(rrid))

    # Mark ready (rider is ACCEPTED on both)
    jpost(c, f"/api/orders/{o1['id']}/ready", headers=rest_headers(r1))
    jpost(c, f"/api/orders/{o2['id']}/ready", headers=rest_headers(r2))
    jpost(c, f"/api/assignments/{off1['id']}/pickup", headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{off2['id']}/pickup", headers=rider_headers(rrid))
    # deliver first
    a1 = body_of(jpost(c, f"/api/assignments/{off1['id']}/deliver",
                       headers=rider_headers(rrid)))["data"]
    # Solo fee at ~5km: base 300 + ceil(5)*120 = 300+600 = 900 (off-peak)
    # Discount = floor(900*0.25) = 225 -> final = 675
    # In peak: 900+200=1100, discount=275 -> final=825
    # Just verify final < solo
    import compute
    o1_after = body_of(jget(c, f"/api/orders/{o1['id']}",
                            headers=admin_headers()))["data"]
    solo = compute.solo_delivery_fee_cents(o1_after["distance_km"],
                                           o1_after["is_peak"])
    expected = solo - compute.merge_discount_cents(solo)
    assert_eq(a1["final_delivery_fee_cents"], expected, "merge discount applied")
    assert_eq(o1_after["final_delivery_fee_cents"], expected, "mirrored on order")
