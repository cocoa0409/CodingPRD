"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock ────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Patient ──────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ─── Supplier ─────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def update_supplier(self, supplier_id, payload, headers):
        return self._request("PATCH", f"/suppliers/{supplier_id}", payload, headers)

    # ─── HCPCSItem ────────────────────────────────────
    def create_hcpcs_item(self, payload, headers):
        return self._request("POST", "/hcpcs-items", payload, headers)

    def get_hcpcs_item(self, item_id, headers):
        return self._request("GET", f"/hcpcs-items/{item_id}", headers=headers)

    # ─── DMEOrder ─────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/dme-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/dme-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/dme-orders", headers=headers, params=params)

    def get_rental_quote(self, order_id, headers):
        return self._request(
            "GET", f"/dme-orders/{order_id}/rental-quote", headers=headers
        )

    def mark_ready(self, order_id, headers):
        return self._request(
            "POST", f"/dme-orders/{order_id}/mark-ready", {}, headers
        )

    def activate_billing(self, order_id, headers):
        return self._request(
            "POST", f"/dme-orders/{order_id}/activate-billing", {}, headers
        )

    def post_rental_cycle(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/dme-orders/{order_id}/rental-cycles", payload or {}, headers
        )

    def close_order(self, order_id, headers):
        return self._request("POST", f"/dme-orders/{order_id}/close", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dme-orders/{order_id}/cancel", {}, headers)

    # ─── CMN ──────────────────────────────────────────
    def create_cmn(self, payload, headers):
        return self._request("POST", "/cmns", payload, headers)

    def get_cmn(self, cmn_id, headers):
        return self._request("GET", f"/cmns/{cmn_id}", headers=headers)

    def list_cmns(self, headers, params=None):
        return self._request("GET", "/cmns", headers=headers, params=params)

    def activate_cmn(self, cmn_id, expected_order_version, headers):
        return self._request(
            "POST",
            f"/cmns/{cmn_id}/activate",
            {"expected_order_version": expected_order_version},
            headers,
        )

    def revoke_cmn(self, cmn_id, headers):
        return self._request("POST", f"/cmns/{cmn_id}/revoke", {}, headers)

    # ─── PriorAuthorization ───────────────────────────
    def create_prior_auth(self, payload, headers):
        return self._request("POST", "/prior-authorizations", payload, headers)

    def get_prior_auth(self, pa_id, headers):
        return self._request(
            "GET", f"/prior-authorizations/{pa_id}", headers=headers
        )

    def list_prior_auths(self, headers, params=None):
        return self._request(
            "GET", "/prior-authorizations", headers=headers, params=params
        )

    def approve_prior_auth(self, pa_id, headers, payload=None):
        return self._request(
            "POST", f"/prior-authorizations/{pa_id}/approve", payload or {}, headers
        )

    def deny_prior_auth(self, pa_id, headers, payload=None):
        return self._request(
            "POST", f"/prior-authorizations/{pa_id}/deny", payload or {}, headers
        )

    # ─── Delivery ─────────────────────────────────────
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def confirm_delivery(self, delivery_id, pod_signature_name, headers):
        return self._request(
            "POST",
            f"/deliveries/{delivery_id}/confirm",
            {"pod_signature_name": pod_signature_name},
            headers,
        )

    def fail_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/fail", {}, headers
        )

    def cancel_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/cancel", {}, headers
        )

    # ─── RentalBillingCycle ───────────────────────────
    def get_rental_cycle(self, cycle_id, headers):
        return self._request("GET", f"/rental-cycles/{cycle_id}", headers=headers)

    def list_rental_cycles(self, headers, params=None):
        return self._request(
            "GET", "/rental-cycles", headers=headers, params=params
        )

    def mark_paid(self, cycle_id, headers):
        return self._request(
            "POST", f"/rental-cycles/{cycle_id}/mark-paid", {}, headers
        )

    # ─── ClaimLine ────────────────────────────────────
    def get_claim_line(self, claim_line_id, headers):
        return self._request(
            "GET", f"/claim-lines/{claim_line_id}", headers=headers
        )

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/claim-lines", headers=headers, params=params)

    # ─── CPAPResupplyOrder ────────────────────────────
    def create_resupply(self, payload, headers):
        return self._request("POST", "/cpap-resupply-orders", payload, headers)

    def get_resupply(self, resupply_id, headers):
        return self._request(
            "GET", f"/cpap-resupply-orders/{resupply_id}", headers=headers
        )

    def list_resupplies(self, headers, params=None):
        return self._request(
            "GET", "/cpap-resupply-orders", headers=headers, params=params
        )

    def ship_resupply(self, resupply_id, headers):
        return self._request(
            "POST", f"/cpap-resupply-orders/{resupply_id}/ship", {}, headers
        )

    def deny_resupply(self, resupply_id, headers):
        return self._request(
            "POST", f"/cpap-resupply-orders/{resupply_id}/deny", {}, headers
        )

    # ─── Audit ────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def uphold_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/uphold", {}, headers)

    def dismiss_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/dismiss", {}, headers)


api_client = ApiClient()
