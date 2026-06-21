"""API client: one method per endpoint defined in the Formalwear & Costume Rental PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Catalog ──────────────────────────────────────────────────────
    def create_catalog(self, payload, headers):
        return self._request("POST", "/catalogs", payload, headers)

    def get_catalog(self, catalog_id, headers):
        return self._request("GET", f"/catalogs/{catalog_id}", headers=headers)

    def list_catalogs(self, headers, params=None):
        return self._request("GET", "/catalogs", headers=headers, params=params)

    # ─── GarmentUnit ──────────────────────────────────────────────────
    def create_garment_unit(self, payload, headers):
        return self._request("POST", "/garment-units", payload, headers)

    def get_garment_unit(self, unit_id, headers):
        return self._request("GET", f"/garment-units/{unit_id}", headers=headers)

    def list_garment_units(self, headers, params=None):
        return self._request("GET", "/garment-units", headers=headers, params=params)

    def clear_cleaning(self, unit_id, headers):
        return self._request("POST", f"/garment-units/{unit_id}/clear-cleaning", headers=headers)

    def retire_garment_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/garment-units/{unit_id}/retire", payload, headers)

    # ─── Customer ─────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── MeasurementProfile ───────────────────────────────────────────
    def create_measurement_profile(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/measurement-profiles", payload, headers)

    def list_measurement_profiles(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/measurement-profiles", headers=headers, params=params)

    def get_measurement_profile(self, profile_id, headers):
        return self._request("GET", f"/measurement-profiles/{profile_id}", headers=headers)

    # ─── Reservation ──────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", headers=headers)

    def pickup_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/pickup", headers=headers)

    def return_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/return", payload, headers)

    # ─── Alteration ───────────────────────────────────────────────────
    def create_alteration(self, payload, headers):
        return self._request("POST", "/alterations", payload, headers)

    def get_alteration(self, alteration_id, headers):
        return self._request("GET", f"/alterations/{alteration_id}", headers=headers)

    def list_alterations(self, headers, params=None):
        return self._request("GET", "/alterations", headers=headers, params=params)

    def complete_alteration(self, alteration_id, headers):
        return self._request("POST", f"/alterations/{alteration_id}/complete", headers=headers)

    def cancel_alteration(self, alteration_id, headers):
        return self._request("POST", f"/alterations/{alteration_id}/cancel", headers=headers)

    # ─── FitCheck ─────────────────────────────────────────────────────
    def create_fit_check(self, payload, headers):
        return self._request("POST", "/fit-checks", payload, headers)

    def get_fit_check(self, fit_check_id, headers):
        return self._request("GET", f"/fit-checks/{fit_check_id}", headers=headers)

    def list_fit_checks(self, headers, params=None):
        return self._request("GET", "/fit-checks", headers=headers, params=params)

    # ─── PartyOrder ───────────────────────────────────────────────────
    def create_party_order(self, payload, headers):
        return self._request("POST", "/party-orders", payload, headers)

    def get_party_order(self, party_id, headers):
        return self._request("GET", f"/party-orders/{party_id}", headers=headers)

    def list_party_orders(self, headers, params=None):
        return self._request("GET", "/party-orders", headers=headers, params=params)

    def lock_party_order(self, party_id, payload, headers):
        return self._request("POST", f"/party-orders/{party_id}/lock", payload, headers)

    def dissolve_party_order(self, party_id, headers):
        return self._request("POST", f"/party-orders/{party_id}/dissolve", headers=headers)

    # ─── Settlement ───────────────────────────────────────────────────
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/finalize", headers=headers)

    def waive_fee(self, settlement_id, payload, headers):
        return self._request("POST", f"/settlements/{settlement_id}/waive-fee", payload, headers)

    # ─── LedgerEntry (read) ───────────────────────────────────────────
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────────────────────
    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
