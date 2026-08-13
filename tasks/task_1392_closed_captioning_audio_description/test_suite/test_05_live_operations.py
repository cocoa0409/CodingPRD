"""Live operations: stenographer overlap geometry, committed-minutes capacity
boundary, check-in window edges, preemption/no-show compensation, the offer
cascades, air control gates, and the selector ranking (PRD §3.6, §3.7, §2.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_offer,
    assert_live_assignment,
    assert_same_instant,
    check_in,
    create_client,
    create_live_event,
    create_offer,
    create_stenographer,
    get_success_data,
    make_stenographer_headers,
    run_sweep,
    set_clock,
    setup_accepted_assignment,
    setup_confirmed_event,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS, SCHED

MONDAY = "2026-08-03T10:00:00Z"
LIVE_MONDAY = "2026-08-10T08:00:00Z"


class TestStenographerBufferedOverlap:
    """Difficulty: half-open windows [start-prep, end+wrap) with asymmetric
    buffers; buffer intersection conflicts, edge-touch does not."""

    def _setup(self, api):
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer(certification="CERT_CART")
        # E1 10:00-11:00 prep 15 wrap 5 -> occupied [09:45, 11:05).
        e1 = create_live_event(client["id"], title="E1", start_at="2026-08-10T10:00:00Z",
                               end_at="2026-08-10T11:00:00Z", required_certification="CERT_CART")
        a1 = create_offer(e1["id"], s1["id"])
        accept_offer(a1["id"], s1["id"])
        e2 = create_live_event(client["id"], title="E2", start_at="2026-08-10T11:05:00Z",
                               end_at="2026-08-10T12:00:00Z", required_certification="CERT_CART")
        e3 = create_live_event(client["id"], title="E3", start_at="2026-08-10T11:20:00Z",
                               end_at="2026-08-10T12:00:00Z", required_certification="CERT_CART")
        return s1, e2, e3

    def test_buffer_intersection_rejected(self, api):
        """PRD §3.7: "The candidate conflicts with any existing assignment of
        the same stenographer in `ACCEPTED`, `CONFIRMED`, or `LIVE` whenever the
        candidate window's start precedes the existing window's end and the
        candidate window's end follows the existing window's start".
        PRD §3.7: "A conflict is rejected with `ERR_STENOGRAPHER_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/stenographer_buffered_halfopen_overlap
        """
        s1, e2, _ = self._setup(api)
        resp = api.create_assignment(
            e2["id"], {"stenographer_id": s1["id"],
                       "expected_live_event_version": e2["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_STENOGRAPHER_DOUBLE_BOOKED)

    def test_touching_edge_admitted(self, api):
        """PRD §3.7: "touching edges — a candidate starting exactly where
        another ends — are not a conflict."

        Design: Difficulty/resource_temporal_overlap/stenographer_buffered_halfopen_overlap
        """
        s1, _, e3 = self._setup(api)
        offer = validate_success(api.create_assignment(
            e3["id"], {"stenographer_id": s1["id"],
                       "expected_live_event_version": e3["version"]}, SCHED),
            expected_status=201)
        assert_live_assignment(offer)
        assert offer["assignment_status"] == "OFFERED"


class TestCapacityBoundary:
    """Difficulty: committed-minutes cap is inclusive at exactly 300; one minute
    over rejects."""

    def _setup(self, api):
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer()  # default cap 300 (PRD §3.6)
        # Event A 09:00-13:20 (260 min) prep 15 wrap 5 -> booked 280.
        ev_a = create_live_event(client["id"], title="A",
                                 start_at="2026-08-10T09:00:00Z",
                                 end_at="2026-08-10T13:20:00Z")
        a_a = create_offer(ev_a["id"], s1["id"])
        accept_offer(a_a["id"], s1["id"])
        # Event B 14:00-14:20 prep 0 wrap 0 -> booked 20.
        ev_b = create_live_event(client["id"], title="B", channel_id="CH2",
                                 start_at="2026-08-10T14:00:00Z",
                                 end_at="2026-08-10T14:20:00Z",
                                 prep_minutes=0, wrap_minutes=0)
        a_b = create_offer(ev_b["id"], s1["id"])
        # Event C 15:00-15:01 prep 0 wrap 0 -> booked 1.
        ev_c = create_live_event(client["id"], title="C", channel_id="CH3",
                                 start_at="2026-08-10T15:00:00Z",
                                 end_at="2026-08-10T15:01:00Z",
                                 prep_minutes=0, wrap_minutes=0)
        a_c = create_offer(ev_c["id"], s1["id"])
        return s1, a_a, a_b, a_c

    def test_booked_minutes_and_exact_cap_accept(self, api):
        """PRD §3.7: "computes `booked_minutes` as the event's air time in
        seconds divided by sixty and rounded up, plus its `prep_minutes` and
        `wrap_minutes`".
        PRD §3.7: "Equality is allowed; one minute over is rejected with
        `ERR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_300
        """
        s1, a_a, a_b, _ = self._setup(api)
        assert a_a["booked_minutes"] == 280
        assert a_b["booked_minutes"] == 20
        accepted = validate_success(
            api.accept_assignment(a_b["id"], make_stenographer_headers(s1["id"])))
        assert accepted["assignment_status"] == "ACCEPTED"  # committed == 300 == cap

    def test_one_minute_over_cap_rejected(self, api):
        """PRD §3.7: "the stenographer's committed minutes for the event's UTC
        day — the sum of `booked_minutes` over that stenographer's assignments
        in `ACCEPTED`, `CONFIRMED`, or `LIVE` whose events start on that day —
        plus the candidate's `booked_minutes` must not exceed
        `max_daily_live_minutes`. Equality is allowed; one minute over is
        rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_300
        """
        s1, _, a_b, a_c = self._setup(api)
        get_success_data(api.accept_assignment(a_b["id"], make_stenographer_headers(s1["id"])))
        resp = api.accept_assignment(a_c["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        after = validate_success(api.get_assignment(a_c["id"], SCHED))
        assert after["assignment_status"] == "OFFERED"


class TestStateBeatsConstraint:
    """Difficulty pair: accepting a DECLINED assignment while an overlapping
    ACCEPTED booking exists must raise the state error, not the geometry one."""

    def _setup(self, api):
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer()
        e1 = create_live_event(client["id"], title="E1",
                               start_at="2026-08-10T14:00:00Z",
                               end_at="2026-08-10T15:00:00Z")
        a1 = create_offer(e1["id"], s1["id"])
        get_success_data(api.decline_assignment(a1["id"], make_stenographer_headers(s1["id"])))
        e2 = create_live_event(client["id"], title="E2", channel_id="CH2",
                               start_at="2026-08-10T14:30:00Z",
                               end_at="2026-08-10T15:30:00Z")
        a2 = create_offer(e2["id"], s1["id"])
        accept_offer(a2["id"], s1["id"])
        return s1, a1

    def test_declined_accept_returns_invalid_transition(self, api):
        """PRD §2.4: "Requests are validated in a fixed order, and the first
        failing check determines the rejection: authentication of the two
        headers comes first, then role authorization, then resolution of path
        identifiers and body foreign keys from left to right (a dangling
        reference yields `ERR_NOT_FOUND`), then entity-backed ownership
        (`ERR_FORBIDDEN_OWNERSHIP`), then request shape and field constraints
        (`ERR_VALIDATION`), then optimistic concurrency, then state-machine
        admissibility (`ERR_INVALID_TRANSITION`), then segregation-of-duties and
        compliance rules, then temporal windows, then capacity and geometry
        constraints, and finally linked-entity state preconditions."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_assignment_accept
        """
        s1, a1 = self._setup(api)
        resp = api.accept_assignment(a1["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

    def test_rejected_accept_has_no_side_effects(self, api):
        """PRD §2.4: "Requests are validated in a fixed order, and the first
        failing check determines the rejection".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_assignment_accept
        """
        s1, a1 = self._setup(api)
        validate_error(api.accept_assignment(a1["id"], make_stenographer_headers(s1["id"])),
                       ApiErrorId.ERR_INVALID_TRANSITION)
        after = validate_success(api.get_assignment(a1["id"], SCHED))
        assert after["assignment_status"] == "DECLINED"


class TestPreemptionCascade:
    """Difficulty depth-3 chain: preempt -> event falls back -> auto-offer to
    the next-ranked eligible stenographer."""

    def _setup(self, api):
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer(display_name="S1", certified_since="2020-01-01T00:00:00Z")
        s2 = create_stenographer(display_name="S2", certified_since="2021-06-01T00:00:00Z")
        ev = create_live_event(client["id"], title="News Hour",
                               start_at="2026-08-10T14:00:00Z",
                               end_at="2026-08-10T15:00:00Z")
        a1 = create_offer(ev["id"], s1["id"])
        accept_offer(a1["id"], s1["id"])
        set_clock("2026-08-10T13:40:00Z")
        check_in(a1["id"], s1["id"])
        return client, s1, s2, ev, a1

    def test_preempt_moves_assignment_and_drops_event_posture(self, api):
        """PRD §3.7: "Preemption compensates the displaced stenographer:
        `make_up_minutes_credited` grows by the assignment's `booked_minutes`,
        and the committed minutes are released. If no `CONFIRMED` assignments
        remain and the event was `BRIEFED`, the event falls back to `SCHEDULED`".

        Design: Difficulty/transitive_cascade/preemption_reoffer_cascade
        """
        _, s1, _, ev, a1 = self._setup(api)
        preempted = validate_success(api.preempt_assignment(
            a1["id"], {"preemption_reason": "EMERGENCY_REBOOK"}, SCHED))
        assert preempted["assignment_status"] == "PREEMPTED"
        steno = validate_success(api.get_stenographer(s1["id"], SCHED))
        assert steno["make_up_minutes_credited"] == 80  # booked 60 + prep 15 + wrap 5
        event = validate_success(api.get_live_event(ev["id"], SCHED))
        assert event["event_status"] == "SCHEDULED"

    def test_preempt_cascades_auto_offer_to_next_ranked(self, api):
        """PRD §3.7: "the selector runs excluding both the preempted
        stenographer and every stenographer with a prior `DECLINED`,
        `PREEMPTED`, or `NO_SHOW` assignment for the event."
        PRD §3.7: "When `stenographer_id` is omitted, the auto-offer selector
        runs and the resulting offer's `origin` is `AUTO_OFFER`."

        Design: Difficulty/transitive_cascade/preemption_reoffer_cascade
        """
        _, s1, s2, ev, a1 = self._setup(api)
        get_success_data(api.preempt_assignment(
            a1["id"], {"preemption_reason": "EMERGENCY_REBOOK"}, SCHED))
        offers = get_success_data(api.list_assignments(
            SCHED, params={"live_event_id": ev["id"], "assignment_status": "OFFERED"}))
        assert len(offers) == 1, "exactly one cascade offer must exist"
        assert offers[0]["stenographer_id"] == s2["id"]
        assert offers[0]["origin"] == "AUTO_OFFER"
        assert offers[0]["stenographer_id"] != s1["id"], (
            "the preempted stenographer is never re-offered the same event"
        )


class TestCapacityConservation:
    """Difficulty: committed + released == total ever booked; preemption credits
    make-up minutes, no-show does not."""

    def _setup(self, api):
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer()
        # E1 09:00-10:00 prep 15 wrap 5 -> booked 80; ACCEPTED then PREEMPTED.
        e1 = create_live_event(client["id"], title="E1",
                               start_at="2026-08-10T09:00:00Z",
                               end_at="2026-08-10T10:00:00Z")
        a1 = create_offer(e1["id"], s1["id"])
        accept_offer(a1["id"], s1["id"])
        get_success_data(api.preempt_assignment(
            a1["id"], {"preemption_reason": "SCHEDULER_OVERRIDE"}, SCHED))
        # E2 12:00-12:30 prep 0 wrap 0 -> booked 30; ACCEPTED.
        e2 = create_live_event(client["id"], title="E2", channel_id="CH2",
                               start_at="2026-08-10T12:00:00Z",
                               end_at="2026-08-10T12:30:00Z",
                               prep_minutes=0, wrap_minutes=0)
        a2 = create_offer(e2["id"], s1["id"])
        accept_offer(a2["id"], s1["id"])
        # E3 14:00-14:10 prep 0 wrap 0 -> booked 10; ACCEPTED then NO_SHOW.
        e3 = create_live_event(client["id"], title="E3", channel_id="CH3",
                               start_at="2026-08-10T14:00:00Z",
                               end_at="2026-08-10T14:10:00Z",
                               prep_minutes=0, wrap_minutes=0)
        a3 = create_offer(e3["id"], s1["id"])
        accept_offer(a3["id"], s1["id"])
        set_clock("2026-08-10T14:00:00Z")
        get_success_data(api.mark_no_show(a3["id"], SCHED))
        return client, s1

    def test_make_up_credit_only_for_preemption(self, api):
        """PRD §3.7: "Preemption compensates the displaced stenographer:
        `make_up_minutes_credited` grows by the assignment's `booked_minutes`".
        PRD §3.7: "A no-show, marked by the scheduler at or after the event's
        `start_at`, moves `ACCEPTED` or `CONFIRMED` to `NO_SHOW`:
        `no_show_count` increments, committed minutes are released without
        make-up credit".

        Design: Difficulty/compensating_invariant/preemption_capacity_conservation
        """
        _, s1 = self._setup(api)
        steno = validate_success(api.get_stenographer(s1["id"], SCHED))
        assert steno["make_up_minutes_credited"] == 80
        assert steno["no_show_count"] == 1

    def test_released_capacity_is_immediately_reusable(self, api):
        """PRD §3.7: "the committed minutes are released."
        PRD §3.7: "A conservation invariant ties the counters together: for each
        stenographer and UTC day, the committed minutes plus the released
        minutes always equal the total `booked_minutes` of assignments that ever
        reached `ACCEPTED`."

        Design: Difficulty/compensating_invariant/preemption_capacity_conservation
        """
        client, s1 = self._setup(api)
        # Rewind to before E4's start: offer_expires_at = min(offered+4h,
        # start_at), so an offer created at 14:00 for a 09:50 start would be
        # born expired and could never be accepted (PRD §3.7).
        set_clock("2026-08-10T08:00:00Z")
        # Committed is now 30 (only E2). A fresh 09:50-10:00 event overlaps the
        # freed E1 window; capacity 30 + 10 = 40 <= 300, so it must accept.
        e4 = create_live_event(client["id"], title="E4", channel_id="CH4",
                               start_at="2026-08-10T09:50:00Z",
                               end_at="2026-08-10T10:00:00Z",
                               prep_minutes=0, wrap_minutes=0)
        a4 = create_offer(e4["id"], s1["id"])
        accepted = validate_success(
            api.accept_assignment(a4["id"], make_stenographer_headers(s1["id"])))
        assert accepted["assignment_status"] == "ACCEPTED"


class TestCheckInWindow:
    def test_checkin_window_edges(self, api):
        """PRD §3.7: "Check-in moves `ACCEPTED` → `CONFIRMED`, requires
        ownership, and is only admitted inside a twenty-minute window: from
        thirty minutes before the event's `start_at` through ten minutes before
        it, both bounds inclusive; outside that window the attempt is rejected
        with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409)."
        PRD §3.7: "the first assignment to reach `CONFIRMED` moves the event
        `SCHEDULED` → `BRIEFED`."

        Design: Corner/state_machines/assignment_checkin_window_edges
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer()
        asgs = []
        for i, (start, end) in enumerate((
                ("2026-08-10T14:00:00Z", "2026-08-10T14:30:00Z"),
                ("2026-08-10T16:00:00Z", "2026-08-10T16:30:00Z"),
                ("2026-08-10T18:00:00Z", "2026-08-10T18:30:00Z"))):
            ev = create_live_event(client["id"], title=f"E{i+1}", channel_id=f"CH{i+1}",
                                   start_at=start, end_at=end)
            a = create_offer(ev["id"], s1["id"])
            accept_offer(a["id"], s1["id"])
            asgs.append((ev, a))
        # Window edge: exactly start-30min -> admitted.
        set_clock("2026-08-10T13:30:00Z")
        confirmed = validate_success(api.check_in_assignment(
            asgs[0][1]["id"], make_stenographer_headers(s1["id"])))
        assert confirmed["assignment_status"] == "CONFIRMED"
        event = validate_success(api.get_live_event(asgs[0][0]["id"], SCHED))
        assert event["event_status"] == "BRIEFED"
        # One minute before window open -> closed.
        set_clock("2026-08-10T15:29:00Z")
        resp = api.check_in_assignment(asgs[1][1]["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)
        # One minute past window close -> closed.
        set_clock("2026-08-10T17:51:00Z")
        resp = api.check_in_assignment(asgs[2][1]["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)


class TestAirControl:
    def test_go_on_air_requires_confirmed_assignment(self, api):
        """PRD §3.7: "Going on air moves `SCHEDULED` or `BRIEFED` to `ON_AIR`,
        requires at least one `CONFIRMED` assignment (else
        `ERR_GO_ON_AIR_BLOCKED`, HTTP 409)".

        Design: Corner/state_machines/go_on_air_requires_confirmed_assignment
        """
        set_clock(LIVE_MONDAY)
        ctx = setup_accepted_assignment()  # ACCEPTED but never checked in
        set_clock("2026-08-10T13:50:00Z")
        resp = api.go_on_air(ctx["event"]["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_GO_ON_AIR_BLOCKED)
        event = validate_success(api.get_live_event(ctx["event"]["id"], SCHED))
        assert event["event_status"] == "SCHEDULED"
        asg = validate_success(api.get_assignment(ctx["assignment"]["id"], SCHED))
        assert asg["assignment_status"] == "ACCEPTED"

    def test_event_wrap_before_end_invalid(self, api):
        """PRD §3.7: "Wrapping moves `ON_AIR` → `WRAP`, requires the instant to
        be at or after `end_at`, and moves every `LIVE` assignment to
        `COMPLETED`."
        PRD §3.7: "Going on air ... is admitted only from thirty minutes before
        `start_at` up to (but not including) `end_at` — outside that span the
        attempt is rejected with `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/event_wrap_before_end_invalid
        """
        set_clock(LIVE_MONDAY)
        ctx = setup_confirmed_event(checkin_at="2026-08-10T13:40:00Z")
        set_clock("2026-08-10T13:50:00Z")
        get_success_data(api.go_on_air(ctx["event"]["id"], SCHED))
        resp = api.wrap_event(ctx["event"]["id"], SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        set_clock("2026-08-10T15:00:00Z")  # exactly end_at
        wrapped = validate_success(api.wrap_event(ctx["event"]["id"], SCHED))
        assert wrapped["event_status"] == "WRAP"
        asg = validate_success(api.get_assignment(ctx["assignment"]["id"], SCHED))
        assert asg["assignment_status"] == "COMPLETED"

    def test_live_event_settle_creates_archive_item(self, api):
        """PRD §3.7: "Settling moves `WRAP` → `SETTLED` and creates the event's
        `ArchiveItem` in `ACTIVE_HOLD` with `retention_class` `LIVE_ONLY`."
        PRD §3.9: "The archive holds one item per delivered track and one per
        settled live event."

        Design: Corner/state_machines/live_event_settle_creates_archive_item
        """
        set_clock(LIVE_MONDAY)
        ctx = setup_confirmed_event()
        get_success_data(api.go_on_air(ctx["event"]["id"], SCHED))
        set_clock("2026-08-10T15:00:00Z")
        get_success_data(api.wrap_event(ctx["event"]["id"], SCHED))
        settled = validate_success(api.settle_event(ctx["event"]["id"], SCHED))
        assert settled["event_status"] == "SETTLED"
        items = get_success_data(api.list_archive_items(
            OPS, params={"live_event_id": ctx["event"]["id"]}))
        assert len(items) == 1
        assert items[0]["retention_class"] == "LIVE_ONLY"
        assert items[0]["archive_status"] == "ACTIVE_HOLD"


class TestSelector:
    def test_selector_ranking_and_tiebreak(self, api):
        """PRD §3.7: "Ranking is by committed minutes on the event day
        ascending, then `certified_since` ascending (seniority wins ties), then
        `created_at` ascending; the first candidate by that order wins."
        PRD §3.7: "computes `offer_expires_at` as the earlier of four hours
        after `offered_at` and the event's `start_at`".

        Design: Corner/calculations/selector_ranking_and_tiebreak
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s_busy = create_stenographer(display_name="Busy",
                                     certified_since="2019-01-01T00:00:00Z")
        s_old = create_stenographer(display_name="IdleOld",
                                    certified_since="2020-01-01T00:00:00Z")
        create_stenographer(display_name="IdleNew",
                            certified_since="2020-01-01T00:00:00Z")
        # S_busy picks up 60 committed minutes on the event day.
        ev0 = create_live_event(client["id"], title="Early",
                                start_at="2026-08-10T09:00:00Z",
                                end_at="2026-08-10T10:00:00Z",
                                prep_minutes=0, wrap_minutes=0)
        a0 = create_offer(ev0["id"], s_busy["id"])
        accept_offer(a0["id"], s_busy["id"])
        # Target event; offer with stenographer omitted -> selector runs.
        ev_t = create_live_event(client["id"], title="Target", channel_id="CH2",
                                 start_at="2026-08-10T14:00:00Z",
                                 end_at="2026-08-10T15:00:00Z")
        offer = validate_success(api.create_assignment(
            ev_t["id"], {"expected_live_event_version": ev_t["version"]}, SCHED),
            expected_status=201)
        assert offer["stenographer_id"] == s_old["id"], (
            "committed 0 beats 60; certified_since ties; earlier created_at wins"
        )
        assert offer["origin"] == "AUTO_OFFER"
        assert_same_instant(offer["offer_expires_at"], "2026-08-10T12:00:00Z")

    def test_auto_assign_empty_pool_rejected(self, api):
        """PRD §3.7: "An empty pool behaves differently by trigger: a direct
        create with an omitted `stenographer_id` is rejected with
        `ERR_NO_ELIGIBLE_STENOGRAPHER`, while a decline or preemption cascade
        silently creates nothing and leaves the event under-covered."

        Design: Corner/cross_cutting_layers/auto_assign_empty_pool_rejected
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        create_stenographer(certification="CERT_CBC")
        ev = create_live_event(client["id"], required_certification="CERT_CART")
        resp = api.create_assignment(
            ev["id"], {"expected_live_event_version": ev["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STENOGRAPHER)
        offers = get_success_data(api.list_assignments(
            SCHED, params={"live_event_id": ev["id"]}))
        assert isinstance(offers, list) and len(offers) == 0


class TestOfferOcc:
    def test_assignment_offer_stale_event_version(self, api):
        """PRD §2.5: "Creating a live assignment offer requires
        `expected_live_event_version` to match the event's current `version`; a
        mismatch is rejected with `ERR_STALE_LIVE_EVENT_VERSION` (HTTP 412)."
        PRD §3.7: "Creation increments the event's `version`".

        Design: Corner/cross_cutting_layers/occ_assignment_offer_stale
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer(display_name="S1")
        s2 = create_stenographer(display_name="S2", certified_since="2021-01-01T00:00:00Z")
        ev = create_live_event(client["id"])
        stale_v = ev["version"]
        first = validate_success(api.create_assignment(
            ev["id"], {"stenographer_id": s1["id"],
                       "expected_live_event_version": stale_v}, SCHED),
            expected_status=201)
        assert first["assignment_status"] == "OFFERED"
        after = validate_success(api.get_live_event(ev["id"], SCHED))
        assert after["version"] == stale_v + 1
        resp = api.create_assignment(
            ev["id"], {"stenographer_id": s2["id"],
                       "expected_live_event_version": stale_v}, SCHED)
        validate_error(resp, ApiErrorId.ERR_STALE_LIVE_EVENT_VERSION)
        offers = get_success_data(api.list_assignments(
            SCHED, params={"live_event_id": ev["id"], "stenographer_id": s2["id"]}))
        assert isinstance(offers, list) and len(offers) == 0


class TestOfferExpiry:
    def test_offer_expiry_temporal_then_sweep(self, api):
        """PRD §3.7: "the instant must precede `offer_expires_at` (at or after
        it, the accept is rejected with `ERR_OFFER_EXPIRED`, HTTP 409)".
        PRD §2.7: "offers past their expiry move `OFFERED` → `OFFER_EXPIRED`".
        PRD §3.7: "computes `offer_expires_at` as the earlier of four hours
        after `offered_at` and the event's `start_at`".

        Design: Corner/validations/offer_expiry_temporal_then_sweep
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer()
        ev = create_live_event(client["id"])
        asg = create_offer(ev["id"], s1["id"])
        assert_same_instant(asg["offer_expires_at"], "2026-08-10T12:00:00Z")
        # At exactly offer_expires_at (pre-sweep): temporal guard fires.
        set_clock("2026-08-10T12:00:00Z")
        resp1 = api.accept_assignment(asg["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp1, ApiErrorId.ERR_OFFER_EXPIRED)
        # After the sweep, the state gate fires instead.
        sweep = run_sweep()
        assert sweep["expired_offer_count"] == 1
        resp2 = api.accept_assignment(asg["id"], make_stenographer_headers(s1["id"]))
        validate_error(resp2, ApiErrorId.ERR_INVALID_TRANSITION)
        after = validate_success(api.get_assignment(asg["id"], SCHED))
        assert after["assignment_status"] == "OFFER_EXPIRED"


class TestCertificationLapse:
    def test_sweep_lapses_certification_and_renew(self, api):
        """PRD §3.6: "the sweep moves an `ACTIVE` stenographer past
        `cert_valid_until` to `CERTIFICATION_LAPSED`; and renewal — supplying a
        new `cert_valid_until` later than the current instant — moves
        `CERTIFICATION_LAPSED` → `ACTIVE` with the new expiry stored."
        PRD §3.7: "the named stenographer must be eligible — `ACTIVE`,
        certification matching the event's `required_certification`, and
        `cert_valid_until` no earlier than the event's `end_at` — or the create
        is rejected with `ERR_NO_ELIGIBLE_STENOGRAPHER` (HTTP 422)".

        Design: Corner/cross_cutting_layers/sweep_lapses_certification_and_renew
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer(cert_valid_until="2026-08-05T00:00:00Z")
        ev = create_live_event(client["id"], start_at="2026-08-12T14:00:00Z",
                               end_at="2026-08-12T15:00:00Z")
        sweep = run_sweep()
        assert sweep["lapsed_certification_count"] == 1
        steno = validate_success(api.get_stenographer(s1["id"], SCHED))
        assert steno["steno_status"] == "CERTIFICATION_LAPSED"

        current = validate_success(api.get_live_event(ev["id"], SCHED))
        resp = api.create_assignment(
            ev["id"], {"stenographer_id": s1["id"],
                       "expected_live_event_version": current["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STENOGRAPHER)

        renewed = validate_success(api.renew_certification(
            s1["id"], {"cert_valid_until": "2027-08-01T00:00:00Z"}, SCHED))
        assert renewed["steno_status"] == "ACTIVE"
        current = validate_success(api.get_live_event(ev["id"], SCHED))
        offer = validate_success(api.create_assignment(
            ev["id"], {"stenographer_id": s1["id"],
                       "expected_live_event_version": current["version"]}, SCHED),
            expected_status=201)
        assert offer["assignment_status"] == "OFFERED"


class TestDeclineCascade:
    def test_decline_auto_offer_cascade(self, api):
        """PRD §3.7: "Declining moves `OFFERED` → `DECLINED` — again the caller
        must own the assignment — and triggers the selector with the decliner
        excluded, producing one `AUTO_OFFER` to the next-ranked eligible
        stenographer or, when the pool is empty, nothing at all."
        PRD §3.7: "no existing assignment for this event in `DECLINED`,
        `PREEMPTED`, `NO_SHOW`, or `OFFER_EXPIRED` — an exclusion memory
        ensuring a stenographer who declined or was removed from this event is
        never re-offered it."

        Design: Corner/cross_cutting_layers/decline_auto_offer_cascade
        """
        set_clock(LIVE_MONDAY)
        client = create_client(name="Live Co", compliance_standard="FCC_BROADCAST")
        s1 = create_stenographer(display_name="S1", certified_since="2020-01-01T00:00:00Z")
        s2 = create_stenographer(display_name="S2", certified_since="2021-01-01T00:00:00Z")
        ev = create_live_event(client["id"])
        a1 = create_offer(ev["id"], s1["id"])
        # S1 declines -> cascade offers S2.
        get_success_data(api.decline_assignment(a1["id"], make_stenographer_headers(s1["id"])))
        offers = get_success_data(api.list_assignments(
            SCHED, params={"live_event_id": ev["id"], "assignment_status": "OFFERED"}))
        assert len(offers) == 1
        assert offers[0]["stenographer_id"] == s2["id"]
        assert offers[0]["origin"] == "AUTO_OFFER"
        # S2 declines -> pool empty (both excluded); silent no-op.
        get_success_data(api.decline_assignment(
            offers[0]["id"], make_stenographer_headers(s2["id"])))
        offers_after = get_success_data(api.list_assignments(
            SCHED, params={"live_event_id": ev["id"], "assignment_status": "OFFERED"}))
        assert isinstance(offers_after, list) and len(offers_after) == 0
