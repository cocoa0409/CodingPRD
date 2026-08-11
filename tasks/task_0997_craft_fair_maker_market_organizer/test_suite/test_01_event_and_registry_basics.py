"""Event creation defaults, registry rules, pagination, and auth/RBAC gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_vendor_headers, make_juror_headers,
    assert_maker_event, assert_vendor_profile,
    create_maker_event_payload, create_booth_zone_payload,
    create_vendor_profile_payload, create_decide_payload,
    reset_clock, create_event, create_vendor, open_applications,
    create_application,
)


def test_maker_event_creation_returns_201_and_defaults(api, coordinator_headers):
    """PRD §3.1: "A new event's `posture` is `PLANNING`."
    PRD §3.1: "The event's `weather_flag` may optionally be supplied at creation and
    defaults to `CLEAR`; its recognized values are `CLEAR`, `ADVISORY`, and `SEVERE`."
    PRD §4: "Throughout the API, operations that create a new resource — an event, a
    zone, a booth, a vendor profile, an application, a jury score, a load slot, a
    ticket, a sales ledger entry — return `201 Created`."

    Design: Corner/entities/maker_event_creation_returns_201_and_defaults
    """
    reset_clock()
    res = api.create_maker_event(
        create_maker_event_payload(name="Default Fair", venue_capacity=50),
        coordinator_headers,
    )
    event = validate_success(res, 201)
    assert_maker_event(event)
    assert event["posture"] == "PLANNING", (
        f"new event posture must be PLANNING, got {event['posture']}"
    )
    assert event["weather_flag"] == "CLEAR", (
        f"weather_flag must default to CLEAR, got {event['weather_flag']}"
    )


def test_maker_event_get_not_found_returns_404(api, coordinator_headers):
    """PRD §2.4: "These two gates sit below authentication and existence checks in
    the evaluation order: a missing or malformed header surfaces as `ERR_MISSING_AUTH`
    before anything else, an unauthorized role as `ERR_FORBIDDEN` next, a nonexistent
    path resource as `ERR_NOT_FOUND` after that, and only then do the posture gate and
    the per-entity state gate apply, in that order."

    Design: Corner/entities/maker_event_get_not_found_returns_404
    """
    reset_clock()
    res = api.get_maker_event(NON_EXISTENT_UUID, coordinator_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_vendor_profile_email_uniqueness_enforced(api, platform_admin_headers):
    """PRD §3.1: "The contact email is unique across all vendors — a duplicate
    registration is rejected with `ERR_EMAIL_TAKEN` — and a new vendor's `status`
    is `ACTIVE`."

    Design: Corner/entities/vendor_profile_email_uniqueness_enforced
    """
    first = validate_success(
        api.create_vendor_profile(
            create_vendor_profile_payload(display_name="V1", contact_email="dup@x.com"),
            platform_admin_headers,
        ),
        201,
    )
    assert_vendor_profile(first)
    assert first["status"] == "ACTIVE"

    res = api.create_vendor_profile(
        create_vendor_profile_payload(display_name="V2", contact_email="dup@x.com",
                                      home_region="OR"),
        platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_EMAIL_TAKEN, expected_status=409)


def test_maker_event_list_returns_paginated(api, coordinator_headers):
    """PRD §2.3: "List responses carry four pagination fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter sets the maximum number of items returned; when
    omitted it defaults to 10, and it is bounded below by 1 and above by 100."

    Design: Corner/entities/maker_event_list_returns_paginated
    """
    reset_clock()
    create_event(coordinator_headers, name="E1")
    create_event(coordinator_headers, name="E2",
                 opens_at="2026-07-01T09:00:00Z", closes_at="2026-07-01T18:00:00Z")

    data, meta = validate_paginated(
        api.list_maker_events(coordinator_headers, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert len(data) == 1, f"limit=1 must return exactly one event, got {len(data)}"
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is
    rejected with `ERR_MISSING_AUTH`."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    reset_clock()
    res = api.list_maker_events(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH, expected_status=400)


def test_forbidden_role_returns_403(api, platform_admin_headers):
    """PRD §2.1: "A request whose role is not authorized for the attempted operation
    is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST `/maker-events` is authorized for EventCoordinator only.

    Design: Corner/validations/forbidden_role_returns_403
    """
    vendor = create_vendor()
    res = api.create_maker_event(
        create_maker_event_payload(name="V"),
        make_vendor_headers(vendor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_juror_cannot_create_booth_zone(api, coordinator_headers):
    """PRD §2.1: "A request whose role is not authorized for the attempted operation
    is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST `/maker-events/{event_id}/booth-zones` is authorized for
    EventCoordinator only.

    Design: Corner/rbac/juror_cannot_create_booth_zone
    """
    reset_clock()
    event = create_event(coordinator_headers, name="R")
    res = api.create_booth_zone(
        event["id"],
        create_booth_zone_payload(label="X", category_cap=1),
        make_juror_headers("juror-1"),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_treasurer_cannot_decide_application(api, coordinator_headers,
                                             treasurer_headers):
    """PRD §2.1: "A request whose role is not authorized for the attempted operation
    is rejected with `ERR_FORBIDDEN`."
    PRD §4: POST `/maker-events/{event_id}/applications/{app_id}/decide` is authorized
    for EventCoordinator only.

    Design: Corner/rbac/treasurer_cannot_decide_application
    """
    reset_clock()
    event = create_event(coordinator_headers, name="RBAC")
    vendor = create_vendor()
    open_applications(event["id"], coordinator_headers)
    app = create_application(event["id"], vendor)
    version = validate_success(
        api.get_maker_event(event["id"], treasurer_headers), 200
    )["version"]
    res = api.decide_application(
        event["id"], app["id"],
        create_decide_payload("APPROVE", version),
        treasurer_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
