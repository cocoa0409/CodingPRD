"""Response envelope, pagination, typed 404s, and user-context header gate
(PRD §2.1, §2.2, §2.3, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_draft_easement,
    validate_error,
    validate_paginated,
)


class TestPaginationEnvelope:
    def test_easement_list_pagination_envelope(self, api, trust_admin_headers):
        """PRD §2.3: "`limit` sets the maximum number of items returned; when not
        provided it defaults to 10, and accepted values run from a minimum of 1
        to a maximum of 100. `offset` sets how many items are skipped and
        defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the envelope's `meta` object."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/easement_list_pagination_envelope
        """
        first = create_draft_easement(name="E-P1", parcel_acreage=100,
                                      matrix={"AGRICULTURE": "PERMITTED"})
        second = create_draft_easement(name="E-P2", parcel_acreage=200,
                                       matrix={"AGRICULTURE": "PERMITTED"})

        resp1 = api.list_easements(trust_admin_headers, params={"limit": 1, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        body1 = resp1.json()
        assert isinstance(body1["meta"]["api_request_id"], str)
        assert isinstance(body1["meta"]["api_request_timestamp"], str)
        assert body1["response_type"] == "array"
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        resp2 = api.list_easements(trust_admin_headers, params={"limit": 1, "offset": 1})
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        # The two pages partition the two created easements.
        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {first["id"], second["id"]}


class TestTypedNotFound:
    def test_get_easement_not_found_returns_404(self, api, trust_admin_headers):
        """PRD §2.9: "Existence — path identifiers are validated left to right,
        and the first identifier that does not resolve yields its typed 404:
        `ERR_EASEMENT_NOT_FOUND` for `easementId`, `ERR_LANDOWNER_NOT_FOUND` for
        `landownerId`, `ERR_BASELINE_REPORT_NOT_FOUND` for `baselineReportId`,
        `ERR_MONITORING_VISIT_NOT_FOUND` for `monitoringVisitId`,
        `ERR_VIOLATION_NOT_FOUND` for `violationId`,
        `ERR_AMENDMENT_REQUEST_NOT_FOUND` for `amendmentRequestId`,
        `ERR_USE_AUTHORIZATION_NOT_FOUND` for `useAuthorizationId`,
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` for `enforcementActionId`,
        `ERR_SUCCESSION_NOTICE_NOT_FOUND` for `successionNoticeId`,
        `ERR_APPRAISAL_NOT_FOUND` for `appraisalId`, and
        `ERR_ENDOWMENT_FUND_NOT_FOUND` for `endowmentFundId`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/get_easement_not_found_returns_404
        """
        resp = api.get_easement(NON_EXISTENT_UUID, trust_admin_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_EASEMENT_NOT_FOUND)
        assert error_data["message"].strip(), "error must carry a human-readable message"

    def test_get_violation_not_found_returns_typed_404(self, api, coordinator_headers):
        """PRD §2.9: "Existence — path identifiers are validated left to right,
        and the first identifier that does not resolve yields its typed 404:
        `ERR_EASEMENT_NOT_FOUND` for `easementId`, `ERR_LANDOWNER_NOT_FOUND` for
        `landownerId`, `ERR_BASELINE_REPORT_NOT_FOUND` for `baselineReportId`,
        `ERR_MONITORING_VISIT_NOT_FOUND` for `monitoringVisitId`,
        `ERR_VIOLATION_NOT_FOUND` for `violationId`,
        `ERR_AMENDMENT_REQUEST_NOT_FOUND` for `amendmentRequestId`,
        `ERR_USE_AUTHORIZATION_NOT_FOUND` for `useAuthorizationId`,
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` for `enforcementActionId`,
        `ERR_SUCCESSION_NOTICE_NOT_FOUND` for `successionNoticeId`,
        `ERR_APPRAISAL_NOT_FOUND` for `appraisalId`, and
        `ERR_ENDOWMENT_FUND_NOT_FOUND` for `endowmentFundId`."

        Design: Corner/entities/get_violation_not_found_returns_typed_404
        """
        resp = api.get_violation(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_VIOLATION_NOT_FOUND)

    def test_typed_404_sweep_all_resources(self, api, trust_admin_headers):
        """PRD §2.9: "Existence — path identifiers are validated left to right,
        and the first identifier that does not resolve yields its typed 404:
        `ERR_EASEMENT_NOT_FOUND` for `easementId`, `ERR_LANDOWNER_NOT_FOUND` for
        `landownerId`, `ERR_BASELINE_REPORT_NOT_FOUND` for `baselineReportId`,
        `ERR_MONITORING_VISIT_NOT_FOUND` for `monitoringVisitId`,
        `ERR_VIOLATION_NOT_FOUND` for `violationId`,
        `ERR_AMENDMENT_REQUEST_NOT_FOUND` for `amendmentRequestId`,
        `ERR_USE_AUTHORIZATION_NOT_FOUND` for `useAuthorizationId`,
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` for `enforcementActionId`,
        `ERR_SUCCESSION_NOTICE_NOT_FOUND` for `successionNoticeId`,
        `ERR_APPRAISAL_NOT_FOUND` for `appraisalId`, and
        `ERR_ENDOWMENT_FUND_NOT_FOUND` for `endowmentFundId`."

        Design: Corner/errors/typed_404_sweep_all_resources
        """
        checks = [
            (api.get_landowner, ApiErrorId.ERR_LANDOWNER_NOT_FOUND),
            (api.get_baseline_report, ApiErrorId.ERR_BASELINE_REPORT_NOT_FOUND),
            (api.get_monitoring_visit, ApiErrorId.ERR_MONITORING_VISIT_NOT_FOUND),
            (api.get_amendment_request, ApiErrorId.ERR_AMENDMENT_REQUEST_NOT_FOUND),
            (api.get_use_authorization, ApiErrorId.ERR_USE_AUTHORIZATION_NOT_FOUND),
            (api.get_enforcement_action, ApiErrorId.ERR_ENFORCEMENT_ACTION_NOT_FOUND),
            (api.get_succession_notice, ApiErrorId.ERR_SUCCESSION_NOTICE_NOT_FOUND),
            (api.get_appraisal, ApiErrorId.ERR_APPRAISAL_NOT_FOUND),
            (api.get_endowment_fund, ApiErrorId.ERR_ENDOWMENT_FUND_NOT_FOUND),
        ]
        for getter, expected_error in checks:
            resp = getter(NON_EXISTENT_UUID, trust_admin_headers)
            assert resp.status_code == 404, (
                f"{expected_error} must use HTTP 404, got {resp.status_code}"
            )
            validate_error(resp, expected_error)


class TestUserContextHeader:
    def test_missing_user_context_header_returns_400(self, api, trust_admin_headers):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. A request missing either header, or naming a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_returns_400
        """
        # Neither X-User-ID nor X-User-Role present.
        resp = api.list_easements({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Role present but not one of the six declared roles.
        resp2 = api.list_easements(
            {"X-User-ID": "admin-1", "X-User-Role": "SuperUser",
             "Content-Type": "application/json"}
        )
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
