"""Role-based access control and segregation-of-duties role chain tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_shelf_slot, create_scanner_unit, shelve_box, set_clock,
    batch_in_scanning, scan_and_commit, index_document, destroy_box,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_prep_technician_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers,
    make_destruction_specialist_headers, make_compliance_officer_headers,
    make_client_user_headers,
    ADMIN, CLERK, PREP, SCAN, QA, IDX, DS, CO, WITNESS,
)


class TestIndexerCannotCreateBatchesForbidden:
    """Corner: indexer_cannot_create_batches_forbidden."""

    def test_indexer_role_denied_on_batch_create(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint —
        or a `ClientUser` acting outside its own client subtree — is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/indexer_cannot_create_batches_forbidden
        """
        client, _ = create_client_with_agreement(name="RBAC Co", hipaa_covered=False)
        resp = api_client.create_batch(
            {"client_id": client["id"], "priority": "STANDARD"},
            make_indexer_headers("idx-9"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestClientUserCrossTenantReadForbidden:
    """Corner: client_user_cross_tenant_read_forbidden."""

    def test_cross_tenant_read_denied_own_tenant_allowed(self, api):
        """PRD §2.1: "The exception is `ClientUser`: when `X-User-Role` is
        `ClientUser`, `X-User-ID` is the `id` of the acting `Client`, and
        every ownership check on a resource that references a client compares
        the resource's `client_id` to `X-User-ID`. A `ClientUser` may read
        only its own client subtree and may act (request returns, create or
        revoke grants, download) only within it."

        Design: Corner/rbac/client_user_cross_tenant_read_forbidden
        """
        client_a, _ = create_client_with_agreement(name="Tenant A", hipaa_covered=False)
        client_b, _ = create_client_with_agreement(name="Tenant B", hipaa_covered=False)
        batch_b = create_batch(client_b["id"])

        # ClientUser A reads B's batch: forbidden.
        resp = api_client.get_batch(batch_b["id"], make_client_user_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        # ClientUser B reads its own batch: allowed.
        ok = api_client.get_batch(batch_b["id"], make_client_user_headers(client_b["id"]))
        data = validate_success(ok, expected_status=200)
        assert data["status"] == "INTAKE"


class TestSegregationOfDutiesRoleExclusiveChain:
    """Corner: segregation_of_duties_role_exclusive_chain."""

    def test_close_is_compliance_only_intake_clerk_denied(self, api):
        """PRD §4 endpoint table: `POST /batches/{id}/close` is bound to
        `ComplianceOfficer`. PRD §2.1: "A request whose role is not permitted
        for the endpoint — or a `ClientUser` acting outside its own client
        subtree — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/segregation_of_duties_role_exclusive_chain
        """
        # Drive a batch through the full pipeline with per-step roles.
        client, _ = create_client_with_agreement(
            name="SoD Co", hipaa_covered=False, retention_days=5,
        )
        slot = create_shelf_slot(shelf_code="SH-SOD", zone="GENERAL", capacity_grams=2000)
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx["box"]["id"], slot["id"])
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 100)])
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        set_clock("2026-05-15T00:00:00Z")
        destroy_box(ctx["box"]["id"], method="PULP")

        # IntakeClerk attempts close: denied (role-exclusive op).
        resp = api_client.close_batch(ctx["batch"]["id"], make_intake_clerk_headers(CLERK))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        # ComplianceOfficer closes successfully.
        ok = api_client.close_batch(ctx["batch"]["id"], make_compliance_officer_headers(CO))
        batch = validate_success(ok, expected_status=200)
        assert batch["status"] == "CLOSED"
