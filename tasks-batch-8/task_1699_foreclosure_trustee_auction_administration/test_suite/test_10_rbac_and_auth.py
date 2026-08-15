"""Role-based access control, entity-backed ownership, and header authentication."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    create_beneficiary,
    create_case,
    create_nod_payload,
    make_beneficiary_headers,
    validate_error,
    validate_success,
)


class TestRolePermissions:
    def test_beneficiary_cannot_record_nod_returns_403(self, api):
        """PRD §2.1: "When the caller is authenticated but the role is not among those permitted for the endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The complete role-permission mapping for each operation appears in the endpoint table in Section 4."
        PRD §4: "Record the notice of default (`REFERRED` to `NOD_RECORDED`)" — the endpoint table lists `CaseManager` as this operation's only authorized role.

        Design: Corner/rbac/beneficiary_cannot_record_nod_returns_403
        """
        ben = create_beneficiary("BEN-RB1")
        case = create_case(ben["id"], loan_reference="LN-RB1")
        resp = api.record_nod(
            case["id"],
            create_nod_payload(instrument_number="NOD-RB1"),
            make_beneficiary_headers(ben["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request arriving without these headers, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        resp = api.list_cases(NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestBeneficiaryOwnership:
    def test_beneficiary_cannot_read_others_case_returns_403(self, api):
        """PRD §2.1: "Concretely, a `Beneficiary`-role call that touches a specific case — reading the case itself, submitting or listing its bidding instructions, or submitting or listing its cost advances — requires the case's `beneficiary_id` to equal `X-User-ID`; otherwise the request is rejected with `ERR_BENEFICIARY_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/beneficiary_cannot_read_others_case_returns_403
        """
        ben_a = create_beneficiary("BEN-RB3A", name="Beneficiary RB3A",
                                   contact_email="rb3a@ben.example")
        ben_b = create_beneficiary("BEN-RB3B", name="Beneficiary RB3B",
                                   contact_email="rb3b@ben.example")
        case_a = create_case(ben_a["id"], loan_reference="LN-RB3A")
        resp = api.get_case(case_a["id"], make_beneficiary_headers(ben_b["id"]))
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_OWNERSHIP_MISMATCH, 403)
        own = validate_success(
            api.get_case(case_a["id"], make_beneficiary_headers(ben_a["id"])), 200
        )
        assert own["id"] == case_a["id"]
