"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /rental prefix. The base _request() method
is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Catalog: GearType -----------------------------------------------
    def create_gear_type(self, payload, headers):
        return self._request("POST", "/rental/gear-types", payload, headers)

    def get_gear_type(self, gear_type_id, headers):
        return self._request("GET", f"/rental/gear-types/{gear_type_id}", headers=headers)

    def list_gear_types(self, headers, params=None):
        return self._request("GET", "/rental/gear-types", headers=headers, params=params)

    # --- Catalog: RateCard -----------------------------------------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rental/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rental/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rental/rate-cards", headers=headers, params=params)

    # --- Catalog: SeasonWindow -------------------------------------------
    def create_season_window(self, payload, headers):
        return self._request("POST", "/rental/season-windows", payload, headers)

    def list_season_windows(self, headers, params=None):
        return self._request("GET", "/rental/season-windows", headers=headers, params=params)

    # --- Catalog: AddOn --------------------------------------------------
    def create_addon(self, payload, headers):
        return self._request("POST", "/rental/addons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/rental/addons", headers=headers, params=params)

    # --- Customer --------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/rental/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/rental/customers/{customer_id}", headers=headers)

    # --- GearUnit --------------------------------------------------------
    def create_gear_unit(self, payload, headers):
        return self._request("POST", "/rental/gear-units", payload, headers)

    def get_gear_unit(self, gear_unit_id, headers):
        return self._request("GET", f"/rental/gear-units/{gear_unit_id}", headers=headers)

    def list_gear_units(self, headers, params=None):
        return self._request("GET", "/rental/gear-units", headers=headers, params=params)

    def repair_gear_unit(self, gear_unit_id, headers):
        return self._request("POST", f"/rental/gear-units/{gear_unit_id}/repair", {}, headers)

    # --- Reservation -----------------------------------------------------
    def create_reservation(self, payload, headers):
        return self._request("POST", "/rental/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/rental/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/rental/reservations", headers=headers, params=params)

    def get_reservation_quote(self, reservation_id, headers):
        return self._request("GET", f"/rental/reservations/{reservation_id}/quote", headers=headers)

    def attach_addon(self, reservation_id, payload, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/addons", payload, headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/confirm", {}, headers)

    def checkout_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/checkout", payload, headers)

    def checkin_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/checkin", payload, headers)

    def settle_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/settle", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/rental/reservations/{reservation_id}/cancel", {}, headers)

    # --- ReservationAddOn (reads) ----------------------------------------
    def list_reservation_addons(self, headers, params=None):
        return self._request("GET", "/rental/reservation-addons", headers=headers, params=params)

    def get_reservation_addon(self, line_id, headers):
        return self._request("GET", f"/rental/reservation-addons/{line_id}", headers=headers)

    # --- ConditionReport (reads) -----------------------------------------
    def get_condition_report(self, report_id, headers):
        return self._request("GET", f"/rental/condition-reports/{report_id}", headers=headers)

    def list_condition_reports(self, headers, params=None):
        return self._request("GET", "/rental/condition-reports", headers=headers, params=params)

    # --- DamageAssessment ------------------------------------------------
    def get_damage_assessment(self, assessment_id, headers):
        return self._request("GET", f"/rental/damage-assessments/{assessment_id}", headers=headers)

    def list_damage_assessments(self, headers, params=None):
        return self._request("GET", "/rental/damage-assessments", headers=headers, params=params)

    def dispute_damage_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/rental/damage-assessments/{assessment_id}/dispute", payload, headers)

    def reassess_damage_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/rental/damage-assessments/{assessment_id}/reassess", payload, headers)

    # --- LedgerEntry (reads) ---------------------------------------------
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/rental/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/rental/ledger-entries", headers=headers, params=params)

    # --- Test clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/rental/_clock/set", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
