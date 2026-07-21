"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_adjuster_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Adjuster",
        "email": f"{_uniq('adj')}@example.com",
        "adjuster_type": "INDEPENDENT",
        "home_state": "FL",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(adjuster_id, **overrides) -> dict:
    defaults = {
        "adjuster_id": adjuster_id,
        "state_code": "FL",
        "license_number": _uniq("LIC"),
        "license_type": "ALL_LINES",
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cat_event_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Event"),
        "peril_type": "HURRICANE",
        "affected_states": ["FL"],
        "roster_capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_deployment_payload(adjuster_id, cat_event_id, **overrides) -> dict:
    defaults = {
        "adjuster_id": adjuster_id,
        "cat_event_id": cat_event_id,
        "start_at": "2026-07-10T09:00:00Z",
        "end_at": "2026-07-10T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_number": _uniq("CLM"),
        "policyholder_name": "Policyholder",
        "loss_state": "FL",
        "peril_type": "HAIL",
        "policy_type": "ACV",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(claim_id, adjuster_id, **overrides) -> dict:
    defaults = {"claim_id": claim_id, "adjuster_id": adjuster_id}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(assignment_id, claim_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "claim_id": claim_id,
        "scheduled_start": "2026-07-02T09:00:00Z",
        "scheduled_end": "2026-07-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(inspection_id, claim_id, line_items=None, **overrides) -> dict:
    if line_items is None:
        line_items = [{"description": "Roof", "rcv_cents": 4_000_000, "depreciation_pct": 0}]
    defaults = {
        "inspection_id": inspection_id,
        "claim_id": claim_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(inspection_id, assignment_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "assignment_id": assignment_id,
        "scope_narrative": "Scope of loss narrative",
        "photo_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "work_date": "2026-07-02T00:00:00Z",
        "activity": "INSPECTION",
        "hours": 6.0,
        "expense_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "name": "STD",
        "tier1_max_rcv_cents": 5_000_000,
        "tier2_max_rcv_cents": 25_000_000,
        "tier1_flat_fee_cents": 30_000,
        "tier2_flat_fee_cents": 60_000,
        "tier3_flat_fee_cents": 100_000,
        "rcv_pct_bps": 250,
        "pct_cap_cents": 20_000_000,
        "hourly_rate_cents": 8_500,
        "cat_peril_multiplier_bps": 12_500,
    }
    defaults.update(overrides)
    return defaults


def create_fee_bill_payload(assignment_id, claim_id, fee_schedule_id,
                            billing_method, expected_assignment_version, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "claim_id": claim_id,
        "fee_schedule_id": fee_schedule_id,
        "billing_method": billing_method,
        "expected_assignment_version": expected_assignment_version,
    }
    defaults.update(overrides)
    return defaults
