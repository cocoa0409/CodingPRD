"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- tray templates --------------------------------------------------
    def create_tray_template(self, payload, headers):
        return self._request("POST", "/spd/tray-templates", payload, headers)

    def list_tray_templates(self, headers, params=None):
        return self._request("GET", "/spd/tray-templates", headers=headers, params=params)

    def get_tray_template(self, template_id, headers):
        return self._request("GET", f"/spd/tray-templates/{template_id}", headers=headers)

    def update_tray_template(self, template_id, payload, headers):
        return self._request("PUT", f"/spd/tray-templates/{template_id}", payload, headers)

    def get_template_availability(self, template_id, window_start_at, headers):
        return self._request(
            "GET",
            f"/spd/tray-templates/{template_id}/availability",
            {"window_start_at": window_start_at},
            headers,
        )

    # ---- trays -----------------------------------------------------------
    def create_tray(self, payload, headers):
        return self._request("POST", "/spd/trays", payload, headers)

    def list_trays(self, headers, params=None):
        return self._request("GET", "/spd/trays", headers=headers, params=params)

    def get_tray(self, tray_id, headers):
        return self._request("GET", f"/spd/trays/{tray_id}", headers=headers)

    def start_decontamination(self, tray_id, headers):
        return self._request(
            "POST", f"/spd/trays/{tray_id}/decontamination/start", {}, headers
        )

    def complete_decontamination(self, tray_id, headers):
        return self._request(
            "POST", f"/spd/trays/{tray_id}/decontamination/complete", {}, headers
        )

    def start_assembly(self, tray_id, headers):
        return self._request("POST", f"/spd/trays/{tray_id}/assembly/start", {}, headers)

    def submit_assembly_verification(self, tray_id, payload, headers):
        return self._request(
            "POST", f"/spd/trays/{tray_id}/assembly-verifications", payload, headers
        )

    def discard_tray(self, tray_id, headers):
        return self._request("POST", f"/spd/trays/{tray_id}/discard", {}, headers)

    # ---- assembly verifications ------------------------------------------
    def list_assembly_verifications(self, headers, params=None):
        return self._request(
            "GET", "/spd/assembly-verifications", headers=headers, params=params
        )

    def get_assembly_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/spd/assembly-verifications/{verification_id}", headers=headers
        )

    # ---- instruments & repair --------------------------------------------
    def create_instrument(self, payload, headers):
        return self._request("POST", "/spd/instruments", payload, headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/spd/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/spd/instruments/{instrument_id}", headers=headers)

    def assign_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/spd/instruments/{instrument_id}/assign", payload, headers
        )

    def flag_instrument_for_repair(self, instrument_id, headers):
        return self._request(
            "POST", f"/spd/instruments/{instrument_id}/flag-for-repair", {}, headers
        )

    def retire_instrument(self, instrument_id, headers):
        return self._request(
            "POST", f"/spd/instruments/{instrument_id}/retire", {}, headers
        )

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/spd/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/spd/repair-orders/{order_id}", headers=headers)

    def send_repair_order(self, order_id, payload, headers):
        return self._request("POST", f"/spd/repair-orders/{order_id}/send", payload, headers)

    def receive_repair_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/spd/repair-orders/{order_id}/receive", payload, headers
        )

    # ---- sterilizers -------------------------------------------------------
    def create_sterilizer(self, payload, headers):
        return self._request("POST", "/spd/sterilizers", payload, headers)

    def list_sterilizers(self, headers, params=None):
        return self._request("GET", "/spd/sterilizers", headers=headers, params=params)

    def get_sterilizer(self, sterilizer_id, headers):
        return self._request("GET", f"/spd/sterilizers/{sterilizer_id}", headers=headers)

    # ---- sterilization loads ----------------------------------------------
    def create_sterilization_load(self, payload, headers):
        return self._request("POST", "/spd/sterilization-loads", payload, headers)

    def list_sterilization_loads(self, headers, params=None):
        return self._request(
            "GET", "/spd/sterilization-loads", headers=headers, params=params
        )

    def get_sterilization_load(self, load_id, headers):
        return self._request(
            "GET", f"/spd/sterilization-loads/{load_id}", headers=headers
        )

    def add_tray_to_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/trays", payload, headers
        )

    def start_load(self, load_id, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/start", {}, headers
        )

    def complete_load(self, load_id, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/complete", {}, headers
        )

    def fail_load_cycle(self, load_id, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/fail-cycle", {}, headers
        )

    def abort_load(self, load_id, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/abort", {}, headers
        )

    def release_load(self, load_id, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/release", {}, headers
        )

    def recall_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/spd/sterilization-loads/{load_id}/recall", payload, headers
        )

    # ---- biological indicators ---------------------------------------------
    def add_biological_indicator(self, load_id, payload, headers):
        return self._request(
            "POST",
            f"/spd/sterilization-loads/{load_id}/biological-indicators",
            payload,
            headers,
        )

    def list_biological_indicators(self, headers, params=None):
        return self._request(
            "GET", "/spd/biological-indicators", headers=headers, params=params
        )

    def get_biological_indicator(self, bi_id, headers):
        return self._request(
            "GET", f"/spd/biological-indicators/{bi_id}", headers=headers
        )

    def record_bi_result(self, bi_id, payload, headers):
        return self._request(
            "POST", f"/spd/biological-indicators/{bi_id}/record-result", payload, headers
        )

    # ---- OR cases & reservations -------------------------------------------
    def create_or_case(self, payload, headers):
        return self._request("POST", "/spd/or-cases", payload, headers)

    def list_or_cases(self, headers, params=None):
        return self._request("GET", "/spd/or-cases", headers=headers, params=params)

    def get_or_case(self, case_id, headers):
        return self._request("GET", f"/spd/or-cases/{case_id}", headers=headers)

    def create_reservation(self, case_id, payload, headers):
        return self._request(
            "POST", f"/spd/or-cases/{case_id}/reservations", payload, headers
        )

    def list_tray_reservations(self, headers, params=None):
        return self._request(
            "GET", "/spd/tray-reservations", headers=headers, params=params
        )

    def get_tray_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/spd/tray-reservations/{reservation_id}", headers=headers
        )

    def release_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/spd/tray-reservations/{reservation_id}/release", {}, headers
        )

    def start_case(self, case_id, headers):
        return self._request("POST", f"/spd/or-cases/{case_id}/start", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/spd/or-cases/{case_id}/complete", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/spd/or-cases/{case_id}/cancel", {}, headers)

    # ---- IUSS exceptions -----------------------------------------------------
    def create_iuss_exception(self, payload, headers):
        return self._request("POST", "/spd/iuss-exceptions", payload, headers)

    def list_iuss_exceptions(self, headers, params=None):
        return self._request("GET", "/spd/iuss-exceptions", headers=headers, params=params)

    def get_iuss_exception(self, iuss_id, headers):
        return self._request("GET", f"/spd/iuss-exceptions/{iuss_id}", headers=headers)

    def review_iuss_exception(self, iuss_id, payload, headers):
        return self._request(
            "POST", f"/spd/iuss-exceptions/{iuss_id}/review", payload, headers
        )

    # ---- technicians ---------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/spd/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/spd/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/spd/technicians/{technician_id}", headers=headers)

    def update_technician(self, technician_id, payload, headers):
        return self._request("PUT", f"/spd/technicians/{technician_id}", payload, headers)

    def suspend_technician(self, technician_id, headers):
        return self._request(
            "POST", f"/spd/technicians/{technician_id}/suspend", {}, headers
        )

    def reinstate_technician(self, technician_id, headers):
        return self._request(
            "POST", f"/spd/technicians/{technician_id}/reinstate", {}, headers
        )

    # ---- loaner sets ----------------------------------------------------------
    def create_loaner_set(self, payload, headers):
        return self._request("POST", "/spd/loaner-sets", payload, headers)

    def list_loaner_sets(self, headers, params=None):
        return self._request("GET", "/spd/loaner-sets", headers=headers, params=params)

    def get_loaner_set(self, loaner_id, headers):
        return self._request("GET", f"/spd/loaner-sets/{loaner_id}", headers=headers)

    def receive_loaner_set(self, loaner_id, headers):
        return self._request(
            "POST", f"/spd/loaner-sets/{loaner_id}/receive", {}, headers
        )

    def mark_loaner_ready(self, loaner_id, headers):
        return self._request(
            "POST", f"/spd/loaner-sets/{loaner_id}/mark-ready", {}, headers
        )

    # ---- compliance -----------------------------------------------------------
    def get_compliance_summary(self, headers):
        return self._request("GET", "/spd/compliance/summary", headers=headers)


api_client = ApiClient()
