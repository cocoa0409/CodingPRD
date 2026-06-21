"""API client: one method per endpoint defined in the Auto Title Loan PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
All endpoints are mounted under /atl except the test-driving clock at /_clock.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── RegulatoryProfile ────────────────────────────────────────────────
    def create_regulatory_profile(self, payload, headers):
        return self._request("POST", "/atl/regulatory-profiles", payload, headers)

    def list_regulatory_profiles(self, headers, params=None):
        return self._request("GET", "/atl/regulatory-profiles", headers=headers, params=params)

    # ─── Borrower ─────────────────────────────────────────────────────────
    def create_borrower(self, payload, headers):
        return self._request("POST", "/atl/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/atl/borrowers/{borrower_id}", headers=headers)

    def list_borrower_vehicles(self, borrower_id, headers, params=None):
        return self._request("GET", f"/atl/borrowers/{borrower_id}/vehicles", headers=headers, params=params)

    # ─── Vehicle ──────────────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/atl/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/atl/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_appraisals(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/atl/vehicles/{vehicle_id}/appraisals", headers=headers, params=params)

    def list_vehicle_devices(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/atl/vehicles/{vehicle_id}/devices", headers=headers, params=params)

    # ─── Appraisal ────────────────────────────────────────────────────────
    def create_appraisal(self, payload, headers):
        return self._request("POST", "/atl/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/atl/appraisals/{appraisal_id}", headers=headers)

    def finalize_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/atl/appraisals/{appraisal_id}/finalize", {}, headers)

    # ─── LoanApplication ──────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/atl/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/atl/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/atl/applications/{application_id}", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/atl/applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/atl/applications/{application_id}/reject", {}, headers)

    # ─── Loan ─────────────────────────────────────────────────────────────
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/atl/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/atl/loans", headers=headers, params=params)

    def list_loan_installments(self, loan_id, headers, params=None):
        return self._request("GET", f"/atl/loans/{loan_id}/installments", headers=headers, params=params)

    def get_payoff_quote(self, loan_id, headers):
        return self._request("GET", f"/atl/loans/{loan_id}/payoff-quote", headers=headers)

    def assess_delinquency(self, loan_id, headers):
        return self._request("POST", f"/atl/loans/{loan_id}/assess-delinquency", {}, headers)

    def declare_default(self, loan_id, headers):
        return self._request("POST", f"/atl/loans/{loan_id}/declare-default", {}, headers)

    def create_payment(self, loan_id, payload, headers):
        return self._request("POST", f"/atl/loans/{loan_id}/payments", payload, headers)

    def list_loan_payments(self, loan_id, headers, params=None):
        return self._request("GET", f"/atl/loans/{loan_id}/payments", headers=headers, params=params)

    def create_renewal(self, loan_id, payload, headers):
        return self._request("POST", f"/atl/loans/{loan_id}/renewals", payload, headers)

    def list_loan_renewals(self, loan_id, headers, params=None):
        return self._request("GET", f"/atl/loans/{loan_id}/renewals", headers=headers, params=params)

    def list_loan_title_liens(self, loan_id, headers, params=None):
        return self._request("GET", f"/atl/loans/{loan_id}/title-liens", headers=headers, params=params)

    def list_loan_repossession_orders(self, loan_id, headers, params=None):
        return self._request("GET", f"/atl/loans/{loan_id}/repossession-orders", headers=headers, params=params)

    # ─── TitleLien ────────────────────────────────────────────────────────
    def get_title_lien(self, lien_id, headers):
        return self._request("GET", f"/atl/title-liens/{lien_id}", headers=headers)

    def file_title_lien(self, lien_id, payload, headers):
        return self._request("POST", f"/atl/title-liens/{lien_id}/file", payload, headers)

    # ─── RepossessionOrder ────────────────────────────────────────────────
    def create_repossession_order(self, payload, headers):
        return self._request("POST", "/atl/repossession-orders", payload, headers)

    def get_repossession_order(self, order_id, headers):
        return self._request("GET", f"/atl/repossession-orders/{order_id}", headers=headers)

    def create_assignment(self, order_id, payload, headers):
        return self._request("POST", f"/atl/repossession-orders/{order_id}/assignments", payload, headers)

    def list_assignments(self, order_id, headers, params=None):
        return self._request("GET", f"/atl/repossession-orders/{order_id}/assignments", headers=headers, params=params)

    def assign_repossession_order(self, order_id, headers):
        return self._request("POST", f"/atl/repossession-orders/{order_id}/assign", {}, headers)

    def recover_repossession_order(self, order_id, headers):
        return self._request("POST", f"/atl/repossession-orders/{order_id}/recover", {}, headers)

    def sell_repossession_order(self, order_id, payload, headers):
        return self._request("POST", f"/atl/repossession-orders/{order_id}/sell", payload, headers)

    # ─── Device / DeviceCommand ───────────────────────────────────────────
    def create_device(self, payload, headers):
        return self._request("POST", "/atl/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/atl/devices/{device_id}", headers=headers)

    def create_device_command(self, device_id, payload, headers):
        return self._request("POST", f"/atl/devices/{device_id}/commands", payload, headers)

    def list_device_commands(self, device_id, headers, params=None):
        return self._request("GET", f"/atl/devices/{device_id}/commands", headers=headers, params=params)


api_client = ApiClient()
