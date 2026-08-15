"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/employee-health"


class ApiClient(GenericApiClient):
    # --- Logical clock (system-level, outside the /employee-health prefix) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    # --- Pre-placement screenings ---
    def create_screening(self, employee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/employees/{employee_id}/pre-placement-screenings", payload, headers
        )

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pre-placement-screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{PREFIX}/pre-placement-screenings/{screening_id}", headers=headers)

    def complete_screening_component(self, screening_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pre-placement-screenings/{screening_id}/components/complete",
            payload, headers,
        )

    def decide_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pre-placement-screenings/{screening_id}/decide", payload, headers
        )

    # --- Titer results ---
    def create_titer_result(self, employee_id, payload, headers):
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/titer-results", payload, headers)

    def list_titer_results(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/titer-results", headers=headers, params=params)

    def get_titer_result(self, titer_id, headers):
        return self._request("GET", f"{PREFIX}/titer-results/{titer_id}", headers=headers)

    # --- Annual requirement cycles ---
    def create_cycle(self, employee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/employees/{employee_id}/annual-requirement-cycles", payload, headers
        )

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/annual-requirement-cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/annual-requirement-cycles/{cycle_id}", headers=headers)

    def record_cycle_completion(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/annual-requirement-cycles/{cycle_id}/completions", payload, headers
        )

    # --- Compliance holds ---
    def list_holds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/compliance-holds", headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"{PREFIX}/compliance-holds/{hold_id}", headers=headers)

    def release_hold(self, hold_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-holds/{hold_id}/release", payload, headers)

    # --- Exposure cases ---
    def create_exposure_case(self, employee_id, payload, headers):
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/exposure-cases", payload, headers)

    def list_exposure_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exposure-cases", headers=headers, params=params)

    def get_exposure_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/exposure-cases/{case_id}", headers=headers)

    def transition_exposure_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exposure-cases/{case_id}/transition", payload, headers)

    def record_source_testing(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exposure-cases/{case_id}/source-testing", payload, headers)

    # --- PEP regimens ---
    def list_pep_regimens(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pep-regimens", headers=headers, params=params)

    def get_pep_regimen(self, pep_id, headers):
        return self._request("GET", f"{PREFIX}/pep-regimens/{pep_id}", headers=headers)

    def transition_pep_regimen(self, pep_id, payload, headers):
        return self._request("POST", f"{PREFIX}/pep-regimens/{pep_id}/transition", payload, headers)

    # --- Serology follow-ups ---
    def list_serology_followups(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/serology-follow-ups", headers=headers, params=params)

    def get_serology_followup(self, followup_id, headers):
        return self._request("GET", f"{PREFIX}/serology-follow-ups/{followup_id}", headers=headers)

    def transition_serology_followup(self, followup_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/serology-follow-ups/{followup_id}/transition", payload, headers
        )

    # --- Work restrictions & clearances ---
    def create_work_restriction(self, employee_id, payload, headers):
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/work-restrictions", payload, headers)

    def list_work_restrictions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-restrictions", headers=headers, params=params)

    def get_work_restriction(self, restriction_id, headers):
        return self._request("GET", f"{PREFIX}/work-restrictions/{restriction_id}", headers=headers)

    def create_clearance(self, restriction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-restrictions/{restriction_id}/clearances", payload, headers
        )

    def list_clearances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/return-to-work-clearances", headers=headers, params=params)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"{PREFIX}/return-to-work-clearances/{clearance_id}", headers=headers)

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/return-to-work-clearances/{clearance_id}/decide", payload, headers
        )

    # --- Communicable events & contact tracing ---
    def create_communicable_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/communicable-events", payload, headers)

    def list_communicable_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/communicable-events", headers=headers, params=params)

    def get_communicable_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/communicable-events/{event_id}", headers=headers)

    def advance_communicable_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/communicable-events/{event_id}/advance", payload, headers
        )

    def enroll_contact(self, event_id, payload, headers):
        return self._request("POST", f"{PREFIX}/communicable-events/{event_id}/contacts", payload, headers)

    def list_exposure_contacts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exposure-contacts", headers=headers, params=params)

    def get_exposure_contact(self, contact_id, headers):
        return self._request("GET", f"{PREFIX}/exposure-contacts/{contact_id}", headers=headers)

    def report_symptom(self, contact_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-contacts/{contact_id}/report-symptom", payload, headers
        )

    def transition_exposure_contact(self, contact_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exposure-contacts/{contact_id}/transition", payload, headers
        )

    # --- Injury reports / workers' compensation ---
    def create_injury_report(self, employee_id, payload, headers):
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/injury-reports", payload, headers)

    def list_injury_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/injury-reports", headers=headers, params=params)

    def get_injury_report(self, injury_id, headers):
        return self._request("GET", f"{PREFIX}/injury-reports/{injury_id}", headers=headers)

    def transition_injury_report(self, injury_id, payload, headers):
        return self._request("POST", f"{PREFIX}/injury-reports/{injury_id}/transition", payload, headers)

    # --- Vaccination campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vaccination-campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vaccination-campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{PREFIX}/vaccination-campaigns/{campaign_id}", headers=headers)

    def transition_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/vaccination-campaigns/{campaign_id}/transition", payload, headers
        )

    def get_campaign_coverage(self, campaign_id, headers):
        return self._request(
            "GET", f"{PREFIX}/vaccination-campaigns/{campaign_id}/coverage", headers=headers
        )

    def list_participations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/campaign-participations", headers=headers, params=params)

    def get_participation(self, participation_id, headers):
        return self._request("GET", f"{PREFIX}/campaign-participations/{participation_id}", headers=headers)

    def transition_participation(self, participation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaign-participations/{participation_id}/transition", payload, headers
        )


api_client = ApiClient()
