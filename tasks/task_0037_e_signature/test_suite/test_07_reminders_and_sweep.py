"""Reminder rules, sweep, and idempotency.

Covers PRD §3.8 (ReminderRule creation and constraints, sweep behavior,
escalation, idempotency, OCC on PATCH).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours,
    advance_clock,
    api_client,
    assert_reminder_event,
    assert_reminder_rule,
    create_reminder_rule_payload,
    current_clock_iso,
    fire_reminder_payload,
    get_contract,
    list_reminder_events,
    make_contract_initiator_headers,
    patch_reminder_rule_payload,
    run_sweep,
    setup_pending_sign_single_party,
    setup_reminder_rule_in_pending_sign,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


class TestCreateReminderRule:

    def test_create_with_valid_inputs_succeeds(self, api):
        """PRD §3.8: 'A ReminderRule is created on a Contract with an
        interval_hours (between 1 and 168 inclusive...)'.

        Claim: a valid ReminderRule on a PENDING_SIGN contract is created
        in 201 with interval_hours, channels, escalation_after_misses
        echoed back.
        """
        ctx = setup_pending_sign_single_party()
        res = api.create_reminder_rule(
            ctx["contract"]["id"],
            create_reminder_rule_payload(
                interval_hours=24, channels=["SMS"],
                escalation_after_misses=2,
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_reminder_rule(data)
        assert data["interval_hours"] == 24
        assert data["channels"] == ["SMS"]
        assert data["escalation_after_misses"] == 2
        assert data["enabled"] is True
        assert data["misses_count"] == 0

    @pytest.mark.parametrize("bad_interval", [0, 169, -1])
    def test_invalid_interval_hours_rejected(self, api, bad_interval):
        """PRD §3.8: 'an interval_hours (between 1 and 168 inclusive --
        i.e., an hourly cadence up to a weekly cadence)'.

        Claim: interval_hours outside [1, 168] -> ERR_VALIDATION_FAILED.
        """
        ctx = setup_pending_sign_single_party()
        res = api.create_reminder_rule(
            ctx["contract"]["id"],
            create_reminder_rule_payload(
                interval_hours=bad_interval,
                channels=["SMS"],
                escalation_after_misses=2,
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)


class TestPatchReminderRuleOcc:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.4 + §3.8: 'The rule may be edited under OCC; the OCC
        version check applies on every PATCH.'

        Claim: PATCH with a stale version -> ERR_VERSION_CONFLICT.
        """
        ctx = setup_reminder_rule_in_pending_sign()
        rule = ctx["rule"]
        # First successful PATCH bumps version.
        api.patch_reminder_rule(
            rule["id"],
            patch_reminder_rule_payload(
                version=rule["version"], enabled=False,
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        # Second PATCH with the OLD version -> conflict.
        res = api.patch_reminder_rule(
            rule["id"],
            patch_reminder_rule_payload(
                version=rule["version"], enabled=True,
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestFireReminder:

    def test_fire_creates_reminder_event(self, api):
        """PRD §3.8: 'When a reminder fires, a ReminderEvent row is
        created with the reminder_rule_id, the denormalized contract_id,
        the fired_at set to the current server time, the channels_used
        array (the rule's channels...), the boolean escalated, and an
        idempotency_key of the form {reminder_rule_id}:{slot}'.

        Claim: fire returns 201 with a ReminderEvent.
        """
        ctx = setup_reminder_rule_in_pending_sign(interval_hours=24)
        # PRD §3.8 says fire is only valid when due, but test-driving
        # endpoints accept idempotency_key. We pin slot=0 for the first
        # firing which is the one due immediately on activation.
        idem = unique_idempotency_key(ctx["rule"]["id"], 0)
        res = api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_reminder_event(data)
        assert data["reminder_rule_id"] == ctx["rule"]["id"]
        assert data["idempotency_key"] == idem
        # PRD §3.8: 'channels_used array (the rule's channels)'.
        assert "SMS" in data["channels_used"]

    def test_duplicate_idempotency_key_rejected(self, api):
        """PRD §3.8: 'The pair (reminder_rule_id, idempotency_key) is
        unique -- duplicate firings of the same slot are rejected with
        ERR_DUPLICATE_REMINDER.'

        Claim: a second fire with the same idempotency_key under the
        same rule -> 409 ERR_DUPLICATE_REMINDER.
        """
        ctx = setup_reminder_rule_in_pending_sign(interval_hours=24)
        idem = unique_idempotency_key(ctx["rule"]["id"], 0)
        # First fire.
        api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        # Second with the same key.
        res = api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REMINDER.value)


class TestSweepRunMechanics:

    def test_sweep_returns_count_object(self, api, platform_admin_headers):
        """PRD §3.8: 'A sweep-run capability runs the periodic sweep on
        demand, returning a small object indicating how many contracts
        auto-voided and how many reminders fired in this run.'

        Claim: POST /_sweep/run returns an object with auto_voided and
        reminders_fired keys.
        """
        res = api.run_sweep(platform_admin_headers)
        data = validate_success(res)
        assert "auto_voided" in data
        assert "reminders_fired" in data
        assert isinstance(data["auto_voided"], int)
        assert isinstance(data["reminders_fired"], int)
