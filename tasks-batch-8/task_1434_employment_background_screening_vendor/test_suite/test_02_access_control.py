"""Access control: header validation, role gating, and entity-backed ownership."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_candidate_payload,
    create_consent_payload,
    create_matrix_payload,
    create_report_payload,
    create_vendor_payload,
    get_success_data,
    make_candidate_headers,
    make_vendor_agent_headers,
    setup_dispatched_order,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]
ADJ = TEST_USERS["adjudicator_headers"]


class TestAuthHeaderGate:
    def test_missing_auth_headers_rejected(self, api):
        """PRD section "User and Role-Based Access Control": "A request missing
        either header, or carrying an unrecognized role name, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)." and PRD
        section "Validation Ordering": "First, authentication: the two headers
        must be present and the role recognized
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        # No X-User-ID / X-User-Role headers at all: authentication (first
        # pipeline category) fires before existence, so even a non-existent id
        # yields the header error, not ERR_NOT_FOUND.
        resp = api.get_vendor(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleDenialMatrix:
    def test_role_denial_matrix_exclusive_operations(self, api):
        """PRD section "User and Role-Based Access Control": "A request whose
        role is not permitted for the endpoint, or that fails an entity-backed
        ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD
        section "Validation Ordering": "Second, authorization: the role must be
        permitted for the endpoint ... (`ERR_FORBIDDEN`). Third, existence:
        ..."."

        Design: Corner/roles/role_denial_matrix_exclusive_operations
        """
        vendor = validate_success(
            api.create_vendor(create_vendor_payload(name="V-RB1"), HR),
            expected_status=201,
        )
        candidate = validate_success(
            api.create_candidate(
                create_candidate_payload(full_name="Rb One", email="rb1@x.com"), HR
            ),
            expected_status=201,
        )

        cases = [
            # POST /vendors is HRAdmin-only; HiringManager is rejected.
            api.create_vendor(create_vendor_payload(name="V-RB1-X"), HM),
            # POST /screening-orders is HiringManager-only; Candidate is
            # rejected (role gate precedes the non-existent position check).
            api.create_order(
                {"candidate_id": candidate["id"], "position_id": NON_EXISTENT_UUID},
                make_candidate_headers(candidate["id"]),
            ),
            # POST /adjudication-matrices is ComplianceOfficer-only.
            api.create_matrix(
                create_matrix_payload(), make_vendor_agent_headers(vendor["id"])
            ),
            # POST /vendors/{id}/suspend is ComplianceOfficer-only.
            api.suspend_vendor(vendor["id"], AUD),
            # POST /vendor-accuracy-audits is Auditor-only.
            api.create_audit(
                {
                    "vendor_id": vendor["id"],
                    "period_start": "2026-01-01T00:00:00Z",
                    "period_end": "2026-02-01T00:00:00Z",
                    "sample_size": 10,
                    "mismatches_found": 0,
                },
                HR,
            ),
            # send-final-notice is ComplianceOfficer-only; an Adjudicator is
            # rejected even for a non-existent case id (role before existence).
            api.send_final_notice(
                NON_EXISTENT_UUID, build_user_headers("adj-rb1", "Adjudicator")
            ),
            # POST /screening-orders rejects ComplianceOfficer.
            api.create_order(
                {"candidate_id": candidate["id"], "position_id": NON_EXISTENT_UUID},
                CO,
            ),
        ]
        for resp in cases:
            validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestEntityBackedOwnership:
    def test_entity_backed_ownership_enforcement(self, api):
        """PRD section "User and Role-Based Access Control": "when `X-User-Role`
        is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`
        record, and any ownership check on a resource that references a
        candidate (an order, a consent record, a dispute, a withdrawal)
        compares the resource's candidate foreign key to `X-User-ID`." and "Only
        the vendor assigned to an order may deliver its report: the acting
        `VendorAgent`'s identity must equal the order's `vendor_id`, else
        `ERR_FORBIDDEN`"."

        Design: Corner/roles/entity_backed_ownership_enforcement
        """
        ctx = setup_dispatched_order(tag="RB2", candidate_email="rb2a@x.com")
        order = ctx["order"]
        candidate_a = ctx["candidate"]

        # Candidate B cannot capture consent on candidate A's order. Build a
        # second order still in DRAFT for the ownership probe.
        candidate_b = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Rb TwoB", email="rb2b@x.com"),
                HR,
            )
        )

        # Fresh DRAFT order owned by candidate A on a second position.
        position_b = get_success_data(
            api.create_position(
                {
                    "title": "T2",
                    "department": "D",
                    "risk_tier": "TIER_1_STANDARD",
                    "package_id": ctx["package"]["id"],
                    "jurisdiction_code": "US-CA",
                    "annual_salary_cents": 9000000,
                },
                HR,
            )
        )
        order_a2 = get_success_data(
            api.create_order(
                {"candidate_id": candidate_a["id"], "position_id": position_b["id"]},
                HM,
            )
        )
        resp1 = api.capture_consent(
            order_a2["id"],
            create_consent_payload(),
            make_candidate_headers(candidate_b["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)

        # Vendor B cannot deliver a report for an order dispatched to vendor A.
        vendor_b = validate_success(
            api.create_vendor(create_vendor_payload(name="V-RB2-B"), HR),
            expected_status=201,
        )
        resp2 = api.create_report(
            create_report_payload(order["id"], findings=[]),
            make_vendor_agent_headers(vendor_b["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

        # The dispatched order is unaffected.
        order_now = validate_success(api.get_order(order["id"], HR))
        assert order_now["fulfillment_status"] == "DISPATCHED"
