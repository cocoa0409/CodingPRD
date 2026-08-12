"""API client: one method per endpoint defined in the PRD.

Every POST automatically injects an ``Idempotency-Key`` header when the caller
did not supply one explicitly via ``extra_headers``; per the PRD every POST
must carry one. Tests that exercise the missing-idempotency-key error path
pass ``skip_idempotency=True``.
"""
import uuid

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _post(self, path, payload, headers, skip_idempotency=False, extra_headers=None):
        headers = dict(headers or {})
        if extra_headers:
            headers.update(extra_headers)
        if not skip_idempotency and "Idempotency-Key" not in headers:
            headers["Idempotency-Key"] = f"idem-{uuid.uuid4().hex}"
        return self._request("POST", path, payload, headers)

    # ---- clock ----
    def set_clock(self, to_iso8601, headers):
        return self._post("/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Case ----
    def create_case(self, payload, headers, **kw):
        return self._post("/api/cases", payload, headers, **kw)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def transition_case(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/transition", payload, headers, **kw)

    # ---- Allegation ----
    def create_allegation(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/allegations", payload, headers, **kw)

    def list_allegations(self, headers, params=None):
        return self._request("GET", "/api/allegations", headers=headers, params=params)

    def get_allegation(self, allegation_id, headers):
        return self._request("GET", f"/api/allegations/{allegation_id}", headers=headers)

    def transition_allegation(self, allegation_id, payload, headers, **kw):
        return self._post(f"/api/allegations/{allegation_id}/transition", payload, headers, **kw)

    # ---- InvestigationPlan ----
    def create_plan(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/plans", payload, headers, **kw)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}", headers=headers)

    def transition_plan(self, plan_id, payload, headers, **kw):
        return self._post(f"/api/plans/{plan_id}/transition", payload, headers, **kw)

    # ---- CaseSubject ----
    def create_subject(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/subjects", payload, headers, **kw)

    def list_subjects(self, headers, params=None):
        return self._request("GET", "/api/subjects", headers=headers, params=params)

    def get_subject(self, subject_id, headers):
        return self._request("GET", f"/api/subjects/{subject_id}", headers=headers)

    def transition_subject(self, subject_id, payload, headers, **kw):
        return self._post(f"/api/subjects/{subject_id}/transition", payload, headers, **kw)

    # ---- PreservationNotice ----
    def create_preservation_notice(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/preservation-notices", payload, headers, **kw)

    def list_preservation_notices(self, headers, params=None):
        return self._request("GET", "/api/preservation-notices", headers=headers, params=params)

    def get_preservation_notice(self, notice_id, headers):
        return self._request("GET", f"/api/preservation-notices/{notice_id}", headers=headers)

    def transition_preservation_notice(self, notice_id, payload, headers, **kw):
        return self._post(f"/api/preservation-notices/{notice_id}/transition", payload, headers, **kw)

    # ---- CollectionScope ----
    def create_collection_scope(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/collection-scopes", payload, headers, **kw)

    def list_collection_scopes(self, headers, params=None):
        return self._request("GET", "/api/collection-scopes", headers=headers, params=params)

    def get_collection_scope(self, scope_id, headers):
        return self._request("GET", f"/api/collection-scopes/{scope_id}", headers=headers)

    def transition_collection_scope(self, scope_id, payload, headers, **kw):
        return self._post(f"/api/collection-scopes/{scope_id}/transition", payload, headers, **kw)

    # ---- EvidenceItem ----
    def create_evidence_item(self, scope_id, payload, headers, **kw):
        return self._post(f"/api/collection-scopes/{scope_id}/evidence-items", payload, headers, **kw)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/api/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, item_id, headers):
        return self._request("GET", f"/api/evidence-items/{item_id}", headers=headers)

    def transition_evidence_item(self, item_id, payload, headers, **kw):
        return self._post(f"/api/evidence-items/{item_id}/transition", payload, headers, **kw)

    # ---- WitnessInterview ----
    def create_interview(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/interviews", payload, headers, **kw)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/api/interviews", headers=headers, params=params)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/api/interviews/{interview_id}", headers=headers)

    def transition_interview(self, interview_id, payload, headers, **kw):
        return self._post(f"/api/interviews/{interview_id}/transition", payload, headers, **kw)

    # ---- PrivilegeDesignation ----
    def create_privilege_designation(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/privilege-designations", payload, headers, **kw)

    def list_privilege_designations(self, headers, params=None):
        return self._request("GET", "/api/privilege-designations", headers=headers, params=params)

    def get_privilege_designation(self, designation_id, headers):
        return self._request("GET", f"/api/privilege-designations/{designation_id}", headers=headers)

    def transition_privilege_designation(self, designation_id, payload, headers, **kw):
        return self._post(f"/api/privilege-designations/{designation_id}/transition", payload, headers, **kw)

    # ---- Finding ----
    def create_finding(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/findings", payload, headers, **kw)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/api/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/api/findings/{finding_id}", headers=headers)

    def transition_finding(self, finding_id, payload, headers, **kw):
        return self._post(f"/api/findings/{finding_id}/transition", payload, headers, **kw)

    # ---- DisciplinaryRecommendation ----
    def create_disciplinary_recommendation(self, finding_id, payload, headers, **kw):
        return self._post(f"/api/findings/{finding_id}/disciplinary-recommendations", payload, headers, **kw)

    def list_disciplinary_recommendations(self, headers, params=None):
        return self._request("GET", "/api/disciplinary-recommendations", headers=headers, params=params)

    def get_disciplinary_recommendation(self, rec_id, headers):
        return self._request("GET", f"/api/disciplinary-recommendations/{rec_id}", headers=headers)

    def transition_disciplinary_recommendation(self, rec_id, payload, headers, **kw):
        return self._post(f"/api/disciplinary-recommendations/{rec_id}/transition", payload, headers, **kw)

    # ---- CaseReport ----
    def create_report(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/reports", payload, headers, **kw)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/api/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/api/reports/{report_id}", headers=headers)

    def transition_report(self, report_id, payload, headers, **kw):
        return self._post(f"/api/reports/{report_id}/transition", payload, headers, **kw)

    # ---- SelfDisclosureDecision ----
    def create_self_disclosure_decision(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/self-disclosure-decisions", payload, headers, **kw)

    def list_self_disclosure_decisions(self, headers, params=None):
        return self._request("GET", "/api/self-disclosure-decisions", headers=headers, params=params)

    def get_self_disclosure_decision(self, decision_id, headers):
        return self._request("GET", f"/api/self-disclosure-decisions/{decision_id}", headers=headers)

    def transition_self_disclosure_decision(self, decision_id, payload, headers, **kw):
        return self._post(f"/api/self-disclosure-decisions/{decision_id}/transition", payload, headers, **kw)

    # ---- RemediationAction ----
    def create_remediation_action(self, case_id, payload, headers, **kw):
        return self._post(f"/api/cases/{case_id}/remediation-actions", payload, headers, **kw)

    def list_remediation_actions(self, headers, params=None):
        return self._request("GET", "/api/remediation-actions", headers=headers, params=params)

    def get_remediation_action(self, action_id, headers):
        return self._request("GET", f"/api/remediation-actions/{action_id}", headers=headers)

    def transition_remediation_action(self, action_id, payload, headers, **kw):
        return self._post(f"/api/remediation-actions/{action_id}/transition", payload, headers, **kw)

    # ---- PatternAlert ----
    def scan_pattern_alerts(self, payload, headers, **kw):
        return self._post("/api/pattern-alerts/scan", payload, headers, **kw)

    def list_pattern_alerts(self, headers, params=None):
        return self._request("GET", "/api/pattern-alerts", headers=headers, params=params)

    def get_pattern_alert(self, alert_id, headers):
        return self._request("GET", f"/api/pattern-alerts/{alert_id}", headers=headers)

    def transition_pattern_alert(self, alert_id, payload, headers, **kw):
        return self._post(f"/api/pattern-alerts/{alert_id}/transition", payload, headers, **kw)


api_client = ApiClient()
