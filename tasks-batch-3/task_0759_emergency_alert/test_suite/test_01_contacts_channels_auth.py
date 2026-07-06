"""Contacts, channels, and authentication/authorization basics.

Queue B (Corner) coverage: entity creation/validation/defaults/not-found, channel
reverse-reachability, opt-in token enforcement, and the two auth gates.
"""
from test_helpers import (
    api_client as _ac,  # noqa: F401  (ensures package import side effects)
    validate_success, validate_error, validate_paginated, get_success_data,
    build_user_headers,
    create_contact_payload, create_channel_payload,
    ApiErrorId, make_contact_headers, TEST_USERS,
)

ADMIN = TEST_USERS["contact_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_contact_starts_active(api):
    """PRD §3.1: "A new contact's `status` begins as `ACTIVE` and may later read
    `SUSPENDED` or `DELETED`."

    Design: Corner/entities/contact_creation_returns_active
    """
    resp = api.create_contact(create_contact_payload(full_name="Nia", primary_language="EN"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"


def test_get_unknown_contact_returns_not_found(api):
    """PRD §2.8: "the server validates each identifier left to right and rejects on
    the first that does not resolve, returning the not-found error specific to that
    resource type (`ERR_CONTACT_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`, ...".

    Design: Corner/entities/contact_not_found_returns_404
    """
    resp = api.get_contact("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTACT_NOT_FOUND.value)


def test_create_contact_missing_full_name_rejected(api):
    """PRD §3.1: "A `ContactAdmin` seeds the resident database by creating a contact
    with a `full_name`."
    PRD §2.11: "A malformed body, a missing required field, an invalid enum, or an
    out-of-range number is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/contact_missing_full_name_returns_validation
    """
    resp = api.create_contact({"primary_language": "EN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_contact_defaults_primary_language_en(api):
    """PRD §3.1: "a `primary_language` chosen from `EN`, `ES`, `ZH`, or `VI`
    (defaulting to `EN`)".

    Design: Corner/entities/contact_primary_language_default_en
    """
    resp = api.create_contact({"full_name": "Omar"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["primary_language"] == "EN", f"Expected EN default, got {data['primary_language']}"


def test_contact_channels_reverse_reachable(api):
    """PRD §3.1: "Channels can be listed for a contact and filtered by `opt_in_status`."

    Design: Corner/entities/channel_reverse_reachable_from_contact
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Pia"), ADMIN))
    channel = get_success_data(api.add_channel(
        contact["id"], create_channel_payload(channel_type="SMS", address="+15550040"), ADMIN))
    resp = api.list_channels(contact["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert any(c["id"] == channel["id"] for c in data), "created channel must be reverse-reachable"


def test_confirm_channel_wrong_token_rejected(api):
    """PRD §3.1: "the value must equal the channel's stored `confirmation_token` or the
    request is rejected with `ERR_INVALID_TOKEN`, and the acting resident's `X-User-ID`
    must equal the channel's `contact_id`."

    Design: Corner/state_machines/confirm_channel_wrong_token_returns_invalid_token
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Quinn"), ADMIN))
    channel = get_success_data(api.add_channel(
        contact["id"], create_channel_payload(channel_type="SMS", address="+15550041"), ADMIN))
    resp = api.confirm_channel(channel["id"], {"confirmation_token": "WRONG-TOKEN"},
                               make_contact_headers(contact["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_TOKEN.value)
    # Channel stays PENDING when the token is wrong.
    reread = get_success_data(api.get_contact(contact["id"], ADMIN))  # noqa: F841
    chans, _ = validate_paginated(api.list_channels(contact["id"], ADMIN))
    assert chans[0]["opt_in_status"] == "PENDING"


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    ghost = build_user_headers("uma", "Ghost")
    resp = api.create_contact({"full_name": "Uma"}, ghost)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_contact_role_cannot_compose_alert(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/contact_role_cannot_compose_alert
    """
    contact = get_success_data(api.create_contact(create_contact_payload(full_name="Tay"), ADMIN))
    payload = {
        "title": "X", "severity": "WARNING", "channels": ["SMS"], "target_type": "GEO",
        "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000,
        "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-11T00:00:00Z",
    }
    resp = api.create_alert(payload, make_contact_headers(contact["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
