"""Studio configuration: members, rooms, teachers, intro offers — creation, defaults,
required-field and enum validation, not-found, listing, and config-side RBAC.

Translates corner-design instances from sections `entities`, `validations`, and `rbac`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    create_member_payload, create_room_payload, create_teacher_payload,
    create_intro_offer_payload,
    create_member, create_room, create_teacher, create_intro_offer,
    NON_EXISTENT_UUID,
)

MGR = TEST_USERS["studio_manager_headers"]


def test_create_member_returns_201_with_defaults(api):
    """PRD §3.1: "A newly registered member starts with `is_new_student` true,
    `lifetime_attended_count` and `no_show_strike_count` and `outstanding_fee_cents` at 0, and
    `account_status` `ACTIVE`."

    Design: Corner/entities/create_member_returns_201_with_defaults
    """
    resp = api.create_member(create_member_payload(email="new@x.com", full_name="Nora"), MGR)
    data = validate_success(resp, 201)
    assert data["is_new_student"] is True
    assert data["account_status"] == "ACTIVE"
    assert data["no_show_strike_count"] == 0


def test_create_room_missing_required_field_returns_invalid_request(api):
    """PRD §3.10: "generic request-body validation — required fields present and field types
    and enum values well-formed — is the last check, reported as `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_room_missing_required_field_returns_invalid_request
    """
    resp = api.create_room({"name": "Roomless", "station_capacity": 4}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_create_room_invalid_enum_room_type(api):
    """PRD §3.10: "generic request-body validation — required fields present and field types
    and enum values well-formed — is the last check, reported as `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_room_invalid_enum_room_type
    """
    resp = api.create_room({"name": "Pool", "room_type": "POOL", "station_capacity": 4}, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_get_member_not_found_returns_404(api):
    """PRD §2.5: "each id in the path is resolved in order, and the first id that does not
    correspond to an existing resource produces `ERR_NOT_FOUND` before any later id or body rule
    is evaluated."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Paginated list-based responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_members_pagination_envelope
    """
    create_member(email="a@x.com", full_name="A")
    create_member(email="b@x.com", full_name="B")
    resp = api.list_members(MGR, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_create_intro_offer_returns_201_active(api):
    """PRD §3.1: "An offer opens in `status` `ACTIVE`; only an `ACTIVE` offer may be redeemed
    into a new `INTRO` entitlement, and a retired offer carries `status` `RETIRED`."

    Design: Corner/entities/create_intro_offer_returns_201_active
    """
    resp = api.create_intro_offer(
        create_intro_offer_payload(name="Two Weeks Unlimited", price_cents=3000,
                                   credits_total=-1, window_days=14),
        MGR,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["window_days"] == 14


def test_new_student_redeems_intro_offer_succeeds(api):
    """PRD §3.3: "Purchasing an `INTRO` entitlement is gated by new-student eligibility,
    evaluated as a single business rule: the buying member must currently have `is_new_student`
    true, the referenced `intro_offer_id` must name an `ACTIVE` `IntroOffer`, and the member must
    not already hold an `INTRO` entitlement (at most one per member)."
    PRD §3.3: "At purchase the entitlement is created in `lifecycle_status` `PENDING` with
    `freeze_status` `UNFROZEN`, and its `cycle_end_utc` is computed as `cycle_start_utc` plus 30
    days."

    Design: Corner/entities/new_student_redeems_intro_offer_succeeds
    """
    api_client.set_clock("2026-02-01T00:00:00Z", MGR)
    offer = create_intro_offer(name="Two Weeks Unlimited", price_cents=3000,
                               credits_total=-1, window_days=14)
    member = create_member(email="nr@x.com", full_name="Nr")
    resp = api.create_entitlement(
        {"member_id": member["id"], "kind": "INTRO", "price_cents": 3000,
         "credits_total": -1, "cycle_start_utc": "2026-02-01T00:00:00Z",
         "intro_offer_id": offer["id"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["intro_offer_id"] == offer["id"]
    assert data["kind"] == "INTRO"
    assert data["lifecycle_status"] == "PENDING"


def test_end_before_start_rejected_on_session_create(api):
    """PRD §3.2: "a `start_utc` and `end_utc` (both ISO 8601 UTC, with `end_utc` required to be
    strictly after `start_utc`, else `ERR_END_BEFORE_START` at HTTP 422)"

    Design: Corner/validations/end_before_start_rejected_on_session_create
    """
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    resp = api.create_class_session(
        {"room_id": room["id"], "teacher_id": teacher["id"], "discipline": "VINYASA",
         "start_utc": "2026-02-20T11:00:00Z", "end_utc": "2026-02-20T10:00:00Z",
         "published_capacity": 10},
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_END_BEFORE_START.value, 422)


def test_capacity_exceeds_room_on_create(api):
    """PRD §3.2: "At creation and at publish, `published_capacity` must not exceed the room's
    `station_capacity`, otherwise the request is rejected with `ERR_CAPACITY_EXCEEDS_ROOM`
    (HTTP 422)."

    Design: Corner/validations/capacity_exceeds_room_on_create
    """
    room = create_room(room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Tara", certifications=["REFORMER"])
    resp = api.create_class_session(
        {"room_id": room["id"], "teacher_id": teacher["id"], "discipline": "REFORMER",
         "start_utc": "2026-02-20T10:00:00Z", "end_utc": "2026-02-20T11:00:00Z",
         "published_capacity": 8},
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDS_ROOM.value, 422)


def test_teacher_not_certified_for_discipline(api):
    """PRD §3.2: "The session's `discipline` must appear among the teacher's `certifications`,
    and the teacher must be active at publish time; a discipline the teacher is not certified
    for, or an inactive teacher, is rejected with `ERR_TEACHER_NOT_CERTIFIED` (HTTP 409)."

    Design: Corner/validations/teacher_not_certified_for_discipline
    """
    api_client.set_clock("2026-02-01T00:00:00Z", MGR)
    room = create_room(room_type="REFORMER", station_capacity=4)
    teacher = create_teacher(full_name="Van", certifications=["VINYASA"])
    resp_create = api.create_class_session(
        {"room_id": room["id"], "teacher_id": teacher["id"], "discipline": "REFORMER",
         "start_utc": "2026-02-20T10:00:00Z", "end_utc": "2026-02-20T11:00:00Z",
         "published_capacity": 4},
        MGR,
    )
    session = validate_success(resp_create, 201)
    resp = api.publish_class_session(session["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_TEACHER_NOT_CERTIFIED.value, 409)


# ---- RBAC config-side ----

def test_member_cannot_create_class_session(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_cannot_create_class_session
    """
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="mc@x.com", full_name="Mc")
    resp = api.create_class_session(
        {"room_id": room["id"], "teacher_id": teacher["id"], "discipline": "VINYASA",
         "start_utc": "2026-02-20T10:00:00Z", "end_utc": "2026-02-20T11:00:00Z",
         "published_capacity": 10},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    member = create_member(email="au@x.com", full_name="Au")
    # Send the request with no X-User-ID / X-User-Role headers at all.
    resp = api.list_member_entitlements(member["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
