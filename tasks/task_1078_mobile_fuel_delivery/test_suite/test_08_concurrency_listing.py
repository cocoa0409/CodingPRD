"""Optimistic concurrency on fleet-account updates and list/pagination endpoints.

Queue B: cross_cutting_complexity_layers (OCC stale-version reject, OCC correct-version
succeed) and endpoints (order pagination envelope, compartment reverse lookup).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_fleet_manager_headers, make_member_headers,
    setup_fleet_account, get_fleet_account,
    post_fuel_price, new_customer, new_vehicle, new_order,
    new_truck, new_compartment,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Queue B: cross_cutting_complexity_layers / OCC ─────────────────────────

def test_stale_fleet_account_version_rejected(api):
    """PRD §2.6: "If another writer has advanced the account's `version` since the client
    last read it, the values no longer match and the update is rejected with
    `ERR_STALE_FLEET_ACCOUNT_VERSION` (HTTP 412), which prevents the client from silently
    clobbering a change it never saw (a lost update)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fleet_account_version_conflict
    """
    cust_id, fa = setup_fleet_account()
    headers = make_fleet_manager_headers(cust_id)
    first = validate_success(api.update_fleet_account(
        fa["id"], {"expected_fleet_account_version": fa["version"],
                   "monthly_budget_cap_cents": 120000}, headers), 200)
    assert first["version"] == 2
    res = api.update_fleet_account(
        fa["id"], {"expected_fleet_account_version": fa["version"],
                   "monthly_budget_cap_cents": 130000}, headers)
    validate_error(res, "ERR_STALE_FLEET_ACCOUNT_VERSION", expected_status=412)
    current = get_fleet_account(fa["id"])
    assert current["version"] == 2, "the stale write did not advance the version"
    assert current["monthly_budget_cap_cents"] == 120000, "the stale write did not clobber the cap"


def test_correct_fleet_account_version_succeeds_and_bumps(api):
    """PRD §3.1: "The optimistic-concurrency behavior of that version field is specified in
    Section 2.6; when the update succeeds it applies only the provided fields and increments
    the account's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    cust_id, fa = setup_fleet_account(name="OkFleet", email="ops@okfleet.com")
    res = api.update_fleet_account(
        fa["id"], {"expected_fleet_account_version": fa["version"],
                   "allowed_fuel_types": ["REGULAR", "DIESEL"]},
        make_fleet_manager_headers(cust_id))
    updated = validate_success(res, 200)
    assert updated["version"] == 2, "a successful update bumps version 1 -> 2"
    assert updated["allowed_fuel_types"] == ["REGULAR", "DIESEL"], "the provided field is applied"


# ─── Queue B: endpoints ─────────────────────────────────────────────────────

def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the response envelope."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    post_fuel_price()
    cust = new_customer(name="Dot", email="dot@x.com")
    veh = new_vehicle(cust["id"], make_model="Vento")
    new_order(cust["id"], veh["id"], requested_gallons=5, delivery_address="P1",
              delivery_window_start="2026-05-02T09:00:00Z",
              delivery_window_end="2026-05-02T10:00:00Z")
    new_order(cust["id"], veh["id"], requested_gallons=5, delivery_address="P2",
              delivery_window_start="2026-05-02T14:00:00Z",
              delivery_window_end="2026-05-02T15:00:00Z")
    res = api.list_orders(make_member_headers(cust["id"]),
                          params={"customer_id": cust["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 1, "limit=1 returns a single item"
    assert meta["total_count"] == 2, "two orders exist for this customer"
    assert meta["has_more"] is True, "one of two returned leaves more"


def test_list_compartments_reverse_lookup(api):
    """PRD §3.3: "A truck's compartments may be listed as a reverse lookup by the parent
    `truck_id`."

    Design: Corner/endpoints/list_compartments_reverse_lookup
    """
    truck = new_truck(plate="TRK-RC")
    c1 = new_compartment(truck["id"], fuel_type="REGULAR", gallons_onboard=100)
    c2 = new_compartment(truck["id"], fuel_type="DIESEL", gallons_onboard=80)
    res = api.list_compartments(truck["id"], ADMIN)
    assert res.status_code == 200
    data = res.json()["data"]
    ids = {c["id"] for c in data}
    assert len(data) == 2
    assert {c1["id"], c2["id"]} <= ids, "both compartments returned for the parent truck"
