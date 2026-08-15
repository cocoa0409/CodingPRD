"""Authentication, authorization (segregation of duties), and validation order."""

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, create_batch, create_dailies_package,
    create_project, create_project_payload, create_turnover, create_vendor,
    create_vendor_bid, setup_active_project, setup_batch_ready,
    setup_staged_turnover_with_bid, stage_turnover, validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_media_manager_headers, make_post_supervisor_headers,
    make_qc_operator_headers, make_reviewer_lead_headers,
    make_vendor_rep_headers,
)

PS = make_post_supervisor_headers()
MM = make_media_manager_headers()
QC = make_qc_operator_headers()
RL = make_reviewer_lead_headers()


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "If either header is missing, or the role value is not one
        of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.9 item 1: "`X-User-Role` must be present and equal to one of the
        nine declared roles, and `X-User-ID` must be present; otherwise the
        request fails with `ERR_UNAUTHENTICATED` (HTTP 401). This check applies
        to every endpoint."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        resp = api.list_projects(headers={"X-User-ID": "u-1",
                                          "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_forbidden_role_on_exclusive_endpoint(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted to invoke
        the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`PostSupervisor` — owns the project lifecycle (create,
        activate, wrap, close, archive), ..."

        Design: Corner/validations/forbidden_role_on_exclusive_endpoint
        """
        resp = api.create_project(create_project_payload(
            title="X", client_code="CLX", storage_quota_gb=10), QC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestFromState:
    def test_invalid_state_on_missing_from_state(self, api):
        """PRD §2.9 item 6: "The target resource must currently be in the
        from-state required by the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409). Applies to every state-transition
        endpoint."
        PRD §3.2: "Finishing ingest moves the batch from `INGESTING` to
        `PROXYING`."

        Design: Corner/validations/invalid_state_on_missing_from_state
        """
        project = create_project(title="P", client_code="CL400",
                                 storage_quota_gb=10)
        batch = create_batch(project["id"], batch_label="D1",
                             ingest_window_start="2026-08-01T00:00:00Z",
                             ingest_window_end="2026-08-31T23:59:59Z")
        # Batch is DECLARED, never INGESTING: finish-ingest cannot apply.
        resp = api.finish_ingest(project["id"], batch["id"], MM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRoleExclusiveDenial:
    def test_media_manager_cannot_publish_dailies(self, api):
        """PRD §2.1: "`DailiesCoordinator` — owns dailies packaging and
        distribution: creating packages and publishing or revoking them."
        PRD §2.1: "If the role is recognized but is not permitted to invoke the
        endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/media_manager_cannot_publish_dailies
        """
        project, batch, _assets = setup_batch_ready(
            project_overrides={"title": "P", "client_code": "CL700",
                               "storage_quota_gb": 100})
        wm = validate_success(api.list_watermark_profiles(project["id"], PS))[0]
        pkg = create_dailies_package(project["id"], batch["id"], wm["id"])
        resp = api.publish_dailies_package(project["id"], pkg["id"], MM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_vendor_rep_cannot_award_own_bid(self, api):
        """PRD §2.1: "`PostSupervisor` — owns the project lifecycle (create,
        activate, wrap, close, archive), watermark profiles, edit bay management,
        turnover issue/close/void, bid award, and deliverable delivery and
        rejection."
        PRD §2.1: "If the role is recognized but is not permitted to invoke the
        endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/vendor_rep_cannot_award_own_bid
        """
        project, turnover, vendor, bid = setup_staged_turnover_with_bid(
            project_overrides={"title": "P", "client_code": "CL701",
                               "storage_quota_gb": 100},
            vendor_overrides={"capabilities": ["COLOR"], "capacity_slots": 2},
            turnover_overrides={"turnover_kind": "COLOR",
                                "sequence_label": "SEQ-01"})
        resp = api.award_bid(project["id"], bid["id"],
                             make_vendor_rep_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_reviewer_lead_cannot_create_archive_job(self, api):
        """PRD §2.1: "`MediaManager` — owns ingest, proxies, storage, and
        archives: batches and their ingest transitions, asset registration and
        verification, and archive jobs."
        PRD §2.1: "If the role is recognized but is not permitted to invoke the
        endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/reviewer_lead_cannot_create_archive_job
        """
        project = create_project(title="P", client_code="CL702",
                                 storage_quota_gb=100)
        resp = api.create_archive_job(project["id"], {
            "lto_generation": "LTO9", "target_scope": "FULL_PROJECT",
            "retention_years": 5}, RL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestQCReportAppendOnly:
    def test_qcreport_immutable_no_update_endpoint(self, api):
        """PRD §2.5: "A `QCReport` is an immutable, append-once record: it
        carries `id` and `created_at` only, and both `updated_at` and `version`
        are absent from it."
        PRD §2.6: "the system validates them sequentially from left to right and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing entity."

        Design: Corner/entities/qcreport_immutable_no_update_endpoint
        """
        resp = api.list_deliverable_qc_reports(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, QC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
