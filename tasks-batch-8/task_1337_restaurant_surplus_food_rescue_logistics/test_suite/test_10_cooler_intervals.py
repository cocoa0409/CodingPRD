"""Cooler buffered reservation intervals (PRD §3.1, §3.3)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, get_offer_version,
)

ADMIN = TEST_USERS["admin_headers"]


def _buffered_setup(api):
    """Cooler C1 pinned to a run whose pickup window is 10:00-12:00Z, so its
    reservation blocks [10:00, 14:15) — window_end plus the 135-minute buffer.
    Two further OPEN offers wait: O2 at 13:30 (inside the buffer) and O3 at
    14:15 (exactly at the buffered edge)."""
    donor = create_donor(legal_name="Buf Bistro", ein="135792468",
                         contact_email="buf@bistro.example")
    agency = create_agency()
    driver = create_driver(cold_chain_certified=True)
    add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z")
    add_window(driver["id"], "2026-08-02T13:00:00Z", "2026-08-02T14:15:00Z")
    add_window(driver["id"], "2026-08-02T14:15:00Z", "2026-08-02T16:00:00Z")
    cooler = create_cooler(label="C1")
    o1 = create_offer(donor["id"], estimated_weight_lbs=10, publish=True)
    o2 = create_offer(donor["id"], estimated_weight_lbs=10,
                      pickup_window_start="2026-08-02T13:30:00Z",
                      pickup_window_end="2026-08-02T14:00:00Z", publish=True)
    o3 = create_offer(donor["id"], estimated_weight_lbs=10,
                      pickup_window_start="2026-08-02T14:15:00Z",
                      pickup_window_end="2026-08-02T15:00:00Z", publish=True)
    set_clock("2026-08-02T09:30:00Z")
    r1 = dispatch_run(o1["id"], driver_id=driver["id"], agency_id=agency["id"],
                      cooler_ids=[cooler["id"]])
    return {"donor": donor, "agency": agency, "driver": driver,
            "cooler": cooler, "o2": o2, "o3": o3, "r1": r1}


class TestCoolerReservationBufferedInterval:
    def test_pickup_inside_buffer_rejected(self, api):
        """PRD §3.1: "a blocked interval whose `blocked_start` is the offer's
        `pickup_window_start` at dispatch time and whose `blocked_end` is the
        offer's `pickup_window_end` plus 135 minutes — a 90-minute return
        allowance followed by a 45-minute cleaning buffer."
        PRD §3.3: "In pinned mode, every listed cooler must be a candidate — a
        cooler that is not lazily `AVAILABLE` or whose buffered interval
        conflicts answers `ERR_COOLER_UNAVAILABLE`"

        Design: Difficulty/resource_temporal_overlap/cooler_reservation_buffered_interval
        """
        s = _buffered_setup(api)
        # O2's blocked interval would start at 13:30 < 14:15 (C1's blocked_end):
        # the 90-minute return allowance + 45-minute cleaning buffer rejects it.
        payload = {"offer_id": s["o2"]["id"],
                   "expected_offer_version": get_offer_version(s["o2"]["id"]),
                   "driver_id": s["driver"]["id"], "agency_id": s["agency"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_COOLER_UNAVAILABLE)

    def test_pickup_at_buffered_edge_allowed(self, api):
        """PRD §3.3: "Candidate coolers are those lazily `AVAILABLE` with no
        reservation in `RESERVED` or `CHECKED_OUT` whose buffered blocked
        interval overlaps the new one; intervals conflict when the new start
        falls before the existing `blocked_end` and the existing
        `blocked_start` falls before the new end, and because the test is
        strict, a new interval starting exactly at an existing `blocked_end` is
        allowed."

        Design: Difficulty/resource_temporal_overlap/cooler_reservation_buffered_interval
        """
        s = _buffered_setup(api)
        # O3's pickup window starts at 14:15 — exactly C1's buffered blocked_end.
        r3 = dispatch_run(s["o3"]["id"], driver_id=s["driver"]["id"],
                          agency_id=s["agency"]["id"],
                          cooler_ids=[s["cooler"]["id"]])
        assert r3["run_status"] == "PROPOSED"
        resp = api.list_cooler_reservations(
            s["cooler"]["id"], ADMIN, params={"status": "RESERVED"})
        reservations = validate_success(resp)
        assert len(reservations) == 2, "adjacent buffered reservations coexist"
