"""Helper builders for tests — keep test bodies focused on what they assert."""
from .client import Client


def setup_basics(c=None, *, rate_override=None):
    """Bring up admin + customer + restaurant + 1 menu item. Returns (Client, ids dict)."""
    c = c or Client()
    # Restaurant
    body = {"name": "R1", "address": "addr", "lat": 10.0, "lng": 10.0}
    if rate_override is not None:
        body["commission_rate_override"] = rate_override
    _, rr = c.post("/api/restaurants", body, role="PlatformAdmin", user_id="op")
    rid = rr["data"]["id"]
    c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
    _, mi = c.post(f"/api/restaurants/{rid}/menu-items",
                   {"name": "burger", "price_cents": 500},
                   role="PlatformAdmin", user_id="op")
    mid = mi["data"]["id"]
    _, cust = c.post("/api/customers",
                     {"name": "C", "phone": "555-1", "address": "x", "lat": 10.01, "lng": 10.01},
                     role="PlatformAdmin", user_id="op")
    cid = cust["data"]["id"]
    return c, {"rid": rid, "mid": mid, "cid": cid}


def register_rider(c, phone="r-test", name="Rider"):
    _, r = c.post("/api/riders", {"name": name, "phone": phone},
                  role="PlatformAdmin", user_id="op")
    rid = r["data"]["id"]
    c.post(f"/api/riders/{rid}/go-online", role="Rider", user_id=rid)
    return rid


def place_order(c, ids, qty=1):
    s, body = c.post("/api/orders", {
        "customer_id": ids["cid"],
        "restaurant_id": ids["rid"],
        "items": [{"menu_item_id": ids["mid"], "quantity": qty}],
    }, role="Customer", user_id=ids["cid"])
    return s, body
