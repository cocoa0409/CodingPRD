"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/freight/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Shippers
    # ------------------------------------------------------------------
    def create_shipper(self, payload, headers):
        return self._request("POST", "/freight/shippers", payload, headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", "/freight/shippers", headers=headers, params=params)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/freight/shippers/{shipper_id}", headers=headers)

    def patch_shipper_credit_terms(self, shipper_id, payload, headers):
        return self._request("PATCH", f"/freight/shippers/{shipper_id}/credit-terms",
                             payload, headers)

    def suspend_shipper(self, shipper_id, headers):
        return self._request("POST", f"/freight/shippers/{shipper_id}/suspend", {}, headers)

    def reinstate_shipper(self, shipper_id, headers):
        return self._request("POST", f"/freight/shippers/{shipper_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Tariffs
    # ------------------------------------------------------------------
    def create_tariff(self, payload, headers):
        return self._request("POST", "/freight/tariffs", payload, headers)

    def list_tariffs(self, headers, params=None):
        return self._request("GET", "/freight/tariffs", headers=headers, params=params)

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"/freight/tariffs/{tariff_id}", headers=headers)

    def publish_tariff(self, tariff_id, headers, payload=None):
        return self._request("POST", f"/freight/tariffs/{tariff_id}/publish",
                             payload or {}, headers)

    def retire_tariff(self, tariff_id, headers):
        return self._request("POST", f"/freight/tariffs/{tariff_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Carrier contracts
    # ------------------------------------------------------------------
    def create_carrier_contract(self, payload, headers):
        return self._request("POST", "/freight/carrier-contracts", payload, headers)

    def list_carrier_contracts(self, headers, params=None):
        return self._request("GET", "/freight/carrier-contracts", headers=headers, params=params)

    def get_carrier_contract(self, contract_id, headers):
        return self._request("GET", f"/freight/carrier-contracts/{contract_id}",
                             headers=headers)

    def activate_carrier_contract(self, contract_id, headers):
        return self._request("POST", f"/freight/carrier-contracts/{contract_id}/activate",
                             {}, headers)

    def suspend_carrier_contract(self, contract_id, headers):
        return self._request("POST", f"/freight/carrier-contracts/{contract_id}/suspend",
                             {}, headers)

    def resume_carrier_contract(self, contract_id, headers):
        return self._request("POST", f"/freight/carrier-contracts/{contract_id}/resume",
                             {}, headers)

    # ------------------------------------------------------------------
    # Surety bonds
    # ------------------------------------------------------------------
    def create_surety_bond(self, payload, headers):
        return self._request("POST", "/freight/surety-bonds", payload, headers)

    def list_surety_bonds(self, headers, params=None):
        return self._request("GET", "/freight/surety-bonds", headers=headers, params=params)

    def get_surety_bond(self, bond_id, headers):
        return self._request("GET", f"/freight/surety-bonds/{bond_id}", headers=headers)

    def activate_surety_bond(self, bond_id, headers):
        return self._request("POST", f"/freight/surety-bonds/{bond_id}/activate", {}, headers)

    # ------------------------------------------------------------------
    # Voyages
    # ------------------------------------------------------------------
    def create_voyage(self, payload, headers):
        return self._request("POST", "/freight/voyages", payload, headers)

    def list_voyages(self, headers, params=None):
        return self._request("GET", "/freight/voyages", headers=headers, params=params)

    def get_voyage(self, voyage_id, headers):
        return self._request("GET", f"/freight/voyages/{voyage_id}", headers=headers)

    def open_voyage_for_booking(self, voyage_id, headers):
        return self._request("POST", f"/freight/voyages/{voyage_id}/open-for-booking",
                             {}, headers)

    def depart_voyage(self, voyage_id, headers):
        return self._request("POST", f"/freight/voyages/{voyage_id}/depart", {}, headers)

    def arrive_voyage(self, voyage_id, headers):
        return self._request("POST", f"/freight/voyages/{voyage_id}/arrive", {}, headers)

    def close_voyage(self, voyage_id, headers):
        return self._request("POST", f"/freight/voyages/{voyage_id}/close", {}, headers)

    def blank_voyage(self, voyage_id, headers):
        return self._request("POST", f"/freight/voyages/{voyage_id}/blank", {}, headers)

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/freight/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/freight/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/freight/bookings/{booking_id}", headers=headers)

    def amend_booking(self, booking_id, payload, headers):
        return self._request("PATCH", f"/freight/bookings/{booking_id}", payload, headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/freight/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/freight/bookings/{booking_id}/cancel",
                             payload, headers)

    def roll_booking(self, booking_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/freight/bookings/{booking_id}/roll",
                             payload, headers)

    def rebook_booking(self, booking_id, new_voyage_id, headers):
        return self._request("POST", f"/freight/bookings/{booking_id}/rebook",
                             {"new_voyage_id": new_voyage_id}, headers)

    def deliver_booking(self, booking_id, headers):
        return self._request("POST", f"/freight/bookings/{booking_id}/deliver", {}, headers)

    # ------------------------------------------------------------------
    # Consolidations
    # ------------------------------------------------------------------
    def create_consolidation(self, payload, headers):
        return self._request("POST", "/freight/consolidations", payload, headers)

    def list_consolidations(self, headers, params=None):
        return self._request("GET", "/freight/consolidations", headers=headers, params=params)

    def get_consolidation(self, consolidation_id, headers):
        return self._request("GET", f"/freight/consolidations/{consolidation_id}",
                             headers=headers)

    def stuff_consolidation(self, consolidation_id, booking_id,
                            expected_consolidation_version, headers):
        return self._request(
            "POST", f"/freight/consolidations/{consolidation_id}/stuff",
            {"booking_id": booking_id,
             "expected_consolidation_version": expected_consolidation_version},
            headers)

    def unstuff_consolidation(self, consolidation_id, booking_id, headers):
        return self._request("POST", f"/freight/consolidations/{consolidation_id}/unstuff",
                             {"booking_id": booking_id}, headers)

    def close_consolidation(self, consolidation_id, headers):
        return self._request("POST", f"/freight/consolidations/{consolidation_id}/close",
                             {}, headers)

    def tender_consolidation(self, consolidation_id, headers):
        return self._request("POST", f"/freight/consolidations/{consolidation_id}/tender",
                             {}, headers)

    def cancel_consolidation(self, consolidation_id, headers):
        return self._request("POST", f"/freight/consolidations/{consolidation_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Container assignments
    # ------------------------------------------------------------------
    def create_container_assignment(self, payload, headers):
        return self._request("POST", "/freight/container-assignments", payload, headers)

    def list_container_assignments(self, headers, params=None):
        return self._request("GET", "/freight/container-assignments",
                             headers=headers, params=params)

    def get_container_assignment(self, assignment_id, headers):
        return self._request("GET", f"/freight/container-assignments/{assignment_id}",
                             headers=headers)

    def gate_in_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/freight/container-assignments/{assignment_id}/gate-in",
                             {}, headers)

    def gate_out_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/freight/container-assignments/{assignment_id}/gate-out",
                             {}, headers)

    def empty_return_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/freight/container-assignments/{assignment_id}/empty-return",
                             {}, headers)

    # ------------------------------------------------------------------
    # Bills of lading
    # ------------------------------------------------------------------
    def create_bill_of_lading(self, payload, headers):
        return self._request("POST", "/freight/bill-of-lading", payload, headers)

    def list_bill_of_lading(self, headers, params=None):
        return self._request("GET", "/freight/bill-of-lading", headers=headers, params=params)

    def get_bill_of_lading(self, bl_id, headers):
        return self._request("GET", f"/freight/bill-of-lading/{bl_id}", headers=headers)

    def issue_bill_of_lading(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/issue", {}, headers)

    def request_bl_amendment(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/request-amendment",
                             {}, headers)

    def reissue_bill_of_lading(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/reissue", {}, headers)

    def surrender_bill_of_lading(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/surrender",
                             {}, headers)

    def release_bill_of_lading(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/release", {}, headers)

    def void_bill_of_lading(self, bl_id, headers):
        return self._request("POST", f"/freight/bill-of-lading/{bl_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Compliance filings
    # ------------------------------------------------------------------
    def create_compliance_filing(self, payload, headers):
        return self._request("POST", "/freight/compliance-filings", payload, headers)

    def list_compliance_filings(self, headers, params=None):
        return self._request("GET", "/freight/compliance-filings",
                             headers=headers, params=params)

    def get_compliance_filing(self, filing_id, headers):
        return self._request("GET", f"/freight/compliance-filings/{filing_id}",
                             headers=headers)

    def submit_compliance_filing(self, filing_id, headers):
        return self._request("POST", f"/freight/compliance-filings/{filing_id}/submit",
                             {}, headers)

    def record_filing_response(self, filing_id, outcome, headers):
        return self._request("POST",
                             f"/freight/compliance-filings/{filing_id}/record-response",
                             {"outcome": outcome}, headers)

    def resolve_filing_penalty(self, filing_id, resolution, headers):
        return self._request("POST",
                             f"/freight/compliance-filings/{filing_id}/resolve-penalty",
                             {"resolution": resolution}, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/freight/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/freight/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/freight/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/freight/invoices/{invoice_id}/issue", {}, headers)

    def record_invoice_payment(self, invoice_id, amount_cents, headers):
        return self._request("POST", f"/freight/invoices/{invoice_id}/payments",
                             {"amount_cents": amount_cents}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/freight/invoices/{invoice_id}/void", {}, headers)

    def add_invoice_adjustment(self, invoice_id, description, quantity,
                               unit_rate_cents, expected_invoice_version, headers):
        return self._request(
            "POST", f"/freight/invoices/{invoice_id}/adjustments",
            {"description": description, "quantity": quantity,
             "unit_rate_cents": unit_rate_cents,
             "expected_invoice_version": expected_invoice_version},
            headers)

    # ------------------------------------------------------------------
    # Cargo insurance policies
    # ------------------------------------------------------------------
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/freight/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/freight/insurance-policies",
                             headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/freight/insurance-policies/{policy_id}",
                             headers=headers)

    def bind_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/freight/insurance-policies/{policy_id}/bind",
                             {}, headers)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/freight/insurance-policies/{policy_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Cargo claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/freight/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/freight/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/freight/claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/freight/claims/{claim_id}/start-review",
                             {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/freight/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/freight/claims/{claim_id}/deny", {}, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/freight/claims/{claim_id}/settle", {}, headers)


api_client = ApiClient()
