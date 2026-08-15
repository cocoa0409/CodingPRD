"""Auth headers, role authorization, ownership, and pagination envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_program,
    create_program_payload,
    draft_application,
    make_applicant_headers,
    register_applicant,
    setup_open_program,
    TEST_USERS,
    api_client,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in
    which they act. A request missing either header, or carrying a role value
    outside the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/calls_missing_header_return_400
    """
    program = create_program()
    # Dispatched with no X-User-ID / X-User-Role headers at all.
    resp = api.get_program(program["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_auth_checked_before_existence(api):
    """PRD §2.6: "1. Header presence and role validity —
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.6: "3. Existence of every referenced resource, path identifiers
    validated left to right and body foreign keys thereafter — the not-found
    family of §2.5."
    PRD §2.6: "A request that fails both a state check and a fiscal check
    therefore reports the state error, and so on down the ladder; lower rungs
    are evaluated only when every higher rung has passed."

    Design: Corner/validations/priority_auth_beats_not_found
    """
    # A read on a nonexistent contract WITHOUT auth headers reports the
    # priority-1 header error, not the priority-3 not-found error.
    resp = api.get_contract(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_applicant_role_cannot_create_program(api):
    """PRD §2.1: "Each write endpoint admits a fixed set of roles (§4); a
    request whose role is not among them is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: creating a program admits only
    ProgramAdmin.

    Design: Corner/validations/applicant_role_cannot_create_program
    """
    applicant = register_applicant(parcel_ids=("P-1",))
    resp = api.create_program(
        create_program_payload(program_name="X"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_applicant_cannot_act_for_other_applicant(api):
    """PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id`
    of the acting Applicant record; ownership checks on any resource that
    references an applicant compare the resource's `applicant_id` foreign-key
    field to `X-User-ID`, and a mismatch is rejected with
    `ERR_APPLICANT_NOT_OWNER` (HTTP 403)." PRD §3.2: "the `applicant_id` —
    which, because the drafter acts in the `Applicant` role, must equal the
    actor's `X-User-ID` or the request fails with `ERR_APPLICANT_NOT_OWNER`".

    Design: Corner/validations/applicant_cannot_touch_others_resources
    """
    ctx = setup_open_program(pools=(("GENERAL", 100000),))
    applicant_a = register_applicant(legal_name="A", parcel_ids=("P-1",))
    applicant_b = register_applicant(legal_name="B", parcel_ids=("P-2",))

    # Applicant B drafting an application in A's name.
    payload = {
        "program_id": ctx["program"]["id"],
        "applicant_id": applicant_a["id"],
        "parcel_id": "P-1",
        "planned_practices": [{"practice_code": "FENCE", "quantity": 10}],
        "self_reported_answers": {},
    }
    resp = api.create_application(payload, make_applicant_headers(applicant_b["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_OWNER)


def test_applications_list_pagination_envelope(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the
    number of items skipped and defaults to 0." and "Paginated list responses
    carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object
    of the response envelope." PRD §2.2: "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/applications_list_pagination_envelope
    """
    ctx = setup_open_program(pools=(("GENERAL", 100000),))
    applicant = register_applicant(parcel_ids=("P-1", "P-2", "P-3"))
    for parcel in ("P-1", "P-2", "P-3"):
        draft_application(
            ctx["program"]["id"], applicant, parcel_id=parcel,
            planned=(("FENCE", 10),), self_reported_answers={},
        )

    resp1 = api.list_applications(
        ADMIN, params={"program_id": ctx["program"]["id"], "limit": 2, "offset": 0}
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["response_type"] == "array"
    assert isinstance(body1["meta"].get("api_request_id"), str)
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    resp2 = api.list_applications(
        ADMIN, params={"program_id": ctx["program"]["id"], "limit": 2, "offset": 2}
    )
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
