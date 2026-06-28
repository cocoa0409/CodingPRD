"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ---- MembershipTier ----
    def create_tier(self, payload, headers):
        return self._request("POST", "/membership-tiers", payload, headers=headers)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/membership-tiers/{tier_id}", headers=headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/membership-tiers", headers=headers, params=params)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def sign_waiver(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/sign-waiver", {}, headers=headers)

    def topup(self, member_id, amount_cents, headers):
        return self._request(
            "POST", f"/members/{member_id}/topup", {"amount_cents": amount_cents}, headers=headers
        )

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/activate", {}, headers=headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers=headers)

    def cancel_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/cancel", {}, headers=headers)

    def buy_daypass(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/buy-daypass", {}, headers=headers)

    def roll_cycle(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/roll-cycle", {}, headers=headers)

    # ---- WalletEntry ----
    def get_wallet_entry(self, entry_id, headers):
        return self._request("GET", f"/wallet-entries/{entry_id}", headers=headers)

    def list_wallet_entries(self, headers, params=None):
        return self._request("GET", "/wallet-entries", headers=headers, params=params)

    # ---- Machine ----
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers=headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def set_machine_status(self, machine_id, operational_status, headers):
        return self._request(
            "POST",
            f"/machines/{machine_id}/set-status",
            {"operational_status": operational_status},
            headers=headers,
        )

    # ---- Certification ----
    def create_certification(self, payload, headers):
        return self._request("POST", "/certifications", payload, headers=headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def refresh_expiry(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/refresh-expiry", {}, headers=headers)

    def renew_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/renew", {}, headers=headers)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"/certifications/{cert_id}/revoke", {}, headers=headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, expected_member_version, headers):
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/confirm",
            {"expected_member_version": expected_member_version},
            headers=headers,
        )

    def release_hold(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/release-hold", {}, headers=headers)

    def check_in(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers=headers)

    def check_out(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-out", {}, headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers=headers)

    def mark_no_show(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/mark-no-show", {}, headers=headers)

    # ---- Locker ----
    def create_locker(self, payload, headers):
        return self._request("POST", "/lockers", payload, headers=headers)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/lockers/{locker_id}", headers=headers)

    def list_lockers(self, headers, params=None):
        return self._request("GET", "/lockers", headers=headers, params=params)

    def update_locker(self, locker_id, payload, headers):
        return self._request("PATCH", f"/lockers/{locker_id}", payload, headers=headers)

    def release_locker(self, locker_id, headers):
        return self._request("POST", f"/lockers/{locker_id}/release", {}, headers=headers)

    # ---- MaterialItem ----
    def create_material_item(self, payload, headers):
        return self._request("POST", "/material-items", payload, headers=headers)

    def get_material_item(self, item_id, headers):
        return self._request("GET", f"/material-items/{item_id}", headers=headers)

    def list_material_items(self, headers, params=None):
        return self._request("GET", "/material-items", headers=headers, params=params)

    # ---- MaterialPurchase ----
    def create_material_purchase(self, payload, headers):
        return self._request("POST", "/material-purchases", payload, headers=headers)

    def get_material_purchase(self, purchase_id, headers):
        return self._request("GET", f"/material-purchases/{purchase_id}", headers=headers)

    def list_material_purchases(self, headers, params=None):
        return self._request("GET", "/material-purchases", headers=headers, params=params)

    def bill_purchase(self, purchase_id, headers):
        return self._request("POST", f"/material-purchases/{purchase_id}/bill", {}, headers=headers)

    def void_purchase(self, purchase_id, headers):
        return self._request("POST", f"/material-purchases/{purchase_id}/void", {}, headers=headers)

    # ---- Workshop ----
    def create_workshop(self, payload, headers):
        return self._request("POST", "/workshops", payload, headers=headers)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}", headers=headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/workshops", headers=headers, params=params)

    def start_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/start", {}, headers=headers)

    def complete_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/complete", {}, headers=headers)

    def cancel_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/cancel", {}, headers=headers)

    # ---- WorkshopEnrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/workshop-enrollments", payload, headers=headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/workshop-enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/workshop-enrollments", headers=headers, params=params)

    def mark_attended(self, enrollment_id, headers):
        return self._request(
            "POST", f"/workshop-enrollments/{enrollment_id}/mark-attended", {}, headers=headers
        )

    def mark_enrollment_no_show(self, enrollment_id, headers):
        return self._request(
            "POST", f"/workshop-enrollments/{enrollment_id}/mark-no-show", {}, headers=headers
        )

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/workshop-enrollments/{enrollment_id}/withdraw", {}, headers=headers
        )


api_client = ApiClient()
