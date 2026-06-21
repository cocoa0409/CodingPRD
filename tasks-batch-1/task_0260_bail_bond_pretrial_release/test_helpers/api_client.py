"""API client for the Bail Bond & Pretrial Release API.

One method per endpoint. Subclasses the framework's GenericApiClient, which
supplies the base _request() implementation, envelope handling, and the
API_BASE_URL wiring.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Defendants ----
    def create_defendant(self, payload, headers):
        return self._request("POST", "/defendants", payload, headers)

    def get_defendant(self, defendant_id, headers):
        return self._request("GET", f"/defendants/{defendant_id}", headers=headers)

    def list_defendants(self, headers, params=None):
        return self._request("GET", "/defendants", headers=headers, params=params)

    # ---- Bail Orders ----
    def create_bail_order(self, defendant_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bail-orders", payload, headers)

    def list_bail_orders(self, defendant_id, headers, params=None):
        return self._request("GET", f"/defendants/{defendant_id}/bail-orders", headers=headers, params=params)

    def get_bail_order(self, order_id, headers):
        return self._request("GET", f"/bail-orders/{order_id}", headers=headers)

    # ---- Bonds ----
    def create_bond(self, defendant_id, order_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bail-orders/{order_id}/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    def list_bonds_under_order(self, order_id, headers, params=None):
        return self._request("GET", f"/bail-orders/{order_id}/bonds", headers=headers, params=params)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def activate_bond(self, defendant_id, bond_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/activate", payload or {}, headers)

    def exonerate_bond(self, defendant_id, bond_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/exonerate", payload or {}, headers)

    def revoke_bond(self, defendant_id, bond_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/revoke", payload or {}, headers)

    # ---- Indemnitors & Agreements ----
    def create_indemnitor(self, payload, headers):
        return self._request("POST", "/indemnitors", payload, headers)

    def get_indemnitor(self, indemnitor_id, headers):
        return self._request("GET", f"/indemnitors/{indemnitor_id}", headers=headers)

    def create_indemnity_agreement(self, defendant_id, bond_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/indemnity-agreements", payload, headers)

    def list_bond_indemnity_agreements(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/indemnity-agreements", headers=headers, params=params)

    def get_indemnity_agreement(self, agreement_id, headers):
        return self._request("GET", f"/indemnity-agreements/{agreement_id}", headers=headers)

    def list_indemnity_agreements(self, headers, params=None):
        return self._request("GET", "/indemnity-agreements", headers=headers, params=params)

    # ---- Collateral ----
    def create_collateral(self, defendant_id, bond_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/collateral", payload, headers)

    def list_collateral(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/collateral", headers=headers, params=params)

    # ---- Court Dates & Notifications ----
    def create_court_date(self, defendant_id, bond_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/court-dates", payload, headers)

    def list_court_dates(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/court-dates", headers=headers, params=params)

    def get_court_date(self, court_date_id, headers):
        return self._request("GET", f"/court-dates/{court_date_id}", headers=headers)

    def notify_court_date(self, defendant_id, court_date_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/court-dates/{court_date_id}/notify", payload, headers)

    def list_notifications(self, court_date_id, headers, params=None):
        return self._request("GET", f"/court-dates/{court_date_id}/notifications", headers=headers, params=params)

    def record_appearance(self, defendant_id, court_date_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/court-dates/{court_date_id}/record-appearance", payload or {}, headers)

    def record_fta(self, defendant_id, court_date_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/court-dates/{court_date_id}/record-fta", payload or {}, headers)

    def continue_court_date(self, defendant_id, court_date_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/court-dates/{court_date_id}/continue", payload or {}, headers)

    # ---- Check-ins ----
    def create_check_in(self, defendant_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/check-ins", payload, headers)

    def list_check_ins(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/check-ins", headers=headers, params=params)

    # ---- GPS Devices ----
    def create_gps_device(self, payload, headers):
        return self._request("POST", "/gps-devices", payload, headers)

    def get_gps_device(self, device_id, headers):
        return self._request("GET", f"/gps-devices/{device_id}", headers=headers)

    def assign_gps(self, defendant_id, bond_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/bonds/{bond_id}/gps/assign", payload, headers)

    def list_bond_gps_devices(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/gps-devices", headers=headers, params=params)

    def activate_gps(self, defendant_id, device_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/gps/{device_id}/activate", payload or {}, headers)

    def clear_tamper(self, defendant_id, device_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/gps/{device_id}/clear-tamper", payload or {}, headers)

    def return_gps(self, defendant_id, device_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/gps/{device_id}/return", payload or {}, headers)

    # ---- Forfeiture / Recovery / Judgment ----
    def get_forfeiture(self, proceeding_id, headers):
        return self._request("GET", f"/forfeitures/{proceeding_id}", headers=headers)

    def list_bond_forfeitures(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/forfeitures", headers=headers, params=params)

    def list_court_date_forfeitures(self, court_date_id, headers, params=None):
        return self._request("GET", f"/court-dates/{court_date_id}/forfeitures", headers=headers, params=params)

    def open_recovery(self, defendant_id, proceeding_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/forfeitures/{proceeding_id}/open-recovery", payload or {}, headers)

    def reinstate(self, defendant_id, proceeding_id, headers, payload=None):
        return self._request("POST", f"/defendants/{defendant_id}/forfeitures/{proceeding_id}/reinstate", payload or {}, headers)

    def enter_judgment(self, defendant_id, proceeding_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/forfeitures/{proceeding_id}/enter-judgment", payload, headers)

    def remit(self, defendant_id, proceeding_id, payload, headers):
        return self._request("POST", f"/defendants/{defendant_id}/forfeitures/{proceeding_id}/remit", payload, headers)

    # ---- Ledger ----
    def list_ledger(self, bond_id, headers, params=None):
        return self._request("GET", f"/bonds/{bond_id}/ledger", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
