"""Booking and membership state-machine claims: parallel schedule/credit
dimensions, the membership ACTIVE<->FROZEN cycle, initial state, invalid
transitions, the complete precondition, and credit-pack depletion/expiry/retire
transitions.
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
    make_flexologist_headers,
)

FD = make_front_desk_headers()
SM = make_studio_manager_headers()


# ===========================================================================
# non_linear_state_machine — membership ACTIVE -> FROZEN -> ACTIVE cycle
# ===========================================================================

class TestMembershipCycle:
    def test_active_frozen_active_cycle_increments_version(self, api):
        """PRD §3.7: "On a successful freeze the `status` moves `ACTIVE → FROZEN`, the `version` increments by one, and a fee credit is accrued into `freeze_credit_cents`."
        PRD §3.7: "Unfreezing requires the membership be `FROZEN` and that `expected_membership_version` match; it moves `status` `FROZEN → ACTIVE` and increments `version`."

        version 1 -> freeze -> 2 -> unfreeze -> 3; final status ACTIVE.

        Design: Difficulty/non_linear_state_machine/membership_active_frozen_active_cycle
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PLUS",
                                          monthly_fee_cents=9000, included_credits=6,
                                          rollover_cap=2)
        hdr = make_member_headers(mem["id"])
        assert ship["version"] == 1
        frozen = validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-12T00:00:00Z",
                                     ship["version"]), hdr))
        assert frozen["status"] == "FROZEN"
        assert frozen["version"] == 2
        reactivated = validate_success(api.unfreeze_membership(
            ship["id"], {"expected_membership_version": frozen["version"]}, hdr))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["version"] == 3

    def test_unfreeze_returns_membership_to_active(self, api):
        """PRD §3.7: "A membership's `status` cycles between `ACTIVE` and `FROZEN` any number of times before it reaches the terminal `CANCELLED`."
        PRD §3.7: "Unfreezing requires the membership be `FROZEN` and that `expected_membership_version` match; it moves `status` `FROZEN → ACTIVE` and increments `version`."

        Design: Difficulty/non_linear_state_machine/membership_active_frozen_active_cycle
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PLUS",
                                          monthly_fee_cents=9000, included_credits=6,
                                          rollover_cap=2)
        hdr = make_member_headers(mem["id"])
        frozen = validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-12T00:00:00Z",
                                     ship["version"]), hdr))
        assert frozen["status"] == "FROZEN"
        reactivated = validate_success(api.unfreeze_membership(
            ship["id"], {"expected_membership_version": frozen["version"]}, hdr))
        assert reactivated["status"] == "ACTIVE"


# ===========================================================================
# non_linear_state_machine — Booking parallel schedule/credit dimensions
# ===========================================================================

class TestBookingParallelDimensions:
    def test_credit_held_until_complete_then_consumed(self, api):
        """PRD §3.4: "A booking carries two independent status dimensions that live on the same row and evolve under their own triggers: `schedule_status`, which tracks the scheduling lifecycle, and `credit_status`, which tracks the wallet."
        PRD §3.4: "On completion `schedule_status` advances `CONFIRMED → COMPLETED` and the credit dimension advances `HELD → CONSUMED`, which means the funding wallet's `held_credits` decreases by the booking's `credit_cost` and its `consumed_credits` increases by the same amount."

        Confirm leaves credit HELD; only complete flips it to CONSUMED.

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_and_credit_dimensions
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            assessment=factories.intro_assessment_payload())
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                     "2026-04-13T10:00:00Z", "MEMBERSHIP", ship["id"])
        confirmed = validate_success(api.confirm_booking(bk["id"], FD))
        assert confirmed["schedule_status"] == "CONFIRMED"
        assert confirmed["credit_status"] == "HELD", "credit must stay HELD on confirm"
        fixtures.set_clock("2026-04-13T10:30:00Z")
        completed = validate_success(api.complete_booking(
            bk["id"], make_flexologist_headers(flex["id"])))
        assert completed["schedule_status"] == "COMPLETED"
        assert completed["credit_status"] == "CONSUMED"

    def test_complete_consumes_wallet_credit(self, api):
        """PRD §3.4: "On completion `schedule_status` advances `CONFIRMED → COMPLETED` and the credit dimension advances `HELD → CONSUMED`, which means the funding wallet's `held_credits` decreases by the booking's `credit_cost` and its `consumed_credits` increases by the same amount."

        8 granted, credit_cost=2: after complete -> consumed 2, held 0, available 6.

        Design: Difficulty/non_linear_state_machine/booking_parallel_schedule_and_credit_dimensions
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        fixtures.create_completed_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                          "2026-04-13T10:00:00Z", "MEMBERSHIP", ship["id"],
                                          complete_clock="2026-04-13T10:30:00Z")
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["consumed_credits"] == 2
        assert m["held_credits"] == 0
        assert m["available_credits"] == 6


# ===========================================================================
# Corner: initial state, invalid transitions, complete precondition
# ===========================================================================

class TestBookingTransitions:
    def test_new_booking_starts_requested_and_held(self, api):
        """PRD §3.3: "On success the booking is born with `schedule_status` `REQUESTED` and `credit_status` `HELD".

        Design: Corner/state_machines/initial_state_booking_requested_held
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = validate_success(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table,
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            expected_status=201)
        assert bk["schedule_status"] == "REQUESTED"
        assert bk["credit_status"] == "HELD"

    def test_cancel_completed_booking_invalid_state(self, api):
        """PRD §3.5: "Cancellation is permitted only while `schedule_status` is `REQUESTED` or `CONFIRMED`; otherwise it is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_already_completed_booking_invalid_state
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_completed_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                               "2026-04-12T10:00:00Z", "CREDIT_PACK", pack["id"],
                                               complete_clock="2026-04-12T10:30:00Z")
        validate_error(api.cancel_booking(bk["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)
        again = validate_success(api.get_booking(bk["id"], FD))
        assert again["schedule_status"] == "COMPLETED"

    def test_complete_before_session_start_invalid_state(self, api):
        """PRD §3.4: "Completing a booking is permitted only when its `schedule_status` is `CONFIRMED`, the clock has reached or passed `session_start_utc`, and `credit_status` is still `HELD`."
        PRD §3.4: "Attempting any transition from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Clock left at 04-11T08:30Z, well before a 04-25 session start.

        Design: Corner/state_machines/complete_before_session_start_invalid_state
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                               "2026-04-25T10:00:00Z", "CREDIT_PACK", pack["id"])
        # clock is still 04-11T08:30Z from the intro completion in the fixture
        validate_error(api.complete_booking(bk["id"], make_flexologist_headers(flex["id"])),
                       ApiErrorId.ERR_INVALID_STATE.value)
        again = validate_success(api.get_booking(bk["id"], FD))
        assert again["schedule_status"] == "CONFIRMED"


# ===========================================================================
# Corner: credit-pack depletion/reactivation and service retirement
# ===========================================================================

class TestCatalogAndPackTransitions:
    def test_pack_depleted_then_active_after_release(self, api):
        """PRD §3.8: "A pack's `status` informally drops to `DEPLETED` the moment its `available_credits` reaches 0 after a hold or consume, and returns to `ACTIVE` when a booking it funded is released and `available_credits` rises above 0 again — depletion is informational and a pack remains usable once credits free up."

        Design: Corner/state_machines/creditpack_depleted_then_active_after_release
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            cancel_window_hours=12)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=1,
                                           base_unit_price_cents=100)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                     "2026-04-25T10:00:00Z", "CREDIT_PACK", pack["id"])
        depleted = validate_success(api.get_credit_pack(pack["id"], FD))
        assert depleted["status"] == "DEPLETED"
        assert depleted["available_credits"] == 0
        # free cancel (clock far before the window) releases the credit
        validate_success(api.cancel_booking(bk["id"], FD))
        reactivated = validate_success(api.get_credit_pack(pack["id"], FD))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["available_credits"] == 1

    def test_booking_retired_service_rejected(self, api):
        """PRD §3.1: "its `status` begins `ACTIVE` and retiring it moves it to `RETIRED`, after which it cannot be booked."
        PRD §3.3: "a violation is `ERR_OUTSIDE_BUSINESS_HOURS` (HTTP 422), which also covers a `RETIRED` service, an `INACTIVE` flexologist, or an `OUT_OF_SERVICE` table."

        Design: Corner/state_machines/booking_retired_service_rejected
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        retired = validate_success(api.retire_service(svc["id"], SM))
        assert retired["status"] == "RETIRED"
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table,
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_OUTSIDE_BUSINESS_HOURS.value)
