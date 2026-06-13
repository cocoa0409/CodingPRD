"""Optimistic concurrency control on the two version-guarded member writes.

Translates corner queue instances:
  cross_cutting / booking_create_stale_member_version_rejected
  cross_cutting / storage_assign_correct_version_succeeds_and_bumps
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_member, create_station, create_storage_unit,
)

FM = TEST_USERS["facility_manager_headers"]


# ── Corner: cross_cutting / booking_create_stale_member_version_rejected ──

def test_booking_create_with_stale_member_version_rejected(api):
    """PRD 2.6: "A booking debits the member's wallet and advances the member's
    version; if another writer (a prior booking, a wallet top-up, a suspension,
    or any other member mutation) has advanced that version since the client last
    read the member, the create is rejected with ERR_STALE_VERSION (HTTP 412)".
    The second booking carries the now-stale prior version.

    Design: Corner/cross_cutting_complexity_layers/booking_create_stale_member_version_rejected
    """
    member = register_member(business_name="Sc")
    mo = make_member_operator_headers(member["id"])
    topped = validate_success(api.top_up_wallet(member["id"], {"amount_cents": 100000}, mo), 201)
    station = validate_success(api.create_station({"name": "PrepSc", "station_class": "PREP_TABLE"}, FM), 201)
    first = validate_success(api.create_booking(member["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-21T12:00:00.000Z",
        "end_utc": "2026-07-21T13:00:00.000Z",
        "expected_member_version": topped["version"],
    }, mo), 201)
    # Observe the now-current version, then deliberately send one-behind.
    current = validate_success(api.get_member(member["id"], mo), 200)
    stale_version = current["version"] - 1
    res = api.create_booking(member["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-21T15:00:00.000Z",
        "end_utc": "2026-07-21T16:00:00.000Z",
        "expected_member_version": stale_version,
    }, mo)
    validate_error(res, "ERR_STALE_VERSION")


# ── Corner: cross_cutting / storage_assign_correct_version_succeeds_and_bumps ──

def test_storage_assignment_with_current_version_succeeds_and_bumps(api):
    """PRD 2.6: "The storage-assignment create behaves the same way: its
    expected_member_version must match the member's current version". PRD 2.5:
    "when ... a storage unit's used-slot count changes ... the affected resource
    is a genuine mutation and advances its own version." A create with the current
    version succeeds and the member's version increments to 2.

    Design: Corner/cross_cutting_complexity_layers/storage_assign_correct_version_succeeds_and_bumps
    """
    member = register_member(business_name="Ok")
    mo = make_member_operator_headers(member["id"])
    create_storage_unit(name="DryOk", temp_class="DRY", total_slots=10,
                        temp_min_c=10.0, temp_max_c=25.0)
    asn = validate_success(api.create_storage_assignment(member["id"], {
        "temp_class": "DRY", "requested_slots": 3, "expected_member_version": member["version"],
    }, mo), 201)
    assert asn["status"] == "ACTIVE"
    member_now = validate_success(api.get_member(member["id"], mo), 200)
    assert member_now["version"] == 2, f"got {member_now['version']}"
