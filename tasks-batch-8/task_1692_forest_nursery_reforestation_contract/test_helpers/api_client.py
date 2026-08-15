"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reforestation"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Landowners ---
    def create_landowner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/landowners", payload, headers)

    def get_landowner(self, landowner_id, headers):
        return self._request("GET", f"{PREFIX}/landowners/{landowner_id}", headers=headers)

    # --- Seed zones ---
    def create_seed_zone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seed-zones", payload, headers)

    def get_seed_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/seed-zones/{zone_id}", headers=headers)

    # --- Seed lots ---
    def create_seed_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seed-lots", payload, headers)

    def get_seed_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/seed-lots/{lot_id}", headers=headers)

    def list_seed_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seed-lots", headers=headers, params=params)

    def quarantine_seed_lot(self, lot_id, headers):
        return self._request("POST", f"{PREFIX}/seed-lots/{lot_id}/quarantine", {}, headers)

    def release_seed_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/seed-lots/{lot_id}/release", payload, headers)

    # --- Crop batches ---
    def create_crop_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crop-batches", payload, headers)

    def get_crop_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/crop-batches/{batch_id}", headers=headers)

    def list_crop_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crop-batches", headers=headers, params=params)

    def sow_crop_batch(self, batch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/crop-batches/{batch_id}/sow", payload, headers)

    def lift_crop_batch(self, batch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/crop-batches/{batch_id}/lift", payload, headers)

    def grade_crop_batch(self, batch_id, payload, headers):
        return self._request("POST", f"{PREFIX}/crop-batches/{batch_id}/grade", payload, headers)

    # --- Seedling orders ---
    def create_seedling_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seedling-orders", payload, headers)

    def get_seedling_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/seedling-orders/{order_id}", headers=headers)

    def list_seedling_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seedling-orders", headers=headers, params=params)

    def confirm_seedling_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/seedling-orders/{order_id}/confirm", {}, headers)

    def amend_seedling_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/seedling-orders/{order_id}/amend", payload, headers)

    def cancel_seedling_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/seedling-orders/{order_id}/cancel", {}, headers)

    def create_allocation(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/seedling-orders/{order_id}/allocations", payload, headers)

    # --- Allocations ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"{PREFIX}/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"{PREFIX}/allocations/{allocation_id}/release", {}, headers)

    # --- Storage units ---
    def create_storage_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-units", payload, headers)

    def get_storage_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/storage-units/{unit_id}", headers=headers)

    # --- Storage placements ---
    def create_storage_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/storage-placements", payload, headers)

    def get_storage_placement(self, placement_id, headers):
        return self._request("GET", f"{PREFIX}/storage-placements/{placement_id}", headers=headers)

    def list_storage_placements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/storage-placements", headers=headers, params=params)

    def discard_storage_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/storage-placements/{placement_id}/discard", payload, headers,
        )

    # --- Planting contracts ---
    def create_planting_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/planting-contracts", payload, headers)

    def get_planting_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/planting-contracts/{contract_id}", headers=headers)

    def list_planting_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/planting-contracts", headers=headers, params=params)

    def record_site_prep(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/record-site-prep", payload, headers,
        )

    def verify_site_prep(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/verify-site-prep", {}, headers,
        )

    def mark_ready(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/mark-ready", {}, headers,
        )

    def start_planting(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/start-planting", {}, headers,
        )

    def complete_planting(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/complete-planting", payload, headers,
        )

    def cancel_planting_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/planting-contracts/{contract_id}/cancel", {}, headers,
        )

    # --- Crews ---
    def create_crew(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"{PREFIX}/crews/{crew_id}", headers=headers)

    # --- Crew assignments ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crew-assignments", headers=headers, params=params)

    def confirm_crew_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/crew-assignments/{assignment_id}/confirm", {}, headers,
        )

    def release_crew_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/crew-assignments/{assignment_id}/release", {}, headers,
        )

    # --- Shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/shipments/{shipment_id}/deliver", payload, headers)

    def confirm_shipment_planted(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/confirm-planted", payload, headers,
        )

    def report_shipment_spoilage(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/report-spoilage", payload, headers,
        )

    # --- Survival surveys ---
    def create_survival_survey(self, payload, headers):
        return self._request("POST", f"{PREFIX}/survival-surveys", payload, headers)

    def get_survival_survey(self, survey_id, headers):
        return self._request("GET", f"{PREFIX}/survival-surveys/{survey_id}", headers=headers)

    def list_survival_surveys(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/survival-surveys", headers=headers, params=params)

    def schedule_replant(self, survey_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/survival-surveys/{survey_id}/schedule-replant", payload, headers,
        )

    def reopen_replant(self, survey_id, headers):
        return self._request(
            "POST", f"{PREFIX}/survival-surveys/{survey_id}/reopen-replant", {}, headers,
        )

    def fulfill_replant(self, survey_id, headers):
        return self._request(
            "POST", f"{PREFIX}/survival-surveys/{survey_id}/fulfill-replant", {}, headers,
        )

    def waive_replant(self, survey_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/survival-surveys/{survey_id}/waive-replant", payload, headers,
        )

    # --- Cost-share enrollments ---
    def create_cost_share_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cost-share-enrollments", payload, headers)

    def get_cost_share_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cost-share-enrollments/{enrollment_id}", headers=headers,
        )

    def list_cost_share_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cost-share-enrollments", headers=headers, params=params)

    def submit_cost_share_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-share-enrollments/{enrollment_id}/submit", payload, headers,
        )

    def approve_cost_share_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-share-enrollments/{enrollment_id}/approve", {}, headers,
        )

    def return_enrollment_for_correction(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cost-share-enrollments/{enrollment_id}/return-for-correction",
            payload,
            headers,
        )

    def pay_cost_share_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cost-share-enrollments/{enrollment_id}/pay", {}, headers,
        )


api_client = ApiClient()
