"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import FAR_FUTURE_EXPIRY


def create_room_payload(room_name="Lab 1", equipment_profile=None):
    """PRD §3.1: room_name required; equipment_profile optional (defaults empty)."""
    payload = {"room_name": room_name}
    if equipment_profile is not None:
        payload["equipment_profile"] = equipment_profile
    return payload


def create_staff_payload(full_name="Dr Perform", staff_role="INTERVENTIONAL_CARDIOLOGIST",
                         credentials=None):
    """PRD §3.1: full_name and staff_role required; credentials optional."""
    payload = {"full_name": full_name, "staff_role": staff_role}
    if credentials is not None:
        payload["credentials"] = credentials
    return payload


def create_case_payload(patient_mrn="MRN-1", procedure_type="PCI", priority="URGENT",
                        performing_physician_id=None, weight_kg=70,
                        serum_creatinine=1.0, equipment_needs=None,
                        scheduled_start=None):
    """PRD §3.2: equipment_needs optional; scheduled_start required iff STEMI."""
    payload = {
        "patient_mrn": patient_mrn,
        "procedure_type": procedure_type,
        "priority": priority,
        "performing_physician_id": performing_physician_id,
        "weight_kg": weight_kg,
        "serum_creatinine": serum_creatinine,
    }
    if equipment_needs is not None:
        payload["equipment_needs"] = equipment_needs
    if scheduled_start is not None:
        payload["scheduled_start"] = scheduled_start
    return payload


def schedule_case_payload(lab_id, scheduled_start, bed_id=None):
    """PRD §3.3: lab_id + scheduled_start required; bed_id optional pin."""
    payload = {"lab_id": lab_id, "scheduled_start": scheduled_start}
    if bed_id is not None:
        payload["bed_id"] = bed_id
    return payload


def auc_attestation_payload(ordering_physician_id, expected_case_version,
                            auc_score="APPROPRIATE", criterion_code="AUC-45.1"):
    """PRD §3.8 + §2.7: version-gated attestation payload."""
    return {
        "ordering_physician_id": ordering_physician_id,
        "auc_score": auc_score,
        "criterion_code": criterion_code,
        "expected_case_version": expected_case_version,
    }


def staff_assignment_payload(staff_id, role_in_case):
    """PRD §3.4: staff_id + role_in_case."""
    return {"staff_id": staff_id, "role_in_case": role_in_case}


def create_device_lot_payload(device_type="STENT_DES", manufacturer="Acme",
                              model_number="DS-100", lot_number="LOT-A",
                              ownership="OWNED", quantity_on_hand=5,
                              reorder_threshold=2, expiration_date=FAR_FUTURE_EXPIRY):
    """PRD §3.5: all eight fields are required inputs."""
    return {
        "device_type": device_type,
        "manufacturer": manufacturer,
        "model_number": model_number,
        "lot_number": lot_number,
        "ownership": ownership,
        "quantity_on_hand": quantity_on_hand,
        "reorder_threshold": reorder_threshold,
        "expiration_date": expiration_date,
    }


def restock_payload(quantity, expected_lot_version):
    """PRD §3.5 + §2.7: version-gated restock payload."""
    return {"quantity": quantity, "expected_lot_version": expected_lot_version}


def device_usage_payload(lot_id, quantity):
    """PRD §3.5: lot_id + quantity (>= 1)."""
    return {"lot_id": lot_id, "quantity": quantity}


def contrast_record_payload(contrast_ml):
    """PRD §3.6: a contrast entry requires contrast_ml."""
    return {"record_type": "CONTRAST", "contrast_ml": contrast_ml}


def radiation_record_payload(fluoroscopy_mgy, cine_mgy):
    """PRD §3.6: a radiation entry requires fluoroscopy_mgy and cine_mgy."""
    return {"record_type": "RADIATION",
            "fluoroscopy_mgy": fluoroscopy_mgy,
            "cine_mgy": cine_mgy}


def create_recovery_bed_payload(bed_label="Bed 1"):
    """PRD §3.1: bed_label required."""
    return {"bed_label": bed_label}


def record_decision_payload(outcome, rejection_reason=None):
    """PRD §3.9: REJECTED requires rejection_reason."""
    payload = {"outcome": outcome}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload


def revise_payload(correction_note="corrected data"):
    """PRD §3.9: revise carries a required correction_note."""
    return {"correction_note": correction_note}
