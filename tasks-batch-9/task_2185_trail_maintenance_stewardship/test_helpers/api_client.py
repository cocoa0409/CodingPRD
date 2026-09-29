"""API client: one method per endpoint defined in the PRD (section 4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/stewardship"


class ApiClient(GenericApiClient):
    # --- Land managers ---
    def create_land_manager(self, payload, headers):
        return self._request("POST", f"{PREFIX}/land-managers", payload, headers)

    def get_land_manager(self, land_manager_id, headers):
        return self._request(
            "GET", f"{PREFIX}/land-managers/{land_manager_id}", headers=headers
        )

    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/volunteers/{volunteer_id}", headers=headers
        )

    # --- Trail segments ---
    def create_trail_segment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trail-segments", payload, headers)

    def get_trail_segment(self, segment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/trail-segments/{segment_id}", headers=headers
        )

    def list_trail_segments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trail-segments", headers=headers, params=params
        )

    # --- Adoption agreements ---
    def create_adoption_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/adoption-agreements", payload, headers)

    def get_adoption_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/adoption-agreements/{agreement_id}", headers=headers
        )

    def list_adoption_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/adoption-agreements", headers=headers, params=params
        )

    def submit_adoption_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/adoption-agreements/{agreement_id}/submit",
            payload or {},
            headers,
        )

    def review_adoption_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/adoption-agreements/{agreement_id}/review",
            payload,
            headers,
        )

    def activate_adoption_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/adoption-agreements/{agreement_id}/activate",
            payload or {},
            headers,
        )

    def terminate_adoption_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/adoption-agreements/{agreement_id}/terminate",
            payload,
            headers,
        )

    # --- Work plans ---
    def create_work_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-plans", payload, headers)

    def get_work_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/work-plans/{plan_id}", headers=headers)

    def list_work_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-plans", headers=headers, params=params
        )

    def submit_work_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{plan_id}/submit", payload or {}, headers
        )

    def review_work_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-plans/{plan_id}/review", payload, headers
        )

    def get_grant_match(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/work-plans/{plan_id}/grant-match",
            headers=headers,
            params=params,
        )

    # --- Condition reports ---
    def create_condition_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/condition-reports", payload, headers)

    def get_condition_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/condition-reports/{report_id}", headers=headers
        )

    def list_condition_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/condition-reports", headers=headers, params=params
        )

    def triage_condition_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/condition-reports/{report_id}/triage", payload, headers
        )

    def disposition_condition_report(self, report_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/condition-reports/{report_id}/disposition",
            payload,
            headers,
        )

    def resolve_condition_report(self, report_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/condition-reports/{report_id}/resolve",
            payload or {},
            headers,
        )

    def void_condition_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/condition-reports/{report_id}/void", payload, headers
        )

    # --- Work permits ---
    def create_work_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-permits", payload, headers)

    def get_work_permit(self, permit_id, headers):
        return self._request(
            "GET", f"{PREFIX}/work-permits/{permit_id}", headers=headers
        )

    def list_work_permits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-permits", headers=headers, params=params
        )

    def decide_work_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-permits/{permit_id}/decision", payload, headers
        )

    def revoke_work_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-permits/{permit_id}/revoke", payload, headers
        )

    # --- Work parties ---
    def create_work_party(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-parties", payload, headers)

    def get_work_party(self, party_id, headers):
        return self._request(
            "GET", f"{PREFIX}/work-parties/{party_id}", headers=headers
        )

    def list_work_parties(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-parties", headers=headers, params=params
        )

    def deliver_briefing(self, party_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/briefing", payload, headers
        )

    def confirm_work_party(self, party_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/confirm", payload or {}, headers
        )

    def start_work_party(self, party_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/start", payload or {}, headers
        )

    def complete_work_party(self, party_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/complete", payload or {}, headers
        )

    def cancel_work_party(self, party_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/cancel", payload, headers
        )

    def register_shift(self, party_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-parties/{party_id}/shifts", payload, headers
        )

    # --- Volunteer shifts ---
    def get_shift(self, shift_id, headers):
        return self._request("GET", f"{PREFIX}/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shifts/{shift_id}/check-in", payload or {}, headers
        )

    def check_out_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shifts/{shift_id}/check-out", payload or {}, headers
        )

    def withdraw_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shifts/{shift_id}/withdraw", payload or {}, headers
        )

    def review_shift_hours(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shifts/{shift_id}/hours-review", payload, headers
        )

    def certify_shift_hours(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/shifts/{shift_id}/certify", payload or {}, headers
        )

    # --- Material orders ---
    def create_material_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/material-orders", payload, headers)

    def get_material_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/material-orders/{order_id}", headers=headers
        )

    def list_material_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/material-orders", headers=headers, params=params
        )

    def submit_material_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/material-orders/{order_id}/submit", payload or {}, headers
        )

    def approve_material_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/material-orders/{order_id}/approve",
            payload or {},
            headers,
        )

    def receive_material_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/material-orders/{order_id}/receive",
            payload or {},
            headers,
        )

    def cancel_material_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/material-orders/{order_id}/cancel", payload, headers
        )

    # --- Incident reports ---
    def create_incident(self, payload, headers):
        return self._request("POST", f"{PREFIX}/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"{PREFIX}/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/incidents", headers=headers, params=params
        )

    def review_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/incidents/{incident_id}/review", payload or {}, headers
        )

    def close_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incidents/{incident_id}/close", payload, headers
        )

    # --- Administrative capabilities ---
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    def record_weather_observation(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_weather/observations", payload, headers
        )


api_client = ApiClient()
