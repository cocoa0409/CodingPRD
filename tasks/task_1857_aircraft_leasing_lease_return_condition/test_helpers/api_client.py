"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- aircraft, documents, transition slots ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/leasing/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/leasing/aircraft/{aircraft_id}", headers=headers)

    def create_document(self, aircraft_id, payload, headers):
        return self._request("POST", f"/leasing/aircraft/{aircraft_id}/documents", payload, headers)

    def list_documents(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/leasing/aircraft/{aircraft_id}/documents", headers=headers, params=params)

    def review_document(self, document_id, payload, headers):
        return self._request("POST", f"/leasing/documents/{document_id}/review", payload, headers)

    def create_transition_slot(self, aircraft_id, payload, headers):
        return self._request("POST", f"/leasing/aircraft/{aircraft_id}/transition-slots", payload, headers)

    def list_transition_slots(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/leasing/aircraft/{aircraft_id}/transition-slots", headers=headers, params=params)

    def advance_transition_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/leasing/transition-slots/{slot_id}/advance", payload, headers)

    # --- lessees & inspectors ---
    def create_lessee(self, payload, headers):
        return self._request("POST", "/leasing/lessees", payload, headers)

    def list_lessees(self, headers, params=None):
        return self._request("GET", "/leasing/lessees", headers=headers, params=params)

    def get_lessee(self, lessee_id, headers):
        return self._request("GET", f"/leasing/lessees/{lessee_id}", headers=headers)

    def set_lessee_status(self, lessee_id, payload, headers):
        return self._request("POST", f"/leasing/lessees/{lessee_id}/status", payload, headers)

    def list_lessee_novation_requests(self, lessee_id, headers, params=None):
        return self._request("GET", f"/leasing/lessees/{lessee_id}/novation-requests", headers=headers, params=params)

    def create_inspector(self, payload, headers):
        return self._request("POST", "/leasing/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/leasing/inspectors/{inspector_id}", headers=headers)

    def list_inspector_bookings(self, inspector_id, headers, params=None):
        return self._request("GET", f"/leasing/inspectors/{inspector_id}/inspection-bookings", headers=headers, params=params)

    # --- leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leasing/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leasing/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leasing/leases/{lease_id}", headers=headers)

    def amend_lease(self, lease_id, payload, headers):
        return self._request("PATCH", f"/leasing/leases/{lease_id}", payload, headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/activate", {}, headers)

    def initiate_return(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/initiate-return", {}, headers)

    def abort_return(self, lease_id, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/abort-return", {}, headers)

    def get_monthly_charge(self, lease_id, month, headers):
        return self._request("GET", f"/leasing/leases/{lease_id}/monthly-charge", headers=headers, params={"month": month})

    # --- utilization reports ---
    def create_utilization_report(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/utilization-reports", payload, headers)

    def list_utilization_reports(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/utilization-reports", headers=headers, params=params)

    def review_utilization_report(self, report_id, payload, headers):
        return self._request("POST", f"/leasing/utilization-reports/{report_id}/review", payload, headers)

    def revise_utilization_report(self, report_id, payload, headers):
        return self._request("POST", f"/leasing/utilization-reports/{report_id}/revise", payload, headers)

    def void_utilization_report(self, report_id, headers):
        return self._request("POST", f"/leasing/utilization-reports/{report_id}/void", {}, headers)

    # --- reserve claims ---
    def create_reserve_claim(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/reserve-claims", payload, headers)

    def list_reserve_claims(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/reserve-claims", headers=headers, params=params)

    def decide_reserve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/leasing/reserve-claims/{claim_id}/decide", payload, headers)

    def pay_reserve_claim(self, claim_id, headers):
        return self._request("POST", f"/leasing/reserve-claims/{claim_id}/pay", {}, headers)

    def reverse_claim_payment(self, claim_id, headers):
        return self._request("POST", f"/leasing/reserve-claims/{claim_id}/reverse-payment", {}, headers)

    # --- return cases, bookings, checklist ---
    def list_return_cases(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/return-cases", headers=headers, params=params)

    def get_return_case(self, return_case_id, headers):
        return self._request("GET", f"/leasing/return-cases/{return_case_id}", headers=headers)

    def advance_return_case(self, return_case_id, payload, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/advance", payload, headers)

    def create_inspection_booking(self, return_case_id, payload, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/inspection-bookings", payload, headers)

    def list_inspection_bookings(self, return_case_id, headers, params=None):
        return self._request("GET", f"/leasing/return-cases/{return_case_id}/inspection-bookings", headers=headers, params=params)

    def list_checklist_items(self, return_case_id, headers, params=None):
        return self._request("GET", f"/leasing/return-cases/{return_case_id}/checklist-items", headers=headers, params=params)

    def inspect_checklist_item(self, item_id, payload, headers):
        return self._request("POST", f"/leasing/checklist-items/{item_id}/inspect", payload, headers)

    def waive_checklist_item(self, item_id, payload, headers):
        return self._request("POST", f"/leasing/checklist-items/{item_id}/waive", payload, headers)

    def rectify_checklist_item(self, item_id, headers):
        return self._request("POST", f"/leasing/checklist-items/{item_id}/rectify", {}, headers)

    def create_proposal(self, return_case_id, payload, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/proposals", payload, headers)

    def agree_return_case(self, return_case_id, payload, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/agree", payload, headers)

    def request_reinspection(self, return_case_id, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/request-reinspection", {}, headers)

    def settle_return_case(self, return_case_id, headers):
        return self._request("POST", f"/leasing/return-cases/{return_case_id}/settle", {}, headers)

    # --- novation / sublease ---
    def create_novation_request(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/novation-requests", payload, headers)

    def list_novation_requests(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/novation-requests", headers=headers, params=params)

    def review_novation_request(self, request_id, payload, headers):
        return self._request("POST", f"/leasing/novation-requests/{request_id}/review", payload, headers)

    # --- default & repossession ---
    def create_default_case(self, lease_id, payload, headers):
        return self._request("POST", f"/leasing/leases/{lease_id}/default-cases", payload, headers)

    def list_default_cases(self, lease_id, headers, params=None):
        return self._request("GET", f"/leasing/leases/{lease_id}/default-cases", headers=headers, params=params)

    def cure_default_case(self, case_id, headers):
        return self._request("POST", f"/leasing/default-cases/{case_id}/cure", {}, headers)

    def authorize_repossession(self, case_id, headers):
        return self._request("POST", f"/leasing/default-cases/{case_id}/authorize-repossession", {}, headers)

    def execute_repossession(self, case_id, headers):
        return self._request("POST", f"/leasing/default-cases/{case_id}/execute-repossession", {}, headers)

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/leasing/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
