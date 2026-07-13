"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/landfill/facilities", payload, headers=headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/landfill/facilities/{facility_id}", headers=headers)

    # ---- Cell ----
    def create_cell(self, facility_id, payload, headers):
        return self._request("POST", f"/landfill/facilities/{facility_id}/cells", payload, headers=headers)

    def list_cells(self, facility_id, headers, params=None):
        return self._request("GET", f"/landfill/facilities/{facility_id}/cells", headers=headers, params=params)

    def get_cell(self, cell_id, headers):
        return self._request("GET", f"/landfill/cells/{cell_id}", headers=headers)

    # ---- HaulerAccount ----
    def create_hauler_account(self, payload, headers):
        return self._request("POST", "/landfill/hauler-accounts", payload, headers=headers)

    def get_hauler_account(self, hauler_id, headers):
        return self._request("GET", f"/landfill/hauler-accounts/{hauler_id}", headers=headers)

    # ---- Manifest ----
    def create_manifest(self, payload, headers):
        return self._request("POST", "/landfill/manifests", payload, headers=headers)

    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/landfill/manifests/{manifest_id}", headers=headers)

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/landfill/manifests", headers=headers, params=params)

    def submit_manifest(self, manifest_id, headers):
        return self._request("POST", f"/landfill/manifests/{manifest_id}/submit", {}, headers=headers)

    # ---- SpecialWasteApproval ----
    def create_special_waste_approval(self, manifest_id, payload, headers):
        return self._request("POST", f"/landfill/manifests/{manifest_id}/special-waste-approvals", payload, headers=headers)

    def list_special_waste_approvals(self, manifest_id, headers, params=None):
        return self._request("GET", f"/landfill/manifests/{manifest_id}/special-waste-approvals", headers=headers, params=params)

    def decide_special_waste_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/landfill/special-waste-approvals/{approval_id}/decide", payload, headers=headers)

    # ---- Ticket ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/landfill/tickets", payload, headers=headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/landfill/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/landfill/tickets", headers=headers, params=params)

    def weigh_out_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/landfill/tickets/{ticket_id}/weigh-out", payload, headers=headers)

    def inspect_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/landfill/tickets/{ticket_id}/inspect", payload, headers=headers)

    def post_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/landfill/tickets/{ticket_id}/post", payload, headers=headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/landfill/tickets/{ticket_id}/void", {}, headers=headers)

    # ---- GasReading ----
    def create_gas_reading(self, facility_id, payload, headers):
        return self._request("POST", f"/landfill/facilities/{facility_id}/gas-readings", payload, headers=headers)

    def list_gas_readings(self, facility_id, headers, params=None):
        return self._request("GET", f"/landfill/facilities/{facility_id}/gas-readings", headers=headers, params=params)

    # ---- DisposalWindow ----
    def create_disposal_window(self, cell_id, payload, headers):
        return self._request("POST", f"/landfill/cells/{cell_id}/disposal-windows", payload, headers=headers)

    def list_disposal_windows(self, cell_id, headers, params=None):
        return self._request("GET", f"/landfill/cells/{cell_id}/disposal-windows", headers=headers, params=params)

    # ---- ScaleReservation ----
    def create_scale_reservation(self, facility_id, payload, headers):
        return self._request("POST", f"/landfill/facilities/{facility_id}/scale-reservations", payload, headers=headers)

    def list_scale_reservations(self, facility_id, headers, params=None):
        return self._request("GET", f"/landfill/facilities/{facility_id}/scale-reservations", headers=headers, params=params)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/landfill/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/landfill/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/landfill/invoices", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/landfill/invoices/{invoice_id}/payments", payload, headers=headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/landfill/invoices/{invoice_id}/payments", headers=headers, params=params)


api_client = ApiClient()
