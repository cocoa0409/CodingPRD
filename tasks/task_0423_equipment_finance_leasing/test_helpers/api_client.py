"""API client: one method per endpoint defined in the PRD (§4).

Every path is rooted at the lessor identified by lessorId.
The base _request() method is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Lessor ──────────────────────────────────────────────────────
    def create_lessor(self, payload, headers):
        return self._request("POST", "/lessors", payload, headers)

    def get_lessor(self, lessor_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}", headers=headers)

    def set_clock(self, lessor_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/_clock/set", payload, headers)

    # ─── Vendor ──────────────────────────────────────────────────────
    def create_vendor(self, lessor_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/vendors", payload, headers)

    def get_vendor(self, lessor_id, vendor_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, lessor_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/vendors", headers=headers, params=params)

    def approve_vendor(self, lessor_id, vendor_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/vendors/{vendor_id}/approve", {}, headers)

    def suspend_vendor(self, lessor_id, vendor_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/vendors/{vendor_id}/suspend", {}, headers)

    # ─── CreditApplication ───────────────────────────────────────────
    def create_credit_application(self, lessor_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications", payload, headers)

    def get_credit_application(self, lessor_id, app_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/credit-applications/{app_id}", headers=headers)

    def list_credit_applications(self, lessor_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/credit-applications", headers=headers, params=params)

    def submit_credit_application(self, lessor_id, app_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications/{app_id}/submit", {}, headers)

    def return_credit_application(self, lessor_id, app_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications/{app_id}/return-for-info", {}, headers)

    def revise_credit_application(self, lessor_id, app_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications/{app_id}/revise", {}, headers)

    def approve_credit_application(self, lessor_id, app_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications/{app_id}/approve", payload, headers)

    def decline_credit_application(self, lessor_id, app_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/credit-applications/{app_id}/decline", {}, headers)

    # ─── Lessee ──────────────────────────────────────────────────────
    def get_lessee(self, lessor_id, lessee_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/lessees/{lessee_id}", headers=headers)

    def list_lessees(self, lessor_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/lessees", headers=headers, params=params)

    # ─── Lease ───────────────────────────────────────────────────────
    def create_lease(self, lessor_id, lessee_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/lessees/{lessee_id}/leases", payload, headers)

    def get_lease(self, lessor_id, lease_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}", headers=headers)

    def list_leases(self, lessor_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases", headers=headers, params=params)

    def book_lease(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/book", payload, headers)

    def fund_lease(self, lessor_id, lease_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/fund", {}, headers)

    def begin_end_of_term(self, lessor_id, lease_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/begin-end-of-term", {}, headers)

    def terminate_lease(self, lessor_id, lease_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/terminate", {}, headers)

    # ─── EquipmentUnit ───────────────────────────────────────────────
    def attach_equipment(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/equipment", payload, headers)

    def get_equipment(self, lessor_id, unit_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/equipment/{unit_id}", headers=headers)

    def list_lease_equipment(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/equipment", headers=headers, params=params)

    def return_equipment(self, lessor_id, unit_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/equipment/{unit_id}/return", {}, headers)

    def list_equipment(self, lessor_id, unit_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/equipment/{unit_id}/list", {}, headers)

    def record_sale(self, lessor_id, unit_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/equipment/{unit_id}/record-sale", payload, headers)

    def dispose_equipment(self, lessor_id, unit_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/equipment/{unit_id}/dispose", {}, headers)

    # ─── ScheduleLine ────────────────────────────────────────────────
    def get_schedule_line(self, lessor_id, line_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/schedule-lines/{line_id}", headers=headers)

    def list_schedule_lines(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/schedule-lines", headers=headers, params=params)

    def list_schedule_line_invoices(self, lessor_id, line_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/schedule-lines/{line_id}/invoices", headers=headers, params=params)

    # ─── Invoice ─────────────────────────────────────────────────────
    def create_invoice(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/invoices", payload, headers)

    def get_invoice(self, lessor_id, invoice_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/invoices/{invoice_id}", headers=headers)

    def list_lease_invoices(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/invoices", headers=headers, params=params)

    def void_invoice(self, lessor_id, invoice_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/invoices/{invoice_id}/void", {}, headers)

    # ─── Payment ─────────────────────────────────────────────────────
    def create_payment(self, lessor_id, invoice_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/invoices/{invoice_id}/payments", payload, headers)

    def get_payment(self, lessor_id, payment_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/payments/{payment_id}", headers=headers)

    def list_invoice_payments(self, lessor_id, invoice_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/invoices/{invoice_id}/payments", headers=headers, params=params)

    def list_lease_payments(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/payments", headers=headers, params=params)

    # ─── UccFiling ───────────────────────────────────────────────────
    def create_ucc_filing(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/ucc-filings", payload, headers)

    def get_ucc_filing(self, lessor_id, filing_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/ucc-filings/{filing_id}", headers=headers)

    def list_lease_ucc_filings(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/ucc-filings", headers=headers, params=params)

    def terminate_ucc_filing(self, lessor_id, filing_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/ucc-filings/{filing_id}/terminate", {}, headers)

    # ─── TaxAssessment ───────────────────────────────────────────────
    def create_tax_assessment(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/tax-assessments", payload, headers)

    def get_tax_assessment(self, lessor_id, assessment_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/tax-assessments/{assessment_id}", headers=headers)

    def list_lease_tax_assessments(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/tax-assessments", headers=headers, params=params)

    def remit_tax_assessment(self, lessor_id, assessment_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/tax-assessments/{assessment_id}/remit", {}, headers)

    # ─── AddOn ───────────────────────────────────────────────────────
    def create_addon(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/add-ons", payload, headers)

    def get_addon(self, lessor_id, addon_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/add-ons/{addon_id}", headers=headers)

    def list_lease_addons(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/add-ons", headers=headers, params=params)

    def list_equipment_addons(self, lessor_id, unit_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/equipment/{unit_id}/add-ons", headers=headers, params=params)

    def apply_addon(self, lessor_id, lease_id, addon_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/add-ons/{addon_id}/apply", {}, headers)

    def reject_addon(self, lessor_id, lease_id, addon_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/add-ons/{addon_id}/reject", {}, headers)

    # ─── EndOfTermElection ───────────────────────────────────────────
    def create_eot_election(self, lessor_id, lease_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/eot-elections", payload, headers)

    def get_eot_election(self, lessor_id, election_id, headers):
        return self._request("GET", f"/lessors/{lessor_id}/eot-elections/{election_id}", headers=headers)

    def list_lease_eot_elections(self, lessor_id, lease_id, headers, params=None):
        return self._request("GET", f"/lessors/{lessor_id}/leases/{lease_id}/eot-elections", headers=headers, params=params)

    def exercise_eot_election(self, lessor_id, lease_id, election_id, payload, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/eot-elections/{election_id}/exercise", payload, headers)

    def cancel_eot_election(self, lessor_id, lease_id, election_id, headers):
        return self._request("POST", f"/lessors/{lessor_id}/leases/{lease_id}/eot-elections/{election_id}/cancel", {}, headers)


api_client = ApiClient()
