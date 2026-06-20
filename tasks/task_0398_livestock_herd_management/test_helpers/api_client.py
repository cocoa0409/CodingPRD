"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Herd ----
    def create_herd(self, payload, headers):
        return self._request("POST", "/herds", payload, headers)

    def get_herd(self, herd_id, headers):
        return self._request("GET", f"/herds/{herd_id}", headers=headers)

    # ---- Pasture ----
    def create_pasture(self, payload, headers):
        return self._request("POST", "/pastures", payload, headers)

    def get_pasture(self, pasture_id, headers):
        return self._request("GET", f"/pastures/{pasture_id}", headers=headers)

    # ---- DrugProduct ----
    def create_drug_product(self, payload, headers):
        return self._request("POST", "/drug-products", payload, headers)

    # ---- FeedRation ----
    def create_feed_ration(self, payload, headers):
        return self._request("POST", "/feed-rations", payload, headers)

    def get_computed_ration(self, ration_id, headers):
        return self._request(
            "GET", f"/feed-rations/{ration_id}/computed-ration", headers=headers
        )

    # ---- Animal ----
    def create_animal(self, payload, headers):
        return self._request("POST", "/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/animals", headers=headers, params=params)

    def set_life_status(self, animal_id, payload, headers):
        return self._request(
            "POST", f"/animals/{animal_id}/life-status", payload, headers
        )

    def create_weight(self, animal_id, payload, headers):
        return self._request(
            "POST", f"/animals/{animal_id}/weights", payload, headers
        )

    def list_weights(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/animals/{animal_id}/weights", headers=headers, params=params
        )

    def get_trace(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/animals/{animal_id}/trace", headers=headers, params=params
        )

    # ---- BreedingRecord ----
    def create_breeding_record(self, payload, headers):
        return self._request("POST", "/breeding-records", payload, headers)

    def get_breeding_record(self, record_id, headers):
        return self._request("GET", f"/breeding-records/{record_id}", headers=headers)

    def list_breeding_records(self, headers, params=None):
        return self._request(
            "GET", "/breeding-records", headers=headers, params=params
        )

    def transition_breeding_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/breeding-records/{record_id}/transition", payload, headers
        )

    # ---- HealthTreatment ----
    def create_health_treatment(self, payload, headers):
        return self._request("POST", "/health-treatments", payload, headers)

    def get_health_treatment(self, treatment_id, headers):
        return self._request(
            "GET", f"/health-treatments/{treatment_id}", headers=headers
        )

    def list_health_treatments(self, headers, params=None):
        return self._request(
            "GET", "/health-treatments", headers=headers, params=params
        )

    def void_health_treatment(self, treatment_id, headers):
        return self._request(
            "POST", f"/health-treatments/{treatment_id}/void", headers=headers
        )

    # ---- MovementRecord ----
    def create_movement_record(self, payload, headers):
        return self._request("POST", "/movement-records", payload, headers)

    def get_movement_record(self, record_id, headers):
        return self._request("GET", f"/movement-records/{record_id}", headers=headers)

    def list_movement_records(self, headers, params=None):
        return self._request(
            "GET", "/movement-records", headers=headers, params=params
        )

    def apply_movement(self, record_id, payload, headers):
        return self._request(
            "POST", f"/movement-records/{record_id}/apply", payload, headers
        )

    def revert_movement(self, record_id, headers):
        return self._request(
            "POST", f"/movement-records/{record_id}/revert", headers=headers
        )

    # ---- SaleLot ----
    def create_sale_lot(self, payload, headers):
        return self._request("POST", "/sale-lots", payload, headers)

    def get_sale_lot(self, lot_id, headers):
        return self._request("GET", f"/sale-lots/{lot_id}", headers=headers)

    def list_sale_lots(self, headers, params=None):
        return self._request("GET", "/sale-lots", headers=headers, params=params)

    def add_ticket(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/sale-lots/{lot_id}/tickets", payload, headers
        )

    def list_tickets(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/sale-lots/{lot_id}/tickets", headers=headers, params=params
        )

    def sell_lot(self, lot_id, headers):
        return self._request("POST", f"/sale-lots/{lot_id}/sell", headers=headers)

    def withdraw_lot(self, lot_id, headers):
        return self._request("POST", f"/sale-lots/{lot_id}/withdraw", headers=headers)

    # ---- WeightTicket ----
    def get_weight_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weight-tickets/{ticket_id}", headers=headers)

    def list_weight_tickets(self, headers, params=None):
        return self._request("GET", "/weight-tickets", headers=headers, params=params)

    # ---- MortalityRecord ----
    def create_mortality_record(self, payload, headers):
        return self._request("POST", "/mortality-records", payload, headers)

    def get_mortality_record(self, record_id, headers):
        return self._request(
            "GET", f"/mortality-records/{record_id}", headers=headers
        )

    def list_mortality_records(self, headers, params=None):
        return self._request(
            "GET", "/mortality-records", headers=headers, params=params
        )

    def void_mortality_record(self, record_id, headers):
        return self._request(
            "POST", f"/mortality-records/{record_id}/void", headers=headers
        )


api_client = ApiClient()
