"""Confirmation side effects, the orientation sign/countersign cycle,
itinerary approval semantics, OCC-guarded date modification, and zone
capacity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_itinerary,
    cancel_booking_payload,
    confirm_booking,
    countersign_orientation,
    create_booking,
    create_geo_zone,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    find_charge,
    get_booking,
    get_single_turn,
    itinerary_payload,
    list_charges,
    list_itineraries,
    modify_booking_payload,
    put_itinerary,
    setup_confirmed_booking,
    setup_fleet_with_rate,
    sign_all_orientation_items,
    sign_orientation_item,
    validate_error,
    validate_success,
    waypoint,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]


def _items_by_code(booking):
    return {item["item_code"]: item for item in booking["orientation_items"]}


class TestConfirmation:
    def test_double_confirm_rejected(self, api):
        """PRD §2.11: "Generic transition state — the resource is not in a
        state that permits the requested transition (confirm on a non-`HELD`
        booking, checkout on a non-`CONFIRMED` booking, settle on a
        non-`RETURNED` booking, sign-item on a `COUNTERSIGNED` orientation,
        inspect on a turn that is not `IN_PROGRESS`, a decision on a
        non-`SUBMITTED` certificate, a resolve on a non-`REPORTED` incident):
        `ERR_INVALID_STATE`."
        PRD §3.5: "a `RENTAL` charge for that amount is posted already `PAID`;
        the deposit dimension moves `PENDING` → `HELD` with
        `deposit_held_cents` set to `deposit_required_cents`; orientation moves
        `NOT_STARTED` → `IN_PROGRESS` with its item set created from the
        vessel's size class; a cleaning turn is created for the booking with
        `scheduled_date` equal to the booking's `end_date`, status `SCHEDULED`,
        and `re_clean_count` 0"

        Design: Corner/state_machines/double_confirm_rejected
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-24")
        booking = ctx["booking"]
        assert booking["status"] == "CONFIRMED"

        resp = api.confirm_booking(booking["id"], ctx["renter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        charges = list_charges(booking["id"])
        rental_lines = [c for c in charges if c["line_type"] == "RENTAL"]
        assert len(rental_lines) == 1, "the first confirm's RENTAL line is not duplicated"
        assert rental_lines[0]["amount_cents"] == 180000  # 4 nights x 45000
        assert rental_lines[0]["status"] == "PAID"

        after = get_booking(booking["id"])
        assert after["deposit_held_cents"] == 150000, (
            "deposit hold is not captured twice"
        )
        turn = get_single_turn(booking["id"])
        assert turn["status"] == "SCHEDULED"


class TestOrientationCycle:
    def test_orientation_countersign_reject_reopens_cycle(self, api):
        """PRD §3.5: "When the last unsigned item is signed, the orientation
        moves `IN_PROGRESS` → `COMPLETED` automatically."
        PRD §3.5: "or rejects the work by responding with `approved` false and
        an `item_code` present in the booking's item set (an unknown code is
        `ERR_INVALID_REQUEST`), which reopens the cycle to `IN_PROGRESS` and
        resets that item's `signed` flag to false"

        Design: Corner/state_machines/orientation_countersign_reject_reopens_cycle
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22")
        booking = ctx["booking"]
        headers = ctx["renter_headers"]

        booking = sign_all_orientation_items(booking["id"], headers,
                                             ctx["size_class"])
        assert booking["orientation_status"] == "COMPLETED"

        booking = countersign_orientation(booking["id"], approved=False,
                                          item_code="DOCKING")
        assert booking["orientation_status"] == "IN_PROGRESS"
        items = _items_by_code(booking)
        assert items["DOCKING"]["signed"] is False, "rejected item is unsigned"
        for code in ("SAFETY_BRIEF", "ANCHORING", "GENERATOR_OPS"):
            assert items[code]["signed"] is True, f"{code} stays signed"

        booking = sign_orientation_item(booking["id"], headers, "DOCKING")
        assert booking["orientation_status"] == "COMPLETED"

        booking = countersign_orientation(booking["id"], approved=True)
        assert booking["orientation_status"] == "COUNTERSIGNED", (
            "the reopen cycle COMPLETED -> IN_PROGRESS -> COMPLETED -> "
            "COUNTERSIGNED is fully traversable"
        )

    def test_orientation_countersign_on_in_progress_rejected(self, api):
        """PRD §3.5: "A `DockStaff` member then countersigns with `approved`
        set to true, moving `COMPLETED` → `COUNTERSIGNED`"
        PRD §2.11: "Generic transition state — the resource is not in a state
        that permits the requested transition (confirm on a non-`HELD` booking,
        checkout on a non-`CONFIRMED` booking, settle on a non-`RETURNED`
        booking, sign-item on a `COUNTERSIGNED` orientation, inspect on a turn
        that is not `IN_PROGRESS`, a decision on a non-`SUBMITTED` certificate,
        a resolve on a non-`REPORTED` incident): `ERR_INVALID_STATE`."

        Design: Corner/state_machines/orientation_countersign_on_in_progress_rejected
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22")
        booking = ctx["booking"]
        headers = ctx["renter_headers"]
        sign_orientation_item(booking["id"], headers, "SAFETY_BRIEF")
        booking = sign_orientation_item(booking["id"], headers, "DOCKING")
        assert booking["orientation_status"] == "IN_PROGRESS", (
            "2 of 4 items signed leaves the orientation IN_PROGRESS"
        )

        resp = api.countersign_orientation(booking["id"], {"approved": True}, DS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_sign_unknown_item_rejected(self, api):
        """PRD §2.11: "Body well-formedness — missing required fields, type
        mismatches, unknown enum members, an unknown orientation `item_code`,
        empty `zone_ids`, a window whose end does not follow its start, a
        duplicate `zone_code`, or an `occurred_at` in the future or before the
        booking's start: `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/sign_unknown_item_rejected
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-22")
        booking = ctx["booking"]
        resp = api.sign_orientation_item(booking["id"], {"item_code": "JETSKI_OPS"},
                                         ctx["renter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

        after = get_booking(booking["id"])
        assert after["orientation_status"] == "IN_PROGRESS"
        assert all(item["signed"] is False for item in after["orientation_items"]), (
            "no item may be marked signed by a rejected request"
        )


class TestItinerary:
    def test_itinerary_superseded_on_replacement(self, api):
        """PRD §3.5: "A booking never counts against itself: submitting a
        replacement supersedes the booking's prior `APPROVED` itinerary before
        any counting, so the new record is evaluated against other bookings
        only. A fully valid submission is created already `APPROVED`, and
        occupancy immediately reflects only the replacement's waypoints."

        Design: Corner/state_machines/itinerary_superseded_on_replacement
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-23",
                                      with_itinerary=True,
                                      zone_code="ZP-SUPER", zone_cap=5)
        booking = ctx["booking"]
        headers = ctx["renter_headers"]
        zone = ctx["zone"]
        assert ctx["itinerary"]["status"] == "APPROVED"

        second = put_itinerary(booking["id"], headers,
                               [waypoint(zone["id"], "2026-08-21")])
        assert second["status"] == "APPROVED"

        records = list_itineraries(booking["id"])
        assert len(records) == 2, "replacement does not duplicate records"
        for record in records:
            assert_itinerary(record)
        by_status = {}
        for record in records:
            by_status.setdefault(record["status"], []).append(record)
        assert len(by_status.get("SUPERSEDED", [])) == 1
        assert len(by_status.get("APPROVED", [])) == 1
        superseded = by_status["SUPERSEDED"][0]
        assert superseded["waypoints"][0]["night_date"] == "2026-08-20", (
            "the earlier record is the one superseded"
        )
        assert by_status["APPROVED"][0]["waypoints"][0]["night_date"] == "2026-08-21"

    def test_waypoint_outside_booking_dates_rejected(self, api):
        """PRD §3.5: "every `night_date` must be an actual night of the
        booking, meaning it falls on or after `start_date` and before
        `end_date` (`ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE`)"

        Design: Corner/validations/waypoint_outside_booking_dates_rejected
        """
        ctx = setup_confirmed_booking(start_date="2026-08-20",
                                      end_date="2026-08-23")
        booking = ctx["booking"]
        zone = create_geo_zone(zone_code="ZP-OOR", name="Out Of Range Bay",
                               allowed_size_classes=["COMPACT_36"])

        # night_date == end_date lies outside the half-open stay interval.
        resp = api.put_itinerary(booking["id"],
                                 itinerary_payload([waypoint(zone["id"], "2026-08-23")]),
                                 ctx["renter_headers"])
        validate_error(resp, ApiErrorId.ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE, 422)

        assert list_itineraries(booking["id"]) == [], (
            "an atomically rejected submission leaves no itinerary record"
        )

    def test_zone_size_class_forbidden_rejected(self, api):
        """PRD §3.5: "every referenced zone must list the vessel's size class
        in its `allowed_size_classes` (`ERR_ZONE_SIZE_CLASS_FORBIDDEN`)"

        Design: Corner/validations/zone_size_class_forbidden_rejected
        """
        ctx = setup_confirmed_booking(size_class="LUXE_56", tank=300, berth=8,
                                      start_date="2026-08-20",
                                      end_date="2026-08-23", party_size=4)
        booking = ctx["booking"]
        zone = create_geo_zone(zone_code="ZP-SMALL", name="Small Boats Only",
                               allowed_size_classes=["COMPACT_36"])

        resp = api.put_itinerary(booking["id"],
                                 itinerary_payload([waypoint(zone["id"], "2026-08-20")]),
                                 ctx["renter_headers"])
        validate_error(resp, ApiErrorId.ERR_ZONE_SIZE_CLASS_FORBIDDEN, 422)


class TestZoneCapacity:
    def _setup_two_vessels_one_cap_zone(self, api):
        v1 = create_vessel(name="Compact A", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        v2 = create_vessel(name="Compact B", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)
        zone = create_geo_zone(zone_code="ZP-NARROW", name="The Narrows",
                               max_vessels_per_night=1,
                               allowed_size_classes=["COMPACT_36"])
        r1, h1, _ = create_qualified_renter(full_name="Zoe Cap", email="zoe@x.com",
                                            cert_number="C-1001")
        r2, h2, _ = create_qualified_renter(full_name="Zach Cap", email="zach@x.com",
                                            cert_number="C-1002",
                                            issuing_authority="USCG",
                                            cert_issued_on="2026-01-16")
        j = create_booking(v1["id"], r1, h1, start_date="2026-08-20",
                           end_date="2026-08-23")
        j = confirm_booking(j["id"], h1)
        put_itinerary(j["id"], h1, [waypoint(zone["id"], "2026-08-21")])
        k = create_booking(v2["id"], r2, h2, start_date="2026-08-21",
                           end_date="2026-08-24")
        k = confirm_booking(k["id"], h2)
        return j, k, h2, zone

    def test_zone_capacity_rejects_at_cap_approves_below(self, api):
        """PRD §3.5: "for every waypoint, the zone's occupancy on that night
        must remain strictly below its `max_vessels_per_night`
        (`ERR_ZONE_CAPACITY_EXCEEDED`)"
        PRD §3.5: "Occupancy for a zone-night counts `APPROVED` itineraries —
        `SUPERSEDED` and `VOID` records never count — whose bookings sit in
        `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED` and which
        contain a waypoint on that zone and night."

        Design: Difficulty/resource_temporal_overlap/zone_aggregate_capacity_per_night
        """
        j, k, h2, zone = self._setup_two_vessels_one_cap_zone(api)

        # J's APPROVED itinerary fills the zone's single slot on 2026-08-21.
        resp = api.put_itinerary(k["id"],
                                 itinerary_payload([waypoint(zone["id"], "2026-08-21")]),
                                 h2)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED, 409)

        ok = api.put_itinerary(k["id"],
                               itinerary_payload([waypoint(zone["id"], "2026-08-22")]),
                               h2)
        record = validate_success(ok, 201)
        assert record["status"] == "APPROVED", (
            "the next night has occupancy 0 < cap 1, so it approves"
        )

    def test_itinerary_validation_atomic_on_capacity_failure(self, api):
        """PRD §3.5: "Validation is atomic and ordered per §2.11: every
        `night_date` must be an actual night of the booking, meaning it falls
        on or after `start_date` and before `end_date`
        (`ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE`); every referenced zone must
        list the vessel's size class in its `allowed_size_classes`
        (`ERR_ZONE_SIZE_CLASS_FORBIDDEN`); and for every waypoint, the zone's
        occupancy on that night must remain strictly below its
        `max_vessels_per_night` (`ERR_ZONE_CAPACITY_EXCEEDED`)."

        Design: Difficulty/resource_temporal_overlap/zone_aggregate_capacity_per_night
        """
        j, k, h2, zone = self._setup_two_vessels_one_cap_zone(api)

        # First waypoint is free, second is at cap: the whole submission fails.
        resp = api.put_itinerary(
            k["id"],
            itinerary_payload([waypoint(zone["id"], "2026-08-22"),
                               waypoint(zone["id"], "2026-08-21")]),
            h2,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED, 409)
        assert list_itineraries(k["id"]) == [], (
            "atomic validation creates no itinerary record on failure"
        )


class TestModifyOptimisticConcurrency:
    def test_occ_modify_stale_version_returns_412(self, api):
        """PRD §2.8: "If another writer has advanced the booking's version
        since that observation — for example a prior date modification that
        changed the quote, or a confirm that captured funds — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
        from acting on a booking state it has not observed. This stale-version
        check is evaluated before any other state preconditions of the
        operation."
        PRD §3.5: "a positive delta is posted `PAID` with funds captured
        immediately, while a negative delta is posted `REFUNDED` and its
        absolute amount is added to `refund_issued_cents`"

        Design: Corner/cross_cutting_layers/occ_modify_stale_version_returns_412
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200,
            rates=[("SHOULDER", "2026-09-01", "2026-10-31", 47000, 10)],
            start_date="2026-09-01", end_date="2026-09-05")
        booking = ctx["booking"]
        headers = ctx["renter_headers"]
        stale_version = booking["version"]
        assert booking["quoted_total_cents"] == 188000  # 4 nights x 47000

        first = validate_success(api.modify_booking(
            booking["id"],
            modify_booking_payload(stale_version, "2026-09-01", "2026-09-04"),
            headers), 200)
        assert first["quoted_total_cents"] == 141000  # 3 nights x 47000
        assert first["version"] == stale_version + 1, "modify bumps version by 1"
        assert first["refund_issued_cents"] == 47000

        charges = list_charges(booking["id"])
        adjustment = find_charge(charges, "RENTAL_ADJUSTMENT")
        assert adjustment["amount_cents"] == -47000
        assert adjustment["status"] == "REFUNDED", "negative delta is refunded"

        # The stale pre-modify version is now rejected.
        resp = api.modify_booking(
            booking["id"],
            modify_booking_payload(stale_version, "2026-09-02", "2026-09-05"),
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = get_booking(booking["id"])
        assert after["start_date"] == "2026-09-01"
        assert after["end_date"] == "2026-09-04", "rejected modify leaves dates alone"
        assert after["quoted_total_cents"] == 141000
