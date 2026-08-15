"""Header/role enforcement and optimistic concurrency on the engagement."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_adjustment,
    create_engagement_payload,
    create_evidence_upload_payload,
    create_fieldwork_engagement,
    create_pbc,
    create_pbc_request_payload,
    engagement_version,
    get_engagement,
    make_preparer_headers,
    upload_evidence,
    validate_error,
    validate_success,
)
from test_helpers.constants import VALID_SHA256_A, VALID_SHA256_B

CONTROLLER = TEST_USERS["controller_headers"]
PREPARER = TEST_USERS["preparer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestUserContextHeaders:

    def test_missing_user_context_header_rejected(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request missing either header, or carrying a
        malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api_client.create_engagement(
            create_engagement_payload(client_name="C"), headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:

    def test_wrong_role_cannot_create_engagement(self):
        """PRD §2.1: "Each endpoint admits a defined set of roles (§4); a
        request whose role is not admitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/api/audit-engagements` | Create a new audit
        engagement | Controller |".

        Design: Corner/validations/wrong_role_cannot_create_engagement
        """
        resp = api_client.create_engagement(
            create_engagement_payload(client_name="C"), AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_preparer_cannot_create_pbc_request(self):
        """PRD §2.1: "Each endpoint admits a defined set of roles (§4); a
        request whose role is not admitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/api/pbc-requests` | Add a PBC request to an
        engagement | ExternalAuditor |".

        Design: Corner/rbac/preparer_cannot_create_pbc_request
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        resp = api_client.create_pbc_request(
            create_pbc_request_payload(eng["id"], title="T",
                                       owner_user_id="prep1"),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_auditor_cannot_disposition_adjustment(self):
        """PRD §2.1: "Each endpoint admits a defined set of roles (§4); a
        request whose role is not admitted is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: "| POST | `/api/adjustments/{id}/disposition` | Disposition a
        proposed adjustment | Controller |".

        Design: Corner/rbac/auditor_cannot_disposition_adjustment
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        adj = create_adjustment(eng["id"], 5_000, description="A")
        resp = api_client.disposition_adjustment(
            adj["id"], {"disposition": "ACCEPT"}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestOptimisticConcurrency:

    def test_stale_engagement_version_on_upload_rejected(self):
        """PRD §2.9: "Uploading evidence requires the request body to carry
        `expected_engagement_version`, a non-optional field holding the
        engagement `version` the client last observed. If the engagement's
        current `version` does not match — because signing or cancellation
        activity has advanced it since the client's last read — the upload is
        rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)".
        PRD §2.6: "Uploading evidence and signing the representation letter
        each increment the parent engagement's `version` by one".

        Design: Corner/cross_cutting_layers/occ_stale_engagement_version_on_upload_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        p1 = create_pbc(eng["id"], owner="prep1", title="T")
        p2 = create_pbc(eng["id"], owner="prep1", title="T2")
        snapshot = engagement_version(eng["id"])
        # A successful upload against the OTHER request advances the
        # engagement version (PRD §2.6), rendering the snapshot stale.
        first = upload_evidence(p2["id"], eng["id"], owner="prep1",
                                file_name="f.pdf", sha256=VALID_SHA256_A)
        assert first["status"] == "PENDING_REVIEW"
        advanced = engagement_version(eng["id"])
        assert advanced == snapshot + 1, (
            f"upload increments the engagement version by one "
            f"({snapshot} -> {advanced})"
        )
        resp = api_client.upload_evidence(
            p1["id"],
            create_evidence_upload_payload(
                snapshot, file_name="f.pdf", sha256=VALID_SHA256_B),
            make_preparer_headers("prep1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION)
        assert get_engagement(eng["id"])["version"] == advanced, \
            "rejected stale upload must not advance the engagement version"
