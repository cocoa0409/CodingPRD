"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- AlloySpec ---
    def create_alloy_spec(self, payload, headers):
        return self._request("POST", "/alloy-specs", payload, headers)

    def list_alloy_specs(self, headers, params=None):
        return self._request("GET", "/alloy-specs", headers=headers, params=params)

    def get_alloy_spec(self, alloy_id, headers):
        return self._request("GET", f"/alloy-specs/{alloy_id}", headers=headers)

    # --- MillHeat ---
    def create_mill_heat(self, payload, headers):
        return self._request("POST", "/mill-heats", payload, headers)

    def list_mill_heats(self, headers, params=None):
        return self._request("GET", "/mill-heats", headers=headers, params=params)

    def get_mill_heat(self, heat_id, headers):
        return self._request("GET", f"/mill-heats/{heat_id}", headers=headers)

    def verify_heat_cert(self, heat_id, payload, headers):
        return self._request("POST", f"/mill-heats/{heat_id}/verify-cert", payload, headers)

    def quarantine_heat(self, heat_id, payload, headers):
        return self._request("POST", f"/mill-heats/{heat_id}/quarantine", payload, headers)

    def release_heat_quarantine(self, heat_id, headers):
        return self._request("POST", f"/mill-heats/{heat_id}/release-quarantine", {}, headers)

    def reject_heat(self, heat_id, payload, headers):
        return self._request("POST", f"/mill-heats/{heat_id}/reject", payload, headers)

    # --- Billet ---
    def cut_billets(self, heat_id, payload, headers):
        return self._request("POST", f"/mill-heats/{heat_id}/billets", payload, headers)

    def list_heat_billets(self, heat_id, headers, params=None):
        return self._request("GET", f"/mill-heats/{heat_id}/billets", headers=headers, params=params)

    def list_billets(self, headers, params=None):
        return self._request("GET", "/billets", headers=headers, params=params)

    def get_billet(self, billet_id, headers):
        return self._request("GET", f"/billets/{billet_id}", headers=headers)

    def scrap_billet(self, billet_id, payload, headers):
        return self._request("POST", f"/billets/{billet_id}/scrap", payload, headers)

    # --- Furnace ---
    def create_furnace(self, payload, headers):
        return self._request("POST", "/furnaces", payload, headers)

    def list_furnaces(self, headers, params=None):
        return self._request("GET", "/furnaces", headers=headers, params=params)

    def get_furnace(self, furnace_id, headers):
        return self._request("GET", f"/furnaces/{furnace_id}", headers=headers)

    def set_furnace_status(self, furnace_id, payload, headers):
        return self._request("POST", f"/furnaces/{furnace_id}/set-status", payload, headers)

    # --- FurnaceCharge ---
    def create_furnace_charge(self, payload, headers):
        return self._request("POST", "/furnace-charges", payload, headers)

    def list_furnace_charges(self, headers, params=None):
        return self._request("GET", "/furnace-charges", headers=headers, params=params)

    def get_furnace_charge(self, charge_id, headers):
        return self._request("GET", f"/furnace-charges/{charge_id}", headers=headers)

    def close_charge_loading(self, charge_id, headers):
        return self._request("POST", f"/furnace-charges/{charge_id}/close-loading", {}, headers)

    def mark_charge_ready(self, charge_id, headers):
        return self._request("POST", f"/furnace-charges/{charge_id}/mark-ready", {}, headers)

    def discharge_charge(self, charge_id, headers):
        return self._request("POST", f"/furnace-charges/{charge_id}/discharge", {}, headers)

    def abort_charge(self, charge_id, headers):
        return self._request("POST", f"/furnace-charges/{charge_id}/abort", {}, headers)

    def list_charge_heats(self, charge_id, headers, params=None):
        return self._request("GET", f"/furnace-charges/{charge_id}/heats", headers=headers, params=params)

    # --- DieSet ---
    def create_die_set(self, payload, headers):
        return self._request("POST", "/die-sets", payload, headers)

    def list_die_sets(self, headers, params=None):
        return self._request("GET", "/die-sets", headers=headers, params=params)

    def get_die_set(self, die_id, headers):
        return self._request("GET", f"/die-sets/{die_id}", headers=headers)

    def install_die_set(self, die_id, payload, headers):
        return self._request("POST", f"/die-sets/{die_id}/install", payload, headers)

    def uninstall_die_set(self, die_id, headers):
        return self._request("POST", f"/die-sets/{die_id}/uninstall", {}, headers)

    def start_die_resink(self, die_id, headers):
        return self._request("POST", f"/die-sets/{die_id}/start-resink", {}, headers)

    def complete_die_resink(self, die_id, headers):
        return self._request("POST", f"/die-sets/{die_id}/complete-resink", {}, headers)

    def retire_die_set(self, die_id, headers):
        return self._request("POST", f"/die-sets/{die_id}/retire", {}, headers)

    # --- WorkCenter ---
    def create_work_center(self, payload, headers):
        return self._request("POST", "/work-centers", payload, headers)

    def list_work_centers(self, headers, params=None):
        return self._request("GET", "/work-centers", headers=headers, params=params)

    def get_work_center(self, wc_id, headers):
        return self._request("GET", f"/work-centers/{wc_id}", headers=headers)

    def set_work_center_status(self, wc_id, payload, headers):
        return self._request("POST", f"/work-centers/{wc_id}/set-status", payload, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", {}, headers)

    def ship_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/ship", payload, headers)

    def list_work_order_runs(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/forge-runs", headers=headers, params=params)

    def list_work_order_certs(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/quality-certs", headers=headers, params=params)

    def list_work_order_invoices(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/invoices", headers=headers, params=params)

    def list_work_order_parts(self, wo_id, headers, params=None):
        return self._request("GET", f"/work-orders/{wo_id}/part-serials", headers=headers, params=params)

    # --- ForgeRun ---
    def create_forge_run(self, payload, headers):
        return self._request("POST", "/forge-runs", payload, headers)

    def list_forge_runs(self, headers, params=None):
        return self._request("GET", "/forge-runs", headers=headers, params=params)

    def get_forge_run(self, run_id, headers):
        return self._request("GET", f"/forge-runs/{run_id}", headers=headers)

    def start_forge_run(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/start", {}, headers)

    def record_forge_heat(self, run_id, payload, headers):
        return self._request("POST", f"/forge-runs/{run_id}/heats", payload, headers)

    def list_forge_run_heats(self, run_id, headers, params=None):
        return self._request("GET", f"/forge-runs/{run_id}/heats", headers=headers, params=params)

    def finish_forging(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/finish-forging", {}, headers)

    def reopen_forge_run(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/reopen", {}, headers)

    def complete_forge_run(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/complete", {}, headers)

    def cancel_forge_run(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/cancel", {}, headers)

    # --- TrimTicket ---
    def create_trim_ticket(self, run_id, headers):
        return self._request("POST", f"/forge-runs/{run_id}/trim-tickets", {}, headers)

    def list_trim_tickets(self, run_id, headers, params=None):
        return self._request("GET", f"/forge-runs/{run_id}/trim-tickets", headers=headers, params=params)

    def get_trim_ticket(self, ticket_id, headers):
        return self._request("GET", f"/trim-tickets/{ticket_id}", headers=headers)

    def record_trim_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/trim-tickets/{ticket_id}/record", payload, headers)

    def approve_trim_deviation(self, ticket_id, payload, headers):
        return self._request("POST", f"/trim-tickets/{ticket_id}/approve-deviation", payload, headers)

    def void_trim_ticket(self, ticket_id, headers):
        return self._request("POST", f"/trim-tickets/{ticket_id}/void", {}, headers)

    # --- QualityCert ---
    def create_quality_cert(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/quality-certs", payload, headers)

    def list_quality_certs(self, headers, params=None):
        return self._request("GET", "/quality-certs", headers=headers, params=params)

    def get_quality_cert(self, cert_id, headers):
        return self._request("GET", f"/quality-certs/{cert_id}", headers=headers)

    def submit_quality_cert(self, cert_id, payload, headers):
        return self._request("POST", f"/quality-certs/{cert_id}/submit", payload, headers)

    def certify_quality_cert(self, cert_id, headers):
        return self._request("POST", f"/quality-certs/{cert_id}/certify", {}, headers)

    def reject_quality_cert(self, cert_id, payload, headers):
        return self._request("POST", f"/quality-certs/{cert_id}/reject", payload, headers)

    # --- PartSerial ---
    def list_part_serials(self, headers, params=None):
        return self._request("GET", "/part-serials", headers=headers, params=params)

    def get_part_serial(self, part_id, headers):
        return self._request("GET", f"/part-serials/{part_id}", headers=headers)

    def inspect_part_serial(self, part_id, headers):
        return self._request("POST", f"/part-serials/{part_id}/inspect", {}, headers)

    def scrap_part_serial(self, part_id, payload, headers):
        return self._request("POST", f"/part-serials/{part_id}/scrap", payload, headers)

    # --- SurchargeIndex ---
    def create_surcharge_index(self, payload, headers):
        return self._request("POST", "/surcharge-indices", payload, headers)

    def list_surcharge_indices(self, headers, params=None):
        return self._request("GET", "/surcharge-indices", headers=headers, params=params)

    def get_surcharge_index(self, index_id, headers):
        return self._request("GET", f"/surcharge-indices/{index_id}", headers=headers)

    # --- Invoice ---
    def create_invoice(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", {}, headers)


api_client = ApiClient()
