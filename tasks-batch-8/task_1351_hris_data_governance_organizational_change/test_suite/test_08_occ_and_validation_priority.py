"""Optimistic-concurrency guards and the ordered validation cascade."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_batch_line_record,
    approve_change_request_record,
    create_batch_record,
    create_data_field_record,
    create_position_record,
    create_worker_change_request_record,
    create_worker_record,
    get_batch_version,
    list_assignment_rows,
    provision_grant,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]


class TestOptimisticConcurrency:
    def test_stale_worker_version_rejected_on_change_create(self, api):
        """PRD §2.7: "Creating a worker-targeted change request
        (`POST /hris/workers/{workerId}/change-requests`) requires a non-optional
        `expected_worker_version` carrying the worker's current `version`. A
        mismatch is rejected with `ERR_STALE_WORKER_VERSION` (HTTP 412). Because a
        new request legitimately supersedes same-field pending requests and the
        worker's version advances on every applied mutation, a client working from
        a stale snapshot must re-read before proposing."

        Design: Corner/cross_cutting_complexity_layers/stale_worker_version_rejected_on_change_create
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W920")
        field = create_data_field_record()

        cr1 = create_worker_change_request_record(
            worker["id"], worker["version"], field["id"], new_value="12000",
        )
        assert cr1["status"] == "PENDING_APPROVAL"

        worker_now = validate_success(api.get_worker(worker["id"], ANALYST))
        assert worker_now["version"] == worker["version"] + 1

        resp = api.create_worker_change_request(
            worker["id"],
            {
                "target_type": "WORKER_FIELD",
                "target_field_id": field["id"],
                "new_value": "13000",
                "effective_date": "2026-10-01",
                "expected_worker_version": worker["version"],
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_WORKER_VERSION)

    def test_stale_position_version_rejected_on_position_change_create(self, api):
        """PRD §2.7: "Creating a position-targeted change request
        (`POST /hris/positions/{positionId}/change-requests`) requires a
        non-optional `expected_position_version` matching the position's current
        `version`; a mismatch is rejected with `ERR_STALE_POSITION_VERSION`
        (HTTP 412), since hierarchy and attribute proposals must be based on the
        current tree shape."

        Design: Corner/cross_cutting_complexity_layers/stale_position_version_rejected_on_position_change_create
        """
        pos = create_position_record(title="Engineer")
        field = create_data_field_record(
            field_key="position.title", sensitivity="INTERNAL", channels=[],
            owner_team="people", display_name="Position Title",
        )

        resp = api.create_position_change_request(
            pos["id"],
            {
                "target_type": "POSITION_FIELD",
                "target_field_id": field["id"],
                "new_value": "Senior Engineer",
                "effective_date": "2026-09-01",
                "expected_position_version": pos["version"],
            },
            ANALYST,
        )
        validate_success(resp, expected_status=201)

        err = api.create_position_change_request(
            pos["id"],
            {
                "target_type": "POSITION_FIELD",
                "target_field_id": field["id"],
                "new_value": "Staff Engineer",
                "effective_date": "2026-10-01",
                "expected_position_version": pos["version"],
            },
            ANALYST,
        )
        validate_error(err, ApiErrorId.ERR_STALE_POSITION_VERSION)

    def test_stale_batch_version_rejected_on_submit(self, api):
        """PRD §2.7: "Submitting a mass change batch
        (`POST /hris/mass-change-batches/{batchId}/submit`) requires a
        non-optional `expected_batch_version` matching the batch's current
        `version`; a mismatch is rejected with `ERR_STALE_BATCH_VERSION`
        (HTTP 412), because submission must cover exactly the line set the client
        reviewed."

        Design: Corner/cross_cutting_complexity_layers/stale_batch_version_rejected_on_submit
        """
        env = setup_worker_with_field(
            worker_number="W921", field_key="assignment.location_code", channels=[],
        )
        batch = create_batch_record(name="occ")
        stale_version = batch["version"]
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF")

        resp = api.submit_batch(batch["id"], {"expected_batch_version": stale_version}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)


class TestValidationPriority:
    def test_missing_user_id_header_rejected(self, api, analyst_headers):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or carrying an empty
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_id_header_rejected
        """
        create_position_record()  # DB non-empty
        bad_headers = dict(analyst_headers)
        bad_headers["X-User-ID"] = ""
        resp = api.list_workers(bad_headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_auth_denial_beats_not_found(self, api, analyst_headers):
        """PRD §2.8: "Every request is evaluated against an ordered cascade, and
        the first failing tier determines the error response."
        PRD §2.8: "2. **Role authorization** — the caller's role must be permitted
        on the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403)."
        PRD §2.8: "3. **Existence** — path identifiers are resolved left to right,
        and body foreign keys such as `target_field_id`, `target_row_id`,
        `initial_position_id`, and `parent_position_id` must exist (the
        resource-specific not-found errors, 404; see §2.9)."

        Design: Corner/validations/auth_denial_beats_not_found
        """
        create_data_field_record(field_key="assignment.pay_grade", activate=False)
        resp = api.activate_data_field(NON_EXISTENT_UUID, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_stale_batch_version_beats_not_draft_state(self, api):
        """PRD §2.8: "Every request is evaluated against an ordered cascade, and
        the first failing tier determines the error response."
        PRD §2.8: "5. **Optimistic concurrency** — the `expected_worker_version`,
        `expected_position_version`, or `expected_batch_version` on the three
        guarded writes must equal the parent's current `version` (the
        stale-version errors, 412)."
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

        Design: Corner/validations/stale_batch_version_beats_not_draft_state
        """
        env = setup_worker_with_field(
            worker_number="W922", field_key="assignment.location_code", channels=[],
        )
        batch = create_batch_record(name="prio")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF")
        pre_submit_version = get_batch_version(batch["id"])
        submitted = validate_success(
            api.submit_batch(batch["id"], {"expected_batch_version": pre_submit_version}, ANALYST)
        )
        assert submitted["status"] == "VALIDATED"

        # Batch is no longer DRAFT AND the version is stale: the OCC error (tier 5)
        # must outrank the DRAFT-state error (tier 6).
        resp = api.submit_batch(batch["id"], {"expected_batch_version": pre_submit_version}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)


class TestHierarchyValidation:
    def test_hierarchy_cycle_rejected_on_apply(self, api):
        """PRD §3.4: "a `POSITION_HIERARCHY` change additionally requires the new
        parent to exist and be `ACTIVE` (`ERR_POSITION_NOT_ACTIVE`), to create no
        cycle — the new parent may not be the position itself or any of its
        descendants (`ERR_HIERARCHY_CYCLE`) — to keep the chain within ten levels
        (`ERR_HIERARCHY_DEPTH_EXCEEDED`), and to carry an `effective_date` on or
        after the clock date (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`)"

        Design: Corner/validations/hierarchy_cycle_rejected_on_apply
        """
        pa = create_position_record(title="A", department="HQ")
        pb = create_position_record(title="B", department="ENG", parent_position_id=pa["id"])
        field = create_data_field_record(
            field_key="position.parent_position_id", sensitivity="INTERNAL", channels=[],
            owner_team="people", display_name="Reports To",
        )
        provision_grant("appr-1", "CHANGE_APPROVER")

        resp = api.create_position_change_request(
            pa["id"],
            {
                "target_type": "POSITION_HIERARCHY",
                "target_field_id": field["id"],
                "new_value": pb["id"],
                "effective_date": "2026-09-01",
                "expected_position_version": pa["version"],
            },
            ANALYST,
        )
        cr = validate_success(resp, expected_status=201)
        approve_change_request_record(cr["id"], "appr-1")

        err = api.apply_change_request(cr["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_HIERARCHY_CYCLE)
