"""Menu items lifecycle."""
from .client import Client


def _setup(c):
    _, r = c.post("/api/restaurants", {"name": "R", "address": "a", "lat": 0, "lng": 0},
                  role="PlatformAdmin", user_id="op")
    rid = r["data"]["id"]
    c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
    return rid


def run(suite):
    def create_and_default_listed():
        c = Client()
        rid = _setup(c)
        s, body = c.post(f"/api/restaurants/{rid}/menu-items",
                         {"name": "burger", "price_cents": 500},
                         role="Restaurant", user_id=rid)
        assert s == 201
        m = body["data"]
        assert m["is_listed"] is True
        assert m["price_cents"] == 500
        assert m["restaurant_id"] == rid

    def price_out_of_range():
        c = Client()
        rid = _setup(c)
        s, _ = c.post(f"/api/restaurants/{rid}/menu-items",
                      {"name": "x", "price_cents": 0},
                      role="Restaurant", user_id=rid)
        assert s == 422
        s, _ = c.post(f"/api/restaurants/{rid}/menu-items",
                      {"name": "x", "price_cents": 1_000_001},
                      role="Restaurant", user_id=rid)
        assert s == 422

    def patch_only_owner_or_admin():
        c = Client()
        rid = _setup(c)
        _, body = c.post(f"/api/restaurants/{rid}/menu-items",
                         {"name": "x", "price_cents": 500},
                         role="Restaurant", user_id=rid)
        mid = body["data"]["id"]
        # Wrong restaurant
        s, _ = c.patch(f"/api/menu-items/{mid}", {"price_cents": 700},
                       role="Restaurant", user_id="other")
        assert s == 403
        # PlatformAdmin can update
        s, _ = c.patch(f"/api/menu-items/{mid}", {"price_cents": 800},
                       role="PlatformAdmin", user_id="op")
        assert s == 200

    def list_filter_listed():
        c = Client()
        rid = _setup(c)
        c.post(f"/api/restaurants/{rid}/menu-items",
               {"name": "a", "price_cents": 500, "is_listed": True},
               role="Restaurant", user_id=rid)
        c.post(f"/api/restaurants/{rid}/menu-items",
               {"name": "b", "price_cents": 500, "is_listed": False},
               role="Restaurant", user_id=rid)
        s, body = c.get(f"/api/restaurants/{rid}/menu-items?is_listed=true",
                        role="Customer", user_id="c")
        assert s == 200
        assert len(body["data"]) == 1
        assert body["data"][0]["is_listed"] is True

    suite.case("create menu item defaults to is_listed=true", create_and_default_listed)
    suite.case("price_cents must be in [1, 1_000_000]", price_out_of_range)
    suite.case("PATCH allowed only to owner restaurant or admin", patch_only_owner_or_admin)
    suite.case("list filter is_listed", list_filter_listed)
