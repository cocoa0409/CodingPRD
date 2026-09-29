"""Request-payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides so a test can vary exactly the field it is exercising.  The
defaults are drawn from the worked illustrations in the requirements: a program
with a base unit price of 62,500,000 cents, an escalation index of 4.0 percent
per year and a base year of 2024, and a pumper on a 17,000 kg chassis whose
axle loads land exactly on the rear rating.
"""

import itertools

# Monotonic suffixes keep codes and names unique within a single test run.
_counter = itertools.count(1)


def next_suffix():
    return next(_counter)


# ─── Apparatus program ────────────────────────────────────────────────────

def build_program_payload(**overrides):
    payload = {
        "name": f"Metro FD 2024-2029 Pumper Program {next_suffix()}",
        "agency_name": "Metro Fire Department",
        "base_year": 2024,
        "base_unit_price_cents": 62_500_000,
        "escalation_index_pct_per_year": 4.0,
        "max_option_units": 1,
        "contract_ceiling_cents": 400_000_000,
    }
    payload.update(overrides)
    return payload


# ─── Bid specification and clauses ────────────────────────────────────────

def build_specification_payload(program_id, **overrides):
    payload = {
        "program_id": program_id,
        "title": f"Pumper Body Specification Rev {next_suffix()}",
    }
    payload.update(overrides)
    return payload


def build_clause_payload(**overrides):
    payload = {
        "clause_code": f"C{next_suffix()}",
        "category": "PUMP",
        "requirement_text": "1500 gpm single stage pump",
        "mandatory": True,
        "is_restrictive": False,
    }
    payload.update(overrides)
    return payload


# ─── Compliance matrix ────────────────────────────────────────────────────

def build_compliance_entry_payload(specification_id, clause_id, **overrides):
    payload = {
        "specification_id": specification_id,
        "clause_id": clause_id,
        "response": "COMPLY",
    }
    payload.update(overrides)
    return payload


def build_disposition_payload(**overrides):
    payload = {"disposition": "ACCEPTED"}
    payload.update(overrides)
    return payload


# ─── Unit order ───────────────────────────────────────────────────────────

def build_unit_order_payload(program_id, specification_id, **overrides):
    """A pumper whose rear axle load lands exactly on its 10,110 kg rating."""
    payload = {
        "program_id": program_id,
        "specification_id": specification_id,
        "unit_type": "PUMPER",
        "award_year": 2026,
        "gvwr_kg": 17_000,
        "front_axle_rating_kg": 6_800,
        "rear_axle_rating_kg": 10_110,
        "base_curb_front_kg": 5_200,
        "base_curb_rear_kg": 7_000,
        "crew_seat_count": 4,
        "weight_calc_engineer_user_id": "eng-1",
    }
    payload.update(overrides)
    return payload


# ─── Supplier slot line and chassis reservation ───────────────────────────

def build_slot_line_payload(**overrides):
    payload = {
        "supplier_name": f"Freightline Custom Chassis {next_suffix()}",
        "component_type": "CHASSIS",
        "total_slot_count": 2,
    }
    payload.update(overrides)
    return payload


def build_reservation_payload(program_id, slot_line_id, expected_slot_line_version,
                              **overrides):
    payload = {
        "program_id": program_id,
        "slot_line_id": slot_line_id,
        "slot_start_date": "2026-09-01T00:00:00Z",
        "slot_end_date": "2026-09-15T00:00:00Z",
        "reserved_price_cents": 30_000_000,
        "expiry_at": "2026-12-01T00:00:00Z",
        "expected_slot_line_version": expected_slot_line_version,
    }
    payload.update(overrides)
    return payload


# ─── Plant bay and inspection trip ────────────────────────────────────────

def build_plant_bay_payload(**overrides):
    payload = {
        "name": f"Bay {next_suffix()}",
        "max_concurrent_visitors": 10,
    }
    payload.update(overrides)
    return payload


def build_inspection_trip_payload(unit_order_id, plant_bay_id, **overrides):
    payload = {
        "unit_order_id": unit_order_id,
        "plant_bay_id": plant_bay_id,
        "trip_type": "PRE_CONSTRUCTION",
        "scheduled_start": "2026-08-10T08:00:00Z",
        "scheduled_end": "2026-08-10T16:00:00Z",
        "committee_size": 4,
    }
    payload.update(overrides)
    return payload


# ─── Change order ─────────────────────────────────────────────────────────

def build_line_item(**overrides):
    item = {
        "description": "Additional compartment shelving",
        "quantity": 1,
        "unit_cost_cents": 100_000,
        "markup_pct": 10.0,
        "is_taxable": False,
    }
    item.update(overrides)
    return item


def build_change_order_payload(unit_order_id, inspection_trip_id,
                               expected_unit_order_version, **overrides):
    payload = {
        "unit_order_id": unit_order_id,
        "inspection_trip_id": inspection_trip_id,
        "expected_unit_order_version": expected_unit_order_version,
        "line_items": [build_line_item()],
        "weight_delta_front_kg": 0,
        "weight_delta_rear_kg": 0,
    }
    payload.update(overrides)
    return payload


def build_revision_payload(**overrides):
    payload = {
        "line_items": [build_line_item()],
        "weight_delta_front_kg": 0,
        "weight_delta_rear_kg": 0,
    }
    payload.update(overrides)
    return payload


# ─── Certification test ───────────────────────────────────────────────────

def build_certification_test_payload(unit_order_id, **overrides):
    payload = {
        "unit_order_id": unit_order_id,
        "test_standard": "NFPA_1901",
    }
    payload.update(overrides)
    return payload


def build_test_result_payload(**overrides):
    payload = {
        "result": "PASS",
        "signed_by_user_id": "eng-2",
    }
    payload.update(overrides)
    return payload


# ─── Delivery and warranty ────────────────────────────────────────────────

def build_delivery_payload(**overrides):
    payload = {
        "delivery_date": "2026-10-15T00:00:00Z",
        "training_hours": 4.0,
        "warranty_months": 24,
    }
    payload.update(overrides)
    return payload


def build_training_payload(**overrides):
    payload = {"additional_training_hours": 12.0}
    payload.update(overrides)
    return payload
