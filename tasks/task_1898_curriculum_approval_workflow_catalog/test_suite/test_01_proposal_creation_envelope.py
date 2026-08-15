"""Proposal creation, read surface, response envelope, and the decision log.

Covers body validation at creation (missing required field, bad enum),
system-managed identity copying, 404 resolution, pagination envelope shape,
the append-only decision record shape, and the authentication gate.
"""
from test_helpers import (
    ApiErrorId,
    assert_decision_record,
    assert_proposal,
    create_department,
    create_new_course_proposal,
    create_term,
    create_submitted_new_course_proposal,
    make_proposer_headers,
    make_registrar_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT_PROPOSAL_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def _new_course_draft_payload(dept_id, term_id, course_number="450"):
    return {
        "proposal_type": "NEW_COURSE",
        "proposer_department_id": dept_id,
        "requested_effective_term_id": term_id,
        "proposed_subject_code": "CS",
        "proposed_course_number": course_number,
        "proposed_title": "Compilers",
        "proposed_credit_hours": 3,
        "contact_hours_per_week": 3,
        "out_of_class_hours_per_week": 6,
        "learning_outcomes": ["build a compiler"],
        "justification": "curriculum gap",
    }


def test_create_proposal_missing_required_field_rejected(api):
    """PRD §3.3: "A `FacultyProposer` creates a proposal in `DRAFT` status by
    supplying the `proposal_type`, the sponsoring `proposer_department_id`, and
    the `requested_effective_term_id` naming the term the proposer asks the
    change to take effect in."
    PRD §2.8: "fourth, request-body shape and completeness, including
    type-specific submit completeness, date ordering, array length, and
    foreign-key existence (`ERR_VALIDATION`)".

    Design: Corner/entities/create_proposal_missing_required_field_rejected
    """
    dept = create_department()
    term = create_term()

    resp = api.create_proposal(
        {"proposer_department_id": dept["id"],
         "requested_effective_term_id": term["id"]},
        make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)

    data, meta = validate_paginated(
        api.list_proposals(make_registrar_headers()))
    assert data == [], "nothing may be persisted by a rejected creation"
    assert meta["total_count"] == 0


def test_create_proposal_invalid_enum_rejected(api):
    """PRD §3.3: "The **Proposal** is the vehicle for every curriculum change,
    and its `proposal_type` is one of `NEW_COURSE`, `COURSE_CHANGE`, or
    `DEACTIVATION`."
    PRD §2.8: "fourth, request-body shape and completeness, including
    type-specific submit completeness, date ordering, array length, and
    foreign-key existence (`ERR_VALIDATION`)".

    Design: Corner/entities/create_proposal_invalid_enum_rejected
    """
    dept = create_department()
    term = create_term()

    payload = _new_course_draft_payload(dept["id"], term["id"])
    payload["proposal_type"] = "NEW_PROGRAM"
    resp = api.create_proposal(payload, make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_proposal_create_copies_proposer_identity(api):
    """PRD §3.3: "At creation the server copies the caller's `X-User-ID` into
    `proposer_id`, which becomes the ownership anchor for all later author
    operations."
    PRD §3.3: "A `FacultyProposer` creates a proposal in `DRAFT` status by
    supplying the `proposal_type`, the sponsoring `proposer_department_id`, and
    the `requested_effective_term_id` naming the term the proposer asks the
    change to take effect in."

    Design: Corner/entities/proposal_create_copies_proposer_identity
    """
    dept = create_department()
    term = create_term()

    resp = api.create_proposal(
        _new_course_draft_payload(dept["id"], term["id"]),
        make_proposer_headers("fac-001"))
    data = validate_success(resp, 201)
    assert_proposal(data)
    assert data["proposer_id"] == "fac-001", (
        "proposer_id is copied from X-User-ID, not from the body")
    assert data["status"] == "DRAFT"
    assert data["version"] == 1, "a newly created proposal starts at version 1"


def test_get_proposal_not_found_returns_404(api):
    """PRD §2.7: "Each templated identifier is resolved in turn, and the
    request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not resolve to an existing resource; later
    segments are never consulted."

    Design: Corner/entities/get_proposal_not_found_returns_404
    """
    resp = api.get_proposal(NON_EXISTENT_PROPOSAL_ID, make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_proposals_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, accepts a minimum of 1, and is bounded above at 100. The
    `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` envelope of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_proposals_pagination_envelope
    """
    dept = create_department()
    term = create_term()
    for number in ("450", "451", "452"):
        create_new_course_proposal(dept["id"], term["id"], number)

    page1, meta1 = validate_paginated(
        api.list_proposals(make_registrar_headers(),
                           params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_proposals(make_registrar_headers(),
                           params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    body = api.list_proposals(make_registrar_headers()).json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_decision_record_immutable_shape(api):
    """PRD §2.4: "A `DecisionRecord` is an append-only audit entry carrying
    only `id` and `created_at` from the common set; both `updated_at` and
    `version` are absent on decision records, because an audit row, once
    written, is never modified."
    PRD §3.4: "A `DecisionRecord` with action `SUBMIT` is appended, capturing
    `from_status` `DRAFT` (or `RETURNED`) and `to_status` `DEPT_REVIEW`, and
    the proposal's `version` increments."

    Design: Corner/entities/decision_record_immutable_shape
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"], "450")

    data, meta = validate_paginated(
        api.list_decisions(proposal["id"], make_registrar_headers()))
    assert meta["total_count"] == 1
    record = data[0]
    assert_decision_record(record)
    assert record["action"] == "SUBMIT"
    assert record["from_status"] == "DRAFT"
    assert record["to_status"] == "DEPT_REVIEW"
    assert record["proposal_id"] == proposal["id"]
    assert record["actor_role"] == "FacultyProposer"
    assert record["actor_id"] == "fac-001"
    assert record["recorded_term_id"] is None, (
        "recorded_term_id is a denormalized audit copy supplied only with "
        "approve and reassign actions")


def test_list_proposals_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role string
    outside the five declared roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/list_proposals_unauthenticated
    """
    resp = api.list_proposals(headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
