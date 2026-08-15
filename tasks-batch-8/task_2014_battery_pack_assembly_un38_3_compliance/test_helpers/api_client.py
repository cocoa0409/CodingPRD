"""API client: one method per endpoint defined in the PRD (section 4).

All business resources live under /api; the logical-clock capability lives
outside that prefix. Flat retrieval routes (PRD section 2.5) are included.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # IntegrationProgram
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/api/integration-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/api/integration-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}", headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/resume", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # CellLot / CellInspectionRecord
    # ------------------------------------------------------------------
    def create_cell_lot(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/cell-lots", payload, headers)

    def list_cell_lots(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/cell-lots", headers=headers, params=params)

    def get_cell_lot(self, program_id, lot_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/cell-lots/{lot_id}", headers=headers)

    def quarantine_cell_lot(self, program_id, lot_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/cell-lots/{lot_id}/quarantine", {}, headers)

    def create_cell_inspection(self, program_id, lot_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/cell-lots/{lot_id}/inspections", payload, headers)

    def list_cell_inspections(self, program_id, lot_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/cell-lots/{lot_id}/inspections", headers=headers, params=params)

    def retest_cell_lot(self, program_id, lot_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/cell-lots/{lot_id}/retest", {}, headers)

    # ------------------------------------------------------------------
    # PackBOM
    # ------------------------------------------------------------------
    def create_pack_bom(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/pack-boms", payload, headers)

    def list_pack_boms(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/pack-boms", headers=headers, params=params)

    def get_pack_bom(self, program_id, bom_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/pack-boms/{bom_id}", headers=headers)

    # ------------------------------------------------------------------
    # BatteryPack
    # ------------------------------------------------------------------
    def create_battery_pack(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs", payload, headers)

    def list_battery_packs(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs", headers=headers, params=params)

    def get_battery_pack(self, program_id, pack_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}", headers=headers)

    def pick_battery_pack(self, program_id, pack_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/pick", {}, headers)

    # ------------------------------------------------------------------
    # WeldingParameterRecord
    # ------------------------------------------------------------------
    def create_welding_record(self, program_id, pack_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/welding-records", payload, headers)

    def list_welding_records(self, program_id, pack_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/welding-records", headers=headers, params=params)

    def get_welding_record(self, program_id, pack_id, record_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/welding-records/{record_id}", headers=headers)

    def certify_welding_record(self, program_id, pack_id, record_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/welding-records/{record_id}/certify", {}, headers)

    # ------------------------------------------------------------------
    # BMSFirmware / FirmwareApproval
    # ------------------------------------------------------------------
    def create_bms_firmware(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/bms-firmwares", payload, headers)

    def list_bms_firmwares(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/bms-firmwares", headers=headers, params=params)

    def get_bms_firmware(self, program_id, fw_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/bms-firmwares/{fw_id}", headers=headers)

    def submit_firmware_review(self, program_id, fw_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/bms-firmwares/{fw_id}/submit-review", {}, headers)

    def create_firmware_approval(self, program_id, fw_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/bms-firmwares/{fw_id}/approvals", payload, headers)

    def list_firmware_approvals(self, program_id, fw_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/bms-firmwares/{fw_id}/approvals", headers=headers, params=params)

    def deprecate_firmware(self, program_id, fw_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/bms-firmwares/{fw_id}/deprecate", {}, headers)

    # ------------------------------------------------------------------
    # BMSFlashRecord
    # ------------------------------------------------------------------
    def create_bms_flash_record(self, program_id, pack_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/bms-flash-records", payload, headers)

    def list_bms_flash_records(self, program_id, pack_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/bms-flash-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # SafetyTestDossier
    # ------------------------------------------------------------------
    def create_safety_test_dossier(self, program_id, pack_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers", {}, headers)

    def list_safety_test_dossiers(self, program_id, pack_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers", headers=headers, params=params)

    def get_safety_test_dossier(self, program_id, pack_id, dossier_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers/{dossier_id}", headers=headers)

    def update_safety_test_dossier(self, program_id, pack_id, dossier_id, payload, headers):
        return self._request("PUT", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers/{dossier_id}", payload, headers)

    def submit_safety_test_dossier(self, program_id, pack_id, dossier_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers/{dossier_id}/submit", {}, headers)

    def approve_safety_test_dossier(self, program_id, pack_id, dossier_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/battery-packs/{pack_id}/safety-test-dossiers/{dossier_id}/approve", {}, headers)

    # ------------------------------------------------------------------
    # StorageLocation / StoragePlacement
    # ------------------------------------------------------------------
    def create_storage_location(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/storage-locations", payload, headers)

    def list_storage_locations(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/storage-locations", headers=headers, params=params)

    def get_storage_location(self, program_id, location_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/storage-locations/{location_id}", headers=headers)

    def create_storage_placement(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/storage-placements", payload, headers)

    def list_storage_placements(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/storage-placements", headers=headers, params=params)

    def get_storage_placement(self, program_id, placement_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/storage-placements/{placement_id}", headers=headers)

    def store_storage_placement(self, program_id, placement_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/storage-placements/{placement_id}/store", {}, headers)

    def release_storage_placement(self, program_id, placement_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/storage-placements/{placement_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # TransportShipment / ShipmentPackLink
    # ------------------------------------------------------------------
    def create_transport_shipment(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments", payload, headers)

    def list_transport_shipments(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/transport-shipments", headers=headers, params=params)

    def get_transport_shipment(self, program_id, shipment_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}", headers=headers)

    def attach_shipment_pack(self, program_id, shipment_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/attach", payload, headers)

    def list_shipment_packs(self, program_id, shipment_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/packs", headers=headers, params=params)

    def tender_shipment(self, program_id, shipment_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/tender", {}, headers)

    def carrier_accept_shipment(self, program_id, shipment_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/carrier-accept", payload, headers)

    def carrier_reject_shipment(self, program_id, shipment_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/carrier-reject", {}, headers)

    def mark_shipment_in_transit(self, program_id, shipment_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/mark-in-transit", {}, headers)

    def mark_shipment_delivered(self, program_id, shipment_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/transport-shipments/{shipment_id}/mark-delivered", {}, headers)

    # ------------------------------------------------------------------
    # ReturnAuthorization
    # ------------------------------------------------------------------
    def create_return_authorization(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations", payload, headers)

    def list_return_authorizations(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/return-authorizations", headers=headers, params=params)

    def get_return_authorization(self, program_id, rma_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}", headers=headers)

    def approve_return_authorization(self, program_id, rma_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/approve", {}, headers)

    def deny_return_authorization(self, program_id, rma_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/deny", {}, headers)

    def begin_discharge(self, program_id, rma_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/begin-discharge", {}, headers)

    def complete_discharge(self, program_id, rma_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/complete-discharge", payload, headers)

    def receive_return_authorization(self, program_id, rma_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/receive", {}, headers)

    def close_return_authorization(self, program_id, rma_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/return-authorizations/{rma_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # RecallCampaign
    # ------------------------------------------------------------------
    def create_recall_campaign(self, program_id, payload, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/recall-campaigns", payload, headers)

    def list_recall_campaigns(self, program_id, headers, params=None):
        return self._request("GET", f"/api/integration-programs/{program_id}/recall-campaigns", headers=headers, params=params)

    def get_recall_campaign(self, program_id, recall_id, headers):
        return self._request("GET", f"/api/integration-programs/{program_id}/recall-campaigns/{recall_id}", headers=headers)

    def activate_recall_campaign(self, program_id, recall_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/recall-campaigns/{recall_id}/activate", {}, headers)

    def mark_recall_contained(self, program_id, recall_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/recall-campaigns/{recall_id}/mark-contained", {}, headers)

    def close_recall_campaign(self, program_id, recall_id, headers):
        return self._request("POST", f"/api/integration-programs/{program_id}/recall-campaigns/{recall_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Logical clock (outside /api)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Flat single-get / filtered-list routes (PRD section 2.5)
    # ------------------------------------------------------------------
    def get_cell_lot_flat(self, lot_id, headers):
        return self._request("GET", f"/api/cell-lots/{lot_id}", headers=headers)

    def list_cell_lots_flat(self, headers, params=None):
        return self._request("GET", "/api/cell-lots", headers=headers, params=params)

    def get_cell_inspection_record_flat(self, rec_id, headers):
        return self._request("GET", f"/api/cell-inspection-records/{rec_id}", headers=headers)

    def list_cell_inspection_records_flat(self, headers, params=None):
        return self._request("GET", "/api/cell-inspection-records", headers=headers, params=params)

    def get_pack_bom_flat(self, bom_id, headers):
        return self._request("GET", f"/api/pack-boms/{bom_id}", headers=headers)

    def list_pack_boms_flat(self, headers, params=None):
        return self._request("GET", "/api/pack-boms", headers=headers, params=params)

    def get_battery_pack_flat(self, pack_id, headers):
        return self._request("GET", f"/api/battery-packs/{pack_id}", headers=headers)

    def list_battery_packs_flat(self, headers, params=None):
        return self._request("GET", "/api/battery-packs", headers=headers, params=params)

    def get_welding_parameter_record_flat(self, rec_id, headers):
        return self._request("GET", f"/api/welding-parameter-records/{rec_id}", headers=headers)

    def list_welding_parameter_records_flat(self, headers, params=None):
        return self._request("GET", "/api/welding-parameter-records", headers=headers, params=params)

    def get_bms_firmware_flat(self, fw_id, headers):
        return self._request("GET", f"/api/bms-firmwares/{fw_id}", headers=headers)

    def list_bms_firmwares_flat(self, headers, params=None):
        return self._request("GET", "/api/bms-firmwares", headers=headers, params=params)

    def get_firmware_approval_flat(self, approval_id, headers):
        return self._request("GET", f"/api/firmware-approvals/{approval_id}", headers=headers)

    def list_firmware_approvals_flat(self, headers, params=None):
        return self._request("GET", "/api/firmware-approvals", headers=headers, params=params)

    def get_bms_flash_record_flat(self, rec_id, headers):
        return self._request("GET", f"/api/bms-flash-records/{rec_id}", headers=headers)

    def list_bms_flash_records_flat(self, headers, params=None):
        return self._request("GET", "/api/bms-flash-records", headers=headers, params=params)

    def get_safety_test_dossier_flat(self, dossier_id, headers):
        return self._request("GET", f"/api/safety-test-dossiers/{dossier_id}", headers=headers)

    def list_safety_test_dossiers_flat(self, headers, params=None):
        return self._request("GET", "/api/safety-test-dossiers", headers=headers, params=params)

    def get_storage_location_flat(self, location_id, headers):
        return self._request("GET", f"/api/storage-locations/{location_id}", headers=headers)

    def list_storage_locations_flat(self, headers, params=None):
        return self._request("GET", "/api/storage-locations", headers=headers, params=params)

    def get_storage_placement_flat(self, placement_id, headers):
        return self._request("GET", f"/api/storage-placements/{placement_id}", headers=headers)

    def list_storage_placements_flat(self, headers, params=None):
        return self._request("GET", "/api/storage-placements", headers=headers, params=params)

    def get_transport_shipment_flat(self, shipment_id, headers):
        return self._request("GET", f"/api/transport-shipments/{shipment_id}", headers=headers)

    def list_transport_shipments_flat(self, headers, params=None):
        return self._request("GET", "/api/transport-shipments", headers=headers, params=params)

    def get_shipment_pack_link_flat(self, link_id, headers):
        return self._request("GET", f"/api/shipment-pack-links/{link_id}", headers=headers)

    def list_shipment_pack_links_flat(self, headers, params=None):
        return self._request("GET", "/api/shipment-pack-links", headers=headers, params=params)

    def get_return_authorization_flat(self, rma_id, headers):
        return self._request("GET", f"/api/return-authorizations/{rma_id}", headers=headers)

    def list_return_authorizations_flat(self, headers, params=None):
        return self._request("GET", "/api/return-authorizations", headers=headers, params=params)

    def get_recall_campaign_flat(self, recall_id, headers):
        return self._request("GET", f"/api/recall-campaigns/{recall_id}", headers=headers)

    def list_recall_campaigns_flat(self, headers, params=None):
        return self._request("GET", "/api/recall-campaigns", headers=headers, params=params)


api_client = ApiClient()
