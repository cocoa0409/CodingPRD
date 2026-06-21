"""Corner: optimistic concurrency (party lock, unit retire), the manager fee
waiver, and the clock-advance overdue sweep."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer,
    make_customer_headers, setup_party_with_confirmed_member,
    create_picked_up_reservation, return_reservation, advance_clock,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import retire_payload, waive_fee_payload

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}
ONTIME_RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


def test_occ_stale_party_version_on_lock_returns_412(api):
    """PRD §2.10: "Locking a party order requires `expected_party_order_version` to match the `PartyOrder`'s current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_party_version_on_lock_returns_412
    """
    info = setup_party_with_confirmed_member(required_member_count=1)
    party = info["party"]
    coord_headers = make_customer_headers(info["coordinator"]["id"])
    stale = info["party_version_after_confirm"] - 1
    res = api_client.lock_party_order(
        party["id"], {"expected_party_order_version": stale}, coord_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_party_order(party["id"], coord_headers), 200)
    assert after["posture"] == "READY"


def test_occ_correct_party_version_on_lock_succeeds(api):
    """PRD §3.9: "Locking moves the `posture` from `READY` to `LOCKED`, freezes the member reservations so that `CONFIRMED` members may no longer be cancelled until pickup, and advances the party's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_party_version_on_lock_succeeds
    """
    info = setup_party_with_confirmed_member(required_member_count=1)
    party = info["party"]
    coord_headers = make_customer_headers(info["coordinator"]["id"])
    current_v = info["party_version_after_confirm"]
    locked = validate_success(api_client.lock_party_order(
        party["id"], {"expected_party_order_version": current_v}, coord_headers), 200)
    assert locked["posture"] == "LOCKED"
    assert locked["version"] == current_v + 1, "lock advances the party version by 1"


def test_occ_stale_garment_unit_version_on_retire_returns_412(api):
    """PRD §2.10: "Retiring a garment unit requires `expected_garment_unit_version` to match that `GarmentUnit`'s current `version`, and waiving a settlement fee requires `expected_settlement_version` to match that `Settlement`'s current `version`; either mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_garment_unit_version_on_retire_returns_412
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux L2"})
    unit = create_unit(catalog["id"], "M")
    res = api_client.retire_garment_unit(
        unit["id"], retire_payload(unit["version"] - 1), MANAGER)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert after["status"] == "AVAILABLE"


def test_garment_unit_version_increments_on_retire(api):
    """PRD §3.1: "the retirement carries the unit to the terminal `RETIRED` state, recomputes (decrementing) the owning catalog's `active_unit_count`, and advances the unit's own `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/garment_unit_version_increments_on_retire
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux K2"})
    unit = create_unit(catalog["id"], "M")
    retired = validate_success(api_client.retire_garment_unit(
        unit["id"], retire_payload(unit["version"]), MANAGER), 200)
    assert retired["status"] == "RETIRED"
    assert retired["version"] == unit["version"] + 1
    catalog_after = validate_success(api_client.get_catalog(catalog["id"], MANAGER), 200)
    assert catalog_after["active_unit_count"] == 0


def test_manager_waive_fee_reduces_net_charge(api):
    """PRD §3.8: "The waiver posts a `FEE_WAIVE` for the amount, reduces the settlement's `net_charge_cents`, recomputes the customer's `balance_owed_cents`, and advances the settlement's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/manager_waive_fee_reduces_net_charge
    """
    _, _, customer, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux J2"}, reservation_overrides=ONTIME_RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "DAMAGED")
    assert settlement["net_charge_cents"] == 28000

    waived = validate_success(api_client.waive_fee(
        settlement["id"], waive_fee_payload(28000, settlement["version"]), MANAGER), 200)
    assert waived["net_charge_cents"] == 0, "waive 28000 zeroes the net charge"
    cust = validate_success(api_client.get_customer(customer["id"], CLERK), 200)
    assert cust["balance_owed_cents"] == 0


def test_clock_advance_sweeps_pickedup_to_overdue(api):
    """PRD §3.10: "any reservation still `PICKED_UP` whose `return_window_end_iso` the clock has now crossed is flagged `OVERDUE`; as noted in §3.7, this sweep-driven transition creates no settlement and leaves the unit `OUT`, so late fees accrue and the eventual return will create the settlement."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_sweeps_pickedup_to_overdue
    """
    _, unit, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux I2"}, reservation_overrides=ONTIME_RESV)
    assert resv["status"] == "PICKED_UP"

    advance_clock("2026-09-04T09:00:00Z")  # past return_window_end 09-03T17:00

    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "OVERDUE"
    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["status"] == "OUT", "sweep leaves the unit OUT (no settlement)"
    _, meta = validate_paginated(
        api_client.list_settlements(CLERK, params={"reservation_id": resv["id"]}))
    assert meta["total_count"] == 0, "no settlement created by the sweep"
