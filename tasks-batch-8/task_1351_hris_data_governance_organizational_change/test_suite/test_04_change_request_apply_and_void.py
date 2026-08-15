"""Change-request application (both correction modes), field-history replay, and voids."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_change_request_record,
    create_approved_worker_change,
    create_applied_worker_change,
    create_data_field_record,
    create_position_record,
    create_worker_change_request_record,
    create_worker_record,
    list_assignment_rows,
    list_audit_entries,
    list_events,
    provision_grant,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _correct_history_setup(worker_number, sensitivity="CONFIDENTIAL", channels=None):
    """Worker with one ACTIVE row at salary 10000 + a CORRECT_HISTORY change
    applied, overwriting the row's salary to 9500. Returns (env, row, cr)."""
    env = setup_worker_with_field(
        worker_number=worker_number, sensitivity=sensitivity, channels=channels,
    )
    worker = env["worker"]
    field = env["field"]
    row = list_assignment_rows(worker["id"])[0]
    cr = create_worker_change_request_record(
        worker["id"], worker["version"], field["id"], new_value="9500",
        correction_mode="CORRECT_HISTORY", target_row_id=row["id"],
    )
    approve_change_request_record(cr["id"], "appr-1")
    from test_helpers import apply_change_request_record
    applied = apply_change_request_record(cr["id"])
    return env, row, applied


class TestApplySideEffects:
    def test_apply_new_record_truncates_covering_row_and_inherits_attributes(self, api):
        """PRD §2.6: "Second, if a row covers D strictly inside its interval, that
        covering row is truncated so its end becomes D, the truncated row's
        original end is snapshot onto the requesting change as `prior_row_end`,
        and the new row runs from D to that original end."
        PRD §2.6: "The new row inherits the covering row's current attribute
        values and then overwrites the single governed attribute with the
        requested value."
        PRD §3.4: "Under `NEW_RECORD` for a worker field, the covering row is
        truncated and the new row inserted exactly as §2.6 prescribes, an audit
        entry with action `APPLY` is written when the field's sensitivity is
        `CONFIDENTIAL` or `RESTRICTED`, one `QUEUED` integration event of type
        `CHANGE_APPLIED` is emitted per channel in the field's
        `downstream_channels`, and the worker's `version` increments by one."

        Design: Corner/state_machines/apply_new_record_truncates_covering_row_and_inherits_attributes
        """
        env = setup_worker_with_field(
            worker_number="W728", channels=["PAYROLL"],
            initial_pay_grade="G5", initial_location_code="NY",
        )
        worker = env["worker"]
        field = env["field"]
        cr = create_approved_worker_change(worker["id"], worker["version"], field["id"])

        applied = validate_success(api.apply_change_request(cr["id"], ANALYST))
        assert applied["status"] == "APPLIED"

        rows = list_assignment_rows(worker["id"])
        assert len(rows) == 2
        r1, r2 = rows[0], rows[1]
        assert r1["effective_end_date"] == "2026-09-01"
        assert r1["row_status"] == "ACTIVE"
        assert r2["effective_start_date"] == "2026-09-01"
        assert r2["effective_end_date"] is None
        assert r2["salary_cents"] == 12000
        assert r2["pay_grade"] == "G5"
        assert r2["location_code"] == "NY"
        assert r2["row_status"] == "FUTURE"

        events = list_events(change_request_id=cr["id"])
        assert len(events) == 1
        assert events[0]["event_type"] == "CHANGE_APPLIED"
        assert events[0]["channel"] == "PAYROLL"
        assert events[0]["status"] == "QUEUED"


class TestApplyRejections:
    def test_apply_change_to_terminated_worker_rejected(self, api):
        """PRD §3.4: "the request must be `APPROVED` (`ERR_REQUEST_INVALID_STATE`);
        a `WORKER_FIELD` target worker must be `ACTIVE` (`ERR_WORKER_NOT_ACTIVE`);
        the target field must be `ACTIVE` (`ERR_FIELD_NOT_ACTIVE`)"

        Design: Corner/state_machines/apply_change_to_terminated_worker_rejected
        """
        env = setup_worker_with_field(worker_number="W729", channels=[])
        worker = env["worker"]
        cr = create_approved_worker_change(worker["id"], worker["version"], env["field"]["id"])
        validate_success(
            api.terminate_worker(worker["id"], {"termination_date": "2026-08-10"}, ANALYST)
        )

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ACTIVE)

        now = validate_success(api.get_change_request(cr["id"], ANALYST))
        assert now["status"] == "APPROVED"

    def test_apply_change_with_deprecated_field_rejected(self, api):
        """PRD §3.4: "the request must be `APPROVED` (`ERR_REQUEST_INVALID_STATE`);
        a `WORKER_FIELD` target worker must be `ACTIVE` (`ERR_WORKER_NOT_ACTIVE`);
        the target field must be `ACTIVE` (`ERR_FIELD_NOT_ACTIVE`)"
        PRD §3.1: "Deprecation moves `ACTIVE` to `DEPRECATED`, after which any new
        change request or batch line referencing the field is rejected with
        `ERR_FIELD_NOT_ACTIVE`, while requests already in flight —
        `PENDING_APPROVAL`, `PARTIALLY_APPROVED`, or `APPROVED` — are unaffected."

        Design: Corner/state_machines/apply_change_with_deprecated_field_rejected
        """
        env = setup_worker_with_field(worker_number="W730", channels=[])
        worker = env["worker"]
        field = env["field"]
        cr = create_approved_worker_change(worker["id"], worker["version"], field["id"])
        validate_success(api.deprecate_data_field(field["id"], STEWARD))

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FIELD_NOT_ACTIVE)

        now = validate_success(api.get_change_request(cr["id"], ANALYST))
        assert now["status"] == "APPROVED"

    def test_apply_correct_history_on_append_only_field_rejected(self, api):
        """PRD §3.4: "an `APPEND_ONLY` field refuses `CORRECT_HISTORY`, as does a
        correction missing its `target_row_id`
        (`ERR_CORRECTION_MODE_NOT_ALLOWED`)"

        Design: Corner/state_machines/apply_correct_history_on_append_only_field_rejected
        """
        env = setup_worker_with_field(
            worker_number="W731", history_policy="APPEND_ONLY", channels=[],
        )
        worker = env["worker"]
        field = env["field"]
        row = list_assignment_rows(worker["id"])[0]
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="9500",
            correction_mode="CORRECT_HISTORY", target_row_id=row["id"],
        )
        approve_change_request_record(cr["id"], "appr-1")

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CORRECTION_MODE_NOT_ALLOWED)

    def test_apply_new_record_exact_start_collision_rejected(self, api):
        """PRD §2.6: "First, if any existing row starts exactly on D, the
        placement is rejected with `ERR_EFFECTIVE_PERIOD_OVERLAP` — an exact-start
        collision is never legal, and the caller must either correct the existing
        row in place or choose another date."

        Design: Corner/state_machines/apply_new_record_exact_start_collision_rejected
        """
        env = setup_worker_with_field(worker_number="W732", channels=[])
        worker = env["worker"]
        cr = create_approved_worker_change(
            worker["id"], worker["version"], env["field"]["id"], effective_date="2026-01-05",
        )

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_PERIOD_OVERLAP)

    def test_apply_effective_date_out_of_window_rejected(self, api):
        """PRD §3.4: "a `NEW_RECORD` `effective_date` must lie no earlier than 730
        days before and no later than 365 days after the current clock date
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`)"

        Design: Corner/state_machines/apply_effective_date_out_of_window_rejected
        """
        env = setup_worker_with_field(worker_number="W733", channels=[])
        worker = env["worker"]
        cr = create_approved_worker_change(
            worker["id"], worker["version"], env["field"]["id"], effective_date="2028-06-01",
        )

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_OUT_OF_WINDOW)

    def test_apply_rejected_request_state_beats_temporal(self, api):
        """PRD §2.8: "Every request is evaluated against an ordered cascade, and
        the first failing tier determines the error response."
        PRD §2.8: "6. **Resource state preconditions** — the target resource must
        be in a status permitting the operation: change-request status for
        approve, reject, apply and void; batch status for line adds, submit,
        reopen, schedule, execute and rollback; event status for dispatch, retry
        and resolve; `OPEN` for exception resolve and waive; `REQUESTED`,
        `APPROVED` or `PROVISIONED` for grant actions; `ACTIVE` for fields,
        workers and positions (`ERR_REQUEST_INVALID_STATE`, `ERR_BATCH_NOT_DRAFT`,
        `ERR_BATCH_NOT_REOPENABLE`, `ERR_BATCH_NOT_EXECUTABLE`,
        `ERR_BATCH_NOT_ROLLBACKABLE`, `ERR_EVENT_INVALID_STATE`,
        `ERR_EXCEPTION_NOT_OPEN`, `ERR_GRANT_INVALID_STATE`,
        `ERR_FIELD_NOT_ACTIVE`, `ERR_WORKER_NOT_ACTIVE`, `ERR_POSITION_NOT_ACTIVE`,
        all 409)."
        PRD §2.8: "10. **Temporal windows** — effective dates must sit inside the
        allowed windows and waiver expiries inside theirs
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`, `ERR_WAIVER_WINDOW_EXCEEDED`,
        both 422)."

        Design: Difficulty/priority_pair_validation_conflict/apply_rejected_request_state_beats_temporal
        """
        env = setup_worker_with_field(worker_number="W801", channels=[])
        worker = env["worker"]
        field = env["field"]
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], effective_date="2028-06-01",
        )
        from test_helpers import make_approver_headers
        rejected = validate_success(
            api.reject_change_request(cr["id"], {}, make_approver_headers("appr-1"))
        )
        assert rejected["status"] == "REJECTED"

        resp = api.apply_change_request(cr["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)

        now = validate_success(api.get_change_request(cr["id"], ANALYST))
        assert now["status"] == "REJECTED"

    def test_apply_rejected_request_state_beats_temporal_window_alone_would_fire(self, api):
        """PRD §3.4: "the request must be `APPROVED`
        (`ERR_REQUEST_INVALID_STATE`)"
        PRD §3.4: "a `NEW_RECORD` `effective_date` must lie no earlier than 730
        days before and no later than 365 days after the current clock date
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`)"

        Second coverage of the same cascade pair from the REJECTED branch: the
        rejected request's 2028-06-01 date is independently outside
        [clock-730d, clock+365d], yet the reported error is the state error.

        Design: Difficulty/priority_pair_validation_conflict/apply_rejected_request_state_beats_temporal
        """
        env = setup_worker_with_field(worker_number="W802", channels=[])
        worker = env["worker"]
        field = env["field"]
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], effective_date="2028-06-01",
        )
        from test_helpers import make_approver_headers
        validate_success(api.reject_change_request(cr["id"], {}, make_approver_headers("appr-1")))

        resp = api.apply_change_request(cr["id"], ANALYST)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_REQUEST_INVALID_STATE", (
            f"state error (tier 6) must outrank the temporal error (tier 10), got {body}"
        )
        assert resp.status_code == 409


class TestFieldHistoryVariants:
    def test_corrected_salary_as_is_vs_as_was(self, api):
        """PRD §3.9: "In `AS_IS` mode the answer is that row's currently stored
        attribute — the corrected view of history, since corrections overwrite.
        In `AS_WAS` mode the system replays the audit trail: among entries with
        action `CORRECT` for that worker and field that targeted the covering row
        — matched by following the entry's `change_request_id` to the request's
        `target_row_id` — the answer is the `old_value` of the earliest such
        entry by creation time; when no correction entry exists, `AS_WAS` yields
        the same value as `AS_IS`."

        Design: Difficulty/dual_variant_calc/corrected_salary_as_is_vs_as_was
        """
        env, row, applied = _correct_history_setup("W803", channels=["PAYROLL"])
        worker = env["worker"]
        field = env["field"]
        assert applied["status"] == "APPLIED"

        asis = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_IS"},
            )
        )
        aswas = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_WAS"},
            )
        )
        assert asis["value"] == "9500"
        assert aswas["value"] == "10000"
        assert asis["value"] != aswas["value"]

    def test_corrected_salary_modes_diverge_only_after_correction(self, api):
        """PRD §3.9: "The two modes diverge exactly when at least one correction
        entry exists for that row and field."
        PRD §3.4: "Under `CORRECT_HISTORY`, the target row's governed attribute is
        rewritten to `new_value`, the overwritten value is snapshot onto the
        request as `prior_value`, an audit entry with action `CORRECT` is always
        written, and integration events with event type `CORRECTION_PROPAGATED`
        are emitted only when the request's `propagate_correction` flag is true."

        Design: Difficulty/dual_variant_calc/corrected_salary_as_is_vs_as_was
        """
        env = setup_worker_with_field(worker_number="W804", sensitivity="CONFIDENTIAL", channels=[])
        worker = env["worker"]
        field = env["field"]

        # Before any correction the two modes agree.
        pre_asis = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_IS"},
            )
        )
        pre_aswas = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_WAS"},
            )
        )
        assert pre_asis["value"] == pre_aswas["value"] == "10000"

        # After the correction they diverge and the CORRECT audit entry exists.
        row = list_assignment_rows(worker["id"])[0]
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="9500",
            correction_mode="CORRECT_HISTORY", target_row_id=row["id"],
        )
        approve_change_request_record(cr["id"], "appr-1")
        from test_helpers import apply_change_request_record
        applied = apply_change_request_record(cr["id"])
        assert applied["status"] == "APPLIED"
        assert applied["prior_value"] == "10000"

        audits = list_audit_entries(change_request_id=cr["id"])
        assert [a["action"] for a in audits] == ["CORRECT"]

        post_asis = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_IS"},
            )
        )
        post_aswas = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_WAS"},
            )
        )
        assert post_asis["value"] == "9500"
        assert post_aswas["value"] == "10000"


class TestVoidCompensation:
    def test_void_new_record_restores_truncated_interval(self, api):
        """PRD §3.4: "A voided `NEW_RECORD` request sees its inserted row move to
        `VOIDED` and the truncated row's original end restored from
        `prior_row_end`; a voided `CORRECT_HISTORY` request sees the row's
        attribute restored from `prior_value`. Either way an audit entry with
        action `VOID` is written, one `QUEUED` integration event of type
        `REVERSAL` is emitted per channel that received the original event, and
        the target worker's or position's `version` increments by one, landing
        the request in `VOIDED`."

        Design: Corner/state_machines/void_new_record_restores_truncated_interval
        """
        env = setup_worker_with_field(
            worker_number="W737", sensitivity="CONFIDENTIAL", channels=["PAYROLL"],
        )
        worker = env["worker"]
        applied = create_applied_worker_change(worker["id"], worker["version"], env["field"]["id"])

        voided = validate_success(
            api.void_change_request(applied["id"], {"reason": "erroneous"}, ANALYST)
        )
        assert voided["status"] == "VOIDED"

        rows = list_assignment_rows(worker["id"])
        assert len(rows) == 2
        assert rows[0]["effective_end_date"] is None
        assert rows[1]["row_status"] == "VOIDED"

        queued = [e for e in list_events(change_request_id=applied["id"]) if e["status"] == "QUEUED"]
        assert len(queued) == 2
        assert {e["event_type"] for e in queued} == {"CHANGE_APPLIED", "REVERSAL"}

        audits = list_audit_entries(change_request_id=applied["id"])
        assert len(audits) == 2
        assert audits[1]["action"] == "VOID"

    def test_void_correct_history_restores_prior_value(self, api):
        """PRD §3.4: "A voided `NEW_RECORD` request sees its inserted row move to
        `VOIDED` and the truncated row's original end restored from
        `prior_row_end`; a voided `CORRECT_HISTORY` request sees the row's
        attribute restored from `prior_value`. Either way an audit entry with
        action `VOID` is written, one `QUEUED` integration event of type
        `REVERSAL` is emitted per channel that received the original event, and
        the target worker's or position's `version` increments by one, landing
        the request in `VOIDED`."

        Design: Corner/state_machines/void_correct_history_restores_prior_value
        """
        env, row, applied = _correct_history_setup("W738", channels=[])
        worker = env["worker"]
        field = env["field"]

        voided = validate_success(
            api.void_change_request(applied["id"], {"reason": "undo correction"}, ANALYST)
        )
        assert voided["status"] == "VOIDED"

        row_now = validate_success(api.get_position_assignment(row["id"], ANALYST))
        assert row_now["salary_cents"] == 10000

        asis = validate_success(
            api.get_field_history(
                worker["id"], STEWARD,
                params={"field_id": field["id"], "as_of_date": "2026-06-01", "mode": "AS_IS"},
            )
        )
        assert asis["value"] == "10000"

        audits = list_audit_entries(change_request_id=applied["id"])
        assert len(audits) == 2
        assert audits[0]["action"] == "CORRECT"
        assert audits[1]["action"] == "VOID"

    def test_void_blocked_when_later_applied_change_exists(self, api):
        """PRD §3.4: "It is lawful only while the request is `APPLIED` and only
        while no later-created `APPLIED` request exists for the same target and
        field; either violation is `ERR_REQUEST_INVALID_STATE`."

        Design: Corner/state_machines/void_blocked_when_later_applied_change_exists
        """
        env = setup_worker_with_field(worker_number="W739", channels=[])
        worker = env["worker"]
        field = env["field"]
        cr1 = create_applied_worker_change(
            worker["id"], worker["version"], field["id"], new_value="11000",
            effective_date="2026-09-01",
        )
        worker_now = validate_success(api.get_worker(worker["id"], ANALYST))
        cr2 = create_applied_worker_change(
            worker["id"], worker_now["version"], field["id"], new_value="12000",
            effective_date="2026-10-01",
        )

        err = api.void_change_request(cr1["id"], {"reason": "try old first"}, ANALYST)
        validate_error(err, ApiErrorId.ERR_REQUEST_INVALID_STATE)

        voided2 = validate_success(
            api.void_change_request(cr2["id"], {"reason": "undo latest"}, ANALYST)
        )
        assert voided2["status"] == "VOIDED"

        cr1_now = validate_success(api.get_change_request(cr1["id"], ANALYST))
        assert cr1_now["status"] == "APPLIED"

    def test_void_pending_request_rejected(self, api):
        """PRD §3.4: "It is lawful only while the request is `APPLIED` and only
        while no later-created `APPLIED` request exists for the same target and
        field; either violation is `ERR_REQUEST_INVALID_STATE`."

        Design: Corner/state_machines/void_pending_request_rejected
        """
        env = setup_worker_with_field(worker_number="W740", channels=[])
        worker = env["worker"]
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], env["field"]["id"], new_value="12000",
        )

        resp = api.void_change_request(cr["id"], {"reason": "too early"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)


class TestSensitivityGatedAudit:
    def test_audit_entry_written_only_for_sensitive_fields(self, api):
        """PRD §3.9: "Entries are written by the rules already stated: always for
        corrections, voids, rollbacks, and grant decisions; for applies and batch
        lines only when the field is `CONFIDENTIAL` or `RESTRICTED`; and never for
        supersession."

        Design: Corner/state_machines/audit_entry_written_only_for_sensitive_fields
        """
        pos = create_position_record()
        worker = create_worker_record(
            pos["id"], worker_number="W762", initial_location_code="NY",
        )
        loc_field = create_data_field_record(
            field_key="assignment.location_code", sensitivity="INTERNAL", channels=[],
        )
        sal_field = create_data_field_record(
            field_key="assignment.salary_cents", sensitivity="CONFIDENTIAL", channels=[],
        )
        provision_grant("appr-1", "CHANGE_APPROVER")

        cr1 = create_applied_worker_change(
            worker["id"], worker["version"], loc_field["id"], new_value="SF",
            effective_date="2026-09-01",
        )
        worker_now = validate_success(api.get_worker(worker["id"], ANALYST))
        cr2 = create_applied_worker_change(
            worker["id"], worker_now["version"], sal_field["id"], new_value="11000",
            effective_date="2026-10-01",
        )

        audits_internal = list_audit_entries(change_request_id=cr1["id"])
        assert audits_internal == [], "INTERNAL-field apply must not write an audit entry"

        audits_confidential = list_audit_entries(change_request_id=cr2["id"])
        assert len(audits_confidential) == 1
        assert audits_confidential[0]["action"] == "APPLY"
        assert audits_confidential[0]["old_value"] == "10000"
        assert audits_confidential[0]["new_value"] == "11000"
