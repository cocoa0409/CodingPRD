"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient from the framework; the base _request() handles
the HTTP envelope. All paths are flat top-level collections linked by FK fields.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ── Inspector ───────────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def suspend_inspector(self, inspector_id, headers):
        return self._request("POST", f"/inspectors/{inspector_id}/suspend",
                             headers=headers)

    # ── MitigationCrew ──────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def suspend_crew(self, crew_id, headers):
        return self._request("POST", f"/crews/{crew_id}/suspend", headers=headers)

    # ── Property ────────────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ── RadonTest ───────────────────────────────────────────────────────
    def create_radon_test(self, payload, headers):
        return self._request("POST", "/radon-tests", payload, headers)

    def get_radon_test(self, test_id, headers):
        return self._request("GET", f"/radon-tests/{test_id}", headers=headers)

    def list_radon_tests(self, headers, params=None):
        return self._request("GET", "/radon-tests", headers=headers, params=params)

    def retrieve_radon_test(self, test_id, payload, headers):
        return self._request("POST", f"/radon-tests/{test_id}/retrieve",
                             payload, headers)

    def record_result(self, test_id, headers):
        return self._request("POST", f"/radon-tests/{test_id}/record-result",
                             headers=headers)

    def void_radon_test(self, test_id, headers):
        return self._request("POST", f"/radon-tests/{test_id}/void", headers=headers)

    # ── MitigationJob ───────────────────────────────────────────────────
    def create_mitigation_job(self, payload, headers):
        return self._request("POST", "/mitigation-jobs", payload, headers)

    def get_mitigation_job(self, job_id, headers):
        return self._request("GET", f"/mitigation-jobs/{job_id}", headers=headers)

    def list_mitigation_jobs(self, headers, params=None):
        return self._request("GET", "/mitigation-jobs", headers=headers, params=params)

    def quote_job(self, job_id, headers):
        return self._request("POST", f"/mitigation-jobs/{job_id}/quote",
                             headers=headers)

    def schedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/mitigation-jobs/{job_id}/schedule",
                             payload, headers)

    def complete_install(self, job_id, headers):
        return self._request("POST", f"/mitigation-jobs/{job_id}/complete-install",
                             headers=headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/mitigation-jobs/{job_id}/cancel",
                             headers=headers)

    # ── PaymentRecord ───────────────────────────────────────────────────
    def create_payment_record(self, payload, headers):
        return self._request("POST", "/payment-records", payload, headers)

    def get_payment_record(self, record_id, headers):
        return self._request("GET", f"/payment-records/{record_id}", headers=headers)

    def list_payment_records(self, headers, params=None):
        return self._request("GET", "/payment-records", headers=headers, params=params)

    # ── Permit ──────────────────────────────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", headers=headers)

    # ── Warranty ────────────────────────────────────────────────────────
    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    def refresh_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/refresh",
                             headers=headers)

    def cancel_warranty(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/cancel",
                             payload, headers)

    def open_claim(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/open-claim",
                             headers=headers)

    # ── RetestSchedule ──────────────────────────────────────────────────
    def get_retest_schedule(self, schedule_id, headers):
        return self._request("GET", f"/retest-schedules/{schedule_id}", headers=headers)

    def list_retest_schedules(self, headers, params=None):
        return self._request("GET", "/retest-schedules", headers=headers, params=params)

    def fire_due(self, schedule_id, headers):
        return self._request("POST", f"/retest-schedules/{schedule_id}/fire-due",
                             headers=headers)

    def pause_schedule(self, schedule_id, headers):
        return self._request("POST", f"/retest-schedules/{schedule_id}/pause",
                             headers=headers)

    def resume_schedule(self, schedule_id, headers):
        return self._request("POST", f"/retest-schedules/{schedule_id}/resume",
                             headers=headers)


api_client = ApiClient()
