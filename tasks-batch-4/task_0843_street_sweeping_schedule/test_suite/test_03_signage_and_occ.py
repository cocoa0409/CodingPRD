"""Signage lifecycle and optimistic-concurrency control on post-sign.

Translates queue B (Corner) cross_cutting_complexity_layers OCC instances and the
verify-from-unposted invalid-transition instance.
"""
from test_helpers import (
    validate_success, validate_error,
    create_route_payload, create_block_payload, post_sign_payload,
    TEST_USERS,
    create_route, create_block,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]
INSPECTOR = TEST_USERS["signage_inspector_headers"]


def test_verify_sign_from_unposted_returns_invalid_state(api):
    """PRD §3.2: "Verification is only valid when `sign_status` is currently `POSTED`; attempting it from any other signage state is rejected as an invalid state transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/verify_sign_from_unposted_returns_invalid_state
    """
    route = create_route()
    block = create_block(route["id"])
    assert block["sign_status"] == "UNPOSTED"
    res = api.verify_sign(block["id"], INSPECTOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_occ_stale_block_version_on_repost_rejected(api):
    """PRD §2.6: "If they do not match — for instance because a prior post-sign already superseded the previous sign and advanced the block's `version` since the client last read it — the request is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412), preventing the client from overwriting signage state it has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_block_version_on_repost
    """
    route = create_route()
    block = create_block(route["id"])
    stale_version = block["version"]
    # First post-sign advances the block version past `stale_version`.
    validate_success(api.post_sign(block["id"], post_sign_payload(stale_version), INSPECTOR), 200)

    res = api.post_sign(block["id"], post_sign_payload(stale_version, "2026-11-30T00:00:00Z"), INSPECTOR)
    validate_error(res, "ERR_STALE_BLOCK_VERSION", expected_status=412)


def test_occ_correct_block_version_repost_succeeds(api):
    """PRD §3.2: "On a successful post, the server sets `sign_posted_at` to the current logical-clock instant, stores the supplied `sign_expires_at`, sets `sign_status` to `POSTED`, and increments the block's `version` by one."
    PRD §2.4: "`version` — an integer that begins at creation and increments by one on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_block_version_repost_succeeds
    """
    route = create_route()
    block = create_block(route["id"])
    posted_once = validate_success(api.post_sign(block["id"], post_sign_payload(block["version"]), INSPECTOR), 200)
    # Re-read the advanced version and re-post with it.
    reposted = validate_success(
        api.post_sign(block["id"], post_sign_payload(posted_once["version"], "2026-11-30T00:00:00Z"), INSPECTOR), 200)
    assert reposted["version"] == 3
    assert reposted["sign_status"] == "POSTED"
