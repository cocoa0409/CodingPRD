"""Integration error queue, dead-lettering, exception triage, priority scoring, DQ gates."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    create_applied_worker_change,
    create_dq_rule_record,
    dispatch_event,
    drive_event_to_dead_letter,
    list_events,
    list_exceptions,
    provision_grant,
    retry_event,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _applied_change_with_event(worker_number, channels=("PAYROLL",)):
    """Applied NEW_RECORD salary change emitting one QUEUED event per channel."""
    env = setup_worker_with_field(worker_number=worker_number, channels=list(channels))
    worker = env["worker"]
    cr = create_applied_worker_change(worker["id"], worker["version"], env["field"]["id"])
    events = list_events(change_request_id=cr["id"])
    assert len(events) == len(list(channels))
    return env, cr, events[0]


class TestRetryLoop:
    def test_integration_event_retry_loop_until_dead_letter(self, api):
        """PRD §3.6: "When a failure would push `retry_count` to three, the event
        instead becomes `DEAD_LETTERED` and an `OPEN` exception record is opened
        against it with `integration_event_id` set. A `FAILED` event can be
        requeued while its `retry_count` remains below three — retry from any
        other state or at the budget's end is `ERR_EVENT_INVALID_STATE` —
        returning it to `QUEUED` for another dispatch."

        Design: Difficulty/non_linear_state_machine/integration_event_retry_loop_until_dead_letter
        """
        env, cr, event = _applied_change_with_event("W820")

        first = dispatch_event(event["id"], "FAILED")
        assert first["status"] == "FAILED"
        assert first["retry_count"] == 1

        retry_event(event["id"])

        second = dispatch_event(event["id"], "FAILED")
        assert second["status"] == "FAILED"
        assert second["retry_count"] == 2

        retry_event(event["id"])

        third = dispatch_event(event["id"], "FAILED")
        assert third["status"] == "DEAD_LETTERED"
        assert third["retry_count"] == 3

        err = api.retry_integration_event(event["id"], OPERATOR)
        validate_error(err, ApiErrorId.ERR_EVENT_INVALID_STATE)

    def test_integration_event_retry_loop_returns_failed_event_to_queued(self, api):
        """PRD §3.6: "A `FAILED` event can be requeued while its `retry_count`
        remains below three — retry from any other state or at the budget's end
        is `ERR_EVENT_INVALID_STATE` — returning it to `QUEUED` for another
        dispatch."

        Design: Difficulty/non_linear_state_machine/integration_event_retry_loop_until_dead_letter
        """
        env, cr, event = _applied_change_with_event("W821")

        first = dispatch_event(event["id"], "FAILED")
        assert first["status"] == "FAILED"
        assert first["retry_count"] == 1

        requeued = retry_event(event["id"])
        assert requeued["status"] == "QUEUED"
        assert requeued["retry_count"] == 1

        # The QUEUED event can be dispatched again (the loop is live).
        second = dispatch_event(event["id"], "FAILED")
        assert second["status"] == "FAILED"
        assert second["retry_count"] == 2

        retry_event(event["id"])
        third = dispatch_event(event["id"], "FAILED")
        assert third["status"] == "DEAD_LETTERED"
        assert third["retry_count"] == 3

        err = api.retry_integration_event(event["id"], OPERATOR)
        validate_error(err, ApiErrorId.ERR_EVENT_INVALID_STATE)


class TestDeadLetterCascade:
    def test_dispatch_third_failure_deadletters_and_opens_exception(self, api):
        """PRD §3.6: "When a failure would push `retry_count` to three, the event
        instead becomes `DEAD_LETTERED` and an `OPEN` exception record is opened
        against it with `integration_event_id` set."
        PRD §3.7: "The score starts from a severity base: 100 for a `WARNING`
        rule, 300 for a `CRITICAL` rule, and 300 for dead-letter-originated
        exceptions where `rule_id` is null."

        Design: Difficulty/transitive_cascade/dispatch_third_failure_deadletters_and_opens_exception
        """
        env, cr, event = _applied_change_with_event("W822")
        dispatch_event(event["id"], "FAILED")
        retry_event(event["id"])
        dispatch_event(event["id"], "FAILED")
        retry_event(event["id"])

        third = dispatch_event(event["id"], "FAILED")
        assert third["status"] == "DEAD_LETTERED"
        assert third["retry_count"] == 3

        exceptions = list_exceptions(worker_id=env["worker"]["id"])
        assert len(exceptions) == 1
        exc = exceptions[0]
        assert exc["status"] == "OPEN"
        assert exc["integration_event_id"] == event["id"]
        assert exc["priority_score"] == 300

    def test_dispatch_third_failure_deadletters_and_opens_exception_record_shape(self, api):
        """PRD §3.7: "Each record carries the offending context — `rule_id` (null
        when the exception came from a dead-lettered event rather than a quality
        rule), `change_request_id` or `batch_id` depending on origin,
        `integration_event_id` set only for dead-letter-originated records,
        `worker_id`, `field_id`, and a snapshot of the `observed_value` — plus a
        `status` of `OPEN`, `RESOLVED`, or `WAIVED`, a computed `priority_score`,
        and optional `waiver_expiry_date` and `resolution_note`."
        PRD §3.6: "When a failure would push `retry_count` to three, the event
        instead becomes `DEAD_LETTERED` and an `OPEN` exception record is opened
        against it with `integration_event_id` set."

        Design: Difficulty/transitive_cascade/dispatch_third_failure_deadletters_and_opens_exception
        """
        env, cr, event = _applied_change_with_event("W823")
        drive_event_to_dead_letter(event["id"])

        exceptions = list_exceptions(worker_id=env["worker"]["id"])
        assert len(exceptions) == 1
        exc = exceptions[0]
        assert exc["status"] == "OPEN"
        assert exc["integration_event_id"] == event["id"]
        assert exc["rule_id"] is None
        assert exc["priority_score"] == 300


class TestEventStateGuards:
    def test_integration_event_acknowledged_is_terminal(self, api):
        """PRD §3.6: "An `IntegrationOperator` dispatches a `QUEUED` event —
        dispatch from any other state fails with `ERR_EVENT_INVALID_STATE` —
        supplying an `outcome` that deterministically settles the attempt: the
        event passes through `DISPATCHED` into `ACKNOWLEDGED` on success, or into
        `FAILED` on failure, with `retry_count` incrementing by one on each
        failure."

        Design: Corner/state_machines/integration_event_acknowledged_is_terminal
        """
        env, cr, event = _applied_change_with_event("W756")

        first = dispatch_event(event["id"], "ACKNOWLEDGED")
        assert first["status"] == "ACKNOWLEDGED"

        err = api.dispatch_integration_event(event["id"], {"outcome": "ACKNOWLEDGED"}, OPERATOR)
        validate_error(err, ApiErrorId.ERR_EVENT_INVALID_STATE)

    def test_resolve_dead_lettered_event_success(self, api):
        """PRD §3.6: "A dead-lettered event is closed out manually by an
        `IntegrationOperator` supplying a `resolution_note`, moving
        `DEAD_LETTERED` to `RESOLVED`; resolve from any other state fails with
        `ERR_EVENT_INVALID_STATE`."

        Design: Corner/state_machines/resolve_dead_lettered_event_success
        """
        env, cr, event = _applied_change_with_event("W757")
        dead = drive_event_to_dead_letter(event["id"])
        assert dead["status"] == "DEAD_LETTERED"
        assert dead["retry_count"] == 3

        resolved = validate_success(
            api.resolve_integration_event(
                event["id"], {"resolution_note": "downstream fixed manually"}, OPERATOR
            )
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "downstream fixed manually"


class TestExceptionTriage:
    def test_exception_resolve_then_resolve_rejected(self, api):
        """PRD §3.7: "A `DataSteward` resolves an `OPEN` exception by recording a
        `resolution_note`, moving it to `RESOLVED`; resolving or waiving from any
        other state fails with `ERR_EXCEPTION_NOT_OPEN`."

        Design: Corner/state_machines/exception_resolve_then_resolve_rejected
        """
        env = setup_worker_with_field(worker_number="W758", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )
        exc = list_exceptions(worker_id=worker["id"])[0]

        first = validate_success(
            api.resolve_exception_record(
                exc["id"], {"resolution_note": "value confirmed with comp team"}, STEWARD
            )
        )
        assert first["status"] == "RESOLVED"

        err = api.resolve_exception_record(exc["id"], {"resolution_note": "again"}, STEWARD)
        validate_error(err, ApiErrorId.ERR_EXCEPTION_NOT_OPEN)

    def test_waived_exception_reopens_on_clock_sweep_past_expiry(self, api):
        """PRD §3.7: "Waivers are not permanent shelter — when the clock sweeps
        past the `waiver_expiry_date`, the exception reopens to `OPEN` and the
        expiry date is cleared."
        PRD §3.7: "The waiver window is bounded: the expiry may not sit more than
        90 days past the current logical clock date, beyond which the waive is
        rejected with `ERR_WAIVER_WINDOW_EXCEEDED`."

        Design: Corner/state_machines/waived_exception_reopens_on_clock_sweep_past_expiry
        """
        env = setup_worker_with_field(worker_number="W759", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )
        exc = list_exceptions(worker_id=worker["id"])[0]

        waived = validate_success(
            api.waive_exception_record(
                exc["id"],
                {"waiver_expiry_date": "2026-08-15", "resolution_note": "temporary waiver"},
                STEWARD,
            )
        )
        assert waived["status"] == "WAIVED"

        advance_clock("2026-08-16T00:00:00Z")

        now = validate_success(api.get_exception_record(exc["id"], STEWARD))
        assert now["status"] == "OPEN"
        assert now["waiver_expiry_date"] is None

    def test_waive_exception_beyond_window_rejected(self, api):
        """PRD §3.7: "The waiver window is bounded: the expiry may not sit more
        than 90 days past the current logical clock date, beyond which the waive
        is rejected with `ERR_WAIVER_WINDOW_EXCEEDED`."

        Design: Corner/state_machines/waive_exception_beyond_window_rejected
        """
        env = setup_worker_with_field(worker_number="W760", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )
        exc = list_exceptions(worker_id=worker["id"])[0]

        err = api.waive_exception_record(exc["id"], {"waiver_expiry_date": "2026-12-01"}, STEWARD)
        validate_error(err, ApiErrorId.ERR_WAIVER_WINDOW_EXCEEDED)

        now = validate_success(api.get_exception_record(exc["id"], STEWARD))
        assert now["status"] == "OPEN"


class TestPriorityScoring:
    def test_exception_priority_score_tiered_inputs(self, api):
        """PRD §3.7: "The score starts from a severity base: 100 for a `WARNING`
        rule, 300 for a `CRITICAL` rule, and 300 for dead-letter-originated
        exceptions where `rule_id` is null. That base is multiplied by a
        sensitivity factor drawn from the linked field: 1 for `PUBLIC`, 1 for
        `INTERNAL`, 2 for `CONFIDENTIAL`, and 3 for `RESTRICTED`, with a factor of
        1 when `field_id` is null. An age bonus is then added: nothing while the
        exception is younger than 7 days, 50 once it has aged at least 7 days but
        fewer than 30, and 150 once it has aged at least 30 days, where age is
        the count of calendar days between the record's creation date and the
        current clock date — zero when they coincide."

        Design: Difficulty/combinatorial_formula/exception_priority_score_tiered_inputs
        """
        env = setup_worker_with_field(worker_number="W824", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )

        advance_clock("2026-08-08T00:00:00Z")

        exceptions = list_exceptions(worker_id=worker["id"])
        assert len(exceptions) == 1
        exc = exceptions[0]
        assert exc["status"] == "OPEN"
        # age_days == 7 (2026-08-01 -> 2026-08-08): 100 * 2 + 50 = 250.
        assert exc["priority_score"] == 250

    def test_exception_priority_score_age_grows_with_clock(self, api):
        """PRD §3.7: "The `priority_score` is the sum of the multiplied base and
        the age bonus, capped at 1000, and because age grows with time, the score
        is recomputed on creation and on every logical-clock advance."
        PRD §3.7: "An age bonus is then added: nothing while the exception is
        younger than 7 days, 50 once it has aged at least 7 days but fewer than
        30, and 150 once it has aged at least 30 days, where age is the count of
        calendar days between the record's creation date and the current clock
        date — zero when they coincide."

        Design: Difficulty/combinatorial_formula/exception_priority_score_tiered_inputs
        """
        env = setup_worker_with_field(worker_number="W825", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )

        at_zero = list_exceptions(worker_id=worker["id"])[0]
        assert at_zero["priority_score"] == 200  # age_days == 0: no bonus

        advance_clock("2026-08-08T00:00:00Z")
        at_seven = list_exceptions(worker_id=worker["id"])[0]
        assert at_seven["priority_score"] == 250  # age_days == 7: +50

    def test_exception_priority_score_age_tier2_bonus(self, api):
        """PRD §3.7: "An age bonus is then added: nothing while the exception is
        younger than 7 days, 50 once it has aged at least 7 days but fewer than
        30, and 150 once it has aged at least 30 days, where age is the count of
        calendar days between the record's creation date and the current clock
        date — zero when they coincide."
        PRD §3.7: "The `priority_score` is the sum of the multiplied base and the
        age bonus, capped at 1000, and because age grows with time, the score is
        recomputed on creation and on every logical-clock advance."

        Design: Corner/calculations/exception_priority_score_age_tier2_bonus
        """
        env = setup_worker_with_field(worker_number="W800", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="WARNING")
        create_applied_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )

        advance_clock("2026-08-31T00:00:00Z")

        exc = list_exceptions(worker_id=worker["id"])[0]
        # age_days == 30 (2026-08-01 -> 2026-08-31): 100 * 2 + 150 = 350.
        assert exc["priority_score"] == 350


class TestDataQualityGates:
    def test_dq_critical_range_violation_rejects_apply(self, api):
        """PRD §3.1: "When a proposed value fails a `CRITICAL` rule, the apply is
        rejected outright with `ERR_DQ_CRITICAL_VIOLATION`; a `WARNING` failure
        lets the apply succeed and opens an exception record afterward, as
        described in §3.7."
        PRD §3.1: "A rule's `rule_type` is `RANGE` (the proposed value, parsed as
        an integer, must lie between `param_min` and `param_max`, both bounds
        inclusive), `REQUIRED` (the value must be non-empty), or `REGEX` (the
        value must match `param_pattern`)."

        Design: Corner/state_machines/dq_critical_range_violation_rejects_apply
        """
        env = setup_worker_with_field(worker_number="W734", channels=[])
        worker = env["worker"]
        create_dq_rule_record(env["field"]["id"], severity="CRITICAL")
        from test_helpers import create_approved_worker_change
        cr = create_approved_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )

        err = api.apply_change_request(cr["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_DQ_CRITICAL_VIOLATION)

        assert list_exceptions(worker_id=worker["id"]) == []

    def test_dq_critical_regex_violation_rejects_apply(self, api):
        """PRD §3.1: "A rule's `rule_type` is `RANGE` (the proposed value, parsed
        as an integer, must lie between `param_min` and `param_max`, both bounds
        inclusive), `REQUIRED` (the value must be non-empty), or `REGEX` (the
        value must match `param_pattern`)."
        PRD §3.1: "When a proposed value fails a `CRITICAL` rule, the apply is
        rejected outright with `ERR_DQ_CRITICAL_VIOLATION`; a `WARNING` failure
        lets the apply succeed and opens an exception record afterward, as
        described in §3.7."

        Design: Corner/state_machines/dq_critical_regex_violation_rejects_apply
        """
        env = setup_worker_with_field(
            worker_number="W735", field_key="assignment.location_code",
            channels=[], initial_location_code="NY",
        )
        worker = env["worker"]
        create_dq_rule_record(
            env["field"]["id"], rule_type="REGEX", severity="CRITICAL",
            param_pattern="^[A-Z]{2}$",
        )
        from test_helpers import create_approved_worker_change
        cr = create_approved_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="sf",
        )

        err = api.apply_change_request(cr["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_DQ_CRITICAL_VIOLATION)

    def test_disabled_dq_rule_skipped_on_apply(self, api):
        """PRD §3.1: "Rules are born `ACTIVE`; a `DataSteward` may patch a rule to
        toggle it between `ACTIVE` and `DISABLED` or to adjust `param_min`,
        `param_max`, or `param_pattern`, and `DISABLED` rules are skipped during
        evaluation."

        Design: Corner/state_machines/disabled_dq_rule_skipped_on_apply
        """
        env = setup_worker_with_field(worker_number="W736", channels=[])
        worker = env["worker"]
        rule = create_dq_rule_record(env["field"]["id"], severity="CRITICAL")
        patched = validate_success(
            api.patch_data_quality_rule(rule["id"], {"status": "DISABLED"}, STEWARD)
        )
        assert patched["status"] == "DISABLED"

        from test_helpers import create_approved_worker_change
        cr = create_approved_worker_change(
            worker["id"], worker["version"], env["field"]["id"], new_value="99999",
        )
        applied = validate_success(api.apply_change_request(cr["id"], ANALYST))
        assert applied["status"] == "APPLIED"

        assert list_exceptions(worker_id=worker["id"]) == []
