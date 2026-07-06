"""Targeting: groups, subscriptions, member-count, and geo-boundary matching."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_contact_payload, create_subscription_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_gateway, create_contact, add_confirmed_channel,
    subscribe_geo, compose_geo_alert, add_localization,
)

ADMIN = TEST_USERS["contact_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_group_subscription_bumps_member_count(api):
    """PRD §3.2: "the group opens with `status` `OPEN` and exposes a computed
    `member_count` equal to the number of active group subscriptions that reference it."

    Design: Corner/state_machines/subscription_cancel_updates_member_count
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Sy"), ADMIN))
    group = get_success_data(api.create_group({"name": "G1"}, ADMIN))
    get_success_data(api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN))
    reread = get_success_data(api.get_group(group["id"], ADMIN))
    assert reread["member_count"] == 1, f"Expected member_count 1, got {reread['member_count']}"


def test_cancel_group_subscription_drops_member_count(api):
    """PRD §3.2: "Cancelling a group subscription recomputes the affected group's
    `member_count`."

    Design: Corner/state_machines/subscription_cancel_updates_member_count
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Sy"), ADMIN))
    group = get_success_data(api.create_group({"name": "G1"}, ADMIN))
    sub = get_success_data(api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN))
    assert get_success_data(api.get_group(group["id"], ADMIN))["member_count"] == 1
    get_success_data(api.cancel_subscription(sub["id"], ADMIN))
    reread = get_success_data(api.get_group(group["id"], ADMIN))
    assert reread["member_count"] == 0, f"Expected member_count 0 after cancel, got {reread['member_count']}"


def test_duplicate_group_subscription_rejected(api):
    """PRD §3.2: "if an `ACTIVE` subscription already exists for the same contact, type,
    and group or geo-centroid, the create is rejected with `ERR_DUPLICATE_SUBSCRIPTION`."

    Design: Corner/errors/duplicate_group_subscription_rejected
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Val"), ADMIN))
    group = get_success_data(api.create_group({"name": "G1"}, ADMIN))
    get_success_data(api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN))
    resp = api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION.value)


def test_subscription_against_closed_group_rejected(api):
    """PRD §3.2: "Creating a group subscription against a group that is not `OPEN` is
    rejected with `ERR_GROUP_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/subscription_requires_open_group
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Ivy"), ADMIN))
    group = get_success_data(api.create_group({"name": "G1"}, ADMIN))
    get_success_data(api.close_group(group["id"], ADMIN))
    resp = api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_GROUP_NOT_OPEN.value)


def test_subscription_against_open_group_succeeds(api):
    """PRD §3.2: "A `ContactAdmin` may close a group, advancing it `OPEN → CLOSED`; a
    closed group refuses new subscriptions."
    PRD §3.2: "A new subscription's `status` is `ACTIVE` and may later become
    `CANCELLED`."

    Design: Difficulty/cross_entity_state_dependency/subscription_requires_open_group
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Ivy2"), ADMIN))
    group = get_success_data(api.create_group({"name": "G1open"}, ADMIN))
    # Group is OPEN by default; the subscription must be accepted and ACTIVE.
    resp = api.create_subscription(
        create_subscription_payload(contact["id"], "GROUP", group_id=group["id"]), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


def test_geo_subscription_at_boundary_is_matched(api):
    """PRD §2.7: "A subscription is matched when this rounded distance in meters is less
    than or equal to the alert's target radius in meters; the boundary is inclusive."
    PRD §3.5: "a `Dispatcher` or `Approver` may request a non-mutating recipient
    preview, which resolves the current targeting and returns the projected
    `estimated_reach`, the `matched_contact_ids`, and the `throttled_contact_ids`
    without changing any state."

    Design: Difficulty/boundary_precision_check/geo_radius_inclusive_boundary_on_preview
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=100)
    contact = create_contact(api, full_name="Hal")
    add_confirmed_channel(api, contact["id"], channel_type="SMS", address="+15550009")
    subscribe_geo(api, contact["id"], center_lat=0.0, center_lon=0.0, radius_m=500)
    # Distance from (0,0) to (0,0.01) rounds to 1113 m; radius 1113 includes it (<=).
    alert = compose_geo_alert(api, center_lat=0.0, center_lon=0.01, radius_m=1113, title="In")
    add_localization(api, alert["id"], "EN", "In.")
    data = get_success_data(api.preview_alert(alert["id"], DISPATCHER))
    assert data["estimated_reach"] == 1, f"Expected reach 1 at inclusive boundary, got {data['estimated_reach']}"


def test_geo_subscription_just_outside_boundary_excluded(api):
    """PRD §2.7: "A subscription is matched when this rounded distance in meters is less
    than or equal to the alert's target radius in meters; the boundary is inclusive."
    PRD §3.5: "a `Dispatcher` or `Approver` may request a non-mutating recipient
    preview, which resolves the current targeting and returns the projected
    `estimated_reach`, the `matched_contact_ids`, and the `throttled_contact_ids`
    without changing any state."

    Design: Difficulty/boundary_precision_check/geo_radius_inclusive_boundary_on_preview
    """
    set_clock(api, "2026-03-10T14:00:00Z")
    create_gateway(api, channel_type="SMS", capacity_per_window=100)
    contact = create_contact(api, full_name="Hal")
    add_confirmed_channel(api, contact["id"], channel_type="SMS", address="+15550009")
    subscribe_geo(api, contact["id"], center_lat=0.0, center_lon=0.0, radius_m=500)
    # Distance rounds to 1113 m; radius 1112 excludes it (1113 > 1112).
    alert = compose_geo_alert(api, center_lat=0.0, center_lon=0.01, radius_m=1112, title="Out")
    add_localization(api, alert["id"], "EN", "Out.")
    data = get_success_data(api.preview_alert(alert["id"], DISPATCHER))
    assert data["estimated_reach"] == 0, f"Expected reach 0 just outside boundary, got {data['estimated_reach']}"
