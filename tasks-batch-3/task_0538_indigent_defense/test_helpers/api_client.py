"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- DefenderOffice ----
    def create_defender_office(self, payload, headers):
        return self._request("POST", "/defender-offices", payload, headers)

    def get_defender_office(self, office_id, headers):
        return self._request("GET", f"/defender-offices/{office_id}", headers=headers)

    # ---- Attorney ----
    def create_attorney(self, payload, headers):
        return self._request("POST", "/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request("GET", f"/attorneys/{attorney_id}", headers=headers)

    def list_attorneys(self, headers, params=None):
        return self._request("GET", "/attorneys", headers=headers, params=params)

    def suspend_attorney(self, attorney_id, headers):
        return self._request("POST", f"/attorneys/{attorney_id}/suspend", {}, headers)

    def reactivate_attorney(self, attorney_id, headers):
        return self._request("POST", f"/attorneys/{attorney_id}/reactivate", {}, headers)

    # ---- Courtroom ----
    def create_courtroom(self, payload, headers):
        return self._request("POST", "/courtrooms", payload, headers)

    def get_courtroom(self, courtroom_id, headers):
        return self._request("GET", f"/courtrooms/{courtroom_id}", headers=headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def reassign_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reassign", payload, headers)

    def adjust_weight(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/adjust-weight", payload, headers)

    def dispose_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/dispose", payload, headers)

    # ---- FinancialScreening ----
    def create_financial_screening(self, payload, headers):
        return self._request("POST", "/financial-screenings", payload, headers)

    def get_financial_screening(self, screening_id, headers):
        return self._request("GET", f"/financial-screenings/{screening_id}", headers=headers)

    def list_financial_screenings(self, headers, params=None):
        return self._request("GET", "/financial-screenings", headers=headers, params=params)

    def decide_screening(self, screening_id, headers):
        return self._request("POST", f"/financial-screenings/{screening_id}/decide", {}, headers)

    # ---- ConflictCheck ----
    def create_conflict_check(self, payload, headers):
        return self._request("POST", "/conflict-checks", payload, headers)

    def get_conflict_check(self, conflict_check_id, headers):
        return self._request("GET", f"/conflict-checks/{conflict_check_id}", headers=headers)

    def list_conflict_checks(self, headers, params=None):
        return self._request("GET", "/conflict-checks", headers=headers, params=params)

    # ---- Assignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    # ---- CourtEvent ----
    def create_court_event(self, payload, headers):
        return self._request("POST", "/court-events", payload, headers)

    def get_court_event(self, court_event_id, headers):
        return self._request("GET", f"/court-events/{court_event_id}", headers=headers)

    def list_court_events(self, headers, params=None):
        return self._request("GET", "/court-events", headers=headers, params=params)

    def vacate_court_event(self, court_event_id, headers):
        return self._request("POST", f"/court-events/{court_event_id}/vacate", {}, headers)

    # ---- ServiceRequest ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, service_request_id, headers):
        return self._request("GET", f"/service-requests/{service_request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def approve_service_request(self, service_request_id, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/approve", {}, headers)

    def complete_service_request(self, service_request_id, headers):
        return self._request("POST", f"/service-requests/{service_request_id}/complete", {}, headers)

    # ---- Voucher ----
    def create_voucher(self, payload, headers):
        return self._request("POST", "/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def submit_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/submit", {}, headers)

    def approve_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/approve", {}, headers)

    def reject_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/reject", {}, headers)

    def revise_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/revise", {}, headers)

    def void_voucher(self, voucher_id, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/void", {}, headers)

    # ---- RecoupmentOrder ----
    def get_recoupment_order(self, recoupment_order_id, headers):
        return self._request("GET", f"/recoupment-orders/{recoupment_order_id}", headers=headers)

    def list_recoupment_orders(self, headers, params=None):
        return self._request("GET", "/recoupment-orders", headers=headers, params=params)

    def collect_recoupment(self, recoupment_order_id, payload, headers):
        return self._request("POST", f"/recoupment-orders/{recoupment_order_id}/collect", payload, headers)

    def waive_recoupment(self, recoupment_order_id, headers):
        return self._request("POST", f"/recoupment-orders/{recoupment_order_id}/waive", {}, headers)

    # ---- Logical clock (test driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
