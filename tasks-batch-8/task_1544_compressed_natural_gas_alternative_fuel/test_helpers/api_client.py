"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- stations ---
    def create_station(self, payload, headers):
        return self._request("POST", "/cng/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/cng/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/cng/stations/{station_id}", headers=headers)

    def activate_station(self, station_id, headers):
        return self._request("POST", f"/cng/stations/{station_id}/activate", {}, headers)

    def suspend_station(self, station_id, headers):
        return self._request("POST", f"/cng/stations/{station_id}/suspend", {}, headers)

    def resume_station(self, station_id, headers):
        return self._request("POST", f"/cng/stations/{station_id}/resume", {}, headers)

    # --- compressors ---
    def create_compressor(self, payload, headers):
        return self._request("POST", "/cng/compressors", payload, headers)

    def list_compressors(self, headers, params=None):
        return self._request("GET", "/cng/compressors", headers=headers, params=params)

    def get_compressor(self, compressor_id, headers):
        return self._request("GET", f"/cng/compressors/{compressor_id}", headers=headers)

    def report_compressor_condition(self, compressor_id, payload, headers):
        return self._request(
            "POST", f"/cng/compressors/{compressor_id}/report-condition", payload, headers
        )

    # --- dispensers ---
    def create_dispenser(self, payload, headers):
        return self._request("POST", "/cng/dispensers", payload, headers)

    def list_dispensers(self, headers, params=None):
        return self._request("GET", "/cng/dispensers", headers=headers, params=params)

    def get_dispenser(self, dispenser_id, headers):
        return self._request("GET", f"/cng/dispensers/{dispenser_id}", headers=headers)

    # --- calibration records ---
    def create_calibration_record(self, payload, headers):
        return self._request("POST", "/cng/calibration-records", payload, headers)

    def list_calibration_records(self, headers, params=None):
        return self._request("GET", "/cng/calibration-records", headers=headers, params=params)

    def get_calibration_record(self, record_id, headers):
        return self._request("GET", f"/cng/calibration-records/{record_id}", headers=headers)

    # --- pricing policies ---
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/cng/pricing-policies", payload, headers)

    def list_pricing_policies(self, headers, params=None):
        return self._request("GET", "/cng/pricing-policies", headers=headers, params=params)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/cng/pricing-policies/{policy_id}", headers=headers)

    # --- fleet accounts ---
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/cng/fleet-accounts", payload, headers)

    def list_fleet_accounts(self, headers, params=None):
        return self._request("GET", "/cng/fleet-accounts", headers=headers, params=params)

    def get_fleet_account(self, account_id, headers):
        return self._request("GET", f"/cng/fleet-accounts/{account_id}", headers=headers)

    def suspend_fleet_account(self, account_id, headers):
        return self._request("POST", f"/cng/fleet-accounts/{account_id}/suspend", {}, headers)

    def resume_fleet_account(self, account_id, headers):
        return self._request("POST", f"/cng/fleet-accounts/{account_id}/resume", {}, headers)

    def close_fleet_account(self, account_id, headers):
        return self._request("POST", f"/cng/fleet-accounts/{account_id}/close", {}, headers)

    # --- fleet cards ---
    def create_fleet_card(self, payload, headers):
        return self._request("POST", "/cng/fleet-cards", payload, headers)

    def list_fleet_cards(self, headers, params=None):
        return self._request("GET", "/cng/fleet-cards", headers=headers, params=params)

    def get_fleet_card(self, card_id, headers):
        return self._request("GET", f"/cng/fleet-cards/{card_id}", headers=headers)

    def set_fleet_card_status(self, card_id, payload, headers):
        return self._request("POST", f"/cng/fleet-cards/{card_id}/set-status", payload, headers)

    # --- supply contracts / settlements ---
    def create_supply_contract(self, payload, headers):
        return self._request("POST", "/cng/supply-contracts", payload, headers)

    def list_supply_contracts(self, headers, params=None):
        return self._request("GET", "/cng/supply-contracts", headers=headers, params=params)

    def get_supply_contract(self, contract_id, headers):
        return self._request("GET", f"/cng/supply-contracts/{contract_id}", headers=headers)

    def activate_supply_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/cng/supply-contracts/{contract_id}/activate", {}, headers
        )

    def settle_month(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/cng/supply-contracts/{contract_id}/settle-month", payload, headers
        )

    def list_monthly_settlements(self, headers, params=None):
        return self._request("GET", "/cng/monthly-settlements", headers=headers, params=params)

    def get_monthly_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/cng/monthly-settlements/{settlement_id}", headers=headers
        )

    # --- fueling sessions ---
    def authorize_session(self, payload, headers):
        return self._request("POST", "/cng/fueling-sessions/authorize", payload, headers)

    def authorize_public_session(self, payload, headers):
        return self._request("POST", "/cng/fueling-sessions/authorize-public", payload, headers)

    def complete_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/cng/fueling-sessions/{session_id}/complete", payload, headers
        )

    def void_session(self, session_id, payload, headers):
        return self._request("POST", f"/cng/fueling-sessions/{session_id}/void", payload, headers)

    def list_fueling_sessions(self, headers, params=None):
        return self._request("GET", "/cng/fueling-sessions", headers=headers, params=params)

    def get_fueling_session(self, session_id, headers):
        return self._request("GET", f"/cng/fueling-sessions/{session_id}", headers=headers)

    # --- maintenance windows ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/cng/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request("GET", "/cng/maintenance-windows", headers=headers, params=params)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/cng/maintenance-windows/{window_id}", headers=headers)

    def start_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/cng/maintenance-windows/{window_id}/start", {}, headers
        )

    def complete_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/cng/maintenance-windows/{window_id}/complete", {}, headers
        )

    def cancel_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/cng/maintenance-windows/{window_id}/cancel", {}, headers
        )

    # --- backup fueling arrangements ---
    def create_backup_arrangement(self, payload, headers):
        return self._request("POST", "/cng/backup-arrangements", payload, headers)

    def list_backup_arrangements(self, headers, params=None):
        return self._request("GET", "/cng/backup-arrangements", headers=headers, params=params)

    def get_backup_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/cng/backup-arrangements/{arrangement_id}", headers=headers)

    def activate_backup_arrangement(self, arrangement_id, headers):
        return self._request(
            "POST", f"/cng/backup-arrangements/{arrangement_id}/activate", {}, headers
        )

    def record_backup_draw(self, arrangement_id, payload, headers):
        return self._request(
            "POST", f"/cng/backup-arrangements/{arrangement_id}/record-draw", payload, headers
        )

    def release_backup_arrangement(self, arrangement_id, headers):
        return self._request(
            "POST", f"/cng/backup-arrangements/{arrangement_id}/release", {}, headers
        )

    # --- safety inspections ---
    def create_safety_inspection(self, payload, headers):
        return self._request("POST", "/cng/safety-inspections", payload, headers)

    def list_safety_inspections(self, headers, params=None):
        return self._request("GET", "/cng/safety-inspections", headers=headers, params=params)

    def get_safety_inspection(self, inspection_id, headers):
        return self._request("GET", f"/cng/safety-inspections/{inspection_id}", headers=headers)

    def complete_safety_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/cng/safety-inspections/{inspection_id}/complete", payload, headers
        )

    def approve_safety_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/cng/safety-inspections/{inspection_id}/approve", {}, headers
        )

    # --- tax credit claims ---
    def create_tax_credit_claim(self, payload, headers):
        return self._request("POST", "/cng/tax-credit-claims", payload, headers)

    def list_tax_credit_claims(self, headers, params=None):
        return self._request("GET", "/cng/tax-credit-claims", headers=headers, params=params)

    def get_tax_credit_claim(self, claim_id, headers):
        return self._request("GET", f"/cng/tax-credit-claims/{claim_id}", headers=headers)

    def finalize_tax_credit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/cng/tax-credit-claims/{claim_id}/finalize", {}, headers
        )

    def submit_tax_credit_claim(self, claim_id, headers):
        return self._request("POST", f"/cng/tax-credit-claims/{claim_id}/submit", {}, headers)

    def decide_tax_credit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/cng/tax-credit-claims/{claim_id}/decision", payload, headers
        )

    def reopen_tax_credit_claim(self, claim_id, headers):
        return self._request("POST", f"/cng/tax-credit-claims/{claim_id}/reopen", {}, headers)


api_client = ApiClient()
