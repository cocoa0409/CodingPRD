"""Check-in safety gates: weight ceiling, waiver validity, and state precedence
(PRD §3.6, §2.7, §2.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    set_clock,
    setup_scheduled_flight,
    validate_error,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


class TestWeightBoundaryEqualAllowed:
    """A weight exactly at the ceiling passes; the gate is strictly greater."""

    def _setup(self, api):
        return setup_scheduled_flight(
            api,
            tunnel_kw={"max_weight_kg": 120},
            member_kw={"name": "Edge", "weight_kg": 120},
            booking_kw={"party_size": 1},
            scheduled_minutes=2,
            sign_waiver=True,
            start=False,
        )

    def test_weight_equal_ceiling_checks_in(self, api):
        """PRD §3.6: "the member's `weight_kg` must not exceed the tunnel's
        `max_weight_kg`, where a weight strictly greater than the ceiling is rejected
        with `ERR_WEIGHT_LIMIT_EXCEEDED` while a weight exactly at the ceiling passes."

        Design: Difficulty/boundary_precision_check/weight_limit_equal_allowed_boundary
        """
        ctx = self._setup(api)
        checked_in = validate_success(api.check_in_flight(ctx["flight"]["id"], FRONTDESK), 200)
        assert checked_in["status"] == "CHECKED_IN", checked_in["status"]

    def test_weight_equal_ceiling_persisted(self, api):
        """PRD §3.6: "the member's `weight_kg` must not exceed the tunnel's
        `max_weight_kg`, where a weight strictly greater than the ceiling is rejected
        with `ERR_WEIGHT_LIMIT_EXCEEDED` while a weight exactly at the ceiling passes."

        Design: Difficulty/boundary_precision_check/weight_limit_equal_allowed_boundary
        """
        ctx = self._setup(api)
        api.check_in_flight(ctx["flight"]["id"], FRONTDESK)
        reread = validate_success(api.get_flight(ctx["flight"]["id"], FRONTDESK), 200)
        assert reread["status"] == "CHECKED_IN", reread["status"]


def test_checkin_over_weight_returns_weight_limit_exceeded(api):
    """PRD §3.6: "the member's `weight_kg` must not exceed the tunnel's
    `max_weight_kg`, where a weight strictly greater than the ceiling is rejected with
    `ERR_WEIGHT_LIMIT_EXCEEDED` while a weight exactly at the ceiling passes."

    Design: Corner/validations/checkin_over_weight_returns_weight_limit_exceeded
    """
    ctx = setup_scheduled_flight(
        api,
        tunnel_kw={"max_weight_kg": 120},
        member_kw={"name": "Heavy", "weight_kg": 121},
        booking_kw={"party_size": 1},
        sign_waiver=True,
        start=False,
    )
    resp = api.check_in_flight(ctx["flight"]["id"], FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_WEIGHT_LIMIT_EXCEEDED.value)


def test_checkin_with_expired_waiver_returns_waiver_invalid(api):
    """PRD §2.7: "A waiver reads as `SIGNED` while the current clock is at or before
    `expires_at`, and is treated as `EXPIRED` once the current clock passes
    `expires_at`."
    PRD §3.6: "the member must hold a waiver whose `status` is `SIGNED` with the
    current clock at or before its `expires_at`, else `ERR_WAIVER_INVALID`".

    Design: Corner/state_machines/checkin_with_expired_waiver_returns_waiver_invalid
    """
    ctx = setup_scheduled_flight(
        api,
        booking_kw={"party_size": 1},
        session_kw={"start_utc": "2026-08-10T10:00:00Z", "end_utc": "2026-08-10T10:30:00Z"},
        sign_waiver=True,
        start=False,
    )
    # Waiver was signed at the startup clock (2026-05-01), expiring 2026-07-30.
    set_clock(api, "2026-08-01T00:00:00Z")
    resp = api.check_in_flight(ctx["flight"]["id"], FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID.value)


class TestStatePrecedenceOverSafety:
    """State (priority 4) fires before check-in safety (priority 6)."""

    def _setup_noshow_overweight(self, api):
        ctx = setup_scheduled_flight(
            api,
            tunnel_kw={"max_weight_kg": 70},
            member_kw={"name": "Heavy", "weight_kg": 80},
            booking_kw={"party_size": 1},
            sign_waiver=True,
            start=True,
        )
        # Closing the session turns the still-SCHEDULED flight into NO_SHOW.
        validate_success(api.close_session(ctx["session"]["id"], FRONTDESK), 200)
        return ctx

    def test_state_precedence_returns_invalid_state(self, api):
        """PRD §2.10: "When several validations could apply to one request, they are
        evaluated in a fixed priority order, and the first failure determines the error
        returned. Lower-priority checks are never reached once a higher-priority check
        fails."
        PRD §2.10: "**State** — the target resource must be in a valid state for the
        requested transition (session operational or staffing axis, flight status, or
        booking status), else `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_checkin
        """
        ctx = self._setup_noshow_overweight(api)
        resp = api.check_in_flight(ctx["flight"]["id"], FRONTDESK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_precedence_flight_stays_noshow(self, api):
        """PRD §2.10: "Lower-priority checks are never reached once a higher-priority
        check fails."
        PRD §3.6: "Every flight still `SCHEDULED` or `CHECKED_IN` at close becomes
        `NO_SHOW` with its minutes forfeited and no refund."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_checkin
        """
        ctx = self._setup_noshow_overweight(api)
        api.check_in_flight(ctx["flight"]["id"], FRONTDESK)
        reread = validate_success(api.get_flight(ctx["flight"]["id"], FRONTDESK), 200)
        assert reread["status"] == "NO_SHOW", reread["status"]
