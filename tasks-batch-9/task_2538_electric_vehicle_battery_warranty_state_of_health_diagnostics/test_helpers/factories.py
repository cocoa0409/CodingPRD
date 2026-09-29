"""Payload factories: one per write operation named by the PRD.

Each factory returns the minimal valid body for its operation and merges
`**overrides` last, so a test that wants one field different says so and nothing
else. Optional fields are deliberately left out unless a caller supplies them —
that is how the reference-default assertions stay honest.
"""

from typing import List, Optional


def _merge(base: dict, overrides: dict) -> dict:
    """Overrides win; an override of None is kept so a test can send an explicit null."""
    out = dict(base)
    out.update(overrides)
    return out


# ═════════════════════════ WarrantyProgram ═════════════════════════


def warranty_program_payload(name: str = "MX Capacity Retention 2020", **overrides) -> dict:
    """Only the program name is required; every constant carries a reference default."""
    return _merge({"name": name}, overrides)


# ═════════════════════════════ Vehicle ═════════════════════════════


def vehicle_payload(
    warranty_program_id: str,
    vin: str = "5YJ3E1EA7KF000001",
    in_service_date: str = "2020-03-10",
    **overrides,
) -> dict:
    return _merge(
        {
            "vin": vin,
            "warranty_program_id": warranty_program_id,
            "in_service_date": in_service_date,
        },
        overrides,
    )


# ═══════════════════════════ ServiceCenter ═══════════════════════════


def service_center_payload(name: str = "West HV Center", **overrides) -> dict:
    return _merge({"name": name}, overrides)


# ════════════════════════════ Technician ════════════════════════════


def technician_payload(full_name: str = "Tech A", **overrides) -> dict:
    return _merge({"full_name": full_name}, overrides)


# ═══════════════════════════ BatteryPack ═══════════════════════════


def battery_pack_payload(
    serial_number: str = "PK-C001",
    installed_vehicle_id: Optional[str] = None,
    **overrides,
) -> dict:
    base = {"serial_number": serial_number}
    if installed_vehicle_id is not None:
        base["installed_vehicle_id"] = installed_vehicle_id
    return _merge(base, overrides)


# ══════════════════════════ TelematicsSnapshot ══════════════════════════


def snapshot_payload(
    captured_at: str,
    odometer_miles: int,
    reported_capacity_kwh: float,
    **overrides,
) -> dict:
    """The three required screening inputs; `vehicle_id` comes from the path."""
    return _merge(
        {
            "captured_at": captured_at,
            "odometer_miles": odometer_miles,
            "reported_capacity_kwh": reported_capacity_kwh,
        },
        overrides,
    )


# ═══════════════════════════ SoHAssessment ═══════════════════════════


def telematics_assessment_payload(
    vehicle_id: str,
    pack_id: str,
    technician_id: str,
    expected_vehicle_version: int,
    **overrides,
) -> dict:
    """A `TELEMATICS_FLEET` diagnostic: the window supplies the capacity estimate."""
    return _merge(
        {
            "vehicle_id": vehicle_id,
            "pack_id": pack_id,
            "technician_id": technician_id,
            "variant": "TELEMATICS_FLEET",
            "expected_vehicle_version": expected_vehicle_version,
        },
        overrides,
    )


def bench_assessment_payload(
    vehicle_id: str,
    pack_id: str,
    technician_id: str,
    expected_vehicle_version: int,
    bench_measured_capacity_kwh: float,
    **overrides,
) -> dict:
    """A `BENCH_CAPACITY_TEST` diagnostic: the bench figure is the capacity estimate."""
    return _merge(
        {
            "vehicle_id": vehicle_id,
            "pack_id": pack_id,
            "technician_id": technician_id,
            "variant": "BENCH_CAPACITY_TEST",
            "expected_vehicle_version": expected_vehicle_version,
            "bench_measured_capacity_kwh": bench_measured_capacity_kwh,
        },
        overrides,
    )


# ═══════════════════════════ WarrantyClaim ═══════════════════════════


def claim_payload(
    vehicle_id: str,
    service_center_id: str,
    assessment_id: str,
    diagnosing_technician_id: str,
    **overrides,
) -> dict:
    return _merge(
        {
            "vehicle_id": vehicle_id,
            "service_center_id": service_center_id,
            "assessment_id": assessment_id,
            "diagnosing_technician_id": diagnosing_technician_id,
        },
        overrides,
    )


def request_info_payload(reason_note: str = "more evidence please", **overrides) -> dict:
    return _merge({"reason_note": reason_note}, overrides)


def resubmit_payload(assessment_id: str, note: str = "resubmitted", **overrides) -> dict:
    return _merge({"assessment_id": assessment_id, "note": note}, overrides)


def adjudicate_payload(approved_remedy: str, **overrides) -> dict:
    return _merge({"approved_remedy": approved_remedy}, overrides)


def fulfil_payload(
    fulfilment_technician_id: str,
    hv_bay_window_start: str = "2026-08-01T10:00:00Z",
    hv_bay_window_end: str = "2026-08-01T14:00:00Z",
    **overrides,
) -> dict:
    return _merge(
        {
            "fulfilment_technician_id": fulfilment_technician_id,
            "hv_bay_window_start": hv_bay_window_start,
            "hv_bay_window_end": hv_bay_window_end,
        },
        overrides,
    )


def close_payload(closure_note: str = "closed", **overrides) -> dict:
    return _merge({"closure_note": closure_note}, overrides)


# ═══════════════════════════ ThermalEvent ═══════════════════════════


def thermal_event_payload(
    vehicle_id: str,
    pack_id: str,
    severity: str,
    detected_at: str,
    source: str = "TELEMATICS",
    affected_module_positions: Optional[List[int]] = None,
    **overrides,
) -> dict:
    base = {
        "vehicle_id": vehicle_id,
        "pack_id": pack_id,
        "severity": severity,
        "detected_at": detected_at,
        "source": source,
    }
    if affected_module_positions is not None:
        base["affected_module_positions"] = affected_module_positions
    return _merge(base, overrides)


def containment_step_payload(step_index: int, step_note: str = "step recorded", **overrides) -> dict:
    return _merge({"step_index": step_index, "step_note": step_note}, overrides)


def regulatory_notification_payload(
    reporting_service_center_id: str,
    regulator_reference: str = "REG-2026-0001",
    **overrides,
) -> dict:
    return _merge(
        {
            "reporting_service_center_id": reporting_service_center_id,
            "regulator_reference": regulator_reference,
        },
        overrides,
    )


# ═════════════════════════ RemediationCampaign ═════════════════════════


def campaign_payload(
    campaign_code: str = "CMP-CHG-01",
    target_defect: str = "CHARGING",
    software_version: str = "bms-4.2.1",
    applies_to_pack_type: str = "ANY",
    **overrides,
) -> dict:
    return _merge(
        {
            "campaign_code": campaign_code,
            "target_defect": target_defect,
            "software_version": software_version,
            "applies_to_pack_type": applies_to_pack_type,
        },
        overrides,
    )


def release_payload(release_scope: str, **overrides) -> dict:
    return _merge({"release_scope": release_scope}, overrides)


# ═════════════════════════ RemediationConsent ═════════════════════════


def consent_payload(
    campaign_id: str,
    vehicle_id: str,
    expected_campaign_version: int,
    **overrides,
) -> dict:
    return _merge(
        {
            "campaign_id": campaign_id,
            "vehicle_id": vehicle_id,
            "expected_campaign_version": expected_campaign_version,
        },
        overrides,
    )


def consent_decision_payload(decision: str, **overrides) -> dict:
    """`decision` is GRANT or DECLINE."""
    return _merge({"decision": decision}, overrides)


def apply_update_payload(installer_note: str = "flash applied", **overrides) -> dict:
    return _merge({"installer_note": installer_note}, overrides)


# ══════════════════════════ CapacityDispute ══════════════════════════


def dispute_payload(
    claim_id: str,
    expected_claim_version: int,
    lab_name: str = "Statewide Cell Lab",
    owner_statement: str = "capacity is worse than measured",
    **overrides,
) -> dict:
    return _merge(
        {
            "claim_id": claim_id,
            "lab_name": lab_name,
            "owner_statement": owner_statement,
            "expected_claim_version": expected_claim_version,
        },
        overrides,
    )


def lab_result_payload(
    lab_measured_capacity_kwh: float,
    lab_report_reference: str = "LAB-0001",
    **overrides,
) -> dict:
    return _merge(
        {
            "lab_measured_capacity_kwh": lab_measured_capacity_kwh,
            "lab_report_reference": lab_report_reference,
        },
        overrides,
    )


def resolve_payload(resolution_note: str = "OEM measurement stands", **overrides) -> dict:
    return _merge({"resolution_note": resolution_note}, overrides)


# ═══════════════════════════ PackShipment ═══════════════════════════


def shipment_payload(
    pack_id: str,
    origin_service_center_id: str,
    certifying_technician_id: str,
    shipment_contents: str = "FULL_PACK",
    packaging_spec: str = "SP376_STRONG_OUTER",
    state_of_charge_pct: float = 30.00,
    **overrides,
) -> dict:
    return _merge(
        {
            "pack_id": pack_id,
            "origin_service_center_id": origin_service_center_id,
            "certifying_technician_id": certifying_technician_id,
            "shipment_contents": shipment_contents,
            "packaging_spec": packaging_spec,
            "state_of_charge_pct": state_of_charge_pct,
        },
        overrides,
    )


def tender_payload(carrier_reference: str = "CAR-0001", **overrides) -> dict:
    return _merge({"carrier_reference": carrier_reference}, overrides)


def receive_accepted_payload(disposition: str, **overrides) -> dict:
    """An acceptance carries `disposition`; REMANUFACTURE also needs `refurb_soh_pct`."""
    return _merge({"outcome": "ACCEPTED", "disposition": disposition}, overrides)


def receive_rejected_payload(rejection_reason: str, **overrides) -> dict:
    """A rejection carries `rejection_reason` and nothing else."""
    return _merge({"outcome": "REJECTED", "rejection_reason": rejection_reason}, overrides)
