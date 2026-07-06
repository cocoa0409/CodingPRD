"""Facility bookings, OCC, capacity, child check-in security."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member, create_child_member,
    create_facility, create_facility_booking, create_event,
    setup_facility_with_booking, setup_child_checked_in,
    get_facility, create_child_checkin,
    create_facility_booking_payload,
)


class TestFacilityBookingOverlap:
    def test_buffered_overlap_rejected(self, api):
        """PRD §3.5: "A new booking's requested window [starts_at, ends_at)
        — a half-open interval, so a booking that starts precisely when
        another ends does not overlap it — is expanded on both sides by
        buffer_minutes and then checked against every existing CONFIRMED
        booking on the same facility. Any pairwise overlap after buffering
        rejects the create with ERR_FACILITY_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/facility_booking_buffered_overlap
        """
        set_clock("2026-05-01T09:00:00Z")
        f = create_facility(name="Sanctuary", capacity=200, buffer_minutes=30)
        create_facility_booking(
            f["id"], "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z",
            headcount=100, expected_facility_version=f["version"],
            booking_type="EXTERNAL",
        )
        f_after = get_facility(f["id"])
        # Try to book 11:20 - 12:00 — B1 ends 11:00, buffered zone extends
        # to 11:30. 11:20 falls inside the buffer → overlap.
        resp = api.create_facility_booking(
            create_facility_booking_payload(
                facility_id=f["id"], booking_type="EXTERNAL",
                starts_at="2026-05-10T11:20:00Z",
                ends_at="2026-05-10T12:00:00Z",
                headcount=100,
                expected_facility_version=f_after["version"],
            ),
            TEST_USERS["coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_OVERLAP)

    def test_touching_end_start_zero_buffer_no_overlap(self, api):
        """PRD §3.5: "A new booking's requested window [starts_at, ends_at)
        — a half-open interval, so a booking that starts precisely when
        another ends does not overlap it..."

        Design: Difficulty/resource_temporal_overlap/facility_booking_buffered_overlap
        """
        # Second required test — the complementary "touching endpoints do
        # NOT overlap" half of the half-open interval rule (buffer=0).
        set_clock("2026-05-01T09:00:00Z")
        f = create_facility(name="Sanctuary2", capacity=200, buffer_minutes=0)
        create_facility_booking(
            f["id"], "2026-05-11T10:00:00Z", "2026-05-11T11:00:00Z",
            headcount=100, expected_facility_version=f["version"],
            booking_type="EXTERNAL",
        )
        f_after = get_facility(f["id"])
        # Booking starts precisely when the other ends — half-open, no overlap.
        resp = api.create_facility_booking(
            create_facility_booking_payload(
                facility_id=f["id"], booking_type="EXTERNAL",
                starts_at="2026-05-11T11:00:00Z",
                ends_at="2026-05-11T12:00:00Z",
                headcount=100,
                expected_facility_version=f_after["version"],
            ),
            TEST_USERS["coordinator_headers"],
        )
        booking = validate_success(resp, expected_status=201)
        assert booking["status"] == "CONFIRMED"


class TestFacilityCapacity:
    def test_headcount_over_capacity_rejected(self, api):
        """PRD §2.8 rung 9: "Capacity constraints must hold — a booking's
        headcount at most equal to the facility's capacity..."
        PRD §3.5: "headcount (strictly greater than zero and at most
        facility.capacity, otherwise ERR_CAPACITY_EXCEEDED)..."

        Design: Corner/validations/facility_booking_headcount_exceeds_capacity
        """
        set_clock("2026-05-01T00:00:00Z")
        f = create_facility(name="Small Room", capacity=50, buffer_minutes=0)
        resp = api.create_facility_booking(
            create_facility_booking_payload(
                facility_id=f["id"], booking_type="EXTERNAL",
                starts_at="2026-05-10T10:00:00Z",
                ends_at="2026-05-10T11:00:00Z",
                headcount=100,
                expected_facility_version=f["version"],
            ),
            TEST_USERS["coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestFacilityOccStaleVersion:
    def test_stale_facility_version_rejected(self, api):
        """PRD §2.5: "If another writer has advanced the facility's version
        since the client last observed it — which happens whenever another
        booking was successfully created against the same facility — the
        create is rejected with ERR_STALE_FACILITY_VERSION and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/facility_stale_version_returns_precondition_failed
        """
        set_clock("2026-05-01T00:00:00Z")
        f = create_facility(name="Sanctuary", capacity=200, buffer_minutes=0)
        v0 = f["version"]
        # First booking advances the version.
        create_facility_booking(
            f["id"], "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z",
            headcount=50, expected_facility_version=v0,
            booking_type="EXTERNAL",
        )
        # Second booking (non-overlapping window) with the same stale version.
        resp = api.create_facility_booking(
            create_facility_booking_payload(
                facility_id=f["id"], booking_type="EXTERNAL",
                starts_at="2026-05-10T14:00:00Z",
                ends_at="2026-05-10T15:00:00Z",
                headcount=50,
                expected_facility_version=v0,
            ),
            TEST_USERS["coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FACILITY_VERSION)


class TestChildCheckoutSecurityHold:
    def test_wrong_pin_transitions_to_security_hold(self, api):
        """PRD §3.8: "On failure of either security check — a supplied PIN
        that does not match, or a pickup requester who is not an
        authorized guardian — the check-in does not move to CHECKED_OUT;
        instead, it sibling-transitions to SECURITY_HOLD, with hold_reason
        set to PIN_MISMATCH when the pin is wrong and UNAUTHORIZED_PICKUP
        when the guardian is not authorized, and the API responds with
        ERR_SECURITY_HOLD_TRIGGERED."

        Design: Corner/state_machines/child_checkout_wrong_pin_transitions_to_security_hold
        """
        h, g, k, e, ch = setup_child_checked_in()
        resp = api.checkout_child_checkin(
            ch["id"],
            {"pickup_pin": "0000", "pickup_by_member_id": g["id"]},
            TEST_USERS["coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SECURITY_HOLD_TRIGGERED)
        after = validate_success(
            api.get_child_checkin(ch["id"],
                                  TEST_USERS["coordinator_headers"])
        )
        assert after["status"] == "SECURITY_HOLD"
        assert after["hold_reason"] == "PIN_MISMATCH"


class TestSmallGroupLeaderEligibility:
    def test_leader_not_regular_or_member_rejected(self, api):
        """PRD §3.7: "The leader's membership_status MUST be REGULAR or
        MEMBER; violating this returns ERR_MEMBERSHIP_INELIGIBLE."

        Design: Corner/validations/small_group_leader_not_regular_or_member
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        # membership_status defaults to VISITOR — not REGULAR/MEMBER.
        resp = api.create_small_group(
            {"name": "Study", "leader_member_id": m["id"],
             "ministry_area": "STUDY", "capacity": 10},
            TEST_USERS["coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_INELIGIBLE)
