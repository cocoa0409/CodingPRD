"""Authentication, role permissioning, ownership, scope, segregation of duties
(PRD §2.1, §2.8, §3.5, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_crew_member_payload,
    create_display_payload,
    create_incident_payload,
    create_operator_payload,
    create_site_plan_payload,
    create_weather_reading_payload,
    get_success_data,
    make_crew_member_headers,
    make_marshal_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MARSHAL_1,
    add_site_plan,
    approve_permit,
    create_operator,
    setup_event_draft,
    setup_event_standby_confirmed,
    setup_event_submitted,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or the role string is not
        one of the declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api._request("GET", f"/pyro/displays/{NON_EXISTENT_UUID}", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401

    def test_role_checked_before_existence(self, api):
        """PRD §2.8: "Authentication comes first — missing or unknown headers yield `ERR_UNAUTHENTICATED` — followed by role permissioning, which yields `ERR_FORBIDDEN_ROLE`."
        PRD §2.8: "Fourth, existence: path identifiers are resolved left-to-right and body-referenced identifiers (`site_plan_id`, `product_batch_id`, `display_event_id`) must exist, otherwise `ERR_NOT_FOUND`."

        Design: Corner/validations/role_checked_before_existence
        """
        resp = api.ready_display(NON_EXISTENT_UUID, make_marshal_headers("fm_9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403


class TestRbacDenials:
    def test_fire_marshal_cannot_create_display(self, api):
        """PRD §2.1: "If the role is recognized but not permitted on the
        endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)." PRD §4: POST /pyro/displays is authorized for Operator only.

        Design: Corner/rbac/fire_marshal_cannot_create_display_returns_forbidden
        """
        resp = api.create_display(create_display_payload(), make_marshal_headers("fm_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_operator_cannot_approve_permit(self, api):
        """PRD §2.1: "If the role is recognized but not permitted on the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /pyro/permit-applications/{id}/approve ("FireMarshal approves the application") is authorized for FireMarshal only.

        Design: Corner/rbac/operator_cannot_approve_permit_returns_forbidden
        """
        op, op_headers, ev, sp, app = setup_event_submitted()
        resp = api.approve_permit(app["id"], {"decision_note": "self-approve"}, op_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fresh = get_success_data(api.get_permit_application(app["id"], op_headers))
        assert fresh["status"] == "SUBMITTED"

    def test_cross_operator_ownership_returns_forbidden(self, api):
        """PRD §2.1: "A display's `operator_id`, a magazine's `operator_id`, a batch reached through its magazine's `operator_id`, and any child of a display are all checked this way; a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/cross_operator_ownership_returns_forbidden
        """
        opa, opa_headers = create_operator(
            legal_name="Pyro A", atf_license_number="ATF-A"
        )
        opb, opb_headers = create_operator(
            legal_name="Pyro B", atf_license_number="ATF-B"
        )
        ev = get_success_data(
            api.create_display(create_display_payload(), opa_headers)
        )
        resp = api.cancel_display(ev["id"], {"reason": "not mine"}, opb_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert resp.status_code == 403
        fresh = get_success_data(api.get_display(ev["id"], opa_headers))
        assert fresh["status"] == "DRAFT"

    def test_crew_scope_mismatch_rejected(self, api):
        """PRD §2.1: "when a crew member records a reading or report against a
        display, the server verifies that the crew member belongs to the
        display's operator — a cross-scope mismatch surfaces as
        `ERR_SCOPE_MISMATCH` (HTTP 422)".

        Design: Corner/rbac/crew_scope_mismatch_rejected
        """
        opa, opa_headers = create_operator(
            legal_name="Pyro A", atf_license_number="ATF-A"
        )
        opb, opb_headers = create_operator(
            legal_name="Pyro B", atf_license_number="ATF-B"
        )
        ev = get_success_data(api.create_display(create_display_payload(), opa_headers))
        crew_b = get_success_data(api.create_crew_member(
            opb["id"],
            create_crew_member_payload(full_name="Bo", cert_level="SHOOTER"),
            opb_headers,
        ))
        resp = api.create_weather_reading(
            ev["id"],
            create_weather_reading_payload(),
            make_crew_member_headers(crew_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCOPE_MISMATCH)
        assert resp.status_code == 422


class TestSegregationOfDuties:
    def test_sod_standby_same_marshal_rejected(self, api):
        """PRD §3.5: "Segregation of duties applies: the confirming marshal's
        `X-User-ID` must differ from the `reviewed_by_user_id` on the approved
        application, else `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/sod_standby_same_marshal_rejected
        """
        # Build APPROVED event with approver fm_1, then attempt confirm as fm_1.
        op, op_headers, ev, sp, app = setup_event_submitted()
        approve_permit(app, marshal_headers=make_marshal_headers("fm_1"))
        bad = api.standby_confirm(
            ev["id"], {"standby_engines_on_site": 1}, make_marshal_headers("fm_1")
        )
        validate_error(bad, ApiErrorId.ERR_SOD_VIOLATION)
        assert bad.status_code == 403
        good = api.standby_confirm(
            ev["id"], {"standby_engines_on_site": 1}, make_marshal_headers("fm_2")
        )
        data = validate_success(good)
        assert data["status"] == "STANDBY_CONFIRMED"
        assert data["standby_confirmed_by"] == "fm_2"

    def test_sod_incident_close_by_reporter_rejected(self, api):
        """PRD §3.8: "segregation of duties forbids the same user id from
        closing a report they filed, surfacing as `ERR_SOD_VIOLATION`."
        PRD §3.8: "Closure stamps `closed_by_user_id`, moves the report
        `FILED → CLOSED`".

        Design: Corner/rbac/sod_incident_close_by_reporter_rejected
        """
        op, op_headers, ev, sp, app = setup_event_standby_confirmed()
        inc = get_success_data(api.create_incident(
            ev["id"],
            create_incident_payload(incident_type="CROWD_BREACH", description="spectator near tape"),
            make_marshal_headers("fm_9"),
        ))
        assert inc["reported_by_user_id"] == "fm_9"
        bad = api.close_incident(
            inc["id"], {"resolution_note": "escorted out"}, make_marshal_headers("fm_9")
        )
        validate_error(bad, ApiErrorId.ERR_SOD_VIOLATION)
        good = api.close_incident(
            inc["id"], {"resolution_note": "escorted out"}, make_marshal_headers("fm_10")
        )
        data = validate_success(good)
        assert data["status"] == "CLOSED"
        assert data["closed_by_user_id"] == "fm_10"
