"""Rider lifecycle: go-online/offline, suspend criteria."""
from .client import Client


def _register(c, phone="r1"):
    return c.post("/api/riders", {"name": "Ri", "phone": phone},
                  role="PlatformAdmin", user_id="op")


def run(suite):
    def starts_offline():
        c = Client()
        s, body = _register(c)
        assert s == 201
        assert body["data"]["status"] == "OFFLINE"
        assert body["data"]["bonus_tier"] == "BRONZE"

    def go_online_self_only():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        s, _ = c.post(f"/api/riders/{rid}/go-online", role="Rider", user_id="other")
        assert s == 403
        s, body = c.post(f"/api/riders/{rid}/go-online", role="Rider", user_id=rid)
        assert s == 200
        assert body["data"]["status"] == "AVAILABLE"

    def go_offline_invalid_state():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        # cannot go offline while OFFLINE
        s, _ = c.post(f"/api/riders/{rid}/go-offline", role="Rider", user_id=rid)
        assert s == 409

    def suspend_criteria_not_met():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        c.post(f"/api/riders/{rid}/go-online", role="Rider", user_id=rid)
        # Fresh rider has on_time_rate=1.0, acceptance_rate=1.0 -> suspend fails
        s, e = c.post(f"/api/riders/{rid}/suspend", role="PlatformAdmin", user_id="op")
        assert s == 422
        assert e["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"

    suite.case("rider starts OFFLINE, BRONZE", starts_offline)
    suite.case("go-online requires identity match", go_online_self_only)
    suite.case("go-offline from OFFLINE -> ERR_INVALID_STATE", go_offline_invalid_state)
    suite.case("suspend with healthy metrics -> ERR_SUSPEND_CRITERIA_NOT_MET", suspend_criteria_not_met)
