"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Facility & clock ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers=headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def advance_clock(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/_clock/advance", payload, headers=headers
        )

    # ---- Owner ----
    def create_owner(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/owners", payload, headers=headers
        )

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owners(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/owners", headers=headers, params=params
        )

    # ---- Pet ----
    def create_pet(self, owner_id, payload, headers):
        return self._request("POST", f"/owners/{owner_id}/pets", payload, headers=headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/pets/{pet_id}", headers=headers)

    def list_pets(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/pets", headers=headers, params=params
        )

    def review_pet(self, pet_id, payload, headers):
        return self._request("POST", f"/pets/{pet_id}/review", payload, headers=headers)

    # ---- VaccinationRecord ----
    def create_vaccination(self, pet_id, payload, headers):
        return self._request(
            "POST", f"/pets/{pet_id}/vaccinations", payload, headers=headers
        )

    def list_vaccinations(self, pet_id, headers, params=None):
        return self._request(
            "GET", f"/pets/{pet_id}/vaccinations", headers=headers, params=params
        )

    # ---- Run ----
    def create_run(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/runs", payload, headers=headers
        )

    def list_runs(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/runs", headers=headers, params=params
        )

    # ---- Reservation ----
    def create_reservation(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/reservations", payload, headers=headers
        )

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def pay_deposit(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/pay_deposit", payload, headers=headers
        )

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm", headers=headers
        )

    def check_in(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check_in", headers=headers
        )

    def check_out(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check_out", payload, headers=headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", headers=headers
        )

    def mark_no_show(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/mark_no_show", headers=headers
        )

    def create_incident(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/incidents", payload, headers=headers
        )

    # ---- RunAssignment ----
    def create_assignment(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/assignments", payload, headers=headers
        )

    def list_assignments(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/reservations/{reservation_id}/assignments",
            headers=headers, params=params,
        )

    # ---- AddOn ----
    def create_addon(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/addons", payload, headers=headers
        )

    # ---- Package ----
    def create_package(self, owner_id, payload, headers):
        return self._request(
            "POST", f"/owners/{owner_id}/packages", payload, headers=headers
        )

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/packages", headers=headers, params=params
        )

    def renew_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/renew", headers=headers)

    def list_redemptions(self, package_id, headers, params=None):
        return self._request(
            "GET", f"/packages/{package_id}/redemptions", headers=headers, params=params
        )


api_client = ApiClient()
