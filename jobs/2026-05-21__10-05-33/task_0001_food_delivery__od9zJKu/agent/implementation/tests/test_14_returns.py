"""Returns workflow (§3.9): open, approve, reject, escalate, reopen."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _deliver_order(c, *, item_price=1000, qty=1):
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=item_price)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": qty}])
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


@test("open return on DELIVERED order: order -> REFUND_REQUESTED, return REQUESTED")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    assert s == 201
    assert b["data"]["status"] == "REQUESTED"
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["status"] == "REFUND_REQUESTED"


@test("open return on non-DELIVERED order -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100}),
               "ERR_INVALID_STATE", http=409)


@test("return outside 24-hour window -> ERR_RETURN_WINDOW_EXPIRED")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    # Advance past 24h
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 25 * 3600})
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500}),
               "ERR_RETURN_WINDOW_EXPIRED", http=422)


@test("requested_refund < 1 -> ERR_REFUND_AMOUNT_INVALID")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 0}),
               "ERR_REFUND_AMOUNT_INVALID", http=422)


@test("requested_refund > subtotal -> ERR_REFUND_AMOUNT_INVALID")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=1000, qty=1)  # subtotal=1000
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 2000}),
               "ERR_REFUND_AMOUNT_INVALID", http=422)


@test("duplicate return while first is REQUESTED -> ERR_DUPLICATE_RETURN")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    assert s == 201
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "WRONG_ITEM", "requested_refund_cents": 100}),
               "ERR_DUPLICATE_RETURN", http=409)


@test("approve return: order -> REFUNDED, customer credit + restaurant pending -")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    # pending after delivery: subtotal 2000 - commission 300 = 1700
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    ret = b["data"]
    s, b = c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
                  body={"approved_refund_cents": 500})
    assert s == 200 and b["data"]["status"] == "APPROVED"
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["status"] == "REFUNDED"
    assert ob["data"]["payment_status"] == "PARTIALLY_REFUNDED"
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 500
    s, rb = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    assert rb["data"]["pending_settlement_cents"] == 1700 - 500


@test("approve refund == subtotal -> FULLY_REFUNDED")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=1000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 1000})
    ret = b["data"]
    s, b = c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
                  body={"approved_refund_cents": 1000})
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["payment_status"] == "FULLY_REFUNDED"


@test("approved_refund > requested_refund -> ERR_REFUND_AMOUNT_INVALID")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    expect_err(c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
                      body={"approved_refund_cents": 600}),
               "ERR_REFUND_AMOUNT_INVALID", http=422)


@test("reject return reverts order to DELIVERED with no monetary change")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    s, b = c.post(f"/api/returns/{ret['id']}/reject", role="CustomerService")
    assert s == 200 and b["data"]["status"] == "REJECTED"
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["status"] == "DELIVERED"
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 0
    s, rb = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    assert rb["data"]["pending_settlement_cents"] == 1700  # unchanged


@test("escalate return REQUESTED -> ESCALATED + WorkOrder opened linked via related_return_id")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    s, b = c.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService")
    assert s == 200 and b["data"]["status"] == "ESCALATED"
    from app.store import store
    wos = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]]
    assert len(wos) == 1
    assert wos[0]["status"] == "OPEN"


@test("reopen ESCALATED return -> REQUESTED, linked WorkOrder -> CLOSED")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService")
    s, b = c.post(f"/api/returns/{ret['id']}/reopen", role="CustomerService")
    assert s == 200 and b["data"]["status"] == "REQUESTED"
    from app.store import store
    wos = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]]
    assert wos[0]["status"] == "CLOSED"


@test("approve from ESCALATED also legal")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService")
    s, b = c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
                  body={"approved_refund_cents": 500})
    assert s == 200 and b["data"]["status"] == "APPROVED"


@test("reopen from non-ESCALATED -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    expect_err(c.post(f"/api/returns/{ret['id']}/reopen", role="CustomerService"),
               "ERR_INVALID_STATE", http=409)


@test("abusive return fine: trust_score < 0.5 + QUALITY_ISSUE creates ABUSIVE_RETURN fine")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    # Drop trust_score artificially
    from app.store import store
    store.customers[cust["id"]]["trust_score"] = 0.4
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
           body={"approved_refund_cents": 500})
    fines = [f for f in store.fines.values()
             if f["subject_type"] == "CUSTOMER" and f["subject_id"] == cust["id"]
             and f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 500


@test("abusive fine NOT created when reason is not QUALITY_ISSUE")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    from app.store import store
    store.customers[cust["id"]]["trust_score"] = 0.3
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
           body={"approved_refund_cents": 500})
    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 0


@test("abusive fine NOT created when trust_score >= 0.5")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c, item_price=2000)
    from app.store import store
    store.customers[cust["id"]]["trust_score"] = 0.5
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService",
           body={"approved_refund_cents": 500})
    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 0


@test("invalid reason value -> ERR_VALIDATION")
def t():
    c = Client()
    rest, cust, rider, o = _deliver_order(c)
    expect_err(c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                      body={"reason": "BAD_REASON", "requested_refund_cents": 500}),
               "ERR_VALIDATION", http=422)
