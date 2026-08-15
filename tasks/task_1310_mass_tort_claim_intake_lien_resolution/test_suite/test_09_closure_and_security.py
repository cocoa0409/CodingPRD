"""Closing-statement sealing and immutability; authentication and role gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_closing_statement,
    create_program, create_published_matrix, create_claimant,
    create_injury_verified_claim, create_ready_for_disbursement_claim,
    create_closed_claim, get_claim_version,
    make_disbursement_approver_headers,
    PREPARE_USER_ID, APPROVER_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
RECORDS = TEST_USERS["records_analyst_headers"]
LIEN_HEADERS = TEST_USERS["lien_analyst_headers"]


class TestClosingStatement:
    def test_closing_statement_snapshot_and_no_version_field(self, api, program_admin_headers):
        """PRD §2.4: "`ClosingStatement` is an append-only artifact and is the single exception: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it entirely."
        PRD §3.8: "Closing a claim moves it from `DISBURSED` to the terminal `CLOSED` status and seals an immutable `ClosingStatement`: an append-only audit artifact carrying the claim's `gross_award_cents`, `total_lien_cents`, `attorney_fee_cents`, and `net_award_cents` as a snapshot at closing, a rendered `statement_body`, and a `sealed_at` timestamp taken from the program clock."

        Design: Corner/entities/closing_statement_immutable_no_version_field
        """
        ctx = create_closed_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        assert ctx["claim"]["status"] == "CLOSED"
        resp = api.list_closing_statements(pid, cid, program_admin_headers)
        body = resp.json()
        assert resp.status_code == 200 and isinstance(body.get("data"), list)
        assert len(body["data"]) == 1, f"Exactly one closing statement must be sealed, got {len(body['data'])}"
        stmt = body["data"][0]
        assert_closing_statement(stmt)
        assert stmt["gross_award_cents"] == 5_000_000
        assert stmt["net_award_cents"] == 5_000_000


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_error
        """
        resp = api.list_programs(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the role under which that user acts. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_error
        """
        resp = api.list_programs(headers={"X-User-Role": "ProgramAdministrator"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_records_analyst_cannot_assign_tier(self, api, records_analyst_headers):
        """PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.4: "Tier assignment is the pivot on which the money turns, and it is performed by a `ProgramAdministrator`."

        Design: Corner/endpoints/rbac_denied_records_analyst_cannot_assign_tier
        """
        program = create_program(program_code="MT-RBAC1")
        pid = program["id"]
        matrix = create_published_matrix(pid, severity_score_min=0, severity_score_max=100,
                                         base_award_cents=5_000_000)
        claimant = create_claimant(pid, full_name="Ned", ssn_last4="3131")
        claim, _ = create_injury_verified_claim(pid, claimant["id"], severities=(70, 65))
        version = get_claim_version(pid, claim["id"])
        resp = api.assign_tier(pid, claim["id"],
                               {"tier_matrix_id": matrix["id"], "expected_claim_version": version},
                               records_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_lien_analyst_cannot_release_disbursement(self, api, lien_analyst_headers):
        """PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`DisbursementApprover` prepares, approves, releases, and voids disbursements, subject to a segregation-of-duties rule against the prepare-disbursement caller."

        Design: Corner/endpoints/rbac_denied_lien_analyst_cannot_release_disbursement
        """
        ctx = create_ready_for_disbursement_claim(
            prepare_user_id=PREPARE_USER_ID,
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        did = ctx["disbursements"][0]["id"]
        validate_success(api.approve_disbursement(
            pid, cid, did, make_disbursement_approver_headers(APPROVER_USER_ID)))
        resp = api.release_disbursement(pid, cid, did, lien_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
