"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Office ───────────────────────────────────────────────────────────
    def create_office(self, payload, headers):
        return self._request("POST", "/offices", payload, headers)

    def get_office(self, office_id, headers):
        return self._request("GET", f"/offices/{office_id}", headers=headers)

    def set_efin_status(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/efin-status", payload, headers)

    # ─── ComplianceCredential ─────────────────────────────────────────────
    def create_credential(self, payload, headers):
        return self._request("POST", "/credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", "/credentials", headers=headers, params=params)

    def revoke_credential(self, credential_id, headers):
        return self._request("POST", f"/credentials/{credential_id}/revoke", {}, headers)

    # ─── Preparer ─────────────────────────────────────────────────────────
    def create_preparer(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/preparers", payload, headers)

    def list_office_preparers(self, office_id, headers, params=None):
        return self._request("GET", f"/offices/{office_id}/preparers", headers=headers, params=params)

    def get_preparer(self, preparer_id, headers):
        return self._request("GET", f"/preparers/{preparer_id}", headers=headers)

    def list_preparers(self, headers, params=None):
        return self._request("GET", "/preparers", headers=headers, params=params)

    # ─── Client ───────────────────────────────────────────────────────────
    def create_client(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/clients", payload, headers)

    def list_office_clients(self, office_id, headers, params=None):
        return self._request("GET", f"/offices/{office_id}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ─── Appointment ──────────────────────────────────────────────────────
    def create_appointment(self, office_id, payload, headers):
        return self._request("POST", f"/offices/{office_id}/appointments", payload, headers)

    def list_office_appointments(self, office_id, headers, params=None):
        return self._request("GET", f"/offices/{office_id}/appointments", headers=headers, params=params)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def transition_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/transition", payload, headers)

    # ─── TaxReturn ────────────────────────────────────────────────────────
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def assign_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/assign", payload, headers)

    def transition_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/transition", payload, headers)

    def efile_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/efile", {}, headers)

    def efile_ack_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/efile-ack", payload, headers)

    # ─── DocumentIntake ───────────────────────────────────────────────────
    def create_document(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/documents", payload, headers)

    def list_documents(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/documents", headers=headers, params=params)

    def set_document_status(self, document_id, payload, headers):
        return self._request("POST", f"/documents/{document_id}/status", payload, headers)

    # ─── FeeLine ──────────────────────────────────────────────────────────
    def list_fee_lines(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/fee-lines", headers=headers, params=params)

    # ─── AuditProtection ──────────────────────────────────────────────────
    def create_audit_protection(self, payload, headers):
        return self._request("POST", "/audit-protections", payload, headers)

    def get_audit_protection(self, ap_id, headers):
        return self._request("GET", f"/audit-protections/{ap_id}", headers=headers)

    def list_audit_protections(self, headers, params=None):
        return self._request("GET", "/audit-protections", headers=headers, params=params)

    def cancel_audit_protection(self, ap_id, headers):
        return self._request("POST", f"/audit-protections/{ap_id}/cancel", {}, headers)

    # ─── EfileSubmission ──────────────────────────────────────────────────
    def list_efile_submissions(self, return_id, headers, params=None):
        return self._request("GET", f"/returns/{return_id}/efile-submissions", headers=headers, params=params)

    # ─── RefundTransfer ───────────────────────────────────────────────────
    def create_refund_transfer(self, payload, headers):
        return self._request("POST", "/refund-transfers", payload, headers)

    def get_refund_transfer(self, rt_id, headers):
        return self._request("GET", f"/refund-transfers/{rt_id}", headers=headers)

    def list_refund_transfers(self, headers, params=None):
        return self._request("GET", "/refund-transfers", headers=headers, params=params)

    def adjust_refund_transfer(self, rt_id, payload, headers):
        return self._request("POST", f"/refund-transfers/{rt_id}/adjust", payload, headers)

    def disburse_refund_transfer(self, rt_id, payload, headers):
        return self._request("POST", f"/refund-transfers/{rt_id}/disburse", payload, headers)

    def cancel_refund_transfer(self, rt_id, headers):
        return self._request("POST", f"/refund-transfers/{rt_id}/cancel", {}, headers)

    # ─── RefundAdvance ────────────────────────────────────────────────────
    def create_refund_advance(self, payload, headers):
        return self._request("POST", "/refund-advances", payload, headers)

    def get_refund_advance(self, adv_id, headers):
        return self._request("GET", f"/refund-advances/{adv_id}", headers=headers)

    def list_refund_advances(self, headers, params=None):
        return self._request("GET", "/refund-advances", headers=headers, params=params)

    def underwrite_refund_advance(self, adv_id, payload, headers):
        return self._request("POST", f"/refund-advances/{adv_id}/underwrite", payload, headers)

    def disburse_refund_advance(self, adv_id, headers):
        return self._request("POST", f"/refund-advances/{adv_id}/disburse", {}, headers)

    # ─── Clock (test-driving) ─────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
