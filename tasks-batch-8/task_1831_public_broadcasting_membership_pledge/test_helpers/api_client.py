"""API client: one method per endpoint defined in the PRD (all under /station)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/station/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Membership levels
    # ------------------------------------------------------------------
    def create_membership_level(self, payload, headers):
        return self._request("POST", "/station/membership-levels", payload, headers)

    def list_membership_levels(self, headers, params=None):
        return self._request("GET", "/station/membership-levels",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Premiums and inventory lots
    # ------------------------------------------------------------------
    def create_premium(self, payload, headers):
        return self._request("POST", "/station/premiums", payload, headers)

    def get_premium(self, premium_id, headers):
        return self._request("GET", f"/station/premiums/{premium_id}",
                             headers=headers)

    def create_lot(self, premium_id, payload, headers):
        return self._request("POST", f"/station/premiums/{premium_id}/lots",
                             payload, headers)

    def list_lots(self, premium_id, headers, params=None):
        return self._request("GET", f"/station/premiums/{premium_id}/lots",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Donors and memberships
    # ------------------------------------------------------------------
    def create_donor(self, payload, headers):
        return self._request("POST", "/station/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/station/donors/{donor_id}", headers=headers)

    def list_donor_memberships(self, donor_id, headers, params=None):
        return self._request("GET", f"/station/donors/{donor_id}/memberships",
                             headers=headers, params=params)

    def create_membership(self, payload, headers):
        return self._request("POST", "/station/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/station/memberships/{membership_id}",
                             headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/station/memberships",
                             headers=headers, params=params)

    def reinstate_membership(self, membership_id, headers):
        return self._request("POST",
                             f"/station/memberships/{membership_id}/reinstate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Pledge drives and on-air breaks
    # ------------------------------------------------------------------
    def create_drive(self, payload, headers):
        return self._request("POST", "/station/pledge-drives", payload, headers)

    def get_drive(self, drive_id, headers):
        return self._request("GET", f"/station/pledge-drives/{drive_id}",
                             headers=headers)

    def create_break(self, drive_id, payload, headers):
        return self._request("POST", f"/station/pledge-drives/{drive_id}/breaks",
                             payload, headers)

    def list_breaks(self, drive_id, headers, params=None):
        return self._request("GET", f"/station/pledge-drives/{drive_id}/breaks",
                             headers=headers, params=params)

    def schedule_drive(self, drive_id, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/schedule",
                             {}, headers)

    def unschedule_drive(self, drive_id, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/unschedule",
                             {}, headers)

    def go_live_drive(self, drive_id, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/go-live",
                             {}, headers)

    def close_drive(self, drive_id, headers):
        return self._request("POST", f"/station/pledge-drives/{drive_id}/close",
                             {}, headers)

    def reconcile_drive(self, drive_id, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/reconcile",
                             {}, headers)

    # ------------------------------------------------------------------
    # Pledges, payments, and premium fulfillment
    # ------------------------------------------------------------------
    def create_pledge(self, payload, headers):
        return self._request("POST", "/station/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/station/pledges/{pledge_id}",
                             headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/station/pledges", headers=headers,
                             params=params)

    def post_payment(self, pledge_id, payload, headers):
        return self._request("POST", f"/station/pledges/{pledge_id}/payments",
                             payload, headers)

    def decline_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/station/pledges/{pledge_id}/decline",
                             payload, headers)

    def write_off_pledge(self, pledge_id, payload, headers):
        return self._request("POST", f"/station/pledges/{pledge_id}/write-off",
                             payload, headers)

    def create_premium_reservation(self, pledge_id, payload, headers):
        return self._request("POST",
                             f"/station/pledges/{pledge_id}/premium-reservations",
                             payload, headers)

    def list_pledge_reservations(self, pledge_id, headers, params=None):
        return self._request("GET",
                             f"/station/pledges/{pledge_id}/premium-reservations",
                             headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET",
                             f"/station/premium-reservations/{reservation_id}",
                             headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/station/premium-reservations",
                             headers=headers, params=params)

    def ship_premium(self, pledge_id, headers):
        return self._request("POST",
                             f"/station/pledges/{pledge_id}/ship-premium",
                             {}, headers)

    def waive_premium(self, pledge_id, headers):
        return self._request("POST",
                             f"/station/pledges/{pledge_id}/waive-premium",
                             {}, headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST",
                             f"/station/premium-reservations/{reservation_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Matching challenges and underwriting credits
    # ------------------------------------------------------------------
    def create_matching_challenge(self, drive_id, payload, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/matching-challenges",
                             payload, headers)

    def list_matching_challenges(self, drive_id, headers, params=None):
        return self._request("GET",
                             f"/station/pledge-drives/{drive_id}/matching-challenges",
                             headers=headers, params=params)

    def get_matching_challenge(self, challenge_id, headers):
        return self._request("GET",
                             f"/station/matching-challenges/{challenge_id}",
                             headers=headers)

    def create_underwriting_credit(self, drive_id, payload, headers):
        return self._request("POST",
                             f"/station/pledge-drives/{drive_id}/underwriting-credits",
                             payload, headers)

    def list_underwriting_credits(self, drive_id, headers, params=None):
        return self._request("GET",
                             f"/station/pledge-drives/{drive_id}/underwriting-credits",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # NFFS reports
    # ------------------------------------------------------------------
    def create_nffs_report(self, payload, headers):
        return self._request("POST", "/station/nffs-reports", payload, headers)

    def get_nffs_report(self, report_id, headers):
        return self._request("GET", f"/station/nffs-reports/{report_id}",
                             headers=headers)

    def finalize_nffs_report(self, report_id, headers):
        return self._request("POST",
                             f"/station/nffs-reports/{report_id}/finalize",
                             {}, headers)

    def amend_nffs_report(self, report_id, headers):
        return self._request("POST",
                             f"/station/nffs-reports/{report_id}/amend",
                             {}, headers)


api_client = ApiClient()
