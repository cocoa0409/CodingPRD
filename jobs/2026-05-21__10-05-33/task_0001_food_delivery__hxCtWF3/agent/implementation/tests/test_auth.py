"""Header presence, role-set, ERR_AUTH_REQUIRED, ERR_FORBIDDEN."""
from .client import Client


def run(suite):
    def missing_headers():
        c = Client()
        status, body = c.get("/api/restaurants")
        assert status == 401
        assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"

    def unknown_role():
        c = Client()
        status, body = c.get("/api/restaurants", role="Wizard", user_id="x")
        assert status == 401
        assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"

    def forbidden_role():
        c = Client()
        status, body = c.post("/api/restaurants",
                              {"name": "X", "address": "a", "lat": 0, "lng": 0},
                              role="Customer", user_id="x")
        assert status == 403
        assert body["data"]["error_id"] == "ERR_FORBIDDEN"

    def all_recognized_roles_pass_auth():
        c = Client()
        for role in ("Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"):
            status, body = c.get("/api/restaurants", role=role, user_id="x")
            # Restaurants list is open to all five roles — must succeed
            assert status == 200, (role, status, body)

    suite.case("missing headers -> ERR_AUTH_REQUIRED", missing_headers)
    suite.case("unknown role -> ERR_AUTH_REQUIRED", unknown_role)
    suite.case("disallowed role on endpoint -> ERR_FORBIDDEN", forbidden_role)
    suite.case("all 5 roles authorized for GET /api/restaurants", all_recognized_roles_pass_auth)
