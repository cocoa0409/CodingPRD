"""Envelope shape: success, error, request id, timestamp."""
import re

from .client import Client


def run(suite):
    def envelope_unknown_path():
        c = Client()
        status, body = c.get("/api/does-not-exist", role="PlatformAdmin", user_id="op")
        assert status == 404, status
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
                        body["meta"]["api_request_timestamp"])

    def envelope_success_object():
        c = Client()
        status, body = c.post("/api/restaurants", {
            "name": "X", "address": "a", "lat": 0, "lng": 0,
        }, role="PlatformAdmin", user_id="op")
        assert status == 201, (status, body)
        assert body["response_type"] == "object"
        assert "id" in body["data"]
        assert body["data"]["version"] == 1

    def envelope_success_list():
        c = Client()
        status, body = c.get("/api/restaurants", role="PlatformAdmin", user_id="op")
        assert status == 200
        assert body["response_type"] == "array"
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in body["meta"], k

    suite.case("envelope_unknown_path -> ERR_NOT_FOUND envelope", envelope_unknown_path)
    suite.case("success object envelope", envelope_success_object)
    suite.case("success list envelope", envelope_success_list)
