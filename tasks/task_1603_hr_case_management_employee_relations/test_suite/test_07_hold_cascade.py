"""Case hold cascade tests (Difficulty rule 4, instance 1)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_investigating_case,
    schedule_interview,
    set_clock,
    validate_success,
    get_success_data,
)


def _setup_investigating_with_two_interviews():
    """Returns (case, iv1, iv2, inv1) — case INVESTIGATING with 2 SCHEDULED interviews."""
    set_clock("2026-08-05T00:00:00Z")
    channel = setup_intake_channel(
        channel_code="HR_DIRECT", display_name="HR Direct C",
        default_category="RETALIATION", default_severity="HIGH",
        sla_business_days=25,
    )
    reporter = setup_employee(location_code="DAL")
    subject = setup_employee(location_code="DAL")
    witness = setup_employee(location_code="DAL")
    _, inv1 = setup_investigator()
    case = setup_investigating_case(
        channel["id"], subject["id"], inv1["id"],
        reporter_employee_id=reporter["id"],
        category="RETALIATION", severity="HIGH",
    )
    iv1 = schedule_interview(
        case["id"], inv1["id"], subject["id"],
        scheduled_start="2026-07-31T09:00:00Z",
        scheduled_end="2026-07-31T10:00:00Z",
    )
    iv2 = schedule_interview(
        case["id"], inv1["id"], witness["id"],
        scheduled_start="2026-07-31T11:00:00Z",
        scheduled_end="2026-07-31T12:00:00Z",
    )
    return case, iv1, iv2, inv1


class TestHoldCascade:
    def test_hold_cancels_scheduled_interviews(self):
        """PRD §3.6: "The hold cascades downward — every `SCHEDULED` interview
        on the case is cancelled to `CANCELLED` — and for each cancelled
        interview the interviewer undergoes a fresh `active_case_count`
        recomputation, a bookkeeping pass that is not expected to change the
        number but keeps the derived figure current."

        Design: Difficulty/transitive_cascade/hold_cascades_to_interviews_then_interviewer_recompute
        """
        case, iv1, iv2, inv1 = _setup_investigating_with_two_interviews()
        resp = api_client.hold_case(
            case["id"],
            {"hold_reason": "Key witness unavailable pending medical leave; investigation paused."},
            TEST_USERS["er_manager_headers"],
        )
        held = validate_success(resp, 200)
        assert held["status"] == "ON_HOLD"
        # Both scheduled interviews must be CANCELLED
        iv1_after = get_success_data(api_client.get_interview(iv1["id"], TEST_USERS["er_manager_headers"]))
        iv2_after = get_success_data(api_client.get_interview(iv2["id"], TEST_USERS["er_manager_headers"]))
        assert iv1_after["status"] == "CANCELLED", (
            f"iv1 expected CANCELLED, got {iv1_after['status']}"
        )
        assert iv2_after["status"] == "CANCELLED", (
            f"iv2 expected CANCELLED, got {iv2_after['status']}"
        )

    def test_hold_keeps_case_assigned_and_drops_from_active_count(self):
        """PRD §3.1: "the derived `active_case_count` tracks the live figure —
        the number of cases currently assigned to the investigator whose status
        is one of `TRIAGE`, `ASSIGNED`, `INVESTIGATING`, `FINDINGS_DRAFT`,
        `CALIBRATION`, or `PENDING_CLOSURE`. Cases on hold, reopened but not
        yet reassigned, or closed do not count toward the cap."

        Design: Difficulty/transitive_cascade/hold_cascades_to_interviews_then_interviewer_recompute
        """
        case, iv1, iv2, inv1 = _setup_investigating_with_two_interviews()
        inv_before = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_before["active_case_count"] == 1
        resp = api_client.hold_case(
            case["id"],
            {"hold_reason": "Key witness unavailable pending medical leave; investigation paused."},
            TEST_USERS["er_manager_headers"],
        )
        validate_success(resp, 200)
        case_after = get_success_data(
            api_client.get_case(case["id"], TEST_USERS["er_manager_headers"])
        )
        assert case_after["status"] == "ON_HOLD"
        assert case_after["assigned_investigator_id"] == inv1["id"], (
            "Hold must not unassign the investigator"
        )
        # PRD pins ON_HOLD as excluded from the cap-bearing status set, so the
        # recomputed active_case_count for this single-case investigator is 0.
        inv_after = get_success_data(
            api_client.get_investigator(inv1["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv_after["active_case_count"] == 0, (
            f"active_case_count expected 0 while case is ON_HOLD, got {inv_after['active_case_count']}"
        )
