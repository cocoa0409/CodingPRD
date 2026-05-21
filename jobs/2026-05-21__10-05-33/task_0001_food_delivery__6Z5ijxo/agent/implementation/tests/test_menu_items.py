from . import client
from .fixtures import make_restaurant, make_menu_item


def test_menu_item_create_and_view():
    rest = make_restaurant()
    r = client.post(f"/api/restaurants/{rest['id']}/menu-items",
                    role="Restaurant", uid=rest["id"],
                    json={"name": "Pasta", "price_cents": 1200})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["price_cents"] == 1200
    assert d["is_listed"] is True


def test_menu_item_price_out_of_range():
    rest = make_restaurant()
    bad = {"name": "X", "price_cents": 0}
    r = client.post(f"/api/restaurants/{rest['id']}/menu-items",
                    role="Restaurant", uid=rest["id"], json=bad)
    assert r.status_code == 422


def test_menu_item_patch_and_listing_filter():
    rest = make_restaurant()
    m1 = make_menu_item(rest["id"], name="A", price_cents=500)
    m2 = make_menu_item(rest["id"], name="B", price_cents=600, is_listed=False)
    r = client.get(f"/api/restaurants/{rest['id']}/menu-items?is_listed=true",
                   role="Customer", uid="c1")
    ids = [x["id"] for x in r.json()["data"]]
    assert m1["id"] in ids and m2["id"] not in ids
    # Patch m1 to unlisted
    p = client.patch(f"/api/menu-items/{m1['id']}",
                     role="Restaurant", uid=rest["id"],
                     json={"is_listed": False})
    assert p.status_code == 200
    assert p.json()["data"]["is_listed"] is False
    assert p.json()["data"]["version"] == 2


def test_menu_item_not_owning_restaurant_forbidden():
    a = make_restaurant(name="A")
    b = make_restaurant(name="B")
    r = client.post(f"/api/restaurants/{a['id']}/menu-items",
                    role="Restaurant", uid=b["id"],
                    json={"name": "X", "price_cents": 100})
    assert r.status_code == 403
