"""Authentication and role-based access control (PRD §2.1, §3)."""
from test_helpers import (
    ApiErrorId,
    CM,
    NON_EXISTENT_UUID,
    OPS,
    create_account,
    create_account_and_year,
    create_engagement,
    create_rin_lot_payload,
    create_vendor,
    get_success_data,
    make_auditor_headers,
    make_trader_headers,
    validate_error,
    validate_success,
    api_client,
)


class TestUnauthenticated:
    def test_missing_role_header_rejected_401(self, api):
        """PRD §2.1: "A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (401)."
        PRD §2.8: "Authentication comes first: missing or invalid headers yield `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        resp = api.get(
            f"/rfs/compliance-accounts/{NON_EXISTENT_UUID}",
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleDenials:
    def test_trader_cannot_run_diligence(self, api):
        """PRD §3.3: "Due diligence belongs to the `ComplianceManager`, who records an `outcome` on the vendor"
        PRD §2.1: "A request whose authenticated role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/trader_cannot_run_diligence
        """
        acct = create_account(epa_registration_id="EPA-RBAC-1")
        ven = create_vendor(acct["id"])  # UNVETTED
        resp = api.record_diligence(
            ven["id"], {"outcome": "APPROVED"}, make_trader_headers("tr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_vendor(ven["id"], CM))
        assert after["diligence_status"] == "UNVETTED"

    def test_auditor_cannot_create_lots(self, api):
        """PRD §2.1: "`ComplianceManager` is the RFS desk lead: it opens obligation years, records generation and blending, runs vendor diligence, builds and submits retirement batches and reports, manages the state-program overlay, and verifies or invalidates delivered RINs."
        PRD §2.1: "A request whose authenticated role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/auditor_cannot_create_lots
        """
        acct = create_account(epa_registration_id="EPA-RBAC-2")
        payload = create_rin_lot_payload(account_id=acct["id"], gallon_qty=10)
        resp = api.create_rin_lot(payload, make_auditor_headers("aud-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_opsadmin_cannot_close_attest_engagement(self, api):
        """PRD §3.6: "Clean findings close the engagement: the auditor moves `FINDINGS_ISSUED` → `CLOSED_CLEAN`"
        PRD §4: the close endpoint is authorized for Auditor only.
        PRD §2.1: "A request whose authenticated role is not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/opsadmin_cannot_decide_own_attest_close
        """
        _acct, yr = create_account_and_year(epa_registration_id="EPA-RBAC-3")
        eng = create_engagement(yr["id"], auditor_user_id="aud-1")
        aud = make_auditor_headers("aud-1")
        get_success_data(api.begin_fieldwork(eng["id"], aud))
        get_success_data(api.issue_findings(eng["id"], {"findings": "CLEAN"}, aud))
        resp = api.close_engagement(eng["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
