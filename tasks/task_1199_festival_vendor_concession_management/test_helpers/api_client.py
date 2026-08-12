"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Festival ---
    def create_festival(self, payload, headers):
        return self._request("POST", "/festivals", payload, headers)

    def list_festivals(self, headers, params=None):
        return self._request("GET", "/festivals", headers=headers, params=params)

    def get_festival(self, festival_id, headers):
        return self._request("GET", f"/festivals/{festival_id}", headers=headers)

    def advance_festival_status(self, festival_id, payload, headers):
        return self._request("POST", f"/festivals/{festival_id}/advance-status", payload, headers)

    def sweep_operations(self, festival_id, headers):
        return self._request("POST", f"/festivals/{festival_id}/sweep-operations", {}, headers)

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    # --- VendorApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", "/vendor-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/vendor-applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/vendor-applications/{application_id}", headers=headers)

    def start_review(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/start-review", {}, headers)

    def request_changes(self, application_id, payload, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/request-changes", payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/decide", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/vendor-applications/{application_id}/withdraw", {}, headers)

    # --- Zone ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    # --- Booth ---
    def create_booth(self, payload, headers):
        return self._request("POST", "/booths", payload, headers)

    def list_booths(self, headers, params=None):
        return self._request("GET", "/booths", headers=headers, params=params)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    # --- BoothAssignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/booth-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/booth-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/booth-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/confirm", {}, headers)

    def reassign_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/reassign", payload, headers)

    def provision_utilities(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/provision-utilities", {}, headers)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/activate", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/booth-assignments/{assignment_id}/release", {}, headers)

    # --- InspectionRecord ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspection-records", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspection-records", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspection-records/{inspection_id}", headers=headers)

    # --- LoadInSlot ---
    def create_slot(self, payload, headers):
        return self._request("POST", "/load-in-slots", payload, headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/load-in-slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/load-in-slots/{slot_id}", headers=headers)

    # --- LoadInReservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/load-in-reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/load-in-reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/load-in-reservations/{reservation_id}", headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/load-in-reservations/{reservation_id}/check-in", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/load-in-reservations/{reservation_id}/cancel", {}, headers)

    # --- PosTransaction ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/pos-transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/pos-transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/pos-transactions/{transaction_id}", headers=headers)

    def void_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"/pos-transactions/{transaction_id}/void", payload, headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def reconcile_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/reconcile", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/dispute", payload, headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/finalize", {}, headers)

    def mark_paid_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/mark-paid", {}, headers)

    # --- ComplianceFine ---
    def create_fine(self, payload, headers):
        return self._request("POST", "/compliance-fines", payload, headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/compliance-fines", headers=headers, params=params)

    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/compliance-fines/{fine_id}", headers=headers)

    def respond_fine(self, fine_id, payload, headers):
        return self._request("POST", f"/compliance-fines/{fine_id}/respond", payload, headers)

    def waive_fine(self, fine_id, headers):
        return self._request("POST", f"/compliance-fines/{fine_id}/waive", {}, headers)

    def mark_paid_fine(self, fine_id, headers):
        return self._request("POST", f"/compliance-fines/{fine_id}/mark-paid", {}, headers)

    # --- PerformanceReview ---
    def list_reviews(self, headers, params=None):
        return self._request("GET", "/performance-reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/performance-reviews/{review_id}", headers=headers)

    def compute_score(self, review_id, headers):
        return self._request("POST", f"/performance-reviews/{review_id}/compute-score", {}, headers)

    def issue_invitation(self, review_id, headers):
        return self._request("POST", f"/performance-reviews/{review_id}/issue-invitation", {}, headers)

    def respond_review(self, review_id, payload, headers):
        return self._request("POST", f"/performance-reviews/{review_id}/respond", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
