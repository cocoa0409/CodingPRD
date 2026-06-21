"""API client: one method per endpoint defined in the Home Health Nurse Dispatch PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-only) ----
    def set_clock(self, now_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"now_utc": now_utc}, headers)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patient_episodes(self, patient_id, headers, params=None):
        return self._request("GET", f"/patients/{patient_id}/episodes", headers=headers, params=params)

    # ---- Clinician ----
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def update_clinician(self, clinician_id, payload, headers):
        return self._request("PATCH", f"/clinicians/{clinician_id}", payload, headers)

    def list_clinician_visits(self, clinician_id, headers, params=None):
        return self._request("GET", f"/clinicians/{clinician_id}/visits", headers=headers, params=params)

    # ---- OASIS ----
    def create_oasis(self, payload, headers):
        return self._request("POST", "/oasis-assessments", payload, headers)

    def list_oasis(self, headers, params=None):
        return self._request("GET", "/oasis-assessments", headers=headers, params=params)

    def get_oasis(self, oasis_id, headers):
        return self._request("GET", f"/oasis-assessments/{oasis_id}", headers=headers)

    def list_oasis_recert_requests(self, oasis_id, headers, params=None):
        return self._request("GET", f"/oasis-assessments/{oasis_id}/recert-requests", headers=headers, params=params)

    # ---- PDGM rate config ----
    def create_rate_config(self, payload, headers):
        return self._request("POST", "/pdgm-rate-configs", payload, headers)

    def list_rate_configs(self, headers, params=None):
        return self._request("GET", "/pdgm-rate-configs", headers=headers, params=params)

    # ---- Episode ----
    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def activate_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/activate", {}, headers)

    def cancel_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/cancel", {}, headers)

    def finalize_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/finalize", {}, headers)

    def reopen_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/reopen", {}, headers)

    def get_episode_summary(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}/summary", headers=headers)

    def list_episode_events(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/events", headers=headers, params=params)

    def list_payment_ledger(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/payment-ledger", headers=headers, params=params)

    # ---- PlanOfCare ----
    def create_plan(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/plans-of-care", payload, headers)

    def list_plans(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/plans-of-care", headers=headers, params=params)

    # ---- Visit ----
    def create_visit(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/visits", payload, headers)

    def list_episode_visits(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def confirm_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/confirm", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def mark_missed_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/mark-missed", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    # ---- CompanionShift ----
    def create_companion_shift(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/companion-shifts", payload, headers)

    def list_companion_shifts(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/companion-shifts", headers=headers, params=params)

    def deliver_companion_shift(self, shift_id, headers):
        return self._request("POST", f"/companion-shifts/{shift_id}/deliver", {}, headers)

    def cancel_companion_shift(self, shift_id, headers):
        return self._request("POST", f"/companion-shifts/{shift_id}/cancel", {}, headers)

    # ---- MileageClaim ----
    def create_mileage_claim(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/mileage-claims", payload, headers)

    def list_mileage_claims(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/mileage-claims", headers=headers, params=params)

    def approve_mileage_claim(self, claim_id, headers):
        return self._request("POST", f"/mileage-claims/{claim_id}/approve", {}, headers)

    def reject_mileage_claim(self, claim_id, headers):
        return self._request("POST", f"/mileage-claims/{claim_id}/reject", {}, headers)

    # ---- RecertRequest ----
    def create_recert_request(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/recert-requests", payload, headers)

    def list_episode_recert_requests(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/recert-requests", headers=headers, params=params)

    def get_recert_request(self, recert_id, headers):
        return self._request("GET", f"/recert-requests/{recert_id}", headers=headers)

    def approve_recert_request(self, recert_id, headers):
        return self._request("POST", f"/recert-requests/{recert_id}/approve", {}, headers)

    def return_recert_request(self, recert_id, payload, headers):
        return self._request("POST", f"/recert-requests/{recert_id}/return", payload, headers)

    def resubmit_recert_request(self, recert_id, headers):
        return self._request("POST", f"/recert-requests/{recert_id}/resubmit", {}, headers)

    def deny_recert_request(self, recert_id, headers):
        return self._request("POST", f"/recert-requests/{recert_id}/deny", {}, headers)


api_client = ApiClient()
