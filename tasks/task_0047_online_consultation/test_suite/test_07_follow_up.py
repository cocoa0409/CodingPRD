"""Follow-up task lifecycle: planning, reminder firing, form submission,
auto-close vs escalation. Covers PRD §3.8."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    advance_clock,
    api_client,
    create_follow_up,
    create_follow_up_payload,
    fire_reminder,
    get_success_data,
    make_doctor_headers,
    make_patient_headers,
    setup_completed_consultation,
    submit_follow_up_form,
    submit_form_payload,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
)


def _future_iso(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


# =========================================================================
# Create: reminder_channels validation.
# =========================================================================
class TestCreate:

    def test_create_with_empty_channels_rejected(self, api):
        """PRD §3.8: 'An empty or out-of-range reminder_channels value is
        rejected with ERR_REMINDER_CHANNELS_INVALID.'

        Claim: reminder_channels=[] -> 422 ERR_REMINDER_CHANNELS_INVALID.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        res = api.create_follow_up_task(
            create_follow_up_payload(
                consultation_id=state["consultation"]["id"],
                scheduled_reminder_at=_future_iso(3600),
                reminder_channels=[],
            ),
            make_doctor_headers(state["doctor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REMINDER_CHANNELS_INVALID.value)

    def test_create_with_one_channel_succeeds(self, api):
        """PRD §3.8: 'a non-empty subset of reminder_channels drawn from
        SMS, EMAIL, and APP_PUSH'.

        Claim: reminder_channels=['SMS'] -> created in PLANNED status.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(3600),
            reminder_channels=["SMS"],
        )
        assert task["status"] == "PLANNED"
        assert task["reminder_channels"] == ["SMS"]
        assert task.get("abnormal_flag") is False


# =========================================================================
# Fire-reminder: PLANNED -> REMINDED.
# =========================================================================
class TestReminder:

    def test_fire_reminder_advances_to_reminded(self, api):
        """PRD §3.8: 'When the server clock reaches scheduled_reminder_at,
        an admin-driven reminder trigger advances status from PLANNED to
        REMINDED and emits one MULTI_CHANNEL_REMINDER event per channel
        listed in reminder_channels.'

        Claim: after clock advances past scheduled_reminder_at,
        /fire-reminder -> status REMINDED.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(3600),
            reminder_channels=["SMS", "EMAIL"],
        )
        # Advance clock past scheduled_reminder_at
        advance_clock(3600 + 1)
        reminded = fire_reminder(task)
        assert reminded["status"] == "REMINDED"


# =========================================================================
# Submit form: CLOSED vs ESCALATED.
# =========================================================================
class TestSubmitForm:

    def test_normal_submission_closes(self, api):
        """PRD §3.8: 'When abnormal_flag is false, the task advances from
        SUBMITTED to the terminal CLOSED.'

        Claim: form with no abnormal severity -> status CLOSED,
        abnormal_flag false.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(60),
            reminder_channels=["SMS"],
        )
        advance_clock(61)
        fire_reminder(task)
        result = submit_follow_up_form(
            task=task, patient=state["patient"],
            form_payload={"severity": 1, "notes": "Feeling fine"},
        )
        assert result["status"] == "CLOSED"
        assert result["abnormal_flag"] is False

    def test_abnormal_submission_escalates(self, api):
        """PRD §3.8: 'When abnormal_flag is true, the task advances from
        SUBMITTED to the terminal ESCALATED: the system creates a new
        Consultation for the same patient with the same doctor in a
        freshly created state, records the new consultation's id in
        escalation_consultation_id'.

        Claim: form with severity >= ABNORMAL_THRESHOLD -> status
        ESCALATED, escalation_consultation_id set and resolves to a
        Consultation.
        """
        state = setup_completed_consultation(elapsed_seconds=60)
        task = create_follow_up(
            consultation=state["consultation"],
            doctor=state["doctor"],
            scheduled_reminder_at=_future_iso(60),
            reminder_channels=["SMS"],
        )
        advance_clock(61)
        fire_reminder(task)
        # Use clearly-abnormal severity (10) to trigger abnormal_flag.
        result = submit_follow_up_form(
            task=task, patient=state["patient"],
            form_payload={"severity": 10, "notes": "Bleeding"},
        )
        assert result["status"] == "ESCALATED"
        assert result["abnormal_flag"] is True
        escalation_id = result.get("escalation_consultation_id")
        assert escalation_id, (
            "Expected escalation_consultation_id to be set per PRD §3.8"
        )
        # Verify the escalation Consultation exists.
        consult = get_success_data(api_client.get_consultation(
            escalation_id, ADMIN,
        ))
        assert consult["id"] == escalation_id
