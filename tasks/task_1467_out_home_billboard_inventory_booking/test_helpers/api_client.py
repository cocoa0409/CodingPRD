"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- RateCard ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/api/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/api/rate-cards/{rate_card_id}", headers=headers)

    def update_rate_card(self, rate_card_id, payload, headers):
        return self._request("PUT", f"/api/rate-cards/{rate_card_id}", payload, headers)

    def list_rate_card_flights(self, rate_card_id, headers, params=None):
        return self._request("GET", f"/api/rate-cards/{rate_card_id}/flights",
                             headers=headers, params=params)

    # --- Face ---
    def create_face(self, payload, headers):
        return self._request("POST", "/api/faces", payload, headers)

    def get_face(self, face_id, headers):
        return self._request("GET", f"/api/faces/{face_id}", headers=headers)

    def update_face(self, face_id, payload, headers):
        return self._request("PUT", f"/api/faces/{face_id}", payload, headers)

    def list_face_permits(self, face_id, headers, params=None):
        return self._request("GET", f"/api/faces/{face_id}/permits",
                             headers=headers, params=params)

    def list_face_work_orders(self, face_id, headers, params=None):
        return self._request("GET", f"/api/faces/{face_id}/maintenance-work-orders",
                             headers=headers, params=params)

    def list_face_flights(self, face_id, headers, params=None):
        return self._request("GET", f"/api/faces/{face_id}/flights",
                             headers=headers, params=params)

    def get_face_availability(self, face_id, headers, params=None):
        return self._request("GET", f"/api/faces/{face_id}/availability",
                             headers=headers, params=params)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def update_permit(self, permit_id, payload, headers):
        return self._request("PUT", f"/api/permits/{permit_id}", payload, headers)

    def list_permit_successors(self, permit_id, headers, params=None):
        return self._request("GET", f"/api/permits/{permit_id}/successors",
                             headers=headers, params=params)

    # --- MaintenanceWorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/api/maintenance-work-orders", payload, headers)

    def update_work_order(self, work_order_id, payload, headers):
        return self._request("PUT", f"/api/maintenance-work-orders/{work_order_id}",
                             payload, headers)

    # --- AdvertiserAccount ---
    def create_advertiser(self, payload, headers):
        return self._request("POST", "/api/advertiser-accounts", payload, headers)

    def get_advertiser(self, advertiser_id, headers):
        return self._request("GET", f"/api/advertiser-accounts/{advertiser_id}",
                             headers=headers)

    def update_advertiser(self, advertiser_id, payload, headers):
        return self._request("PUT", f"/api/advertiser-accounts/{advertiser_id}",
                             payload, headers)

    def list_advertiser_campaigns(self, advertiser_id, headers, params=None):
        return self._request("GET",
                             f"/api/advertiser-accounts/{advertiser_id}/campaigns",
                             headers=headers, params=params)

    # --- Campaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/api/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/api/campaigns/{campaign_id}", headers=headers)

    def update_campaign(self, campaign_id, payload, headers):
        return self._request("PUT", f"/api/campaigns/{campaign_id}", payload, headers)

    def list_campaign_flights(self, campaign_id, headers, params=None):
        return self._request("GET", f"/api/campaigns/{campaign_id}/flights",
                             headers=headers, params=params)

    # --- Flight ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/api/flights", payload, headers)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/api/flights/{flight_id}", headers=headers)

    def update_flight(self, flight_id, payload, headers):
        return self._request("PUT", f"/api/flights/{flight_id}", payload, headers)

    def confirm_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/api/flights/{flight_id}/confirm",
                             payload, headers)

    def list_successor_flights(self, flight_id, headers, params=None):
        return self._request("GET", f"/api/flights/{flight_id}/successor-flights",
                             headers=headers, params=params)

    def list_flight_artwork_orders(self, flight_id, headers, params=None):
        return self._request("GET", f"/api/flights/{flight_id}/artwork-orders",
                             headers=headers, params=params)

    def list_flight_posting_records(self, flight_id, headers, params=None):
        return self._request("GET", f"/api/flights/{flight_id}/posting-records",
                             headers=headers, params=params)

    def list_flight_make_goods(self, flight_id, headers, params=None):
        return self._request("GET", f"/api/flights/{flight_id}/make-goods",
                             headers=headers, params=params)

    def append_impression_entry(self, flight_id, payload, headers):
        return self._request("POST", f"/api/flights/{flight_id}/impression-entries",
                             payload, headers)

    # --- ArtworkOrder ---
    def create_artwork_order(self, payload, headers):
        return self._request("POST", "/api/artwork-orders", payload, headers)

    def update_artwork_order(self, artwork_order_id, payload, headers):
        return self._request("PUT", f"/api/artwork-orders/{artwork_order_id}",
                             payload, headers)

    # --- PostingRecord ---
    def create_posting_record(self, payload, headers):
        return self._request("POST", "/api/posting-records", payload, headers)

    def update_posting_record(self, posting_record_id, payload, headers):
        return self._request("PUT", f"/api/posting-records/{posting_record_id}",
                             payload, headers)

    # --- MakeGood ---
    def create_make_good(self, payload, headers):
        return self._request("POST", "/api/make-goods", payload, headers)

    def update_make_good(self, make_good_id, payload, headers):
        return self._request("PUT", f"/api/make-goods/{make_good_id}", payload, headers)


api_client = ApiClient()
