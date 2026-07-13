"""Optimistic concurrency on session booking, and the validation-priority rule
that a business precondition outranks the last-place version check."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_confirmed_order,
    order_version,
    create_session_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

TWO_SESSION_PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
                    "included_revision_rounds": 1, "included_coaching_sessions": 2, "guarantee_type": "NONE"}


class TestReferentialBeatsFiscal:
    PLAN = {"tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
            "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"}

    def test_inactive_coach_error_wins_over_stale_version(self, api):
        """PRD §3.5: "The target coach must be ACTIVE; a booking against an inactive coach
        is rejected with ERR_COACH_INACTIVE (HTTP 409)." PRD §2.12: "Because the version
        check sits last, a booking that is otherwise invalid surfaces its business error
        before any stale-version rejection."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_booking
        """
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"status": "INACTIVE"})
        stale_version = order_version(ctx["order_id"]) - 1
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z",
                                         "2026-04-01T11:00:00Z", stale_version)
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        validate_error(resp, ApiErrorId.ERR_COACH_INACTIVE.value)

    def test_stale_version_is_not_the_reported_error(self, api):
        """PRD §2.12: "Because the version check sits last, a booking that is otherwise
        invalid surfaces its business error before any stale-version rejection." The
        inactive-coach booking with a stale version reports the coach error, never
        ERR_STALE_VERSION.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_booking
        """
        ctx = setup_confirmed_order(plan_overrides=self.PLAN, coach_overrides={"status": "INACTIVE"})
        stale_version = order_version(ctx["order_id"]) - 1
        payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z",
                                         "2026-04-01T11:00:00Z", stale_version)
        resp = api.create_session(ctx["order_id"], payload, ctx["client_headers"])
        error_id = resp.json()["data"]["error_id"]
        assert error_id == ApiErrorId.ERR_COACH_INACTIVE.value
        assert error_id != ApiErrorId.ERR_STALE_VERSION.value


def test_occ_stale_order_version_on_second_booking_rejected(api):
    """PRD §2.8: "if another writer has advanced the order's version since the client last
    read it — every successful booking mutates the order's session and ledger fields and
    increments version by one — the stale request is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_order_version_on_second_booking_rejected
    """
    ctx = setup_confirmed_order(plan_overrides=TWO_SESSION_PLAN, coach_overrides={"buffer_minutes": 15})
    v0 = order_version(ctx["order_id"])
    first = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z", v0)
    validate_success(api.create_session(ctx["order_id"], first, ctx["client_headers"]), 201)
    # Second booking still carries the pre-booking version -> stale.
    second = create_session_payload(ctx["coach_id"], "2026-04-01T14:00:00Z", "2026-04-01T15:00:00Z", v0)
    resp = api.create_session(ctx["order_id"], second, ctx["client_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_order_version_increments_on_booking(api):
    """PRD §2.8: "every successful booking mutates the order's session and ledger fields
    and increments version by one".

    Design: Corner/cross_cutting/occ_order_version_increments_on_booking
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 1, "guarantee_type": "NONE"})
    v0 = order_version(ctx["order_id"])
    payload = create_session_payload(ctx["coach_id"], "2026-04-01T10:00:00Z", "2026-04-01T11:00:00Z", v0)
    validate_success(api.create_session(ctx["order_id"], payload, ctx["client_headers"]), 201)
    v1 = order_version(ctx["order_id"])
    assert v1 > v0, f"version should advance after booking, was {v0} now {v1}"
