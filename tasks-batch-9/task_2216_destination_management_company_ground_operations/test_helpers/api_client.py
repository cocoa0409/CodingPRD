"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4 / §4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Programmes
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/dmc/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/dmc/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/dmc/programs", headers=headers, params=params)

    def get_program_cost_summary(self, program_id, headers):
        return self._request(
            "GET", f"/dmc/programs/{program_id}/cost-summary", headers=headers
        )

    def lock_program_design(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/lock-design", payload or {}, headers
        )

    def unlock_program_design(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/unlock-design", payload or {}, headers
        )

    def confirm_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/confirm", payload or {}, headers
        )

    def start_program_execution(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/start-execution", payload or {}, headers
        )

    def cancel_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/cancel", payload or {}, headers
        )

    def reconcile_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/reconcile", payload or {}, headers
        )

    def issue_program_invoice(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/issue-invoice", payload or {}, headers
        )

    def credit_program_invoice(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/programs/{program_id}/credit-invoice", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Venues
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/dmc/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/dmc/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/dmc/venues", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/dmc/suppliers", payload, headers)

    def patch_supplier(self, supplier_id, payload, headers):
        return self._request("PATCH", f"/dmc/suppliers/{supplier_id}", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/dmc/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/dmc/suppliers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Supplier contracts
    # ------------------------------------------------------------------
    def create_supplier_contract(self, payload, headers):
        return self._request("POST", "/dmc/supplier-contracts", payload, headers)

    def get_supplier_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/dmc/supplier-contracts/{contract_id}", headers=headers
        )

    def list_supplier_contracts(self, headers, params=None):
        return self._request(
            "GET", "/dmc/supplier-contracts", headers=headers, params=params
        )

    def send_supplier_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/supplier-contracts/{contract_id}/send",
            payload or {},
            headers,
        )

    def counter_supplier_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/dmc/supplier-contracts/{contract_id}/counter", payload, headers
        )

    def countersign_supplier_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/supplier-contracts/{contract_id}/countersign",
            payload or {},
            headers,
        )

    def terminate_supplier_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/supplier-contracts/{contract_id}/terminate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Program elements
    # ------------------------------------------------------------------
    def create_program_element(self, payload, headers):
        return self._request("POST", "/dmc/program-elements", payload, headers)

    def get_program_element(self, element_id, headers):
        return self._request(
            "GET", f"/dmc/program-elements/{element_id}", headers=headers
        )

    def list_program_elements(self, headers, params=None):
        return self._request(
            "GET", "/dmc/program-elements", headers=headers, params=params
        )

    def patch_program_element(self, element_id, payload, headers):
        return self._request(
            "PATCH", f"/dmc/program-elements/{element_id}", payload, headers
        )

    def mark_element_ready(self, element_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/program-elements/{element_id}/mark-ready",
            payload or {},
            headers,
        )

    def deliver_element(self, element_id, payload, headers):
        return self._request(
            "POST", f"/dmc/program-elements/{element_id}/deliver", payload, headers
        )

    def weather_switch_element(self, element_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/program-elements/{element_id}/weather-switch",
            payload or {},
            headers,
        )

    def cancel_element(self, element_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/program-elements/{element_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Permits
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/dmc/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/dmc/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/dmc/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers, payload=None):
        return self._request(
            "POST", f"/dmc/permits/{permit_id}/submit", payload or {}, headers
        )

    def record_permit_decision(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/dmc/permits/{permit_id}/record-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Transport segments
    # ------------------------------------------------------------------
    def create_transport_segment(self, payload, headers):
        return self._request("POST", "/dmc/transport-segments", payload, headers)

    def get_transport_segment(self, segment_id, headers):
        return self._request(
            "GET", f"/dmc/transport-segments/{segment_id}", headers=headers
        )

    def list_transport_segments(self, headers, params=None):
        return self._request(
            "GET", "/dmc/transport-segments", headers=headers, params=params
        )

    def depart_transport_segment(self, segment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/transport-segments/{segment_id}/depart",
            payload or {},
            headers,
        )

    def cancel_transport_segment(self, segment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/transport-segments/{segment_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Manifest entries
    # ------------------------------------------------------------------
    def create_manifest_entry(self, payload, headers):
        return self._request("POST", "/dmc/manifest-entries", payload, headers)

    def get_manifest_entry(self, manifest_entry_id, headers):
        return self._request(
            "GET", f"/dmc/manifest-entries/{manifest_entry_id}", headers=headers
        )

    def list_manifest_entries(self, headers, params=None):
        return self._request(
            "GET", "/dmc/manifest-entries", headers=headers, params=params
        )

    def move_manifest_entry(self, manifest_entry_id, payload, headers):
        return self._request(
            "POST", f"/dmc/manifest-entries/{manifest_entry_id}/move", payload, headers
        )

    def check_in_manifest_entry(self, manifest_entry_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/manifest-entries/{manifest_entry_id}/check-in",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Staff members
    # ------------------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/dmc/staff-members", payload, headers)

    def patch_staff_member(self, staff_member_id, payload, headers):
        return self._request(
            "PATCH", f"/dmc/staff-members/{staff_member_id}", payload, headers
        )

    def get_staff_member(self, staff_member_id, headers):
        return self._request(
            "GET", f"/dmc/staff-members/{staff_member_id}", headers=headers
        )

    def list_staff_members(self, headers, params=None):
        return self._request(
            "GET", "/dmc/staff-members", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Staff assignments
    # ------------------------------------------------------------------
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", "/dmc/staff-assignments", payload, headers)

    def get_staff_assignment(self, staff_assignment_id, headers):
        return self._request(
            "GET", f"/dmc/staff-assignments/{staff_assignment_id}", headers=headers
        )

    def list_staff_assignments(self, headers, params=None):
        return self._request(
            "GET", "/dmc/staff-assignments", headers=headers, params=params
        )

    def confirm_staff_assignment(self, staff_assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/staff-assignments/{staff_assignment_id}/confirm",
            payload or {},
            headers,
        )

    def check_in_staff_assignment(self, staff_assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/staff-assignments/{staff_assignment_id}/check-in",
            payload or {},
            headers,
        )

    def release_staff_assignment(self, staff_assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/staff-assignments/{staff_assignment_id}/release",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Reconciliation lines
    # ------------------------------------------------------------------
    def get_reconciliation_line(self, reconciliation_line_id, headers):
        return self._request(
            "GET",
            f"/dmc/reconciliation-lines/{reconciliation_line_id}",
            headers=headers,
        )

    def list_reconciliation_lines(self, headers, params=None):
        return self._request(
            "GET", "/dmc/reconciliation-lines", headers=headers, params=params
        )

    def patch_reconciliation_line(self, reconciliation_line_id, payload, headers):
        return self._request(
            "PATCH",
            f"/dmc/reconciliation-lines/{reconciliation_line_id}",
            payload,
            headers,
        )

    def approve_reconciliation_line(self, reconciliation_line_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/reconciliation-lines/{reconciliation_line_id}/approve",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Settlement payments
    # ------------------------------------------------------------------
    def create_settlement_payment(self, payload, headers):
        return self._request("POST", "/dmc/settlement-payments", payload, headers)

    def get_settlement_payment(self, settlement_payment_id, headers):
        return self._request(
            "GET", f"/dmc/settlement-payments/{settlement_payment_id}", headers=headers
        )

    def list_settlement_payments(self, headers, params=None):
        return self._request(
            "GET", "/dmc/settlement-payments", headers=headers, params=params
        )

    def approve_settlement_payment(self, settlement_payment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/settlement-payments/{settlement_payment_id}/approve",
            payload or {},
            headers,
        )

    def release_settlement_payment(self, settlement_payment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/settlement-payments/{settlement_payment_id}/release",
            payload or {},
            headers,
        )

    def void_settlement_payment(self, settlement_payment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dmc/settlement-payments/{settlement_payment_id}/void",
            payload or {},
            headers,
        )


api_client = ApiClient()
