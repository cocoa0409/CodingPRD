"""API client: one method per endpoint defined in PRD §4.

All resources are mounted under the /depot prefix (PRD §1, §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/depot"


class ApiClient(GenericApiClient):
    # --- Logical clock and daily ops (PRD §2.4, §3.9) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def run_daily_close(self, headers):
        return self._request("POST", f"{BASE}/ops/run_daily_close", {}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", f"{BASE}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{BASE}/customers/{customer_id}", headers=headers)

    # --- Product models ---
    def create_product_model(self, payload, headers):
        return self._request("POST", f"{BASE}/product-models", payload, headers)

    def get_product_model(self, model_id, headers):
        return self._request("GET", f"{BASE}/product-models/{model_id}", headers=headers)

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", f"{BASE}/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"{BASE}/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", f"{BASE}/units", headers=headers, params=params)

    # --- Parts ---
    def create_part(self, payload, headers):
        return self._request("POST", f"{BASE}/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{BASE}/parts/{part_id}", headers=headers)

    def restock_part(self, part_id, payload, headers):
        return self._request("POST", f"{BASE}/parts/{part_id}/restock", payload, headers)

    # --- Failure codes ---
    def create_failure_code(self, payload, headers):
        return self._request("POST", f"{BASE}/failure-codes", payload, headers)

    # --- Depot bays ---
    def create_depot_bay(self, payload, headers):
        return self._request("POST", f"{BASE}/depot-bays", payload, headers)

    def get_depot_bay(self, bay_id, headers):
        return self._request("GET", f"{BASE}/depot-bays/{bay_id}", headers=headers)

    def deactivate_depot_bay(self, bay_id, headers):
        return self._request("POST", f"{BASE}/depot-bays/{bay_id}/deactivate", {}, headers)

    def reactivate_depot_bay(self, bay_id, headers):
        return self._request("POST", f"{BASE}/depot-bays/{bay_id}/reactivate", {}, headers)

    # --- Loaner units ---
    def create_loaner_unit(self, payload, headers):
        return self._request("POST", f"{BASE}/loaner-units", payload, headers)

    def get_loaner_unit(self, loaner_unit_id, headers):
        return self._request("GET", f"{BASE}/loaner-units/{loaner_unit_id}", headers=headers)

    def list_loaner_units(self, headers, params=None):
        return self._request("GET", f"{BASE}/loaner-units", headers=headers, params=params)

    def inspect_loaner_unit(self, loaner_unit_id, payload, headers):
        return self._request("POST", f"{BASE}/loaner-units/{loaner_unit_id}/inspect", payload, headers)

    # --- RMAs ---
    def create_rma(self, payload, headers):
        return self._request("POST", f"{BASE}/rmas", payload, headers)

    def get_rma(self, rma_id, headers):
        return self._request("GET", f"{BASE}/rmas/{rma_id}", headers=headers)

    def list_rmas(self, headers, params=None):
        return self._request("GET", f"{BASE}/rmas", headers=headers, params=params)

    def patch_rma(self, rma_id, payload, headers):
        return self._request("PATCH", f"{BASE}/rmas/{rma_id}", payload, headers)

    def authorize_rma(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/authorize", {}, headers)

    def receive_rma(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/receive", payload, headers)

    def triage_rma(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/triage", payload, headers)

    def diagnose_rma(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/diagnose", payload, headers)

    def schedule_bay(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/schedule-bay", payload, headers)

    def await_parts(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/await-parts", {}, headers)

    def consume_part(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/parts", payload, headers)

    def repair_complete(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/repair-complete", {}, headers)

    def qa_release(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/qa-release", payload, headers)

    def ship_rma(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/ship", payload, headers)

    def close_rma(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/close", {}, headers)

    def cancel_rma(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/cancel", {}, headers)

    def return_unrepaired(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/return-unrepaired", {}, headers)

    def scrap_rma(self, rma_id, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/scrap", {}, headers)

    def override_decision(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/override-decision", payload, headers)

    def warranty_override(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/warranty-override", payload, headers)

    # --- Quotes ---
    def create_quote_revision(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{BASE}/quotes/{quote_id}", headers=headers)

    def list_rma_quotes(self, rma_id, headers, params=None):
        return self._request("GET", f"{BASE}/rmas/{rma_id}/quotes", headers=headers, params=params)

    def approve_quote(self, quote_id, payload, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/approve", payload, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"{BASE}/quotes/{quote_id}/decline", {}, headers)

    # --- Loaner reservations ---
    def create_loaner_reservation(self, rma_id, payload, headers):
        return self._request("POST", f"{BASE}/rmas/{rma_id}/loaner-reservations", payload, headers)

    def get_loaner_reservation(self, reservation_id, headers):
        return self._request("GET", f"{BASE}/loaner-reservations/{reservation_id}", headers=headers)

    def list_loaner_reservations(self, headers, params=None):
        return self._request("GET", f"{BASE}/loaner-reservations", headers=headers, params=params)

    def ship_loaner_reservation(self, reservation_id, headers):
        return self._request("POST", f"{BASE}/loaner-reservations/{reservation_id}/ship", {}, headers)

    def return_loaner_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"{BASE}/loaner-reservations/{reservation_id}/return", payload, headers)

    def cancel_loaner_reservation(self, reservation_id, headers):
        return self._request("POST", f"{BASE}/loaner-reservations/{reservation_id}/cancel", {}, headers)

    def forfeit_loaner_reservation(self, reservation_id, headers):
        return self._request("POST", f"{BASE}/loaner-reservations/{reservation_id}/forfeit", {}, headers)

    # --- Engineering escalations ---
    def create_engineering_escalation(self, payload, headers):
        return self._request("POST", f"{BASE}/engineering-escalations", payload, headers)

    def get_engineering_escalation(self, escalation_id, headers):
        return self._request("GET", f"{BASE}/engineering-escalations/{escalation_id}", headers=headers)

    def list_engineering_escalations(self, headers, params=None):
        return self._request("GET", f"{BASE}/engineering-escalations", headers=headers, params=params)

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request("POST", f"{BASE}/engineering-escalations/{escalation_id}/acknowledge", {}, headers)

    def contain_escalation(self, escalation_id, headers):
        return self._request("POST", f"{BASE}/engineering-escalations/{escalation_id}/contain", {}, headers)

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"{BASE}/engineering-escalations/{escalation_id}/resolve", payload, headers)

    # --- Repair lines ---
    def get_repair_line(self, repair_line_id, headers):
        return self._request("GET", f"{BASE}/repair-lines/{repair_line_id}", headers=headers)

    def list_repair_lines(self, headers, params=None):
        return self._request("GET", f"{BASE}/repair-lines", headers=headers, params=params)

    def reverse_repair_line(self, repair_line_id, headers):
        return self._request("POST", f"{BASE}/repair-lines/{repair_line_id}/reverse", {}, headers)

    # --- Notifications ---
    def list_rma_notifications(self, rma_id, headers, params=None):
        return self._request("GET", f"{BASE}/rmas/{rma_id}/notifications", headers=headers, params=params)


api_client = ApiClient()
