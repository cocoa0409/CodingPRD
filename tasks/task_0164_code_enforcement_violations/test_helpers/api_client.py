"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- Fee schedules ----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ---- Owners ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ---- Properties ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- Cases ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def close_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/cases/{case_id}/close", payload or {}, headers)

    def post_payment(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/payments", payload, headers)

    # ---- Complaints ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_case_complaints(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/complaints", headers=headers, params=params
        )

    def triage_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST", f"/complaints/{complaint_id}/triage", payload or {}, headers
        )

    def dismiss_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST", f"/complaints/{complaint_id}/dismiss", payload or {}, headers
        )

    # ---- Inspections ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def submit_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/submit", payload, headers
        )

    # ---- Violation notices ----
    def create_notice(self, payload, headers):
        return self._request("POST", "/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def contest_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/notices/{notice_id}/contest", payload, headers
        )

    # ---- Reinspections ----
    def create_reinspection(self, payload, headers):
        return self._request("POST", "/reinspections", payload, headers)

    def list_notice_reinspections(self, notice_id, headers, params=None):
        return self._request(
            "GET", f"/notices/{notice_id}/reinspections", headers=headers, params=params
        )

    def record_reinspection_result(self, reinspection_id, payload, headers):
        return self._request(
            "POST", f"/reinspections/{reinspection_id}/result", payload, headers
        )

    # ---- Fines ----
    def list_notice_fines(self, notice_id, headers, params=None):
        return self._request(
            "GET", f"/notices/{notice_id}/fines", headers=headers, params=params
        )

    # ---- Hearings ----
    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_notice_hearings(self, notice_id, headers, params=None):
        return self._request(
            "GET", f"/notices/{notice_id}/hearings", headers=headers, params=params
        )

    def decide_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/decide", payload, headers
        )

    def continue_hearing(self, hearing_id, headers, payload=None):
        return self._request(
            "POST", f"/hearings/{hearing_id}/continue", payload or {}, headers
        )

    def reschedule_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/reschedule", payload, headers
        )

    # ---- Abatement orders ----
    def create_abatement_order(self, payload, headers):
        return self._request("POST", "/abatement-orders", payload, headers)

    def get_abatement_order(self, order_id, headers):
        return self._request("GET", f"/abatement-orders/{order_id}", headers=headers)

    def list_case_abatement_orders(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/abatement-orders", headers=headers, params=params
        )

    def start_abatement_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/abatement-orders/{order_id}/start", payload or {}, headers
        )

    def complete_abatement_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/abatement-orders/{order_id}/complete", payload, headers
        )

    def cancel_abatement_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/abatement-orders/{order_id}/cancel", payload or {}, headers
        )

    # ---- Liens ----
    def create_lien(self, payload, headers):
        return self._request("POST", "/liens", payload, headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/liens", headers=headers, params=params)

    def release_lien(self, lien_id, headers, payload=None):
        return self._request(
            "POST", f"/liens/{lien_id}/release", payload or {}, headers
        )

    def foreclose_lien(self, lien_id, headers, payload=None):
        return self._request(
            "POST", f"/liens/{lien_id}/foreclose", payload or {}, headers
        )


api_client = ApiClient()
