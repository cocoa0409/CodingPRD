"""Cross-entity state dependencies: listing-ACTIVE gate; CONFIRMED gate for issuance."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_showing_request,
    create_showing_request_payload,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_create_requires_listing_active_rejected_while_paused(api):
    """PRD §3.3: "The listing must be ACTIVE — intake against a PAUSED or
    WITHDRAWN listing fails with `ERR_LISTING_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/create_requires_listing_active
    """
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    validate_success(api_client.pause_listing(listing_id, world["la_headers"]))

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)


def test_create_requires_listing_active_succeeds_after_resume(api):
    """PRD §3.2: "the owning listing agent pauses an ACTIVE listing, moving it
    to PAUSED with a `LISTING_PAUSED` event appended, and later resumes it from
    PAUSED back to ACTIVE with `LISTING_RESUMED`."

    Design: Difficulty/cross_entity_state_dependency/create_requires_listing_active
    """
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    validate_success(api_client.pause_listing(listing_id, world["la_headers"]))
    validate_success(api_client.resume_listing(listing_id, world["la_headers"]))

    req = create_showing_request(listing_id, world["buyer_agent"]["id"],
                                 "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    assert req["status"] == "APPROVED", req  # VACANT + auto_approve


def test_credential_issue_requires_confirmed_rejected_when_approved(api):
    """PRD §3.5: "Issuance requires the request in CONFIRMED — any other state
    yields `ERR_SHOWING_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/credential_issue_requires_confirmed
    """
    world = setup_vacant_auto_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    assert req["status"] == "APPROVED"  # auto-approved, not yet confirmed

    resp = api_client.issue_access_credential(
        req["id"], {"credential_type": "LOCKBOX_CODE"}, world["la_headers"])
    validate_error(resp, ApiErrorId.ERR_SHOWING_NOT_CONFIRMED)


def test_credential_issue_requires_confirmed_succeeds_after_confirm(api):
    """PRD §3.5: "With a confirmed showing in hand, the owning listing agent
    issues exactly one access credential for it." and "a `CREDENTIAL_ISSUED`
    event marks the birth of the credential in ISSUED status."

    Design: Difficulty/cross_entity_state_dependency/credential_issue_requires_confirmed
    """
    world = setup_vacant_auto_world()
    req = create_showing_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                 "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    validate_success(api_client.confirm_showing_request(req["id"], world["ba_headers"]))

    resp = api_client.issue_access_credential(
        req["id"], {"credential_type": "LOCKBOX_CODE"}, world["la_headers"])
    cred = validate_success(resp, expected_status=201)
    assert cred["status"] == "ISSUED", cred
