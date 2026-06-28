"""Optimistic concurrency on pledge pause and upgrade (PRD §2.7).

Covers the cross-cutting OCC corner instances: version increments on pause, and
stale-version rejection on both pause and upgrade.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_patron_headers,
    make_platform_admin_headers,
    ApiErrorId,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_active_pledge,
    setup_active_membership,
    get_pledge,
)

ADMIN = make_platform_admin_headers()


def test_pause_increments_version_and_resume_with_new_version_succeeds(api):
    """PRD §3.2: "A pause suspends future renewal charges with no refund of the
    current cycle and increments the pledge's `version` by one."
    PRD §3.2: "Resume re-anchors `cycle_anchor_date` to the current clock cycle so
    that renewal billing resumes at the next anchor, and increments the pledge's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_pause
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    patron_headers = make_patron_headers(s["patron"]["id"])
    v0 = s["pledge"]["version"]

    paused = validate_success(
        api_client.pause_pledge(s["pledge"]["id"], {"expected_pledge_version": v0}, patron_headers), 200)
    assert paused["version"] == v0 + 1, f"pause must bump version to {v0 + 1}, got {paused['version']}"

    resumed = validate_success(
        api_client.resume_pledge(s["pledge"]["id"], {"expected_pledge_version": v0 + 1}, patron_headers), 200)
    assert resumed["version"] == v0 + 2, f"resume must bump version to {v0 + 2}, got {resumed['version']}"
    assert resumed["lifecycle_status"] == "ACTIVE"


def test_pause_with_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the pledge's current `version` —
    because some other writer advanced the pledge since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is
    made."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_pause_returns_412
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    basic = create_published_tier(creator["id"], name="BASIC", rank=1, monthly_fee_cents=800)
    plus = create_published_tier(creator["id"], name="PLUS", rank=2, monthly_fee_cents=1500)
    patron = create_patron()
    patron_headers = make_patron_headers(patron["id"])
    pledge = create_active_pledge(patron["id"], creator["id"], basic["id"])
    v0 = pledge["version"]

    # An upgrade bumps the version past v0.
    validate_success(api_client.upgrade_pledge(
        pledge["id"], {"new_tier_id": plus["id"], "expected_pledge_version": v0}, patron_headers), 200)

    # Pausing with the stale (pre-upgrade) version is rejected.
    resp = api_client.pause_pledge(pledge["id"], {"expected_pledge_version": v0}, patron_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_upgrade_with_stale_version_rejected(api):
    """PRD §2.7: "Both the pause operation and the upgrade operation require the
    request to carry `expected_pledge_version`, a non-optional field whose value
    is the `version` of the target `Pledge` that the client last read. If that
    value does not equal the pledge's current `version` ... the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is made."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_upgrade_returns_412
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    basic = create_published_tier(creator["id"], name="BASIC", rank=1, monthly_fee_cents=800)
    plus = create_published_tier(creator["id"], name="PLUS", rank=2, monthly_fee_cents=1500)
    patron = create_patron()
    patron_headers = make_patron_headers(patron["id"])
    pledge = create_active_pledge(patron["id"], creator["id"], basic["id"])
    v0 = pledge["version"]

    # A pause bumps the version to v0+1.
    validate_success(api_client.pause_pledge(
        pledge["id"], {"expected_pledge_version": v0}, patron_headers), 200)

    # Upgrading with the stale version v0 is rejected.
    resp = api_client.upgrade_pledge(
        pledge["id"], {"new_tier_id": plus["id"], "expected_pledge_version": v0}, patron_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
