"""Composite setup helpers for multi-step test prerequisites.

All helpers build state from scratch via PRD-declared endpoints and use the
lenient get_success_data() validator so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, INTAKE_USER_1, INTAKE_USER_2
from .factories import (
    create_attestation_campaign_payload,
    create_attestation_request_payload,
    create_distribution_batch_payload,
    create_distribution_target_payload,
    create_provider_attribute_payload,
    create_provider_merge_payload,
    create_provider_payload,
    create_roster_file_payload,
    create_roster_source_payload,
)
from .test_users import TEST_USERS, make_intake_operator_headers

STEWARD = TEST_USERS["data_steward_headers"]
INTAKE = TEST_USERS["intake_operator_headers"]
INTAKE_2 = TEST_USERS["intake_operator_2_headers"]
DIST_OP = TEST_USERS["distribution_operator_headers"]
CONTACT = TEST_USERS["provider_contact_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Install the logical clock value (PRD §2.4). Returns {current_utc}."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, STEWARD)
    return get_success_data(res)


# ─── Tier 1/2: sources, providers, attributes ─────────

def create_source(**overrides) -> dict:
    """Register a roster source. Returns the ACTIVE source."""
    res = api_client.create_roster_source(create_roster_source_payload(**overrides), STEWARD)
    return get_success_data(res)


def create_provider(**overrides) -> dict:
    """Manually create a provider. Returns the ACTIVE provider (initial score run done)."""
    res = api_client.create_provider(create_provider_payload(**overrides), STEWARD)
    return get_success_data(res)


def get_provider(provider_id: str) -> dict:
    return get_success_data(api_client.get_provider(provider_id, STEWARD))


def add_attribute(provider_id: str, **overrides) -> dict:
    """Manually add an effective-dated attribute. Returns the created attribute."""
    res = api_client.create_provider_attribute(
        provider_id, create_provider_attribute_payload(**overrides), STEWARD
    )
    return get_success_data(res)


# ─── Roster file pipeline (zero-row files) ────────────

def register_file(source_id: str, user_id: str = INTAKE_USER_1, **overrides) -> dict:
    """Register a roster file (default: zero declared rows). Returns RECEIVED file."""
    headers = make_intake_operator_headers(user_id)
    res = api_client.create_roster_file(
        create_roster_file_payload(source_id, **overrides), headers
    )
    return get_success_data(res)


def drive_file_to_state(file_id: str, target_state: str) -> dict:
    """Advance a RECEIVED file through parse/normalize/validate up to target_state.

    target_state is one of PARSED, NORMALIZED, VALIDATED.
    Returns the file as re-read after the last transition.
    """
    steps = {"PARSED": ["parse"], "NORMALIZED": ["parse", "normalize"],
             "VALIDATED": ["parse", "normalize", "validate"]}
    if target_state not in steps:
        raise ValueError(f"unsupported target_state {target_state!r}")
    for step in steps[target_state]:
        res = getattr(api_client, f"{step}_roster_file")(file_id, INTAKE)
        get_success_data(res)
    return get_success_data(api_client.get_roster_file(file_id, INTAKE))


def setup_validated_empty_file(source_overrides=None, file_overrides=None,
                               registrant_user_id: str = INTAKE_USER_1) -> tuple:
    """Source + zero-row file driven to VALIDATED. Returns (source, file)."""
    source = create_source(**(source_overrides or {}))
    f = register_file(source["id"], user_id=registrant_user_id, **(file_overrides or {}))
    file_now = drive_file_to_state(f["id"], "VALIDATED")
    return source, file_now


def commit_file(file_id: str, committer_user_id: str = INTAKE_USER_2) -> dict:
    """Commit a VALIDATED file as a DIFFERENT operator than the registrant (§2.8).

    Re-reads the file to obtain its current version for the OCC field.
    Returns the COMMITTED file from the commit response.
    """
    current = get_success_data(api_client.get_roster_file(file_id, INTAKE))
    res = api_client.commit_roster_file(
        file_id,
        {"expected_roster_file_version": current["version"]},
        make_intake_operator_headers(committer_user_id),
    )
    return get_success_data(res)


def setup_committed_empty_file(source_overrides=None) -> tuple:
    """Source + zero-row file driven through to COMMITTED. Returns (source, file)."""
    source, f = setup_validated_empty_file(source_overrides=source_overrides)
    committed = commit_file(f["id"])
    return source, committed


# ─── Distribution targets and batches ─────────────────

def create_target(**overrides) -> dict:
    """Register a distribution target. Returns the ACTIVE target."""
    res = api_client.create_distribution_target(
        create_distribution_target_payload(**overrides), DIST_OP
    )
    return get_success_data(res)


def create_batch(target_id: str, **overrides) -> dict:
    """Create a distribution batch. Returns the BUILDING batch."""
    res = api_client.create_distribution_batch(
        create_distribution_batch_payload(target_id, **overrides), DIST_OP
    )
    return get_success_data(res)


def publish_batch(batch_id: str) -> dict:
    return get_success_data(api_client.publish_batch(batch_id, DIST_OP))


def setup_acked_baseline_batch(target_id: str) -> dict:
    """Create → publish → ack a batch, making it the target's baseline. Returns it."""
    batch = create_batch(target_id)
    publish_batch(batch["id"])
    return get_success_data(api_client.ack_batch(batch["id"], DIST_OP))


def list_batch_items(batch_id: str, params=None) -> list:
    res = api_client.list_batch_items(batch_id, DIST_OP, params=params)
    body = res.json()
    return body["data"]


# ─── Attestation campaigns and requests ───────────────

def create_open_campaign(window_days: int = 5, **overrides) -> dict:
    """Create a campaign and open it. Returns the OPEN campaign."""
    campaign = get_success_data(
        api_client.create_attestation_campaign(
            create_attestation_campaign_payload(window_days=window_days, **overrides),
            STEWARD,
        )
    )
    return get_success_data(api_client.open_campaign(campaign["id"], STEWARD))


def create_draft_request(campaign_id: str, provider_id: str) -> dict:
    res = api_client.create_attestation_request(
        campaign_id, create_attestation_request_payload(provider_id), STEWARD
    )
    return get_success_data(res)


def send_request(request_id: str) -> dict:
    return get_success_data(api_client.send_attestation_request(request_id, STEWARD))


def create_sent_request(campaign_id: str, provider_id: str) -> dict:
    """Create a DRAFT request and dispatch it. Returns the SENT request."""
    req = create_draft_request(campaign_id, provider_id)
    return send_request(req["id"])


def get_request(request_id: str) -> dict:
    return get_success_data(api_client.get_attestation_request(request_id, STEWARD))


def advance_clock_and_sweep(to_iso8601: str) -> dict:
    """Move the logical clock, then run the expiry sweep. Returns sweep data."""
    set_clock(to_iso8601)
    return get_success_data(api_client.sweep_attestation_requests(STEWARD))


def expire_sent_request(request_id: str, past_due_iso: str) -> dict:
    """Advance the clock past the request's due_at and sweep. Returns EXPIRED request."""
    advance_clock_and_sweep(past_due_iso)
    return get_request(request_id)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_two_consecutive_expiries(provider_id: str, window_days: int = 5) -> tuple:
    """Drive two consecutive attestation requests for the provider to EXPIRED.

    Neither request is escalated, so the provider remains ACTIVE until an
    escalation evaluates the consecutive-expiry count (PRD §3.8).

    Timeline (clock starts 2026-08-01, w = window_days; requires w >= 2):
      R1 sent at start, due start+w; clock -> due1+1d; sweep expires R1.
      R2 sent at due1+1d, due sent+w; clock -> due2+1d; sweep expires R2.
      Escalation of R2 stays legal while clock < due2 + w, which holds at
      due2+1d whenever w >= 2.

    Returns (campaign, request1, request2) with both requests EXPIRED.
    """
    if window_days < 2:
        raise ValueError("window_days must be >= 2 so post-expiry escalation stays legal")
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    due1 = start + timedelta(days=window_days)
    after_due1 = due1 + timedelta(days=1)
    due2 = after_due1 + timedelta(days=window_days)
    after_due2 = due2 + timedelta(days=1)

    campaign = create_open_campaign(window_days=window_days)
    req1 = create_sent_request(campaign["id"], provider_id)
    req1 = expire_sent_request(req1["id"], _iso(after_due1))
    assert req1["status"] == "EXPIRED", f"Setup: request 1 should be EXPIRED, got {req1['status']}"
    req2 = create_sent_request(campaign["id"], provider_id)
    req2 = expire_sent_request(req2["id"], _iso(after_due2))
    assert req2["status"] == "EXPIRED", f"Setup: request 2 should be EXPIRED, got {req2['status']}"
    return campaign, req1, req2


def setup_suspended_provider_via_attestation(provider_id: str, window_days: int = 5) -> tuple:
    """Two consecutive expiries, then escalate the second -> provider SUSPENDED.

    Returns (campaign, request1, request2, provider_after).
    """
    campaign, req1, req2 = setup_two_consecutive_expiries(provider_id, window_days)
    get_success_data(api_client.escalate_attestation_request(req2["id"], STEWARD))
    return campaign, req1, req2, get_provider(provider_id)


# ─── Provider merges ──────────────────────────────────

def merge_providers(survivor_id: str, merged_id: str, rationale: str = "dup") -> dict:
    """Merge merged_id into survivor_id using the merged provider's current version.

    Returns the created provider merge record.
    """
    merged_now = get_provider(merged_id)
    res = api_client.create_provider_merge(
        create_provider_merge_payload(
            survivor_id, merged_id, merged_now["version"], rationale=rationale
        ),
        STEWARD,
    )
    return get_success_data(res)
