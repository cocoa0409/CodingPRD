"""Payload factories — one per creatable resource, input fields only.

Fields that the server assigns (status, computed counters, timestamps, version,
issuing_officer_id, fee_charged_cents, etc.) are never included. Defaults for
unique fields (zone_code, license_plate) carry a random suffix so a single test
can create several resources without colliding.
"""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---- clock ----
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ---- Zone ----
def create_zone_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Residential Zone",
        "zone_code": _uniq("RPZ"),
        "permit_capacity": 2,
        "max_permits_per_household": 2,
        "guest_pass_daily_limit": 2,
        "permit_annual_fee_cents": 12000,
        "visitor_pass_fee_cents": 500,
    }
    defaults.update(overrides)
    return defaults


# ---- Household ----
def create_household_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "unit_address": "1 Test Street",
        "resident_name": "Test Resident",
        "contact_email": "resident@example.com",
    }
    defaults.update(overrides)
    return defaults


# ---- Vehicle ----
def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "license_plate": _uniq("PLT"),
        "make": "Honda",
        "model": "Civic",
    }
    defaults.update(overrides)
    return defaults


# ---- ProofSubmission ----
def create_proof_submission_payload(**overrides) -> dict:
    defaults = {"document_type": "LEASE"}
    defaults.update(overrides)
    return defaults


def review_proof_payload(outcome: str) -> dict:
    return {"outcome": outcome}


# ---- PermitApplication ----
def create_permit_application_payload(zone_id: str, household_id: str, vehicle_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "household_id": household_id,
        "vehicle_id": vehicle_id,
    }
    defaults.update(overrides)
    return defaults


def approve_payload(expected_zone_version: int) -> dict:
    return {"expected_zone_version": expected_zone_version}


def deny_payload(denial_reason: str = "ineligible") -> dict:
    return {"denial_reason": denial_reason}


# ---- Permit lifecycle ----
def renew_approve_payload(expected_permit_version: int) -> dict:
    return {"expected_permit_version": expected_permit_version}


def transfer_payload(vehicle_id: str) -> dict:
    return {"vehicle_id": vehicle_id}


def refund_payload(refund_type: str) -> dict:
    return {"refund_type": refund_type}


def revoke_payload(reason: str = "for cause") -> dict:
    return {"reason": reason}


# ---- VisitorPass ----
def create_visitor_pass_payload(household_id: str, permit_id: str, valid_from: str,
                                valid_until: str, pass_type: str = "TEMPORARY",
                                guest_plate: str = None, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "permit_id": permit_id,
        "pass_type": pass_type,
        "guest_plate": guest_plate or _uniq("GST"),
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    defaults.update(overrides)
    return defaults


# ---- Citation ----
def create_citation_payload(zone_id: str, license_plate: str, violation_type: str,
                            permit_id: str = None, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "license_plate": license_plate,
        "violation_type": violation_type,
    }
    if permit_id is not None:
        defaults["permit_id"] = permit_id
    defaults.update(overrides)
    return defaults


def adjudicate_payload(outcome: str) -> dict:
    return {"outcome": outcome}


# ---- Complaint ----
def create_complaint_payload(zone_id: str, complaint_type: str = "ILLEGAL_PARKING",
                             description: str = "test complaint",
                             target_plate: str = None, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "complaint_type": complaint_type,
        "description": description,
    }
    if target_plate is not None:
        defaults["target_plate"] = target_plate
    defaults.update(overrides)
    return defaults


def resolve_complaint_payload(outcome: str, resolution_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload
