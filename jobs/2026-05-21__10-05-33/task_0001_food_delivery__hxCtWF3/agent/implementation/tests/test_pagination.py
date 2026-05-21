"""Pagination defaults, bounds, and ordering by created_at ascending."""
from .client import Client


def run(suite):
    def defaults_and_total():
        c = Client()
        # Create 15 restaurants
        for i in range(15):
            c.post("/api/restaurants",
                   {"name": f"R{i:02d}", "address": "a", "lat": 0, "lng": 0},
                   role="PlatformAdmin", user_id="op")
        s, body = c.get("/api/restaurants", role="PlatformAdmin", user_id="op")
        assert s == 200
        assert body["meta"]["limit"] == 10
        assert body["meta"]["offset"] == 0
        assert body["meta"]["total_count"] == 15
        assert body["meta"]["has_more"] is True
        assert len(body["data"]) == 10

    def offset_and_window():
        c = Client()
        for i in range(15):
            c.post("/api/restaurants",
                   {"name": f"R{i:02d}", "address": "a", "lat": 0, "lng": 0},
                   role="PlatformAdmin", user_id="op")
        s, body = c.get("/api/restaurants?limit=5&offset=12",
                        role="PlatformAdmin", user_id="op")
        assert len(body["data"]) == 3
        assert body["meta"]["has_more"] is False

    def limit_out_of_range():
        c = Client()
        s, body = c.get("/api/restaurants?limit=0",
                        role="PlatformAdmin", user_id="op")
        assert s == 422 and body["data"]["error_id"] == "ERR_VALIDATION"
        s, body = c.get("/api/restaurants?limit=101",
                        role="PlatformAdmin", user_id="op")
        assert s == 422

    def sort_by_created_at_ascending():
        c = Client()
        # creation order: A, B, C
        for n in ("A", "B", "C"):
            c.post("/api/restaurants",
                   {"name": n, "address": "a", "lat": 0, "lng": 0},
                   role="PlatformAdmin", user_id="op")
        s, body = c.get("/api/restaurants", role="PlatformAdmin", user_id="op")
        names = [r["name"] for r in body["data"]]
        assert names == ["A", "B", "C"], names

    suite.case("default limit=10, offset=0, total_count, has_more", defaults_and_total)
    suite.case("offset windowing + has_more=false at tail", offset_and_window)
    suite.case("limit out of [1,100] -> ERR_VALIDATION", limit_out_of_range)
    suite.case("default sort by created_at ascending", sort_by_created_at_ascending)
