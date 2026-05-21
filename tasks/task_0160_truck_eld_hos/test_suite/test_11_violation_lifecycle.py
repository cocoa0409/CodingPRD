"""Violation lifecycle — PRD §3.4, §3.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_violation,
    assert_violation,
    list_violations,
    make_driver_headers,
    report_violation,
    setup_violation_from_overage,
    validate_error,
    validate_success,
)


# ===========================================================================
# Violation creation on overage — PRD §3.4
# ===========================================================================
class TestViolationOnOverage:

    def test_eleven_hour_overage_creates_open_violation(self, api):
        """PRD §3.4: "A driver who completes a duty event such that ...
        the available driving minutes remaining at `event_time`
        becomes negative ... generates a `Violation` row on the
        transition that closes the over-limit DRIVING interval ...
        `rule_code` is one of `ELEVEN_HOUR_DRIVING`,
        `FOURTEEN_HOUR_WINDOW`, `SEVENTY_HOUR_CYCLE`, or
        `SIXTY_HOUR_CYCLE` ... `overage_minutes` is the positive
        number of minutes by which the limit was exceeded at
        detection; `status` is `OPEN`".

        Claim: a closing OFF_DUTY event after 745 minutes of DRIVING
        since the qualifying break produces a Violation row with
        rule_code=ELEVEN_HOUR_DRIVING, status=OPEN,
        overage_minutes=85.
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-08-15T10:00:00.000Z",
        )
        v = state["violation"]
        assert v["rule_code"] == "ELEVEN_HOUR_DRIVING", (
            f"Expected ELEVEN_HOUR_DRIVING, got {v['rule_code']!r}"
        )
        assert v["status"] == "OPEN"
        assert v["overage_minutes"] == 85, (
            f"Expected overage_minutes == 85 (745 - 660), got "
            f"{v['overage_minutes']}"
        )
        assert v["driver_id"] == state["driver"]["id"]
        assert v["triggering_duty_event_id"] == state["closing_event"]["id"]
        assert_violation(v)


# ===========================================================================
# Acknowledge — PRD §3.8
# ===========================================================================
class TestAcknowledge:

    def test_acknowledge_open_violation_moves_to_acknowledged(self, api):
        """PRD §3.8: "A driver acknowledges it, transitioning
        `Violation.status` from `OPEN` to `ACKNOWLEDGED`".

        Claim: acknowledging an OPEN violation returns the violation
        with status="ACKNOWLEDGED".
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-08-16T10:00:00.000Z",
        )
        driver, violation = state["driver"], state["violation"]
        resp = api.acknowledge_violation(
            violation["id"], make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACKNOWLEDGED"

    def test_acknowledge_already_acknowledged_rejected(self, api):
        """PRD §3.8: "an acknowledgement attempt on a violation
        whose `status` is not `OPEN` is rejected with
        `ERR_INVALID_VIOLATION_STATE`."

        Claim: a second acknowledge on a violation whose status is
        already ACKNOWLEDGED fails with ERR_INVALID_VIOLATION_STATE.
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-08-17T10:00:00.000Z",
        )
        driver, violation = state["driver"], state["violation"]
        acknowledge_violation(driver, violation["id"])
        # Second acknowledge.
        resp = api.acknowledge_violation(
            violation["id"], make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VIOLATION_STATE.value)


# ===========================================================================
# Report to FMCSA — PRD §3.8
# ===========================================================================
class TestReport:

    def test_report_acknowledged_violation_succeeds(self, api):
        """PRD §3.8: "A `CarrierSafetyOfficer` whose carrier matches
        the driver's carrier reports the violation, transitioning it
        from `ACKNOWLEDGED` to `REPORTED`; on success the server sets
        `reported_to_fmcsa_at` to the server clock and
        `fmcsa_report_id` to a freshly generated tracking identifier."

        Claim: report on an ACKNOWLEDGED violation succeeds with
        status="REPORTED", reported_to_fmcsa_at non-null, and
        fmcsa_report_id non-null.
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-08-18T10:00:00.000Z",
        )
        driver, violation = state["driver"], state["violation"]
        acknowledge_violation(driver, violation["id"])
        resp = api.report_violation_to_fmcsa(
            violation["id"], TEST_USERS["officer_headers"],
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "REPORTED"
        assert data["reported_to_fmcsa_at"] is not None
        assert data["fmcsa_report_id"] is not None

    def test_report_open_violation_rejected(self, api):
        """PRD §3.8: "A report attempt on a violation whose `status`
        is not `ACKNOWLEDGED` is rejected with
        `ERR_INVALID_VIOLATION_STATE`."

        Claim: reporting an OPEN (not yet ACKNOWLEDGED) violation
        fails with ERR_INVALID_VIOLATION_STATE.
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-08-19T10:00:00.000Z",
        )
        violation = state["violation"]
        assert violation["status"] == "OPEN"
        resp = api.report_violation_to_fmcsa(
            violation["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_VIOLATION_STATE.value)
