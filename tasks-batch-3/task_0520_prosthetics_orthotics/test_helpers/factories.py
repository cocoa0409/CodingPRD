"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PATIENT_NAME": "Test Patient",
    "DOB": "1960-01-01",
    "PHYSICIAN_NAME": "Dr Test",
    "FIT_NAME": "Tech Fit",
    "NPI_RX": "1111111111",
    "NPI_FIT": "2222222222",
    "SUPPLIER_NAME": "Acme O&P",
    "DIAGNOSIS_ORTHOSIS": "M21.6X1",
    "DIAGNOSIS_PROSTHETIC": "Z89.511",
    "FACE_TO_FACE": "2026-05-20",
    "MBI": "1EG4TE5MK72",
    "L_CODE_ORTHOSIS": "L1960",
    "L_CODE_PROSTHETIC": "L5301",
}


def create_patient_payload(**overrides) -> dict:
    """Patient: full_name, date_of_birth, payer_type required; MBI & K-level optional."""
    defaults = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "payer_type": "COMMERCIAL",
    }
    defaults.update(overrides)
    return defaults


def create_medicare_patient_payload(**overrides) -> dict:
    """A Medicare patient with the MBI and a functional K-level."""
    defaults = {
        "full_name": "Med Patient",
        "date_of_birth": "1955-01-01",
        "payer_type": "MEDICARE",
        "medicare_beneficiary_id": DEFAULTS["MBI"],
        "functional_k_level": 3,
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    """Physician: full_name, npi required; pecos_enrolled optional (default false)."""
    defaults = {
        "full_name": DEFAULTS["PHYSICIAN_NAME"],
        "npi": DEFAULTS["NPI_RX"],
        "pecos_enrolled": True,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    """Supplier: legal_name required; accreditation_expiry & surety_bond_active optional."""
    defaults = {
        "legal_name": DEFAULTS["SUPPLIER_NAME"],
        "accreditation_expiry": "2028-01-01T00:00:00Z",
        "surety_bond_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(patient_id: str, physician_id: str, **overrides) -> dict:
    """Prescription: patient_id, physician_id, device_category, primary_diagnosis_code,
    face_to_face_date all required."""
    defaults = {
        "patient_id": patient_id,
        "physician_id": physician_id,
        "device_category": "LOWER_EXTREMITY_ORTHOSIS",
        "primary_diagnosis_code": DEFAULTS["DIAGNOSIS_ORTHOSIS"],
        "face_to_face_date": DEFAULTS["FACE_TO_FACE"],
    }
    defaults.update(overrides)
    return defaults


def create_device_order_payload(prescription_id: str, supplier_id: str,
                                fitting_practitioner_id: str, **overrides) -> dict:
    """DeviceOrder: prescription_id, supplier_id, fitting_practitioner_id required."""
    defaults = {
        "prescription_id": prescription_id,
        "supplier_id": supplier_id,
        "fitting_practitioner_id": fitting_practitioner_id,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(device_order_id: str, **overrides) -> dict:
    """ClaimLine: device_order_id, l_code, billed_units, fee_schedule_cents required;
    modifier optional (default NONE)."""
    defaults = {
        "device_order_id": device_order_id,
        "l_code": DEFAULTS["L_CODE_ORTHOSIS"],
        "modifier": "NONE",
        "billed_units": 1,
        "fee_schedule_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(step: str = "ASSEMBLY", weight: int = 1, **overrides) -> dict:
    """FabricationMilestone: step, weight required."""
    defaults = {"step": step, "weight": weight}
    defaults.update(overrides)
    return defaults


def create_assess_payload(parts_cents: int = 0, **overrides) -> dict:
    """Assess: parts_cents supplied at assessment."""
    defaults = {"parts_cents": parts_cents}
    defaults.update(overrides)
    return defaults


def create_repair_request_payload(device_order_id: str, **overrides) -> dict:
    """RepairRequest: device_order_id required."""
    defaults = {"device_order_id": device_order_id}
    defaults.update(overrides)
    return defaults


def deliver_payload(expected_version: int, **overrides) -> dict:
    """Deliver: expected_device_order_version required (OCC)."""
    defaults = {"expected_device_order_version": expected_version}
    defaults.update(overrides)
    return defaults


def resubmit_payload(expected_version: int, **overrides) -> dict:
    """Resubmit: expected_prior_auth_version required (OCC)."""
    defaults = {"expected_prior_auth_version": expected_version}
    defaults.update(overrides)
    return defaults


def appeal_decision_payload(outcome: str, **overrides) -> dict:
    """Appeal-decision: outcome required (UPHELD or OVERTURNED)."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    """Logical clock set."""
    return {"to_iso8601": to_iso8601}
