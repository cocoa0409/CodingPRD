"""Optimistic concurrency (policy / approval-settings OCC) and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_confirmed_request,
    create_listing_payload,
    create_seller_payload,
    make_admin_headers,
    make_listing_agent_headers,
    make_seller_headers,
    register_agent,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_occ_policy_update_happy_path(api):
    """PRD §2.8: "A successful guarded update increments the parent's `version`
    by one, so every accepted write invalidates previously observed versions."
    PRD §3.2: "The caller may supply any subset of `buffer_minutes`,
    `max_showings_per_day`, and `min_notice_minutes`, and — because this is one
    of the two OCC-guarded writes in the platform — must supply
    `expected_listing_version` matching the listing's current `version`."

    Design: Corner/complexity_layers/occ_policy_update_happy_path
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="OC S", contact_email="oc@x.com"),
        make_admin_headers()), expected_status=201)
    la = register_agent(name="OC LA", license_number="LIC-OC-LA")
    la_headers = make_listing_agent_headers(la["id"])
    listing = validate_success(api_client.create_listing(
        create_listing_payload(seller["id"], address="61 Occ Rd", occupancy_type="VACANT"),
        la_headers), expected_status=201)

    updated = validate_success(api_client.update_listing_policy(
        listing["id"],
        {"buffer_minutes": 45, "expected_listing_version": listing["version"]},
        la_headers))
    assert updated["buffer_minutes"] == 45, updated
    assert updated["version"] == listing["version"] + 1, updated


def test_occ_policy_update_stale_rejected(api):
    """PRD §2.8: "if the listing's version has advanced beyond what the caller
    observed, the update is rejected with `ERR_STALE_LISTING_VERSION` (HTTP
    412), and the caller must re-read the listing before reapplying the
    change."

    Design: Corner/complexity_layers/occ_policy_update_stale_rejected
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="OC2 S", contact_email="oc2@x.com"),
        make_admin_headers()), expected_status=201)
    la = register_agent(name="OC2 LA", license_number="LIC-OC2-LA")
    la_headers = make_listing_agent_headers(la["id"])
    listing = validate_success(api_client.create_listing(
        create_listing_payload(seller["id"], address="63 Occ St", occupancy_type="VACANT"),
        la_headers), expected_status=201)

    updated = validate_success(api_client.update_listing_policy(
        listing["id"],
        {"buffer_minutes": 45, "expected_listing_version": listing["version"]},
        la_headers))

    resp = api_client.update_listing_policy(
        listing["id"],
        {"buffer_minutes": 90, "expected_listing_version": updated["version"] - 1},
        la_headers)
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_LISTING_VERSION)

    after = validate_success(api_client.get_listing(listing["id"], la_headers))
    assert after["buffer_minutes"] == 45, after


def test_occ_seller_settings_stale_rejected(api):
    """PRD §2.8: "An approval-settings update on a seller must likewise carry
    `expected_seller_version`, a non-optional input holding the caller's last
    observed `version` of that seller; a mismatch is rejected with
    `ERR_STALE_SELLER_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_seller_settings_stale_rejected
    """
    seller = validate_success(api_client.create_seller(
        create_seller_payload(full_name="OC3 S", contact_email="oc3@x.com"),
        make_admin_headers()), expected_status=201)
    seller_headers = make_seller_headers(seller["id"])

    updated = validate_success(api_client.update_seller_approval_settings(
        seller["id"],
        {"approval_timeout_minutes": 120, "expected_seller_version": seller["version"]},
        seller_headers))

    resp = api_client.update_seller_approval_settings(
        seller["id"],
        {"auto_approve": True, "expected_seller_version": updated["version"] - 1},
        seller_headers)
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_SELLER_VERSION)

    after = validate_success(api_client.get_seller(seller["id"], make_admin_headers()))
    assert after["auto_approve"] is False, after
    assert after["approval_timeout_minutes"] == 120, after


def test_immediate_consistency_after_confirm(api):
    """PRD §2.9: "Consistency is immediate: a cascade completes within the
    triggering call." PRD §3.5: "the listing's `confirmed_showing_count`
    increments by one (the forward leg of the confirmed-count invariant)."

    The confirm response shows CONFIRMED and an immediate follow-up GET of the
    listing already shows confirmed_showing_count == 1.

    Design: Corner/consistency_model/immediate_consistency_after_confirm
    """
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    req = create_confirmed_request(listing_id, ba_id, world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    assert req["status"] == "CONFIRMED", req

    listing = validate_success(api_client.get_listing(listing_id, world["la_headers"]))
    assert listing["confirmed_showing_count"] == 1, listing
