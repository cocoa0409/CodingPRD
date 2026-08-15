"""API client: one method per endpoint defined in the PRD.

All routes are mounted under the /closet prefix per the PRD endpoint table.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (admin-only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/closet/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/closet/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/closet/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/closet/clients/{client_id}", headers=headers)

    def patch_client(self, client_id, payload, headers):
        return self._request("PATCH", f"/closet/clients/{client_id}", payload, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/closet/clients/{client_id}/suspend", {}, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/closet/clients/{client_id}/reinstate", {}, headers)

    # ------------------------------------------------------------------
    # Visits and distribution lines
    # ------------------------------------------------------------------
    def checkin_visit(self, client_id, payload, headers):
        return self._request("POST", f"/closet/clients/{client_id}/visits", payload, headers)

    def list_client_visits(self, client_id, headers, params=None):
        return self._request("GET", f"/closet/clients/{client_id}/visits",
                             headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/closet/visits/{visit_id}", headers=headers)

    def add_line(self, visit_id, payload, headers):
        return self._request("POST", f"/closet/visits/{visit_id}/lines", payload, headers)

    def checkout_visit(self, visit_id, headers):
        return self._request("POST", f"/closet/visits/{visit_id}/checkout", {}, headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/closet/visits/{visit_id}/void", {}, headers)

    def list_voucher_visits(self, voucher_id, headers):
        return self._request("GET", f"/closet/vouchers/{voucher_id}/visits", headers=headers)

    def get_distribution_line(self, line_id, headers):
        return self._request("GET", f"/closet/distribution-lines/{line_id}", headers=headers)

    def list_distribution_lines(self, headers, params=None):
        return self._request("GET", "/closet/distribution-lines", headers=headers, params=params)

    def delete_distribution_line(self, line_id, headers):
        return self._request("DELETE", f"/closet/distribution-lines/{line_id}", headers=headers)

    def return_distribution_line(self, line_id, headers):
        return self._request("POST", f"/closet/distribution-lines/{line_id}/return", {}, headers)

    # ------------------------------------------------------------------
    # Donation batches and items
    # ------------------------------------------------------------------
    def create_donation_batch(self, payload, headers):
        return self._request("POST", "/closet/donation-batches", payload, headers)

    def get_donation_batch(self, batch_id, headers):
        return self._request("GET", f"/closet/donation-batches/{batch_id}", headers=headers)

    def start_sorting(self, batch_id, headers):
        return self._request("POST", f"/closet/donation-batches/{batch_id}/start-sorting",
                             {}, headers)

    def create_batch_item(self, batch_id, payload, headers):
        return self._request("POST", f"/closet/donation-batches/{batch_id}/items",
                             payload, headers)

    def close_donation_batch(self, batch_id, headers):
        return self._request("POST", f"/closet/donation-batches/{batch_id}/close", {}, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/closet/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/closet/items", headers=headers, params=params)

    def stock_item(self, item_id, payload, headers):
        return self._request("POST", f"/closet/items/{item_id}/stock", payload, headers)

    def quarantine_item(self, item_id, headers):
        return self._request("POST", f"/closet/items/{item_id}/quarantine", {}, headers)

    def release_quarantine(self, item_id, payload, headers):
        return self._request("POST", f"/closet/items/{item_id}/release-quarantine",
                             payload, headers)

    # ------------------------------------------------------------------
    # Storage zones
    # ------------------------------------------------------------------
    def create_storage_zone(self, payload, headers):
        return self._request("POST", "/closet/storage-zones", payload, headers)

    def get_storage_zone(self, zone_id, headers):
        return self._request("GET", f"/closet/storage-zones/{zone_id}", headers=headers)

    def list_storage_zones(self, headers, params=None):
        return self._request("GET", "/closet/storage-zones", headers=headers, params=params)

    def patch_storage_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/closet/storage-zones/{zone_id}", payload, headers)

    # ------------------------------------------------------------------
    # Seasonal rotations
    # ------------------------------------------------------------------
    def create_seasonal_rotation(self, payload, headers):
        return self._request("POST", "/closet/seasonal-rotations", payload, headers)

    def get_seasonal_rotation(self, rotation_id, headers):
        return self._request("GET", f"/closet/seasonal-rotations/{rotation_id}", headers=headers)

    def execute_rotation(self, rotation_id, headers):
        return self._request("POST", f"/closet/seasonal-rotations/{rotation_id}/execute",
                             {}, headers)

    def cancel_rotation(self, rotation_id, headers):
        return self._request("POST", f"/closet/seasonal-rotations/{rotation_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Volunteers, shifts, signups
    # ------------------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/closet/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/closet/volunteers/{volunteer_id}", headers=headers)

    def list_volunteer_signups(self, volunteer_id, headers, params=None):
        return self._request("GET", f"/closet/volunteers/{volunteer_id}/signups",
                             headers=headers, params=params)

    def create_shift(self, payload, headers):
        return self._request("POST", "/closet/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/closet/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/closet/shifts/{shift_id}/cancel", {}, headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/closet/shifts/{shift_id}/complete", {}, headers)

    def create_signup(self, shift_id, payload, headers):
        return self._request("POST", f"/closet/shifts/{shift_id}/signups", payload, headers)

    def list_shift_signups(self, shift_id, headers, params=None):
        return self._request("GET", f"/closet/shifts/{shift_id}/signups",
                             headers=headers, params=params)

    def cancel_signup(self, shift_id, signup_id, headers):
        return self._request("POST", f"/closet/shifts/{shift_id}/signups/{signup_id}/cancel",
                             {}, headers)

    def checkin_signup(self, shift_id, signup_id, headers):
        return self._request("POST", f"/closet/shifts/{shift_id}/signups/{signup_id}/check-in",
                             {}, headers)

    # ------------------------------------------------------------------
    # Referral partners and vouchers
    # ------------------------------------------------------------------
    def create_referral_partner(self, payload, headers):
        return self._request("POST", "/closet/referral-partners", payload, headers)

    def get_referral_partner(self, partner_id, headers):
        return self._request("GET", f"/closet/referral-partners/{partner_id}", headers=headers)

    def suspend_referral_partner(self, partner_id, headers):
        return self._request("POST", f"/closet/referral-partners/{partner_id}/suspend",
                             {}, headers)

    def issue_voucher(self, partner_id, payload, headers):
        return self._request("POST", f"/closet/referral-partners/{partner_id}/vouchers",
                             payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/closet/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/closet/vouchers", headers=headers, params=params)

    def revoke_voucher(self, voucher_id, headers):
        return self._request("POST", f"/closet/vouchers/{voucher_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Special drives
    # ------------------------------------------------------------------
    def create_drive(self, payload, headers):
        return self._request("POST", "/closet/drives", payload, headers)

    def get_drive(self, drive_id, headers):
        return self._request("GET", f"/closet/drives/{drive_id}", headers=headers)

    def close_drive(self, drive_id, headers):
        return self._request("POST", f"/closet/drives/{drive_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Recycling batches
    # ------------------------------------------------------------------
    def create_recycling_batch(self, payload, headers):
        return self._request("POST", "/closet/recycling-batches", payload, headers)

    def get_recycling_batch(self, batch_id, headers):
        return self._request("GET", f"/closet/recycling-batches/{batch_id}", headers=headers)

    def sweep_recycling_batch(self, batch_id, headers):
        return self._request("POST", f"/closet/recycling-batches/{batch_id}/sweep", {}, headers)

    def seal_recycling_batch(self, batch_id, headers):
        return self._request("POST", f"/closet/recycling-batches/{batch_id}/seal", {}, headers)

    def pickup_recycling_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/closet/recycling-batches/{batch_id}/pickup",
                             payload, headers)

    # ------------------------------------------------------------------
    # Impact report
    # ------------------------------------------------------------------
    def get_impact_report(self, zone_id, headers):
        return self._request("GET", "/closet/reports/impact",
                             headers=headers, params={"zone_id": zone_id})


api_client = ApiClient()
