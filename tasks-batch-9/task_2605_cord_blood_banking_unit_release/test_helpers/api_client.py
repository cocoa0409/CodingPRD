"""HTTP client with one method per declared endpoint.

Every resource lives under the ``/cbb`` prefix; the logical clock control
endpoint is the single exception and sits at ``/_clock/set_current_utc``.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cbb"


class ApiClient(GenericApiClient):
    """One method per endpoint declared by the API."""

    # --- Logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[dict] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Enrollments -------------------------------------------------------

    def create_enrollment(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/enrollments", None, headers, params)

    def sign_consent(self, enrollment_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/consent", payload, headers
        )

    def open_consent_amendment(
        self, enrollment_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/consent-amendment", payload, headers
        )

    def withdraw_enrollment(
        self, enrollment_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    def list_enrollment_storage_accounts(
        self, enrollment_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/enrollments/{enrollment_id}/storage-accounts", None, headers, params
        )

    def list_enrollment_collection_kits(
        self, enrollment_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/enrollments/{enrollment_id}/collection-kits", None, headers, params
        )

    def list_enrollment_maternal_screenings(
        self, enrollment_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/enrollments/{enrollment_id}/maternal-screenings",
            None,
            headers,
            params,
        )

    # --- Storage accounts --------------------------------------------------

    def create_storage_account(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/storage-accounts", payload, headers)

    def get_storage_account(self, account_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/storage-accounts/{account_id}", None, headers)

    def list_storage_account_units(
        self, account_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/storage-accounts/{account_id}/units", None, headers, params
        )

    def list_storage_account_invoices(
        self, account_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/storage-accounts/{account_id}/storage-invoices", None, headers, params
        )

    # --- Collection kits ---------------------------------------------------

    def create_collection_kit(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/collection-kits", payload, headers)

    def get_collection_kit(self, kit_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/collection-kits/{kit_id}", None, headers)

    def list_kit_collections(
        self, kit_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/collection-kits/{kit_id}/collections", None, headers, params
        )

    # --- Collections -------------------------------------------------------

    def create_collection(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/collections", payload, headers)

    def get_collection(self, collection_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/collections/{collection_id}", None, headers)

    def receive_collection(
        self, collection_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/collections/{collection_id}/receive", payload, headers
        )

    def reject_collection(
        self, collection_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/collections/{collection_id}/reject", payload, headers
        )

    def list_collection_units(
        self, collection_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/collections/{collection_id}/units", None, headers, params
        )

    # --- Cord blood units --------------------------------------------------

    def get_unit(self, unit_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/units/{unit_id}", None, headers)

    def search_units(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/units/search", None, headers, params)

    def determine_eligibility(self, unit_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/eligibility-determination", payload, headers
        )

    def cryopreserve_unit(self, unit_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/units/{unit_id}/cryopreserve", payload, headers)

    def dispose_unit(self, unit_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/units/{unit_id}/dispose", payload, headers)

    def list_unit_processing_runs(
        self, unit_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/units/{unit_id}/processing-runs", None, headers, params
        )

    def list_unit_quality_tests(
        self, unit_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/units/{unit_id}/quality-tests", None, headers, params
        )

    def list_unit_registry_listings(
        self, unit_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/units/{unit_id}/registry-listings", None, headers, params
        )

    # --- Processing runs ---------------------------------------------------

    def create_processing_run(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/processing-runs", payload, headers)

    def get_processing_run(self, run_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/processing-runs/{run_id}", None, headers)

    def complete_processing_run(self, run_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/processing-runs/{run_id}/complete", payload, headers
        )

    # --- Quality tests -----------------------------------------------------

    def create_quality_test(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/quality-tests", payload, headers)

    def get_quality_test(self, test_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/quality-tests/{test_id}", None, headers)

    # --- Maternal screenings -----------------------------------------------

    def create_maternal_screening(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/maternal-screenings", payload, headers)

    def get_maternal_screening(self, screening_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/maternal-screenings/{screening_id}", None, headers)

    def amend_maternal_screening(
        self, screening_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "PATCH", f"{PREFIX}/maternal-screenings/{screening_id}", payload, headers
        )

    # --- Storage tanks -----------------------------------------------------

    def create_storage_tank(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/storage-tanks", payload, headers)

    def get_storage_tank(self, tank_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/storage-tanks/{tank_id}", None, headers)

    def list_storage_tanks(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/storage-tanks", None, headers, params)

    def record_temperature_reading(
        self, tank_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/storage-tanks/{tank_id}/temperature-readings", payload, headers
        )

    def list_tank_units(
        self, tank_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request("GET", f"{PREFIX}/storage-tanks/{tank_id}/units", None, headers, params)

    def list_tank_excursions(
        self, tank_id: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/storage-tanks/{tank_id}/temperature-excursions", None, headers, params
        )

    # --- Temperature excursions --------------------------------------------

    def get_excursion(self, excursion_id: str, headers: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/temperature-excursions/{excursion_id}", None, headers
        )

    def acknowledge_excursion(
        self, excursion_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/temperature-excursions/{excursion_id}/acknowledge", payload, headers
        )

    def resolve_excursion(self, excursion_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/temperature-excursions/{excursion_id}/resolve", payload, headers
        )

    # --- Registry listings -------------------------------------------------

    def create_registry_listing(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/registry-listings", payload, headers)

    def get_registry_listing(self, listing_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/registry-listings/{listing_id}", None, headers)

    def suspend_registry_listing(
        self, listing_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/registry-listings/{listing_id}/suspend", payload, headers
        )

    def resume_registry_listing(
        self, listing_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/registry-listings/{listing_id}/resume", payload, headers
        )

    # --- Storage invoices --------------------------------------------------

    def create_storage_invoice(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/storage-invoices", payload, headers)

    def get_storage_invoice(self, invoice_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/storage-invoices/{invoice_id}", None, headers)

    def pay_storage_invoice(self, invoice_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"{PREFIX}/storage-invoices/{invoice_id}/payments", payload, headers
        )

    # --- Reservations ------------------------------------------------------

    def create_reservation(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}", None, headers)

    def list_reservations(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", f"{PREFIX}/reservations", None, headers, params)

    def confirm_reservation(
        self, reservation_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/confirm", payload, headers
        )

    def decline_reservation(
        self, reservation_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/decline", payload, headers
        )

    def release_reservation(
        self, reservation_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/release", payload, headers
        )

    def cancel_reservation(
        self, reservation_id: str, payload: dict, headers: Optional[dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/cancel", payload, headers
        )

    def get_release_summary(self, reservation_id: str, headers: Optional[dict] = None):
        return self._request(
            "GET", f"{PREFIX}/reservations/{reservation_id}/release-summary", None, headers
        )

    # --- Operations --------------------------------------------------------

    def run_nightly_batch(self, payload: Optional[dict] = None, headers: Optional[dict] = None):
        return self._request("POST", f"{PREFIX}/ops/nightly-run", payload or {}, headers)


api_client = ApiClient()
