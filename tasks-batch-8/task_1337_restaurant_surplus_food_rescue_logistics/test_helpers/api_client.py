"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- DonorSite ---
    def create_donor_site(self, payload, headers):
        return self._request("POST", "/api/donor-sites", payload, headers)

    def get_donor_site(self, donor_id, headers):
        return self._request("GET", f"/api/donor-sites/{donor_id}", headers=headers)

    def patch_donor_site_status(self, donor_id, target_status, headers):
        return self._request(
            "PATCH",
            f"/api/donor-sites/{donor_id}/status",
            {"target_status": target_status},
            headers,
        )

    def list_donor_offers(self, donor_id, headers, params=None):
        return self._request(
            "GET", f"/api/donor-sites/{donor_id}/donation-offers",
            headers=headers, params=params,
        )

    def list_donor_tax_receipts(self, donor_id, headers, params=None):
        return self._request(
            "GET", f"/api/donor-sites/{donor_id}/tax-receipts",
            headers=headers, params=params,
        )

    def issue_tax_receipt(self, donor_id, payload, headers):
        return self._request(
            "POST", f"/api/donor-sites/{donor_id}/tax-receipts", payload, headers
        )

    # --- RecipientAgency ---
    def create_recipient_agency(self, payload, headers):
        return self._request("POST", "/api/recipient-agencies", payload, headers)

    def get_recipient_agency(self, agency_id, headers):
        return self._request(
            "GET", f"/api/recipient-agencies/{agency_id}", headers=headers
        )

    # --- VolunteerDriver ---
    def create_volunteer_driver(self, payload, headers):
        return self._request("POST", "/api/volunteer-drivers", payload, headers)

    def get_volunteer_driver(self, driver_id, headers):
        return self._request(
            "GET", f"/api/volunteer-drivers/{driver_id}", headers=headers
        )

    def patch_volunteer_driver_status(self, driver_id, target_status, headers):
        return self._request(
            "PATCH",
            f"/api/volunteer-drivers/{driver_id}/status",
            {"target_status": target_status},
            headers,
        )

    def create_availability_window(self, driver_id, payload, headers):
        return self._request(
            "POST",
            f"/api/volunteer-drivers/{driver_id}/availability-windows",
            payload,
            headers,
        )

    def list_availability_windows(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/api/volunteer-drivers/{driver_id}/availability-windows",
            headers=headers, params=params,
        )

    # --- Cooler ---
    def create_cooler(self, payload, headers):
        return self._request("POST", "/api/coolers", payload, headers)

    def get_cooler(self, cooler_id, headers):
        return self._request("GET", f"/api/coolers/{cooler_id}", headers=headers)

    def list_cooler_reservations(self, cooler_id, headers, params=None):
        return self._request(
            "GET", f"/api/coolers/{cooler_id}/cooler-reservations",
            headers=headers, params=params,
        )

    # --- DonationOffer ---
    def create_donation_offer(self, payload, headers):
        return self._request("POST", "/api/donation-offers", payload, headers)

    def get_donation_offer(self, offer_id, headers):
        return self._request(
            "GET", f"/api/donation-offers/{offer_id}", headers=headers
        )

    def patch_donation_offer_status(self, offer_id, target_status, headers):
        return self._request(
            "PATCH",
            f"/api/donation-offers/{offer_id}/status",
            {"target_status": target_status},
            headers,
        )

    # --- RescueRun ---
    def create_rescue_run(self, payload, headers):
        return self._request("POST", "/api/rescue-runs", payload, headers)

    def list_rescue_runs(self, headers, params=None):
        return self._request("GET", "/api/rescue-runs", headers=headers, params=params)

    def get_rescue_run(self, run_id, headers):
        return self._request("GET", f"/api/rescue-runs/{run_id}", headers=headers)

    def respond_rescue_run(self, run_id, decision, headers):
        return self._request(
            "POST", f"/api/rescue-runs/{run_id}/respond", {"decision": decision}, headers
        )

    def record_pickup(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/rescue-runs/{run_id}/record-pickup", payload, headers
        )

    def fail_rescue_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/rescue-runs/{run_id}/fail", payload, headers
        )

    def record_delivery(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/rescue-runs/{run_id}/record-delivery", payload, headers
        )

    def verify_delivery(self, run_id, headers):
        return self._request(
            "POST", f"/api/rescue-runs/{run_id}/verify-delivery", headers=headers
        )

    def list_temperature_logs(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/api/rescue-runs/{run_id}/temperature-logs",
            headers=headers, params=params,
        )

    def list_run_cooler_reservations(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/api/rescue-runs/{run_id}/cooler-reservations",
            headers=headers, params=params,
        )

    def list_run_strike_reports(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/api/rescue-runs/{run_id}/strike-reports",
            headers=headers, params=params,
        )

    # --- StrikeReport ---
    def adjudicate_strike_report(self, strike_id, outcome, headers):
        return self._request(
            "POST",
            f"/api/strike-reports/{strike_id}/adjudicate",
            {"outcome": outcome},
            headers,
        )

    # --- RateCard ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/api/rate-cards", payload, headers)


api_client = ApiClient()
