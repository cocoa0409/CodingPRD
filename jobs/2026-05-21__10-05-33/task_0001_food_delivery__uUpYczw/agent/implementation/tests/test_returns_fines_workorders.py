"""Tests for §3.9 (Returns/Refunds), §3.10 (WorkOrders), §3.11 (Fines)."""
from __future__ import annotations

from .harness import test


def _deliver(ctx, *, price=10000, minutes_late=0):
    rest = ctx.make_active_restaurant(lat=40.0, lng=-74.0)
    mi = ctx.add_menu_item(rest["id"], price_cents=price)
    cust = ctx.register_customer(lat=40.001, lng=-74.001)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    ctx.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    if minutes_late > 0:
        ctx.clock_advance((45 + minutes_late) * 60)
    ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    return rest, cust, o, rider, a


@test("return: open within 24h → REQUESTED, order REFUND_REQUESTED")
def t1(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 5000})
    assert s == 201 and b["data"]["status"] == "REQUESTED"
    s, ob = ctx.get(f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["status"] == "REFUND_REQUESTED"


@test("return: outside 24h → ERR_RETURN_WINDOW_EXPIRED")
def t2(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    ctx.clock_advance(25 * 3600)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 5000})
    assert s == 422 and b["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"


@test("return: refund out of range → ERR_REFUND_AMOUNT_INVALID")
def t3(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 0})
    assert s == 422 and b["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 99999})
    assert s == 422 and b["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


@test("return: duplicate active return → ERR_DUPLICATE_RETURN")
def t4(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    assert s == 201
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    assert s == 409 and b["data"]["error_id"] == "ERR_DUPLICATE_RETURN"


@test("return approve: credit balance up, settlement down, order REFUNDED + PARTIALLY_REFUNDED")
def t5(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 4000})
    ret = b["data"]
    s, b = ctx.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs-1",
                     json_body={"approved_refund_cents": 3000})
    assert s == 200 and b["data"]["status"] == "APPROVED"
    s, ob = ctx.get(f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["status"] == "REFUNDED"
    assert ob["data"]["payment_status"] == "PARTIALLY_REFUNDED"
    s, cb = ctx.get(f"/api/customers/{cust['id']}", role="PlatformAdmin", user_id="a")
    assert cb["data"]["credit_balance_cents"] == 3000
    s, rb = ctx.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", user_id="a")
    assert rb["data"]["pending_settlement_cents"] == 10000 - 1500 - 3000


@test("return approve: full refund → FULLY_REFUNDED")
def t6(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "WRONG_ITEM", "requested_refund_cents": 10000})
    ret = b["data"]
    s, b = ctx.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs-1",
                     json_body={"approved_refund_cents": 10000})
    assert s == 200
    s, ob = ctx.get(f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["payment_status"] == "FULLY_REFUNDED"


@test("return approve: amount > requested → ERR_REFUND_AMOUNT_INVALID")
def t7(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    s, b = ctx.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs-1",
                     json_body={"approved_refund_cents": 1500})
    assert s == 422 and b["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


@test("return abusive: low trust + QUALITY_ISSUE → ABUSIVE_RETURN fine")
def t8(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    with ctx.app.config["STORE"].lock:
        ctx.app.config["STORE"].customers[cust["id"]]["trust_score"] = 0.3
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 2000})
    ret = b["data"]
    ctx.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs-1",
              json_body={"approved_refund_cents": 2000})
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    abusive = [f for f in fb["data"] if f["reason"] == "ABUSIVE_RETURN"]
    assert len(abusive) == 1
    assert abusive[0]["amount_cents"] == 2000


@test("return reject: REJECTED + order back to DELIVERED, no monetary change")
def t9(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    s, b = ctx.post(f"/api/returns/{ret['id']}/reject", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "REJECTED"
    s, ob = ctx.get(f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["status"] == "DELIVERED"
    s, cb = ctx.get(f"/api/customers/{cust['id']}", role="PlatformAdmin", user_id="a")
    assert cb["data"]["credit_balance_cents"] == 0


@test("return escalate: REQUESTED → ESCALATED opens linked WO")
def t10(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    s, b = ctx.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "ESCALATED"
    store = ctx.app.config["STORE"]
    with store.lock:
        linked = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]]
    assert len(linked) == 1


@test("return reopen: ESCALATED → REQUESTED closes linked WO")
def t11(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    ctx.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/returns/{ret['id']}/reopen", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "REQUESTED"
    store = ctx.app.config["STORE"]
    with store.lock:
        wo = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]][0]
    assert wo["status"] == "CLOSED"


@test("fine waive: PENDING → WAIVED, wallet restored")
def t12(ctx):
    rest, cust, o, rider, a = _deliver(ctx, price=10000, minutes_late=5)
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    fine = fb["data"][0]
    pre_wallet = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")[1]["data"]["wallet_balance_cents"]
    s, b = ctx.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["settlement_status"] == "WAIVED"
    post_wallet = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")[1]["data"]["wallet_balance_cents"]
    assert post_wallet == pre_wallet + fine["amount_cents"]


@test("fine waive: not PENDING → ERR_INVALID_STATE")
def t13(ctx):
    rest, cust, o, rider, a = _deliver(ctx, price=10000, minutes_late=5)
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    fine = fb["data"][0]
    ctx.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs-1")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("fine list: subject_id must match X-User-ID for Rider/Restaurant/Customer")
def t14(ctx):
    rest, cust, o, rider, a = _deliver(ctx, price=10000, minutes_late=5)
    # As Rider, query own fines
    s, fb = ctx.get("/api/fines", role="Rider", user_id=rider["id"],
                     query={"subject_id": rider["id"]})
    assert s == 200 and fb["meta"]["total_count"] >= 1
    # As Rider, query other rider's fines → ERR_FORBIDDEN
    other = ctx.register_rider(phone="other")
    s, fb = ctx.get("/api/fines", role="Rider", user_id=rider["id"],
                     query={"subject_id": other["id"]})
    assert s == 403


@test("wo: open with category — opener_role/id must match caller")
def t15(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "FOOD_QUALITY"})
    assert s == 201
    # Different opened_by_id → ERR_FORBIDDEN
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": "other",
                                "category": "FOOD_QUALITY"})
    assert s == 403


@test("wo: assign by CS claims ticket and moves to UNDER_REVIEW")
def t16(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wo = b["data"]
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-7")
    assert s == 200 and b["data"]["status"] == "UNDER_REVIEW"
    assert b["data"]["assigned_cs_user_id"] == "cs-7"


@test("wo: request-info → AWAITING_INFO; opener submit-info → UNDER_REVIEW")
def t17(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wo = b["data"]
    ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/request-info", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "AWAITING_INFO"
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/submit-info", role="Customer", user_id=c["id"])
    assert s == 200 and b["data"]["status"] == "UNDER_REVIEW"


@test("wo: resolve requires assigned_cs_user_id non-null")
def t18(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wo = b["data"]
    # Resolve attempted from OPEN: not UNDER_REVIEW/ESCALATED → ERR_INVALID_STATE
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs-1",
                     json_body={"resolution_notes": "n"})
    assert s == 409


@test("wo: resolve with unresolved related return → ERR_RELATED_RETURN_UNRESOLVED")
def t19(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    # Escalate creates a linked WO automatically
    ctx.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs-1")
    store = ctx.app.config["STORE"]
    with store.lock:
        wo = [w for w in store.work_orders.values() if w.get("related_return_id") == ret["id"]][0]
    ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-1")
    # Return still ESCALATED → unresolved
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs-1",
                     json_body={"resolution_notes": "n"})
    assert s == 422 and b["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"


@test("wo: resolve then close → RESOLVED then CLOSED")
def t20(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wo = b["data"]
    ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs-1",
                     json_body={"resolution_notes": "ok"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/close", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "CLOSED"


@test("return approve from ESCALATED is legal (§3.9)")
def t21(ctx):
    rest, cust, o, *_ = _deliver(ctx, price=10000)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 1000})
    ret = b["data"]
    ctx.post(f"/api/returns/{ret['id']}/escalate", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs-1",
                     json_body={"approved_refund_cents": 1000})
    assert s == 200 and b["data"]["status"] == "APPROVED"


@test("wo: escalate UNDER_REVIEW → ESCALATED → resolve")
def t22(ctx):
    c = ctx.register_customer()
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wo = b["data"]
    ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/escalate", role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "ESCALATED"
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/resolve", role="CustomerService", user_id="cs-1",
                     json_body={"resolution_notes": "supervisor ok"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"


@test("wo: submit-info identity mismatch → ERR_FORBIDDEN")
def t23(ctx):
    c1 = ctx.register_customer(phone="c1")
    c2 = ctx.register_customer(phone="c2")
    s, b = ctx.post("/api/work-orders", role="Customer", user_id=c1["id"],
                     json_body={"opened_by_role": "CUSTOMER", "opened_by_id": c1["id"],
                                "category": "OTHER"})
    wo = b["data"]
    ctx.post(f"/api/work-orders/{wo['id']}/assign", role="CustomerService", user_id="cs-1")
    ctx.post(f"/api/work-orders/{wo['id']}/request-info", role="CustomerService", user_id="cs-1")
    s, b = ctx.post(f"/api/work-orders/{wo['id']}/submit-info", role="Customer", user_id=c2["id"])
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN"
