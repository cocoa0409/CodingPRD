"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_RECEIVED_AT = "2026-01-02T00:00:00.000Z"


def create_part_payload(**overrides) -> dict:
    """POST /parts. is_rohs_required / contains_conflict_minerals have PRD defaults
    (true / false), so they are only supplied when overridden."""
    defaults = {
        "internal_pn": "P-TEST",
        "description": "test part",
        "package_type": "0402",
        "standard_cost_cents": 50,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    """POST /vendors. is_rohs_certified has PRD default false."""
    defaults = {
        "name": "Test Vendor",
        "cage_code": "TST01",
    }
    defaults.update(overrides)
    return defaults


def create_avl_entry_payload(part_id, vendor_id, **overrides) -> dict:
    """POST /avl-entries."""
    defaults = {
        "part_id": part_id,
        "vendor_id": vendor_id,
        "vendor_pn": "VND-PN",
        "approval_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def receive_lot_payload(expected_avl_entry_version, **overrides) -> dict:
    """POST /avl-entries/{id}/receive-lot. is_rohs_compliant / has_cmrt have PRD
    defaults false, so they are only supplied when overridden."""
    defaults = {
        "lot_code": "LOT-1",
        "received_qty": 100,
        "unit_cost_cents": 50,
        "received_at": DEFAULT_RECEIVED_AT,
        "expected_avl_entry_version": expected_avl_entry_version,
    }
    defaults.update(overrides)
    return defaults


def create_bom_payload(**overrides) -> dict:
    """POST /boms. supersedes_bom_id is optional."""
    defaults = {
        "product_code": "BRD-TEST",
        "revision": "A",
    }
    defaults.update(overrides)
    return defaults


def add_bom_line_payload(part_id, **overrides) -> dict:
    """POST /boms/{id}/lines. is_dnp has PRD default false."""
    defaults = {
        "part_id": part_id,
        "ref_designators": ["R1"],
        "qty_per_assembly": 1,
    }
    defaults.update(overrides)
    return defaults


def create_line_program_payload(bom_id, **overrides) -> dict:
    """POST /line-programs."""
    defaults = {
        "bom_id": bom_id,
        "line_code": "LINE-A",
        "feeder_slot_count": 4,
        "program_checksum": "CK1",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(bom_id, **overrides) -> dict:
    """POST /work-orders."""
    defaults = {
        "bom_id": bom_id,
        "planned_qty": 1,
    }
    defaults.update(overrides)
    return defaults


def setup_payload(line_program_id, **overrides) -> dict:
    """POST /work-orders/{id}/setup."""
    defaults = {"line_program_id": line_program_id}
    defaults.update(overrides)
    return defaults


def ship_payload(expected_work_order_version, **overrides) -> dict:
    """POST /work-orders/{id}/ship."""
    defaults = {"expected_work_order_version": expected_work_order_version}
    defaults.update(overrides)
    return defaults


def test_result_payload(result, **overrides) -> dict:
    """POST /units/{id}/test-result. defect_code required only on FAIL."""
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_eco_payload(bom_id, **overrides) -> dict:
    """POST /ecos."""
    defaults = {
        "title": "Test ECO",
        "bom_id": bom_id,
        "change_summary": "test change",
    }
    defaults.update(overrides)
    return defaults


def eco_action_payload(acting_user_id, **overrides) -> dict:
    """POST /ecos/{id}/submit and /approve carry acting_user_id."""
    defaults = {"acting_user_id": acting_user_id}
    defaults.update(overrides)
    return defaults


def create_rework_order_payload(unit_id, defect_code, **overrides) -> dict:
    """POST /rework-orders. eco_id optional."""
    defaults = {
        "unit_id": unit_id,
        "defect_code": defect_code,
    }
    defaults.update(overrides)
    return defaults


def close_rework_payload(replacement_part_id, replacement_qty, acting_user_id, **overrides) -> dict:
    """POST /rework-orders/{id}/close."""
    defaults = {
        "replacement_part_id": replacement_part_id,
        "replacement_qty": replacement_qty,
        "acting_user_id": acting_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_rma_payload(unit_id, **overrides) -> dict:
    """POST /rmas."""
    defaults = {
        "unit_id": unit_id,
        "reported_defect_code": "FIELD-DEFECT",
    }
    defaults.update(overrides)
    return defaults


def triage_rma_payload(failure_class, **overrides) -> dict:
    """POST /rmas/{id}/triage."""
    defaults = {"failure_class": failure_class}
    defaults.update(overrides)
    return defaults


def build_and_test_payload(work_order_id, pass_first_count, rework_from_fail_count,
                           replacement_part_id, **overrides) -> dict:
    """POST /_test/build-and-test-units."""
    defaults = {
        "work_order_id": work_order_id,
        "pass_first_count": pass_first_count,
        "rework_from_fail_count": rework_from_fail_count,
        "replacement_part_id": replacement_part_id,
    }
    defaults.update(overrides)
    return defaults
