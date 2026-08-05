"""Baseline CRUD, defaults, not-found, pagination, and role/ownership/presiding
authorization (PRD §2.1, §2.3, §2.5, §3.1, §3.4)."""
from test_helpers import (
    validate_success, validate_paginated, validate_error, ApiErrorId,
    NON_EXISTENT_UUID, assert_public_body,
    create_public_body_payload, create_records_request_payload,
    create_agenda_item_payload, register_requester, create_body,
    make_requester_headers, make_body_member_headers, TEST_USERS,
    setup_scheduled_meeting, setup_noticed_meeting, setup_records_request,
    get_success_data,
)

CLERK = TEST_USERS["clerk_headers"]


def test_create_public_body_returns_201_with_fields(api):
    """PRD §3.1: "a `seat_count` of at least 1 giving the total authorized voting
    seats, and a `quorum_size` giving the minimum members that must be present to
    convene."
    PRD §2.4: "The `version` begins at 1 on creation and increases by exactly 1 on
    every mutation of the resource".

    Design: Corner/entities/create_public_body_returns_201_with_fields
    """
    data = validate_success(api.create_public_body(
        create_public_body_payload(name="Town Board", jurisdiction_state="VT",
                                   seat_count=7, quorum_size=4), CLERK), 201)
    assert_public_body(data)
    assert data["seat_count"] == 7
    assert data["quorum_size"] == 4
    assert data["version"] == 1


def test_get_nonexistent_meeting_returns_not_found(api):
    """PRD §2.5: "the server validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_meeting_nonexistent_returns_not_found
    """
    resp = api.get_meeting(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_records_request_missing_subject_rejected(api):
    """PRD §3.7: "the `body_id`, a `subject`, a `description` of the records sought,
    and an `estimated_page_count` of at least 0."
    PRD §2.10: "request-body well-formedness — required fields present, enums valid,
    numeric ranges honored".

    Design: Corner/entities/create_records_request_missing_required_returns_validation
    """
    requester = register_requester(api, "Ann", "ann@example.com")
    body = create_body(api)
    payload = create_records_request_payload(requester["id"], body["id"])
    del payload["subject"]
    resp = api.create_records_request(payload, make_requester_headers(requester["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_agenda_item_defaults_applied(api):
    """PRD §3.4: "an `item_type` of `ACTION`, `DISCUSSION`, or `CONSENT` (defaulting
    to `DISCUSSION`), and a `public_comment_enabled` flag (defaulting to true)".

    Design: Corner/entities/agenda_item_defaults_applied
    """
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=5,
                                  quorum_size=2, num_members=1)
    item = validate_success(api.create_agenda_item(
        ctx["meeting"]["id"], create_agenda_item_payload(title="Default item", sequence=1),
        CLERK), 201)
    assert item["item_type"] == "DISCUSSION"
    assert item["public_comment_enabled"] is True


def test_requester_cannot_create_public_body(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the
    target operation is rejected with `ERR_UNAUTHORIZED`." (POST /public-bodies is
    Clerk-only per §4.)

    Design: Corner/rbac/requester_cannot_create_public_body_unauthorized
    """
    requester = register_requester(api, "Cy", "cy@example.com")
    resp = api.create_public_body(
        create_public_body_payload(name="Sneaky", jurisdiction_state="ND"),
        make_requester_headers(requester["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_other_requester_cannot_withdraw(api):
    """PRD §3.8: "A requester may withdraw their own request (ownership enforced,
    else `ERR_NOT_RESOURCE_OWNER`)".

    Design: Corner/rbac/other_requester_cannot_withdraw_not_owner
    """
    ctx = setup_records_request(api, requester_name="Eve", requester_email="eve@example.com")
    other = register_requester(api, "Fox", "fox@example.com")
    resp = api.transition_records_request(
        ctx["request"]["id"], {"to_status": "WITHDRAWN"},
        make_requester_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_nonpresiding_member_cannot_convene(api):
    """PRD §3.3: "the acting member's `X-User-ID` must equal the meeting's
    `presiding_member_id`, else `ERR_NOT_PRESIDING_OFFICER`".

    Design: Corner/rbac/nonpresiding_member_cannot_convene
    """
    ctx = setup_noticed_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                quorum_size=2, num_members=2)
    non_presiding = ctx["members"][1]["id"]
    present = [m["id"] for m in ctx["members"]]
    resp = api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "IN_SESSION", "present_member_ids": present},
        make_body_member_headers(non_presiding))
    validate_error(resp, ApiErrorId.ERR_NOT_PRESIDING_OFFICER.value)


def test_list_meetings_returns_paginated_array(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object."

    Design: Corner/endpoints/list_meetings_returns_paginated_array
    """
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                  quorum_size=1, num_members=1)
    data, meta = validate_paginated(api.list_meetings(ctx["body"]["id"], CLERK))
    assert len(data) == 1
    assert "total_count" in meta
    assert "has_more" in meta
