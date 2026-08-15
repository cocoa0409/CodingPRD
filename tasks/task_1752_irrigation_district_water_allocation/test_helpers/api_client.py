"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- water accounts ---
    def create_water_account(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/water-accounts", payload, headers)

    def list_water_accounts(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/water-accounts", headers=headers, params=params)

    def get_water_account(self, account_id: str, headers: Dict):
        return self._request("GET", f"/district/water-accounts/{account_id}", headers=headers)

    def close_water_account(self, account_id: str, headers: Dict):
        return self._request("POST", f"/district/water-accounts/{account_id}/close", {}, headers)

    # --- irrigation seasons ---
    def create_season(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/seasons", payload, headers)

    def list_seasons(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/seasons", headers=headers, params=params)

    def get_season(self, season_id: str, headers: Dict):
        return self._request("GET", f"/district/seasons/{season_id}", headers=headers)

    def announce_season(self, season_id: str, headers: Dict):
        return self._request("POST", f"/district/seasons/{season_id}/announce", {}, headers)

    def open_season(self, season_id: str, headers: Dict):
        return self._request("POST", f"/district/seasons/{season_id}/open", {}, headers)

    def close_season(self, season_id: str, headers: Dict):
        return self._request("POST", f"/district/seasons/{season_id}/close", {}, headers)

    def run_delinquency_sweep(self, season_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/seasons/{season_id}/run-delinquency-sweep", {}, headers,
        )

    # --- season allocations ---
    def create_season_allocation(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/season-allocations", payload, headers)

    def list_season_allocations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/season-allocations", headers=headers, params=params)

    def get_season_allocation(self, allocation_id: str, headers: Dict):
        return self._request("GET", f"/district/season-allocations/{allocation_id}", headers=headers)

    # --- turnout orders ---
    def create_turnout_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/turnout-orders", payload, headers)

    def list_turnout_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/turnout-orders", headers=headers, params=params)

    def get_turnout_order(self, order_id: str, headers: Dict):
        return self._request("GET", f"/district/turnout-orders/{order_id}", headers=headers)

    def schedule_turnout_order(self, order_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/district/turnout-orders/{order_id}/schedule", payload, headers,
        )

    def reject_turnout_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/district/turnout-orders/{order_id}/reject", {}, headers)

    def cancel_turnout_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/district/turnout-orders/{order_id}/cancel", {}, headers)

    def start_turnout_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/district/turnout-orders/{order_id}/start", {}, headers)

    # --- rider work orders ---
    def list_rider_work_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/rider-work-orders", headers=headers, params=params)

    def get_rider_work_order(self, work_order_id: str, headers: Dict):
        return self._request("GET", f"/district/rider-work-orders/{work_order_id}", headers=headers)

    def submit_measurement(self, work_order_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/district/rider-work-orders/{work_order_id}/submit-measurement",
            payload, headers,
        )

    def verify_work_order(self, work_order_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/rider-work-orders/{work_order_id}/verify", {}, headers,
        )

    def return_work_order(self, work_order_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/district/rider-work-orders/{work_order_id}/return", payload, headers,
        )

    # --- assessment invoices ---
    def create_assessment_invoice(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/assessment-invoices", payload, headers)

    def list_assessment_invoices(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/assessment-invoices", headers=headers, params=params)

    def get_assessment_invoice(self, invoice_id: str, headers: Dict):
        return self._request("GET", f"/district/assessment-invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/district/assessment-invoices/{invoice_id}/issue", payload, headers,
        )

    def pay_invoice(self, invoice_id: str, headers: Dict):
        return self._request("POST", f"/district/assessment-invoices/{invoice_id}/pay", {}, headers)

    def file_lien(self, invoice_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/assessment-invoices/{invoice_id}/file-lien", {}, headers,
        )

    # --- canal reaches ---
    def create_canal_reach(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/canal-reaches", payload, headers)

    def list_canal_reaches(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/canal-reaches", headers=headers, params=params)

    def get_canal_reach(self, reach_id: str, headers: Dict):
        return self._request("GET", f"/district/canal-reaches/{reach_id}", headers=headers)

    # --- maintenance windows ---
    def create_maintenance_window(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/maintenance-windows", headers=headers, params=params)

    def get_maintenance_window(self, window_id: str, headers: Dict):
        return self._request("GET", f"/district/maintenance-windows/{window_id}", headers=headers)

    def activate_maintenance_window(self, window_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/maintenance-windows/{window_id}/activate", {}, headers,
        )

    def complete_maintenance_window(self, window_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/maintenance-windows/{window_id}/complete", {}, headers,
        )

    def cancel_maintenance_window(self, window_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/maintenance-windows/{window_id}/cancel", {}, headers,
        )

    # --- transfer requests ---
    def create_transfer_request(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/transfer-requests", headers=headers, params=params)

    def get_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request("GET", f"/district/transfer-requests/{transfer_id}", headers=headers)

    def approve_transfer(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/transfer-requests/{transfer_id}/approve", {}, headers,
        )

    def post_transfer(self, transfer_id: str, headers: Dict):
        return self._request("POST", f"/district/transfer-requests/{transfer_id}/post", {}, headers)

    def reject_transfer(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/transfer-requests/{transfer_id}/reject", {}, headers,
        )

    def cancel_transfer(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/transfer-requests/{transfer_id}/cancel", {}, headers,
        )

    # --- drought declarations ---
    def create_drought_declaration(self, payload: Dict, headers: Dict):
        return self._request("POST", "/district/drought-declarations", payload, headers)

    def list_drought_declarations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/district/drought-declarations", headers=headers, params=params)

    def get_drought_declaration(self, declaration_id: str, headers: Dict):
        return self._request(
            "GET", f"/district/drought-declarations/{declaration_id}", headers=headers,
        )

    def effectuate_drought(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/drought-declarations/{declaration_id}/effectuate", {}, headers,
        )

    def lift_drought(self, declaration_id: str, headers: Dict):
        return self._request(
            "POST", f"/district/drought-declarations/{declaration_id}/lift", {}, headers,
        )


api_client = ApiClient()
