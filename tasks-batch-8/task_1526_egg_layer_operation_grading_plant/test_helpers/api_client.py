"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock / daily ops run (PlatformAdmin) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_ops(self, headers):
        return self._request("POST", "/api/ops/run-daily", {}, headers)

    # --- Farm ---
    def create_farm(self, payload, headers):
        return self._request("POST", "/api/farms", payload, headers)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/api/farms/{farm_id}", headers=headers)

    # --- House ---
    def create_house(self, payload, headers):
        return self._request("POST", "/api/houses", payload, headers)

    def get_house(self, house_id, headers):
        return self._request("GET", f"/api/houses/{house_id}", headers=headers)

    def list_houses(self, headers, params=None):
        return self._request("GET", "/api/houses", headers=headers, params=params)

    # --- Flock ---
    def create_flock(self, payload, headers):
        return self._request("POST", "/api/flocks", payload, headers)

    def get_flock(self, flock_id, headers):
        return self._request("GET", f"/api/flocks/{flock_id}", headers=headers)

    def list_flocks(self, headers, params=None):
        return self._request("GET", "/api/flocks", headers=headers, params=params)

    def induce_molt(self, flock_id, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/induce-molt", {}, headers)

    def resume_lay(self, flock_id, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/resume-lay", {}, headers)

    def depopulate_flock(self, flock_id, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/depopulate", {}, headers)

    def get_flock_economics(self, flock_id, headers, params=None):
        return self._request(
            "GET", f"/api/flocks/{flock_id}/economics", headers=headers, params=params
        )

    # --- FeedDelivery ---
    def create_feed_delivery(self, payload, headers):
        return self._request("POST", "/api/feed-deliveries", payload, headers)

    def get_feed_delivery(self, feed_delivery_id, headers):
        return self._request(
            "GET", f"/api/feed-deliveries/{feed_delivery_id}", headers=headers
        )

    def list_feed_deliveries(self, headers, params=None):
        return self._request("GET", "/api/feed-deliveries", headers=headers, params=params)

    # --- ProductionDay ---
    def create_production_day(self, payload, headers):
        return self._request("POST", "/api/production-days", payload, headers)

    def get_production_day(self, production_day_id, headers):
        return self._request(
            "GET", f"/api/production-days/{production_day_id}", headers=headers
        )

    def list_production_days(self, headers, params=None):
        return self._request("GET", "/api/production-days", headers=headers, params=params)

    # --- GradingRun ---
    def create_grading_run(self, payload, headers):
        return self._request("POST", "/api/grading-runs", payload, headers)

    def get_grading_run(self, grading_run_id, headers):
        return self._request("GET", f"/api/grading-runs/{grading_run_id}", headers=headers)

    def list_grading_runs(self, headers, params=None):
        return self._request("GET", "/api/grading-runs", headers=headers, params=params)

    def submit_grading_run(self, grading_run_id, payload, headers):
        return self._request(
            "POST", f"/api/grading-runs/{grading_run_id}/submit", payload, headers
        )

    def confirm_grading_run(self, grading_run_id, headers):
        return self._request(
            "POST", f"/api/grading-runs/{grading_run_id}/confirm", {}, headers
        )

    def void_grading_run(self, grading_run_id, headers):
        return self._request(
            "POST", f"/api/grading-runs/{grading_run_id}/void", {}, headers
        )

    # --- EggLot ---
    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/release", {}, headers)

    def hold_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/hold", {}, headers)

    def clear_hold_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/clear-hold", {}, headers)

    def allocate_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/lots/{lot_id}/allocate", payload, headers)

    def ship_lot(self, lot_id, headers):
        return self._request("POST", f"/api/lots/{lot_id}/ship", {}, headers)

    # --- RetailerContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/activate", {}, headers
        )

    def suspend_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/suspend", {}, headers
        )

    def reinstate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/reinstate", {}, headers
        )

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/api/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/api/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/api/settlements/{settlement_id}/finalize", {}, headers
        )

    # --- SalmonellaTest ---
    def create_salmonella_test(self, payload, headers):
        return self._request("POST", "/api/salmonella-tests", payload, headers)

    def get_salmonella_test(self, salmonella_test_id, headers):
        return self._request(
            "GET", f"/api/salmonella-tests/{salmonella_test_id}", headers=headers
        )

    def list_salmonella_tests(self, headers, params=None):
        return self._request("GET", "/api/salmonella-tests", headers=headers, params=params)

    def collect_salmonella_test(self, salmonella_test_id, headers):
        return self._request(
            "POST", f"/api/salmonella-tests/{salmonella_test_id}/collect", {}, headers
        )

    def record_salmonella_result(self, salmonella_test_id, payload, headers):
        return self._request(
            "POST",
            f"/api/salmonella-tests/{salmonella_test_id}/record-result",
            payload,
            headers,
        )

    # --- ComplianceAudit ---
    def create_compliance_audit(self, payload, headers):
        return self._request("POST", "/api/compliance-audits", payload, headers)

    def get_compliance_audit(self, compliance_audit_id, headers):
        return self._request(
            "GET", f"/api/compliance-audits/{compliance_audit_id}", headers=headers
        )

    def list_compliance_audits(self, headers, params=None):
        return self._request(
            "GET", "/api/compliance-audits", headers=headers, params=params
        )

    def start_compliance_audit(self, compliance_audit_id, headers):
        return self._request(
            "POST", f"/api/compliance-audits/{compliance_audit_id}/start", {}, headers
        )

    def record_audit_findings(self, compliance_audit_id, payload, headers):
        return self._request(
            "POST",
            f"/api/compliance-audits/{compliance_audit_id}/record-findings",
            payload,
            headers,
        )

    def close_compliance_audit(self, compliance_audit_id, payload, headers):
        return self._request(
            "POST", f"/api/compliance-audits/{compliance_audit_id}/close", payload, headers
        )

    # --- Recall ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/api/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/api/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/api/recalls", headers=headers, params=params)

    def scope_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/scope", {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/close", {}, headers)

    # --- SpentHenDisposition ---
    def create_disposition(self, payload, headers):
        return self._request("POST", "/api/dispositions", payload, headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/api/dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/api/dispositions", headers=headers, params=params)

    def complete_disposition(self, disposition_id, headers):
        return self._request(
            "POST", f"/api/dispositions/{disposition_id}/complete", {}, headers
        )

    def void_disposition(self, disposition_id, headers):
        return self._request(
            "POST", f"/api/dispositions/{disposition_id}/void", {}, headers
        )


api_client = ApiClient()
