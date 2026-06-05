"""API client: one method per endpoint defined in the PRD."""
import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # Under per-test-server isolation the server is restarted before every
        # test, so any keep-alive connection pooled in the session points at a
        # now-dead server and the first request raises ConnectionError
        # (BadStatusLine / connection reset). Force Connection: close so the
        # pool never reuses a stale socket, and retry once if a reused socket
        # still slips through the race.
        hdrs = dict(headers or {})
        hdrs.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, hdrs, params)
        except requests.ConnectionError:
            return super()._request(method, path, payload, hdrs, params)

    # ─── Server clock ─────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/assets/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Vendor ───────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/assets/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/assets/vendors/{vendor_id}", headers=headers)

    # ─── Employee ─────────────────────────────────────
    def create_employee(self, payload, headers):
        return self._request("POST", "/assets/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/assets/employees/{employee_id}", headers=headers)

    def transition_employee(self, employee_id, to_status, headers):
        return self._request(
            "POST", f"/assets/employees/{employee_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── SoftwareProduct ──────────────────────────────
    def create_software_product(self, payload, headers):
        return self._request("POST", "/assets/software-products", payload, headers)

    def get_software_product(self, product_id, headers):
        return self._request(
            "GET", f"/assets/software-products/{product_id}", headers=headers
        )

    def list_software_products(self, headers, params=None):
        return self._request(
            "GET", "/assets/software-products", headers=headers, params=params
        )

    # ─── LicenseEntitlement ───────────────────────────
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/assets/entitlements", payload, headers)

    def get_entitlement(self, entitlement_id, headers):
        return self._request(
            "GET", f"/assets/entitlements/{entitlement_id}", headers=headers
        )

    def list_entitlements(self, headers, params=None):
        return self._request(
            "GET", "/assets/entitlements", headers=headers, params=params
        )

    def activate_entitlement(self, entitlement_id, headers):
        return self._request(
            "POST", f"/assets/entitlements/{entitlement_id}/activate", {}, headers
        )

    def transition_entitlement(self, entitlement_id, to_status, headers):
        return self._request(
            "POST", f"/assets/entitlements/{entitlement_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── HardwareAsset ────────────────────────────────
    def create_hardware(self, payload, headers):
        return self._request("POST", "/assets/hardware", payload, headers)

    def get_hardware(self, hardware_id, headers):
        return self._request("GET", f"/assets/hardware/{hardware_id}", headers=headers)

    def list_hardware(self, headers, params=None):
        return self._request("GET", "/assets/hardware", headers=headers, params=params)

    def transition_hardware(self, hardware_id, to_status, headers):
        return self._request(
            "POST", f"/assets/hardware/{hardware_id}/transition",
            {"to_status": to_status}, headers,
        )

    def checkout_hardware(self, hardware_id, payload, headers):
        return self._request(
            "POST", f"/assets/hardware/{hardware_id}/checkout", payload, headers
        )

    # ─── AssignmentCheckout ───────────────────────────
    def get_checkout(self, checkout_id, headers):
        return self._request("GET", f"/assets/checkouts/{checkout_id}", headers=headers)

    def list_checkouts(self, headers, params=None):
        return self._request("GET", "/assets/checkouts", headers=headers, params=params)

    def return_checkout(self, checkout_id, headers):
        return self._request(
            "POST", f"/assets/checkouts/{checkout_id}/return", {}, headers
        )

    def transition_checkout(self, checkout_id, to_status, headers):
        return self._request(
            "POST", f"/assets/checkouts/{checkout_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── WarrantyLease (coverage) ─────────────────────
    def create_coverage(self, payload, headers):
        return self._request("POST", "/assets/coverage", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/assets/coverage/{coverage_id}", headers=headers)

    def list_coverage(self, headers, params=None):
        return self._request("GET", "/assets/coverage", headers=headers, params=params)

    def transition_coverage(self, coverage_id, to_status, headers):
        return self._request(
            "POST", f"/assets/coverage/{coverage_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── InstallationRecord ───────────────────────────
    def create_installation(self, payload, headers):
        return self._request("POST", "/assets/installations", payload, headers)

    def get_installation(self, install_id, headers):
        return self._request(
            "GET", f"/assets/installations/{install_id}", headers=headers
        )

    def list_installations(self, headers, params=None):
        return self._request(
            "GET", "/assets/installations", headers=headers, params=params
        )

    def activate_installation(self, install_id, headers):
        return self._request(
            "POST", f"/assets/installations/{install_id}/activate", {}, headers
        )

    def transition_installation(self, install_id, to_status, headers):
        return self._request(
            "POST", f"/assets/installations/{install_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── DisposalRequest ──────────────────────────────
    def create_disposal_request(self, payload, headers):
        return self._request("POST", "/assets/disposal-requests", payload, headers)

    def get_disposal_request(self, request_id, headers):
        return self._request(
            "GET", f"/assets/disposal-requests/{request_id}", headers=headers
        )

    def list_disposal_requests(self, headers, params=None):
        return self._request(
            "GET", "/assets/disposal-requests", headers=headers, params=params
        )

    def approve_disposal(self, request_id, headers):
        return self._request(
            "POST", f"/assets/disposal-requests/{request_id}/approve", {}, headers
        )

    def reject_disposal(self, request_id, headers):
        return self._request(
            "POST", f"/assets/disposal-requests/{request_id}/reject", {}, headers
        )

    def complete_disposal(self, request_id, headers):
        return self._request(
            "POST", f"/assets/disposal-requests/{request_id}/complete", {}, headers
        )

    def reverse_disposal(self, request_id, headers):
        return self._request(
            "POST", f"/assets/disposal-requests/{request_id}/reverse", {}, headers
        )

    # ─── RenewalOrder ─────────────────────────────────
    def create_renewal_order(self, payload, headers):
        return self._request("POST", "/assets/renewal-orders", payload, headers)

    def get_renewal_order(self, order_id, headers):
        return self._request(
            "GET", f"/assets/renewal-orders/{order_id}", headers=headers
        )

    def list_renewal_orders(self, headers, params=None):
        return self._request(
            "GET", "/assets/renewal-orders", headers=headers, params=params
        )

    def complete_renewal_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/assets/renewal-orders/{order_id}/complete", payload, headers
        )

    def transition_renewal_order(self, order_id, to_status, headers):
        return self._request(
            "POST", f"/assets/renewal-orders/{order_id}/transition",
            {"to_status": to_status}, headers,
        )

    # ─── TrueUpReconciliation + ComplianceFinding ─────
    def create_true_up(self, payload, headers):
        return self._request("POST", "/assets/true-ups", payload, headers)

    def get_true_up(self, true_up_id, headers):
        return self._request("GET", f"/assets/true-ups/{true_up_id}", headers=headers)

    def list_true_ups(self, headers, params=None):
        return self._request("GET", "/assets/true-ups", headers=headers, params=params)

    def finalize_true_up(self, true_up_id, headers):
        return self._request(
            "POST", f"/assets/true-ups/{true_up_id}/finalize", {}, headers
        )

    def list_true_up_findings(self, true_up_id, headers, params=None):
        return self._request(
            "GET", f"/assets/true-ups/{true_up_id}/findings", headers=headers, params=params
        )

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/assets/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/assets/findings", headers=headers, params=params)


api_client = ApiClient()
