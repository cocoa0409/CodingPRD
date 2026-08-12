"""Boundary precision: daily cap at exact max; credential expiry exclusivity."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_confirmed_request,
    create_showing_request,
    create_showing_request_payload,
    issue_credential,
    redeem_credential,
    set_clock,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_daily_cap_allows_up_to_max(api):
    """PRD §3.3: "The platform counts the listing's requests in
    PENDING_APPROVAL, APPROVED, or CONFIRMED whose `start_at` falls on the same
    UTC calendar date as the proposed start; creation proceeds only while that
    count is strictly below `max_showings_per_day`."

    With max_showings_per_day=2 the first and second same-day requests succeed.

    Design: Difficulty/boundary_precision_check/daily_cap_at_exact_max
    """
    world = setup_vacant_auto_world(max_showings_per_day=2)
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    r1 = create_showing_request(listing_id, ba_id,
                                "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    r2 = create_showing_request(listing_id, ba_id,
                                "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")
    assert r1["status"] == "APPROVED", r1  # auto-approve world
    assert r2["status"] == "APPROVED", r2


def test_daily_cap_rejects_at_exact_max(api):
    """PRD §3.3: "creation proceeds only while that count is strictly below
    `max_showings_per_day`, so a request arriving when the count already equals
    the cap is rejected with `ERR_DAILY_SHOWING_LIMIT` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/daily_cap_at_exact_max
    """
    world = setup_vacant_auto_world(max_showings_per_day=2)
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    create_showing_request(listing_id, ba_id,
                           "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    create_showing_request(listing_id, ba_id,
                           "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")
    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T14:00:00Z", "2026-05-01T14:30:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DAILY_SHOWING_LIMIT)


def _setup_two_credentials():
    """Two confirmed showings with credentials on a VACANT listing (buffer 30):
    C1 window [09:00, 11:30); C2 window [11:00, 13:30)."""
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]
    seller_id = world["seller"]["id"]
    la_id = world["listing_agent"]["id"]

    r1 = create_confirmed_request(listing_id, ba_id, seller_id,
                                  "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    c1 = issue_credential(r1["id"], la_id, "LOCKBOX_CODE")
    r2 = create_confirmed_request(listing_id, ba_id, seller_id,
                                  "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z")
    c2 = issue_credential(r2["id"], la_id, "DOOR_CODE")
    return world, c1, c2


def test_credential_redeem_one_minute_before_expiry_succeeds(api):
    """PRD §2.10: "A credential is redeemable from its `active_from`
    (inclusive) until its `expires_at` (exclusive); the instant of
    `expires_at` itself is already too late."

    C1 expires_at == 2026-05-01T11:30:00Z; redeem at 11:29 succeeds.

    Design: Difficulty/boundary_precision_check/credential_redeem_at_exact_expiry
    """
    world, c1, _c2 = _setup_two_credentials()
    assert c1["expires_at"] == "2026-05-01T11:30:00Z", c1
    set_clock("2026-05-01T11:29:00Z")
    redeemed = redeem_credential(c1["id"], world["buyer_agent"]["id"])
    assert redeemed["status"] == "USED", redeemed


def test_credential_redeem_at_exact_expiry_rejected(api):
    """PRD §2.10: "A credential is redeemable from its `active_from`
    (inclusive) until its `expires_at` (exclusive); the instant of
    `expires_at` itself is already too late." PRD §3.5: "now must still be
    before `expires_at`, else `ERR_CREDENTIAL_EXPIRED` (HTTP 422)."

    C2 expires_at == 2026-05-01T13:30:00Z; redeem at exactly 13:30 fails.

    Design: Difficulty/boundary_precision_check/credential_redeem_at_exact_expiry
    """
    world, _c1, c2 = _setup_two_credentials()
    assert c2["expires_at"] == "2026-05-01T13:30:00Z", c2
    set_clock("2026-05-01T13:30:00Z")
    resp = api_client.redeem_access_credential(c2["id"], world["ba_headers"])
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRED)
