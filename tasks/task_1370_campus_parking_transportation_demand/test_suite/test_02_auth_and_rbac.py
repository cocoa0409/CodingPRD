"""Authentication context, role authorization, and ownership checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_allocation,
    create_lot,
    create_patron,
    get_allocation_version,
    issue_citation,
    make_commuter_headers,
    purchase_permit,
    setup_patron_with_permit,
    validate_error,
    validate_success,
)


class TestAuthContext:
    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`
        and `X-User-Role`. If either header is missing, or if `X-User-Role` is
        not one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        resp = api.list_patrons(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 401)


class TestRoleAuthorization:
    def test_commuter_cannot_create_lot_forbidden(self, api):
        """PRD §2.1: "If the role is recognized but is not in the endpoint's
        authorized role list, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /parking/lots is authorized for ParkingAdmin only.

        Design: Corner/validations/commuter_cannot_create_lot_forbidden
        """
        patron = create_patron(full_name="C")
        resp = api.create_lot(
            {"lot_code": "HACK", "name": "Nope", "zone": "CORE", "capacity_total": 10},
            make_commuter_headers(patron["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_enforcement_officer_cannot_decide_appeal(self, api, admin_headers):
        """PRD §2.1: "If the role is recognized but is not in the endpoint's
        authorized role list, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /parking/citations/{citationId}/decide-appeal is
        authorized for AppealsOfficer only.

        Design: Corner/rbac/enforcement_officer_cannot_decide_appeal
        """
        ctx = setup_patron_with_permit(name="S", plate="S777", campus_role="STAFF")
        lot_b = create_lot(lot_code="LB", name="Lot B", zone="REMOTE")
        citation = issue_citation(lot_b["id"], "S777", "NO_VALID_PERMIT", officer_id="off-1")
        api.appeal_citation(
            citation["id"], {"reason": "not my car"},
            make_commuter_headers(ctx["patron"]["id"]),
        )
        # An EnforcementOfficer is not in decide-appeal's role list at all.
        resp = api.decide_appeal(
            citation["id"], {"outcome": "UPHELD"},
            {"X-User-ID": "off-1", "X-User-Role": "EnforcementOfficer"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = validate_success(api.get_citation(citation["id"], admin_headers))
        assert after["status"] == "UNDER_APPEAL", (
            f"citation must remain UNDER_APPEAL after a role rejection, got {after['status']}"
        )

    def test_commuter_cannot_issue_citation(self, api):
        """PRD §2.1: "If the role is recognized but is not in the endpoint's
        authorized role list, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /parking/citations is authorized for EnforcementOfficer
        only.

        Design: Corner/rbac/commuter_cannot_issue_citation
        """
        holder = setup_patron_with_permit(
            name="V", plate="V999", campus_role="STAFF",
            eligible_roles=["STUDENT", "STAFF"],
        )
        lot_b = create_lot(lot_code="LB", name="Lot B", zone="REMOTE")
        resp = api.create_citation(
            {"lot_id": lot_b["id"], "plate_number": "V999",
             "violation_type": "NO_VALID_PERMIT"},
            make_commuter_headers(holder["patron"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestOwnership:
    def test_commuter_cannot_cancel_others_permit(self, api, admin_headers):
        """PRD §2.1: "A Commuter acting on a resource whose owning `patron_id`
        does not match the supplied `X-User-ID` is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §4: POST /parking/permits/{permitId}/cancel is shared between
        Commuter and ParkingAdmin.

        Design: Corner/rbac/commuter_cannot_cancel_others_permit
        """
        ctx = setup_patron_with_permit(name="A", plate="A111", campus_role="STUDENT",
                                       lot_code="LO")
        other = create_patron(full_name="B", campus_role="STUDENT",
                              residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        resp = api.cancel_permit(ctx["permit"]["id"], make_commuter_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        ok = api.cancel_permit(ctx["permit"]["id"], admin_headers)
        data = validate_success(ok, 200)
        assert data["status"] == "CANCELLED", (
            f"ParkingAdmin cancel must succeed, got {data['status']}"
        )


class TestExistenceBeforeState:
    def test_decide_appeal_nonexistent_citation_returns_404(self, api, appeals_headers):
        """PRD §2.8: "4. **Existence** — path ids and body foreign keys
        resolve, validated left-to-right (patron, lot, allocation, entry,
        permit, citation, closure, route, incentive account, fund)."
        PRD §5 maps `ERR_CITATION_NOT_FOUND` to HTTP 404.

        Design: Corner/validations/decide_appeal_nonexistent_citation_returns_404
        """
        resp = api.decide_appeal(NON_EXISTENT_UUID, {"outcome": "UPHELD"}, appeals_headers)
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_FOUND, 404)
