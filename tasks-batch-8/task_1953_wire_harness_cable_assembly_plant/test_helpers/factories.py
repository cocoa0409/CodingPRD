"""Payload factories — one per entity, input fields only.

Defaults are sane, PRD-legal values; tests override what they control.
Unique-looking codes are namespaced by the caller via overrides when a test
creates more than one of a resource.
"""

DEFAULTS = {
    "DRAWING_NUMBER": "DWG-1000",
    "CUSTOMER_CODE": "ACME",
    "REVISION": "A",
    "WORKMANSHIP_CLASS": "IPC_CLASS_2",
    "FIND_NUMBER": "T1",
    "COMPONENT_TYPE": "TERMINAL",
    "MPN": "TERM-20",
    "QTY_PER_HARNESS": 1,
    "SUPPLY_TYPE": "FACTORY_STOCK",
    "UNIT_COST_CENTS": 100,
    "LOT_CODE": "LOT-1000",
    "UNIT_LIABILITY_CENTS": 500,
    "REPLACEMENT_COST_CENTS": 640,
    "QTY_RECEIVED": 10,
    "OPERATOR_NAME": "Test Operator",
    "BADGE_NO": "B-1000",
    "CERT_ISSUED_AT": "2026-01-01T00:00:00Z",
    "CERT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "APPLICATOR_CODE": "AP-1000",
    "SETUP_START": "2026-08-01T08:00:00Z",
    "SETUP_END": "2026-08-01T09:00:00Z",
    "SETUP_CLOSE": "2026-08-01T09:00:00Z",
    "PROGRAM_CODE": "PG-1000",
    "WIRE_GAUGE_AWG": 20,
    "WIRE_TYPE": "TXL",
    "CUT_LENGTH_MM": 500.0,
    "STRIP_LENGTH_MM": 5.0,
    "TERMINAL_TYPE": "OPEN_BARREL",
    "MEASURED_FORCE_N": 35.0,
    "ORDER_CODE": "BO-1000",
    "QTY_ORDERED": 1,
    "HIPOT_VOLTAGE_V": 1000.0,
    "DWELL_SECONDS": 2.0,
    "MEASURED_LEAKAGE_UA": 5.0,
    "LEAKAGE_LIMIT_UA": 10.0,
    "TO_REVISION": "B",
    "WIP_DISPOSITION": "REWORK",
}


def create_drawing_payload(**overrides) -> dict:
    defaults = {
        "drawing_number": DEFAULTS["DRAWING_NUMBER"],
        "customer_code": DEFAULTS["CUSTOMER_CODE"],
        "revision": DEFAULTS["REVISION"],
        "workmanship_class": DEFAULTS["WORKMANSHIP_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(drawing_id, **overrides) -> dict:
    defaults = {
        "drawing_id": drawing_id,
        "find_number": DEFAULTS["FIND_NUMBER"],
        "component_type": DEFAULTS["COMPONENT_TYPE"],
        "mpn": DEFAULTS["MPN"],
        "qty_per_harness": DEFAULTS["QTY_PER_HARNESS"],
        "supply_type": DEFAULTS["SUPPLY_TYPE"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_consigned_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": DEFAULTS["LOT_CODE"],
        "owner_customer_code": DEFAULTS["CUSTOMER_CODE"],
        "mpn": "CON-500",
        "unit_liability_cents": DEFAULTS["UNIT_LIABILITY_CENTS"],
        "replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
        "qty_received": DEFAULTS["QTY_RECEIVED"],
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "badge_no": DEFAULTS["BADGE_NO"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(operator_id, **overrides) -> dict:
    defaults = {
        "operator_id": operator_id,
        "workmanship_class": DEFAULTS["WORKMANSHIP_CLASS"],
        "issued_at": DEFAULTS["CERT_ISSUED_AT"],
        "expires_at": DEFAULTS["CERT_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_applicator_payload(**overrides) -> dict:
    defaults = {
        "applicator_code": DEFAULTS["APPLICATOR_CODE"],
        "compatible_terminal_mpn": DEFAULTS["MPN"],
    }
    defaults.update(overrides)
    return defaults


def create_applicator_setup_payload(applicator_id, program_id, setup_operator_id, **overrides) -> dict:
    defaults = {
        "applicator_id": applicator_id,
        "program_id": program_id,
        "setup_operator_id": setup_operator_id,
        "planned_start_at": DEFAULTS["SETUP_START"],
        "planned_end_at": DEFAULTS["SETUP_END"],
    }
    defaults.update(overrides)
    return defaults


def create_machine_program_payload(drawing_id, applicator_id, **overrides) -> dict:
    defaults = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "drawing_id": drawing_id,
        "applicator_id": applicator_id,
        "wire_gauge_awg": DEFAULTS["WIRE_GAUGE_AWG"],
        "wire_type": DEFAULTS["WIRE_TYPE"],
        "cut_length_mm": DEFAULTS["CUT_LENGTH_MM"],
        "strip_length_mm": DEFAULTS["STRIP_LENGTH_MM"],
        "terminal_mpn": DEFAULTS["MPN"],
        "terminal_type": DEFAULTS["TERMINAL_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_pull_test_payload(applicator_id, program_id, **overrides) -> dict:
    defaults = {
        "applicator_id": applicator_id,
        "program_id": program_id,
        "sample_kind": "FIRST_ARTICLE",
        "measured_force_n": DEFAULTS["MEASURED_FORCE_N"],
    }
    defaults.update(overrides)
    return defaults


def create_build_order_payload(drawing_id, **overrides) -> dict:
    defaults = {
        "order_code": DEFAULTS["ORDER_CODE"],
        "drawing_id": drawing_id,
        "qty_ordered": DEFAULTS["QTY_ORDERED"],
    }
    defaults.update(overrides)
    return defaults


def create_kit_issue_payload(component_id, qty_issued, source, consigned_lot_id=None) -> dict:
    payload = {
        "component_id": component_id,
        "qty_issued": qty_issued,
        "source": source,
    }
    if consigned_lot_id is not None:
        payload["consigned_lot_id"] = consigned_lot_id
    return payload


def create_continuity_test_payload(harness_unit_id, opens_count=0) -> dict:
    return {
        "harness_unit_id": harness_unit_id,
        "test_type": "CONTINUITY",
        "opens_count": opens_count,
    }


def create_hipot_test_payload(harness_unit_id, **overrides) -> dict:
    defaults = {
        "harness_unit_id": harness_unit_id,
        "test_type": "HIPOT",
        "hipot_voltage_v": DEFAULTS["HIPOT_VOLTAGE_V"],
        "dwell_seconds": DEFAULTS["DWELL_SECONDS"],
        "measured_leakage_ua": DEFAULTS["MEASURED_LEAKAGE_UA"],
        "leakage_limit_ua": DEFAULTS["LEAKAGE_LIMIT_UA"],
    }
    defaults.update(overrides)
    return defaults


def create_ecn_payload(drawing_id, **overrides) -> dict:
    defaults = {
        "ecn_code": "ECN-1000",
        "drawing_id": drawing_id,
        "to_revision": DEFAULTS["TO_REVISION"],
        "wip_disposition": DEFAULTS["WIP_DISPOSITION"],
    }
    defaults.update(overrides)
    return defaults
