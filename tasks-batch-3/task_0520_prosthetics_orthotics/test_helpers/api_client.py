"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() method is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Patients ──────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/op/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/op/patients/{patient_id}", headers=headers)

    # ── Physicians ────────────────────────────────────────────────────
    def create_physician(self, payload, headers):
        return self._request("POST", "/op/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/op/physicians/{physician_id}", headers=headers)

    # ── Suppliers ─────────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/op/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/op/suppliers/{supplier_id}", headers=headers)

    # ── Prescriptions ─────────────────────────────────────────────────
    def create_prescription(self, payload, headers):
        return self._request("POST", "/op/prescriptions", payload, headers)

    def get_prescription(self, rx_id, headers):
        return self._request("GET", f"/op/prescriptions/{rx_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/op/prescriptions", headers=headers, params=params)

    def sign_prescription(self, rx_id, headers):
        return self._request("POST", f"/op/prescriptions/{rx_id}/sign", {}, headers)

    def void_prescription(self, rx_id, headers):
        return self._request("POST", f"/op/prescriptions/{rx_id}/void", {}, headers)

    # ── Device Orders ─────────────────────────────────────────────────
    def create_device_order(self, payload, headers):
        return self._request("POST", "/op/device-orders", payload, headers)

    def get_device_order(self, order_id, headers):
        return self._request("GET", f"/op/device-orders/{order_id}", headers=headers)

    def list_device_orders(self, headers, params=None):
        return self._request("GET", "/op/device-orders", headers=headers, params=params)

    def submit_auth(self, order_id, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/submit-auth", {}, headers)

    def start_fabrication(self, order_id, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/start-fabrication", {}, headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/deliver", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/cancel", {}, headers)

    def get_billing_summary(self, order_id, headers):
        return self._request("GET", f"/op/device-orders/{order_id}/billing-summary", headers=headers)

    def list_compliance_checks(self, order_id, headers, params=None):
        return self._request("GET", f"/op/device-orders/{order_id}/compliance-checks",
                             headers=headers, params=params)

    # ── Fabrication Milestones ────────────────────────────────────────
    def create_milestone(self, order_id, payload, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/fabrication-milestones",
                             payload, headers)

    def list_milestones(self, order_id, headers, params=None):
        return self._request("GET", f"/op/device-orders/{order_id}/fabrication-milestones",
                             headers=headers, params=params)

    def complete_milestone(self, milestone_id, headers):
        return self._request("POST", f"/op/fabrication-milestones/{milestone_id}/complete",
                             {}, headers)

    # ── Prior Auths ───────────────────────────────────────────────────
    def get_prior_auth(self, pa_id, headers):
        return self._request("GET", f"/op/prior-auths/{pa_id}", headers=headers)

    def list_prior_auths(self, headers, params=None):
        return self._request("GET", "/op/prior-auths", headers=headers, params=params)

    def pend_prior_auth(self, pa_id, headers):
        return self._request("POST", f"/op/prior-auths/{pa_id}/pend", {}, headers)

    def resubmit_prior_auth(self, pa_id, payload, headers):
        return self._request("POST", f"/op/prior-auths/{pa_id}/resubmit", payload, headers)

    def approve_prior_auth(self, pa_id, headers):
        return self._request("POST", f"/op/prior-auths/{pa_id}/approve", {}, headers)

    def deny_prior_auth(self, pa_id, headers):
        return self._request("POST", f"/op/prior-auths/{pa_id}/deny", {}, headers)

    # ── Claim Lines ───────────────────────────────────────────────────
    def create_claim_line(self, payload, headers):
        return self._request("POST", "/op/claim-lines", payload, headers)

    def get_claim_line(self, cl_id, headers):
        return self._request("GET", f"/op/claim-lines/{cl_id}", headers=headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/op/claim-lines", headers=headers, params=params)

    def adjudicate_claim_line(self, cl_id, headers):
        return self._request("POST", f"/op/claim-lines/{cl_id}/adjudicate", {}, headers)

    def deny_claim_line(self, cl_id, headers):
        return self._request("POST", f"/op/claim-lines/{cl_id}/deny", {}, headers)

    def appeal_claim_line(self, cl_id, headers):
        return self._request("POST", f"/op/claim-lines/{cl_id}/appeal", {}, headers)

    def appeal_decision(self, cl_id, payload, headers):
        return self._request("POST", f"/op/claim-lines/{cl_id}/appeal-decision", payload, headers)

    # ── Repair Requests ───────────────────────────────────────────────
    def create_repair_request(self, payload, headers):
        return self._request("POST", "/op/repair-requests", payload, headers)

    def get_repair_request(self, rr_id, headers):
        return self._request("GET", f"/op/repair-requests/{rr_id}", headers=headers)

    def list_repair_requests(self, headers, params=None):
        return self._request("GET", "/op/repair-requests", headers=headers, params=params)

    def assess_repair(self, rr_id, payload, headers):
        return self._request("POST", f"/op/repair-requests/{rr_id}/assess", payload, headers)

    def complete_repair(self, rr_id, headers):
        return self._request("POST", f"/op/repair-requests/{rr_id}/complete-repair", {}, headers)

    def authorize_replacement(self, rr_id, headers):
        return self._request("POST", f"/op/repair-requests/{rr_id}/authorize-replacement", {}, headers)

    def close_repair(self, rr_id, headers):
        return self._request("POST", f"/op/repair-requests/{rr_id}/close", {}, headers)

    # ── Adjustments ───────────────────────────────────────────────────
    def create_adjustment(self, order_id, payload, headers):
        return self._request("POST", f"/op/device-orders/{order_id}/adjustments", payload, headers)

    def list_adjustments(self, order_id, headers, params=None):
        return self._request("GET", f"/op/device-orders/{order_id}/adjustments",
                             headers=headers, params=params)

    # ── Logical clock ─────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/op/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
