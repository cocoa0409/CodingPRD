"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict. Uniqueness-sensitive fields (part_number,
serial_number, doc_number, supplier_code) accept overrides; callers that need
many distinct entities pass a unique suffix.
"""
import uuid


def _suffix() -> str:
    """Short unique token for uniqueness-constrained fields."""
    return uuid.uuid4().hex[:8].upper()


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Components",
        "supplier_code": f"SUP-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(part_type="MAKE", **overrides) -> dict:
    """Part create. BUY parts require default_supplier_id; MAKE/PHANTOM must omit it."""
    defaults = {
        "part_number": f"P-{_suffix()}",
        "name": "Test Part",
        "part_type": part_type,
        "base_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(expected_part_version, **overrides) -> dict:
    defaults = {"expected_part_version": expected_part_version}
    defaults.update(overrides)
    return defaults


def create_bom_line_payload(child_part_id, quantity, expected_part_revision_version, **overrides) -> dict:
    defaults = {
        "child_part_id": child_part_id,
        "quantity": quantity,
        "expected_part_revision_version": expected_part_revision_version,
    }
    defaults.update(overrides)
    return defaults


def create_change_request_payload(affected_part_id, **overrides) -> dict:
    defaults = {
        "title": "Improve fit",
        "affected_part_id": affected_part_id,
        "reason_code": "DESIGN_DEFECT",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(change_request_id, effectivity_date, **overrides) -> dict:
    defaults = {
        "change_request_id": change_request_id,
        "effectivity_date": effectivity_date,
    }
    defaults.update(overrides)
    return defaults


def create_approval_task_payload(assignee_user_id, **overrides) -> dict:
    defaults = {"assignee_user_id": assignee_user_id}
    defaults.update(overrides)
    return defaults


def create_affected_item_payload(part_revision_id, **overrides) -> dict:
    defaults = {"part_revision_id": part_revision_id}
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type="SPEC", **overrides) -> dict:
    defaults = {
        "doc_number": f"DOC-{_suffix()}",
        "title": "Assembly Drawing",
        "doc_type": doc_type,
    }
    defaults.update(overrides)
    return defaults


def create_deviation_payload(part_id, effective_from, effective_to, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "defect_code": "COSMETIC",
        "max_units": 1,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    defaults.update(overrides)
    return defaults


def create_pcn_payload(supplier_id, affected_part_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "affected_part_id": affected_part_id,
        "pcn_reference": f"PCN-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_serialized_unit_payload(part_revision_id, **overrides) -> dict:
    defaults = {
        "serial_number": f"SN-{_suffix()}",
        "part_revision_id": part_revision_id,
    }
    defaults.update(overrides)
    return defaults
