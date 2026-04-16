"""API client: one method per endpoint from scaffold Table 5 / PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Shelter ---
    def create_shelter(self, payload, headers):
        return self._request("POST", "/shelters", payload, headers=headers)

    def list_shelters(self, headers, params=None):
        return self._request("GET", "/shelters", headers=headers, params=params)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}", headers=headers)

    # --- Animal ---
    def create_animal(self, shelter_id, payload, headers):
        return self._request("POST", f"/shelters/{shelter_id}/animals", payload, headers=headers)

    def list_animals(self, shelter_id, headers, params=None):
        return self._request("GET", f"/shelters/{shelter_id}/animals", headers=headers, params=params)

    def get_animal(self, shelter_id, animal_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}/animals/{animal_id}", headers=headers)

    def patch_animal(self, shelter_id, animal_id, payload, headers):
        return self._request("PATCH", f"/shelters/{shelter_id}/animals/{animal_id}", payload, headers=headers)

    # --- Vaccinations ---
    def create_vaccination(self, shelter_id, animal_id, payload, headers):
        return self._request("POST", f"/shelters/{shelter_id}/animals/{animal_id}/vaccinations", payload, headers=headers)

    def list_vaccinations(self, shelter_id, animal_id, headers, params=None):
        return self._request("GET", f"/shelters/{shelter_id}/animals/{animal_id}/vaccinations", headers=headers, params=params)

    def get_compliance(self, shelter_id, animal_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}/animals/{animal_id}/compliance", headers=headers)

    # --- Adopter ---
    def create_adopter(self, payload, headers):
        return self._request("POST", "/adopters", payload, headers=headers)

    def get_adopter(self, adopter_id, headers):
        return self._request("GET", f"/adopters/{adopter_id}", headers=headers)

    # --- Home Visit ---
    def create_home_visit(self, adopter_id, payload, headers):
        return self._request("POST", f"/adopters/{adopter_id}/home-visits", payload, headers=headers)

    def list_home_visits(self, adopter_id, headers, params=None):
        return self._request("GET", f"/adopters/{adopter_id}/home-visits", headers=headers, params=params)

    def submit_home_visit(self, adopter_id, hv_id, payload, headers):
        return self._request("POST", f"/adopters/{adopter_id}/home-visits/{hv_id}/submit", payload, headers=headers)

    def cancel_home_visit(self, adopter_id, hv_id, headers):
        return self._request("POST", f"/adopters/{adopter_id}/home-visits/{hv_id}/cancel", headers=headers)

    # --- Adoption Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/adoption-applications", payload, headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/adoption-applications", headers=headers, params=params)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/adoption-applications/{app_id}", headers=headers)

    def begin_review(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/begin-review", headers=headers)

    def request_home_visit(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/request-home-visit", headers=headers)

    def approve_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/approve", headers=headers)

    def reject_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/adoption-applications/{app_id}/reject", payload, headers=headers)

    def finalize_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/finalize", headers=headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/withdraw", headers=headers)

    # --- Boarding Reservation ---
    def create_reservation(self, shelter_id, payload, headers):
        return self._request("POST", f"/shelters/{shelter_id}/boarding-reservations", payload, headers=headers)

    def list_reservations(self, shelter_id, headers, params=None):
        return self._request("GET", f"/shelters/{shelter_id}/boarding-reservations", headers=headers, params=params)

    def check_in_reservation(self, shelter_id, reservation_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/boarding-reservations/{reservation_id}/check-in", headers=headers)

    def check_out_reservation(self, shelter_id, reservation_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/boarding-reservations/{reservation_id}/check-out", headers=headers)

    def settle_reservation(self, shelter_id, reservation_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/boarding-reservations/{reservation_id}/settle", headers=headers)

    def cancel_reservation(self, shelter_id, reservation_id, headers):
        return self._request("POST", f"/shelters/{shelter_id}/boarding-reservations/{reservation_id}/cancel", headers=headers)

    # --- Fee Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/fee-settlements", payload, headers=headers)

    def capture_settlement(self, settlement_id, headers):
        return self._request("POST", f"/fee-settlements/{settlement_id}/capture", headers=headers)

    def refund_settlement(self, settlement_id, headers):
        return self._request("POST", f"/fee-settlements/{settlement_id}/refund", headers=headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/fee-settlements/{settlement_id}", headers=headers)


api_client = ApiClient()
