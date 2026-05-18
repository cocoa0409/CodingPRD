import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers,
    setup_full_order, create_rider,
)
from store import store


def test_advance_clock(client):
    resp = client.post("/api/_clock/advance", json={"seconds": 100}, headers=admin_headers())
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "new_time" in data


def test_advance_clock_invalid(client):
    resp = client.post("/api/_clock/advance", json={"seconds": -1}, headers=admin_headers())
    assert resp.status_code == 422


def test_advance_clock_forbidden(client):
    resp = client.post("/api/_clock/advance", json={"seconds": 10},
                       headers={"X-User-ID": "c1", "X-User-Role": "Customer"})
    assert resp.status_code == 403


def test_offer_timeout_sweep(client):
    s = setup_full_order(client)

    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    assignments = [a for a in store.assignments.values()
                   if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED"]
    assert len(assignments) == 1

    r2 = create_rider(client, name="R2", phone="555-2002")
    client.post(f"/api/riders/{r2['id']}/go-online", headers=rider_headers(r2["id"]))

    client.post("/api/_clock/advance", json={"seconds": 61}, headers=admin_headers())

    old_assignment = store.assignments.get(assignments[0]["id"])
    assert old_assignment["status"] == "REJECTED"

    new_offers = [a for a in store.assignments.values()
                  if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED"]
    assert len(new_offers) >= 1
