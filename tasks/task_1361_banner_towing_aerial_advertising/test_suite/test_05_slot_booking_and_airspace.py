"""Flight-slot booking gates: aircraft double-booking (half-open), stadium
TFR compliance, temporal lead times, seasonal capacity, state-vs-business
precedence, and the approval-revocation cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    book_slot_in,
    create_draft_banner,
    create_pending_approval,
    create_tfr,
    get_capacity,
    get_slot,
    make_client_headers,
    schedule_slot,
    set_clock,
    setup_operation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COMPLIANCE


class TestAircraftTemporalOverlap:

    def test_adjacent_slots_share_aircraft_half_open(self, api):
        """PRD §3.5: "Then the double-booking check — no two slots for the same
        aircraft may overlap in time on the same half-open interval basis as
        §3.4, failing as `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409)." PRD §3.4:
        "merely touching — a slot ending exactly when a TFR begins — does not
        count as overlap."

        A slot ending at 15:00 and a slot starting at 15:00 merely touch, so
        both book onto the same aircraft.

        Design: Difficulty/resource_temporal_overlap/aircraft_double_booking_half_open
        """
        sc = setup_operation(base_code="KADJ")
        slot1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                             planned_duration_hours=1)
        slot2 = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                             planned_duration_hours=1)
        assert slot1["status"] == "BOOKED"
        assert slot2["status"] == "BOOKED"
        assert slot2["assigned_aircraft_id"] == sc["aircraft"]["id"], (
            f"adjacent slot must still be assigned the single eligible "
            f"aircraft, got {slot2['assigned_aircraft_id']}"
        )

    def test_overlapping_slots_on_same_aircraft_rejected(self, api):
        """PRD §3.5: "Then the double-booking check — no two slots for the same
        aircraft may overlap in time on the same half-open interval basis as
        §3.4, failing as `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409)."

        With a single-aircraft fleet, a second slot starting 30 minutes into
        the first slot's hour overlaps and is rejected.

        Design: Difficulty/resource_temporal_overlap/aircraft_double_booking_half_open
        """
        sc = setup_operation(base_code="KOVL")
        book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                     planned_duration_hours=1)
        capacity = get_capacity(sc["capacity"]["id"])
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": sc["banner"]["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T14:30:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": capacity["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_DOUBLE_BOOKED,
                       expected_status=409)


class TestStadiumTFRCompliance:

    def test_slot_ending_exactly_at_tfr_start_allowed(self, api):
        """PRD §3.4: "The two overlap when the slot's start falls before the
        TFR's end and the slot's end falls after the TFR's start; merely
        touching — a slot ending exactly when a TFR begins — does not count
        as overlap." PRD §3.4: "When a slot on a `STADIUM` route overlaps any
        `PUBLISHED` TFR, the booking is rejected with `ERR_TFR_BLOCKS_SLOT`
        (HTTP 409) unless the slot's airspace approval carries
        `stadium_tfr_waiver` as true."

        Slot [14:00, 15:00) against TFR [15:00, 18:00) touches without
        overlapping, so it books without a waiver.

        Design: Difficulty/resource_temporal_overlap/tfr_overlap_half_open_adjacent_allowed
        """
        sc = setup_operation(base_code="KTFA", route_kind="STADIUM",
                             pilot_endorsement="STADIUM_QUALIFIED",
                             date_local="2026-08-13",
                             window_start="2026-08-13T14:00:00Z",
                             window_end="2026-08-13T18:00:00Z",
                             stadium_tfr_waiver=False)
        create_tfr(sc["route"]["id"], starts="2026-08-13T15:00:00Z",
                   ends="2026-08-13T18:00:00Z")
        slot = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                            planned_duration_hours=1)
        assert slot["status"] == "BOOKED"
        assert slot["assigned_aircraft_id"] == sc["aircraft"]["id"]
        assert slot["assigned_pilot_id"] == sc["pilot"]["id"]

    def test_slot_overlapping_tfr_with_waiver_allowed(self, api):
        """PRD §3.4: "When a slot on a `STADIUM` route overlaps any `PUBLISHED`
        TFR, the booking is rejected with `ERR_TFR_BLOCKS_SLOT` (HTTP 409)
        unless the slot's airspace approval carries `stadium_tfr_waiver` as
        true."

        Slot [15:00, 16:00) squarely overlaps TFR [15:00, 18:00), but the
        approval carries the waiver, so the booking succeeds.

        Design: Difficulty/resource_temporal_overlap/tfr_overlap_half_open_adjacent_allowed
        """
        sc = setup_operation(base_code="KTFW", route_kind="STADIUM",
                             pilot_endorsement="STADIUM_QUALIFIED",
                             date_local="2026-08-13",
                             window_start="2026-08-13T14:00:00Z",
                             window_end="2026-08-13T18:00:00Z",
                             stadium_tfr_waiver=True)
        create_tfr(sc["route"]["id"], starts="2026-08-13T15:00:00Z",
                   ends="2026-08-13T18:00:00Z")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        assert slot["status"] == "BOOKED"

    def test_slot_overlapping_tfr_without_waiver_rejected(self, api):
        """PRD §3.4: "When a slot on a `STADIUM` route overlaps any `PUBLISHED`
        TFR, the booking is rejected with `ERR_TFR_BLOCKS_SLOT` (HTTP 409)
        unless the slot's airspace approval carries `stadium_tfr_waiver` as
        true."

        Design: Corner/validations/tfr_blocks_slot_without_waiver
        """
        sc = setup_operation(base_code="KTFB", route_kind="STADIUM",
                             pilot_endorsement="STADIUM_QUALIFIED",
                             date_local="2026-08-13",
                             window_start="2026-08-13T14:00:00Z",
                             window_end="2026-08-13T18:00:00Z",
                             stadium_tfr_waiver=False)
        create_tfr(sc["route"]["id"], starts="2026-08-13T15:00:00Z",
                   ends="2026-08-13T18:00:00Z")
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": sc["banner"]["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TFR_BLOCKS_SLOT, expected_status=409)


class TestCapacityAndTemporalGates:

    def test_booking_beyond_quota_rejected(self, api):
        """PRD §3.5: "Capacity is checked next: the `hours_remaining` of the
        target base-and-month `SeasonalCapacity` must be at least the slot's
        `planned_duration_hours`, failing as `ERR_SEASONAL_CAPACITY_EXCEEDED`
        (HTTP 409)." PRD §2.8: "The derived `hours_remaining` is the quota
        minus the committed hours."

        Quota of 2 hours is fully consumed by a 2-hour booking; the next
        1-hour booking exceeds the remaining zero hours.

        Design: Corner/validations/seasonal_capacity_exceeded_returns_error
        """
        sc = setup_operation(base_code="KCAP", quota=2)
        slot1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                             planned_duration_hours=2)
        assert slot1["status"] == "BOOKED"
        capacity = get_capacity(sc["capacity"]["id"])
        assert capacity["hours_committed"] == 2
        assert capacity["hours_remaining"] == 0
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": sc["banner"]["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T16:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": capacity["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEASONAL_CAPACITY_EXCEEDED,
                       expected_status=409)

    def test_booking_less_than_24h_out_rejected(self, api):
        """PRD §3.5: "the `planned_start_utc` must be at least twenty-four
        hours in the future at booking time, failing as
        `ERR_BOOKING_TOO_SOON` (HTTP 409)".

        The logical clock reads 2026-08-10T12:00:00Z and the slot is planned
        for 2026-08-10T15:00:00Z — only three hours ahead.

        Design: Corner/validations/booking_too_soon_rejected
        """
        sc = setup_operation(base_code="KTSN", clock="2026-08-09T12:00:00Z",
                             date_local="2026-08-10",
                             window_start="2026-08-10T14:00:00Z",
                             window_end="2026-08-10T18:00:00Z")
        set_clock("2026-08-10T12:00:00Z")
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": sc["banner"]["id"],
                "date_local": "2026-08-10",
                "planned_start_utc": "2026-08-10T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_TOO_SOON, expected_status=409)


class TestStatePreemptsBusinessRules:

    def test_cancelled_campaign_masks_tfr_violation(self, api):
        """PRD §2.7: "Domain business rules run after state checks, in the
        priority order given in the relevant §3 workflows, and the
        optimistic-concurrency version comparison runs last of all". The
        from-state check "rejects a transition the resource's current state
        does not permit with `ERR_INVALID_STATE` (HTTP 409)" before any
        business rule such as the §3.4 TFR check (`ERR_TFR_BLOCKS_SLOT`)
        runs.

        The campaign is already CANCELLED and the slot would also overlap a
        PUBLISHED TFR without a waiver; the state rejection surfaces.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_booking
        """
        sc = setup_operation(base_code="KSVB", route_kind="STADIUM",
                             pilot_endorsement="STADIUM_QUALIFIED",
                             with_ready_banner=False,
                             date_local="2026-08-13",
                             window_start="2026-08-13T14:00:00Z",
                             window_end="2026-08-13T18:00:00Z",
                             stadium_tfr_waiver=False)
        create_tfr(sc["route"]["id"], starts="2026-08-13T14:00:00Z",
                   ends="2026-08-13T18:00:00Z")
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        validate_success(api.cancel_campaign(sc["campaign"]["id"],
                                             make_client_headers(sc["client"]["id"])),
                         expected_status=200)
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_cancelled_campaign_masks_unapproved_airspace(self, api):
        """PRD §2.7: "Domain business rules run after state checks" — the
        from-state check rejects "a transition the resource's current state
        does not permit with `ERR_INVALID_STATE` (HTTP 409)" before the §3.5
        airspace-approval business check ("a non-granted or date-mismatched
        approval fails with `ERR_AIRSPACE_NOT_APPROVED` (HTTP 409)") runs.

        The campaign is already CANCELLED and the approval is still PENDING;
        the state rejection surfaces.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_booking
        """
        sc = setup_operation(base_code="KSVA", with_ready_banner=False)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        pending = create_pending_approval(sc["route"]["id"],
                                          date_local="2026-08-14",
                                          window_start="2026-08-14T14:00:00Z",
                                          window_end="2026-08-14T18:00:00Z")
        validate_success(api.cancel_campaign(sc["campaign"]["id"],
                                             make_client_headers(sc["client"]["id"])),
                         expected_status=200)
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": pending["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-14",
                "planned_start_utc": "2026-08-14T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestApprovalRevocationCascade:

    def test_revoke_cancels_booked_slot_and_releases_capacity(self, api):
        """PRD §3.4: "a `GRANTED` approval moved to `REVOKED` cascades
        immediately: every flight slot referencing that approval that is
        still in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` is cancelled to
        `CANCELLED_TFR`, and each cancelled slot releases its planned hours
        back to its month of seasonal capacity."

        Design: Difficulty/transitive_cascade/approval_revoke_cascade_depth3
        """
        sc = setup_operation(base_code="KRVC1")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=3)
        after_book = get_capacity(sc["capacity"]["id"])
        assert after_book["hours_committed"] == 3
        validate_success(
            api.revoke_airspace_approval(sc["approval"]["id"], COMPLIANCE),
            expected_status=200)
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "CANCELLED_TFR", (
            f"slot must cascade to CANCELLED_TFR, got {slot_after['status']}"
        )
        capacity_after = get_capacity(sc["capacity"]["id"])
        assert capacity_after["hours_committed"] == 0, (
            f"cancelled slot must release its planned hours, committed="
            f"{capacity_after['hours_committed']}"
        )

    def test_revoke_cancels_scheduled_slot_and_releases_capacity(self, api):
        """PRD §3.4: "a `GRANTED` approval moved to `REVOKED` cascades
        immediately: every flight slot referencing that approval that is
        still in `BOOKED`, `SCHEDULED`, or `WEATHER_HOLD` is cancelled to
        `CANCELLED_TFR`, and each cancelled slot releases its planned hours
        back to its month of seasonal capacity."

        The cascade reaches a slot that had already advanced to SCHEDULED.

        Design: Difficulty/transitive_cascade/approval_revoke_cascade_depth3
        """
        sc = setup_operation(base_code="KRVC2")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=2)
        schedule_slot(slot["id"])
        validate_success(
            api.revoke_airspace_approval(sc["approval"]["id"], COMPLIANCE),
            expected_status=200)
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "CANCELLED_TFR", (
            f"SCHEDULED slot must cascade to CANCELLED_TFR, got "
            f"{slot_after['status']}"
        )
        capacity_after = get_capacity(sc["capacity"]["id"])
        assert capacity_after["hours_committed"] == 0
        approval_after = validate_success(
            api.get_airspace_approval(sc["approval"]["id"], ADMIN),
            expected_status=200)
        assert approval_after["status"] == "REVOKED"
