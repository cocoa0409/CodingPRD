from . import client
from .fixtures import make_restaurant


def test_occ_version_conflict():
    rest = make_restaurant(name="OCC")
    # make_restaurant registers + approves, so initial version = 2
    assert rest["version"] == 2
    # First PATCH succeeds and bumps version to 3
    r1 = client.patch(f"/api/restaurants/{rest['id']}",
                      role="PlatformAdmin", uid="admin",
                      json={"address": "AAA", "version": 2})
    assert r1.status_code == 200
    # Second PATCH using version 2 (stale) fails
    r2 = client.patch(f"/api/restaurants/{rest['id']}",
                      role="PlatformAdmin", uid="admin",
                      json={"address": "BBB", "version": 2})
    assert r2.status_code == 409
    assert r2.json()["data"]["error_id"] == "ERR_VERSION_CONFLICT"


def test_occ_omit_version_no_check():
    rest = make_restaurant(name="OCC2")
    r1 = client.patch(f"/api/restaurants/{rest['id']}",
                      role="PlatformAdmin", uid="admin",
                      json={"address": "X"})
    assert r1.status_code == 200
    # No version supplied, even after version bump - still succeeds
    r2 = client.patch(f"/api/restaurants/{rest['id']}",
                      role="PlatformAdmin", uid="admin",
                      json={"address": "Y"})
    assert r2.status_code == 200


def test_pagination_defaults():
    # Create 3 restaurants then list with default
    make_restaurant(name="One")
    make_restaurant(name="Two")
    make_restaurant(name="Three")
    r = client.get("/api/restaurants", role="PlatformAdmin", uid="admin")
    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_pagination_limit_offset():
    for i in range(5):
        make_restaurant(name=f"R{i}")
    r = client.get("/api/restaurants?limit=2&offset=1",
                   role="PlatformAdmin", uid="admin")
    body = r.json()
    assert len(body["data"]) == 2
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 1
    assert body["meta"]["total_count"] == 5
    assert body["meta"]["has_more"] is True  # 1+2=3 < 5


def test_pagination_out_of_range():
    r = client.get("/api/restaurants?limit=200", role="PlatformAdmin", uid="admin")
    assert r.status_code == 422


def test_pagination_negative_offset():
    r = client.get("/api/restaurants?offset=-1", role="PlatformAdmin", uid="admin")
    assert r.status_code == 422
