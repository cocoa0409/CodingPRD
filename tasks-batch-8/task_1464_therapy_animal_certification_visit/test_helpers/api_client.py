"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving / logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/v1/_sweeps/run", None, headers)

    # --- Handlers (PRD §3.1) ---
    def create_handler(self, payload, headers):
        return self._request("POST", "/v1/handlers", payload, headers)

    def get_handler(self, handler_id, headers):
        return self._request("GET", f"/v1/handlers/{handler_id}", headers=headers)

    def list_handlers(self, headers, params=None):
        return self._request("GET", "/v1/handlers", headers=headers, params=params)

    def approve_handler(self, handler_id, headers):
        return self._request("POST", f"/v1/handlers/{handler_id}/approve", None, headers)

    def reject_handler(self, handler_id, payload, headers):
        return self._request("POST", f"/v1/handlers/{handler_id}/reject", payload, headers)

    def suspend_handler(self, handler_id, payload, headers):
        return self._request("POST", f"/v1/handlers/{handler_id}/suspend", payload, headers)

    def reinstate_handler(self, handler_id, headers):
        return self._request("POST", f"/v1/handlers/{handler_id}/reinstate", None, headers)

    def retire_handler(self, handler_id, headers):
        return self._request("POST", f"/v1/handlers/{handler_id}/retire", None, headers)

    def get_handler_recognition(self, handler_id, headers):
        return self._request("GET", f"/v1/handlers/{handler_id}/recognition", headers=headers)

    # --- Animals (PRD §3.1) ---
    def create_animal(self, payload, headers):
        return self._request("POST", "/v1/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/v1/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/v1/animals", headers=headers, params=params)

    def retire_animal(self, animal_id, headers):
        return self._request("POST", f"/v1/animals/{animal_id}/retire", None, headers)

    def place_welfare_hold(self, animal_id, payload, headers):
        return self._request("POST", f"/v1/animals/{animal_id}/welfare-hold", payload, headers)

    def release_welfare_hold(self, animal_id, headers):
        return self._request("POST", f"/v1/animals/{animal_id}/welfare-release", None, headers)

    # --- Vaccination records (PRD §3.3) ---
    def create_vaccination_record(self, payload, headers):
        return self._request("POST", "/v1/vaccination-records", payload, headers)

    def get_vaccination_record(self, record_id, headers):
        return self._request("GET", f"/v1/vaccination-records/{record_id}", headers=headers)

    def list_vaccination_records(self, headers, params=None):
        return self._request("GET", "/v1/vaccination-records", headers=headers, params=params)

    def void_vaccination_record(self, record_id, payload, headers):
        return self._request("POST", f"/v1/vaccination-records/{record_id}/void", payload, headers)

    # --- Teams (PRD §3.1) ---
    def create_team(self, payload, headers):
        return self._request("POST", "/v1/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/v1/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/v1/teams", headers=headers, params=params)

    def dissolve_team(self, team_id, headers):
        return self._request("POST", f"/v1/teams/{team_id}/dissolve", None, headers)

    # --- Evaluators (PRD §3.2) ---
    def create_evaluator(self, payload, headers):
        return self._request("POST", "/v1/evaluators", payload, headers)

    def get_evaluator(self, evaluator_id, headers):
        return self._request("GET", f"/v1/evaluators/{evaluator_id}", headers=headers)

    def list_evaluators(self, headers, params=None):
        return self._request("GET", "/v1/evaluators", headers=headers, params=params)

    def update_evaluator(self, evaluator_id, payload, headers):
        return self._request("PATCH", f"/v1/evaluators/{evaluator_id}", payload, headers)

    # --- Evaluations (PRD §3.2) ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/v1/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/v1/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/v1/evaluations", headers=headers, params=params)

    def schedule_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/v1/evaluations/{evaluation_id}/schedule", payload, headers)

    def score_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/v1/evaluations/{evaluation_id}/score", payload, headers)

    def appeal_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/v1/evaluations/{evaluation_id}/appeal", None, headers)

    def cancel_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/v1/evaluations/{evaluation_id}/cancel", None, headers)

    # --- Certifications (PRD §3.3) ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/v1/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/v1/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/v1/certifications", headers=headers, params=params)

    def activate_certification(self, certification_id, headers):
        return self._request("POST", f"/v1/certifications/{certification_id}/activate", None, headers)

    def renew_certification(self, certification_id, headers):
        return self._request("POST", f"/v1/certifications/{certification_id}/renew", None, headers)

    def suspend_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/v1/certifications/{certification_id}/suspend", payload, headers)

    def reinstate_certification(self, certification_id, headers):
        return self._request("POST", f"/v1/certifications/{certification_id}/reinstate", None, headers)

    def revoke_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/v1/certifications/{certification_id}/revoke", payload, headers)

    # --- Facilities (PRD §3.4) ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/v1/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/v1/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/v1/facilities", headers=headers, params=params)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/v1/facilities/{facility_id}", payload, headers)

    def suspend_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/v1/facilities/{facility_id}/suspend", payload, headers)

    def reinstate_facility(self, facility_id, headers):
        return self._request("POST", f"/v1/facilities/{facility_id}/reinstate", None, headers)

    def terminate_facility(self, facility_id, payload, headers):
        return self._request("POST", f"/v1/facilities/{facility_id}/terminate", payload, headers)

    def get_facility_demand_summary(self, facility_id, headers):
        return self._request("GET", f"/v1/facilities/{facility_id}/demand-summary", headers=headers)

    # --- Facility agreements (PRD §3.4) ---
    def create_facility_agreement(self, payload, headers):
        return self._request("POST", "/v1/facility-agreements", payload, headers)

    def get_facility_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/facility-agreements/{agreement_id}", headers=headers)

    def list_facility_agreements(self, headers, params=None):
        return self._request("GET", "/v1/facility-agreements", headers=headers, params=params)

    def submit_facility_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/facility-agreements/{agreement_id}/submit", None, headers)

    def sign_facility_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/facility-agreements/{agreement_id}/sign-facility", None, headers)

    def sign_program_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/facility-agreements/{agreement_id}/sign-program", None, headers)

    def terminate_facility_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/v1/facility-agreements/{agreement_id}/terminate", payload, headers)

    def withdraw_facility_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/facility-agreements/{agreement_id}/withdraw", None, headers)

    # --- Orientation records (PRD §3.4) ---
    def create_orientation_record(self, payload, headers):
        return self._request("POST", "/v1/orientation-records", payload, headers)

    def get_orientation_record(self, record_id, headers):
        return self._request("GET", f"/v1/orientation-records/{record_id}", headers=headers)

    def list_orientation_records(self, headers, params=None):
        return self._request("GET", "/v1/orientation-records", headers=headers, params=params)

    def complete_orientation_record(self, record_id, payload, headers):
        return self._request("POST", f"/v1/orientation-records/{record_id}/complete", payload, headers)

    def reassign_orientation_record(self, record_id, headers):
        return self._request("POST", f"/v1/orientation-records/{record_id}/reassign", None, headers)

    # --- Insurance policies (PRD §3.5) ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/v1/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/v1/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/v1/insurance-policies", headers=headers, params=params)

    def verify_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/v1/insurance-policies/{policy_id}/verify", None, headers)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/v1/insurance-policies/{policy_id}/cancel", None, headers)

    # --- Liability waivers (PRD §3.4) ---
    def create_liability_waiver(self, payload, headers):
        return self._request("POST", "/v1/liability-waivers", payload, headers)

    def get_liability_waiver(self, waiver_id, headers):
        return self._request("GET", f"/v1/liability-waivers/{waiver_id}", headers=headers)

    def list_liability_waivers(self, headers, params=None):
        return self._request("GET", "/v1/liability-waivers", headers=headers, params=params)

    def void_liability_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/v1/liability-waivers/{waiver_id}/void", payload, headers)

    # --- Visit requests (PRD §3.6) ---
    def create_visit_request(self, payload, headers):
        return self._request("POST", "/v1/visit-requests", payload, headers)

    def get_visit_request(self, request_id, headers):
        return self._request("GET", f"/v1/visit-requests/{request_id}", headers=headers)

    def list_visit_requests(self, headers, params=None):
        return self._request("GET", "/v1/visit-requests", headers=headers, params=params)

    def create_offer(self, request_id, payload, headers):
        return self._request("POST", f"/v1/visit-requests/{request_id}/offers", payload, headers)

    def accept_visit_request(self, request_id, headers):
        return self._request("POST", f"/v1/visit-requests/{request_id}/accept", None, headers)

    def decline_visit_request(self, request_id, headers):
        return self._request("POST", f"/v1/visit-requests/{request_id}/decline", None, headers)

    def withdraw_visit_request(self, request_id, headers):
        return self._request("POST", f"/v1/visit-requests/{request_id}/withdraw", None, headers)

    def get_candidate_teams(self, request_id, headers):
        return self._request("GET", f"/v1/visit-requests/{request_id}/candidate-teams", headers=headers)

    # --- Visits (PRD §3.7, §3.8) ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/v1/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/v1/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/v1/visits", headers=headers, params=params)

    def check_in_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/check-in", None, headers)

    def check_out_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/check-out", None, headers)

    def cancel_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/cancel", payload, headers)

    def verify_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/verify", None, headers)

    def dispute_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/dispute", payload, headers)

    def resolve_dispute(self, visit_id, payload, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/resolve-dispute", payload, headers)

    # --- Incident reports (PRD §3.9) ---
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/v1/incident-reports", payload, headers)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/v1/incident-reports/{incident_id}", headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/v1/incident-reports", headers=headers, params=params)

    def triage_incident(self, incident_id, headers):
        return self._request("POST", f"/v1/incident-reports/{incident_id}/triage", None, headers)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/v1/incident-reports/{incident_id}/escalate", None, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/v1/incident-reports/{incident_id}/resolve", payload, headers)

    # --- Hour credits (PRD §2.9, §3.8) ---
    def get_hour_credit(self, credit_id, headers):
        return self._request("GET", f"/v1/hour-credits/{credit_id}", headers=headers)

    def list_hour_credits(self, headers, params=None):
        return self._request("GET", "/v1/hour-credits", headers=headers, params=params)

    def create_hour_adjustment(self, payload, headers):
        return self._request("POST", "/v1/hour-credits/adjustments", payload, headers)


api_client = ApiClient()
