"""Cascade and wallet-conservation claims: the late-cancel -> NoShowEvent ->
strike -> suspension depth-3 cascade, freeze cascading into the calendar and
wallet, credit conservation across book/cancel and reschedule, membership renewal
rollover, series cancellation cascade, and immediate wallet reconciliation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
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
# transitive_cascade — late cancel -> NoShowEvent -> strike -> SUSPENDED
# ===========================================================================

class TestStrikeCascade:
    def test_late_cancel_top_up_suspends_member_depth3(self, api):
        """PRD §3.5: "Both a late cancellation and a no-show also create a `NoShowEvent` (see §3.7), which in turn recomputes the member's `strike_score` and may suspend the member; this is a depth-three cascade that completes synchronously within the originating request."
        PRD §3.6: "A `NO_SHOW` event is worth 2 `points`; a `LATE_CANCEL` event is worth 1 point."
        PRD §3.6: "When the recomputed `strike_score` reaches 5 or more, the member's `status` is set to `SUSPENDED".

        Two prior NO_SHOWs (4 pts) + a late-cancel (1 pt) -> strike_score 5 -> SUSPENDED.

        Design: Difficulty/transitive_cascade/late_cancel_event_strike_suspend_depth3
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=4, no_show_fee_cents=5000, late_cancel_pct=0.50, cancel_window_hours=12)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2, t3 = s["tables"][0], s["tables"][1], s["tables"][2]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6500)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        # two NO_SHOWs (4 points)
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"],
                                [t1, t2],
                                ["2026-04-12T10:00:00Z", "2026-04-12T12:00:00Z"],
                                "2026-04-12T13:30:00Z", "CREDIT_PACK", pack["id"])
        # the booking to late-cancel for the 5th point
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               t3, "2026-04-14T10:00:00Z", "CREDIT_PACK", pack["id"])
        fixtures.set_clock("2026-04-13T23:00:00Z")
        late = validate_success(api.cancel_booking(bk["id"], FD))
        assert late["schedule_status"] == "LATE_CANCELLED"
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["strike_score"] == 5, f"expected 5, got {member['strike_score']}"
        assert member["status"] == "SUSPENDED"

    def test_late_cancel_creates_one_point_event(self, api):
        """PRD §3.6: "Every late cancellation and every no-show is recorded as a `NoShowEvent` carrying the member's `member_id`, the `booking_id` that resolved, an `event_kind` of `LATE_CANCEL` or `NO_SHOW`, a `points` value, and the `occurred_utc` instant taken from the logical clock."
        PRD §3.6: "A `NO_SHOW` event is worth 2 `points`; a `LATE_CANCEL` event is worth 1 point."

        A single late-cancel from an empty history lifts strike_score to 1.

        Design: Difficulty/transitive_cascade/late_cancel_event_strike_suspend_depth3
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            no_show_fee_cents=5000, late_cancel_pct=0.50, cancel_window_hours=12)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6500)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               table, "2026-04-14T10:00:00Z", "CREDIT_PACK", pack["id"])
        fixtures.set_clock("2026-04-13T23:00:00Z")
        late = validate_success(api.cancel_booking(bk["id"], FD))
        assert late["schedule_status"] == "LATE_CANCELLED"
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["strike_score"] == 1, f"expected 1, got {member['strike_score']}"
        assert member["status"] == "ACTIVE"


# ===========================================================================
# transitive_cascade — freeze cancels covered bookings, releases wallet
# ===========================================================================

class TestFreezeCascade:
    def test_freeze_cancels_covered_bookings_and_releases_wallet(self, api):
        """PRD §3.7: "Every `CONFIRMED` or `REQUESTED` booking funded by this membership whose `session_start_utc` falls within the half-open span from `freeze_start_utc` up to `freeze_end_utc` is cancelled: its `schedule_status` becomes `CANCELLED`, its `credit_status` moves `HELD → RELEASED`, and its add-ons are voided."

        Two covered CONFIRMED bookings (held 2+2) -> both CANCELLED + RELEASED,
        membership available_credits returns to 8 and held to 0.

        Design: Difficulty/transitive_cascade/freeze_cancels_bookings_releases_wallet_depth2
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        bk1 = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                t1, "2026-05-11T10:00:00Z", "MEMBERSHIP", ship["id"])
        bk2 = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                t2, "2026-05-12T10:00:00Z", "MEMBERSHIP", ship["id"])
        validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-20T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"])))
        b1 = validate_success(api.get_booking(bk1["id"], FD))
        b2 = validate_success(api.get_booking(bk2["id"], FD))
        assert b1["schedule_status"] == "CANCELLED"
        assert b1["credit_status"] == "RELEASED"
        assert b2["credit_status"] == "RELEASED"
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["available_credits"] == 8
        assert m["held_credits"] == 0

    def test_freeze_cascade_voids_addons_on_covered_booking(self, api):
        """PRD §3.7: "Every `CONFIRMED` or `REQUESTED` booking funded by this membership whose `session_start_utc` falls within the half-open span from `freeze_start_utc` up to `freeze_end_utc` is cancelled: its `schedule_status` becomes `CANCELLED`, its `credit_status` moves `HELD → RELEASED`, and its add-ons are voided."
        PRD §3.5: "whenever its parent booking is cancelled, late-cancelled, or no-showed — directly or by cascade — every non-voided add-on on that booking is set to `voided` true."

        Freezing cancels the covered booking and voids its add-on (the second hop
        of the freeze cascade), with the credit released.

        Design: Difficulty/transitive_cascade/freeze_cancels_bookings_releases_wallet_depth2
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               table, "2026-05-12T10:00:00Z", "MEMBERSHIP", ship["id"])
        addon = validate_success(api.add_addon(
            bk["id"], factories.create_addon_payload(kind="COMPRESSION", price_cents=1200), FD),
            expected_status=201)
        assert addon["voided"] is False
        validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-20T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"])))
        b = validate_success(api.get_booking(bk["id"], FD))
        assert b["schedule_status"] == "CANCELLED"
        assert b["credit_status"] == "RELEASED"
        addons, _ = validate_paginated(api.list_addons(bk["id"], FD))
        assert len(addons) == 1
        assert addons[0]["voided"] is True

    def test_freeze_only_cancels_bookings_inside_span(self, api):
        """PRD §3.7: "Every `CONFIRMED` or `REQUESTED` booking funded by this membership whose `session_start_utc` falls within the half-open span from `freeze_start_utc` up to `freeze_end_utc` is cancelled".

        A freeze span [05-10,05-20) cancels the 05-12 booking but leaves the
        05-25 booking (outside) CONFIRMED.

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_freeze_only_cancels_covered_bookings
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        inside = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                   t1, "2026-05-12T10:00:00Z", "MEMBERSHIP", ship["id"])
        outside = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                                    t2, "2026-05-25T10:00:00Z", "MEMBERSHIP", ship["id"])
        validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-20T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"])))
        bi = validate_success(api.get_booking(inside["id"], FD))
        bo = validate_success(api.get_booking(outside["id"], FD))
        assert bi["schedule_status"] == "CANCELLED"
        assert bo["schedule_status"] == "CONFIRMED"


# ===========================================================================
# compensating_invariant — conserved credit quantities
# ===========================================================================

class TestCreditConservation:
    def test_membership_available_conserved_across_book_then_free_cancel(self, api):
        """PRD §3.5: "If the clock is at or before that edge, the cancellation is free: `schedule_status` becomes `CANCELLED`, the credit dimension moves `HELD → RELEASED` (the held credit returns to the wallet's available pool as `held_credits` decreases by `credit_cost`), `fee_charged_cents` stays 0".
        PRD §2.6: "available_credits` is `granted_credits` minus `held_credits` minus `consumed_credits`, floored at zero so it is never negative."

        Book (hold 2) then free-cancel (release 2): available_credits back to 8.

        Design: Difficulty/compensating_invariant/membership_available_credits_conserved_across_book_then_free_cancel
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            cancel_window_hours=12)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                     "2026-04-25T10:00:00Z", "MEMBERSHIP", ship["id"])
        cancelled = validate_success(api.cancel_booking(bk["id"], FD))
        assert cancelled["schedule_status"] == "CANCELLED"
        assert cancelled["credit_status"] == "RELEASED"
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["held_credits"] == 0
        assert m["consumed_credits"] == 0
        assert m["available_credits"] == 8

    def test_membership_available_conserved_across_reschedule(self, api):
        """PRD §3.5: "The predecessor booking is cancelled free of charge — `schedule_status` to `CANCELLED`, credit `HELD → RELEASED`, add-ons voided — and a fresh booking is created in `REQUESTED`/`HELD` with `rescheduled_from_booking_id` set to the predecessor's `id`. The replacement re-runs the full overlap and credit gauntlet of §3.3 and re-holds the credit".
        PRD §2.6: "available_credits is `granted_credits` minus `held_credits` minus `consumed_credits`, floored at zero so it is never negative."

        Forward (book, hold 2) + compensating (reschedule: release 2, re-hold 2)
        leaves the membership available_credits unchanged at 6.

        Design: Difficulty/compensating_invariant/membership_available_credits_conserved_across_book_then_free_cancel
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                               "2026-04-20T10:00:00Z", "MEMBERSHIP", ship["id"])
        before = validate_success(api.get_membership(ship["id"], FD))
        assert before["available_credits"] == 6
        validate_success(api.reschedule_booking(
            bk["id"],
            {"session_start_utc": "2026-04-21T14:00:00Z", "flexologist_id": flexB,
             "table_id": t2}, FD), expected_status=201)
        after = validate_success(api.get_membership(ship["id"], FD))
        assert after["held_credits"] == 2
        assert after["available_credits"] == 6

    def test_pack_held_credits_conserved_across_reschedule(self, api):
        """PRD §3.5: "The predecessor booking is cancelled free of charge — `schedule_status` to `CANCELLED`, credit `HELD → RELEASED`, add-ons voided — and a fresh booking is created in `REQUESTED`/`HELD` with `rescheduled_from_booking_id` set to the predecessor's `id`."

        Reschedule releases the predecessor's 1 held credit and re-holds 1 on the
        replacement: CreditPack held_credits stays 1, available stays 9.

        Design: Difficulty/compensating_invariant/pack_held_credits_conserved_across_reschedule
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                               "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        newbk = validate_success(api.reschedule_booking(
            bk["id"],
            {"session_start_utc": "2026-04-21T14:00:00Z", "flexologist_id": flexB,
             "table_id": t2}, FD), expected_status=201)
        assert newbk["rescheduled_from_booking_id"] == bk["id"]
        assert newbk["credit_status"] == "HELD"
        pred = validate_success(api.get_booking(bk["id"], FD))
        assert pred["schedule_status"] == "CANCELLED"
        assert pred["credit_status"] == "RELEASED"
        p = validate_success(api.get_credit_pack(pack["id"], FD))
        assert p["held_credits"] == 1
        assert p["available_credits"] == 9

    def test_pack_total_credits_conserved_replacement_holds_same_amount(self, api):
        """PRD §3.5: "Rescheduling a non-terminal booking is a cancel-and-recreate."
        PRD §3.5: "The predecessor booking is cancelled free of charge — `schedule_status` to `CANCELLED`, credit `HELD → RELEASED`, add-ons voided — and a fresh booking is created in `REQUESTED`/`HELD` with `rescheduled_from_booking_id` set to the predecessor's `id`."

        The predecessor (HELD 1) is released and the replacement re-holds 1; the
        pack's granted total is unchanged, so available_credits is conserved at 9
        and the replacement is HELD.

        Design: Difficulty/compensating_invariant/pack_held_credits_conserved_across_reschedule
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, n_flexologists=2)
        loc, mem = s["loc"], s["member"]
        flexA, flexB = s["flexes"][0], s["flexes"][1]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flexA, t1,
                                               "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        before = validate_success(api.get_credit_pack(pack["id"], FD))
        assert before["available_credits"] == 9
        newbk = validate_success(api.reschedule_booking(
            bk["id"],
            {"session_start_utc": "2026-04-21T14:00:00Z", "flexologist_id": flexB,
             "table_id": t2}, FD), expected_status=201)
        assert newbk["credit_status"] == "HELD"
        after = validate_success(api.get_credit_pack(pack["id"], FD))
        assert after["available_credits"] == 9


# ===========================================================================
# Corner: renewal rollover, series cancel cascade, immediate consistency
# ===========================================================================

class TestWalletReconciliation:
    def test_renew_carries_capped_rollover(self, api):
        """PRD §3.7: "On renewal the carried-over credits are the smaller of the wallet's current `available_credits` and the `rollover_cap`, and `granted_credits` becomes `included_credits` plus that carried amount; `consumed_credits` resets to 0 while `held_credits` is left unchanged so that open holds persist".

        included 8, rollover_cap 4, available 6 after consuming 2: carry
        min(6,4)=4 -> granted 12, consumed 0, available 12.

        Design: Corner/calculations/rollover_cap_on_renew
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        fixtures.create_completed_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                          "2026-05-05T10:00:00Z", "MEMBERSHIP", ship["id"],
                                          complete_clock="2026-05-05T10:30:00Z")
        renewed = validate_success(api.renew_membership(ship["id"], SM))
        assert renewed["granted_credits"] == 12
        assert renewed["consumed_credits"] == 0
        assert renewed["available_credits"] == 12

    def test_series_cancel_cascades_future_bookings(self, api):
        """PRD §3.9: "Cancelling an active series ends it: `status` moves `ACTIVE → ENDED`, and every future booking generated by this series — those whose `session_start_utc` is strictly after the clock and whose `credit_status` is still `HELD` — is cancelled, with `schedule_status` set to `CANCELLED`, credit moved `HELD → RELEASED`, and add-ons voided."

        A 2-occurrence active series (held 2) -> ENDED; membership held 0,
        available back to 8.

        Design: Corner/endpoints/series_cancel_cascades_future_bookings
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        series = validate_success(api.create_recurring_series(
            factories.create_recurring_series_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table, "MEMBERSHIP", ship["id"],
                "2026-05-20T10:00:00Z", 7, 2), FD), expected_status=201)
        validate_success(api.activate_recurring_series(series["id"], FD))
        ended = validate_success(api.cancel_recurring_series(series["id"], FD))
        assert ended["status"] == "ENDED"
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["held_credits"] == 0
        assert m["available_credits"] == 8

    def test_hold_visible_in_same_request_cycle(self, api):
        """PRD §2.6: "each wallet exposes the same four derived credit fields, reconciled synchronously on every event that touches the wallet: `granted_credits`, `held_credits`, `consumed_credits`, and `available_credits`."
        PRD §3.3: "a hold for `credit_cost` is placed against the funding wallet."

        Booking funded by a 10-credit pack (credit_cost=2): an immediate GET shows
        held_credits=2, available_credits=8.

        Design: Corner/consistency_model/immediate_consistency_wallet_visible_same_response
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"])
        p = validate_success(api.get_credit_pack(pack["id"], FD))
        assert p["held_credits"] == 2
        assert p["available_credits"] == 8
