"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the PRD-declared field surface of one
resource. Immutable event records (PRD section 2.4) must carry only ``id``
and ``created_at`` and must NOT carry ``updated_at`` or ``version``.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AssemblyStatus, CellLotStatus, DossierOutcome, DossierStatus, FireZone,
    InspectionOutcome, LogisticsStatus, PackDisposition, PlacementStatus,
    ProgramStatus, RecallSeverity, RecallStatus, RmaReasonCode, RmaStatus,
    ShipmentStatus, ShippingClassification, SocBand, UnClassCode, WeldingProfile,
    FirmwareStatus, ApprovalDecision,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_immutable_event_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable event records must not carry updated_at"
    assert "version" not in data, "immutable event records must not carry version"


def assert_integration_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["status"] in {s.value for s in ProgramStatus}
    assert isinstance(data["compliance_risk_index"], (int, float))
    assert isinstance(data["storage_capacity_wh"], int)
    assert isinstance(data["wh_committed"], (int, float))
    assert isinstance(data["wh_available"], (int, float))
    assert isinstance(data["recall_count"], int)


def assert_cell_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["cell_count"], int) and data["cell_count"] > 0
    assert isinstance(data["rated_capacity_mah"], int)
    assert isinstance(data["receiving_soc_percent"], (int, float))
    assert data["measured_soc_percent"] is None or isinstance(data["measured_soc_percent"], (int, float))
    assert isinstance(data["quarantine_cycle_count"], int)
    assert data["status"] in {s.value for s in CellLotStatus}


def assert_cell_inspection_record(data: dict):
    _assert_immutable_event_fields(data)
    assert is_valid_uuid(data["cell_lot_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    assert isinstance(data["measured_soc_percent"], (int, float))
    assert isinstance(data["measured_voltage_v"], (int, float))
    assert isinstance(data["visual_defect_count"], int) and data["visual_defect_count"] >= 0
    assert data["outcome"] in {o.value for o in InspectionOutcome}


def assert_pack_bom(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["bom_code"], str) and data["bom_code"]
    assert is_valid_uuid(data["cell_lot_id"])
    assert isinstance(data["cells_required"], int) and data["cells_required"] >= 1
    assert isinstance(data["series_count"], int) and data["series_count"] >= 1
    assert isinstance(data["parallel_count"], int) and data["parallel_count"] >= 1
    assert isinstance(data["nominal_energy_wh"], (int, float))
    assert data["welding_profile"] in {p.value for p in WeldingProfile}
    assert isinstance(data["is_locked"], bool)


def assert_battery_pack(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"].startswith("SN-")
    assert is_valid_uuid(data["bom_id"])
    assert is_valid_uuid(data["cell_lot_id"])
    assert isinstance(data["pack_energy_wh"], (int, float))
    assert data["assembly_status"] in {s.value for s in AssemblyStatus}
    assert data["logistics_status"] in {s.value for s in LogisticsStatus}
    assert isinstance(data["soc_percent"], (int, float))
    assert data["soc_band"] in {b.value for b in SocBand}
    assert data["shipping_classification"] in {c.value for c in ShippingClassification}
    for nullable in ("bms_firmware_id", "dossier_id", "storage_location_id", "active_recall_id"):
        assert data[nullable] is None or is_valid_uuid(data[nullable])
    assert isinstance(data["is_safe_discharged"], bool)
    assert data["disposition"] in {d.value for d in PackDisposition}


def assert_welding_record(data: dict):
    _assert_immutable_event_fields(data)
    assert is_valid_uuid(data["battery_pack_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["operator_id"], str) and data["operator_id"]
    assert data["certified_by_id"] is None or isinstance(data["certified_by_id"], str)
    assert isinstance(data["weld_count"], int) and data["weld_count"] >= 1
    assert isinstance(data["current_amps"], (int, float))
    assert isinstance(data["pulse_ms"], int) and data["pulse_ms"] >= 1
    assert isinstance(data["electrode_force_n"], (int, float))
    assert data["weld_profile_used"] in {p.value for p in WeldingProfile}
    assert isinstance(data["heat_dose_j"], (int, float))
    assert isinstance(data["is_certified"], bool)


def assert_bms_firmware(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["firmware_version"], str) and data["firmware_version"]
    sha = data["binary_sha256"]
    assert isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
    assert isinstance(data["supports_soc_hysteresis"], bool)
    assert data["approval_record_id"] is None or is_valid_uuid(data["approval_record_id"])
    assert data["status"] in {s.value for s in FirmwareStatus}


def assert_firmware_approval(data: dict):
    _assert_immutable_event_fields(data)
    assert is_valid_uuid(data["bms_firmware_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["approver_id"], str) and data["approver_id"]
    assert data["decision"] in {d.value for d in ApprovalDecision}
    assert isinstance(data["rationale"], str) and len(data["rationale"]) >= 20


def assert_bms_flash_record(data: dict):
    _assert_immutable_event_fields(data)
    assert is_valid_uuid(data["battery_pack_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["bms_firmware_id"])
    assert isinstance(data["flashed_by_id"], str) and data["flashed_by_id"]
    assert isinstance(data["flash_cycle_index"], int) and data["flash_cycle_index"] >= 1


def assert_safety_test_dossier(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["battery_pack_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["dossier_cycle_index"], int) and data["dossier_cycle_index"] >= 1
    for numeric in ("altitude_sim_kpa", "shock_g_peak"):
        assert data[numeric] is None or isinstance(data[numeric], (int, float))
    for integral in ("thermal_cycles", "vibration_minutes"):
        assert data[integral] is None or isinstance(data[integral], int)
    for boolean in ("external_short_circuit_ok", "impact_crush_ok", "overcharge_ok", "forced_discharge_ok"):
        assert data[boolean] is None or isinstance(data[boolean], bool)
    assert data["provisional_un_score"] is None or isinstance(data["provisional_un_score"], (int, float))
    assert data["final_un_score"] is None or isinstance(data["final_un_score"], (int, float))
    assert data["outcome"] in {o.value for o in DossierOutcome}
    assert data["status"] in {s.value for s in DossierStatus}


def assert_storage_location(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert data["fire_zone"] in {z.value for z in FireZone}
    assert isinstance(data["capacity_wh"], int) and data["capacity_wh"] > 0
    assert isinstance(data["wh_occupied"], (int, float))
    assert isinstance(data["wh_headroom"], (int, float))
    assert isinstance(data["accepts_soc_band"], list)
    assert set(data["accepts_soc_band"]) <= {b.value for b in SocBand}


def assert_storage_placement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["storage_location_id"])
    assert is_valid_uuid(data["battery_pack_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_iso8601_timestamp(data["staged_at_utc"])
    assert data["stored_at_utc"] is None or is_iso8601_timestamp(data["stored_at_utc"])
    assert data["released_at_utc"] is None or is_iso8601_timestamp(data["released_at_utc"])
    assert data["status"] in {s.value for s in PlacementStatus}


def assert_transport_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert data["un_class_code"] in {c.value for c in UnClassCode}
    assert isinstance(data["declared_weight_kg"], (int, float))
    assert isinstance(data["total_pack_count"], int) and data["total_pack_count"] >= 0
    assert isinstance(data["total_wh"], (int, float))
    assert data["carrier_charge_cents"] is None or isinstance(data["carrier_charge_cents"], int)
    assert data["status"] in {s.value for s in ShipmentStatus}


def assert_shipment_pack_link(data: dict):
    _assert_immutable_event_fields(data)
    assert is_valid_uuid(data["transport_shipment_id"])
    assert is_valid_uuid(data["battery_pack_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_iso8601_timestamp(data["attached_at_utc"])


def assert_return_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["battery_pack_id"])
    assert data["reason_code"] in {r.value for r in RmaReasonCode}
    assert isinstance(data["requested_by_id"], str) and data["requested_by_id"]
    assert data["approved_by_id"] is None or isinstance(data["approved_by_id"], str)
    assert isinstance(data["target_soc_percent"], (int, float))
    assert data["actual_soc_after_discharge"] is None or isinstance(data["actual_soc_after_discharge"], (int, float))
    assert data["status"] in {s.value for s in RmaStatus}


def assert_recall_campaign(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["recall_code"], str) and data["recall_code"]
    assert data["severity"] in {s.value for s in RecallSeverity}
    assert isinstance(data["packs_in_scope"], int) and data["packs_in_scope"] >= 0
    assert isinstance(data["packs_contained"], int) and data["packs_contained"] >= 0
    assert data["status"] in {s.value for s in RecallStatus}


def assert_wh_ledgers_consistent(program: dict, location: dict):
    """Watt-hour ledger invariants (PRD section 2.8): headroom/availability
    are pure differences of capacity minus committed/occupied."""
    assert program["wh_available"] == program["storage_capacity_wh"] - program["wh_committed"]
    assert location["wh_headroom"] == location["capacity_wh"] - location["wh_occupied"]
    assert program["wh_committed"] >= 0
    assert location["wh_occupied"] >= 0
