"""API client: one method per endpoint defined in the PRD.

The URL space is flat — every collection sits at the root of the URL space with
no shared prefix segment — so every path below is exactly as written in the PRD.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---------------- catastrophe events ----------------
    def create_event(self, payload, headers):
        return self._request("POST", "/catastrophe-events", payload, headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/catastrophe-events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/catastrophe-events/{event_id}", headers=headers)

    def declare_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/catastrophe-events/{event_id}/declare", payload or {}, headers=headers
        )

    def activate_surge(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/catastrophe-events/{event_id}/activate-surge", payload or {}, headers=headers
        )

    def demobilize_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/catastrophe-events/{event_id}/demobilize", payload or {}, headers=headers
        )

    def close_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/catastrophe-events/{event_id}/close", payload or {}, headers=headers
        )

    # ---------------- regulatory bulletins ----------------
    def create_bulletin(self, payload, headers):
        return self._request("POST", "/regulatory-bulletins", payload, headers=headers)

    def list_bulletins(self, headers, params=None):
        return self._request("GET", "/regulatory-bulletins", headers=headers, params=params)

    def get_bulletin(self, bulletin_id, headers):
        return self._request("GET", f"/regulatory-bulletins/{bulletin_id}", headers=headers)

    def activate_bulletin(self, bulletin_id, headers, payload=None):
        return self._request(
            "POST", f"/regulatory-bulletins/{bulletin_id}/activate", payload or {}, headers=headers
        )

    def withdraw_bulletin(self, bulletin_id, headers, payload=None):
        return self._request(
            "POST", f"/regulatory-bulletins/{bulletin_id}/withdraw", payload or {}, headers=headers
        )

    # ---------------- adjusters ----------------
    def create_adjuster(self, payload, headers):
        return self._request("POST", "/adjusters", payload, headers=headers)

    def list_adjusters(self, headers, params=None):
        return self._request("GET", "/adjusters", headers=headers, params=params)

    def get_adjuster(self, adjuster_id, headers):
        return self._request("GET", f"/adjusters/{adjuster_id}", headers=headers)

    def set_adjuster_unavailable(self, adjuster_id, headers, payload=None):
        return self._request(
            "POST", f"/adjusters/{adjuster_id}/set-unavailable", payload or {}, headers=headers
        )

    def set_adjuster_available(self, adjuster_id, headers, payload=None):
        return self._request(
            "POST", f"/adjusters/{adjuster_id}/set-available", payload or {}, headers=headers
        )

    def apply_license_waiver(self, adjuster_id, payload, headers):
        return self._request(
            "POST", f"/adjusters/{adjuster_id}/apply-license-waiver", payload, headers=headers
        )

    # ---------------- housing blocks ----------------
    def create_housing_block(self, payload, headers):
        return self._request("POST", "/housing-blocks", payload, headers=headers)

    def list_housing_blocks(self, headers, params=None):
        return self._request("GET", "/housing-blocks", headers=headers, params=params)

    def get_housing_block(self, block_id, headers):
        return self._request("GET", f"/housing-blocks/{block_id}", headers=headers)

    def open_housing_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/housing-blocks/{block_id}/open", payload or {}, headers=headers
        )

    def release_housing_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/housing-blocks/{block_id}/release", payload or {}, headers=headers
        )

    # ---------------- deployments ----------------
    def create_deployment(self, payload, headers):
        return self._request("POST", "/deployments", payload, headers=headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/deployments/{deployment_id}", headers=headers)

    def confirm_deployment(self, deployment_id, headers, payload=None):
        return self._request(
            "POST", f"/deployments/{deployment_id}/confirm", payload or {}, headers=headers
        )

    def check_in_deployment(self, deployment_id, headers, payload=None):
        return self._request(
            "POST", f"/deployments/{deployment_id}/check-in", payload or {}, headers=headers
        )

    def demobilize_deployment(self, deployment_id, headers, payload=None):
        return self._request(
            "POST", f"/deployments/{deployment_id}/demobilize", payload or {}, headers=headers
        )

    def cancel_deployment(self, deployment_id, headers, payload=None):
        return self._request(
            "POST", f"/deployments/{deployment_id}/cancel", payload or {}, headers=headers
        )

    # ---------------- claims ----------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def assign_cat_code(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/assign-cat-code", payload, headers=headers
        )

    def triage_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/triage", payload or {}, headers=headers
        )

    def close_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/close", payload or {}, headers=headers
        )

    def reopen_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/reopen", payload or {}, headers=headers
        )

    def create_reserve_entry(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/reserve-entries", payload, headers=headers
        )

    # ---------------- reserve ledger ----------------
    def list_reserve_entries(self, headers, params=None):
        return self._request("GET", "/reserve-entries", headers=headers, params=params)

    def get_reserve_entry(self, entry_id, headers):
        return self._request("GET", f"/reserve-entries/{entry_id}", headers=headers)

    # ---------------- inspection assignments ----------------
    def create_inspection_assignment(self, payload, headers):
        return self._request("POST", "/inspection-assignments", payload, headers=headers)

    def list_inspection_assignments(self, headers, params=None):
        return self._request("GET", "/inspection-assignments", headers=headers, params=params)

    def get_inspection_assignment(self, assignment_id, headers):
        return self._request("GET", f"/inspection-assignments/{assignment_id}", headers=headers)

    def start_inspection(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/inspection-assignments/{assignment_id}/start", payload or {}, headers=headers
        )

    def complete_inspection(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/inspection-assignments/{assignment_id}/complete", payload, headers=headers
        )

    def report_no_access(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/inspection-assignments/{assignment_id}/report-no-access",
            payload or {},
            headers=headers,
        )

    def cancel_inspection_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/inspection-assignments/{assignment_id}/cancel",
            payload or {},
            headers=headers,
        )

    # ---------------- advance payments ----------------
    def create_advance_payment(self, payload, headers):
        return self._request("POST", "/advance-payments", payload, headers=headers)

    def list_advance_payments(self, headers, params=None):
        return self._request("GET", "/advance-payments", headers=headers, params=params)

    def get_advance_payment(self, advance_id, headers):
        return self._request("GET", f"/advance-payments/{advance_id}", headers=headers)

    def void_advance_payment(self, advance_id, payload, headers):
        return self._request(
            "POST", f"/advance-payments/{advance_id}/void", payload, headers=headers
        )

    # ---------------- vendor firms ----------------
    def create_vendor_firm(self, payload, headers):
        return self._request("POST", "/vendor-firms", payload, headers=headers)

    def list_vendor_firms(self, headers, params=None):
        return self._request("GET", "/vendor-firms", headers=headers, params=params)

    def get_vendor_firm(self, firm_id, headers):
        return self._request("GET", f"/vendor-firms/{firm_id}", headers=headers)

    def activate_vendor_firm(self, firm_id, payload, headers):
        return self._request(
            "POST", f"/vendor-firms/{firm_id}/activate", payload, headers=headers
        )

    def suspend_vendor_firm(self, firm_id, headers, payload=None):
        return self._request(
            "POST", f"/vendor-firms/{firm_id}/suspend", payload or {}, headers=headers
        )

    # ---------------- vendor assignments ----------------
    def create_vendor_assignment(self, payload, headers):
        return self._request("POST", "/vendor-assignments", payload, headers=headers)

    def list_vendor_assignments(self, headers, params=None):
        return self._request("GET", "/vendor-assignments", headers=headers, params=params)

    def get_vendor_assignment(self, assignment_id, headers):
        return self._request("GET", f"/vendor-assignments/{assignment_id}", headers=headers)

    def accept_vendor_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/accept", payload or {}, headers=headers
        )

    def decline_vendor_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/decline", payload or {}, headers=headers
        )

    def complete_vendor_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/complete", payload or {}, headers=headers
        )

    def cancel_vendor_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/cancel", payload or {}, headers=headers
        )

    # ---------------- loss estimates ----------------
    def create_loss_estimate(self, payload, headers):
        return self._request("POST", "/loss-estimates", payload, headers=headers)

    def list_loss_estimates(self, headers, params=None):
        return self._request("GET", "/loss-estimates", headers=headers, params=params)

    def get_loss_estimate(self, snapshot_id, headers):
        return self._request("GET", f"/loss-estimates/{snapshot_id}", headers=headers)

    # ---------------- file transfer batches ----------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/file-transfer-batches", payload, headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/file-transfer-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/file-transfer-batches/{batch_id}", headers=headers)

    def add_claim_to_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/file-transfer-batches/{batch_id}/claims", payload, headers=headers
        )

    def submit_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/file-transfer-batches/{batch_id}/submit", payload or {}, headers=headers
        )

    def accept_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/file-transfer-batches/{batch_id}/accept", payload or {}, headers=headers
        )

    def reject_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/file-transfer-batches/{batch_id}/reject", payload, headers=headers
        )

    def reopen_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/file-transfer-batches/{batch_id}/reopen-batch", payload or {}, headers=headers
        )


api_client = ApiClient()
