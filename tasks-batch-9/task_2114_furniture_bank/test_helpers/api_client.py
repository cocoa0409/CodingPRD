"""API client: one method per endpoint defined in the PRD.

The API carries no path prefix, so every path below is used verbatim.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── operational / clock surface ───────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_cycle(self, payload, headers):
        return self._request("POST", "/_ops/run-cycle", payload, headers)

    # ─── agencies ──────────────────────────────────────────────────────

    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # ─── trucks ────────────────────────────────────────────────────────

    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    # ─── volunteers ────────────────────────────────────────────────────

    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteer_crew_assignments(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/crew-assignments",
            headers=headers, params=params,
        )

    # ─── clients (households) ──────────────────────────────────────────

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ─── referrals ─────────────────────────────────────────────────────

    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def submit_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/referrals/{referral_id}/submit", payload or {}, headers
        )

    def review_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/review", payload, headers
        )

    # ─── vouchers ──────────────────────────────────────────────────────

    def create_voucher(self, payload, headers):
        return self._request("POST", "/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def list_voucher_lines(self, voucher_id, headers, params=None):
        return self._request(
            "GET", f"/vouchers/{voucher_id}/lines", headers=headers, params=params
        )

    def list_voucher_stops(self, voucher_id, headers, params=None):
        return self._request(
            "GET", f"/vouchers/{voucher_id}/stops", headers=headers, params=params
        )

    def allocate_voucher(self, voucher_id, payload, headers):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/allocate", payload, headers
        )

    def settle_voucher_fee(self, voucher_id, payload, headers):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/fee-settlement", payload, headers
        )

    def cancel_voucher(self, voucher_id, payload, headers):
        return self._request(
            "POST", f"/vouchers/{voucher_id}/cancel", payload, headers
        )

    # ─── donation offers ───────────────────────────────────────────────

    def create_donation_offer(self, payload, headers):
        return self._request("POST", "/donation-offers", payload, headers)

    def get_donation_offer(self, offer_id, headers):
        return self._request("GET", f"/donation-offers/{offer_id}", headers=headers)

    def list_donation_offers(self, headers, params=None):
        return self._request("GET", "/donation-offers", headers=headers, params=params)

    def list_donation_items(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"/donation-offers/{offer_id}/items", headers=headers, params=params
        )

    def triage_donation_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/donation-offers/{offer_id}/triage", payload or {}, headers
        )

    def schedule_pickup(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/donation-offers/{offer_id}/schedule-pickup", payload, headers
        )

    def intake_donation_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/donation-offers/{offer_id}/intake", payload, headers
        )

    def release_quarantine(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/donation-offers/{offer_id}/quarantine-release",
            payload or {}, headers,
        )

    # ─── inventory ─────────────────────────────────────────────────────

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    # ─── delivery runs, stops, crew ────────────────────────────────────

    def create_delivery_run(self, payload, headers):
        return self._request("POST", "/delivery-runs", payload, headers)

    def get_delivery_run(self, run_id, headers):
        return self._request("GET", f"/delivery-runs/{run_id}", headers=headers)

    def list_delivery_runs(self, headers, params=None):
        return self._request("GET", "/delivery-runs", headers=headers, params=params)

    def create_delivery_stop(self, run_id, payload, headers):
        return self._request(
            "POST", f"/delivery-runs/{run_id}/stops", payload, headers
        )

    def list_run_stops(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/delivery-runs/{run_id}/stops", headers=headers, params=params
        )

    def create_crew_assignment(self, run_id, payload, headers):
        return self._request(
            "POST", f"/delivery-runs/{run_id}/crew", payload, headers
        )

    def list_run_crew(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/delivery-runs/{run_id}/crew", headers=headers, params=params
        )

    def respond_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/respond", payload, headers
        )

    def dispatch_delivery_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/delivery-runs/{run_id}/dispatch", payload or {}, headers
        )

    def record_stop_outcome(self, stop_id, payload, headers):
        return self._request(
            "POST", f"/delivery-stops/{stop_id}/outcome", payload, headers
        )

    # ─── waitlist & reporting ──────────────────────────────────────────

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def get_unmet_need_report(self, headers, params=None):
        return self._request("GET", "/reports/unmet-need", headers=headers, params=params)

    # ─── raw path helpers (for deliberately-unresolvable ids) ──────────

    def get_path(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def post_path(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
