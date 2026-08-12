"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "TEMPLATE_CODE": "GEN-01",
    "TEMPLATE_NAME": "General",
    "SPECIALTY": "GEN",
    "PACKAGING_TYPE": "WRAPPED",
    "ASSEMBLY_MINUTES": 10,
    "REQUIREMENT_TYPE": "SCALPEL",
    "REQUIREMENT_QTY": 2,
    "TECH_CERT_LEVEL": 2,
    "TECH_METHODS": ["STEAM_GRAVITY"],
    "TECH_CERT_EXPIRY": "2027-01-01T00:00:00Z",
    "STERILIZER_METHOD": "STEAM_GRAVITY",
    "CHAMBER_CAPACITY": 4,
    "CYCLE_MINUTES": 60,
    "REQUIRED_CERT_LEVEL": 1,
    "INSTRUMENT_TYPE": "SCALPEL",
    "MAX_CYCLES": 50,
    "REPLACEMENT_COST_CENTS": 100000,
    "CRITICALITY": "ROUTINE",
    "PLANNED_START": "2026-05-01T00:00:00Z",
    "CASE_SURGEON": "Dr A",
    "CASE_START": "2026-05-10T09:00:00Z",
    "CASE_END": "2026-05-10T11:00:00Z",
    "CASE_PRIORITY": "ELECTIVE",
    "JUSTIFICATION": "Emergency turnover; no sterile tray available",
    "VENDOR": "VendorMed",
    "LOANER_TRAY_COUNT": 2,
}


def create_tray_template_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["TEMPLATE_CODE"],
        "name": DEFAULTS["TEMPLATE_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
        "packaging_type": DEFAULTS["PACKAGING_TYPE"],
        "instrument_requirements": [
            {
                "instrument_type": DEFAULTS["REQUIREMENT_TYPE"],
                "quantity": DEFAULTS["REQUIREMENT_QTY"],
            }
        ],
        "assembly_minutes": DEFAULTS["ASSEMBLY_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_tray_payload(template_id, **overrides) -> dict:
    defaults = {"template_id": template_id, "label": "T1"}
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Tech A",
        "certification_level": DEFAULTS["TECH_CERT_LEVEL"],
        "certified_methods": list(DEFAULTS["TECH_METHODS"]),
        "certification_expires_at": DEFAULTS["TECH_CERT_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_sterilizer_payload(**overrides) -> dict:
    defaults = {
        "name": "SG",
        "method": DEFAULTS["STERILIZER_METHOD"],
        "chamber_capacity": DEFAULTS["CHAMBER_CAPACITY"],
        "cycle_minutes": DEFAULTS["CYCLE_MINUTES"],
        "required_certification_level": DEFAULTS["REQUIRED_CERT_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "instrument_type": DEFAULTS["INSTRUMENT_TYPE"],
        "serial_number": "SN-1",
        "max_cycles": DEFAULTS["MAX_CYCLES"],
        "replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
        "criticality": DEFAULTS["CRITICALITY"],
    }
    defaults.update(overrides)
    return defaults


def create_sterilization_load_payload(sterilizer_id, **overrides) -> dict:
    defaults = {
        "sterilizer_id": sterilizer_id,
        "planned_start_at": DEFAULTS["PLANNED_START"],
    }
    defaults.update(overrides)
    return defaults


def assembly_verification_payload(lines=None, **overrides) -> dict:
    """Default count sheet matches the default template (SCALPEL x2)."""
    defaults = {
        "lines": lines
        if lines is not None
        else [{"instrument_type": DEFAULTS["REQUIREMENT_TYPE"], "counted_qty": 2}]
    }
    defaults.update(overrides)
    return defaults


def create_or_case_payload(**overrides) -> dict:
    defaults = {
        "case_number": "C-1",
        "surgeon": DEFAULTS["CASE_SURGEON"],
        "scheduled_start_at": DEFAULTS["CASE_START"],
        "scheduled_end_at": DEFAULTS["CASE_END"],
        "priority": DEFAULTS["CASE_PRIORITY"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(tray_id, expected_or_case_version, **overrides) -> dict:
    defaults = {
        "tray_id": tray_id,
        "expected_or_case_version": expected_or_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_iuss_payload(tray_id, case_id, **overrides) -> dict:
    defaults = {
        "tray_id": tray_id,
        "case_id": case_id,
        "justification": DEFAULTS["JUSTIFICATION"],
    }
    defaults.update(overrides)
    return defaults


def create_loaner_set_payload(case_id, **overrides) -> dict:
    defaults = {
        "vendor": DEFAULTS["VENDOR"],
        "case_id": case_id,
        "tray_count": DEFAULTS["LOANER_TRAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def send_repair_order_payload(**overrides) -> dict:
    defaults = {"vendor": "VendorCo", "quoted_cost_cents": 1000}
    defaults.update(overrides)
    return defaults


def receive_repair_order_payload(**overrides) -> dict:
    defaults = {"actual_cost_cents": 1000, "outcome": "FIXED"}
    defaults.update(overrides)
    return defaults
