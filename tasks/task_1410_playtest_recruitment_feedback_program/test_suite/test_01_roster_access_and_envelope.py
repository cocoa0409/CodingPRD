"""Roster creation defaults, read consistency, pagination, auth and RBAC denials."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_instant_equals,
    assert_participant,
    build_user_headers,
    create_moderator,
    create_participant_payload,
    create_study,
    create_ticket,
    get_booking,
    get_success_data,
    is_valid_uuid,
    make_participant_headers,
    parse_instant,
    register_participant,
    set_clock,
    setup_booked_session,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def test_participant_creation_applies_server_defaults(api):
    """PRD §3.1: "New participants start in `REGISTERED` with `no_show_strikes`
    at 0, `risk_score` at 0, and `verified_platform_tags` empty."

    Design: Corner/entities/participant_creation_applies_defaults
    """
    set_clock()
    resp = api.create_participant(create_participant_payload(
        email="cr1@x.com", full_name="Create One", age_years=30), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_participant(data)
    assert data["status"] == "REGISTERED"
    assert data["no_show_strikes"] == 0
    assert data["risk_score"] == 0
    assert data["verified_platform_tags"] == []


def test_participant_missing_email_returns_invalid_request(api):
    """PRD §2.9: "Required fields are present, enum values are valid, and
    numeric ranges hold — `age_years` at least 13, `max_age` at least
    `min_age`, `cohort_capacity` at least 1, `incentive_budget_cents` at least
    0, `max_keys` at least 1, `key_ttl_hours` at least 1, `seat_capacity` at
    least 1, `reach_count` at least 0, `reproducibility_pct` between 0 and 1
    inclusive, `pass_threshold` between 0 and 100 inclusive, and each answer's
    `points` between 0 and its question's `max_points` inclusive; otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "A participant enters the program when a `ResearchOpsAdmin`
    registers them with an `email` that is unique across all participants, a
    `full_name`, a self-declared `age_years` of at least 13, a self-declared
    `region_code` such as US-W, and self-declared `platform_tags` such as PC,
    PS5, or XB."

    Design: Corner/entities/participant_missing_email_returns_invalid_request
    """
    payload = create_participant_payload(email="cr2@x.com")
    del payload["email"]
    resp = api.create_participant(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    listing = get_success_data(api.list_participants(ADMIN))
    assert isinstance(listing, list) and len(listing) == 0, (
        "a rejected creation persists nothing")


def test_participant_get_not_found_returns_404(api):
    """PRD §2.9: "Identifiers in the path are validated left to right, then
    foreign-key identifiers in the body; the first missing reference yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/participant_get_not_found_returns_404
    """
    resp = api.get_participant(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_participant_ignores_client_supplied_system_fields(api):
    """PRD §2.5: "Every primary resource carries a standard set of
    system-managed fields. The `id` is a server-minted UUID with no type
    prefix."
    PRD §2.4: "Every time-gated rule in the system — session start windows,
    signature and key expiry, rolling strike windows, recorded event times —
    evaluates against a server-side logical clock, never against wall-clock
    time."

    Design: Corner/entities/participant_system_fields_input_ignored
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_participant_payload(email="sys1@x.com", full_name="Sys Fields",
                                         age_years=30)
    payload.update({"id": "client-supplied-id", "version": 99,
                    "created_at": "1999-01-01T00:00:00Z"})
    data = validate_success(api.create_participant(payload, ADMIN), expected_status=201)
    assert data["id"] != "client-supplied-id", "the server mints its own id"
    assert is_valid_uuid(data["id"])
    assert isinstance(data["version"], int), "version is a system-managed integer"
    assert data["created_at"] != "1999-01-01T00:00:00Z", (
        "client-supplied created_at is ignored")
    # created_at is a recorded event time: it reads from the logical clock.
    assert_instant_equals(data["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_created_participant_immediately_readable(api):
    """PRD §2.5: "All state changes are atomic and immediately consistent:
    every effect of a request — primary transition, cascade, counter
    adjustment, journal append — commits within that request and is visible to
    the next read."

    Design: Corner/consistency_model/created_participant_immediately_readable
    """
    created = validate_success(api.create_participant(
        create_participant_payload(email="im2@x.com", full_name="Immediate Two",
                                   age_years=31, region_code="US-E",
                                   platform_tags=["PS5"]), ADMIN),
        expected_status=201)
    fetched = validate_success(api.get_participant(created["id"], RESEARCHER))
    assert fetched["email"] == "im2@x.com"
    assert fetched["status"] == "REGISTERED"
    assert fetched["id"] == created["id"]


def test_participant_list_filters_region_and_paginates(api):
    """PRD §3.1: "The participants listing supports filtering by `status` and
    `region_code`."
    PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum
    of 100. The `offset` parameter controls how many items are skipped and
    defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/complexity_layers/participant_list_pagination_with_region_filter
    """
    p1 = register_participant(email="pg-1@x.com", age_years=25, region_code="US-W",
                              active=False)
    p2 = register_participant(email="pg-2@x.com", age_years=26, region_code="US-W",
                              active=False)
    register_participant(email="pg-3@x.com", age_years=27, region_code="US-E",
                         active=False)
    page1, meta1 = validate_paginated(api.list_participants(
        ADMIN, params={"region_code": "US-W", "limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2, "the filter applies before pagination counts"
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(api.list_participants(
        ADMIN, params={"region_code": "US-W", "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    seen = {row["id"] for row in page1 + page2}
    assert seen == {p1["id"], p2["id"]}, (
        "the two pages together contain exactly the US-W participants")
    assert all(row["region_code"] == "US-W" for row in page1 + page2)


def test_missing_or_undeclared_role_returns_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header, or whose
    `X-User-Role` value is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    validate_error(api.list_studies(None), ApiErrorId.ERR_UNAUTHENTICATED)
    bogus = build_user_headers("anon-1", "Anonymous")
    validate_error(api.list_studies(bogus), ApiErrorId.ERR_UNAUTHENTICATED)


def test_participant_cannot_create_study_returns_forbidden(api):
    """PRD §2.1: "When the presented role is not permitted on the target
    endpoint, or when an ownership check on an owned resource fails, the
    request is rejected with `ERR_FORBIDDEN`."
    PRD §4: "`/playtests/studies` | Create a study | ResearchOpsAdmin"

    Design: Corner/validations/participant_cannot_create_study_returns_forbidden
    """
    p = register_participant(email="rb0-p@x.com", active=False)
    resp = api.create_study({
        "title": "Forbidden Study", "code": "NOPE", "min_age": 18, "max_age": 35,
        "allowed_regions": ["US-W"], "required_platforms": ["PC"],
        "cohort_capacity": 10, "incentive_budget_cents": 1000,
    }, make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_forbidden_outranks_not_found(api):
    """PRD §2.9: "Every request is validated against the same ordered gauntlet,
    and a failure at an earlier tier masks every later check."
    PRD §2.9: "The role is permitted on the endpoint and, for `Participant` and
    `Moderator` actors on owned resources, `X-User-ID` equals the resource's
    ownership field; otherwise `ERR_FORBIDDEN`."

    Design: Corner/validations/forbidden_outranks_not_found
    """
    p = register_participant(email="pr1-p@x.com", active=False)
    # Ban is LegalCounsel-only (PRD §4); the missing target id is never reached.
    resp = api.ban_participant(NON_EXISTENT_UUID, make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_moderator_cannot_triage_feedback_returns_forbidden(api):
    """PRD §2.1: "When the presented role is not permitted on the target
    endpoint, or when an ownership check on an owned resource fails, the
    request is rejected with `ERR_FORBIDDEN`."
    PRD §4: "`/playtests/feedback-tickets/{id}/triage` | Triage a ticket |
    Researcher"

    Design: Corner/rbac/moderator_cannot_triage_feedback_returns_forbidden
    """
    study = create_study(open_recruitment=False, code="RB1")
    moderator = create_moderator(display_name="Mod RB1")
    ticket = create_ticket(study["id"], severity="LOW", reach_count=1,
                           reproducibility_pct=0.1, title="Triage target")
    from test_helpers import make_moderator_headers
    resp = api.triage_feedback_ticket(ticket["id"], make_moderator_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_participant_cannot_list_payouts_returns_forbidden(api):
    """PRD §2.1: "When the presented role is not permitted on the target
    endpoint, or when an ownership check on an owned resource fails, the
    request is rejected with `ERR_FORBIDDEN`."
    PRD §4: "`/playtests/incentive-payouts` | List incentive payouts |
    ResearchOpsAdmin, IncentiveOfficer"

    Design: Corner/rbac/participant_cannot_list_payouts_returns_forbidden
    """
    p = register_participant(email="rb2-p@x.com", active=False)
    resp = api.list_incentive_payouts(make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_participant_cannot_cancel_others_booking(api):
    """PRD §3.5: "A booking moves `BOOKED` → `CANCELLED` or `PROMOTED` →
    `CANCELLED` at the request of its owning participant or a
    `ResearchOpsAdmin` — anyone else is `ERR_FORBIDDEN`"
    PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of
    the acting `Participant`; ownership checks on any resource that references
    a participant — an application, a booking, a signature, a survey response,
    a redeemed key — compare the resource's `participant_id` field against
    `X-User-ID`."

    Design: Corner/rbac/participant_cannot_cancel_others_booking
    """
    ctx = setup_booked_session(email="rb3-a@x.com", with_moderator=False)
    other = register_participant(email="rb3-b@x.com", age_years=27)
    resp = api.cancel_booking(ctx["booking"]["id"], make_participant_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_booking(ctx["booking"]["id"])["status"] == "BOOKED", (
        "a forbidden cancel mutates nothing")
