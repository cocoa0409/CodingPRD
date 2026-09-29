"""API client: one method per endpoint defined in the PRD.

All paths are mounted under ``/toolworks`` and every single-resource path
parameter is literally ``{id}``.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/toolworks"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Tool SKU catalogue
    # ------------------------------------------------------------------
    def create_tool_sku(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tool-skus", payload, headers)

    def list_tool_skus(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tool-skus", headers=headers, params=params)

    def get_tool_sku(self, sku_id, headers):
        return self._request("GET", f"{PREFIX}/tool-skus/{sku_id}", headers=headers)

    def patch_tool_sku(self, sku_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/tool-skus/{sku_id}", payload, headers)

    def create_stock_receipt(self, sku_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tool-skus/{sku_id}/stock-receipts", payload, headers
        )

    def list_sku_production_lots(self, sku_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/tool-skus/{sku_id}/production-lots", headers=headers, params=params
        )

    def list_sku_counterfeit_reports(self, sku_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/tool-skus/{sku_id}/counterfeit-reports",
            headers=headers,
            params=params,
        )

    def list_sku_pack_memberships(self, sku_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/tool-skus/{sku_id}/pack-memberships",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Heat-treat furnaces
    # ------------------------------------------------------------------
    def create_heat_treat_furnace(self, payload, headers):
        return self._request("POST", f"{PREFIX}/heat-treat-furnaces", payload, headers)

    def list_heat_treat_furnaces(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/heat-treat-furnaces", headers=headers, params=params
        )

    def get_heat_treat_furnace(self, furnace_id, headers):
        return self._request(
            "GET", f"{PREFIX}/heat-treat-furnaces/{furnace_id}", headers=headers
        )

    def set_furnace_status(self, furnace_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/heat-treat-furnaces/{furnace_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Salt-spray chambers
    # ------------------------------------------------------------------
    def create_salt_spray_chamber(self, payload, headers):
        return self._request("POST", f"{PREFIX}/salt-spray-chambers", payload, headers)

    def list_salt_spray_chambers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/salt-spray-chambers", headers=headers, params=params
        )

    def get_salt_spray_chamber(self, chamber_id, headers):
        return self._request(
            "GET", f"{PREFIX}/salt-spray-chambers/{chamber_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Production lots
    # ------------------------------------------------------------------
    def create_production_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/production-lots", payload, headers)

    def list_production_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/production-lots", headers=headers, params=params)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/production-lots/{lot_id}", headers=headers)

    def advance_production_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/production-lots/{lot_id}/advance", payload, headers
        )

    def certify_production_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/production-lots/{lot_id}/certify", payload or {}, headers
        )

    def rework_production_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/production-lots/{lot_id}/rework", payload, headers
        )

    def release_production_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/production-lots/{lot_id}/release", payload, headers
        )

    def list_lot_test_runs(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/production-lots/{lot_id}/test-runs", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Furnace campaigns
    # ------------------------------------------------------------------
    def create_furnace_campaign(self, payload, headers):
        return self._request("POST", f"{PREFIX}/furnace-campaigns", payload, headers)

    def list_furnace_campaigns(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/furnace-campaigns", headers=headers, params=params
        )

    def get_furnace_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"{PREFIX}/furnace-campaigns/{campaign_id}", headers=headers
        )

    def complete_furnace_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/furnace-campaigns/{campaign_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Test runs
    # ------------------------------------------------------------------
    def create_test_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-runs", payload, headers)

    def list_test_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/test-runs", headers=headers, params=params)

    def get_test_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/test-runs/{run_id}", headers=headers)

    def submit_test_run_results(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-runs/{run_id}/results", payload, headers)

    def void_test_run(self, run_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-runs/{run_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Pack configurations
    # ------------------------------------------------------------------
    def create_pack_configuration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pack-configurations", payload, headers)

    def list_pack_configurations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pack-configurations", headers=headers, params=params
        )

    def get_pack_configuration(self, pack_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pack-configurations/{pack_id}", headers=headers
        )

    def add_pack_member(self, pack_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pack-configurations/{pack_id}/members", payload, headers
        )

    def list_pack_members(self, pack_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/pack-configurations/{pack_id}/members",
            headers=headers,
            params=params,
        )

    def approve_pack_configuration(self, pack_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/pack-configurations/{pack_id}/approve", payload or {}, headers
        )

    def withdraw_pack_configuration(self, pack_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pack-configurations/{pack_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Warranty programmes
    # ------------------------------------------------------------------
    def create_warranty_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-programs", payload, headers)

    def list_warranty_programs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/warranty-programs", headers=headers, params=params
        )

    def get_warranty_program(self, program_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-programs/{program_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Claimants
    # ------------------------------------------------------------------
    def create_claimant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claimants", payload, headers)

    def list_claimants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claimants", headers=headers, params=params)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"{PREFIX}/claimants/{claimant_id}", headers=headers)

    def block_claimant(self, claimant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claimants/{claimant_id}/block", payload, headers
        )

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/lines", payload, headers
        )

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/warranty-claims/{claim_id}/lines", headers=headers, params=params
        )

    def hold_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/hold", payload, headers
        )

    def clear_hold_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/clear-hold", payload, headers
        )

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/approve", payload, headers
        )

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/deny", payload, headers
        )

    def deny_fraud_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/deny-fraud", payload, headers
        )

    def fulfill_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/fulfill", payload, headers
        )

    def revoke_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-claims/{claim_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Counterfeit reports
    # ------------------------------------------------------------------
    def create_counterfeit_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counterfeit-reports", payload, headers)

    def list_counterfeit_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counterfeit-reports", headers=headers, params=params
        )

    def get_counterfeit_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counterfeit-reports/{report_id}", headers=headers
        )

    def confirm_counterfeit_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counterfeit-reports/{report_id}/confirm", payload, headers
        )

    def dismiss_counterfeit_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counterfeit-reports/{report_id}/dismiss", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical shop clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
