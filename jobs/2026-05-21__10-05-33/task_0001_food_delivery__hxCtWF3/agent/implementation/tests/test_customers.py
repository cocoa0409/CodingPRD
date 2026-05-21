"""Customer registration + identity binding."""
from .client import Client


def run(suite):
    def register_by_admin():
        c = Client()
        s, body = c.post("/api/customers",
                         {"name": "A", "phone": "1", "address": "x", "lat": 1, "lng": 2},
                         role="PlatformAdmin", user_id="op")
        assert s == 201, body
        assert body["data"]["credit_balance_cents"] == 0
        assert body["data"]["trust_score"] == 1.0

    def register_by_cs():
        c = Client()
        s, body = c.post("/api/customers",
                         {"name": "A", "phone": "1", "address": "x", "lat": 1, "lng": 2},
                         role="CustomerService", user_id="cs1")
        assert s == 201

    def register_forbidden_for_customer_role():
        c = Client()
        s, body = c.post("/api/customers",
                         {"name": "A", "phone": "1", "address": "x", "lat": 1, "lng": 2},
                         role="Customer", user_id="x")
        assert s == 403

    def phone_unique():
        c = Client()
        c.post("/api/customers", {"name": "A", "phone": "p", "address": "x", "lat": 1, "lng": 2},
               role="PlatformAdmin", user_id="op")
        s, _ = c.post("/api/customers",
                      {"name": "B", "phone": "p", "address": "x", "lat": 1, "lng": 2},
                      role="PlatformAdmin", user_id="op")
        assert s == 422

    def read_self_only_for_customer():
        c = Client()
        _, body = c.post("/api/customers",
                         {"name": "A", "phone": "1", "address": "x", "lat": 1, "lng": 2},
                         role="PlatformAdmin", user_id="op")
        cid = body["data"]["id"]
        s, _ = c.get(f"/api/customers/{cid}", role="Customer", user_id=cid)
        assert s == 200
        s, e = c.get(f"/api/customers/{cid}", role="Customer", user_id="other")
        assert s == 403

    suite.case("admin registers a customer", register_by_admin)
    suite.case("CS registers a customer", register_by_cs)
    suite.case("Customer role cannot self-register", register_forbidden_for_customer_role)
    suite.case("phone unique across customers", phone_unique)
    suite.case("Customer read scoped to own id", read_self_only_for_customer)
