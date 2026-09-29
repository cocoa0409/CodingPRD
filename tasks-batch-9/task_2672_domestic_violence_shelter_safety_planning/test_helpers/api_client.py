"""API client: one method per endpoint defined in the PRD endpoint table."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Domestic Violence Shelter API."""

    # --- Staff members ------------------------------------------------------

    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_member_id, headers):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def create_wellness_check(self, staff_member_id, payload, headers):
        return self._request(
            "POST", f"/staff-members/{staff_member_id}/wellness-checks", payload, headers
        )

    def list_wellness_checks(self, staff_member_id, headers, params=None):
        return self._request(
            "GET",
            f"/staff-members/{staff_member_id}/wellness-checks",
            headers=headers,
            params=params,
        )

    # --- Clients ------------------------------------------------------------

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def change_consent(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/consent", payload, headers)

    # --- Hotline calls ------------------------------------------------------

    def create_hotline_call(self, payload, headers):
        return self._request("POST", "/hotline-calls", payload, headers)

    def get_hotline_call(self, call_id, headers):
        return self._request("GET", f"/hotline-calls/{call_id}", headers=headers)

    def list_hotline_calls(self, headers, params=None):
        return self._request("GET", "/hotline-calls", headers=headers, params=params)

    def create_risk_assessment(self, call_id, payload, headers):
        return self._request(
            "POST", f"/hotline-calls/{call_id}/risk-assessments", payload, headers
        )

    def list_risk_assessments(self, call_id, headers, params=None):
        return self._request(
            "GET", f"/hotline-calls/{call_id}/risk-assessments", headers=headers, params=params
        )

    def dispose_hotline_call(self, call_id, payload, headers):
        return self._request("POST", f"/hotline-calls/{call_id}/dispose", payload, headers)

    # --- Safety plans -------------------------------------------------------

    def create_safety_plan(self, payload, headers):
        return self._request("POST", "/safety-plans", payload, headers)

    def get_safety_plan(self, plan_id, headers):
        return self._request("GET", f"/safety-plans/{plan_id}", headers=headers)

    def list_safety_plans(self, headers, params=None):
        return self._request("GET", "/safety-plans", headers=headers, params=params)

    def create_plan_component(self, plan_id, payload, headers):
        return self._request("POST", f"/safety-plans/{plan_id}/components", payload, headers)

    def list_plan_components(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/safety-plans/{plan_id}/components", headers=headers, params=params
        )

    def implement_plan_component(self, plan_id, component_id, headers, payload=None):
        return self._request(
            "POST",
            f"/safety-plans/{plan_id}/components/{component_id}/implement",
            payload if payload is not None else {},
            headers,
        )

    def activate_safety_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/safety-plans/{plan_id}/activate", payload if payload is not None else {}, headers
        )

    def revise_safety_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/safety-plans/{plan_id}/revise", payload if payload is not None else {}, headers
        )

    def reactivate_safety_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/safety-plans/{plan_id}/reactivate", payload if payload is not None else {}, headers
        )

    # --- Shelters and units -------------------------------------------------

    def create_shelter(self, payload, headers):
        return self._request("POST", "/shelters", payload, headers)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}", headers=headers)

    def create_shelter_unit(self, shelter_id, payload, headers):
        return self._request("POST", f"/shelters/{shelter_id}/units", payload, headers)

    def list_shelter_units(self, shelter_id, headers, params=None):
        return self._request(
            "GET", f"/shelters/{shelter_id}/units", headers=headers, params=params
        )

    def get_shelter_unit(self, unit_id, headers):
        return self._request("GET", f"/shelter-units/{unit_id}", headers=headers)

    # --- Screening requests -------------------------------------------------

    def create_screening_request(self, payload, headers):
        return self._request("POST", "/screening-requests", payload, headers)

    def get_screening_request(self, request_id, headers):
        return self._request("GET", f"/screening-requests/{request_id}", headers=headers)

    def list_screening_requests(self, headers, params=None):
        return self._request("GET", "/screening-requests", headers=headers, params=params)

    def decide_screening_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/screening-requests/{request_id}/decide", payload, headers
        )

    # --- Shelter admissions -------------------------------------------------

    def create_shelter_admission(self, payload, headers):
        return self._request("POST", "/shelter-admissions", payload, headers)

    def get_shelter_admission(self, admission_id, headers):
        return self._request("GET", f"/shelter-admissions/{admission_id}", headers=headers)

    def list_shelter_admissions(self, headers, params=None):
        return self._request("GET", "/shelter-admissions", headers=headers, params=params)

    def check_in_admission(self, admission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/shelter-admissions/{admission_id}/check-in",
            payload if payload is not None else {},
            headers,
        )

    def exit_admission(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/shelter-admissions/{admission_id}/exit", payload, headers
        )

    def cancel_admission(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/shelter-admissions/{admission_id}/cancel", payload, headers
        )

    def report_location_compromise(self, admission_id, payload, headers):
        return self._request(
            "POST",
            f"/shelter-admissions/{admission_id}/report-location-compromise",
            payload,
            headers,
        )

    def complete_relocation(self, admission_id, payload, headers):
        return self._request(
            "POST",
            f"/shelter-admissions/{admission_id}/complete-relocation",
            payload,
            headers,
        )

    # --- Protective order cases ---------------------------------------------

    def create_protective_order_case(self, payload, headers):
        return self._request("POST", "/protective-order-cases", payload, headers)

    def get_protective_order_case(self, case_id, headers):
        return self._request("GET", f"/protective-order-cases/{case_id}", headers=headers)

    def list_protective_order_cases(self, headers, params=None):
        return self._request("GET", "/protective-order-cases", headers=headers, params=params)

    def file_protective_order_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/protective-order-cases/{case_id}/file", payload, headers
        )

    def record_protective_order_outcome(self, case_id, payload, headers):
        return self._request(
            "POST", f"/protective-order-cases/{case_id}/record-outcome", payload, headers
        )

    # --- Landlord partners and housing referrals ----------------------------

    def create_landlord_partner(self, payload, headers):
        return self._request("POST", "/landlord-partners", payload, headers)

    def get_landlord_partner(self, partner_id, headers):
        return self._request("GET", f"/landlord-partners/{partner_id}", headers=headers)

    def create_housing_referral(self, payload, headers):
        return self._request("POST", "/housing-referrals", payload, headers)

    def get_housing_referral(self, referral_id, headers):
        return self._request("GET", f"/housing-referrals/{referral_id}", headers=headers)

    def list_housing_referrals(self, headers, params=None):
        return self._request("GET", "/housing-referrals", headers=headers, params=params)

    def match_housing_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/housing-referrals/{referral_id}/match", payload, headers
        )

    def withdraw_housing_match(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/housing-referrals/{referral_id}/withdraw-match", payload, headers
        )

    def lease_housing_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/housing-referrals/{referral_id}/lease", payload, headers
        )

    # --- Disclosure events --------------------------------------------------

    def create_disclosure_event(self, payload, headers):
        return self._request("POST", "/disclosure-events", payload, headers)

    def get_disclosure_event(self, event_id, headers):
        return self._request("GET", f"/disclosure-events/{event_id}", headers=headers)

    def list_disclosure_events(self, headers, params=None):
        return self._request("GET", "/disclosure-events", headers=headers, params=params)

    def decide_disclosure_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-events/{event_id}/decide", payload, headers
        )

    # --- Logical clock ------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
