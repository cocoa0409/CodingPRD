"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Test-driving clock (§3.10) ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ---------------- Parcel ----------------
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def list_parcel_crop_plans(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/crop-plans", headers=headers, params=params)

    def list_parcel_irrigation_events(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/irrigation-events", headers=headers, params=params)

    # ---------------- CropPlan ----------------
    def create_crop_plan(self, payload, headers):
        return self._request("POST", "/crop-plans", payload, headers)

    def get_crop_plan(self, plan_id, headers):
        return self._request("GET", f"/crop-plans/{plan_id}", headers=headers)

    def list_crop_plans(self, headers, params=None):
        return self._request("GET", "/crop-plans", headers=headers, params=params)

    def approve_crop_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/approve", payload, headers)

    def request_revision(self, plan_id, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/request-revision", {}, headers)

    def begin_growing(self, plan_id, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/begin-growing", {}, headers)

    def begin_harvest(self, plan_id, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/begin-harvest", {}, headers)

    def close_crop_plan(self, plan_id, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/close", {}, headers)

    def abandon_crop_plan(self, plan_id, headers):
        return self._request("POST", f"/crop-plans/{plan_id}/abandon", {}, headers)

    # ---------------- InputProduct ----------------
    def create_input_product(self, payload, headers):
        return self._request("POST", "/input-products", payload, headers)

    def get_input_product(self, product_id, headers):
        return self._request("GET", f"/input-products/{product_id}", headers=headers)

    def list_product_lots(self, product_id, headers, params=None):
        return self._request("GET", f"/input-products/{product_id}/lots", headers=headers, params=params)

    # ---------------- InputLot ----------------
    def create_input_lot(self, payload, headers):
        return self._request("POST", "/input-lots", payload, headers)

    def get_input_lot(self, lot_id, headers):
        return self._request("GET", f"/input-lots/{lot_id}", headers=headers)

    # ---------------- ApplicationRecord ----------------
    def create_application_record(self, payload, headers):
        return self._request("POST", "/application-records", payload, headers)

    def get_application_record(self, record_id, headers):
        return self._request("GET", f"/application-records/{record_id}", headers=headers)

    def list_application_records(self, headers, params=None):
        return self._request("GET", "/application-records", headers=headers, params=params)

    def confirm_application(self, record_id, headers):
        return self._request("POST", f"/application-records/{record_id}/confirm", {}, headers)

    def void_application(self, record_id, headers):
        return self._request("POST", f"/application-records/{record_id}/void", {}, headers)

    # ---------------- ComplianceRecord ----------------
    def get_compliance_record(self, record_id, headers):
        return self._request("GET", f"/compliance-records/{record_id}", headers=headers)

    def list_compliance_records(self, headers, params=None):
        return self._request("GET", "/compliance-records", headers=headers, params=params)

    # ---------------- PlantingEvent ----------------
    def create_planting_event(self, payload, headers):
        return self._request("POST", "/planting-events", payload, headers)

    def get_planting_event(self, event_id, headers):
        return self._request("GET", f"/planting-events/{event_id}", headers=headers)

    def list_planting_events(self, headers, params=None):
        return self._request("GET", "/planting-events", headers=headers, params=params)

    def void_planting_event(self, event_id, headers):
        return self._request("POST", f"/planting-events/{event_id}/void", {}, headers)

    # ---------------- HarvestEvent ----------------
    def create_harvest_event(self, payload, headers):
        return self._request("POST", "/harvest-events", payload, headers)

    def get_harvest_event(self, event_id, headers):
        return self._request("GET", f"/harvest-events/{event_id}", headers=headers)

    def list_harvest_events(self, headers, params=None):
        return self._request("GET", "/harvest-events", headers=headers, params=params)

    def list_harvest_event_lots(self, event_id, headers, params=None):
        return self._request("GET", f"/harvest-events/{event_id}/harvest-lots", headers=headers, params=params)

    # ---------------- HarvestLot ----------------
    def create_harvest_lot(self, payload, headers):
        return self._request("POST", "/harvest-lots", payload, headers)

    def get_harvest_lot(self, lot_id, headers):
        return self._request("GET", f"/harvest-lots/{lot_id}", headers=headers)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", "/harvest-lots", headers=headers, params=params)

    def grade_harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/harvest-lots/{lot_id}/grade", payload, headers)

    # ---------------- SaleContract ----------------
    def create_sale_contract(self, payload, headers):
        return self._request("POST", "/sale-contracts", payload, headers)

    def get_sale_contract(self, contract_id, headers):
        return self._request("GET", f"/sale-contracts/{contract_id}", headers=headers)

    def list_sale_contracts(self, headers, params=None):
        return self._request("GET", "/sale-contracts", headers=headers, params=params)

    def list_contract_harvest_lots(self, contract_id, headers, params=None):
        return self._request("GET", f"/sale-contracts/{contract_id}/harvest-lots", headers=headers, params=params)

    def commit_lot(self, contract_id, payload, headers):
        return self._request("POST", f"/sale-contracts/{contract_id}/commit-lot", payload, headers)

    def ship_contract(self, contract_id, headers):
        return self._request("POST", f"/sale-contracts/{contract_id}/ship", {}, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/sale-contracts/{contract_id}/cancel", {}, headers)

    # ---------------- EquipmentAsset ----------------
    def create_equipment_asset(self, payload, headers):
        return self._request("POST", "/equipment-assets", payload, headers)

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/equipment-assets/{asset_id}", headers=headers)

    def list_asset_usages(self, asset_id, headers, params=None):
        return self._request("GET", f"/equipment-assets/{asset_id}/usages", headers=headers, params=params)

    # ---------------- EquipmentUsage ----------------
    def create_equipment_usage(self, payload, headers):
        return self._request("POST", "/equipment-usages", payload, headers)

    def get_equipment_usage(self, usage_id, headers):
        return self._request("GET", f"/equipment-usages/{usage_id}", headers=headers)

    def list_equipment_usages(self, headers, params=None):
        return self._request("GET", "/equipment-usages", headers=headers, params=params)

    # ---------------- LaborEntry ----------------
    def create_labor_entry(self, payload, headers):
        return self._request("POST", "/labor-entries", payload, headers)

    def get_labor_entry(self, entry_id, headers):
        return self._request("GET", f"/labor-entries/{entry_id}", headers=headers)

    def list_labor_entries(self, headers, params=None):
        return self._request("GET", "/labor-entries", headers=headers, params=params)

    # ---------------- IrrigationEvent ----------------
    def create_irrigation_event(self, payload, headers):
        return self._request("POST", "/irrigation-events", payload, headers)

    def get_irrigation_event(self, event_id, headers):
        return self._request("GET", f"/irrigation-events/{event_id}", headers=headers)

    def complete_irrigation(self, event_id, headers):
        return self._request("POST", f"/irrigation-events/{event_id}/complete", {}, headers)

    def cancel_irrigation(self, event_id, headers):
        return self._request("POST", f"/irrigation-events/{event_id}/cancel", {}, headers)

    # ---------------- Applicator ----------------
    def create_applicator(self, payload, headers):
        return self._request("POST", "/applicators", payload, headers)

    def get_applicator(self, applicator_id, headers):
        return self._request("GET", f"/applicators/{applicator_id}", headers=headers)


api_client = ApiClient()
