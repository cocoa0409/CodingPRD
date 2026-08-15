"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.9) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Shipper ---
    def create_shipper(self, payload, headers):
        return self._request("POST", "/air-freight/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/air-freight/shippers/{shipper_id}", headers=headers)

    def verify_known_shipper(self, shipper_id, headers):
        return self._request(
            "POST", f"/air-freight/shippers/{shipper_id}/verify-known-shipper", headers=headers
        )

    def list_shipper_rate_agreements(self, shipper_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/shippers/{shipper_id}/rate-agreements",
            headers=headers, params=params,
        )

    # --- RateAgreement ---
    def create_rate_agreement(self, payload, headers):
        return self._request("POST", "/air-freight/rate-agreements", payload, headers)

    # --- FlightBooking ---
    def create_flight_booking(self, payload, headers):
        return self._request("POST", "/air-freight/flight-bookings", payload, headers)

    def get_flight_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/air-freight/flight-bookings/{booking_id}", headers=headers
        )

    def cancel_flight_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/air-freight/flight-bookings/{booking_id}/cancel", headers=headers
        )

    def list_booking_master_waybills(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/flight-bookings/{booking_id}/master-waybills",
            headers=headers, params=params,
        )

    # --- MasterWaybill ---
    def create_master_waybill(self, payload, headers):
        return self._request("POST", "/air-freight/master-waybills", payload, headers)

    def get_master_waybill(self, mawb_id, headers):
        return self._request("GET", f"/air-freight/master-waybills/{mawb_id}", headers=headers)

    def open_master_waybill(self, mawb_id, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/open", headers=headers
        )

    def consolidate_house_waybill(self, mawb_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/house-waybills", payload, headers
        )

    def deconsolidate_house_waybill(self, mawb_id, hwb_id, headers):
        return self._request(
            "DELETE",
            f"/air-freight/master-waybills/{mawb_id}/house-waybills/{hwb_id}",
            headers=headers,
        )

    def tender_master_waybill(self, mawb_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/tender", payload, headers
        )

    def void_master_waybill(self, mawb_id, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/void", headers=headers
        )

    def close_master_waybill(self, mawb_id, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/close", headers=headers
        )

    def record_milestone_event(self, mawb_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/master-waybills/{mawb_id}/milestone-events",
            payload, headers,
        )

    def list_milestone_events(self, mawb_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/master-waybills/{mawb_id}/milestone-events",
            headers=headers, params=params,
        )

    # --- HouseWaybill ---
    def create_house_waybill(self, payload, headers):
        return self._request("POST", "/air-freight/house-waybills", payload, headers)

    def list_house_waybills(self, headers, params=None):
        return self._request("GET", "/air-freight/house-waybills", headers=headers, params=params)

    def get_house_waybill(self, hwb_id, headers):
        return self._request("GET", f"/air-freight/house-waybills/{hwb_id}", headers=headers)

    def submit_house_waybill(self, hwb_id, headers):
        return self._request(
            "POST", f"/air-freight/house-waybills/{hwb_id}/submit", headers=headers
        )

    def recall_house_waybill(self, hwb_id, headers):
        return self._request(
            "POST", f"/air-freight/house-waybills/{hwb_id}/recall", headers=headers
        )

    def cancel_house_waybill(self, hwb_id, headers):
        return self._request(
            "POST", f"/air-freight/house-waybills/{hwb_id}/cancel", headers=headers
        )

    def measure_house_waybill(self, hwb_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/house-waybills/{hwb_id}/measure", payload, headers
        )

    def list_screening_records(self, hwb_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/house-waybills/{hwb_id}/screening-records",
            headers=headers, params=params,
        )

    def list_house_waybill_customs_entries(self, hwb_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/house-waybills/{hwb_id}/customs-entries",
            headers=headers, params=params,
        )

    def list_house_waybill_claims(self, hwb_id, headers, params=None):
        return self._request(
            "GET", f"/air-freight/house-waybills/{hwb_id}/claims",
            headers=headers, params=params,
        )

    # --- ScreeningRecord ---
    def resolve_screening_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/screening-records/{record_id}/resolve", payload, headers
        )

    # --- CustomsEntry ---
    def create_customs_entry(self, hwb_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/house-waybills/{hwb_id}/customs-entries", payload, headers
        )

    def transition_customs_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/customs-entries/{entry_id}/transition", payload, headers
        )

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/air-freight/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/air-freight/claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/air-freight/claims/{claim_id}/start-review", headers=headers
        )

    def resolve_claim_review(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/air-freight/claims/{claim_id}/resolve-review", payload, headers
        )

    def rebut_claim(self, claim_id, headers):
        return self._request("POST", f"/air-freight/claims/{claim_id}/rebut", headers=headers)

    def accept_claim_counter(self, claim_id, headers):
        return self._request(
            "POST", f"/air-freight/claims/{claim_id}/accept-counter", headers=headers
        )

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/air-freight/claims/{claim_id}/settle", headers=headers)


api_client = ApiClient()

# Per-test-server isolation SIGKILLs and respawns the server before every
# test. A pooled keep-alive connection to the just-killed server would
# occasionally be handed out for the next test's first request (urllib3's
# stale probe is time-of-check racy) and surface as a spurious
# RemoteDisconnected. Forcing `Connection: close` makes every request use a
# fresh TCP connection, eliminating the stale-connection race.
api_client.session.headers["Connection"] = "close"
