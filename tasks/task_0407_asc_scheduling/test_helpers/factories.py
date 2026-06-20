"""Payload factories — one per entity, request body (input) fields only.

Each factory provides PRD-faithful defaults and accepts **overrides so a test
can control exactly the values it cares about.
"""

DEFAULTS = {
    "FACILITY_NAME": "Test ASC",
    "ROOM_LABEL": "OR-1",
    "BAY_LABEL": "PACU-1",
    "ANESTH_NAME": "Dr Gas",
    "SURGEON_NAME": "Dr Cut",
    "NPI": "1234567890",
    "CPT": "29881",
    "PROC_DESC": "Knee scope",
    "SCHEDULED_MINUTES": 60,
    "BASE_RATE_CENTS": 150000,
    "SKU": "DEV1",
    "SUPPLY_DESC": "Implant",
    "UNIT_COST_CENTS": 5000,
    "MRN": "MRN1",
    "PATIENT_NAME": "Pat One",
    "DOB": "1980-01-01",
    "SERVICE_DATE": "2026-07-15",
}


# ---------------------------------------------------------------------------
# Facility
# ---------------------------------------------------------------------------
def create_facility_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["FACILITY_NAME"]}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Operating room
# ---------------------------------------------------------------------------
def create_operating_room_payload(facility_id: str, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "room_label": DEFAULTS["ROOM_LABEL"]}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Recovery bay
# ---------------------------------------------------------------------------
def create_recovery_bay_payload(facility_id: str, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "bay_label": DEFAULTS["BAY_LABEL"]}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Anesthesiologist
# ---------------------------------------------------------------------------
def create_anesthesiologist_payload(facility_id: str, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "full_name": DEFAULTS["ANESTH_NAME"]}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Surgeon
# ---------------------------------------------------------------------------
def create_surgeon_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "full_name": DEFAULTS["SURGEON_NAME"],
        "npi": DEFAULTS["NPI"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Procedure
# ---------------------------------------------------------------------------
def create_procedure_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "cpt_code": DEFAULTS["CPT"],
        "description": DEFAULTS["PROC_DESC"],
        "scheduled_minutes": DEFAULTS["SCHEDULED_MINUTES"],
        "cms_payment_indicator": "COVERED_ASC",
        "cms_base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
        "anesthesia_class": "MAC",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Supply item
# ---------------------------------------------------------------------------
def create_supply_item_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "sku": DEFAULTS["SKU"],
        "description": DEFAULTS["SUPPLY_DESC"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
def create_patient_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "mrn": DEFAULTS["MRN"],
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Surgical day
# ---------------------------------------------------------------------------
def create_surgical_day_payload(facility_id: str, **overrides) -> dict:
    defaults = {"facility_id": facility_id, "service_date": DEFAULTS["SERVICE_DATE"]}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Surgeon block
# ---------------------------------------------------------------------------
def create_surgeon_block_payload(surgical_day_id: str, surgeon_id: str,
                                 operating_room_id: str, start_min: int,
                                 end_min: int, **overrides) -> dict:
    defaults = {
        "surgical_day_id": surgical_day_id,
        "surgeon_id": surgeon_id,
        "operating_room_id": operating_room_id,
        "start_min": start_min,
        "end_min": end_min,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Surgical case (booking)
# ---------------------------------------------------------------------------
def book_case_payload(expected_block_version: int, patient_id: str,
                      procedure_id: str, start_min: int, **overrides) -> dict:
    defaults = {
        "expected_block_version": expected_block_version,
        "patient_id": patient_id,
        "procedure_id": procedure_id,
        "start_min": start_min,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Case implant
# ---------------------------------------------------------------------------
def attach_implant_payload(supply_item_id: str, planned_qty: int, **overrides) -> dict:
    defaults = {"supply_item_id": supply_item_id, "planned_qty": planned_qty}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clearance check
# ---------------------------------------------------------------------------
def clearance_check_payload(check_type: str, outcome: str, **overrides) -> dict:
    defaults = {"check_type": check_type, "outcome": outcome}
    defaults.update(overrides)
    return defaults
