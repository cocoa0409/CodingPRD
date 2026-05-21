from . import client
from .fixtures import make_customer


def test_customer_register_and_get():
    c = make_customer(name="Carol")
    assert c["trust_score"] == 1.0
    assert c["credit_balance_cents"] == 0
    r = client.get(f"/api/customers/{c['id']}", role="Customer", uid=c["id"])
    assert r.status_code == 200
    assert r.json()["data"]["id"] == c["id"]


def test_customer_cannot_read_other():
    a = make_customer(name="A")
    b = make_customer(name="B")
    r = client.get(f"/api/customers/{b['id']}", role="Customer", uid=a["id"])
    assert r.status_code == 403


def test_phone_unique():
    c = make_customer(phone="+15551234567")
    r = client.post("/api/customers", role="PlatformAdmin", uid="admin",
                    json={"name": "Dup", "phone": "+15551234567",
                          "address": "x", "lat": 0, "lng": 0})
    assert r.status_code == 422


def test_customer_register_role():
    r = client.post("/api/customers", role="Customer", uid="x",
                    json={"name": "x", "phone": "+1", "address": "x", "lat": 0, "lng": 0})
    assert r.status_code == 403
