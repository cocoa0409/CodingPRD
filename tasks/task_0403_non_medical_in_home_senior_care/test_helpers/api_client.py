"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Agency ----
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    # ---- Caregiver ----
    def create_caregiver(self, payload, headers):
        return self._request("POST", "/caregivers", payload, headers)

    def list_caregivers(self, headers, params=None):
        return self._request("GET", "/caregivers", headers=headers, params=params)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"/caregivers/{caregiver_id}", headers=headers)

    def transition_caregiver(self, caregiver_id, payload, headers):
        return self._request(
            "POST", f"/caregivers/{caregiver_id}/transition", payload, headers
        )

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def transition_client(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/transition", payload, headers
        )

    # ---- CarePlan / CareTask ----
    def create_care_plan(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/care-plans", payload, headers
        )

    def list_care_plans(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/care-plans", headers=headers, params=params
        )

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}", headers=headers)

    def transition_care_plan(self, care_plan_id, payload, headers):
        return self._request(
            "POST", f"/care-plans/{care_plan_id}/transition", payload, headers
        )

    def create_care_task(self, care_plan_id, payload, headers):
        return self._request(
            "POST", f"/care-plans/{care_plan_id}/tasks", payload, headers
        )

    def list_care_tasks(self, care_plan_id, headers, params=None):
        return self._request(
            "GET", f"/care-plans/{care_plan_id}/tasks", headers=headers, params=params
        )

    def delete_care_task(self, care_plan_id, task_id, headers):
        return self._request(
            "DELETE", f"/care-plans/{care_plan_id}/tasks/{task_id}", headers=headers
        )

    # ---- CaregiverMatch ----
    def create_match(self, payload, headers):
        return self._request("POST", "/matches", payload, headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def transition_match(self, match_id, payload, headers):
        return self._request(
            "POST", f"/matches/{match_id}/transition", payload, headers
        )

    # ---- Visit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def clock_in(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/clock-in", payload, headers)

    def clock_out(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/clock-out", payload, headers)

    def transition_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/transition", payload, headers
        )

    # ---- MileageEntry ----
    def create_mileage(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/mileage", payload, headers)

    def list_mileage(self, visit_id, headers, params=None):
        return self._request(
            "GET", f"/visits/{visit_id}/mileage", headers=headers, params=params
        )

    def void_mileage(self, mileage_id, headers):
        return self._request("POST", f"/mileage/{mileage_id}/void", {}, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/finalize", {}, headers
        )

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/transition", payload, headers
        )

    # ---- LtcClaim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/ltc-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/ltc-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ltc-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/ltc-claims/{claim_id}/submit", {}, headers)

    def transition_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/ltc-claims/{claim_id}/transition", payload, headers
        )


api_client = ApiClient()
