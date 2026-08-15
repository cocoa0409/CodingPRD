"""Composite setup helpers.

Most testable claims in this PRD require deep preconditions (a pack cannot be
classified until welded, certified, flashed, and dossier-approved). These
helpers encapsulate those multi-step pipelines so tests can focus on
assertions. All helpers use get_success_data() so a broken precondition
fails loudly as a setup error rather than a confusing assertion.

Identity threading: segregation-of-duties pairs always use distinct operator
ids — the weld operator defaults to ``al-weld-1`` while the weld certifier
defaults to ``qe-cert-1``; the firmware submitter defaults to ``al-fw-1``
while the firmware approver defaults to ``so-fw-1``; the RMA requester
defaults to ``cs-rma-1`` while the RMA approver defaults to ``so-rma-1``.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CELLS_REQUIRED,
    DEFAULT_RATED_CAPACITY_MAH,
    DEFAULT_RECEIVING_SOC,
)
from .factories import (
    create_battery_pack_payload,
    create_bms_firmware_payload,
    create_bms_flash_record_payload,
    create_cell_inspection_payload,
    create_cell_lot_payload,
    create_dossier_matrix_payload,
    create_firmware_approval_payload,
    create_pack_bom_payload,
    create_program_payload,
    create_recall_campaign_payload,
    create_return_authorization_payload,
    create_storage_location_payload,
    create_storage_placement_payload,
    create_transport_shipment_payload,
    create_attach_pack_payload,
    create_welding_record_payload,
)
from .test_users import (
    make_any_headers,
    make_assembly_lead_headers,
    make_carrier_agent_headers,
    make_customer_service_headers,
    make_logistics_coordinator_headers,
    make_quality_engineer_headers,
    make_safety_officer_headers,
)

ANY = make_any_headers()


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def create_program(program_code=None, storage_capacity_wh=100000, officer_id="so-1"):
    """POST /integration-programs. Returns the created program."""
    resp = api_client.create_program(
        create_program_payload(program_code, storage_capacity_wh),
        make_safety_officer_headers(officer_id),
    )
    return get_success_data(resp, 201)


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, ANY))


def create_accepted_cell_lot(program_id, *, soc_percent=DEFAULT_RECEIVING_SOC, cell_count=100,
                             rated_capacity_mah=DEFAULT_RATED_CAPACITY_MAH, lot_code=None,
                             engineer_id="qe-lot-1"):
    """Cell lot driven RECEIVED -> QUARANTINE -> ACCEPTED via a PASS
    inspection whose measured SOC equals the declared receiving SOC."""
    headers = make_quality_engineer_headers(engineer_id)
    lot = get_success_data(
        api_client.create_cell_lot(
            program_id,
            create_cell_lot_payload(lot_code, cell_count, rated_capacity_mah, soc_percent),
            headers,
        ),
        201,
    )
    get_success_data(api_client.quarantine_cell_lot(program_id, lot["id"], headers))
    get_success_data(
        api_client.create_cell_inspection(
            program_id,
            lot["id"],
            create_cell_inspection_payload(measured_soc_percent=soc_percent, outcome="PASS"),
            headers,
        ),
        201,
    )
    return get_success_data(api_client.get_cell_lot(program_id, lot["id"], ANY))


def create_pack_bom(program_id, cell_lot_id, *, bom_code=None, cells_required=DEFAULT_CELLS_REQUIRED,
                    series_count=2, parallel_count=2, welding_profile="WELD_PROFILE_A",
                    lead_id="al-bom-1"):
    resp = api_client.create_pack_bom(
        program_id,
        create_pack_bom_payload(cell_lot_id, bom_code, cells_required, series_count,
                                parallel_count, welding_profile),
        make_assembly_lead_headers(lead_id),
    )
    return get_success_data(resp, 201)


def get_pack_bom(program_id, bom_id):
    return get_success_data(api_client.get_pack_bom(program_id, bom_id, ANY))


def create_battery_pack(program_id, bom_id, *, lead_id="al-pack-1"):
    """Assemble a pack, reading the BOM's live version first so the OCC
    guard is always satisfied (PRD section 2.10)."""
    bom = get_pack_bom(program_id, bom_id)
    resp = api_client.create_battery_pack(
        program_id,
        create_battery_pack_payload(bom_id, bom["version"]),
        make_assembly_lead_headers(lead_id),
    )
    return get_success_data(resp, 201)


def get_battery_pack(program_id, pack_id):
    return get_success_data(api_client.get_battery_pack(program_id, pack_id, ANY))


# ---------------------------------------------------------------------------
# Tier 2: assembly-axis progression
# ---------------------------------------------------------------------------

def record_weld(program_id, pack_id, *, operator_id="al-weld-1",
                weld_profile_used="WELD_PROFILE_A", **weld_overrides):
    resp = api_client.create_welding_record(
        program_id,
        pack_id,
        create_welding_record_payload(weld_profile_used, **weld_overrides),
        make_assembly_lead_headers(operator_id),
    )
    return get_success_data(resp, 201)


def certify_weld(program_id, pack_id, record_id, *, certifier_id="qe-cert-1"):
    resp = api_client.certify_welding_record(
        program_id, pack_id, record_id, make_quality_engineer_headers(certifier_id)
    )
    return get_success_data(resp)


def create_approved_firmware(program_id, *, submitter_id="al-fw-1", approver_id="so-fw-1",
                             firmware_version="1.0.0", supports_soc_hysteresis=False,
                             binary_sha256=None):
    """Firmware driven DRAFT -> PENDING_REVIEW -> APPROVED."""
    fw = get_success_data(
        api_client.create_bms_firmware(
            program_id,
            create_bms_firmware_payload(firmware_version, binary_sha256, supports_soc_hysteresis),
            make_assembly_lead_headers(submitter_id),
        ),
        201,
    )
    get_success_data(
        api_client.submit_firmware_review(program_id, fw["id"], make_assembly_lead_headers(submitter_id))
    )
    get_success_data(
        api_client.create_firmware_approval(
            program_id,
            fw["id"],
            create_firmware_approval_payload("APPROVE"),
            make_safety_officer_headers(approver_id),
        ),
        201,
    )
    return get_success_data(api_client.get_bms_firmware(program_id, fw["id"], ANY))


def get_bms_firmware(program_id, fw_id):
    return get_success_data(api_client.get_bms_firmware(program_id, fw_id, ANY))


def flash_pack(program_id, pack_id, firmware_id, *, flasher_id="al-flash-1"):
    resp = api_client.create_bms_flash_record(
        program_id,
        pack_id,
        create_bms_flash_record_payload(firmware_id),
        make_assembly_lead_headers(flasher_id),
    )
    return get_success_data(resp, 201)


def open_dossier(program_id, pack_id, *, engineer_id="qe-doss-1"):
    resp = api_client.create_safety_test_dossier(
        program_id, pack_id, make_quality_engineer_headers(engineer_id)
    )
    return get_success_data(resp, 201)


def record_test_matrix(program_id, pack_id, dossier_id, *, engineer_id="qe-doss-1",
                       expected_pack_version=None, **matrix_overrides):
    """Record the eight-field T1..T8 matrix. When expected_pack_version is
    not supplied, the pack's live version is read first so the OCC guard is
    satisfied (PRD section 2.10)."""
    if expected_pack_version is None:
        expected_pack_version = get_battery_pack(program_id, pack_id)["version"]
    payload = create_dossier_matrix_payload(expected_pack_version, **matrix_overrides)
    resp = api_client.update_safety_test_dossier(
        program_id, pack_id, dossier_id, payload, make_quality_engineer_headers(engineer_id)
    )
    return get_success_data(resp)


def submit_dossier(program_id, pack_id, dossier_id, *, officer_id="so-doss-1"):
    resp = api_client.submit_safety_test_dossier(
        program_id, pack_id, dossier_id, make_safety_officer_headers(officer_id)
    )
    return get_success_data(resp)


def approve_dossier(program_id, pack_id, dossier_id, *, officer_id="so-doss-1"):
    resp = api_client.approve_safety_test_dossier(
        program_id, pack_id, dossier_id, make_safety_officer_headers(officer_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: full assembly pipelines
# ---------------------------------------------------------------------------

def setup_program_with_bom(*, program_code=None, storage_capacity_wh=100000,
                           soc_percent=DEFAULT_RECEIVING_SOC, cell_count=100,
                           rated_capacity_mah=DEFAULT_RATED_CAPACITY_MAH,
                           cells_required=DEFAULT_CELLS_REQUIRED,
                           welding_profile="WELD_PROFILE_A"):
    """Program + ACCEPTED lot + PackBOM. Returns dict of the three."""
    program = create_program(program_code, storage_capacity_wh)
    lot = create_accepted_cell_lot(
        program["id"], soc_percent=soc_percent, cell_count=cell_count,
        rated_capacity_mah=rated_capacity_mah,
    )
    bom = create_pack_bom(
        program["id"], lot["id"], cells_required=cells_required, welding_profile=welding_profile
    )
    return {"program": program, "lot": lot, "bom": bom}


def drive_pack_to_bms_flashed(program_id, bom, *, firmware=None,
                              weld_operator_id="al-weld-1", certifier_id="qe-cert-1"):
    """Pack driven BUILT -> WELD_RECORDED -> WELD_CERTIFIED -> BMS_FLASHED."""
    pack = create_battery_pack(program_id, bom["id"])
    record = record_weld(program_id, pack["id"], operator_id=weld_operator_id,
                         weld_profile_used=bom["welding_profile"])
    certify_weld(program_id, pack["id"], record["id"], certifier_id=certifier_id)
    if firmware is None:
        firmware = create_approved_firmware(program_id)
    flash_pack(program_id, pack["id"], firmware["id"])
    pack = get_battery_pack(program_id, pack["id"])
    return {"pack": pack, "weld_record": record, "firmware": firmware}


def drive_pack_to_test_queued(program_id, bom, *, firmware=None, **kwargs):
    """Adds dossier opening on top of BMS_FLASHED. Pack ends TEST_QUEUED."""
    bundle = drive_pack_to_bms_flashed(program_id, bom, firmware=firmware, **kwargs)
    dossier = open_dossier(program_id, bundle["pack"]["id"])
    bundle["dossier"] = dossier
    bundle["pack"] = get_battery_pack(program_id, bundle["pack"]["id"])
    return bundle


def drive_pack_to_classified(program_id, bom, *, firmware=None, matrix_overrides=None, **kwargs):
    """Adds the test matrix + dossier submission. Pack ends CLASSIFIED."""
    bundle = drive_pack_to_test_queued(program_id, bom, firmware=firmware, **kwargs)
    pack_id = bundle["pack"]["id"]
    dossier_id = bundle["dossier"]["id"]
    record_test_matrix(program_id, pack_id, dossier_id, **(matrix_overrides or {}))
    bundle["dossier"] = submit_dossier(program_id, pack_id, dossier_id)
    bundle["pack"] = get_battery_pack(program_id, pack_id)
    return bundle


def drive_pack_to_ready_to_store(program_id, bom, *, firmware=None, **kwargs):
    """Full assembly axis: pack ends READY_TO_STORE with an APPROVED dossier."""
    bundle = drive_pack_to_classified(program_id, bom, firmware=firmware, **kwargs)
    pack_id = bundle["pack"]["id"]
    bundle["dossier"] = approve_dossier(program_id, pack_id, bundle["dossier"]["id"])
    bundle["pack"] = get_battery_pack(program_id, pack_id)
    return bundle


def setup_ready_to_store_pack(*, program_code=None, storage_capacity_wh=100000,
                              soc_percent=DEFAULT_RECEIVING_SOC, cell_count=100,
                              cells_required=DEFAULT_CELLS_REQUIRED,
                              welding_profile="WELD_PROFILE_A"):
    """Program + lot + BOM + one pack at READY_TO_STORE. Returns the full bundle."""
    base = setup_program_with_bom(
        program_code=program_code,
        storage_capacity_wh=storage_capacity_wh,
        soc_percent=soc_percent,
        cell_count=cell_count,
        cells_required=cells_required,
        welding_profile=welding_profile,
    )
    bundle = drive_pack_to_ready_to_store(base["program"]["id"], base["bom"])
    base.update(bundle)
    return base


# ---------------------------------------------------------------------------
# Tier 4: logistics-axis progression
# ---------------------------------------------------------------------------

def create_storage_location(program_id, *, location_code=None, fire_zone="ZONE_A",
                            capacity_wh=5000, accepts_soc_band=None, coordinator_id="lc-1"):
    resp = api_client.create_storage_location(
        program_id,
        create_storage_location_payload(location_code, fire_zone, capacity_wh, accepts_soc_band),
        make_logistics_coordinator_headers(coordinator_id),
    )
    return get_success_data(resp, 201)


def get_storage_location(program_id, location_id):
    return get_success_data(api_client.get_storage_location(program_id, location_id, ANY))


def stage_pack(program_id, location_id, pack_id, *, coordinator_id="lc-1"):
    resp = api_client.create_storage_placement(
        program_id,
        create_storage_placement_payload(location_id, pack_id),
        make_logistics_coordinator_headers(coordinator_id),
    )
    return get_success_data(resp, 201)


def store_placement(program_id, placement_id, *, coordinator_id="lc-1"):
    resp = api_client.store_storage_placement(
        program_id, placement_id, make_logistics_coordinator_headers(coordinator_id)
    )
    return get_success_data(resp)


def release_placement(program_id, placement_id, *, coordinator_id="lc-1"):
    resp = api_client.release_storage_placement(
        program_id, placement_id, make_logistics_coordinator_headers(coordinator_id)
    )
    return get_success_data(resp)


def pick_pack(program_id, pack_id, *, coordinator_id="lc-1"):
    resp = api_client.pick_battery_pack(
        program_id, pack_id, make_logistics_coordinator_headers(coordinator_id)
    )
    return get_success_data(resp)


def stage_store_pick_pack(program_id, pack_id, *, capacity_wh=5000, accepts_soc_band=None,
                          location_code=None, coordinator_id="lc-1"):
    """Location + placement STAGED -> STORED -> pack PICKED. Returns
    (location, placement)."""
    location = create_storage_location(
        program_id, location_code=location_code, capacity_wh=capacity_wh,
        accepts_soc_band=accepts_soc_band, coordinator_id=coordinator_id,
    )
    placement = stage_pack(program_id, location["id"], pack_id, coordinator_id=coordinator_id)
    store_placement(program_id, placement["id"], coordinator_id=coordinator_id)
    pick_pack(program_id, pack_id, coordinator_id=coordinator_id)
    placement = get_success_data(api_client.get_storage_placement(program_id, placement["id"], ANY))
    return location, placement


# ---------------------------------------------------------------------------
# Tier 5: transport pipeline
# ---------------------------------------------------------------------------

def create_shipment(program_id, *, carrier_code="DHL-DG", un_class_code="UN3480",
                    declared_weight_kg=10.00, coordinator_id="lc-1"):
    resp = api_client.create_transport_shipment(
        program_id,
        create_transport_shipment_payload(carrier_code, un_class_code, declared_weight_kg),
        make_logistics_coordinator_headers(coordinator_id),
    )
    return get_success_data(resp, 201)


def get_shipment(program_id, shipment_id):
    return get_success_data(api_client.get_transport_shipment(program_id, shipment_id, ANY))


def attach_pack(program_id, shipment_id, pack_id, *, coordinator_id="lc-1"):
    resp = api_client.attach_shipment_pack(
        program_id,
        shipment_id,
        create_attach_pack_payload(pack_id),
        make_logistics_coordinator_headers(coordinator_id),
    )
    return get_success_data(resp, 201)


def tender_shipment(program_id, shipment_id, *, coordinator_id="lc-1"):
    resp = api_client.tender_shipment(
        program_id, shipment_id, make_logistics_coordinator_headers(coordinator_id)
    )
    return get_success_data(resp)


def carrier_accept_shipment(program_id, shipment_id, declared_weight_kg=None, *, agent_id="ca-1"):
    payload = {}
    if declared_weight_kg is not None:
        payload["declared_weight_kg"] = declared_weight_kg
    resp = api_client.carrier_accept_shipment(
        program_id, shipment_id, payload, make_carrier_agent_headers(agent_id)
    )
    return get_success_data(resp)


def mark_in_transit(program_id, shipment_id, *, agent_id="ca-1"):
    resp = api_client.mark_shipment_in_transit(
        program_id, shipment_id, make_carrier_agent_headers(agent_id)
    )
    return get_success_data(resp)


def mark_delivered(program_id, shipment_id, *, agent_id="ca-1"):
    resp = api_client.mark_shipment_delivered(
        program_id, shipment_id, make_carrier_agent_headers(agent_id)
    )
    return get_success_data(resp)


def setup_picked_pack(*, program_code=None, storage_capacity_wh=100000,
                      soc_percent=DEFAULT_RECEIVING_SOC, location_capacity_wh=5000,
                      accepts_soc_band=None):
    """Pack READY_TO_STORE, then STAGED -> STORED -> PICKED. Full bundle."""
    bundle = setup_ready_to_store_pack(
        program_code=program_code, storage_capacity_wh=storage_capacity_wh,
        soc_percent=soc_percent,
    )
    program_id = bundle["program"]["id"]
    location, placement = stage_store_pick_pack(
        program_id, bundle["pack"]["id"], capacity_wh=location_capacity_wh,
        accepts_soc_band=accepts_soc_band,
    )
    bundle["location"] = location
    bundle["placement"] = placement
    bundle["pack"] = get_battery_pack(program_id, bundle["pack"]["id"])
    return bundle


def setup_tendered_shipment(*, un_class_code="UN3480", declared_weight_kg=10.00, **kwargs):
    """Pack attached to a shipment that has been tendered. Full bundle."""
    bundle = setup_picked_pack(**kwargs)
    program_id = bundle["program"]["id"]
    shipment = create_shipment(
        program_id, un_class_code=un_class_code, declared_weight_kg=declared_weight_kg
    )
    attach_pack(program_id, shipment["id"], bundle["pack"]["id"])
    shipment = tender_shipment(program_id, shipment["id"])
    bundle["shipment"] = shipment
    bundle["pack"] = get_battery_pack(program_id, bundle["pack"]["id"])
    return bundle


def setup_delivered_pack(**kwargs):
    """Full outbound journey: pack DELIVERED with disposition IN_SERVICE."""
    bundle = setup_tendered_shipment(**kwargs)
    program_id = bundle["program"]["id"]
    shipment_id = bundle["shipment"]["id"]
    carrier_accept_shipment(program_id, shipment_id)
    mark_in_transit(program_id, shipment_id)
    bundle["shipment"] = mark_delivered(program_id, shipment_id)
    bundle["pack"] = get_battery_pack(program_id, bundle["pack"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Returns and recalls
# ---------------------------------------------------------------------------

def create_rma(program_id, pack_id, *, reason_code="DEFECT", target_soc_percent=25.0,
               requester_id="cs-rma-1"):
    resp = api_client.create_return_authorization(
        program_id,
        create_return_authorization_payload(pack_id, reason_code, target_soc_percent),
        make_customer_service_headers(requester_id),
    )
    return get_success_data(resp, 201)


def get_rma(program_id, rma_id):
    return get_success_data(api_client.get_return_authorization(program_id, rma_id, ANY))


def approve_rma(program_id, rma_id, *, approver_id="so-rma-1"):
    resp = api_client.approve_return_authorization(
        program_id, rma_id, make_safety_officer_headers(approver_id)
    )
    return get_success_data(resp)


def begin_discharge(program_id, rma_id, *, engineer_id="qe-disch-1"):
    resp = api_client.begin_discharge(
        program_id, rma_id, make_quality_engineer_headers(engineer_id)
    )
    return get_success_data(resp)


def complete_discharge(program_id, rma_id, final_soc_percent, *, engineer_id="qe-disch-1"):
    resp = api_client.complete_discharge(
        program_id,
        rma_id,
        {"final_soc_percent": final_soc_percent},
        make_quality_engineer_headers(engineer_id),
    )
    return get_success_data(resp)


def receive_rma(program_id, rma_id, *, service_id="cs-rma-1"):
    resp = api_client.receive_return_authorization(
        program_id, rma_id, make_customer_service_headers(service_id)
    )
    return get_success_data(resp)


def close_rma(program_id, rma_id, *, service_id="cs-rma-1"):
    resp = api_client.close_return_authorization(
        program_id, rma_id, make_customer_service_headers(service_id)
    )
    return get_success_data(resp)


def create_recall(program_id, *, recall_code=None, severity="CLASS_II", scope_lot_id=None,
                  scope_bom_id=None, scope_serial_prefix=None, officer_id="so-rec-1"):
    resp = api_client.create_recall_campaign(
        program_id,
        create_recall_campaign_payload(
            recall_code, severity, scope_lot_id, scope_bom_id, scope_serial_prefix
        ),
        make_safety_officer_headers(officer_id),
    )
    return get_success_data(resp, 201)


def get_recall(program_id, recall_id):
    return get_success_data(api_client.get_recall_campaign(program_id, recall_id, ANY))


def activate_recall(program_id, recall_id, *, officer_id="so-rec-1"):
    resp = api_client.activate_recall_campaign(
        program_id, recall_id, make_safety_officer_headers(officer_id)
    )
    return get_success_data(resp)
