"""Curb events and revocation cascades: depth-3 event chain, depth-2 revoke chain,
per-reservation refund rounding.

Covers difficulty queue A: transitive_cascade (event activate depth-3, permit revoke
depth-2), combinatorial_formula (event refund round-each-then-sum). Plus corner case:
close-planned-event invalid state.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_curb_planner_headers,
    make_permittee_headers,
    advance_clock,
    make_policy,
    make_zone,
    make_permittee,
    make_permit,
    activate_permit,
    make_confirmed_reservation,
    make_event,
    setup_active_permit,
    fetch_ledger_entries,
    ledger_entries_for_reservation,
    ledger_entries_of_type,
)


class TestEventActivationDepth3Cascade:
    """activate -> zone SUSPENDED -> reservation CANCELLED_BY_EVENT+REFUNDED -> REFUND ledger."""

    def _setup_and_activate(self, api):
        ctx = setup_active_permit(api, clock="2026-05-20T00:00:00Z")
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        event = make_event(api, [ctx["zone_id"]],
                           "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z", name="Filming")
        advance_clock(api, "2026-05-25T00:00:00Z")  # before reservation start -> full refund
        get_success_data(api.activate_event(event["id"], make_curb_planner_headers("planner1")))
        return ctx, res["id"]

    def test_zone_suspended_and_reservation_cancelled_by_event(self, api):
        """PRD §3.7: "Each zone in the event's zone_ids that is currently ACTIVE is
        suspended by the system, moving to SUSPENDED. Every CONFIRMED reservation on those
        zones whose window overlaps the event window is moved to CANCELLED_BY_EVENT, its
        payment_status moves to REFUNDED, and a ledger REFUND entry is appended for it."

        Design: Difficulty/transitive_cascade/event_activate_zone_reservation_ledger_depth3
        """
        ctx, res_id = self._setup_and_activate(api)
        zone = validate_success(api.get_zone(ctx["zone_id"], make_curb_planner_headers("planner1")))
        assert zone["status"] == "SUSPENDED"
        res = validate_success(api.get_reservation(res_id, make_permittee_headers(ctx["permittee_id"])))
        assert res["booking_status"] == "CANCELLED_BY_EVENT"
        assert res["payment_status"] == "REFUNDED"

    def test_refund_ledger_entry_written_for_displaced_reservation(self, api):
        """PRD §3.7: "if the logical clock is at or before the reservation's start_utc the
        reservation has not begun and its remaining minutes equal its full duration ...
        Each appended REFUND entry carries the negative of that reservation's rounded
        refund together with its reservation_id and zone_id".

        Design: Difficulty/transitive_cascade/event_activate_zone_reservation_ledger_depth3
        """
        ctx, res_id = self._setup_and_activate(api)
        entries = fetch_ledger_entries(api, params={"reservation_id": res_id})
        refunds = ledger_entries_of_type(entries, "REFUND")
        assert len(refunds) == 1, "one REFUND for the displaced reservation"
        assert refunds[0]["amount_cents"] == -900, "not started -> full refund of estimate 900"


class TestPermitRevokeDepth2Cascade:
    """revoke -> future CONFIRMED reservation CANCELLED+REFUNDED -> REFUND ledger."""

    def _setup_and_revoke(self, api):
        ctx = setup_active_permit(api, clock="2026-05-20T00:00:00Z")
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        revoked = get_success_data(
            api.revoke_permit(ctx["permit_id"], "compliance", make_curb_planner_headers("planner1")))
        return ctx, res["id"], revoked

    def test_revoke_cancels_and_refunds_future_reservation(self, api):
        """PRD §3.2: "every CONFIRMED reservation on the permit whose start instant is
        later than the logical clock is moved to CANCELLED, and any such reservation whose
        payment was CAPTURED has its payment_status moved to REFUNDED with a compensating
        ledger REFUND entry equal to the negative of its estimated_price_cents."

        Design: Difficulty/transitive_cascade/permit_revoke_reservation_ledger_depth2
        """
        ctx, res_id, revoked = self._setup_and_revoke(api)
        assert revoked["status"] == "REVOKED"
        res = validate_success(api.get_reservation(res_id, make_permittee_headers(ctx["permittee_id"])))
        assert res["booking_status"] == "CANCELLED"
        assert res["payment_status"] == "REFUNDED"

    def test_revoke_writes_full_refund_ledger_entry(self, api):
        """PRD §3.2: "a compensating ledger REFUND entry equal to the negative of its
        estimated_price_cents."

        Design: Difficulty/transitive_cascade/permit_revoke_reservation_ledger_depth2
        """
        ctx, res_id, _revoked = self._setup_and_revoke(api)
        entries = fetch_ledger_entries(api, params={"reservation_id": res_id})
        refunds = ledger_entries_of_type(entries, "REFUND")
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == -900


class TestEventRefundRounding:
    """Rounding order pinned: round each reservation's refund, then sum."""

    def _setup_two_in_progress_reservations(self, api):
        advance_clock(api, "2026-05-20T00:00:00Z")
        policy = make_policy(api, name="P2", base_rate_cents_per_15min=100)
        zone = make_zone(api, policy["id"], name="Z2", block_face="OAK-200",
                         length_meters=20, capacity_slots=3)
        permittee = make_permittee(api)
        permit = make_permit(api, permittee["id"], [zone["id"]])
        activate_permit(api, permit["id"], permittee["id"])
        r1 = make_confirmed_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T12:00:00Z", "2026-06-01T12:15:00Z")
        r2 = make_confirmed_reservation(
            api, permit["id"], permittee["id"], zone["id"],
            "2026-06-01T12:00:00Z", "2026-06-01T12:15:00Z")
        event = make_event(api, [zone["id"]],
                           "2026-06-01T12:00:00Z", "2026-06-01T13:00:00Z", name="Street Fair")
        advance_clock(api, "2026-06-01T12:10:00Z")  # 5 of 15 minutes remaining each
        activated = get_success_data(api.activate_event(event["id"], make_curb_planner_headers("planner1")))
        return r1["id"], r2["id"], activated

    def test_total_refund_is_round_then_sum(self, api):
        """PRD §3.7: "each reservation's refund is rounded to whole cents first and only
        then are the per-reservation refunds summed into total_refund_cents — summing the
        raw amounts and rounding once would give a different, incorrect result."

        Design: Difficulty/combinatorial_formula/event_refund_round_each_then_sum_mode_b
        """
        _r1, _r2, activated = self._setup_two_in_progress_reservations(api)
        # round(100*5/15)=round(33.33)=33 each; 33+33=66 (sum-then-round would give 67).
        assert activated["total_refund_cents"] == 66

    def test_per_reservation_refund_entries_each_minus_33(self, api):
        """PRD §3.7: "That reservation's refund is its estimated_price_cents multiplied by
        its remaining minutes, divided by its total minutes, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/event_refund_round_each_then_sum_mode_b
        """
        r1_id, r2_id, _activated = self._setup_two_in_progress_reservations(api)
        for rid in (r1_id, r2_id):
            refunds = ledger_entries_of_type(
                fetch_ledger_entries(api, params={"reservation_id": rid}), "REFUND")
            assert len(refunds) == 1, f"one REFUND for reservation {rid}"
            assert refunds[0]["amount_cents"] == -33


def test_close_planned_event_rejected_invalid_state(api):
    """PRD §3.7: "Any event transition attempted from a state where it is not defined is
    refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/close_planned_event_invalid
    """
    advance_clock(api, "2026-05-20T00:00:00Z")
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    event = make_event(api, [zone["id"]],
                       "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z", name="Fair")
    resp = api.close_event(event["id"], make_curb_planner_headers("planner1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_event(event["id"], make_curb_planner_headers("planner1")))
    assert fetched["status"] == "PLANNED"
