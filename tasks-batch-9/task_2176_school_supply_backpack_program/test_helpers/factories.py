"""Payload factories - one per entity, input fields only."""

from .constants import (
    BACKPACK_PACK_SIZE,
    BACKPACK_UNIT_COST_CENTS,
    CYCLE_WINDOW_END,
    CYCLE_WINDOW_START,
    EVENT_WINDOW_END,
    EVENT_WINDOW_START,
    NOTEBOOK_PACK_SIZE,
    NOTEBOOK_UNIT_COST_CENTS,
    PENCIL_PACK_SIZE,
    PENCIL_UNIT_COST_CENTS,
)


def school_payload(**overrides) -> dict:
    payload = {
        "name": "Lincoln Elementary",
        "district_code": "D7",
        "title_i_pct": 0.80,
        "enrollment_count": 400,
        "max_concurrent_seats": 120,
    }
    payload.update(overrides)
    return payload


def supply_item_payload(**overrides) -> dict:
    payload = {
        "sku": "PEN-12",
        "name": "Pencils 12-pack",
        "category": "WRITING",
        "unit_cost_cents": PENCIL_UNIT_COST_CENTS,
        "bulk_pack_size": PENCIL_PACK_SIZE,
    }
    payload.update(overrides)
    return payload


def pencil_payload(**overrides) -> dict:
    return supply_item_payload(**overrides)


def notebook_payload(**overrides) -> dict:
    return supply_item_payload(
        sku="NBK-01",
        name="Composition notebook",
        category="PAPER",
        unit_cost_cents=NOTEBOOK_UNIT_COST_CENTS,
        bulk_pack_size=NOTEBOOK_PACK_SIZE,
        **overrides,
    )


def backpack_payload(**overrides) -> dict:
    return supply_item_payload(
        sku="BPK-01",
        name="Standard backpack",
        category="BACKPACK",
        unit_cost_cents=BACKPACK_UNIT_COST_CENTS,
        bulk_pack_size=BACKPACK_PACK_SIZE,
        **overrides,
    )


def grade_kit_spec_payload(school_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "grade_band": "K_2",
        "student_target_count": 100,
    }
    payload.update(overrides)
    return payload


def kit_spec_line_payload(spec_id, supply_item_id, **overrides) -> dict:
    payload = {
        "grade_kit_spec_id": spec_id,
        "supply_item_id": supply_item_id,
        "qty_per_student": 1,
    }
    payload.update(overrides)
    return payload


def drive_cycle_payload(**overrides) -> dict:
    payload = {
        "name": "Back-to-School 2026",
        "cadence": "BACK_TO_SCHOOL",
        "window_start": CYCLE_WINDOW_START,
        "window_end": CYCLE_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def collection_site_payload(cycle_id, **overrides) -> dict:
    payload = {
        "drive_cycle_id": cycle_id,
        "name": "Northside Depot",
        "site_type": "RETAIL",
        "bin_capacity": 10,
    }
    payload.update(overrides)
    return payload


def donation_batch_payload(site_id, supply_item_id, **overrides) -> dict:
    payload = {
        "collection_site_id": site_id,
        "supply_item_id": supply_item_id,
        "qty_declared": 10,
        "condition": "NEW",
        "sealed": True,
    }
    payload.update(overrides)
    return payload


def inventory_adjustment_payload(cycle_id, supply_item_id, delta_on_hand_qty, **overrides) -> dict:
    payload = {
        "drive_cycle_id": cycle_id,
        "supply_item_id": supply_item_id,
        "delta_on_hand_qty": delta_on_hand_qty,
        "reason": "opening count",
    }
    payload.update(overrides)
    return payload


def cash_donation_payload(cycle_id, **overrides) -> dict:
    payload = {
        "drive_cycle_id": cycle_id,
        "donor_name": "Acme Corp",
        "amount_cents": 50_000,
        "restriction_type": "UNRESTRICTED",
    }
    payload.update(overrides)
    return payload


def purchase_order_payload(cycle_id, supply_item_id, **overrides) -> dict:
    payload = {
        "drive_cycle_id": cycle_id,
        "supply_item_id": supply_item_id,
        "requested_unit_gap": 24,
    }
    payload.update(overrides)
    return payload


def volunteer_event_payload(site_id, **overrides) -> dict:
    payload = {
        "collection_site_id": site_id,
        "event_type": "ASSEMBLY",
        "window_start": "2026-08-05T09:00:00Z",
        "window_end": "2026-08-05T12:00:00Z",
        "volunteer_count": 6,
        "minor_volunteer_count": 0,
        "adult_supervisor_count": 1,
    }
    payload.update(overrides)
    return payload


def distribution_event_payload(school_id, cycle_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "drive_cycle_id": cycle_id,
        "grade_band": "K_2",
        "window_start": EVENT_WINDOW_START,
        "window_end": EVENT_WINDOW_END,
        "seat_capacity": 10,
    }
    payload.update(overrides)
    return payload


def student_registration_payload(event_id, **overrides) -> dict:
    payload = {
        "distribution_event_id": event_id,
        "student_reference": "S-001",
        "grade_band": "K_2",
        "guardian_name": "G One",
        "free_lunch_eligible": True,
    }
    payload.update(overrides)
    return payload


def teacher_request_payload(school_id, cycle_id, supply_item_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "drive_cycle_id": cycle_id,
        "supply_item_id": supply_item_id,
        "teacher_name": "Ms Rivera",
        "qty_requested": 10,
        "justification": "Classroom restock",
    }
    payload.update(overrides)
    return payload
