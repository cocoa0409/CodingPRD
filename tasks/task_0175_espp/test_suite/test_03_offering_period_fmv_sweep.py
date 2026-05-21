"""OfferingPeriod: grant FMV recording, purchase-date FMV recording,
sweep-driven OPEN -> CLOSED transition, OCC on FMV.

References PRD §3.2, §2.9, §2.10.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_to,
    assert_offering_period,
    assert_status,
    assert_version_incremented_by,
    create_plan,
    create_and_activate_plan,
    get_first_open_offering_period,
    grant_fmv_payload,
    purchase_fmv_payload,
    purchase_fmv_payload_no_version,
    run_sweep,
    setup_active_plan_with_open_period,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Grant-date FMV — PRD §3.2
# ===========================================================================
class TestGrantFmvWindow:
    """PRD §3.2: "the operation accepts a `grant_date_fmv_cents` value
    and is allowed only when the system clock's `current_time` falls
    on the period's `start_date` and `grant_date_fmv_cents` is still
    null. Attempts outside that window, or attempts to overwrite an
    already-set value, are rejected with `ERR_GRANT_FMV_WINDOW`."
    """

    def test_grant_fmv_recorded_on_start_date(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "allowed only when the system clock's `current_time`
        falls on the period's `start_date` and `grant_date_fmv_cents`
        is still null."

        Claim: clock == start_date AND null FMV -> 200 OK + value set.
        """
        plan, op1 = create_and_activate_plan(
            offering_period_months=6,
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=None,
        )
        assert op1.get("grant_date_fmv_cents") is None
        # Advance clock to start_date.
        advance_clock_to(op1["start_date"])
        resp = api.record_grant_fmv(
            plan["id"], op1["id"],
            grant_fmv_payload(grant_date_fmv_cents=1500),
            plan_admin_headers,
        )
        data = validate_success(resp)
        assert data["grant_date_fmv_cents"] == 1500

    def test_grant_fmv_overwrite_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "Attempts ... to overwrite an already-set value,
        are rejected with `ERR_GRANT_FMV_WINDOW`."

        Claim: re-write of grant FMV -> ERR_GRANT_FMV_WINDOW.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        # Clock is already at start_date from the fixture.
        resp = api.record_grant_fmv(
            plan["id"], op1["id"],
            grant_fmv_payload(grant_date_fmv_cents=9999),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_FMV_WINDOW.value)


# ===========================================================================
# Purchase-date FMV — PRD §3.2
# ===========================================================================
class TestPurchaseFmv:
    """PRD §3.2 purchase-date FMV recording rules."""

    def test_purchase_fmv_before_period_end_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "The system requires that `SystemClock.current_time`
        be at or beyond `OfferingPeriod.end_date` at the moment of the
        patch; an earlier attempt is rejected with `ERR_FMV_BEFORE_PERIOD_END`."

        Claim: PATCH purchase FMV with clock < end_date ->
        ERR_FMV_BEFORE_PERIOD_END.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        # Clock is at start_date; well before end_date.
        resp = api.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=2000, version=op1["version"],
            ),
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FMV_BEFORE_PERIOD_END.value)

    def test_purchase_fmv_after_period_end_accepted(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "The system requires that `SystemClock.current_time`
        be at or beyond `OfferingPeriod.end_date` at the moment of the
        patch; an earlier attempt is rejected with `ERR_FMV_BEFORE_PERIOD_END`."

        Claim: PATCH purchase FMV when clock > end_date succeeds with
        version+1.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        advance_clock_to(add_days(op1["end_date"], 1))
        resp = api.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=2000, version=op1["version"],
            ),
            plan_admin_headers,
        )
        data = validate_success(resp)
        assert data["purchase_date_fmv_cents"] == 2000
        assert_version_incremented_by(op1, data, 1)

    def test_purchase_fmv_stale_version_returns_conflict(
        self, api, plan_admin_headers,
    ):
        """PRD §2.10: "patch operations on a plan, on an enrollment, on
        an offering period's purchase-date FMV, and on a disposition all
        accept `version` ... if they differ, the request is rejected
        with `ERR_VERSION_CONFLICT`."

        Claim: second PATCH with stale version -> ERR_VERSION_CONFLICT.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        advance_clock_to(add_days(op1["end_date"], 1))
        # First write succeeds.
        r1 = api.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=2000, version=op1["version"],
            ),
            plan_admin_headers,
        )
        validate_success(r1)
        # Second write with the SAME (now stale) version.
        r2 = api.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=2500, version=op1["version"],
            ),
            plan_admin_headers,
        )
        validate_error(r2, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Sweep transitions OfferingPeriod OPEN -> CLOSED — PRD §3.2, §2.9
# ===========================================================================
class TestPeriodSweep:
    """PRD §3.2 + §2.9 sweep behavior on OPEN OfferingPeriods."""

    def test_sweep_closes_period_after_end_with_fmv_recorded(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "when the system clock reaches or passes
        `end_date` and `purchase_date_fmv_cents` has been recorded
        (not null), the next sweep invocation flips the period to
        `CLOSED`."

        Claim: post-end + FMV-recorded + sweep -> op.status==CLOSED.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        advance_clock_to(add_days(op1["end_date"], 1))
        api.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=2000, version=op1["version"],
            ),
            plan_admin_headers,
        )
        run_sweep()
        resp = api.get_offering_period(op1["id"], plan_admin_headers)
        data = validate_success(resp)
        assert_status(data, "CLOSED")

    def test_sweep_keeps_period_open_without_fmv(
        self, api, plan_admin_headers,
    ):
        """PRD §3.2: "when the system clock reaches or passes `end_date`
        AND `purchase_date_fmv_cents` has been recorded (not null), the
        next sweep invocation flips the period to `CLOSED`."

        Claim: post-end WITHOUT FMV recorded + sweep -> still OPEN.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        advance_clock_to(add_days(op1["end_date"], 1))
        # Sweep WITHOUT recording purchase FMV.
        run_sweep()
        resp = api.get_offering_period(op1["id"], plan_admin_headers)
        data = validate_success(resp)
        assert_status(data, "OPEN")


# ===========================================================================
# Clock advance — PRD §2.9
# ===========================================================================
class TestClockAdvance:
    """PRD §2.9 clock-advance rules."""

    def test_clock_advance_not_strictly_greater_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §2.9: "the supplied timestamp must be strictly greater
        than the current value, otherwise the request is rejected with
        `ERR_CLOCK_NOT_ADVANCING`."

        Claim: clock advance to a timestamp <= current -> 422
        ERR_CLOCK_NOT_ADVANCING.
        """
        advance_clock_to("2024-01-01T00:00:00.000Z")
        # Now attempt to advance to a timestamp NOT strictly greater.
        resp = api.clock_advance(
            {"to_timestamp": "2024-01-01T00:00:00.000Z"},
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_ADVANCING.value)

    def test_clock_advance_to_earlier_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §2.9: "the supplied timestamp must be strictly greater
        than the current value, otherwise the request is rejected with
        `ERR_CLOCK_NOT_ADVANCING`."

        Claim: clock advance to a strictly earlier timestamp ->
        ERR_CLOCK_NOT_ADVANCING.
        """
        advance_clock_to("2024-06-01T00:00:00.000Z")
        resp = api.clock_advance(
            {"to_timestamp": "2024-03-01T00:00:00.000Z"},
            plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_ADVANCING.value)
