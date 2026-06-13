"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Patrons ─────────────────────────────────────────────────────────────
    def create_patron(self, payload, headers):
        return self._request("POST", "/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/patrons/{patron_id}", headers=headers)

    def verify_residency(self, patron_id, headers):
        return self._request("POST", f"/patrons/{patron_id}/verify-residency", {}, headers)

    def list_patron_permits(self, patron_id, headers, params=None):
        return self._request("GET", f"/patrons/{patron_id}/permits", headers=headers, params=params)

    def list_patron_insurance_certificates(self, patron_id, headers, params=None):
        return self._request("GET", f"/patrons/{patron_id}/insurance-certificates",
                             headers=headers, params=params)

    # ─── Facilities ──────────────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/facilities/{facility_id}", payload, headers)

    def list_facility_permits(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/permits",
                             headers=headers, params=params)

    # ─── Insurance Certificates (COI) ────────────────────────────────────────
    def create_insurance_certificate(self, payload, headers):
        return self._request("POST", "/insurance-certificates", payload, headers)

    def get_insurance_certificate(self, coi_id, headers):
        return self._request("GET", f"/insurance-certificates/{coi_id}", headers=headers)

    def list_insurance_certificates(self, headers, params=None):
        return self._request("GET", "/insurance-certificates", headers=headers, params=params)

    def revoke_insurance_certificate(self, coi_id, headers):
        return self._request("POST", f"/insurance-certificates/{coi_id}/revoke", {}, headers)

    # ─── Permits ─────────────────────────────────────────────────────────────
    def apply_permit(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def refund_preview(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}/refund-preview", headers=headers)

    def grant_permit(self, facility_id, permit_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits/{permit_id}/grant",
                             payload, headers)

    def deny_permit(self, facility_id, permit_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits/{permit_id}/deny",
                             {}, headers)

    def cancel_permit(self, facility_id, permit_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits/{permit_id}/cancel",
                             payload, headers)

    def complete_permit(self, facility_id, permit_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits/{permit_id}/complete",
                             {}, headers)

    def no_show_permit(self, facility_id, permit_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/permits/{permit_id}/no-show",
                             {}, headers)

    # ─── Payments ────────────────────────────────────────────────────────────
    def create_payment(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/payments", payload, headers)

    def list_permit_payments(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ─── Refunds ─────────────────────────────────────────────────────────────
    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_permit_refunds(self, permit_id, headers, params=None):
        return self._request("GET", f"/permits/{permit_id}/refunds", headers=headers, params=params)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    # ─── League Series ───────────────────────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_league_permits(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/permits", headers=headers, params=params)

    def cancel_league(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/cancel", payload, headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    # ─── Lottery ─────────────────────────────────────────────────────────────
    def create_lottery_round(self, payload, headers):
        return self._request("POST", "/lottery-rounds", payload, headers)

    def get_lottery_round(self, lottery_round_id, headers):
        return self._request("GET", f"/lottery-rounds/{lottery_round_id}", headers=headers)

    def create_lottery_entry(self, lottery_round_id, payload, headers):
        return self._request("POST", f"/lottery-rounds/{lottery_round_id}/entries", payload, headers)

    def list_lottery_round_entries(self, lottery_round_id, headers, params=None):
        return self._request("GET", f"/lottery-rounds/{lottery_round_id}/entries",
                             headers=headers, params=params)

    def get_lottery_entry(self, lottery_entry_id, headers):
        return self._request("GET", f"/lottery-entries/{lottery_entry_id}", headers=headers)

    def withdraw_lottery_entry(self, lottery_entry_id, headers):
        return self._request("POST", f"/lottery-entries/{lottery_entry_id}/withdraw", {}, headers)

    def draw_lottery_round(self, lottery_round_id, payload, headers):
        return self._request("POST", f"/lottery-rounds/{lottery_round_id}/draw", payload, headers)

    def cancel_lottery_round(self, lottery_round_id, headers):
        return self._request("POST", f"/lottery-rounds/{lottery_round_id}/cancel", {}, headers)

    def list_lottery_entries(self, headers, params=None):
        return self._request("GET", "/lottery-entries", headers=headers, params=params)

    def list_lottery_rounds(self, headers, params=None):
        return self._request("GET", "/lottery-rounds", headers=headers, params=params)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    # ─── Test-driving / ops ──────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def ops_sweep(self, headers):
        return self._request("POST", "/_ops/sweep", {}, headers)

    def inject_no_show_strikes(self, patron_id, strikes, headers):
        return self._request("POST", "/_inject/no_show_strikes",
                             {"patron_id": patron_id, "strikes": strikes}, headers)


api_client = ApiClient()
