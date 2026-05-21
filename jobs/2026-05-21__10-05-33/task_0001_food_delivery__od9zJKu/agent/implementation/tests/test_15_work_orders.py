"""Work Orders lifecycle (§3.10)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _deliver_order(c):
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=2000)
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
    return rest, cust, rider, o


@test("Customer opens work order with category and related_order_id")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "DELIVERY_LATE", "related_order_id": o["id"]})
    assert s == 201
    assert b["data"]["status"] == "OPEN"
    assert b["data"]["opened_by_role"] == "CUSTOMER"
    assert b["data"]["opened_by_id"] == cust["id"]


@test("invalid category -> ERR_VALIDATION")
def t():
    c = Client()
    cust = make_customer(c)
    expect_err(c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                      body={"category": "NOT_A_CATEGORY"}),
               "ERR_VALIDATION", http=422)


@test("non-existent related_order_id -> ERR_NOT_FOUND")
def t():
    c = Client()
    cust = make_customer(c)
    expect_err(c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                      body={"category": "DELIVERY_LATE", "related_order_id": "nope"}),
               "ERR_NOT_FOUND", http=404)


@test("WO lifecycle: OPEN -> assign -> UNDER_REVIEW")
def t():
    c = Client()
    cust = make_customer(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    s, b = c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    assert s == 200 and b["data"]["status"] == "UNDER_REVIEW"
    assert b["data"]["assigned_cs_user_id"] == "cs1"


@test("WO: request-info -> AWAITING_INFO, submit-info -> UNDER_REVIEW")
def t():
    c = Client()
    cust = make_customer(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    s, b = c.post(f"/api/work-orders/{wo['id']}/request-info", role="CustomerService", user_id="cs1")
    assert b["data"]["status"] == "AWAITING_INFO"
    s, b = c.post(f"/api/work-orders/{wo['id']}/submit-info", role="Customer", user_id=cust["id"])
    assert b["data"]["status"] == "UNDER_REVIEW"


@test("submit-info by wrong opener -> ERR_FORBIDDEN")
def t():
    c = Client()
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust1["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    c.post(f"/api/work-orders/{wo['id']}/request-info", role="CustomerService", user_id="cs1")
    expect_err(c.post(f"/api/work-orders/{wo['id']}/submit-info", role="Customer", user_id=cust2["id"]),
               "ERR_FORBIDDEN", http=403)


@test("WO escalate UNDER_REVIEW -> ESCALATED, resolve from ESCALATED -> RESOLVED")
def t():
    c = Client()
    cust = make_customer(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    s, b = c.post(f"/api/work-orders/{wo['id']}/escalate", role="CustomerService", user_id="cs1")
    assert b["data"]["status"] == "ESCALATED"
    s, b = c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
                  body={"resolution_notes": "Fixed."})
    assert b["data"]["status"] == "RESOLVED"
    assert b["data"]["resolution_notes"] == "Fixed."


@test("WO close RESOLVED -> CLOSED")
def t():
    c = Client()
    cust = make_customer(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
           body={"resolution_notes": "Done"})
    s, b = c.post(f"/api/work-orders/{wo['id']}/close", role="CustomerService", user_id="cs1")
    assert b["data"]["status"] == "CLOSED"


@test("resolve WO whose related_return is REQUESTED -> ERR_RELATED_RETURN_UNRESOLVED")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "FOOD_QUALITY", "related_return_id": ret["id"]})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    expect_err(c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
                      body={"resolution_notes": "Done"}),
               "ERR_RELATED_RETURN_UNRESOLVED", http=422)


@test("resolve WO whose related_return is APPROVED -> OK")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "FOOD_QUALITY", "related_return_id": ret["id"]})
    wo = b["data"]
    c.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs1")
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs1",
           body={"approved_refund_cents": 500})
    s, b = c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
                  body={"resolution_notes": "Refund issued"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"


@test("resolve before assign -> ERR_INVALID_STATE (no assigned_cs_user_id)")
def t():
    c = Client()
    cust = make_customer(c)
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    expect_err(c.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs1",
                      body={"resolution_notes": "Done"}),
               "ERR_INVALID_STATE", http=409)


@test("CS role opens WO with opened_by_role CUSTOMER_SERVICE")
def t():
    c = Client()
    s, b = c.post("/api/work-orders", role="CustomerService", user_id="cs5",
                  body={"category": "OTHER"})
    assert s == 201
    assert b["data"]["opened_by_role"] == "CUSTOMER_SERVICE"
    assert b["data"]["opened_by_id"] == "cs5"


@test("Customer cannot read other customer's WO")
def t():
    c = Client()
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    s, b = c.post("/api/work-orders", role="Customer", user_id=cust1["id"],
                  body={"category": "OTHER"})
    wo = b["data"]
    expect_err(c.get(f"/api/work-orders/{wo['id']}", role="Customer", user_id=cust2["id"]),
               "ERR_FORBIDDEN", http=403)


@test("Return escalation auto-opens WO; reopen auto-closes it")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs1")
    from app.store import store
    wos = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]]
    assert len(wos) == 1 and wos[0]["status"] == "OPEN"
    c.post(f"/api/returns/{ret['id']}/reopen", role="CustomerService", user_id="cs1")
    wos = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]]
    assert wos[0]["status"] == "CLOSED"
