"""Role-based access control: per-endpoint role gates and entity-backed
ownership checks (PRD section 2.1 and section 4 role columns)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_carrier,
    create_issued_policy,
    create_program,
    create_program_payload,
    create_tpa,
    get_program_fresh,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
    report_claim,
    setup_active_program,
    setup_program_with_issued_policy_and_tpa,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]
AUD = TEST_USERS["carrier_auditor_headers"]
TPA_OPAQUE = TEST_USERS["tpa_adjuster_headers"]


class TestRoleGates:
    def test_mga_finance_cannot_bind_policy(self, api):
        """PRD §2.1: "`MGAFinance` is the fiduciary desk — premium
        collections, carrier remittances, and bordereaux drafting/submission —
        deliberately segregated from underwriting." PRD §4 restricts
        `POST /mga/policies/{policyId}/bind` to MGAUnderwriter. PRD §2.11:
        "(2) role permission and entity-backed ownership (`ERR_FORBIDDEN`)"
        precedes "(3) existence".

        Design: Corner/rbac/rbac_mga_finance_cannot_bind_policy_forbidden
        """
        resp = api.bind_policy(NON_EXISTENT_UUID, FIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mga_underwriter_cannot_accept_bordereau(self, api):
        """PRD §4 restricts `POST /mga/bordereaux/{bordereauId}/accept` to
        CarrierUnderwriter; PRD §2.1: "a request whose role is not permitted
        for the target endpoint ... is rejected with `ERR_FORBIDDEN` (HTTP
        403)."

        Design: Corner/rbac/rbac_mga_underwriter_cannot_accept_bordereau_forbidden
        """
        resp = api.accept_bordereau(NON_EXISTENT_UUID, UW)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_carrier_underwriter_cannot_perform_audit(self, api):
        """PRD §2.1: "A `CarrierAuditor` schedules audits, conducts them,
        issues findings, and closes or escalates — organizationally separate
        from the carrier's underwriting function." PRD §4 restricts
        `POST /mga/programs/{programId}/audits` to CarrierAuditor.

        Design: Corner/rbac/rbac_carrier_underwriter_cannot_perform_audit_forbidden
        """
        carrier = create_carrier()
        program = create_program(carrier)
        cu = make_carrier_underwriter_headers(carrier["id"])
        resp = api.create_audit(program["id"], {
            "scope": "FULL", "scheduled_start": "2026-09-01T00:00:00Z",
            "scheduled_end": "2026-09-15T00:00:00Z"}, cu)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_carrier_auditor_cannot_activate_program(self, api):
        """PRD §2.1: "A `CarrierAuditor` schedules audits, conducts them,
        issues findings, and closes or escalates — organizationally separate
        from the carrier's underwriting function." PRD §4 restricts
        `POST /mga/programs/{programId}/activate` to CarrierUnderwriter, and
        PRD §2.1: "a request whose role is not permitted for the target
        endpoint, or that fails an entity-backed ownership check, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_carrier_auditor_cannot_activate_program_forbidden
        """
        carrier = create_carrier()
        program = create_program(carrier)
        resp = api.activate_program(program["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_platform_admin_cannot_bind_policy(self, api):
        """PRD §2.1: "A `PlatformAdmin` is the infrastructure operator: it
        onboards carriers and TPAs, suspends them, and exclusively drives the
        logical clock and the daily operations checkpoint." PRD §4 restricts
        `POST /mga/policies/{policyId}/bind` to MGAUnderwriter.

        Design: Corner/rbac/rbac_platform_admin_cannot_bind_forbidden
        """
        resp = api.bind_policy(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_tpa_adjuster_cannot_create_program(self, api):
        """PRD §4 restricts `POST /mga/programs` to MGAUnderwriter; PRD §2.1:
        "A `TPAAdjuster` reviews, reserves, refers, approves (within its
        delegated authority limit), denies, and pays claims."

        Design: Corner/rbac/rbac_tpa_adjuster_cannot_create_program_forbidden
        """
        carrier = create_carrier()
        resp = api.create_program(create_program_payload(carrier["id"]), TPA_OPAQUE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnershipChecks:
    def test_carrier_underwriter_wrong_carrier_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `CarrierUnderwriter`, `X-User-ID`
        is the `id` of the acting Carrier; ownership checks on any resource
        that references a Carrier compare the resource's `carrier_id` foreign
        key to `X-User-ID` — for example, only the carrier that granted a
        program may activate, suspend, or terminate it."

        Design: Corner/rbac/rbac_carrier_underwriter_wrong_carrier_forbidden
        """
        carrier_a = create_carrier()
        carrier_b = create_carrier()
        program = create_program(carrier_a)
        cu_b = make_carrier_underwriter_headers(carrier_b["id"])
        resp = api.suspend_program(program["id"], cu_b)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_program_fresh(program["id"])["status"] == "PROPOSED"

    def test_forbidden_ownership_precedes_state_validation(self, api):
        """PRD §2.11: "The order is: (1) authentication of the headers
        (`ERR_UNAUTHENTICATED`); (2) role permission and entity-backed
        ownership (`ERR_FORBIDDEN`); (3) existence ...; ... (7) state legality
        (`ERR_INVALID_STATE`, `ERR_PROGRAM_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`)."

        Design: Corner/validations/forbidden_beats_state_priority_ordering
        """
        carrier_a = create_carrier()
        carrier_b = create_carrier()
        program = create_program(carrier_a)  # PROPOSED: terminate is state-illegal
        cu_b = make_carrier_underwriter_headers(carrier_b["id"])
        # Both ownership (foreign carrier) and state (PROPOSED has no
        # terminate transition) fail; the ownership error wins.
        resp = api.terminate_program(
            program["id"], {"termination_reason": "hostile"}, cu_b)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_program_fresh(program["id"])["status"] == "PROPOSED"

    def test_tpa_adjuster_wrong_tpa_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `TPAAdjuster`, `X-User-ID` is the
        `id` of the acting TPA; ownership checks on a claim compare the
        claim's `assigned_tpa_id` to `X-User-ID`." PRD §3.6: "the acting
        `TPAAdjuster`'s `X-User-ID` must equal the claim's `assigned_tpa_id`
        for every adjuster action, with mismatches rejected as
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_tpa_adjuster_wrong_tpa_forbidden
        """
        carrier, program, tpa_a, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        tpa_b = create_tpa()
        claim = report_claim(policy, occurrence_date="2026-08-05T00:00:00Z",
                             amount_claimed_cents=30000)
        assert claim["assigned_tpa_id"] == tpa_a["id"]

        resp = api.start_claim_review(
            claim["id"], make_tpa_adjuster_headers(tpa_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
