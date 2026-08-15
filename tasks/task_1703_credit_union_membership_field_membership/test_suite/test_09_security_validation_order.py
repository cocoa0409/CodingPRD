"""Authentication, role-based access control, member ownership, and the
ordered validation ladder."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    add_segment_amendment_payload,
    create_charter_payload,
    create_declaration_payload,
    create_member,
    create_membership_application_payload,
    declare_dividend,
    file_add_segment_amendment,
    make_compliance_officer_headers,
    make_member_headers,
    make_operations_officer_headers,
    make_regulator_headers,
    make_system_admin_headers,
    set_clock,
    setup_charter,
    validate_error,
    validate_paginated,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_director_headers"]
FILER = TEST_USERS["membership_officer_headers"]
OFFICER_9 = TEST_USERS["membership_officer_9_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
REG = TEST_USERS["regulator_headers"]
OPS = TEST_USERS["operations_officer_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their capacity.
        A request missing either header, or carrying an empty value for either,
        is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.6: "`X-User-ID` and `X-User-Role` must be present and non-empty
        on every endpoint, otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_charter(
            create_charter_payload(bond_type="COMMUNITY", segments=[]),
            NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestValidationLadder:
    def test_syntactic_validation_precedes_existence(self, api):
        """PRD §2.6: "Required fields must be present, types must be correct,
        enum values must be in range, and basis-dependent field combinations
        must hold — a SEGMENT_MATCH application requires `segment_id`; a FAMILY
        or HOUSEHOLD application requires `sponsor_member_id` and
        `relationship_to_sponsor`; an ADD_SEGMENT amendment requires the
        `proposed_segment_type`, `proposed_segment_descriptor`, and
        `proposed_segment_required_documents` fields; a RETIRE_SEGMENT
        amendment requires a non-empty `retire_segment_ids`. Any failure is
        `ERR_VALIDATION_FAILED` (400). This tier applies to all endpoints."
        PRD §2.6: "Path identifiers and body foreign-key references must exist,
        validated left to right, otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/validations/syntactic_validation_precedes_existence
        """
        resp = api.create_membership_application(
            create_membership_application_payload(
                applicant_full_name="Bad Enum", basis="FOOBAR",
                segment_id=NON_EXISTENT_UUID, documents_provided=[]),
            FILER)
        # The out-of-range basis enum is a syntactic failure; the nonexistent
        # segment reference is never reached.
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)

    def test_existence_precedes_state_on_action_endpoints(self, api):
        """PRD §2.9: "Requests that address nested resources — a segment under
        a charter, an account under a member, a ballot under a meeting —
        validate each path identifier in strict left-to-right order and are
        rejected with `ERR_NOT_FOUND` (404) at the first identifier that does
        not correspond to an existing resource. Body foreign-key references are
        likewise existence-checked at the same tier. No business or state rule
        is evaluated against a resource that has not first been found to
        exist."

        Design: Corner/validations/existence_precedes_state_on_action_endpoints
        """
        resp = api.approve_membership_application(NON_EXISTENT_UUID, OFFICER_9)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_occ_check_precedes_business_temporal_errors(self, api):
        """PRD §2.6: "The two optimistic-concurrency checks of §2.7 —
        `expected_charter_version` against the charter's current `version` on
        amendment filing, and `expected_member_version` against the member's
        current `version` on a profile update — are evaluated after existence
        and before any state-machine or business check, otherwise
        `ERR_STALE_CHARTER_VERSION` or `ERR_STALE_MEMBER_VERSION` (412)."

        Design: Corner/validations/occ_check_precedes_business_temporal_errors
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter()
        file_add_segment_amendment(charter["id"], charter["version"])

        stale_and_past = api.create_amendment_application(
            add_segment_amendment_payload(
                charter["id"], charter["version"],
                effective_date="2026-07-01",
                proposed_segment_descriptor="Old Town residents"),
            CO1)
        # The replayed baseline fails the OCC check before the past
        # effective_date is ever examined.
        validate_error(stale_and_past, ApiErrorId.ERR_STALE_CHARTER_VERSION)


class TestRoleBasedAccessControl:
    def test_member_cannot_declare_dividend(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: `POST /credit-union/dividend-declarations` — "Declare a
        dividend and run provisional accrual" — BoardDirector.

        Design: Corner/rbac/member_cannot_declare_dividend
        """
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Role Rita")
        resp = api.create_dividend_declaration(
            create_declaration_payload(),
            make_member_headers(member_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_regulator_cannot_create_charter(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: `POST /credit-union/charters` — "Create the singleton charter
        with its initial segments" — BoardDirector.

        Design: Corner/rbac/regulator_cannot_create_charter
        """
        resp = api.create_charter(
            create_charter_payload(bond_type="COMMUNITY", segments=[]),
            make_regulator_headers("reg-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_compliance_cannot_approve_own_amendment(self, api):
        """PRD §2.10: "The same principle is enforced by role boundaries: a
        `ComplianceOfficer` files charter amendments while a `Regulator`
        approves or denies them"
        PRD §4: `POST
        /credit-union/charter-amendment-applications/{id}/approve` — "Approve a
        submitted amendment application" — Regulator.

        Design: Corner/rbac/compliance_cannot_approve_own_amendment
        """
        set_clock("2026-08-01")
        charter, _segs = setup_charter()
        amend = file_add_segment_amendment(charter["id"], charter["version"])

        resp = api.approve_amendment_application(
            amend["id"], make_compliance_officer_headers("co-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        rows, _meta = validate_paginated(
            api.list_charter_amendment_applications(charter["id"], CO1))
        assert rows[0]["status"] == "SUBMITTED", (
            "The forbidden approval changes nothing")

    def test_operations_cannot_open_share_account(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: `POST /credit-union/share-accounts` — "Open a share account" —
        MembershipOfficer.

        Design: Corner/rbac/operations_cannot_open_share_account
        """
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Role Olga")
        resp = api.create_share_account(
            {"member_id": member_id, "account_type": "PRIMARY",
             "initial_deposit_cents": 500},
            make_operations_officer_headers("ops-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_board_cannot_execute_payment_run(self, api):
        """PRD §2.10: "a `BoardDirector` declares and voids dividends while an
        `OperationsOfficer` runs the payment — the declaring director never
        moves the money."
        PRD §4: `POST /credit-union/dividend-declarations/{id}/pay` — "Run the
        dividend payment" — OperationsOfficer.

        Design: Corner/rbac/board_cannot_execute_payment_run
        """
        set_clock("2026-08-02")
        decl = declare_dividend()
        set_clock("2026-08-10")
        resp = api.pay_dividend_declaration(
            decl["id"], TEST_USERS["board_director_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_systemadmin_cannot_read_business_data(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: `GET /credit-union/members` — "List members" —
        MembershipOfficer, ComplianceOfficer, Regulator, BoardDirector,
        OperationsOfficer, Member.

        Design: Corner/rbac/systemadmin_cannot_read_business_data
        """
        resp = api.list_members(make_system_admin_headers("sysadmin-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
