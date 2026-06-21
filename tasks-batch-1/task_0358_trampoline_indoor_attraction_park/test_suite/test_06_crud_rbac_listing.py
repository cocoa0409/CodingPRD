"""CRUD creation/defaults/required-fields/not-found, computed minor classification,
enum validation, listing with pagination, duplicate-email uniqueness, pagination
bounds, RBAC forbidden-role / not-resource-owner / unauthenticated.

Translates corner entities / endpoints / errors / rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    is_valid_uuid, NON_EXISTENT_UUID,
    create_park, create_park_with_clock, create_slot, get_slot_version,
    create_adult, create_member,
    create_slot_payload, create_participant_payload, create_member_payload,
    create_jump_pass_payload, create_membership_payload,
    make_member_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# Corner entities — creation, retrieval, listing, not-found, required, defaults
# ─────────────────────────────────────────────────────────────────────
def test_create_slot_returns_201_with_all_fields(api):
    """PRD §3.2: "A freshly created slot starts with zero seats consumed and is `OPEN`."
    PRD §2.4: "The `version` field is an integer that starts at 1".

    POST /park/slots returns 201 with seats_taken 0, status OPEN, version 1.

    Design: Corner/entities/create_slot_returns_201_with_all_fields
    """
    park = create_park()
    slot = validate_success(api.create_slot(create_slot_payload(park["id"], jump_capacity=10,
                                                                base_price_cents=2000), PM), 201)
    assert is_valid_uuid(slot["id"])
    assert slot["seats_taken"] == 0
    assert slot["status"] == "OPEN"
    assert slot["version"] == 1


def test_get_slot_by_id_returns_stored_entity(api):
    """PRD §3.2: "the `jump_capacity` (at least 1 confirmed jumper)".
    PRD §4 (GET /park/slots/{id}): "Read a slot with derived occupancy".

    GET /park/slots/{id} returns the slot with jump_capacity 10.

    Design: Corner/entities/get_slot_by_id_returns_stored_entity
    """
    park = create_park()
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    got = validate_success(api.get_slot(slot["id"], FD), 200)
    assert got["id"] == slot["id"]
    assert got["jump_capacity"] == 10


def test_list_slots_paginated_envelope(api):
    """PRD §2.3: "Every list-based response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Two slots created; GET /park/slots with limit 1 returns one item, total_count 2,
    has_more true.

    Design: Corner/entities/list_slots_paginated_envelope
    """
    park = create_park()
    create_slot(park["id"], starts_at="2026-06-20T10:00:00Z", ends_at="2026-06-20T12:00:00Z")
    create_slot(park["id"], starts_at="2026-06-20T13:00:00Z", ends_at="2026-06-20T15:00:00Z")
    data, meta = validate_paginated(
        api.list_slots(FD, params={"park_id": park["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_slot_not_found_returns_404(api):
    """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` against the first
    identifier that does not resolve to an existing resource".

    GET /park/slots/{non-existent uuid} -> ERR_NOT_FOUND (404).

    Design: Corner/entities/get_slot_not_found_returns_404
    """
    create_park()
    validate_error(api.get_slot(NON_EXISTENT_UUID, FD), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_slot_missing_jump_capacity_returns_validation(api):
    """PRD §2.7: "A request whose body is structurally malformed — a missing required
    field, an unrecognized enum value, a wrong type, or an out-of-range numeric input
    not covered by a more specific rule above — is rejected with the generic
    `ERR_VALIDATION`."

    POST /park/slots without jump_capacity -> ERR_VALIDATION (422).

    Design: Corner/entities/create_slot_missing_jump_capacity_returns_validation
    """
    park = create_park()
    payload = create_slot_payload(park["id"], base_price_cents=2000)
    del payload["jump_capacity"]
    validate_error(api.create_slot(payload, PM), ApiErrorId.ERR_VALIDATION.value)


def test_park_grip_sock_price_default_applied(api):
    """PRD §3.1: "The `grip_sock_price_cents` is the unit price of one mandatory pair of
    grip socks and defaults to 350 cents".
    PRD §3.1: "The `walkin_surcharge_cents` is a flat surcharge added to a walk-in pass
    and defaults to 500 cents".

    POST /park omitting the knobs -> grip_sock_price_cents 350, walkin_surcharge_cents 500.

    Design: Corner/entities/park_grip_sock_price_default_applied
    """
    park = validate_success(api.create_park({"name": "Sky Park"}, PM), 201)
    assert park["grip_sock_price_cents"] == 350
    assert park["walkin_surcharge_cents"] == 500


def test_participant_is_minor_computed_from_birthdate(api):
    """PRD §3.3: "From the birthdate measured against the park's `minor_age_threshold` on
    the current clock, the server pins `is_minor` at creation time; this classification
    is fixed at creation and is not recomputed later."

    A participant born 2016 at clock 2026 (age ~10 < 18) is flagged is_minor true.

    Design: Corner/entities/participant_is_minor_computed_from_birthdate
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    guardian = create_adult(park["id"], full_name="Guardian A")
    kid = validate_success(
        api.create_participant(
            create_participant_payload(park["id"], full_name="Kid K",
                                       birthdate="2016-01-01T00:00:00Z",
                                       guardian_participant_id=guardian["id"]), FD), 201)
    assert kid["is_minor"] is True


def test_jump_pass_invalid_channel_enum_rejected(api):
    """PRD §2.7: "A request whose body is structurally malformed — a missing required
    field, an unrecognized enum value, a wrong type ... — is rejected with the generic
    `ERR_VALIDATION`."

    POST /park/jump-passes with channel 'ONLINE' (not RESERVATION|WALKIN) ->
    ERR_VALIDATION (422).

    Design: Corner/entities/jump_pass_invalid_channel_enum_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Enum J")
    payload = create_jump_pass_payload(slot["id"], participant["id"], get_slot_version(slot["id"]))
    payload["channel"] = "ONLINE"
    validate_error(api.create_jump_pass(payload, FD), ApiErrorId.ERR_VALIDATION.value)


# ─────────────────────────────────────────────────────────────────────
# Corner endpoints / errors
# ─────────────────────────────────────────────────────────────────────
def test_duplicate_member_email_rejected(api):
    """PRD §3.7: "The email must be unique within the park, compared case-insensitively;
    a duplicate is rejected with `ERR_DUPLICATE_EMAIL`."

    A second member with email A@X.COM (case-insensitive duplicate of a@x.com) in the
    same park -> ERR_DUPLICATE_EMAIL (409).

    Design: Corner/endpoints/duplicate_member_email_rejected
    """
    park = create_park()
    validate_success(api.create_member(create_member_payload(park["id"], email="a@x.com",
                                                             full_name="A One"), FD), 201)
    validate_error(
        api.create_member(create_member_payload(park["id"], email="A@X.COM", full_name="A Two"), FD),
        ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A `limit` outside 1 through 100, or a negative `offset`, is rejected
    with `ERR_PAGINATION_INVALID`."

    GET /park/slots with limit 500 (> max 100) -> ERR_PAGINATION_INVALID (400).

    Design: Corner/errors/pagination_limit_over_max_rejected
    """
    park = create_park()
    validate_error(api.list_slots(FD, params={"park_id": park["id"], "limit": 500}),
                   ApiErrorId.ERR_PAGINATION_INVALID.value)


# ─────────────────────────────────────────────────────────────────────
# Corner rbac
# ─────────────────────────────────────────────────────────────────────
def test_member_cannot_close_slot(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /park/slots/{id}/close is authorized for ParkManager only.

    A Member calling POST /park/slots/{id}/close -> ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/member_cannot_close_slot
    """
    park = create_park()
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    member = create_member(park["id"], email="rb@x.com", full_name="RB M")
    validate_error(api.close_slot(slot["id"], make_member_headers(member["id"])),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_frontdesk_cannot_sign_off_incident(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /park/incidents/{id}/sign-off is authorized for ParkManager only.

    FrontDesk calling POST /park/incidents/{id}/sign-off on a reviewed incident ->
    ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/frontdesk_cannot_sign_off_incident
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="RB J")
    from test_helpers import sign_waiver, create_jump_pass
    sign_waiver(participant["id"], participant["id"], signature_text="RB J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    inc = validate_success(
        api.create_incident({"park_id": park["id"], "jump_pass_id": pas["id"],
                             "severity": "MINOR", "narrative": "bump"}, FD), 201)
    validate_success(api.review_incident(inc["id"], PM), 200)
    validate_error(api.sign_off_incident(inc["id"], FD), ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_member_cancel_other_members_membership_denied(api):
    """PRD §2.1: "A `Member` acting on a membership or reservation that it does not own is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Member B cancelling Member A's membership (X-User-ID != owning Member.id) ->
    ERR_NOT_RESOURCE_OWNER (403).

    Design: Corner/rbac/member_cancel_other_members_membership_denied
    """
    park = create_park_with_clock("2026-06-01T00:00:00Z")
    member_a = create_member(park["id"], email="a@x.com", full_name="Mem A")
    member_b = create_member(park["id"], email="b@x.com", full_name="Mem B")
    membership_a = validate_success(
        api.create_membership(create_membership_payload(member_a["id"], tier="BRONZE",
                                                        cycle_anchor_at="2026-06-01T00:00:00Z"),
                              make_member_headers(member_a["id"])), 201)
    validate_error(
        api.cancel_membership(membership_a["id"], make_member_headers(member_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "When either header is missing, malformed, or names an unrecognized
    role, the request is rejected with `ERR_UNAUTHENTICATED`."

    A protected GET with no auth headers -> ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    park = create_park()
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    validate_error(api.get_slot(slot["id"], {}), ApiErrorId.ERR_UNAUTHENTICATED.value)
