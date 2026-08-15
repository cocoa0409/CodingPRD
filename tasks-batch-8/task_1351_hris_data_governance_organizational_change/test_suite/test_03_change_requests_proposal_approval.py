"""Change-request proposal, approval authority, dual approval, supersession."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_approved_worker_change,
    create_data_field_record,
    create_position_record,
    create_worker_change_request_record,
    create_worker_record,
    get_success_data,
    list_assignment_rows,
    list_audit_entries,
    make_analyst_headers,
    make_approver_headers,
    provision_grant,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]


class TestProposalFks:
    def test_change_request_body_field_fk_not_found(self, api):
        """PRD §2.8: "3. **Existence** — path identifiers are resolved left to
        right, and body foreign keys such as `target_field_id`, `target_row_id`,
        `initial_position_id`, and `parent_position_id` must exist (the
        resource-specific not-found errors, 404; see §2.9)."

        Design: Corner/entities/change_request_body_field_fk_not_found
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W710")

        resp = api.create_worker_change_request(
            worker["id"],
            {
                "target_type": "WORKER_FIELD",
                "target_field_id": NON_EXISTENT_UUID,
                "new_value": "12000",
                "effective_date": "2026-09-01",
                "expected_worker_version": worker["version"],
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_DATA_FIELD_NOT_FOUND)

    def test_change_request_target_row_fk_not_found(self, api):
        """PRD §2.9: "The not-found vocabulary is resource-specific:
        `ERR_DATA_FIELD_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`,
        `ERR_WORKER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND` (including
        `target_row_id` references), `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_BATCH_NOT_FOUND`, `ERR_BATCH_LINE_NOT_FOUND`,
        `ERR_INTEGRATION_EVENT_NOT_FOUND`, `ERR_DQ_RULE_NOT_FOUND`,
        `ERR_EXCEPTION_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, and
        `ERR_AUDIT_ENTRY_NOT_FOUND`."

        Design: Corner/entities/change_request_target_row_fk_not_found
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W711")
        field = create_data_field_record()

        resp = api.create_worker_change_request(
            worker["id"],
            {
                "target_type": "WORKER_FIELD",
                "target_field_id": field["id"],
                "new_value": "9500",
                "correction_mode": "CORRECT_HISTORY",
                "target_row_id": NON_EXISTENT_UUID,
                "expected_worker_version": worker["version"],
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)


class TestSupersession:
    def test_change_request_supersedes_pending_same_field(self, api):
        """PRD §3.4: "Creation also supersedes rivals: any request for the same
        target and field still sitting in `PENDING_APPROVAL` or
        `PARTIALLY_APPROVED` moves to `SUPERSEDED`, deliberately without an audit
        entry, and the target worker's or position's `version` increments by
        one."

        Design: Corner/state_machines/change_request_supersedes_pending_same_field
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W727")
        field = create_data_field_record()

        cr1 = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )
        assert cr1["status"] == "PENDING_APPROVAL"

        worker_now = validate_success(api.get_worker(worker["id"], ANALYST))
        cr2 = create_worker_change_request_record(
            worker["id"], worker_now["version"], field["id"], new_value="13000",
            effective_date="2026-10-01",
        )
        assert cr2["status"] == "PENDING_APPROVAL"

        cr1_now = validate_success(api.get_change_request(cr1["id"], ANALYST))
        assert cr1_now["status"] == "SUPERSEDED"

        audits = list_audit_entries(change_request_id=cr1["id"])
        assert audits == [], "supersession must write no audit entry"


class TestApprovalAuthority:
    def test_approve_change_without_grant_rejected(self, api):
        """PRD §3.4: "Approval belongs to a `ChangeApprover` who must additionally
        hold a `PROVISIONED` grant with `role_code` `CHANGE_APPROVER`; without one
        the attempt fails with `ERR_GRANT_NOT_PROVISIONED`."

        Design: Corner/state_machines/approve_change_without_grant_rejected
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W741")
        field = create_data_field_record()
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )

        resp = api.approve_change_request(cr["id"], make_approver_headers("appr-x"))
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_PROVISIONED)

    def test_approve_own_change_request_rejected(self, api):
        """PRD §3.4: "Self-approval is forbidden — the approver may not be the
        request's `created_by`, on pain of `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/state_machines/approve_own_change_request_rejected
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W742")
        field = create_data_field_record()
        # The creator (analyst-1) also holds a PROVISIONED CHANGE_APPROVER grant.
        provision_grant("analyst-1", "CHANGE_APPROVER")
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
            creator_user_id="analyst-1",
        )
        assert cr["created_by"] == "analyst-1"

        resp = api.approve_change_request(cr["id"], make_approver_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_restricted_field_requires_dual_approval(self, api):
        """PRD §3.4: "For `RESTRICTED` fields approval is dual: the first approval
        moves the request to `PARTIALLY_APPROVED` with `approver_1_id` set, and a
        second, distinct approver — neither `created_by` nor `approver_1_id`,
        again enforced through `ERR_SELF_APPROVAL_FORBIDDEN` — completes it to
        `APPROVED` with `approver_2_id` recorded."

        Design: Corner/state_machines/restricted_field_requires_dual_approval
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W743")
        field = create_data_field_record(sensitivity="RESTRICTED")
        provision_grant("appr-1", "CHANGE_APPROVER", approver_user_id="secadmin-2")
        provision_grant("appr-2", "CHANGE_APPROVER", approver_user_id="secadmin-2")
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )

        first = validate_success(
            api.approve_change_request(cr["id"], make_approver_headers("appr-1"))
        )
        assert first["status"] == "PARTIALLY_APPROVED"
        assert first["approver_1_id"] == "appr-1"

        second = validate_success(
            api.approve_change_request(cr["id"], make_approver_headers("appr-2"))
        )
        assert second["status"] == "APPROVED"
        assert second["approver_2_id"] == "appr-2"

    def test_restricted_second_approval_same_approver_rejected(self, api):
        """PRD §3.4: "For `RESTRICTED` fields approval is dual: the first approval
        moves the request to `PARTIALLY_APPROVED` with `approver_1_id` set, and a
        second, distinct approver — neither `created_by` nor `approver_1_id`,
        again enforced through `ERR_SELF_APPROVAL_FORBIDDEN` — completes it to
        `APPROVED` with `approver_2_id` recorded."

        Design: Corner/state_machines/restricted_second_approval_same_approver_rejected
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W744")
        field = create_data_field_record(sensitivity="RESTRICTED")
        provision_grant("appr-1", "CHANGE_APPROVER")
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )
        first = validate_success(
            api.approve_change_request(cr["id"], make_approver_headers("appr-1"))
        )
        assert first["status"] == "PARTIALLY_APPROVED"

        resp = api.approve_change_request(cr["id"], make_approver_headers("appr-1"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

        now = validate_success(api.get_change_request(cr["id"], ANALYST))
        assert now["status"] == "PARTIALLY_APPROVED"

    def test_reject_partially_approved_request(self, api):
        """PRD §3.4: "Rejection is available from either pending state, accepts an
        optional `reason`, and lands in `REJECTED`."

        Design: Corner/state_machines/reject_partially_approved_request
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W745")
        field = create_data_field_record(sensitivity="RESTRICTED")
        provision_grant("appr-1", "CHANGE_APPROVER")
        cr = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )
        first = validate_success(
            api.approve_change_request(cr["id"], make_approver_headers("appr-1"))
        )
        assert first["status"] == "PARTIALLY_APPROVED"

        rejected = validate_success(
            api.reject_change_request(
                cr["id"], {"reason": "not justified"}, make_approver_headers("appr-1")
            )
        )
        assert rejected["status"] == "REJECTED"
