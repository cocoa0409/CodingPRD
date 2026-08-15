"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- DistrictGrant ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/title-i/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/title-i/grants", headers=headers,
                             params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/title-i/grants/{grant_id}",
                             headers=headers)

    def lock_rankings(self, grant_id, headers, payload=None):
        return self._request("POST", f"/title-i/grants/{grant_id}/lock-rankings",
                             payload or {}, headers)

    def finalize_allocations(self, grant_id, headers, payload=None):
        return self._request("POST",
                             f"/title-i/grants/{grant_id}/finalize-allocations",
                             payload or {}, headers)

    def close_out(self, grant_id, headers):
        return self._request("POST", f"/title-i/grants/{grant_id}/close-out",
                             {}, headers)

    def request_carryover_waiver(self, grant_id, payload, headers):
        return self._request("POST",
                             f"/title-i/grants/{grant_id}/request-carryover-waiver",
                             payload, headers)

    def decide_carryover_waiver(self, grant_id, payload, headers):
        return self._request("POST",
                             f"/title-i/grants/{grant_id}/decide-carryover-waiver",
                             payload, headers)

    # --- School ---
    def create_school(self, payload, headers):
        return self._request("POST", "/title-i/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/title-i/schools", headers=headers,
                             params=params)

    def update_school(self, school_id, payload, headers):
        return self._request("PATCH", f"/title-i/schools/{school_id}",
                             payload, headers)

    # --- PrivateSchool ---
    def create_private_school(self, payload, headers):
        return self._request("POST", "/title-i/private-schools", payload,
                             headers)

    def list_private_schools(self, headers, params=None):
        return self._request("GET", "/title-i/private-schools", headers=headers,
                             params=params)

    # --- PovertyDataSnapshot ---
    def create_snapshot(self, payload, headers):
        return self._request("POST", "/title-i/poverty-snapshots", payload,
                             headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", "/title-i/poverty-snapshots",
                             headers=headers, params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/title-i/poverty-snapshots/{snapshot_id}",
                             headers=headers)

    def certify_snapshot(self, snapshot_id, payload, headers):
        return self._request("POST",
                             f"/title-i/poverty-snapshots/{snapshot_id}/certify",
                             payload, headers)

    # --- SchoolAllocation ---
    def list_allocations(self, headers, params=None):
        return self._request("GET", "/title-i/school-allocations",
                             headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET",
                             f"/title-i/school-allocations/{allocation_id}",
                             headers=headers)

    def certify_allocation(self, allocation_id, headers):
        return self._request("POST",
                             f"/title-i/school-allocations/{allocation_id}/certify",
                             {}, headers)

    # --- SetAside ---
    def list_set_asides(self, headers, params=None):
        return self._request("GET", "/title-i/set-asides", headers=headers,
                             params=params)

    def get_set_aside(self, set_aside_id, headers):
        return self._request("GET", f"/title-i/set-asides/{set_aside_id}",
                             headers=headers)

    def adjust_set_aside(self, set_aside_id, payload, headers):
        return self._request("POST",
                             f"/title-i/set-asides/{set_aside_id}/adjust",
                             payload, headers)

    # --- SupplementDocumentation ---
    def create_sns_document(self, payload, headers):
        return self._request("POST", "/title-i/supplement-documentation",
                             payload, headers)

    def list_sns_documents(self, headers, params=None):
        return self._request("GET", "/title-i/supplement-documentation",
                             headers=headers, params=params)

    def get_sns_document(self, doc_id, headers):
        return self._request("GET",
                             f"/title-i/supplement-documentation/{doc_id}",
                             headers=headers)

    def submit_sns_document(self, doc_id, headers):
        return self._request("POST",
                             f"/title-i/supplement-documentation/{doc_id}/submit",
                             {}, headers)

    def review_sns_document(self, doc_id, payload, headers):
        return self._request("POST",
                             f"/title-i/supplement-documentation/{doc_id}/review",
                             payload, headers)

    # --- EquitableServicesConsultation ---
    def create_consultation(self, payload, headers):
        return self._request("POST", "/title-i/equitable-services-consultations",
                             payload, headers)

    def list_consultations(self, headers, params=None):
        return self._request("GET", "/title-i/equitable-services-consultations",
                             headers=headers, params=params)

    def get_consultation(self, consultation_id, headers):
        return self._request(
            "GET",
            f"/title-i/equitable-services-consultations/{consultation_id}",
            headers=headers)

    def record_session(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/title-i/equitable-services-consultations/{consultation_id}/record-session",
            payload, headers)

    def sign_affirmation(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/title-i/equitable-services-consultations/{consultation_id}/sign-affirmation",
            payload, headers)

    def dispute_consultation(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/title-i/equitable-services-consultations/{consultation_id}/dispute",
            payload, headers)

    def file_complaint(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/title-i/equitable-services-consultations/{consultation_id}/file-complaint",
            payload, headers)

    def resolve_complaint(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"/title-i/equitable-services-consultations/{consultation_id}/resolve-complaint",
            payload, headers)

    # --- Expenditure ---
    def create_expenditure(self, payload, headers):
        return self._request("POST", "/title-i/expenditures", payload, headers)

    def list_expenditures(self, headers, params=None):
        return self._request("GET", "/title-i/expenditures", headers=headers,
                             params=params)

    def get_expenditure(self, expenditure_id, headers):
        return self._request("GET", f"/title-i/expenditures/{expenditure_id}",
                             headers=headers)

    def review_expenditure(self, expenditure_id, payload, headers):
        return self._request("POST",
                             f"/title-i/expenditures/{expenditure_id}/review",
                             payload, headers)

    def reclassify_expenditure(self, expenditure_id, payload, headers):
        return self._request("POST",
                             f"/title-i/expenditures/{expenditure_id}/reclassify",
                             payload, headers)

    # --- BudgetAmendment ---
    def create_amendment(self, payload, headers):
        return self._request("POST", "/title-i/budget-amendments", payload,
                             headers)

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/title-i/budget-amendments",
                             headers=headers, params=params)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/title-i/budget-amendments/{amendment_id}",
                             headers=headers)

    def submit_amendment(self, amendment_id, headers):
        return self._request("POST",
                             f"/title-i/budget-amendments/{amendment_id}/submit",
                             {}, headers)

    def approve_amendment(self, amendment_id, payload, headers):
        return self._request("POST",
                             f"/title-i/budget-amendments/{amendment_id}/approve",
                             payload, headers)

    def reject_amendment(self, amendment_id, payload, headers):
        return self._request("POST",
                             f"/title-i/budget-amendments/{amendment_id}/reject",
                             payload, headers)

    def void_amendment(self, amendment_id, payload, headers):
        return self._request("POST",
                             f"/title-i/budget-amendments/{amendment_id}/void",
                             payload, headers)

    # --- MonitoringVisit ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/title-i/monitoring-visits", payload,
                             headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/title-i/monitoring-visits",
                             headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/title-i/monitoring-visits/{visit_id}",
                             headers=headers)

    def start_visit(self, visit_id, headers):
        return self._request("POST",
                             f"/title-i/monitoring-visits/{visit_id}/start",
                             {}, headers)

    def issue_report(self, visit_id, headers):
        return self._request("POST",
                             f"/title-i/monitoring-visits/{visit_id}/issue-report",
                             {}, headers)

    # --- MonitoringFinding ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/title-i/monitoring-findings", payload,
                             headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/title-i/monitoring-findings",
                             headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET",
                             f"/title-i/monitoring-findings/{finding_id}",
                             headers=headers)

    def submit_cap(self, finding_id, payload, headers):
        return self._request("POST",
                             f"/title-i/monitoring-findings/{finding_id}/submit-cap",
                             payload, headers)

    def accept_cap(self, finding_id, headers):
        return self._request("POST",
                             f"/title-i/monitoring-findings/{finding_id}/accept-cap",
                             {}, headers)

    def return_cap(self, finding_id, payload, headers):
        return self._request("POST",
                             f"/title-i/monitoring-findings/{finding_id}/return-cap",
                             payload, headers)

    def close_no_action(self, finding_id, headers):
        return self._request(
            "POST",
            f"/title-i/monitoring-findings/{finding_id}/close-no-action",
            {}, headers)

    # --- Logical clock (PRD §2.10) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/title-i/_clock/set_current_utc", payload,
                             headers)


api_client = ApiClient()
