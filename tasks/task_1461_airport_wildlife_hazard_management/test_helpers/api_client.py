"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/wildlife/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Airports ---
    def create_airport(self, payload, headers):
        return self._request("POST", "/wildlife/airports", payload, headers)

    def list_airports(self, headers, params=None):
        return self._request("GET", "/wildlife/airports", headers=headers, params=params)

    def get_airport(self, airport_id, headers):
        return self._request("GET", f"/wildlife/airports/{airport_id}", headers=headers)

    def get_hazard_preview(self, airport_id, as_of, headers):
        return self._request(
            "GET", f"/wildlife/airports/{airport_id}/hazard-preview",
            payload={"as_of": as_of}, headers=headers,
        )

    def get_species_seasonal_trends(self, airport_id, headers, params=None):
        return self._request(
            "GET", f"/wildlife/airports/{airport_id}/trends/species-seasonal",
            headers=headers, params=params,
        )

    def get_training_compliance(self, airport_id, headers):
        return self._request(
            "GET", f"/wildlife/airports/{airport_id}/training-compliance",
            headers=headers,
        )

    # --- Species ---
    def create_species(self, payload, headers):
        return self._request("POST", "/wildlife/species", payload, headers)

    def list_species(self, headers, params=None):
        return self._request("GET", "/wildlife/species", headers=headers, params=params)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/wildlife/species/{species_id}", headers=headers)

    # --- Biologists ---
    def create_biologist(self, payload, headers):
        return self._request("POST", "/wildlife/biologists", payload, headers)

    def list_biologists(self, headers, params=None):
        return self._request("GET", "/wildlife/biologists", headers=headers, params=params)

    def get_biologist(self, biologist_id, headers):
        return self._request("GET", f"/wildlife/biologists/{biologist_id}", headers=headers)

    # --- ATC controllers ---
    def create_atc_controller(self, payload, headers):
        return self._request("POST", "/wildlife/atc-controllers", payload, headers)

    def list_atc_controllers(self, headers, params=None):
        return self._request("GET", "/wildlife/atc-controllers", headers=headers, params=params)

    def get_atc_controller(self, controller_id, headers):
        return self._request("GET", f"/wildlife/atc-controllers/{controller_id}", headers=headers)

    # --- Regulators ---
    def create_regulator(self, payload, headers):
        return self._request("POST", "/wildlife/regulators", payload, headers)

    def get_regulator(self, regulator_id, headers):
        return self._request("GET", f"/wildlife/regulators/{regulator_id}", headers=headers)

    # --- Strike reports ---
    def create_strike_report(self, payload, headers):
        return self._request("POST", "/wildlife/strike-reports", payload, headers)

    def list_strike_reports(self, headers, params=None):
        return self._request("GET", "/wildlife/strike-reports", headers=headers, params=params)

    def get_strike_report(self, report_id, headers):
        return self._request("GET", f"/wildlife/strike-reports/{report_id}", headers=headers)

    def submit_strike_report(self, report_id, headers):
        return self._request("POST", f"/wildlife/strike-reports/{report_id}/submit", {}, headers)

    def begin_review_strike_report(self, report_id, headers):
        return self._request("POST", f"/wildlife/strike-reports/{report_id}/begin-review", {}, headers)

    def confirm_strike_report(self, report_id, payload, headers):
        return self._request("POST", f"/wildlife/strike-reports/{report_id}/confirm", payload, headers)

    def reject_strike_report(self, report_id, headers):
        return self._request("POST", f"/wildlife/strike-reports/{report_id}/reject", {}, headers)

    def return_strike_report_to_draft(self, report_id, headers):
        return self._request("POST", f"/wildlife/strike-reports/{report_id}/return-to-draft", {}, headers)

    # --- Carcass records ---
    def create_carcass_record(self, strike_report_id, payload, headers):
        return self._request(
            "POST", f"/wildlife/strike-reports/{strike_report_id}/carcass-records",
            payload, headers,
        )

    def list_carcass_records(self, headers, params=None):
        return self._request("GET", "/wildlife/carcass-records", headers=headers, params=params)

    def get_carcass_record(self, carcass_id, headers):
        return self._request("GET", f"/wildlife/carcass-records/{carcass_id}", headers=headers)

    def list_carcass_records_for_strike(self, strike_report_id, headers):
        return self._request(
            "GET", f"/wildlife/strike-reports/{strike_report_id}/carcass-records",
            headers=headers,
        )

    def send_carcass_to_lab(self, carcass_id, headers):
        return self._request("POST", f"/wildlife/carcass-records/{carcass_id}/send-to-lab", {}, headers)

    def identify_carcass(self, carcass_id, payload, headers):
        return self._request("POST", f"/wildlife/carcass-records/{carcass_id}/identify", payload, headers)

    def dispute_carcass(self, carcass_id, headers):
        return self._request("POST", f"/wildlife/carcass-records/{carcass_id}/dispute", {}, headers)

    def resolve_carcass(self, carcass_id, payload, headers):
        return self._request("POST", f"/wildlife/carcass-records/{carcass_id}/resolve", payload, headers)

    # --- Habitat assessments ---
    def create_habitat_assessment(self, payload, headers):
        return self._request("POST", "/wildlife/habitat-assessments", payload, headers)

    def list_habitat_assessments(self, headers, params=None):
        return self._request("GET", "/wildlife/habitat-assessments", headers=headers, params=params)

    def get_habitat_assessment(self, assessment_id, headers):
        return self._request("GET", f"/wildlife/habitat-assessments/{assessment_id}", headers=headers)

    # --- Mitigation actions ---
    def create_mitigation_action(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/wildlife/habitat-assessments/{assessment_id}/mitigation-actions",
            payload, headers,
        )

    def list_mitigation_actions(self, headers, params=None):
        return self._request("GET", "/wildlife/mitigation-actions", headers=headers, params=params)

    def get_mitigation_action(self, action_id, headers):
        return self._request("GET", f"/wildlife/mitigation-actions/{action_id}", headers=headers)

    def list_mitigations_for_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/wildlife/habitat-assessments/{assessment_id}/mitigation-actions",
            headers=headers,
        )

    def approve_mitigation_action(self, action_id, headers, payload=None):
        return self._request(
            "POST", f"/wildlife/mitigation-actions/{action_id}/approve",
            payload or {}, headers,
        )

    def reject_mitigation_action(self, action_id, headers):
        return self._request("POST", f"/wildlife/mitigation-actions/{action_id}/reject", {}, headers)

    def start_mitigation_work(self, action_id, headers):
        return self._request("POST", f"/wildlife/mitigation-actions/{action_id}/start-work", {}, headers)

    def verify_mitigation_action(self, action_id, headers):
        return self._request("POST", f"/wildlife/mitigation-actions/{action_id}/verify", {}, headers)

    def complete_mitigation_action(self, action_id, payload, headers):
        return self._request("POST", f"/wildlife/mitigation-actions/{action_id}/complete", payload, headers)

    def cancel_mitigation_action(self, action_id, headers):
        return self._request("POST", f"/wildlife/mitigation-actions/{action_id}/cancel", {}, headers)

    # --- Dispersal activities ---
    def create_dispersal_activity(self, payload, headers):
        return self._request("POST", "/wildlife/dispersal-activities", payload, headers)

    def list_dispersal_activities(self, headers, params=None):
        return self._request("GET", "/wildlife/dispersal-activities", headers=headers, params=params)

    def get_dispersal_activity(self, dispersal_id, headers):
        return self._request("GET", f"/wildlife/dispersal-activities/{dispersal_id}", headers=headers)

    def review_dispersal_activity(self, dispersal_id, headers):
        return self._request("POST", f"/wildlife/dispersal-activities/{dispersal_id}/review", {}, headers)

    def close_dispersal_activity(self, dispersal_id, headers):
        return self._request("POST", f"/wildlife/dispersal-activities/{dispersal_id}/close", {}, headers)

    # --- Take permits ---
    def create_take_permit(self, payload, headers):
        return self._request("POST", "/wildlife/take-permits", payload, headers)

    def list_take_permits(self, headers, params=None):
        return self._request("GET", "/wildlife/take-permits", headers=headers, params=params)

    def get_take_permit(self, permit_id, headers):
        return self._request("GET", f"/wildlife/take-permits/{permit_id}", headers=headers)

    def get_take_preview(self, permit_id, headers):
        return self._request("GET", f"/wildlife/take-permits/{permit_id}/take-preview", headers=headers)

    def submit_permit_annual_report(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/wildlife/take-permits/{permit_id}/submit-annual-report",
            payload, headers,
        )

    def revoke_take_permit(self, permit_id, headers):
        return self._request("POST", f"/wildlife/take-permits/{permit_id}/revoke", {}, headers)

    # --- Operational advisories ---
    def create_operational_advisory(self, payload, headers):
        return self._request("POST", "/wildlife/operational-advisories", payload, headers)

    def list_operational_advisories(self, headers, params=None):
        return self._request("GET", "/wildlife/operational-advisories", headers=headers, params=params)

    def get_operational_advisory(self, advisory_id, headers):
        return self._request("GET", f"/wildlife/operational-advisories/{advisory_id}", headers=headers)

    def activate_operational_advisory(self, advisory_id, payload, headers):
        return self._request(
            "POST", f"/wildlife/operational-advisories/{advisory_id}/activate",
            payload, headers,
        )

    def cancel_operational_advisory(self, advisory_id, headers):
        return self._request("POST", f"/wildlife/operational-advisories/{advisory_id}/cancel", {}, headers)

    # --- Runway closures ---
    def create_runway_closure(self, payload, headers):
        return self._request("POST", "/wildlife/runway-closures", payload, headers)

    def list_runway_closures(self, headers, params=None):
        return self._request("GET", "/wildlife/runway-closures", headers=headers, params=params)

    def get_runway_closure(self, closure_id, headers):
        return self._request("GET", f"/wildlife/runway-closures/{closure_id}", headers=headers)

    def authorize_runway_closure(self, closure_id, headers):
        return self._request("POST", f"/wildlife/runway-closures/{closure_id}/authorize", {}, headers)

    def deny_runway_closure(self, closure_id, headers):
        return self._request("POST", f"/wildlife/runway-closures/{closure_id}/deny", {}, headers)

    def release_runway_closure(self, closure_id, headers):
        return self._request("POST", f"/wildlife/runway-closures/{closure_id}/release", {}, headers)

    def cancel_runway_closure(self, closure_id, headers):
        return self._request("POST", f"/wildlife/runway-closures/{closure_id}/cancel", {}, headers)

    # --- Annual plans ---
    def create_annual_plan(self, payload, headers):
        return self._request("POST", "/wildlife/annual-plans", payload, headers)

    def list_annual_plans(self, headers, params=None):
        return self._request("GET", "/wildlife/annual-plans", headers=headers, params=params)

    def get_annual_plan(self, plan_id, headers):
        return self._request("GET", f"/wildlife/annual-plans/{plan_id}", headers=headers)

    def submit_annual_plan(self, plan_id, headers):
        return self._request("POST", f"/wildlife/annual-plans/{plan_id}/submit", {}, headers)

    def return_annual_plan_for_revision(self, plan_id, headers):
        return self._request("POST", f"/wildlife/annual-plans/{plan_id}/return-for-revision", {}, headers)

    def revise_annual_plan(self, plan_id, headers):
        return self._request("POST", f"/wildlife/annual-plans/{plan_id}/revise", {}, headers)

    def approve_annual_plan(self, plan_id, headers):
        return self._request("POST", f"/wildlife/annual-plans/{plan_id}/approve", {}, headers)

    def publish_annual_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/wildlife/annual-plans/{plan_id}/publish", payload, headers)

    # --- Training records ---
    def create_training_record(self, payload, headers):
        return self._request("POST", "/wildlife/training-records", payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/wildlife/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/wildlife/training-records/{record_id}", headers=headers)

    def revoke_training_record(self, record_id, headers):
        return self._request("POST", f"/wildlife/training-records/{record_id}/revoke", {}, headers)


api_client = ApiClient()
