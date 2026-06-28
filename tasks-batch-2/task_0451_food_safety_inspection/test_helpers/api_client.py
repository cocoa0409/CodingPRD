"""API client: one method per endpoint defined in the PRD (Food Safety Inspection API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ──────────────────────────────────────────────────────
    def set_clock(self, to_index, headers):
        return self._request("POST", "/_clock/set_current_index", {"to_index": to_index}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ── FDA Food Codes ─────────────────────────────────────────────────────
    def create_fda_food_code(self, payload, headers):
        return self._request("POST", "/fda-food-codes", payload, headers)

    def list_fda_food_codes(self, headers, params=None):
        return self._request("GET", "/fda-food-codes", headers=headers, params=params)

    def get_fda_food_code(self, code_id, headers):
        return self._request("GET", f"/fda-food-codes/{code_id}", headers=headers)

    def retire_fda_food_code(self, code_id, headers):
        return self._request("POST", f"/fda-food-codes/{code_id}/retire", headers=headers)

    # ── Inspectors ─────────────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    # ── Establishments ─────────────────────────────────────────────────────
    def create_establishment(self, payload, headers):
        return self._request("POST", "/establishments", payload, headers)

    def list_establishments(self, headers, params=None):
        return self._request("GET", "/establishments", headers=headers, params=params)

    def get_establishment(self, establishment_id, headers):
        return self._request("GET", f"/establishments/{establishment_id}", headers=headers)

    def update_establishment(self, establishment_id, payload, headers):
        return self._request("PUT", f"/establishments/{establishment_id}", payload, headers)

    def revoke_establishment(self, establishment_id, headers):
        return self._request("POST", f"/establishments/{establishment_id}/revoke", headers=headers)

    # ── Plan Reviews ───────────────────────────────────────────────────────
    def create_plan_review(self, payload, headers):
        return self._request("POST", "/plan-reviews", payload, headers)

    def list_plan_reviews(self, headers, params=None):
        return self._request("GET", "/plan-reviews", headers=headers, params=params)

    def get_plan_review(self, plan_review_id, headers):
        return self._request("GET", f"/plan-reviews/{plan_review_id}", headers=headers)

    def approve_plan_review(self, plan_review_id, headers):
        return self._request("POST", f"/plan-reviews/{plan_review_id}/approve", headers=headers)

    def reject_plan_review(self, plan_review_id, payload, headers):
        return self._request("POST", f"/plan-reviews/{plan_review_id}/reject", payload, headers)

    def resubmit_plan_review(self, plan_review_id, payload, headers):
        return self._request("POST", f"/plan-reviews/{plan_review_id}/resubmit", payload, headers)

    # ── Permits ────────────────────────────────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    # ── Inspection Routes ──────────────────────────────────────────────────
    def create_inspection_route(self, payload, headers):
        return self._request("POST", "/inspection-routes", payload, headers)

    def list_inspection_routes(self, headers, params=None):
        return self._request("GET", "/inspection-routes", headers=headers, params=params)

    def get_inspection_route(self, route_id, headers):
        return self._request("GET", f"/inspection-routes/{route_id}", headers=headers)

    def dispatch_inspection_route(self, route_id, headers):
        return self._request("POST", f"/inspection-routes/{route_id}/dispatch", headers=headers)

    def close_inspection_route(self, route_id, headers):
        return self._request("POST", f"/inspection-routes/{route_id}/close", headers=headers)

    # ── Inspections ────────────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/start", headers=headers)

    def complete_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", headers=headers)

    def reopen_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/reopen", headers=headers)

    def finalize_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/finalize", payload, headers)

    # ── Violations ─────────────────────────────────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def delete_violation(self, violation_id, headers):
        return self._request("DELETE", f"/violations/{violation_id}", headers=headers)

    # ── Closure Orders ─────────────────────────────────────────────────────
    def create_closure_order(self, payload, headers):
        return self._request("POST", "/closure-orders", payload, headers)

    def list_closure_orders(self, headers, params=None):
        return self._request("GET", "/closure-orders", headers=headers, params=params)

    def get_closure_order(self, closure_order_id, headers):
        return self._request("GET", f"/closure-orders/{closure_order_id}", headers=headers)

    def lift_closure_order(self, closure_order_id, headers):
        return self._request("POST", f"/closure-orders/{closure_order_id}/lift", headers=headers)

    # ── Complaints ─────────────────────────────────────────────────────────
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def triage_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/triage", headers=headers)

    def dispatch_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/dispatch", payload, headers)

    def close_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/close", headers=headers)

    # ── Enforcement Cases / Hearings ───────────────────────────────────────
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", "/enforcement-cases", payload, headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request("GET", "/enforcement-cases", headers=headers, params=params)

    def get_enforcement_case(self, case_id, headers):
        return self._request("GET", f"/enforcement-cases/{case_id}", headers=headers)

    def schedule_hearing(self, case_id, payload, headers):
        return self._request("POST", f"/enforcement-cases/{case_id}/schedule-hearing", payload, headers)

    def rule_enforcement_case(self, case_id, payload, headers):
        return self._request("POST", f"/enforcement-cases/{case_id}/rule", payload, headers)

    def settle_enforcement_case(self, case_id, headers):
        return self._request("POST", f"/enforcement-cases/{case_id}/settle", headers=headers)

    def close_enforcement_case(self, case_id, headers):
        return self._request("POST", f"/enforcement-cases/{case_id}/close", headers=headers)


api_client = ApiClient()
