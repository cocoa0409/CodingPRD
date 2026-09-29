"""Payload factories — one per write endpoint, client-supplied fields only."""

import itertools

from .constants import CLOCK_EPOCH, TEST_DEFAULTS

# --- unique natural keys ---------------------------------------------------
# The database is empty at the start of every test, but a single test may need
# several vehicles / rebuilders / inspectors, so natural keys are sequenced.
_vin_counter = itertools.count(1)
_license_counter = itertools.count(1)
_badge_counter = itertools.count(1)
_station_counter = itertools.count(1)
_claim_counter = itertools.count(1)
_serial_counter = itertools.count(1)

# A valid identification number is exactly 17 characters, uppercase, and never
# contains the letters I, O or Q.
_VIN_PREFIX = "1HGCM82633A0"


def next_vin() -> str:
    """A fresh 17-character vehicle identification number."""
    return f"{_VIN_PREFIX}{next(_vin_counter):05d}"


def next_license_number() -> str:
    return f"RB-{1000 + next(_license_counter):04d}"


def next_badge_number() -> str:
    return f"INS-{3000 + next(_badge_counter):04d}"


def next_station_code() -> str:
    return f"NV-{next(_station_counter):02d}"


def next_claim_number() -> str:
    return f"CM-{70000 + next(_claim_counter):05d}"


def next_part_serial_number() -> str:
    return f"PS-{8800 + next(_serial_counter):05d}"


# --- registry -------------------------------------------------------------
def create_vehicle_payload(**overrides) -> dict:
    payload = {
        "vin": next_vin(),
        "model_year": 2019,
        "make": "Honda",
        "model": "Accord",
        "body_class": "SEDAN",
        "registered_state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_rebuilder_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Sierra Rebuilders LLC",
        "license_number": next_license_number(),
        "license_expires_at": "2027-06-30T00:00:00Z",
        "bond_amount_cents": TEST_DEFAULTS["BOND_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(**overrides) -> dict:
    payload = {"amount_cents": TEST_DEFAULTS["DEPOSIT_CENTS"]}
    payload.update(overrides)
    return payload


def create_license_action_payload(action: str = "SUSPEND", **overrides) -> dict:
    payload = {"action": action, "note": "administrative review"}
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Ruiz",
        "badge_number": next_badge_number(),
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "certifications": ["STRUCTURAL", "THEFT_RECOVERY"],
        "home_state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_inspection_station_payload(**overrides) -> dict:
    payload = {
        "station_code": next_station_code(),
        "bay_count": 2,
        "address_state_code": TEST_DEFAULTS["STATE_CODE"],
        "supports_flood": True,
    }
    payload.update(overrides)
    return payload


# --- damage evaluation and titling ----------------------------------------
def create_damage_report_payload(vehicle_id: str, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "insurer_name": TEST_DEFAULTS["INSURER_NAME"],
        "claim_number": next_claim_number(),
        "basis_code": "GROSS_ESTIMATE",
        "acv_cents": TEST_DEFAULTS["ACV_CENTS"],
        "repair_estimate_cents": TEST_DEFAULTS["REPAIR_ESTIMATE_CENTS"],
        "damage_type": "COLLISION",
        "odometer_reading_miles": 64000,
        "report_effective_at": "2026-07-20T00:00:00Z",
        "total_loss_declared": True,
    }
    payload.update(overrides)
    return payload


def create_title_record_payload(vehicle_id: str, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "issuing_state_code": TEST_DEFAULTS["STATE_CODE"],
        "owner_name": TEST_DEFAULTS["OWNER_NAME"],
    }
    payload.update(overrides)
    return payload


def surrender_title_payload(**overrides) -> dict:
    payload = {"surrender_note": "owner relinquished the certificate"}
    payload.update(overrides)
    return payload


# --- applications and documentation ---------------------------------------
def create_application_payload(
    vehicle_id: str, rebuilder_id: str, salvage_title_id: str, **overrides
) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "rebuilder_id": rebuilder_id,
        "salvage_title_id": salvage_title_id,
        "declared_repair_cost_cents": TEST_DEFAULTS["REPAIR_ESTIMATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_parts_document_payload(**overrides) -> dict:
    payload = {
        "doc_type": "RECEIPT",
        "part_class": "STRUCTURAL",
        "source_type": "NEW",
        "amount_cents": TEST_DEFAULTS["STRUCTURAL_AMOUNT_CENTS"],
        "vendor_name": "OEM Frame Supply",
        "part_serial_number": next_part_serial_number(),
    }
    payload.update(overrides)
    return payload


def create_photograph_payload(photo_view_code: str = "FRONT", **overrides) -> dict:
    payload = {
        "doc_type": "PHOTOGRAPH",
        "part_class": "PHOTO_SET",
        "source_type": "OWNER_SUPPLIED",
        "photo_view_code": photo_view_code,
    }
    payload.update(overrides)
    return payload


def verify_parts_document_payload(**overrides) -> dict:
    payload = {"verification_note": "invoice matches the serial plate"}
    payload.update(overrides)
    return payload


def reject_parts_document_payload(rejection_reason: str = "ILLEGIBLE", **overrides) -> dict:
    payload = {
        "rejection_reason": rejection_reason,
        "rejection_note": "vendor invoice image unreadable on second look",
    }
    payload.update(overrides)
    return payload


def submit_application_payload(**overrides) -> dict:
    payload = {"attestation_signed": True}
    payload.update(overrides)
    return payload


def docs_review_payload(decision: str = "OPEN", **overrides) -> dict:
    notes = {
        "OPEN": "package opened",
        "ACCEPT": "documentation complete",
        "RETURN": "structural invoice illegible",
    }
    payload = {"decision": decision, "review_note": notes.get(decision, "reviewed")}
    payload.update(overrides)
    return payload


def withdraw_application_payload(**overrides) -> dict:
    payload = {"withdrawn_reason": "rebuilder is re-sourcing the structural component"}
    payload.update(overrides)
    return payload


def issue_rebuilt_title_payload(**overrides) -> dict:
    payload = {
        "issuing_state_code": TEST_DEFAULTS["STATE_CODE"],
        "owner_name": TEST_DEFAULTS["OWNER_NAME"],
    }
    payload.update(overrides)
    return payload


# --- inspections ----------------------------------------------------------
def schedule_inspection_payload(
    inspector_id: str,
    station_id: str,
    expected_application_version: int,
    scheduled_start_at: str = None,
    scheduled_end_at: str = None,
    **overrides,
) -> dict:
    payload = {
        "inspector_id": inspector_id,
        "station_id": station_id,
        "scheduled_start_at": scheduled_start_at or TEST_DEFAULTS["SLOT_START"],
        "scheduled_end_at": scheduled_end_at or TEST_DEFAULTS["SLOT_END"],
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def start_inspection_payload(**overrides) -> dict:
    payload = {"start_note": "bay 1 lift"}
    payload.update(overrides)
    return payload


def checkpoint_results(
    structural_frame: str = "PASS",
    restraint_system: str = "PASS",
    vin_integrity: str = "PASS",
    suspension_steering: str = "PASS",
    lamps_glazing: str = "PASS",
) -> list:
    """One entry per checkpoint code, in the order the score weights them."""
    return [
        {"code": "STRUCTURAL_FRAME", "outcome": structural_frame},
        {"code": "RESTRAINT_SYSTEM", "outcome": restraint_system},
        {"code": "VIN_INTEGRITY", "outcome": vin_integrity},
        {"code": "SUSPENSION_STEERING", "outcome": suspension_steering},
        {"code": "LAMPS_GLAZING", "outcome": lamps_glazing},
    ]


def complete_inspection_payload(vin_plate_reading: str, results: list = None, **overrides) -> dict:
    payload = {
        "checkpoint_results": results if results is not None else checkpoint_results(),
        "vin_plate_reading": vin_plate_reading,
    }
    payload.update(overrides)
    return payload


def cancel_inspection_payload(**overrides) -> dict:
    payload = {"cancellation_note": "slot released at the owner's request"}
    payload.update(overrides)
    return payload


def create_finding_payload(
    category: str = "STRUCTURAL_INADEQUACY", severity: str = "MAJOR", **overrides
) -> dict:
    payload = {
        "category": category,
        "severity": severity,
        "description": "frame rail weld does not meet the published repair standard",
    }
    payload.update(overrides)
    return payload


# --- appeals, referrals, recognition, transfers ---------------------------
def create_appeal_payload(inspection_id: str, **overrides) -> dict:
    payload = {
        "inspection_id": inspection_id,
        "grounds": "SCORING_ERROR",
        "narrative": "the restraint checkpoint was scored against the wrong bulletin",
    }
    payload.update(overrides)
    return payload


def review_appeal_payload(**overrides) -> dict:
    payload = {"review_note": "hearing opened on the written record"}
    payload.update(overrides)
    return payload


def decide_appeal_payload(decision: str = "DENY", **overrides) -> dict:
    payload = {
        "decision": decision,
        "decision_note": "the scoring record is consistent with the bulletin",
    }
    payload.update(overrides)
    return payload


def create_fraud_referral_payload(vehicle_id: str, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "referral_type": "ODOMETER",
        "evidence_summary": "prior title shows a higher reading than the current declaration",
    }
    payload.update(overrides)
    return payload


def investigate_referral_payload(**overrides) -> dict:
    payload = {"investigation_note": "pulling the service records"}
    payload.update(overrides)
    return payload


def resolve_referral_payload(outcome: str = "SUBSTANTIATED", **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "resolution_note": "odometer tampering confirmed by the service history",
    }
    payload.update(overrides)
    return payload


def create_recognition_request_payload(
    title_record_id: str, expected_title_version: int, **overrides
) -> dict:
    payload = {
        "title_record_id": title_record_id,
        "requesting_state_code": "AZ",
        "expected_title_version": expected_title_version,
    }
    payload.update(overrides)
    return payload


def decide_recognition_request_payload(mapped_brand_code: str = "REBUILT", **overrides) -> dict:
    payload = {
        "mapped_brand_code": mapped_brand_code,
        "decision_note": "the requesting state maps the brand onto its own ladder",
    }
    payload.update(overrides)
    return payload


def create_title_transfer_payload(from_title_id: str, **overrides) -> dict:
    payload = {
        "from_title_id": from_title_id,
        "buyer_name": TEST_DEFAULTS["BUYER_NAME"],
        "transfer_effective_at": "2026-09-01T00:00:00Z",
        "odometer_reading_miles": 70000,
        "sale_price_cents": 450_000,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str = CLOCK_EPOCH, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
