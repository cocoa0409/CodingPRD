"""API client: one method per endpoint defined in the Building Permit PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Jurisdiction ──────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # ─── Contractor ────────────────────────────────────
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def update_contractor(self, contractor_id, payload, headers):
        return self._request("PATCH", f"/contractors/{contractor_id}", payload, headers)

    # ─── Inspector / PlanReviewer (role-backed) ────────
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def create_plan_reviewer(self, payload, headers):
        return self._request("POST", "/plan-reviewers", payload, headers)

    def get_plan_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/plan-reviewers/{reviewer_id}", headers=headers)

    # ─── PermitApplication core ────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def withdraw_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/withdraw", payload or {}, headers)

    def resubmit_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/resubmit", payload or {}, headers)

    def issue_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", payload, headers)

    def renew_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/renew", payload, headers)

    def expire_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/expire", payload or {}, headers)

    def finalize_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/finalize", payload or {}, headers)

    def list_permit_events(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/events", headers=headers, params=params)

    # ─── Fee payments ──────────────────────────────────
    def create_payment(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ─── Plan reviews ──────────────────────────────────
    def open_review(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def decide_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/decide", payload, headers)

    # ─── Correction notices ────────────────────────────
    def create_correction_notice(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/correction-notices", payload, headers)

    def get_correction_notice(self, correction_id, headers):
        return self._request("GET", f"/correction-notices/{correction_id}", headers=headers)

    def list_correction_notices(self, headers, params=None):
        return self._request("GET", "/correction-notices", headers=headers, params=params)

    def resolve_correction_notice(self, correction_id, headers, payload=None):
        return self._request("POST", f"/correction-notices/{correction_id}/resolve", payload or {}, headers)

    # ─── Inspection slots ──────────────────────────────
    def create_slot(self, payload, headers):
        return self._request("POST", "/inspection-slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/inspection-slots/{slot_id}", headers=headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/inspection-slots", headers=headers, params=params)

    # ─── Inspections ───────────────────────────────────
    def schedule_inspection(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/result", payload, headers)

    def cancel_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", payload or {}, headers)

    # ─── Stop-work orders ──────────────────────────────
    def create_stop_work_order(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/stop-work-orders", payload, headers)

    def get_stop_work_order(self, swo_id, headers):
        return self._request("GET", f"/stop-work-orders/{swo_id}", headers=headers)

    def list_stop_work_orders(self, headers, params=None):
        return self._request("GET", "/stop-work-orders", headers=headers, params=params)

    def lift_stop_work_order(self, swo_id, headers, payload=None):
        return self._request("POST", f"/stop-work-orders/{swo_id}/lift", payload or {}, headers)

    # ─── Certificates of occupancy ─────────────────────
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def revoke_certificate(self, certificate_id, headers, payload=None):
        return self._request("POST", f"/certificates/{certificate_id}/revoke", payload or {}, headers)

    # ─── Test-driving clock ────────────────────────────
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
