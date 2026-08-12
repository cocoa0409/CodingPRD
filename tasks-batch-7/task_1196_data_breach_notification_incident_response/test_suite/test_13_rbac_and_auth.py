"""RBAC and authentication (corner design — validations + rbac sections)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_incident,
    create_incident_confirmed,
    create_incident_payload,
    create_issued_offer,
    get_success_data,
    make_affected_subject_headers,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
DA = TEST_USERS["data_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestAuthRequired:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`
        and `X-User-Role`. If either header is missing, or if `X-User-Role`
        is not one of the declared role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        # Call without X-User-Role / X-User-ID.
        resp = api.list_incidents(headers={"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )


class TestRoleForbidden:
    def test_auditor_cannot_create_incident(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted to
        invoke the requested endpoint, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST /incidents as
        authorized for `IncidentCommander` only; `Auditor` is read-only.

        Design: Corner/validations/role_forbidden_for_exclusive_endpoint
        """
        resp = api.create_incident(create_incident_payload(), AUD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    def test_data_analyst_cannot_confirm(self, api):
        """PRD §4: POST /incidents/{id}/confirm is authorized for
        `IncidentCommander` only. PRD §2.1: an unauthorized role is rejected
        with `ERR_FORBIDDEN` (HTTP 403).

        Design: Corner/rbac/data_analyst_cannot_confirm
        """
        inc = create_incident()
        resp = api.confirm_incident(inc["id"], DA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


class TestAuditorReadOnly:
    def test_auditor_can_read_incident(self, api):
        """PRD §2.1: "`Auditor` — read-only access across all resources for
        compliance review." PRD §4 lists Auditor on GET /incidents/{id}.

        Design: Corner/rbac/auditor_read_only_allowed
        """
        inc = create_incident()
        resp = api.get_incident(inc["id"], AUD)
        data = validate_success(resp)
        assert data["id"] == inc["id"]


class TestAffectedSubjectRole:
    def test_affected_subject_redeems_own_offer(self, api):
        """PRD §3.9: "The subject themselves, authenticating as
        `AffectedSubjectRole` with `X-User-ID` equal to the subject's `id`,
        may redeem the offer while `expires_at` remains strictly in the
        future ... Redemption moves the offer from `ISSUED` to `REDEEMED`."

        Design: Corner/rbac/affected_subject_role_redeems_own_offer
        """
        ctx = create_incident_confirmed(subject_count=1)
        inc = ctx["incident"]
        subj = ctx["subjects"][0]
        offer = create_issued_offer(inc, subj)

        redeem_resp = api.redeem_credit_monitoring_offer(
            inc["id"], offer["id"], make_affected_subject_headers(subj["id"])
        )
        redeemed = validate_success(redeem_resp)
        assert redeemed["status"] == "REDEEMED"
