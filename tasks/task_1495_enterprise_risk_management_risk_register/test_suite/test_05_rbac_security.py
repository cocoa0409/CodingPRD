"""Corner: rbac — role denials (auditor write, control-owner approve mapping,
risk-manager finalize report, risk-owner attest). Cross-cutting OCC is in
test_06."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_risk,
    create_assessed_risk,
    create_active_control, create_proposed_mapping,
    create_report,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers, make_internal_auditor_headers,
    make_board_reporter_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_CONTROL_OWNER,
    USER_INTERNAL_AUDITOR, USER_BOARD_REPORTER,
)


class TestAuditorReadOnly:
    def test_auditor_write_attempt_forbidden(self):
        """PRD §2.1: "the `InternalAuditor` is a read-only assurance role, so
        every write attempt from an auditor fails this check."
        PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/auditor_write_attempt_forbidden
        """
        cat = create_category(name="AU")
        risk = create_risk(cat["id"], title="R")
        # Write attempt from auditor
        res = api_client.create_risk(
            {"category_id": cat["id"], "title": "AuditWrite",
             "owner_user_id": USER_RISK_OWNER},
            make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        # Read by auditor succeeds
        got = validate_success(
            api_client.get_risk(
                risk["id"], make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
            ), 200,
        )
        assert got["id"] == risk["id"]


class TestMappingApprovalSegregated:
    def test_controlowner_cannot_approve_mapping(self):
        """PRD §4: `POST /control-mappings/{id}/approve` is authorized for
        `RiskManager` only; the ControlOwner role (which owns the control
        library) is not listed.
        PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/controlowner_cannot_approve_mapping_forbidden
        """
        risk = create_assessed_risk(likelihood=2, impact=2)
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        res = api_client.approve_mapping(
            m["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        # Mapping remains PROPOSED
        list_res = api_client.list_risk_control_mappings(
            risk["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        mappings = validate_success(list_res, 200)
        statuses = {mm["id"]: mm["status"] for mm in mappings}
        assert statuses[m["id"]] == "PROPOSED"


class TestReportFinalizeSegregated:
    def test_riskmanager_cannot_finalize_report(self):
        """PRD §4: `POST /reports/{id}/finalize` is authorized for
        `BoardReporter` only.
        PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/riskmanager_cannot_finalize_report_forbidden
        """
        rep = create_report(variant="FINAL")
        res = api_client.finalize_report(
            rep["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        got = validate_success(
            api_client.get_report(
                rep["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        assert got["status"] == "DRAFT"


class TestControlAttestationSegregated:
    def test_riskowner_cannot_attest_control(self):
        """PRD §4: `POST /controls/{id}/attest` is authorized for
        `ControlOwner` only; RiskOwner is not listed.
        PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/riskowner_cannot_attest_control_forbidden
        """
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        # ACTIVE -> UNDER_REVIEW so attest is the defined next transition
        api_client.review_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        res = api_client.attest_control(
            ctl["id"], {"effectiveness_pct": 0.7},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
