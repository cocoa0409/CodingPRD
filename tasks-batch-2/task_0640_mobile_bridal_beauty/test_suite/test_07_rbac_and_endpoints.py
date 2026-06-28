"""RBAC denials, ownership, authentication, FK existence, reverse-reachability listing,
and the portfolio-publish computed flag.

Corner queue: rbac, endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_artist,
    create_artist_payload,
    create_event,
    add_face,
    book_trial,
    add_portfolio_item,
    set_clock,
    make_client_headers,
    make_coordinator_headers,
    make_artist_headers,
    build_user_headers,
    NON_EXISTENT_UUID,
)

COORD = make_coordinator_headers()


# ─── RBAC ─────────────────────────────────────────────
def test_client_cannot_register_artist(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST `/bridal-beauty/artists` | Register a roster artist | Coordinator".

    Design: Corner/rbac/client_cannot_register_artist
    """
    payload = create_artist_payload(skill_tier="LEAD", display_name="X")
    resp = api.create_artist(payload, make_client_headers("client-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_coordinator_cannot_complete_trial(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST `/bridal-beauty/trials/{id}/complete` | Mark trial completed | Artist".

    Design: Corner/rbac/coordinator_cannot_complete_trial
    """
    set_clock("2026-06-01T00:00:00Z")
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10, trial_required=True)
    trial = book_trial(event["id"], artist["id"], "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    set_clock("2026-06-10T09:30:00Z")
    # Completing a trial is Artist-exclusive; a Coordinator call -> forbidden.
    validate_error(api.complete_trial(trial["id"], COORD), ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_non_owner_client_cannot_cancel_event(api):
    """PRD §2.4: "the system compares the acting `X-User-ID` to the owning event's
    `client_id`; a mismatch is rejected with `ERR_NOT_EVENT_OWNER`."

    Design: Corner/rbac/non_owner_client_cannot_cancel_event
    """
    set_clock("2026-06-01T00:00:00Z")
    create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    event = create_event(client_id="client-1", venue_distance_km=10)
    face = add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    from test_helpers import confirm_face, quote_event
    confirm_face(face["id"], "client-1")
    quote_event(event["id"])
    # client-2 is not the owner (client-1) -> cancel rejected.
    resp = api.cancel_event(event["id"], {"reason": "CLIENT_CHOICE"}, make_client_headers("client-2"))
    validate_error(resp, ApiErrorId.ERR_NOT_EVENT_OWNER)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which they act.
    A request missing or malforming either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    resp = api.get_artist(NON_EXISTENT_UUID, headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ─── Endpoints / FK integrity / reverse-reachability ──
def test_create_face_for_nonexistent_event_returns_not_found(api):
    """PRD §2.5: "rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve
    to an existing resource. A child lookup never runs before its parent has been confirmed to
    exist."

    Design: Corner/endpoints/create_face_for_nonexistent_event_returns_not_found
    """
    resp = api.add_face(NON_EXISTENT_UUID, {"person_label": "BRIDE", "service_type": "HAIR"}, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_faces_by_event_reverse_reachable(api):
    """PRD §2.5: "Reverse-reachability list endpoints — for example listing the faces of an
    event, the portfolio of an artist, the add-ons of an assignment, or the payments of an
    invoice — first confirm the parent resource exists, then return the children that
    reference it."

    Design: Corner/endpoints/list_faces_by_event_reverse_reachable
    """
    event = create_event(client_id="client-1", venue_distance_km=10)
    add_face(event["id"], "client-1", "BRIDE", "HAIR", is_bride=True)
    resp = api.list_faces(event["id"], make_client_headers("client-1"))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"


def test_list_portfolio_by_artist_reverse_reachable(api):
    """PRD §2.5: "Reverse-reachability list endpoints — for example listing the faces of an
    event, the portfolio of an artist, the add-ons of an assignment, or the payments of an
    invoice — first confirm the parent resource exists, then return the children that
    reference it."

    Design: Corner/endpoints/list_portfolio_by_artist_reverse_reachable
    """
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    add_portfolio_item(artist["id"], look_name="Soft Glam", category="MAKEUP")
    resp = api.list_portfolio(artist["id"], make_client_headers("client-1"))
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"


def test_portfolio_publish_sets_artist_flag(api):
    """PRD §3.1: "Publishing a portfolio item advances it from `DRAFT` to `PUBLISHED` and, as a
    side effect, recomputes the owning artist's `portfolio_published` flag — once any
    published item exists for an artist, that flag reads `true`."

    Design: Corner/endpoints/portfolio_publish_sets_artist_flag
    """
    artist = create_artist(
        hair_rate_per_face_cents=20000, makeup_rate_per_face_cents=25000,
        travel_rate_per_km_cents=600, max_faces_per_hour=2,
    )
    item = add_portfolio_item(artist["id"], look_name="Soft Glam", category="MAKEUP", as_coordinator=False)
    published = validate_success(
        api.publish_portfolio_item(item["id"], make_artist_headers(artist["id"])), 200
    )
    assert published["status"] == "PUBLISHED"
    artist_after = validate_success(api.get_artist(artist["id"], COORD), 200)
    assert artist_after["portfolio_published"] is True
