"""Booking-creation constraints: the table half-open overlap rule, the
flexologist buffer geometry, the strike-suspension threshold boundary, and the
validation rejections (intro gate, certification, cross-location integrity,
business hours, closed location, insufficient credits, add-on state).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures,
    factories,
    make_member_headers,
    make_front_desk_headers,
    make_studio_manager_headers,
)

FD = make_front_desk_headers()
SM = make_studio_manager_headers()


# ===========================================================================
# boundary_precision_check — strike threshold at exactly 5 / >= 5
# ===========================================================================

class TestStrikeThreshold:
    def test_two_no_shows_below_threshold_stay_active(self, api):
        """PRD §3.6: "A `NO_SHOW` event is worth 2 `points`; a `LATE_CANCEL` event is worth 1 point."
        PRD §3.6: "When the recomputed `strike_score` reaches 5 or more, the member's `status` is set to `SUSPENDED`; when it is strictly below 5, the member is `ACTIVE` and is reinstated automatically on the next recompute."

        Exactly two NO_SHOWs -> score 4 (< 5) -> member stays ACTIVE.

        Design: Difficulty/boundary_precision_check/strike_threshold_at_exactly_five_suspends
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=3, no_show_fee_cents=5000)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"],
                                [t1, t2],
                                ["2026-04-12T10:00:00Z", "2026-04-12T12:00:00Z"],
                                "2026-04-12T13:30:00Z", "CREDIT_PACK", pack["id"])
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["strike_score"] == 4, f"expected 4, got {member['strike_score']}"
        assert member["status"] == "ACTIVE"

    def test_third_no_show_crosses_threshold_suspends(self, api):
        """PRD §3.6: "When the recomputed `strike_score` reaches 5 or more, the member's `status` is set to `SUSPENDED".
        PRD §2.8: "Any `CONFIRMED` booking whose `session_end_utc` is at or before the clock is marked `NO_SHOW` (see §3.5)."

        Two NO_SHOWs (4) then a third NO_SHOW via sweep -> score 6 (>= 5) ->
        SUSPENDED.

        Design: Difficulty/boundary_precision_check/strike_threshold_at_exactly_five_suspends
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=4, no_show_fee_cents=5000)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2, t3 = s["tables"][1], s["tables"][2], s["tables"][3]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        # create all three CONFIRMED bookings first
        ns1 = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                t1, "2026-04-12T10:00:00Z", "CREDIT_PACK", pack["id"])
        ns2 = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                t2, "2026-04-12T12:00:00Z", "CREDIT_PACK", pack["id"])
        ns3 = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                t3, "2026-04-13T10:00:00Z", "CREDIT_PACK", pack["id"])
        # sweep the first two only (clock past their ends, before ns3 end)
        fixtures.set_clock("2026-04-12T13:30:00Z")
        validate_success(api.no_show_sweep(SM))
        mid = validate_success(api.get_member(mem["id"], FD))
        assert mid["strike_score"] == 4 and mid["status"] == "ACTIVE"
        # advance past ns3 end and sweep -> score 6
        fixtures.set_clock("2026-04-13T11:30:00Z")
        validate_success(api.no_show_sweep(SM))
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["strike_score"] == 6, f"expected 6, got {member['strike_score']}"
        assert member["status"] == "SUSPENDED"


# ===========================================================================
# boundary_precision / resource_temporal_overlap — table half-open interval
# ===========================================================================

class TestTableOverlap:
    def test_adjacent_booking_end_equals_start_allowed(self, api):
        """PRD §3.3: "Table availability is then checked on a half-open interval from start to end: no other non-terminal booking on the same `table_id` may overlap that interval, though exact adjacency, where one session's end equals the next session's start, is allowed; a conflict is `ERR_TABLE_UNAVAILABLE` (HTTP 409)."

        Prior 50-min session 10:00-10:50 on T1; a new session at 10:50 (== prior
        end) is ACCEPTED.

        Design: Difficulty/boundary_precision_check/table_adjacent_booking_end_equals_start_allowed
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1 = s["tables"][0]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        adj = validate_success(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flexB, t1,
                "2026-04-20T10:50:00Z", "CREDIT_PACK", pack["id"]), FD),
            expected_status=201)
        assert adj["schedule_status"] == "REQUESTED"
        assert adj["table_id"] == t1

    def test_table_inner_start_rejected(self, api):
        """PRD §3.3: "no other non-terminal booking on the same `table_id` may overlap that interval ... a conflict is `ERR_TABLE_UNAVAILABLE` (HTTP 409)."

        A new session starting at 10:30 (strictly inside the prior [10:00,10:50)
        interval) on the same table is rejected.

        Design: Difficulty/resource_temporal_overlap/table_half_open_overlap_rejects_inner_start
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1 = s["tables"][0]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flexB, t1,
                "2026-04-20T10:30:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_TABLE_UNAVAILABLE.value)

    def test_table_earlier_session_overlapping_prior_start_rejected(self, api):
        """PRD §3.3: "Table availability is then checked on a half-open interval from start to end: no other non-terminal booking on the same `table_id` may overlap that interval".

        A new 50-min session at 09:30 (ends 10:20) overlaps the prior
        [10:00,10:50) interval from the left and is rejected.

        Design: Difficulty/resource_temporal_overlap/table_half_open_overlap_rejects_inner_start
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1 = s["tables"][0]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flexB, t1,
                "2026-04-20T09:30:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_TABLE_UNAVAILABLE.value)

    def test_table_one_minute_before_prior_end_rejected(self, api):
        """PRD §3.3: "Table availability is then checked on a half-open interval from start to end: no other non-terminal booking on the same `table_id` may overlap that interval ... a conflict is `ERR_TABLE_UNAVAILABLE` (HTTP 409)."

        A start at 10:49 (one minute before the prior 10:50 end) overlaps the
        prior [10:00,10:50) and is rejected.

        Design: Difficulty/boundary_precision_check/table_adjacent_booking_end_equals_start_allowed
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1 = s["tables"][0]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flexB, t1,
                "2026-04-20T10:49:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_TABLE_UNAVAILABLE.value)


# ===========================================================================
# resource_temporal_overlap — flexologist buffer geometry
# ===========================================================================

class TestFlexologistBuffer:
    def test_gap_below_buffer_rejected(self, api):
        """PRD §3.3: "Flexologist availability uses a different geometry: a new session conflicts when its start is strictly earlier than a prior non-terminal session's end plus the location's `flexologist_buffer_minutes`, meaning the gap between consecutive sessions for the same `flexologist_id` must be at least the buffer; a conflict is `ERR_FLEXOLOGIST_UNAVAILABLE` (HTTP 409)."

        Prior session ends 10:50, buffer 15: a session starting 11:00 (gap 10 <
        15) on a different table but same flexologist is rejected.

        Design: Difficulty/resource_temporal_overlap/flexologist_buffer_gap_must_meet_minimum
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=3, flexologist_buffer_minutes=15)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"], t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], t2,
                "2026-04-20T11:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_FLEXOLOGIST_UNAVAILABLE.value)

    def test_gap_exactly_buffer_accepted(self, api):
        """PRD §3.3: "a new session conflicts when its start is strictly earlier than a prior non-terminal session's end plus the location's `flexologist_buffer_minutes`, meaning the gap between consecutive sessions for the same `flexologist_id` must be at least the buffer".

        Prior session ends 10:50, buffer 15: a session starting 11:05 (gap exactly
        15) on the same flexologist is accepted.

        Design: Difficulty/resource_temporal_overlap/flexologist_buffer_gap_must_meet_minimum
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=3, flexologist_buffer_minutes=15)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"], t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        ok = validate_success(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], t2,
                "2026-04-20T11:05:00Z", "CREDIT_PACK", pack["id"]), FD),
            expected_status=201)
        assert ok["schedule_status"] == "REQUESTED"


# ===========================================================================
# Corner: booking-creation validation rejections
# ===========================================================================

class TestBookingValidations:
    def test_intro_required_blocks_non_intro_first_booking(self, api):
        """PRD §3.2: "While `intro_completed` is false, the member may book only a service whose `kind` is `INTRO`; any attempt to book a non-intro service before the intro is completed is rejected with `ERR_INTRO_REQUIRED` (HTTP 409)."

        Design: Corner/validations/intro_required_blocks_non_intro_first_booking
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        table = fixtures.create_table(loc["id"])
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        mem = fixtures.create_member(loc["id"])
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table["id"],
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_INTRO_REQUIRED.value)

    def test_intro_with_uncertified_flexologist_rejected(self, api):
        """PRD §3.3: "an `INTRO` booking requires the assigned flexologist's `certified_intro` to be true; otherwise the booking is rejected with `ERR_FLEXOLOGIST_NOT_CERTIFIED` (HTTP 422)."

        Design: Corner/validations/intro_flexologist_not_certified
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440)
        flex = fixtures.create_flexologist(loc["id"], full_name="Plain", certified_intro=False)
        table = fixtures.create_table(loc["id"])
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        mem = fixtures.create_member(loc["id"])
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc_intro["id"], flex["id"], table["id"],
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_FLEXOLOGIST_NOT_CERTIFIED.value)

    def test_service_from_other_location_rejected(self, api):
        """PRD §3.3: "the chosen service, flexologist, table, and funding wallet must all belong to the booking's `location_id`, and the `funding_id` type must agree with `funding_source`; any mismatch is `ERR_LOCATION_MISMATCH` (HTTP 422)."

        Design: Corner/validations/location_mismatch_service_from_other_location
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        locA = fixtures.create_location(name="A", open_minute_of_day=0, close_minute_of_day=1440)
        locB = fixtures.create_location(name="B", open_minute_of_day=0, close_minute_of_day=1440)
        flex = fixtures.create_flexologist(locA["id"], certified_intro=True)
        table = fixtures.create_table(locA["id"])
        svc_introA = fixtures.create_service(locA["id"], name="Intro", kind="INTRO",
                                             duration_minutes=25, credit_cost=0, list_price_cents=0)
        svcB = fixtures.create_service(locB["id"], name="B-50m", kind="ASSISTED_STRETCH",
                                       duration_minutes=50, credit_cost=1, list_price_cents=6000)
        mem = fixtures.create_member(locA["id"])
        pack = fixtures.create_credit_pack(mem["id"], locA["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.complete_intro(mem["id"], locA["id"], flex["id"], table["id"], svc_introA["id"],
                                pack_id=pack["id"])
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], locA["id"], svcB["id"], flex["id"], table["id"],
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_LOCATION_MISMATCH.value)

    def test_session_in_the_past_rejected(self, api):
        """PRD §3.3: "The temporal feasibility check requires that `session_start_utc` be strictly later than the clock, that it fall within the location's open and close minutes, and that the referenced service, flexologist, and table all be in their bookable state at the correct location; a violation is `ERR_OUTSIDE_BUSINESS_HOURS` (HTTP 422)".

        Clock at 04-20T12:00Z, attempt a 04-19 session (in the past).

        Design: Corner/validations/booking_in_the_past_outside_hours
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-20T12:00:00Z")
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table,
                "2026-04-19T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_OUTSIDE_BUSINESS_HOURS.value)

    def test_booking_at_closed_location_rejected(self, api):
        """PRD §3.1: "A location's `status` begins `OPEN`; closing it transitions `status` to `CLOSED`, after which new bookings at that location are blocked."
        PRD §3.3: "A booking at a `CLOSED` location is rejected with `ERR_LOCATION_CLOSED` (HTTP 409)."

        Design: Corner/validations/location_closed_blocks_booking
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        validate_success(api.close_location(loc["id"], SM))
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table,
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_LOCATION_CLOSED.value)

    def test_insufficient_credits_rejected(self, api):
        """PRD §2.6: "A booking hold is admitted only when, evaluated in this order, the wallet's `available_credits` is at least the booking's `credit_cost`. When that is not true the booking is rejected with `ERR_INSUFFICIENT_CREDITS` (HTTP 409)."

        Service credit_cost=2 against a 1-credit pack -> rejected.

        Design: Corner/validations/insufficient_credits_on_booking
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        pack1 = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=1,
                                            base_unit_price_cents=100)
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table,
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack1["id"]), FD),
            ApiErrorId.ERR_INSUFFICIENT_CREDITS.value)

    def test_addon_on_completed_booking_rejected(self, api):
        """PRD §3.5: "An add-on may be attached only while the booking's `schedule_status` is `REQUESTED` or `CONFIRMED`; attaching to a booking in any other state is rejected with `ERR_ADDON_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/validations/addon_not_allowed_on_terminal_booking
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc_intro = s["svc_intro"]
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_completed_booking(mem["id"], loc["id"], svc_intro["id"], flex["id"],
                                               table, "2026-04-12T08:00:00Z", "CREDIT_PACK",
                                               pack["id"], complete_clock="2026-04-12T08:30:00Z")
        validate_error(api.add_addon(bk["id"], factories.create_addon_payload(kind="COMPRESSION"), FD),
                       ApiErrorId.ERR_ADDON_NOT_ALLOWED.value)
