"""Credential access-window variants: VACANT vs OCCUPIED (calc_access_window)."""
import pytest

from test_helpers import (
    ApiErrorId,
    INSTRUCTIONS_OCCUPIED,
    INSTRUCTIONS_VACANT,
    api_client,
    create_confirmed_request,
    get_success_data,
    issue_credential,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    make_seller_headers,
    set_clock,
    setup_basic_world,
    setup_occupied_manual_world,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def _issue_for(world, req_id, cred_type="LOCKBOX_CODE"):
    resp = api_client.issue_access_credential(
        req_id, {"credential_type": cred_type}, world["la_headers"]
    )
    return validate_success(resp, expected_status=201)


def test_access_window_vacant_variant_window_and_instructions(api):
    """PRD §3.5: "For a VACANT listing, the credential becomes redeemable one
    hour (60 minutes) before the showing's `start_at` and remains redeemable
    until one hour after its `end_at`; the computed `instructions_text` reads
    "Vacant property: self-access with lockbox/code anytime inside the access
    window.""

    Design: Difficulty/dual_variant_calc/access_window_vacant_vs_occupied
    """
    world = setup_vacant_auto_world(buffer_minutes=30)
    req = create_confirmed_request(
        world["listing"]["id"], world["buyer_agent"]["id"], world["seller"]["id"],
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    cred = _issue_for(world, req["id"], "LOCKBOX_CODE")
    assert cred["active_from"] == "2026-05-02T09:00:00Z", cred
    assert cred["expires_at"] == "2026-05-02T11:30:00Z", cred
    assert cred["instructions_text"] == INSTRUCTIONS_VACANT, cred


def test_access_window_occupied_variant_window_and_instructions(api):
    """PRD §3.5: "For an OCCUPIED listing, entry tightens: redeemable from
    fifteen minutes before `start_at` until the listing's `buffer_minutes`
    after `end_at`, and the `instructions_text` reads "Occupied property:
    occupant-approved access; arrive no earlier than 15 minutes before start.""

    Design: Difficulty/dual_variant_calc/access_window_vacant_vs_occupied
    """
    world = setup_occupied_manual_world(buffer_minutes=30)
    req = create_confirmed_request(
        world["listing"]["id"], world["buyer_agent"]["id"], world["seller"]["id"],
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    cred = _issue_for(world, req["id"], "DOOR_CODE")
    assert cred["active_from"] == "2026-05-02T09:45:00Z", cred
    # expiry rides the listing's buffer_minutes (30) after end_at 10:30
    assert cred["expires_at"] == "2026-05-02T11:00:00Z", cred
    assert cred["instructions_text"] == INSTRUCTIONS_OCCUPIED, cred
