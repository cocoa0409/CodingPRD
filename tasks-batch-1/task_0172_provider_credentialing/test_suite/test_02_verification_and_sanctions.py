"""Primary-source verification, the reverify revert loop, and sanctions screening.

Covers corner-design instances from `state_machines`, `calculations`, and
`cross_cutting_complexity_layers` concerning verification request completion,
the lapsed-credential block, the reverify cascade, and screening resolution.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    make_system_admin_headers, make_specialist_headers,
    make_compliance_officer_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload, create_credential_item_payload,
    create_verification_request_payload, complete_verification_payload,
    create_sanctions_source_payload, create_sanctions_screening_payload,
    resolve_screening_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
COMP = make_compliance_officer_headers("comp-1")


# =========================================================================
# Verification request completion
# =========================================================================
def test_complete_verification_twice_returns_not_open():
    """PRD §3.3: "A completion is permitted only when the owning verification
    request is currently `OPEN` (otherwise `ERR_VERIFICATION_NOT_OPEN`)."

    Design: Corner/state_machines/complete_verification_twice_returns_not_open
    """
    org_id, provider, item = fx.setup_provider_in_verification()
    vr = validate_success(api_client.create_verification_request(
        item["id"], create_verification_request_payload(), SPEC), 201)
    validate_success(api_client.complete_verification_request(
        vr["id"], complete_verification_payload("PASS"), SPEC), 200)
    resp = api_client.complete_verification_request(
        vr["id"], complete_verification_payload("PASS"), SPEC)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_OPEN.value)


def test_reverify_item_not_rejected_returns_error():
    """PRD §3.3: "Re-verification is permitted only when the item's
    `verification_state` is currently `REJECTED` (otherwise
    `ERR_ITEM_NOT_REJECTED`)".

    Design: Corner/state_machines/reverify_item_not_rejected_returns_error
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    item = validate_success(api_client.create_credential_item(
        provider["id"], create_credential_item_payload(), SPEC), 201)
    resp = api_client.reverify_credential_item(item["id"], SPEC)
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_REJECTED.value)


def test_lapsed_item_blocks_pass_verification():
    """PRD §3.3: "A `PASS` completion additionally requires that the credential
    item's `expirable_band` is not `LAPSED`; a lapsed credential cannot be passed
    and is rejected with `ERR_CREDENTIAL_LAPSED` (HTTP 409)."

    Design: Corner/calculations/lapsed_item_blocks_pass_verification
    """
    org = validate_success(api_client.create_org(create_org_payload(), ADMIN), 201)
    provider = validate_success(api_client.create_provider(create_provider_payload(org["id"]), SPEC), 201)
    item = validate_success(api_client.create_credential_item(
        provider["id"],
        create_credential_item_payload(expiration_date="2026-02-01T00:00:00.000Z"),
        SPEC), 201)
    validate_success(api_client.submit_application(provider["id"], SPEC), 200)
    validate_success(api_client.begin_verification(provider["id"], SPEC), 200)
    vr = validate_success(api_client.create_verification_request(
        item["id"], create_verification_request_payload(), SPEC), 201)
    # Advance the clock past the item's expiration so it LAPSES.
    validate_success(api_client.set_clock(
        {"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN), 200)
    resp = api_client.complete_verification_request(
        vr["id"], complete_verification_payload("PASS"), SPEC)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_LAPSED.value)


def test_reverify_creates_fresh_open_request_cascade():
    """PRD §3.3: "Re-verification is permitted only when the item's
    `verification_state` is currently `REJECTED` ...; it returns the item to
    `PENDING_PSV` and creates a fresh verification request in `OPEN` status,
    closing the revert loop so the item can be verified again."

    Design: Corner/cross_cutting_complexity_layers/reverify_creates_fresh_request_cascade
    """
    org_id, provider, item = fx.setup_provider_in_verification()
    vr = validate_success(api_client.create_verification_request(
        item["id"], create_verification_request_payload(), SPEC), 201)
    validate_success(api_client.complete_verification_request(
        vr["id"], complete_verification_payload("FAIL"), SPEC), 200)
    # reverify the now-REJECTED item
    reverified = validate_success(api_client.reverify_credential_item(item["id"], SPEC), 200)
    assert reverified["verification_state"] == "PENDING_PSV"
    # a fresh OPEN verification request now exists for the item
    listing = api_client.list_item_verification_requests(item["id"], SPEC)
    data, _meta = validate_paginated(listing)
    open_requests = [r for r in data if r["status"] == "OPEN"]
    assert len(open_requests) == 1, f"expected exactly one OPEN request, got {[r['status'] for r in data]}"


# =========================================================================
# Sanctions screening resolution
# =========================================================================
def test_resolve_screening_already_resolved_returns_not_open():
    """PRD §3.4: "Resolution is permitted only when the screening is currently
    `OPEN` (otherwise `ERR_SCREENING_NOT_OPEN`)".

    Design: Corner/state_machines/resolve_screening_already_resolved_returns_not_open
    """
    ctx = fx.setup_open_hit_screening(severity_weight=3)
    validate_success(api_client.resolve_sanctions_screening(
        ctx["screening"]["id"], resolve_screening_payload("cleared"), COMP), 200)
    resp = api_client.resolve_sanctions_screening(
        ctx["screening"]["id"], resolve_screening_payload("again"), COMP)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_OPEN.value)


def test_resolve_screening_without_note_returns_note_required():
    """PRD §3.4: "Resolution is permitted only when the screening is currently
    `OPEN` (otherwise `ERR_SCREENING_NOT_OPEN`) and only when a non-empty
    `resolution_note` is provided (otherwise `ERR_RESOLUTION_NOTE_REQUIRED`,
    HTTP 400)."

    Design: Corner/state_machines/resolve_screening_without_note_returns_note_required
    """
    ctx = fx.setup_open_hit_screening(severity_weight=3)
    resp = api_client.resolve_sanctions_screening(
        ctx["screening"]["id"], resolve_screening_payload(""), COMP)
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_NOTE_REQUIRED.value)
