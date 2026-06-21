"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
For GET endpoints, query parameters are passed via ``params``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Surveillance Programs ───────────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/surveillance/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/surveillance/programs/{program_id}", headers=headers)

    def set_clock(self, program_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/programs/{program_id}/clock/set", payload, headers
        )

    # ── Jurisdictions ───────────────────────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/surveillance/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/surveillance/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/surveillance/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # ── Reportable Conditions ───────────────────────────────────────────
    def create_condition(self, payload, headers):
        return self._request("POST", "/surveillance/reportable-conditions", payload, headers)

    def list_conditions(self, headers, params=None):
        return self._request(
            "GET", "/surveillance/reportable-conditions", headers=headers, params=params
        )

    def get_condition(self, condition_id, headers):
        return self._request(
            "GET", f"/surveillance/reportable-conditions/{condition_id}", headers=headers
        )

    # ── Lab Results (ELR intake) ────────────────────────────────────────
    def create_lab_result(self, payload, headers):
        return self._request("POST", "/surveillance/lab-results", payload, headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/surveillance/lab-results", headers=headers, params=params)

    def get_lab_result(self, lab_result_id, headers):
        return self._request(
            "GET", f"/surveillance/lab-results/{lab_result_id}", headers=headers
        )

    def supersede_lab_result(self, lab_result_id, headers):
        return self._request(
            "POST", f"/surveillance/lab-results/{lab_result_id}/supersede", {}, headers
        )

    # ── Cases ───────────────────────────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/surveillance/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/surveillance/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/surveillance/cases/{case_id}", headers=headers)

    def interview_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/cases/{case_id}/interview", payload, headers
        )

    def classify_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/cases/{case_id}/classify", payload, headers
        )

    def close_case(self, case_id, headers):
        return self._request("POST", f"/surveillance/cases/{case_id}/close", {}, headers)

    def reopen_case(self, case_id, headers):
        return self._request("POST", f"/surveillance/cases/{case_id}/reopen", {}, headers)

    def link_lab_result(self, case_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/cases/{case_id}/link-lab-result", payload, headers
        )

    def get_case_cluster(self, case_id, headers):
        return self._request(
            "GET", f"/surveillance/cases/{case_id}/cluster", headers=headers
        )

    # ── Contacts ────────────────────────────────────────────────────────
    def create_contact(self, payload, headers):
        return self._request("POST", "/surveillance/contacts", payload, headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", "/surveillance/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/surveillance/contacts/{contact_id}", headers=headers)

    def record_qualifying_test(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/qualifying-test", payload, headers
        )

    def queue_notification(self, contact_id, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/queue-notification", {}, headers
        )

    def record_notification(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/record-notification", payload, headers
        )

    def create_monitoring_period(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/monitoring-periods", payload, headers
        )

    def list_monitoring_periods(self, headers, params=None):
        return self._request(
            "GET", "/surveillance/monitoring-periods", headers=headers, params=params
        )

    def get_monitoring_period(self, monitoring_period_id, headers):
        return self._request(
            "GET", f"/surveillance/monitoring-periods/{monitoring_period_id}", headers=headers
        )

    def start_monitoring(self, contact_id, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/start-monitoring", {}, headers
        )

    def complete_monitoring(self, contact_id, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/complete-monitoring", {}, headers
        )

    def promote_contact(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/promote", payload, headers
        )

    def void_contact(self, contact_id, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/void", {}, headers
        )

    # ── Exposure Events ─────────────────────────────────────────────────
    def create_exposure_event(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/surveillance/contacts/{contact_id}/exposure-events", payload, headers
        )

    def list_exposure_events(self, headers, params=None):
        return self._request(
            "GET", "/surveillance/exposure-events", headers=headers, params=params
        )

    def get_exposure_event(self, exposure_event_id, headers):
        return self._request(
            "GET", f"/surveillance/exposure-events/{exposure_event_id}", headers=headers
        )

    # ── Jurisdiction Transfers ──────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/surveillance/jurisdiction-transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request(
            "GET", "/surveillance/jurisdiction-transfers", headers=headers, params=params
        )

    def get_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"/surveillance/jurisdiction-transfers/{transfer_id}", headers=headers
        )

    def resolve_transfer(self, transfer_id, payload, headers):
        return self._request(
            "PUT", f"/surveillance/jurisdiction-transfers/{transfer_id}", payload, headers
        )

    # ── Outbreak Clusters ───────────────────────────────────────────────
    def list_clusters(self, headers, params=None):
        return self._request(
            "GET", "/surveillance/outbreak-clusters", headers=headers, params=params
        )

    def get_cluster(self, cluster_id, headers):
        return self._request(
            "GET", f"/surveillance/outbreak-clusters/{cluster_id}", headers=headers
        )

    def close_cluster(self, cluster_id, headers):
        return self._request(
            "POST", f"/surveillance/outbreak-clusters/{cluster_id}/close", {}, headers
        )

    # ── NEDSS Exports ───────────────────────────────────────────────────
    def create_export(self, payload, headers):
        return self._request("POST", "/surveillance/nedss-exports", payload, headers)

    def list_exports(self, headers, params=None):
        return self._request("GET", "/surveillance/nedss-exports", headers=headers, params=params)

    def get_export(self, export_id, headers):
        return self._request(
            "GET", f"/surveillance/nedss-exports/{export_id}", headers=headers
        )

    def transmit_export(self, export_id, headers):
        return self._request(
            "POST", f"/surveillance/nedss-exports/{export_id}/transmit", {}, headers
        )

    def void_export(self, export_id, headers):
        return self._request(
            "POST", f"/surveillance/nedss-exports/{export_id}/void", {}, headers
        )


api_client = ApiClient()
