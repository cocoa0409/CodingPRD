"""Composite setup helpers.

Every helper here builds its preconditions using ONLY the PRD's own endpoints, so
each returned row is one the API itself agreed to create. Helpers are plain
functions (not pytest fixtures) so they compose freely; they take the client and
the acting headers explicitly and return the created entity dict (``response.data``).

Nothing in this module holds mutable module-level state: the server is restarted
per test, so every helper must be called from inside the test that needs it.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START_UTC
from .test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers()
DC = make_deployment_coordinator_headers()
CE = make_claims_examiner_headers()
CO = make_compliance_officer_headers()


def _data(response, expected_status=None):
    """Assert the call succeeded and return its `data` object."""
    return get_success_data(response, expected_status)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(client, iso: str, headers=None):
    """Move the server-owned logical clock to an explicit instant."""
    return _data(client.set_clock(iso, headers or CM))


def clock_start() -> str:
    """The instant the clock reads on startup."""
    return CLOCK_START_UTC


# --------------------------------------------------------------------------
# CatastropheEvent
# --------------------------------------------------------------------------
def create_event(client, headers=CM, **overrides) -> dict:
    return _data(client.create_event(f.create_event_payload(**overrides), headers), 201)


def declared_event(client, headers=CM, **overrides) -> dict:
    """A CatastropheEvent moved MONITORING -> DECLARED."""
    event = create_event(client, headers, **overrides)
    return _data(client.declare_event(event["id"], headers))


def surge_event(client, cm_headers=CM, dc_headers=DC, **overrides) -> dict:
    """A CatastropheEvent in SURGE_ACTIVE, with the housing block and non-stale
    loss-estimate snapshot the readiness bar requires.

    Returns ``{"event": ..., "housing_block": ..., "snapshot": ...}``.
    """
    event = declared_event(client, cm_headers, **overrides)
    block = active_housing_block(client, event["id"], dc_headers)
    snapshot = mint_loss_estimate(client, event["id"], cm_headers)
    event = _data(client.activate_surge(event["id"], cm_headers))
    return {"event": event, "housing_block": block, "snapshot": snapshot}


def mint_loss_estimate(client, event_id, headers=CM, **overrides) -> dict:
    """Append a loss-estimate snapshot, reading the event's current `version`
    first so the optimistic-concurrency token is fresh."""
    event = _data(client.get_event(event_id, headers))
    payload = f.create_loss_estimate_payload(
        event_id=event_id, expected_event_version=event["version"], **overrides
    )
    return _data(client.create_loss_estimate(payload, headers), 201)


def event_version(client, event_id, headers=CM) -> int:
    return _data(client.get_event(event_id, headers))["version"]


def claim_version(client, claim_id, headers=CE) -> int:
    return _data(client.get_claim(claim_id, headers))["version"]


# --------------------------------------------------------------------------
# RegulatoryBulletin
# --------------------------------------------------------------------------
def draft_bulletin(client, event_id, headers=CO, **overrides) -> dict:
    payload = f.create_bulletin_payload(event_id=event_id, **overrides)
    return _data(client.create_bulletin(payload, headers), 201)


def effective_bulletin(client, event_id, headers=CO, **overrides) -> dict:
    """A bulletin moved DRAFT -> EFFECTIVE. `jurisdiction_state` must match the
    parent event's, so callers on a non-FL event must pass it explicitly."""
    bulletin = draft_bulletin(client, event_id, headers, **overrides)
    return _data(client.activate_bulletin(bulletin["id"], headers))


# --------------------------------------------------------------------------
# Adjuster
# --------------------------------------------------------------------------
def create_adjuster(client, headers=DC, **overrides) -> dict:
    return _data(client.create_adjuster(f.create_adjuster_payload(**overrides), headers), 201)


# --------------------------------------------------------------------------
# HousingBlock
# --------------------------------------------------------------------------
def pending_housing_block(client, event_id, headers=DC, **overrides) -> dict:
    payload = f.create_housing_block_payload(event_id=event_id, **overrides)
    return _data(client.create_housing_block(payload, headers), 201)


def active_housing_block(client, event_id, headers=DC, **overrides) -> dict:
    """A HousingBlock moved PENDING -> ACTIVE. The parent event must already be
    DECLARED or SURGE_ACTIVE."""
    block = pending_housing_block(client, event_id, headers, **overrides)
    return _data(client.open_housing_block(block["id"], headers))


# --------------------------------------------------------------------------
# Deployment
# --------------------------------------------------------------------------
def requested_deployment(client, event_id, headers=DC, **overrides) -> dict:
    payload = f.create_deployment_payload(event_id=event_id, **overrides)
    return _data(client.create_deployment(payload, headers), 201)


def confirmed_deployment(client, event_id, headers=DC, **overrides) -> dict:
    deployment = requested_deployment(client, event_id, headers, **overrides)
    return _data(client.confirm_deployment(deployment["id"], headers))


def desk_deployment_confirmed(client, event_id, adjuster_id, headers=DC, **overrides) -> dict:
    """A CONFIRMED DESK deployment: reserves no rooms, so no HousingBlock
    participates and the housing preconditions cannot interfere."""
    kwargs = {
        "role_type": "DESK",
        "adjuster_id": adjuster_id,
        "window_start_utc": "2026-09-01T00:00:00.000Z",
        "window_end_utc": "2026-09-05T00:00:00.000Z",
    }
    kwargs.update(overrides)
    return confirmed_deployment(client, event_id, headers, **kwargs)


def demobilized_deployment(client, deployment_id, headers=DC) -> dict:
    """Demobilize a CONFIRMED deployment at the current clock instant. The
    adjuster lands in RESTING with `last_demobilized_at_utc` set to now."""
    return _data(client.demobilize_deployment(deployment_id, headers))


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------
def intake_claim(client, headers=CE, **overrides) -> dict:
    return _data(client.create_claim(f.create_claim_payload(**overrides), headers), 201)


def cat_coded_claim(client, event_id, headers=CE, **overrides) -> dict:
    """A claim carrying a non-null `event_id`. Supplying `event_id` on creation
    and assigning it afterwards are two distinct write pathways; this helper uses
    creation when `event_id` is passed inline and the endpoint otherwise."""
    claim = intake_claim(client, headers, **overrides)
    if claim.get("event_id") == event_id:
        return claim
    return _data(
        client.assign_cat_code(claim["id"], f.assign_cat_code_payload(event_id=event_id), headers)
    )


def triaged_claim(client, event_id, headers=CE, **overrides) -> dict:
    """A claim moved INTAKE -> TRIAGED, i.e. carrying `severity_score`,
    `triage_tier`, `inspection_mode`, `deadline_utc`, `advance_cap` and an
    INITIAL_CASE ledger row."""
    overrides.setdefault("event_id", event_id)
    claim = intake_claim(client, headers, **overrides)
    return _data(client.triage_claim(claim["id"], headers))


# --------------------------------------------------------------------------
# InspectionAssignment
# --------------------------------------------------------------------------
def scheduled_inspection(client, claim_id, headers=DC, **overrides) -> dict:
    payload = f.create_inspection_assignment_payload(claim_id=claim_id, **overrides)
    return _data(client.create_inspection_assignment(payload, headers), 201)


def in_progress_inspection(client, assignment_id, headers) -> dict:
    """Start a SCHEDULED assignment. The acting identity must be the assigned
    Adjuster (or a coordinator, per the endpoint's role table)."""
    return _data(client.start_inspection(assignment_id, headers))


def completed_inspection(client, assignment_id, headers, verified_damage_amount=100000) -> dict:
    payload = f.complete_inspection_payload(verified_damage_amount=verified_damage_amount)
    return _data(client.complete_inspection(assignment_id, payload, headers))


# --------------------------------------------------------------------------
# AdvancePayment
# --------------------------------------------------------------------------
def issued_advance(client, claim_id, headers=CE, **overrides) -> dict:
    payload = f.create_advance_payment_payload(claim_id=claim_id, **overrides)
    return _data(client.create_advance_payment(payload, headers), 201)


def voided_advance(client, advance_id, headers=CE, void_reason="Issued in error") -> dict:
    return _data(
        client.void_advance_payment(advance_id, f.void_advance_payload(void_reason), headers)
    )


# --------------------------------------------------------------------------
# ReserveEntry
# --------------------------------------------------------------------------
def append_reserve_entry(client, claim_id, headers=CE, **overrides) -> dict:
    """Append a manual ledger row, reading the claim's current `version` first
    unless the caller pins `expected_claim_version` explicitly."""
    if "expected_claim_version" not in overrides:
        overrides["expected_claim_version"] = claim_version(client, claim_id, headers)
    payload = f.create_reserve_entry_payload(**overrides)
    return _data(client.create_reserve_entry(claim_id, payload, headers), 201)


def ledger_for_claim(client, claim_id, headers=CE) -> list:
    response = client.list_reserve_entries(headers, params={"claim_id": claim_id})
    return _data(response)


# --------------------------------------------------------------------------
# VendorFirm / VendorAssignment
# --------------------------------------------------------------------------
def inactive_vendor_firm(client, headers=None, **overrides) -> dict:
    """A NETWORK_INACTIVE firm. Creation needs no firm identity yet, so any
    VendorCoordinator header works."""
    headers = headers or make_vendor_coordinator_headers("vc_seed")
    return _data(client.create_vendor_firm(f.create_vendor_firm_payload(**overrides), headers), 201)


def activated_vendor_firm(client, event_id, **overrides) -> dict:
    """A firm moved NETWORK_INACTIVE -> ACTIVATED onto `event_id`. The activate
    call is made as the firm's own identity (X-User-ID == VendorFirm.id)."""
    firm = inactive_vendor_firm(client, **overrides)
    own = make_vendor_coordinator_headers(firm["id"])
    return _data(client.activate_vendor_firm(firm["id"], f.activate_vendor_firm_payload(event_id), own))


def dispatched_vendor_assignment(client, claim_id, headers=CE, **overrides) -> dict:
    payload = f.create_vendor_assignment_payload(claim_id=claim_id, **overrides)
    return _data(client.create_vendor_assignment(payload, headers), 201)


def accepted_vendor_assignment(client, claim_id, firm_id, headers=CE, **overrides) -> dict:
    overrides.setdefault("vendor_firm_id", firm_id)
    assignment = dispatched_vendor_assignment(client, claim_id, headers, **overrides)
    own = make_vendor_coordinator_headers(firm_id)
    return _data(client.accept_vendor_assignment(assignment["id"], own))


# --------------------------------------------------------------------------
# FileTransferBatch
# --------------------------------------------------------------------------
def open_batch(client, event_id, headers=CE, **overrides) -> dict:
    return _data(client.create_batch(f.create_batch_payload(event_id, **overrides), headers), 201)


def batch_with_claim(client, event_id, claim_id, headers=CE, **overrides) -> dict:
    batch = open_batch(client, event_id, headers, **overrides)
    return _data(client.add_claim_to_batch(batch["id"], f.add_claim_to_batch_payload(claim_id), headers))


def submitted_batch(client, event_id, claim_id, headers=CE, **overrides) -> dict:
    batch = batch_with_claim(client, event_id, claim_id, headers, **overrides)
    return _data(client.submit_batch(batch["id"], headers))
