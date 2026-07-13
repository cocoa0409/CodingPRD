"""Coaching sessions: the cancel/no-show branch, money conservation on cancel,
coach buffer + client overlap rules, active-coach gating, and free vs overage billing."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_confirmed_order,
    setup_order_with_billable_session,
    book_session,
    order_version,
    create_session_payload,
    create_coach_entity,
    find_addon_by_source_ref,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

ZERO_SESSION_PLAN = {"tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
                     "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}


class TestCancelVsNoShowBranch:
    def _two_billable_sessions(self, api):
        ctx = setup_confirmed_order(plan_overrides=ZERO_SESSION_PLAN, coach_overrides={"buffer_minutes": 15})
        sess_a = book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
                              "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z")
        sess_b = book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
                              "2026-04-01T12:00:00Z", "2026-04-01T13:00:00Z")
        return ctx, sess_a, sess_b

    def test_cancel_and_no_show_reach_divergent_terminal_states(self, api):
        """PRD §3.5: cancelling transitions a session "from SCHEDULED to CANCELLED", and a
        no-show "transitioning the session from SCHEDULED to NO_SHOW; a no-show consumes
        the session with no credit restoration and no refund."

        Design: Difficulty/non_linear_state_machine/session_branching_cancel_vs_no_show
        """
        ctx, sess_a, sess_b = self._two_billable_sessions(api)
        validate_success(api.cancel_session(sess_a["id"], ctx["client_headers"]))
        validate_success(api.no_show_session(sess_b["id"], ctx["coach_headers"]))
        assert validate_success(api.get_session(sess_a["id"], ADMIN))["status"] == "CANCELLED"
        assert validate_success(api.get_session(sess_b["id"], ADMIN))["status"] == "NO_SHOW"

    def test_only_cancel_branch_refunds_money(self, api):
        """PRD §3.5: on cancel "if the session was billable it additionally writes a REFUND
        payment for fee_cents with reason SESSION_REFUND (raising amount_refunded_cents by
        that fee)"; a no-show issues "no credit restoration and no refund." Two billable
        12000 sessions charge 44000 total; only the cancel refunds 12000.

        Design: Difficulty/non_linear_state_machine/session_branching_cancel_vs_no_show
        """
        ctx, sess_a, sess_b = self._two_billable_sessions(api)
        validate_success(api.cancel_session(sess_a["id"], ctx["client_headers"]))
        validate_success(api.no_show_session(sess_b["id"], ctx["coach_headers"]))
        order = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert order["amount_charged_cents"] == 44000
        assert order["amount_refunded_cents"] == 12000
        assert order["net_collected_cents"] == 32000


class TestCancelMoneyConservation:
    def test_cancel_conserves_net_back_to_pre_session(self, api):
        """PRD §2.6: "The order's net_collected_cents is always the amount_charged_cents
        minus the amount_refunded_cents." Charging 12000 for a billable session and
        refunding 12000 on cancel restores net to the pre-session 20000.

        Design: Difficulty/compensating_invariant/session_cancel_money_conservation
        """
        ctx = setup_order_with_billable_session()
        validate_success(api.cancel_session(ctx["session"]["id"], ctx["client_headers"]))
        order = validate_success(api.get_order(ctx["order_id"], ADMIN))
        assert order["amount_charged_cents"] == 32000
        assert order["amount_refunded_cents"] == 12000
        assert order["net_collected_cents"] == 20000

    def test_cancel_cancels_the_auto_generated_addon(self, api):
        """PRD §3.5: cancellation "moves the auto-generated add-on whose source_ref is that
        session from CHARGED to CANCELLED."

        Design: Difficulty/compensating_invariant/session_cancel_money_conservation
        """
        ctx = setup_order_with_billable_session()
        session_id = ctx["session"]["id"]
        validate_success(api.cancel_session(session_id, ctx["client_headers"]))
        addons, _ = validate_paginated(api.list_order_addons(ctx["order_id"], ADMIN))
        addon = find_addon_by_source_ref(addons, session_id)
        assert addon is not None and addon["status"] == "CANCELLED"


class TestCoachBufferBoundary:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 2, "guarantee_type": "NONE"}

    def _prior_booking(self, api):
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"buffer_minutes": 15})
        book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
                     "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z")
        return ctx

    def test_session_exactly_buffer_minutes_after_prior_is_accepted(self, api):
        """PRD §3.1: "The buffer_minutes value is the minimum gap the coach requires after
        each of their sessions before starting another". A start exactly 15 minutes after
        the prior end (11:00 -> 11:15) meets the minimum gap and is accepted.

        Design: Difficulty/boundary_precision_check/coach_buffer_exact_gap_boundary
        """
        ctx = self._prior_booking(api)
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T11:15:00Z",
                                         "2026-04-01T12:00:00Z", order_version(ctx["order_id"]))
        data = validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
        assert data["status"] == "SCHEDULED"

    def test_accepted_boundary_session_is_persisted(self, api):
        """PRD §3.5: "the new session must not fall within buffer_minutes of any existing
        SCHEDULED session on the same coach". The exactly-15-minute gap is outside the
        buffer, so the persisted session is SCHEDULED at the requested start.

        Design: Difficulty/boundary_precision_check/coach_buffer_exact_gap_boundary
        """
        ctx = self._prior_booking(api)
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T11:15:00Z",
                                         "2026-04-01T12:00:00Z", order_version(ctx["order_id"]))
        created = validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
        fetched = validate_success(api.get_session(created["id"], ADMIN))
        assert fetched["status"] == "SCHEDULED"
        assert fetched["scheduled_start"] == "2026-04-01T11:15:00Z"


class TestCoachBufferOverlap:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 2, "guarantee_type": "NONE"}

    def _prior_booking(self, api):
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"buffer_minutes": 15})
        book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
                     "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z")
        return ctx

    def test_session_within_buffer_gap_ten_minutes_conflicts(self, api):
        """PRD §3.5: "the new session must not fall within buffer_minutes of any existing
        SCHEDULED session on the same coach, and a violation is rejected with
        ERR_COACH_SLOT_CONFLICT (HTTP 409)." A 10-minute gap is within the 15-minute buffer.

        Design: Difficulty/resource_temporal_overlap/coach_buffer_expanded_overlap
        """
        ctx = self._prior_booking(api)
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T11:10:00Z",
                                         "2026-04-01T11:40:00Z", order_version(ctx["order_id"]))
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        validate_error(resp, ApiErrorId.ERR_COACH_SLOT_CONFLICT.value)

    def test_session_within_buffer_gap_five_minutes_conflicts(self, api):
        """PRD §3.5: "the new session must not fall within buffer_minutes of any existing
        SCHEDULED session on the same coach, and a violation is rejected with
        ERR_COACH_SLOT_CONFLICT (HTTP 409)." A 5-minute gap is well within the buffer.

        Design: Difficulty/resource_temporal_overlap/coach_buffer_expanded_overlap
        """
        ctx = self._prior_booking(api)
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T11:05:00Z",
                                         "2026-04-01T11:35:00Z", order_version(ctx["order_id"]))
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        validate_error(resp, ApiErrorId.ERR_COACH_SLOT_CONFLICT.value)


class TestClientHalfOpenOverlap:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 3, "guarantee_type": "NONE"}

    def _client_with_first_session(self, api):
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"buffer_minutes": 15})
        coach2 = create_coach_entity(name="Peg Coach", email="peg@x.com", specialty="GENERAL", buffer_minutes=15)
        ctx["coach2_id"] = coach2["id"]
        book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
                     "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z")
        return ctx

    def test_strictly_overlapping_session_on_other_coach_conflicts(self, api):
        """PRD §3.5: "the new session must not strictly overlap the interval from the start
        up to but not including the end of any existing SCHEDULED session for the same
        client ... a violation is rejected with ERR_CLIENT_SLOT_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/client_halfopen_overlap
        """
        ctx = self._client_with_first_session(api)
        payload = create_session_payload(ctx["coach2_id"], "2026-04-01T10:30:00Z",
                                         "2026-04-01T11:30:00Z", order_version(ctx["order_id"]))
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        validate_error(resp, ApiErrorId.ERR_CLIENT_SLOT_CONFLICT.value)

    def test_back_to_back_touching_session_is_accepted(self, api):
        """PRD §3.5: "back-to-back sessions whose endpoints merely touch are allowed". A
        session starting exactly at the prior session's end (11:00) does not strictly
        overlap the half-open interval and is accepted.

        Design: Difficulty/resource_temporal_overlap/client_halfopen_overlap
        """
        ctx = self._client_with_first_session(api)
        payload = create_session_payload(ctx["coach2_id"], "2026-04-01T11:00:00Z",
                                         "2026-04-01T12:00:00Z", order_version(ctx["order_id"]))
        data = validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
        assert data["status"] == "SCHEDULED"


class TestActiveCoachGate:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"}

    def test_booking_inactive_coach_rejected(self, api):
        """PRD §3.5: "The target coach must be ACTIVE; a booking against an inactive coach
        is rejected with ERR_COACH_INACTIVE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/session_booking_requires_active_coach
        """
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"status": "INACTIVE"})
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z",
                                         "2026-04-01T11:00:00Z", order_version(ctx["order_id"]))
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        validate_error(resp, ApiErrorId.ERR_COACH_INACTIVE.value)

    def test_booking_active_coach_succeeds(self, api):
        """PRD §3.1: "Only an ACTIVE coach may take new session bookings." An identical
        booking against an ACTIVE coach is accepted and the session is SCHEDULED.

        Design: Difficulty/cross_entity_state_dependency/session_booking_requires_active_coach
        """
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"status": "INACTIVE"})
        active = create_coach_entity(name="Nix Coach", email="nix@x.com", specialty="GENERAL", status="ACTIVE")
        payload = create_session_payload(active["id"], "2026-04-01T10:00:00Z",
                                         "2026-04-01T11:00:00Z", order_version(ctx["order_id"]))
        data = validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
        assert data["status"] == "SCHEDULED"


def test_included_session_is_free(api):
    """PRD §3.5: "If sessions_used is still below that pool the session is covered, its
    billable flag is false, and its fee_cents is zero."

    Design: Corner/calculations/included_session_is_free
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"})
    payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z",
                                     "2026-04-01T11:00:00Z", order_version(ctx["order_id"]))
    data = validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
    assert data["billable"] is False
    assert data["fee_cents"] == 0
    order = validate_success(api.get_order(ctx["order_id"], ADMIN))
    assert order["amount_charged_cents"] == 20000


def test_session_end_not_after_start_returns_validation(api):
    """PRD §2.12: body well-formedness requires "a session's scheduled_end strictly after
    its scheduled_start ... else ERR_VALIDATION (HTTP 422)."

    Design: Corner/validations/session_end_not_after_start_returns_validation
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"})
    payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z",
                                     "2026-04-01T10:00:00Z", order_version(ctx["order_id"]))
    resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_complete_already_completed_session_returns_not_scheduled(api):
    """PRD §3.5: "Any of complete, cancel, or no-show attempted on a session that is not
    SCHEDULED is rejected with ERR_SESSION_NOT_SCHEDULED (HTTP 409)."

    Design: Corner/state_machines/complete_already_completed_session_returns_not_scheduled
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"})
    session = book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"])
    validate_success(api.complete_session(session["id"], ctx["coach_headers"]))
    resp = api.complete_session(session["id"], ctx["coach_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED.value)
