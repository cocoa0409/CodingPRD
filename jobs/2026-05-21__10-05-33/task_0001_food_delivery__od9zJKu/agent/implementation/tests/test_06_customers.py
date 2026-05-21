"""Customer accounts (§3.2)."""
from __future__ import annotations

from ._factories import make_customer
from ._harness import Client, expect_err, expect_ok, test


@test("customer initial credit_balance=0, trust_score=1.0")
def t():
    c = Client()
    cust = make_customer(c)
    assert cust["credit_balance_cents"] == 0
    assert cust["trust_score"] == 1.0


@test("phone must be unique")
def t():
    c = Client()
    make_customer(c, phone="111-2222")
    s, b = c.post("/api/customers", role="PlatformAdmin",
                  body={"name": "x", "phone": "111-2222", "address": "a", "lat": 0, "lng": 0})
    assert s == 422


@test("customer can read only own record")
def t():
    c = Client()
    c1 = make_customer(c, phone="P1")
    c2 = make_customer(c, phone="P2")
    s, _ = c.get(f"/api/customers/{c1['id']}", role="Customer", user_id=c1["id"])
    assert s == 200
    s, b = c.get(f"/api/customers/{c2['id']}", role="Customer", user_id=c1["id"])
    assert s == 403


@test("CustomerService and PlatformAdmin can read any customer")
def t():
    c = Client()
    c1 = make_customer(c, phone="X")
    s, _ = c.get(f"/api/customers/{c1['id']}", role="CustomerService", user_id="cs1")
    assert s == 200
    s, _ = c.get(f"/api/customers/{c1['id']}", role="PlatformAdmin", user_id="adm")
    assert s == 200


@test("Customer cannot register a customer; PlatformAdmin and CustomerService can")
def t():
    c = Client()
    body = {"name": "x", "phone": "z", "address": "a", "lat": 0, "lng": 0}
    s, _ = c.post("/api/customers", role="Customer", body=body)
    assert s == 403
    s, _ = c.post("/api/customers", role="CustomerService", body=body)
    assert s == 201
