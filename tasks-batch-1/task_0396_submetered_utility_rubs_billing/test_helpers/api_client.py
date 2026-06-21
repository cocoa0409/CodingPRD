"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    # ---- Utility ----
    def create_utility(self, payload, headers):
        return self._request("POST", "/utilities", payload, headers)

    def get_utility(self, utility_id, headers):
        return self._request("GET", f"/utilities/{utility_id}", headers=headers)

    def list_utilities(self, headers, params=None):
        return self._request("GET", "/utilities", headers=headers, params=params)

    # ---- Unit ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ---- Meter ----
    def create_meter(self, payload, headers):
        return self._request("POST", "/meters", payload, headers)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def list_meters(self, headers, params=None):
        return self._request("GET", "/meters", headers=headers, params=params)

    def assign_meter(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/assign", payload, headers)

    def retire_meter(self, meter_id, headers):
        return self._request("POST", f"/meters/{meter_id}/retire", headers=headers)

    # ---- Lease ----
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", headers=headers)

    def give_notice(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/give-notice", payload, headers)

    def move_out_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/move-out", headers=headers)

    def close_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/close", headers=headers)

    # ---- VendorBill ----
    def create_vendor_bill(self, payload, headers):
        return self._request("POST", "/vendor-bills", payload, headers)

    def get_vendor_bill(self, vendor_bill_id, headers):
        return self._request("GET", f"/vendor-bills/{vendor_bill_id}", headers=headers)

    def list_vendor_bills(self, headers, params=None):
        return self._request("GET", "/vendor-bills", headers=headers, params=params)

    def approve_vendor_bill(self, vendor_bill_id, headers):
        return self._request(
            "POST", f"/vendor-bills/{vendor_bill_id}/approve", headers=headers
        )

    def void_vendor_bill(self, vendor_bill_id, headers):
        return self._request(
            "POST", f"/vendor-bills/{vendor_bill_id}/void", headers=headers
        )

    # ---- MeterRead ----
    def create_meter_read(self, payload, headers):
        return self._request("POST", "/meter-reads", payload, headers)

    def get_meter_read(self, read_id, headers):
        return self._request("GET", f"/meter-reads/{read_id}", headers=headers)

    def list_meter_reads(self, headers, params=None):
        return self._request("GET", "/meter-reads", headers=headers, params=params)

    def submit_meter_read(self, read_id, payload=None, headers=None):
        return self._request(
            "POST", f"/meter-reads/{read_id}/submit", payload if payload else {}, headers
        )

    def validate_meter_read(self, read_id, headers):
        return self._request(
            "POST", f"/meter-reads/{read_id}/validate", headers=headers
        )

    def flag_meter_read(self, read_id, payload, headers):
        return self._request("POST", f"/meter-reads/{read_id}/flag", payload, headers)

    def request_re_read(self, read_id, headers):
        return self._request(
            "POST", f"/meter-reads/{read_id}/request-re-read", headers=headers
        )

    # ---- BillingCycle ----
    def create_billing_cycle(self, payload, headers):
        return self._request("POST", "/billing-cycles", payload, headers)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/billing-cycles", headers=headers, params=params)

    def lock_reads(self, cycle_id, headers):
        return self._request(
            "POST", f"/billing-cycles/{cycle_id}/lock-reads", headers=headers
        )

    def allocate_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/billing-cycles/{cycle_id}/allocate", headers=headers
        )

    def issue_statements(self, cycle_id, headers):
        return self._request(
            "POST", f"/billing-cycles/{cycle_id}/issue-statements", headers=headers
        )

    def close_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/billing-cycles/{cycle_id}/close", headers=headers
        )

    # ---- TenantStatement ----
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def mark_delivered(self, statement_id, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/mark-delivered", headers=headers
        )

    def assess_late_fee(self, statement_id, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/assess-late-fee", headers=headers
        )

    def send_to_collections(self, statement_id, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/send-to-collections", headers=headers
        )

    def post_payment(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/payments", payload, headers
        )

    # ---- Payment ----
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/payments/{payment_id}/reverse", headers=headers
        )

    # ---- Dispute ----
    def open_dispute(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/statements/{statement_id}/disputes", payload, headers
        )

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def start_review(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/start-review", headers=headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload if payload else {}, headers
        )

    def reject_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/reject", headers=headers
        )

    def reopen_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/reopen", headers=headers
        )


api_client = ApiClient()
