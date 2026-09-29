"""Local setup helpers for the corner coverage files owned by this author.

These are plain functions (not pytest fixtures): the server is restarted before
every test, so each test must build its own preconditions from scratch using only
the API's own endpoints.

Every helper validates its own call, so a broken precondition surfaces as a clear
setup failure rather than as a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import validate_success

from .test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
)

# Opaque operator identities, one per non-entity-backed role.
CM = make_catastrophe_manager_headers("cm_1")
CM_ALT = make_catastrophe_manager_headers("cm_2")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CE_ALT = make_claims_examiner_headers("ce_2")
CO = make_compliance_officer_headers("co_1")

CLOCK_START = "2026-08-01T00:00:00.000Z"


def event_payload(cat_code, peril_type="HAIL", jurisdiction_state="TX", **overrides):
    payload = {
        "cat_code": cat_code,
        "peril_type": peril_type,
        "jurisdiction_state": jurisdiction_state,
        "event_start_utc": "2026-07-26T00:00:00.000Z",
        "exposure_count": 400,
        "avg_insured_value": 150000,
        "expected_severity_index": 0.0000,
    }
    payload.update(overrides)
    return payload


def new_event(api, cat_code, **overrides):
    """A CatastropheEvent in MONITORING."""
    return validate_success(api.create_event(event_payload(cat_code, **overrides), CM), 201)


def declared_event(api, cat_code, **overrides):
    """A CatastropheEvent moved MONITORING -> DECLARED."""
    event = new_event(api, cat_code, **overrides)
    return validate_success(api.declare_event(event["id"], CM))


def adjuster_payload(full_name, **overrides):
    payload = {
        "full_name": full_name,
        "employment_type": "STAFF",
        "home_state": "TX",
        "licensed_states": ["TX"],
        "license_expiry_utc": "2027-06-30T00:00:00.000Z",
        "max_open_claims": 8,
        "daily_rate": 600,
        "per_diem_rate": 80,
        "desk_certified": False,
        "aerial_certified": False,
    }
    payload.update(overrides)
    return payload


def new_adjuster(api, full_name, **overrides):
    return validate_success(api.create_adjuster(adjuster_payload(full_name, **overrides), DC), 201)


def dwelling_claim_payload(policy_number, event_id=None, **overrides):
    """A single-DWELLING-line claim whose severity lands on 38.00 (STANDARD) when
    its event is HAIL with expected_severity_index 0.0000."""
    payload = {
        "policy_number": policy_number,
        "loss_state": "TX",
        "loss_date_utc": "2026-07-26T00:00:00.000Z",
        "reported_loss_amount": 40000,
        "coverage_lines": [
            {
                "coverage_code": "DWELLING",
                "limit_amount": 100000,
                "deductible_amount": 0,
                "estimated_damage_amount": 50000,
            }
        ],
    }
    if event_id is not None:
        payload["event_id"] = event_id
    payload.update(overrides)
    return payload


def new_claim(api, policy_number, event_id=None, headers=CE, **overrides):
    payload = dwelling_claim_payload(policy_number, event_id, **overrides)
    return validate_success(api.create_claim(payload, headers), 201)


def triaged_claim(api, policy_number, event_id, headers=CE, **overrides):
    claim = new_claim(api, policy_number, event_id, headers, **overrides)
    return validate_success(api.triage_claim(claim["id"], headers))


def active_block(api, event_id, hotel_name="Staging Court", **overrides):
    """A HousingBlock moved PENDING -> ACTIVE on a DECLARED/SURGE_ACTIVE event."""
    payload = {
        "event_id": event_id,
        "hotel_name": hotel_name,
        "city": "Lubbock",
        "rooms_total": 6,
        "nightly_rate": 150,
        "block_start_date": "2026-09-01T00:00:00.000Z",
        "block_end_date": "2026-09-08T00:00:00.000Z",
    }
    payload.update(overrides)
    block = validate_success(api.create_housing_block(payload, DC), 201)
    return validate_success(api.open_housing_block(block["id"], DC))


def mint_estimate(api, event_id, method="EXPOSURE_BASED"):
    """Mint a loss-estimate snapshot against the event's current version."""
    event = validate_success(api.get_event(event_id, CM))
    payload = {
        "event_id": event_id,
        "method": method,
        "expected_event_version": event["version"],
    }
    return validate_success(api.create_loss_estimate(payload, CM), 201)


def surge_active_event(api, cat_code, **overrides):
    """A CatastropheEvent in SURGE_ACTIVE, carrying the ACTIVE housing block and
    the non-stale loss-estimate snapshot the readiness bar demands.

    Returns ``(event, block, snapshot)``.
    """
    event = declared_event(api, cat_code, **overrides)
    block = active_block(api, event["id"])
    snapshot = mint_estimate(api, event["id"])
    event = validate_success(api.activate_surge(event["id"], CM))
    return event, block, snapshot
