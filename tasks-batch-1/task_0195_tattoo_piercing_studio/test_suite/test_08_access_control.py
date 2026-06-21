"""Access control and listing.

Covers role-exclusive operation enforcement, entity-backed peer ownership
isolation, the unauthenticated-headers rejection, the existence-before-state
precedence, and the paginated list envelope.
"""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_artist_headers, make_client_headers,
    create_artist, create_chair, create_client,
    hold_appointment, setup_confirmed_appointment,
)
from test_helpers import factories

MANAGER = TEST_USERS["manager_headers"]
ANON = {"Content-Type": "application/json"}


def test_client_cannot_create_artist(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: POST `/studio/artists` is authorized for StudioManager only.

    Design: Corner/rbac/client_cannot_create_artist
    """
    client = create_client()
    resp = api.create_artist(
        {"display_name": "Sneaky", "discipline": "TATTOO", "hourly_rate_cents": 18000},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_artist_cannot_complete_others_appointment(api):
    """PRD §2.1: "The `Artist` role is **entity-backed**: when `X-User-Role` is
    `Artist`, the `X-User-ID` is the `id` of the acting `Artist`. Ownership
    checks on any resource that references an `Artist` compare the resource's
    artist foreign key to `X-User-ID`."
    PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    A second artist (not the appointment's artist_id) cannot complete it.

    Design: Corner/rbac/artist_cannot_complete_others_appointment_peer_isolation
    """
    ctx = setup_confirmed_appointment(clock="2026-06-01T12:00:00Z")
    other_artist = create_artist(display_name="Other Artist", hourly_rate_cents=18000)
    resp = api.complete_appointment(
        ctx["appointment_id"], {"actual_minutes": 200},
        make_artist_headers(other_artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
    after = get_success_data(api.get_appointment(ctx["appointment_id"], MANAGER))
    assert after["status"] == "CONFIRMED", f"appointment must stay CONFIRMED, got {after['status']}"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request, except those explicitly marked as anonymous,
    must carry two HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, declaring the capacity in which they act. A request that omits
    or malforms either header on a protected endpoint is rejected with
    `ERR_UNAUTHENTICATED`."

    POST /studio/flash-designs is a protected (Artist) endpoint.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    artist = create_artist(hourly_rate_cents=18000)
    resp = api.create_flash_design(
        factories.create_flash_design_payload(
            artist["id"], title="NoAuth", piece_price_cents=30000, estimated_minutes=60
        ),
        ANON,  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_existence_beats_state_on_confirm(api):
    """PRD §2.9: "Existence is checked third, resolving path identifiers and then
    body foreign keys left to right and failing with `ERR_NOT_FOUND`. State
    validity is checked fourth: an operation requested against a resource that is
    not in a state permitting the transition fails with `ERR_INVALID_STATE`."

    Confirming a non-existent appointment id surfaces the third-layer existence
    error, not a fourth-layer state error.

    Design: Corner/validations/priority_existence_beats_state_on_confirm
    """
    client = create_client()
    resp = api.confirm_appointment(
        "00000000-0000-4000-8000-0000000000aa", make_client_headers(client["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_list_appointments_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_appointments_pagination_envelope
    """
    artist = create_artist(hourly_rate_cents=18000)
    chair1 = create_chair(label="LP Chair 1")
    chair2 = create_chair(label="LP Chair 2")
    client = create_client()
    cid = client["id"]
    hold_appointment(
        artist["id"], cid, chair1["id"], chair1["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-07-01T10:00:00Z", end_at="2026-07-01T11:00:00Z",
    )
    hold_appointment(
        artist["id"], cid, chair2["id"], chair2["version"],
        pricing_mode="HOURLY", hourly_rate_cents=18000, estimated_minutes=60,
        start_at="2026-07-02T10:00:00Z", end_at="2026-07-02T11:00:00Z",
    )
    resp = api.list_appointments(
        make_client_headers(cid), params={"client_id": cid, "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more true, got {meta['has_more']}"
    assert len(data) == 1, f"limit=1 must return 1 item, got {len(data)}"
