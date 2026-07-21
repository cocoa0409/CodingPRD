"""Grooming station scheduling and cage-config optimistic concurrency."""
from test_helpers import (
    validate_success, validate_error, assert_version_incremented,
    new_customer, new_station, new_appointment, new_boarding_cage, new_housing_cage,
    make_customer_headers, TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]


# ── resource_temporal_overlap: grooming half-open slots ──────────────────────

def test_grooming_overlap_rejected(api):
    """PRD 3.6: "The half-open slot from slot_start up to slot_end must not overlap
    another non-cancelled appointment on the same station; unlike boarding there is no
    buffer, so back-to-back adjacency (one appointment's end equal to the next's start)
    is allowed, and a true overlap is rejected with ERR_STATION_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/station_slot_overlap_rejected_adjacent_allowed
    """
    cust = new_customer()
    st = new_station(["WING_TRIM"])
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    new_appointment(cust["id"], st["id"], "WING_TRIM",
                    "2026-07-10T10:00:00Z", "2026-07-10T10:30:00Z", fee_cents=1500)
    res = api.create_appointment(
        {"customer_id": cust["id"], "grooming_station_id": st["id"], "service_type": "WING_TRIM",
         "slot_start": "2026-07-10T10:15:00Z", "slot_end": "2026-07-10T10:45:00Z", "fee_cents": 1500},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_STATION_TIME_CONFLICT", expected_status=409)


def test_grooming_adjacent_allowed(api):
    """PRD 3.6: "unlike boarding there is no buffer, so back-to-back adjacency (one
    appointment's end equal to the next's start) is allowed, and a true overlap is
    rejected with ERR_STATION_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/station_slot_overlap_rejected_adjacent_allowed
    """
    cust = new_customer()
    st = new_station(["WING_TRIM"])
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    new_appointment(cust["id"], st["id"], "WING_TRIM",
                    "2026-07-10T10:00:00Z", "2026-07-10T10:30:00Z", fee_cents=1500)
    a3 = validate_success(api.create_appointment(
        {"customer_id": cust["id"], "grooming_station_id": st["id"], "service_type": "WING_TRIM",
         "slot_start": "2026-07-10T10:30:00Z", "slot_end": "2026-07-10T11:00:00Z", "fee_cents": 1500},
        make_customer_headers(cust["id"])), 201)
    assert a3["status"] == "BOOKED"


# ── corner: service not offered by the station ───────────────────────────────

def test_grooming_service_not_offered_rejected(api):
    """PRD 3.6: "The requested service_type must be listed in the station's service_types
    and the station must be open; a service the station does not offer, or a closed
    station, is rejected with ERR_SERVICE_NOT_OFFERED."

    Design: Corner/validations/grooming_service_not_offered_rejected
    """
    cust = new_customer()
    st = new_station(["WING_TRIM"])
    res = api.create_appointment(
        {"customer_id": cust["id"], "grooming_station_id": st["id"], "service_type": "NAIL_TRIM",
         "slot_start": "2026-07-10T09:00:00Z", "slot_end": "2026-07-10T09:30:00Z", "fee_cents": 1200},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_SERVICE_NOT_OFFERED", expected_status=409)


# ── corner: cage-config OCC stale version conflict ───────────────────────────

def test_cage_update_stale_version_conflict(api):
    """PRD 2.5: "If they do not match — for example, because a boarding check-in already
    advanced the cage's version and occupancy since the client last read it — the update
    is rejected with ERR_STALE_CAGE_VERSION (HTTP 412), preventing the client from
    overwriting a configuration it never observed."

    Design: Corner/cross_cutting_complexity_layers/cage_update_stale_version_conflict
    """
    cage = new_boarding_cage(capacity=1, nightly_rate_cents=3000)
    v1 = cage["version"]
    updated = validate_success(api.update_cage(
        cage["id"], {"expected_cage_version": v1, "nightly_rate_cents": 4000}, SM), 200)
    assert updated["nightly_rate_cents"] == 4000
    # Re-using the now-stale v1 must be rejected.
    stale = api.update_cage(
        cage["id"], {"expected_cage_version": v1, "nightly_rate_cents": 5000}, SM)
    validate_error(stale, "ERR_STALE_CAGE_VERSION", expected_status=412)
    after = validate_success(api.get_cage(cage["id"], SM), 200)
    assert after["nightly_rate_cents"] == 4000  # stale write rejected


def test_cage_update_correct_version_succeeds(api):
    """PRD 2.5: "A successful update applies the changes and increments the cage's
    version by one."

    Design: Corner/cross_cutting_complexity_layers/cage_update_correct_version_succeeds
    """
    cage = new_housing_cage(capacity=2)
    v1 = cage["version"]
    updated = validate_success(api.update_cage(
        cage["id"], {"expected_cage_version": v1, "capacity": 3}, SM), 200)
    assert updated["capacity"] == 3
    assert_version_incremented(updated["version"], v1)
