"""API client: one method per endpoint defined in the Beekeeping Apiary PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock/now", headers=headers)

    # ─── Apiary ──────────────────────────────────────────────────────
    def create_apiary(self, payload, headers):
        return self._request("POST", "/apiaries", payload, headers)

    def get_apiary(self, apiary_id, headers):
        return self._request("GET", f"/apiaries/{apiary_id}", headers=headers)

    def list_apiaries(self, headers, params=None):
        return self._request("GET", "/apiaries", headers=headers, params=params)

    # ─── StateRegistration ───────────────────────────────────────────
    def create_registration(self, apiary_id, payload, headers):
        return self._request("POST", f"/apiaries/{apiary_id}/registrations",
                             payload, headers)

    def list_registrations(self, apiary_id, headers, params=None):
        return self._request("GET", f"/apiaries/{apiary_id}/registrations",
                             headers=headers, params=params)

    def approve_registration(self, apiary_id, rid, headers):
        return self._request("POST",
                             f"/apiaries/{apiary_id}/registrations/{rid}/approve",
                             headers=headers)

    def expire_registration(self, apiary_id, rid, headers):
        return self._request("POST",
                             f"/apiaries/{apiary_id}/registrations/{rid}/expire",
                             headers=headers)

    def revoke_registration(self, apiary_id, rid, headers):
        return self._request("POST",
                             f"/apiaries/{apiary_id}/registrations/{rid}/revoke",
                             headers=headers)

    # ─── Hive ────────────────────────────────────────────────────────
    def create_hive(self, payload, headers):
        return self._request("POST", "/hives", payload, headers)

    def get_hive(self, hive_id, headers):
        return self._request("GET", f"/hives/{hive_id}", headers=headers)

    def list_hives(self, headers, params=None):
        return self._request("GET", "/hives", headers=headers, params=params)

    def quarantine_hive(self, hive_id, headers):
        return self._request("POST", f"/hives/{hive_id}/quarantine", headers=headers)

    def deadout_hive(self, hive_id, headers):
        return self._request("POST", f"/hives/{hive_id}/deadout", headers=headers)

    def mark_queenless(self, hive_id, headers):
        return self._request("POST", f"/hives/{hive_id}/mark-queenless", headers=headers)

    def requeen_complete(self, hive_id, headers):
        return self._request("POST", f"/hives/{hive_id}/requeen-complete",
                             headers=headers)

    # ─── Inspection ──────────────────────────────────────────────────
    def create_inspection(self, hive_id, payload, headers):
        return self._request("POST", f"/hives/{hive_id}/inspections", payload, headers)

    def list_inspections(self, hive_id, headers, params=None):
        return self._request("GET", f"/hives/{hive_id}/inspections",
                             headers=headers, params=params)

    # ─── Treatment ───────────────────────────────────────────────────
    def create_treatment(self, hive_id, payload, headers):
        return self._request("POST", f"/hives/{hive_id}/treatments", payload, headers)

    def list_treatments(self, hive_id, headers, params=None):
        return self._request("GET", f"/hives/{hive_id}/treatments",
                             headers=headers, params=params)

    def complete_treatment(self, treatment_id, headers):
        return self._request("POST", f"/treatments/{treatment_id}/complete",
                             headers=headers)

    def void_treatment(self, treatment_id, headers):
        return self._request("POST", f"/treatments/{treatment_id}/void",
                             headers=headers)

    # ─── HoneyLot ────────────────────────────────────────────────────
    def create_honey_lot(self, payload, headers):
        return self._request("POST", "/honey-lots", payload, headers)

    def get_honey_lot(self, lot_id, headers):
        return self._request("GET", f"/honey-lots/{lot_id}", headers=headers)

    def list_honey_lots(self, headers, params=None):
        return self._request("GET", "/honey-lots", headers=headers, params=params)

    def unblock_honey_lot(self, lot_id, headers):
        return self._request("POST", f"/honey-lots/{lot_id}/unblock", headers=headers)

    def extract_honey_lot(self, lot_id, headers):
        return self._request("POST", f"/honey-lots/{lot_id}/extract", headers=headers)

    def sell_honey_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/honey-lots/{lot_id}/sell", payload, headers)

    def void_honey_lot(self, lot_id, headers):
        return self._request("POST", f"/honey-lots/{lot_id}/void", headers=headers)

    # ─── Harvest ─────────────────────────────────────────────────────
    def create_harvest(self, lot_id, payload, headers):
        return self._request("POST", f"/honey-lots/{lot_id}/harvests", payload, headers)

    def list_harvests_for_lot(self, lot_id, headers, params=None):
        return self._request("GET", f"/honey-lots/{lot_id}/harvests",
                             headers=headers, params=params)

    def get_harvest(self, harvest_id, headers):
        return self._request("GET", f"/harvests/{harvest_id}", headers=headers)

    def list_harvests(self, headers, params=None):
        return self._request("GET", "/harvests", headers=headers, params=params)

    def void_harvest(self, harvest_id, headers):
        return self._request("POST", f"/harvests/{harvest_id}/void", headers=headers)

    # ─── PollinationContract ─────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/pollination-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/pollination-contracts/{contract_id}",
                             headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/pollination-contracts",
                             headers=headers, params=params)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/pollination-contracts/{contract_id}/sign",
                             headers=headers)

    def finalize_placement(self, contract_id, headers):
        return self._request(
            "POST", f"/pollination-contracts/{contract_id}/finalize-placement",
            headers=headers)

    def dispute_contract(self, contract_id, headers):
        return self._request("POST", f"/pollination-contracts/{contract_id}/dispute",
                             headers=headers)

    def resolve_dispute(self, contract_id, headers):
        return self._request(
            "POST", f"/pollination-contracts/{contract_id}/resolve-dispute",
            headers=headers)

    def fulfill_contract(self, contract_id, headers):
        return self._request("POST", f"/pollination-contracts/{contract_id}/fulfill",
                             headers=headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/pollination-contracts/{contract_id}/cancel",
                             headers=headers)

    # ─── HivePlacement ───────────────────────────────────────────────
    def create_placement(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/pollination-contracts/{contract_id}/placements",
            payload, headers)

    def list_placements_for_contract(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/pollination-contracts/{contract_id}/placements",
            headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/hive-placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/hive-placements", headers=headers, params=params)

    def confirm_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/hive-placements/{placement_id}/confirm",
                             payload, headers)

    def remove_placement(self, placement_id, headers):
        return self._request("POST", f"/hive-placements/{placement_id}/remove",
                             headers=headers)

    def cancel_placement(self, placement_id, headers):
        return self._request("POST", f"/hive-placements/{placement_id}/cancel",
                             headers=headers)

    # ─── QueenNucSale ────────────────────────────────────────────────
    def create_sale(self, apiary_id, payload, headers):
        return self._request("POST", f"/apiaries/{apiary_id}/queen-nuc-sales",
                             payload, headers)

    def list_sales_for_apiary(self, apiary_id, headers, params=None):
        return self._request("GET", f"/apiaries/{apiary_id}/queen-nuc-sales",
                             headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/queen-nuc-sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/queen-nuc-sales", headers=headers, params=params)

    def ship_sale(self, sale_id, headers):
        return self._request("POST", f"/queen-nuc-sales/{sale_id}/ship", headers=headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/queen-nuc-sales/{sale_id}/void", headers=headers)

    # ─── Feeding ─────────────────────────────────────────────────────
    def create_feeding(self, hive_id, payload, headers):
        return self._request("POST", f"/hives/{hive_id}/feedings", payload, headers)

    def list_feedings(self, hive_id, headers, params=None):
        return self._request("GET", f"/hives/{hive_id}/feedings",
                             headers=headers, params=params)

    # ─── RequeenSchedule ─────────────────────────────────────────────
    def create_requeen_schedule(self, hive_id, payload, headers):
        return self._request("POST", f"/hives/{hive_id}/requeen-schedules",
                             payload, headers)

    def list_requeen_schedules(self, hive_id, headers, params=None):
        return self._request("GET", f"/hives/{hive_id}/requeen-schedules",
                             headers=headers, params=params)

    def start_requeen(self, schedule_id, headers):
        return self._request("POST", f"/requeen-schedules/{schedule_id}/start",
                             headers=headers)

    def cancel_requeen(self, schedule_id, headers):
        return self._request("POST", f"/requeen-schedules/{schedule_id}/cancel",
                             headers=headers)


api_client = ApiClient()
