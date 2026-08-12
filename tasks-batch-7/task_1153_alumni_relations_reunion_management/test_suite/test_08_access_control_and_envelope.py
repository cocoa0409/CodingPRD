"""Authentication, authorization, ownership checks, and the error envelope
(PRD §2.1, §2.2, §3.3)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    create_record,
    create_event,
    create_committee,
    invite_member,
    TEST_USERS,
    make_alumni_headers,
    make_committee_volunteer_headers,
)

STAFF = TEST_USERS["staff_headers"]


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing either header, presenting an
    `X-User-Role` value that is not one of the declared roles, or omitting
    `X-User-ID` where the role is entity-backed, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api.create_record(
        {"full_name": "X", "primary_email": "x@x.com", "class_year": 2000,
         "degree_code": "BA"},
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_response_envelope_error_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`" and the data object carries
    "`error_id`" and "`message`", with `response_type` of "error".

    Design: Corner/endpoints/response_envelope_error_shape
    """
    resp = api.get_event(NON_EXISTENT_UUID, STAFF)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()

    body = resp.json()
    assert body["response_type"] == "error"
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_alumni_cannot_create_event(api):
    """PRD §2.1: "Once authenticated, the role is checked against the
    endpoint's authorization list; a role not permitted for the endpoint —
    or an actor failing an ownership check where one is required — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)." The §4 table limits event
    creation to `AlumniRelationsStaff` and `AlumniRelationsDirector`.

    Design: Corner/rbac/alumni_cannot_create_event
    """
    alum = create_record(full_name="RA", primary_email="ra@x.com")
    resp = api.create_event(
        {"class_year": 2001, "title": "R", "event_date": "2026-09-01T18:00:00Z",
         "committee_quorum_required": 1},
        make_alumni_headers(alum["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_staff_cannot_clear_do_not_contact(api):
    """PRD §2.1: "`AlumniRelationsDirector` is the head of alumni relations
    and holds a superset of staff capabilities plus the override-only
    operations: clearing a do-not-contact flag ...". A staff attempt is "a
    role not permitted for the endpoint" and "is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)".

    Design: Corner/rbac/staff_cannot_clear_do_not_contact
    """
    record = create_record(full_name="DNC", primary_email="dnc@x.com")
    validate_success(api.set_do_not_contact(record["id"], STAFF))

    resp = api.clear_do_not_contact(record["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_volunteer_cannot_accept_others_membership(api):
    """PRD §3.3: "Acceptance is personal: a `CommitteeVolunteer` accepts
    their own invitation, meaning the acting user's `AlumniRecord` `id` must
    equal the membership's `alumni_id` or the request fails as
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/volunteer_cannot_accept_others_membership
    """
    v1 = create_record(full_name="V1", primary_email="v1@x.com")
    v2 = create_record(full_name="V2", primary_email="v2@x.com")
    event = create_event()
    committee = create_committee(event["id"])
    membership = invite_member(committee["id"], v1["id"], role="MEMBER")

    resp = api.accept_membership(
        membership["id"], make_committee_volunteer_headers(v2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    row = validate_success(api.get_membership(membership["id"], STAFF))
    assert row["status"] == "INVITED"
