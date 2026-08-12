"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ───
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Site ───
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/api/sites/{site_id}", payload, headers)

    def recompute_posture(self, site_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/recompute_posture",
                             {}, headers)

    # ─── DustSample ───
    def create_dust_sample(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/dust-samples",
                             payload, headers)

    def list_dust_samples(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/dust-samples",
                             headers=headers, params=params)

    def get_dust_sample(self, site_id, sample_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/dust-samples/{sample_id}",
                             headers=headers)

    def update_dust_sample(self, site_id, sample_id, payload, headers):
        return self._request("PATCH", f"/api/sites/{site_id}/dust-samples/{sample_id}",
                             payload, headers)

    # ─── Collector ───
    def create_collector(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/collectors",
                             payload, headers)

    def list_collectors(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/collectors",
                             headers=headers, params=params)

    def get_collector(self, site_id, collector_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/collectors/{collector_id}",
                             headers=headers)

    def update_collector(self, site_id, collector_id, payload, headers):
        return self._request("PATCH", f"/api/sites/{site_id}/collectors/{collector_id}",
                             payload, headers)

    def commission_collector(self, site_id, collector_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/commission",
            {}, headers)

    def take_collector_out_of_service(self, site_id, collector_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/take_out_of_service",
            {}, headers)

    def return_collector_to_service(self, site_id, collector_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/return_to_service",
            {}, headers)

    def decommission_collector(self, site_id, collector_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/decommission",
            {}, headers)

    def submit_dp_reading(self, site_id, collector_id, dp_inwc, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/dp-readings",
            {"dp_inwc": dp_inwc}, headers)

    def record_filter_change(self, site_id, collector_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/collectors/{collector_id}/record_filter_change",
            {}, headers)

    # ─── DHA ───
    def create_dha(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/dhas", payload, headers)

    def list_dhas(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/dhas",
                             headers=headers, params=params)

    def get_dha(self, site_id, dha_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/dhas/{dha_id}",
                             headers=headers)

    def link_dha_sample(self, site_id, dha_id, sample_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/dhas/{dha_id}/samples/{sample_id}",
            {}, headers)

    def unlink_dha_sample(self, site_id, dha_id, sample_id, headers):
        return self._request(
            "DELETE", f"/api/sites/{site_id}/dhas/{dha_id}/samples/{sample_id}",
            headers=headers)

    def submit_dha(self, site_id, dha_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/dhas/{dha_id}/submit",
                             {}, headers)

    def approve_dha(self, site_id, dha_id, expected_site_version, headers):
        return self._request("POST", f"/api/sites/{site_id}/dhas/{dha_id}/approve",
                             {"expected_site_version": expected_site_version}, headers)

    def reject_dha(self, site_id, dha_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/dhas/{dha_id}/reject",
                             {}, headers)

    def revise_dha(self, site_id, dha_id, headers):
        return self._request("POST", f"/api/sites/{site_id}/dhas/{dha_id}/revise",
                             {}, headers)

    # ─── HousekeepingProgram ───
    def create_housekeeping_program(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/housekeeping-programs",
                             payload, headers)

    def list_housekeeping_programs(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/housekeeping-programs",
                             headers=headers, params=params)

    def get_housekeeping_program(self, site_id, program_id, headers):
        return self._request(
            "GET", f"/api/sites/{site_id}/housekeeping-programs/{program_id}",
            headers=headers)

    # ─── HousekeepingAudit ───
    def create_housekeeping_audit(self, site_id, program_id, payload, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/housekeeping-programs/{program_id}/audits",
            payload, headers)

    def list_housekeeping_audits(self, site_id, program_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/housekeeping-programs/{program_id}/audits",
            headers=headers, params=params)

    def get_housekeeping_audit(self, site_id, program_id, audit_id, headers):
        return self._request(
            "GET",
            f"/api/sites/{site_id}/housekeeping-programs/{program_id}/audits/{audit_id}",
            headers=headers)

    def record_housekeeping_audit(self, site_id, program_id, audit_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/housekeeping-programs/{program_id}/audits/{audit_id}/record",
            {}, headers)

    def skip_housekeeping_audit(self, site_id, program_id, audit_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/housekeeping-programs/{program_id}/audits/{audit_id}/skip",
            {}, headers)

    # ─── HotWorkPermit ───
    def create_hot_work_permit(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/hot-work-permits",
                             payload, headers)

    def list_hot_work_permits(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/hot-work-permits",
                             headers=headers, params=params)

    def get_hot_work_permit(self, site_id, permit_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/hot-work-permits/{permit_id}",
                             headers=headers)

    def start_hot_work_permit(self, site_id, permit_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/hot-work-permits/{permit_id}/start",
            {}, headers)

    def close_hot_work_permit(self, site_id, permit_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/hot-work-permits/{permit_id}/close",
            {}, headers)

    def void_hot_work_permit(self, site_id, permit_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/hot-work-permits/{permit_id}/void",
            {}, headers)

    # ─── Inspection ───
    def create_inspection(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/inspections",
                             payload, headers)

    def list_inspections(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/inspections",
                             headers=headers, params=params)

    def get_inspection(self, site_id, inspection_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/inspections/{inspection_id}",
                             headers=headers)

    def submit_inspection(self, site_id, inspection_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/inspections/{inspection_id}/submit",
            {}, headers)

    def accept_inspection(self, site_id, inspection_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/inspections/{inspection_id}/accept",
            {}, headers)

    def reject_inspection(self, site_id, inspection_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/inspections/{inspection_id}/reject",
            {}, headers)

    # ─── InspectionFinding ───
    def create_inspection_finding(self, site_id, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/inspections/{inspection_id}/findings",
            payload, headers)

    def list_inspection_findings(self, site_id, inspection_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/inspections/{inspection_id}/findings",
            headers=headers, params=params)

    def get_inspection_finding(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "GET",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}",
            headers=headers)

    def finding_start_work(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/start_work",
            {}, headers)

    def finding_resolve(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/resolve",
            {}, headers)

    def finding_verify(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/verify",
            {}, headers)

    def finding_reopen(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/reopen",
            {}, headers)

    def finding_dispute(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/dispute",
            {}, headers)

    def finding_withdraw(self, site_id, inspection_id, finding_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/inspections/{inspection_id}/findings/{finding_id}/withdraw",
            {}, headers)

    # ─── RetrofitProject / RetrofitLineItem ───
    def create_retrofit_project(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/retrofit-projects",
                             payload, headers)

    def list_retrofit_projects(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/retrofit-projects",
                             headers=headers, params=params)

    def get_retrofit_project(self, site_id, project_id, headers):
        return self._request(
            "GET", f"/api/sites/{site_id}/retrofit-projects/{project_id}",
            headers=headers)

    def create_line_item(self, site_id, project_id, payload, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/retrofit-projects/{project_id}/line-items",
            payload, headers)

    def list_line_items(self, site_id, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/retrofit-projects/{project_id}/line-items",
            headers=headers, params=params)

    def update_line_item(self, site_id, project_id, line_item_id, payload, headers):
        return self._request(
            "PATCH",
            f"/api/sites/{site_id}/retrofit-projects/{project_id}/line-items/{line_item_id}",
            payload, headers)

    def delete_line_item(self, site_id, project_id, line_item_id, headers):
        return self._request(
            "DELETE",
            f"/api/sites/{site_id}/retrofit-projects/{project_id}/line-items/{line_item_id}",
            headers=headers)

    def finalize_estimate(self, site_id, project_id, expected_project_version, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/retrofit-projects/{project_id}/finalize_estimate",
            {"expected_project_version": expected_project_version}, headers)

    def approve_retrofit_project(self, site_id, project_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/retrofit-projects/{project_id}/approve",
            {}, headers)

    def start_retrofit_execution(self, site_id, project_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/retrofit-projects/{project_id}/start_execution",
            {}, headers)

    def close_retrofit_project(self, site_id, project_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/retrofit-projects/{project_id}/close",
            {}, headers)

    def cancel_retrofit_project(self, site_id, project_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/retrofit-projects/{project_id}/cancel",
            {}, headers)

    # ─── Incident / CAPAAction ───
    def create_incident(self, site_id, payload, headers):
        return self._request("POST", f"/api/sites/{site_id}/incidents",
                             payload, headers)

    def list_incidents(self, site_id, headers, params=None):
        return self._request("GET", f"/api/sites/{site_id}/incidents",
                             headers=headers, params=params)

    def get_incident(self, site_id, incident_id, headers):
        return self._request("GET", f"/api/sites/{site_id}/incidents/{incident_id}",
                             headers=headers)

    def start_investigation(self, site_id, incident_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/incidents/{incident_id}/start_investigation",
            {}, headers)

    def define_capa(self, site_id, incident_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/incidents/{incident_id}/define_capa",
            {}, headers)

    def close_incident(self, site_id, incident_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/incidents/{incident_id}/close",
            {}, headers)

    def reopen_incident(self, site_id, incident_id, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/incidents/{incident_id}/reopen",
            {}, headers)

    def create_capa_action(self, site_id, incident_id, payload, headers):
        return self._request(
            "POST", f"/api/sites/{site_id}/incidents/{incident_id}/capa-actions",
            payload, headers)

    def list_capa_actions(self, site_id, incident_id, headers, params=None):
        return self._request(
            "GET", f"/api/sites/{site_id}/incidents/{incident_id}/capa-actions",
            headers=headers, params=params)

    def start_capa_action(self, site_id, incident_id, capa_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/incidents/{incident_id}/capa-actions/{capa_id}/start",
            {}, headers)

    def close_capa_action(self, site_id, incident_id, capa_id, headers):
        return self._request(
            "POST",
            f"/api/sites/{site_id}/incidents/{incident_id}/capa-actions/{capa_id}/close",
            {}, headers)


api_client = ApiClient()
