"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System / clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def submit_insurance(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/insurance", payload, headers)

    def create_payment(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/payments", payload, headers)

    # --- Commissary ---
    def create_commissary(self, payload, headers):
        return self._request("POST", "/commissaries", payload, headers)

    def get_commissary(self, commissary_id, headers):
        return self._request("GET", f"/commissaries/{commissary_id}", headers=headers)

    def update_commissary(self, commissary_id, payload, headers):
        return self._request("PATCH", f"/commissaries/{commissary_id}", payload, headers)

    # --- Cart ---
    def create_cart(self, payload, headers):
        return self._request("POST", "/carts", payload, headers)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", "/carts", headers=headers, params=params)

    def inspect_cart(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/inspect", payload, headers)

    def approve_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/approve", {}, headers)

    # --- Zone / Spot ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def create_spot(self, zone_id, payload, headers):
        return self._request("POST", f"/zones/{zone_id}/spots", payload, headers)

    def list_spots(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/spots", headers=headers, params=params)

    def get_spot(self, spot_id, headers):
        return self._request("GET", f"/spots/{spot_id}", headers=headers)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def suspend_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/suspend", payload or {}, headers)

    def reinstate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reinstate", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    def renew_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/renew", {}, headers)

    # --- Violations under a permit ---
    def create_violation(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/violations", payload, headers)

    def list_violations(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/violations", headers=headers, params=params)

    # --- Complaints under a permit ---
    def create_complaint(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/complaints", payload, headers)

    def list_complaints(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/complaints", headers=headers, params=params)

    # --- Violation top-level ---
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def contest_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/contest", {}, headers)

    def withdraw_contest_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/withdraw-contest", {}, headers)

    def adjudicate_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/adjudicate", payload, headers)

    # --- Impounds under a cart ---
    def create_impound(self, cart_id, payload, headers):
        return self._request("POST", f"/carts/{cart_id}/impounds", payload, headers)

    def list_impounds(self, cart_id, headers, params=None):
        return self._request("GET", f"/carts/{cart_id}/impounds", headers=headers, params=params)

    def get_impound(self, impound_id, headers):
        return self._request("GET", f"/impounds/{impound_id}", headers=headers)

    def release_impound(self, impound_id, payload, headers):
        return self._request("POST", f"/impounds/{impound_id}/release", payload, headers)

    def forfeit_impound(self, impound_id, payload, headers):
        return self._request("POST", f"/impounds/{impound_id}/forfeit", payload, headers)

    # --- Complaint top-level ---
    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)

    # --- Lottery ---
    def create_lottery(self, payload, headers):
        return self._request("POST", "/lotteries", payload, headers)

    def get_lottery(self, lottery_id, headers):
        return self._request("GET", f"/lotteries/{lottery_id}", headers=headers)

    def list_lotteries(self, headers, params=None):
        return self._request("GET", "/lotteries", headers=headers, params=params)

    def create_lottery_entry(self, lottery_id, payload, headers):
        return self._request("POST", f"/lotteries/{lottery_id}/entries", payload, headers)

    def draw_lottery(self, lottery_id, headers):
        return self._request("POST", f"/lotteries/{lottery_id}/draw", {}, headers)

    def get_lottery_entry(self, entry_id, headers):
        return self._request("GET", f"/lottery-entries/{entry_id}", headers=headers)

    def list_lottery_entries(self, headers, params=None):
        return self._request("GET", "/lottery-entries", headers=headers, params=params)

    # --- SpotAssignment ---
    def create_spot_assignment(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/spot-assignments", payload, headers)

    def get_spot_assignment(self, assignment_id, headers):
        return self._request("GET", f"/spot-assignments/{assignment_id}", headers=headers)

    def list_spot_assignments(self, headers, params=None):
        return self._request("GET", "/spot-assignments", headers=headers, params=params)

    def release_spot_assignment(self, assignment_id, headers):
        return self._request("POST", f"/spot-assignments/{assignment_id}/release", {}, headers)


api_client = ApiClient()
