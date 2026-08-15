"""Payload factories — one per entity, input fields only (PRD 4)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": f"Client {_n()}",
        "client_type": "AMC",
        "contact_email": f"ops{_n()}@client.example",
        "default_turn_time_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_appraiser_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Appraiser {n}",
        "license_level": "CERTIFIED_RESIDENTIAL",
        "license_number": f"CR-{1000 + n}",
        "license_expiry": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_trainee_payload(supervisor_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Trainee {n}",
        "license_level": "TRAINEE",
        "license_number": f"TR-{1000 + n}",
        "license_expiry": "2027-06-01",
        "supervisor_id": supervisor_id,
    }
    defaults.update(overrides)
    return defaults


def create_panel_membership_payload(client_id: str, appraiser_id: str) -> dict:
    return {"client_id": client_id, "appraiser_id": appraiser_id}


def create_fee_schedule_payload(
    client_id: str, expected_client_version: int, **overrides
) -> dict:
    defaults = {
        "client_id": client_id,
        "complexity_tier": "STANDARD",
        "base_fee_cents": 45000,
        "rush_multiplier_bps": 1500,
        "revision_fee_cents": 15000,
        "effective_from": "2026-07-01T00:00:00Z",
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "property_address": f"{_n()} Test St",
        "property_type": "SFR",
        "estimated_value_cents": 45000000,
        "loan_type": "CONVENTIONAL",
        "requested_turn_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(
    order_id: str,
    appraiser_id: str,
    window_start: str = "2026-08-02T09:00:00Z",
    window_end: str = "2026-08-02T10:00:00Z",
) -> dict:
    return {
        "order_id": order_id,
        "appraiser_id": appraiser_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def create_comparable_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "address": f"{_n()} Comp Ln",
        "sale_price_cents": 44000000,
        "sale_date": "2026-06-15",
        "distance_miles": 0.40,
        "site_adjustment_cents": 500000,
        "gla_adjustment_cents": 0,
        "condition_adjustment_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "report_type": "FORM_1004",
        "condition_rating": "C3",
    }
    defaults.update(overrides)
    return defaults


def create_revision_request_payload(
    expected_order_version: int, **overrides
) -> dict:
    defaults = {
        "kind": "CORRECTION",
        "detail": "Please correct the report",
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_workfile_record_payload(
    order_id: str, snapshot_type: str = "COMP_DATA"
) -> dict:
    return {"order_id": order_id, "snapshot_type": snapshot_type}


def create_complaint_payload(
    order_id: str, respondent_appraiser_id: str, **overrides
) -> dict:
    defaults = {
        "order_id": order_id,
        "respondent_appraiser_id": respondent_appraiser_id,
        "description": "Board inquiry narrative",
    }
    defaults.update(overrides)
    return defaults


def create_fee_adjustment_payload(kind: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "amount_cents": amount_cents,
        "reason": f"Adjustment {_n()}",
    }
    defaults.update(overrides)
    return defaults
