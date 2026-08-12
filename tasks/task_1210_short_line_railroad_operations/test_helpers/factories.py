"""Payload factories — one per entity, input fields only (PRD §3)."""

_DEFAULT_MARK_SEQ = {"n": 7000}


def next_reporting_mark(prefix: str = "GNWR") -> str:
    _DEFAULT_MARK_SEQ["n"] += 1
    return f"{prefix} {_DEFAULT_MARK_SEQ['n']}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Shipper Co",
        "billing_email": "billing@shipper.example",
    }
    defaults.update(overrides)
    return defaults


def create_siding_payload(customer_id, segment_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "name": "Test Siding",
        "capacity_cars": 10,
        "serving_track_segment_id": segment_id,
        "agreement_expires_on": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_car_order_payload(customer_id, siding_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "siding_id": siding_id,
        "car_type": "BOX",
        "quantity": 1,
        "needed_by_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_railcar_payload(**overrides) -> dict:
    defaults = {
        "reporting_mark": next_reporting_mark(),
        "car_type": "BOX",
        "ownership": "HOME",
        "hire_rate_per_hour_cents": 0,
        "hire_rate_per_mile_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "name": "T. Crew",
        "craft": "CONDUCTOR",
    }
    defaults.update(overrides)
    return defaults


def create_crew_call_payload(crew_member_id, **overrides) -> dict:
    defaults = {
        "crew_member_id": crew_member_id,
        "scheduled_start_at": "2026-05-02T06:00:00Z",
        "scheduled_end_at": "2026-05-02T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_switch_job_payload(**overrides) -> dict:
    defaults = {
        "scheduled_date": "2026-05-02",
        "notes": "Routine industry switch",
    }
    defaults.update(overrides)
    return defaults


def create_train_movement_payload(route_segment_ids, **overrides) -> dict:
    defaults = {
        "symbol": "GW-100",
        "route_segment_ids": list(route_segment_ids),
    }
    defaults.update(overrides)
    return defaults


def create_interchange_event_payload(railcar_id, **overrides) -> dict:
    defaults = {
        "class_i_partner": "CSX",
        "direction": "RECEIVED",
        "railcar_id": railcar_id,
    }
    defaults.update(overrides)
    return defaults


def create_waybill_payload(railcar_id, origin_customer_id, **overrides) -> dict:
    defaults = {
        "railcar_id": railcar_id,
        "origin_customer_id": origin_customer_id,
        "destination": "CSX Buffalo Frontier Yard",
        "commodity": "GRAIN",
        "weight_tons": 10,
        "through_route": False,
    }
    defaults.update(overrides)
    return defaults


def create_revenue_division_payload(waybill_id, **overrides) -> dict:
    defaults = {
        "waybill_id": waybill_id,
        "basis": "MILEAGE_PRORATE",
    }
    defaults.update(overrides)
    return defaults


def create_track_segment_payload(**overrides) -> dict:
    defaults = {
        "name": "Main MP 1-2",
        "milepost_start": 1,
        "milepost_end": 2,
        "fra_class": "CLASS_1",
    }
    defaults.update(overrides)
    return defaults


def create_track_inspection_payload(segment_id, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "scheduled_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(segment_id, **overrides) -> dict:
    defaults = {
        "incident_type": "DERAILMENT",
        "segment_id": segment_id,
        "occurred_at": "2026-05-01T08:00:00Z",
        "estimated_damage_cents": 2000000,
        "injuries_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_grant_project_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Grant Project",
        "grantor": "FRA CRISI",
        "award_amount_cents": 1000000,
        "required_match_pct": 20,
    }
    defaults.update(overrides)
    return defaults


def create_grant_milestone_payload(**overrides) -> dict:
    defaults = {
        "name": "Milestone 1",
        "milestone_value_cents": 100000,
    }
    defaults.update(overrides)
    return defaults
