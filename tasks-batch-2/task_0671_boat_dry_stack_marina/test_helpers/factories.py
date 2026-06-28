"""Payload factories — one per entity, input fields only.

Only source: input fields appear here; computed/system fields are set by the
server. Defaults follow the PRD field descriptions.
"""
from .constants import DEFAULT_LIABILITY_LIMIT_CENTS


def create_marina_payload(**overrides) -> dict:
    defaults = {"name": "Bayfront"}
    defaults.update(overrides)
    return defaults


def create_forklift_payload(marina_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "label": "FL-1",
        "max_lift_weight_lbs": 15000,
    }
    defaults.update(overrides)
    return defaults


def create_rack_payload(marina_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "bay_label": "M-1",
        "size_class": "MEDIUM",
        "max_loa_ft": 30.00,
        "max_beam_ft": 11.00,
        "max_weight_lbs": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(marina_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "full_name": "Otto Owner",
        "email": "otto@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(marina_id, owner_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "owner_id": owner_id,
        "name": "TestBoat",
        "loa_ft": 25.00,
        "beam_ft": 9.00,
        "dry_weight_lbs": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(vessel_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "carrier_name": "AcmeMarine",
        "liability_limit_cents": DEFAULT_LIABILITY_LIMIT_CENTS,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_storage_agreement_payload(vessel_id, rack_id, **overrides) -> dict:
    defaults = {"vessel_id": vessel_id, "rack_id": rack_id}
    defaults.update(overrides)
    return defaults


def create_waitlist_payload(vessel_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "requested_size_class": "SMALL",
        "deposit_paid": False,
    }
    defaults.update(overrides)
    return defaults


def promote_waitlist_payload(marina_id, requested_size_class, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "requested_size_class": requested_size_class,
    }
    defaults.update(overrides)
    return defaults


def create_launch_request_payload(vessel_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "requested_window_start": "2026-04-02T10:00:00Z",
        "with_valet_splash": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(vessel_id, service_kind, **overrides) -> dict:
    defaults = {"vessel_id": vessel_id, "service_kind": service_kind}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(owner_id, source_kind, source_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "source_kind": source_kind,
        "source_id": source_id,
    }
    defaults.update(overrides)
    return defaults
