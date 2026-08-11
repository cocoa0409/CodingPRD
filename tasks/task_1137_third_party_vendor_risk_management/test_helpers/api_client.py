"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tprm/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/tprm/_clock/current_utc", headers=headers)

    # --- Vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/tprm/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/tprm/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/tprm/vendors/{vendor_id}", headers=headers)

    def activate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/activate", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/suspend", headers=headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/reinstate", headers=headers)

    def exit_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/exit", headers=headers)

    def tier_change_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/tier-change", payload, headers)

    def list_tier_change_log(self, vendor_id, headers, params=None):
        return self._request("GET", f"/tprm/vendors/{vendor_id}/tier-change-log", headers=headers, params=params)

    # --- Vendor engagements ---
    def create_engagement(self, vendor_id, payload, headers):
        return self._request("POST", f"/tprm/vendors/{vendor_id}/engagements", payload, headers)

    def list_engagements(self, vendor_id, headers, params=None):
        return self._request("GET", f"/tprm/vendors/{vendor_id}/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/tprm/engagements/{engagement_id}", headers=headers)

    def initiate_exit(self, engagement_id, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/initiate-exit", headers=headers)

    def finalize_exit(self, engagement_id, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/finalize-exit", headers=headers)

    def terminate_for_cause(self, engagement_id, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/terminate-for-cause", headers=headers)

    # --- Due-diligence packages ---
    def create_dd_package(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/due-diligence-packages", payload, headers)

    def list_dd_packages(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/due-diligence-packages", headers=headers, params=params)

    def get_dd_package(self, package_id, headers):
        return self._request("GET", f"/tprm/due-diligence-packages/{package_id}", headers=headers)

    def submit_dd_package(self, package_id, headers, payload=None):
        return self._request("POST", f"/tprm/due-diligence-packages/{package_id}/submit", payload or {}, headers)

    def begin_review_dd_package(self, package_id, headers):
        return self._request("POST", f"/tprm/due-diligence-packages/{package_id}/begin-review", headers=headers)

    def approve_dd_package(self, package_id, payload, headers):
        return self._request("POST", f"/tprm/due-diligence-packages/{package_id}/approve", payload, headers)

    def reject_dd_package(self, package_id, headers):
        return self._request("POST", f"/tprm/due-diligence-packages/{package_id}/reject", headers=headers)

    def resubmit_dd_package(self, package_id, payload, headers):
        return self._request("POST", f"/tprm/due-diligence-packages/{package_id}/resubmit", payload, headers)

    # --- Contracts ---
    def create_contract(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/contracts", payload, headers)

    def list_contracts_on_engagement(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/contracts", headers=headers, params=params)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/tprm/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/tprm/contracts/{contract_id}", headers=headers)

    def execute_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/tprm/contracts/{contract_id}/execute", payload, headers)

    # --- Fourth parties ---
    def create_fourth_party(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/fourth-parties", payload, headers)

    def list_fourth_parties_on_engagement(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/fourth-parties", headers=headers, params=params)

    def list_fourth_parties(self, headers, params=None):
        return self._request("GET", "/tprm/fourth-parties", headers=headers, params=params)

    def get_fourth_party(self, fourth_party_id, headers):
        return self._request("GET", f"/tprm/fourth-parties/{fourth_party_id}", headers=headers)

    def acknowledge_fourth_party(self, fourth_party_id, headers):
        return self._request("POST", f"/tprm/fourth-parties/{fourth_party_id}/acknowledge", headers=headers)

    def reject_fourth_party(self, fourth_party_id, headers):
        return self._request("POST", f"/tprm/fourth-parties/{fourth_party_id}/reject", headers=headers)

    # --- Monitoring cycles ---
    def list_monitoring_cycles(self, vendor_id, headers, params=None):
        return self._request("GET", f"/tprm/vendors/{vendor_id}/monitoring-cycles", headers=headers, params=params)

    def get_monitoring_cycle(self, cycle_id, headers):
        return self._request("GET", f"/tprm/monitoring-cycles/{cycle_id}", headers=headers)

    def begin_monitoring_cycle(self, cycle_id, headers):
        return self._request("POST", f"/tprm/monitoring-cycles/{cycle_id}/begin", headers=headers)

    def complete_monitoring_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/tprm/monitoring-cycles/{cycle_id}/complete", payload or {}, headers)

    def waive_monitoring_cycle(self, cycle_id, headers):
        return self._request("POST", f"/tprm/monitoring-cycles/{cycle_id}/waive", headers=headers)

    # --- Incidents ---
    def create_incident(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/incidents", payload, headers)

    def list_incidents(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/tprm/incidents/{incident_id}", headers=headers)

    def triage_incident(self, incident_id, headers):
        return self._request("POST", f"/tprm/incidents/{incident_id}/triage", headers=headers)

    def reopen_incident(self, incident_id, headers):
        return self._request("POST", f"/tprm/incidents/{incident_id}/reopen", headers=headers)

    # --- Remediation plans ---
    def create_remediation_plan(self, incident_id, payload, headers):
        return self._request("POST", f"/tprm/incidents/{incident_id}/remediation-plans", payload, headers)

    def list_remediation_plans(self, incident_id, headers, params=None):
        return self._request("GET", f"/tprm/incidents/{incident_id}/remediation-plans", headers=headers, params=params)

    def get_remediation_plan(self, plan_id, headers):
        return self._request("GET", f"/tprm/remediation-plans/{plan_id}", headers=headers)

    def submit_remediation_plan(self, plan_id, headers):
        return self._request("POST", f"/tprm/remediation-plans/{plan_id}/submit", headers=headers)

    def approve_remediation_plan(self, plan_id, headers):
        return self._request("POST", f"/tprm/remediation-plans/{plan_id}/approve", headers=headers)

    def reject_remediation_plan(self, plan_id, headers):
        return self._request("POST", f"/tprm/remediation-plans/{plan_id}/reject", headers=headers)

    def submit_verification(self, plan_id, payload, headers):
        return self._request("POST", f"/tprm/remediation-plans/{plan_id}/submit-verification", payload, headers)

    def verify_remediation_plan(self, plan_id, headers):
        return self._request("POST", f"/tprm/remediation-plans/{plan_id}/verify", headers=headers)

    # --- Concentration assessments ---
    def create_concentration_assessment(self, payload, headers):
        return self._request("POST", "/tprm/concentration-assessments", payload, headers)

    def list_concentration_assessments(self, headers, params=None):
        return self._request("GET", "/tprm/concentration-assessments", headers=headers, params=params)

    def get_concentration_assessment(self, assessment_id, headers):
        return self._request("GET", f"/tprm/concentration-assessments/{assessment_id}", headers=headers)

    def publish_concentration_assessment(self, assessment_id, headers):
        return self._request("POST", f"/tprm/concentration-assessments/{assessment_id}/publish", headers=headers)

    def list_concentration_buckets(self, assessment_id, headers, params=None):
        return self._request("GET", f"/tprm/concentration-assessments/{assessment_id}/buckets", headers=headers, params=params)

    # --- BCP tests ---
    def create_bcp_test(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/bcp-tests", payload, headers)

    def list_bcp_tests(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/bcp-tests", headers=headers, params=params)

    def get_bcp_test(self, bcp_id, headers):
        return self._request("GET", f"/tprm/bcp-tests/{bcp_id}", headers=headers)

    def begin_bcp_test(self, bcp_id, headers):
        return self._request("POST", f"/tprm/bcp-tests/{bcp_id}/begin", headers=headers)

    def submit_bcp_result(self, bcp_id, payload, headers):
        return self._request("POST", f"/tprm/bcp-tests/{bcp_id}/submit-result", payload, headers)

    def cancel_bcp_test(self, bcp_id, headers):
        return self._request("POST", f"/tprm/bcp-tests/{bcp_id}/cancel", headers=headers)

    # --- Audit exercises ---
    def create_audit(self, engagement_id, payload, headers):
        return self._request("POST", f"/tprm/engagements/{engagement_id}/audits", payload, headers)

    def list_audits(self, engagement_id, headers, params=None):
        return self._request("GET", f"/tprm/engagements/{engagement_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/tprm/audits/{audit_id}", headers=headers)

    def begin_audit_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/tprm/audits/{audit_id}/begin-fieldwork", headers=headers)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/tprm/audits/{audit_id}/findings", payload, headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request("GET", f"/tprm/audits/{audit_id}/findings", headers=headers, params=params)

    def list_all_audit_findings(self, headers, params=None):
        return self._request("GET", "/tprm/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/tprm/audit-findings/{finding_id}", headers=headers)

    def issue_audit_findings(self, audit_id, headers):
        return self._request("POST", f"/tprm/audits/{audit_id}/issue-findings", headers=headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/tprm/audits/{audit_id}/close", headers=headers)

    # --- Board reports ---
    def create_board_report(self, payload, headers):
        return self._request("POST", "/tprm/board-reports", payload, headers)

    def list_board_reports(self, headers, params=None):
        return self._request("GET", "/tprm/board-reports", headers=headers, params=params)

    def get_board_report(self, report_id, headers):
        return self._request("GET", f"/tprm/board-reports/{report_id}", headers=headers)

    def publish_board_report(self, report_id, headers):
        return self._request("POST", f"/tprm/board-reports/{report_id}/publish", headers=headers)


api_client = ApiClient()
