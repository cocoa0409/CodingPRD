"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system / clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- patients ------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def update_patient(self, patient_id, payload, headers):
        return self._request("PATCH", f"/patients/{patient_id}", payload, headers)

    def get_billing_summary(self, patient_id, headers):
        return self._request(
            "GET", f"/patients/{patient_id}/billing-summary", headers=headers
        )

    # --- diagnostic panels & tests ------------------------------------------
    def create_panel(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/panels", payload, headers
        )

    def list_patient_panels(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/panels", headers=headers, params=params
        )

    def get_panel(self, panel_id, headers):
        return self._request("GET", f"/panels/{panel_id}", headers=headers)

    def add_test(self, patient_id, panel_id, payload, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/panels/{panel_id}/tests",
            payload,
            headers,
        )

    def list_panel_tests(self, panel_id, headers, params=None):
        return self._request(
            "GET", f"/panels/{panel_id}/tests", headers=headers, params=params
        )

    def finalize_panel(self, patient_id, panel_id, headers):
        return self._request(
            "POST",
            f"/patients/{patient_id}/panels/{panel_id}/finalize",
            headers=headers,
        )

    # --- immunotherapy plans -------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/immunotherapy-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/immunotherapy-plans/{plan_id}", headers=headers
        )

    def list_plans(self, headers, params=None):
        return self._request(
            "GET", "/immunotherapy-plans", headers=headers, params=params
        )

    def activate_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/activate", headers=headers
        )

    def resume_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/resume", payload, headers
        )

    def complete_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/complete", headers=headers
        )

    def discontinue_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/discontinue", headers=headers
        )

    # --- serum lots ----------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/serum-lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/serum-lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/serum-lots", headers=headers, params=params)

    def recall_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/serum-lots/{lot_id}/recall", headers=headers
        )

    # --- serum vials (mixing) ------------------------------------------------
    def mix_vial(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/vials", payload, headers
        )

    def get_vial(self, vial_id, headers):
        return self._request("GET", f"/serum-vials/{vial_id}", headers=headers)

    def list_vials(self, headers, params=None):
        return self._request("GET", "/serum-vials", headers=headers, params=params)

    # --- shot visits ---------------------------------------------------------
    def administer_shot(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/immunotherapy-plans/{plan_id}/shot-visits", payload, headers
        )

    def get_shot_visit(self, visit_id, headers):
        return self._request("GET", f"/shot-visits/{visit_id}", headers=headers)

    def list_shot_visits(self, headers, params=None):
        return self._request("GET", "/shot-visits", headers=headers, params=params)

    def release_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/shot-visits/{visit_id}/release", payload, headers
        )

    def record_reaction(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/shot-visits/{visit_id}/record-reaction", payload, headers
        )

    # --- billing -------------------------------------------------------------
    def get_billing_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/billing-entries/{entry_id}", headers=headers
        )

    def list_billing_entries(self, headers, params=None):
        return self._request(
            "GET", "/billing-entries", headers=headers, params=params
        )


api_client = ApiClient()
