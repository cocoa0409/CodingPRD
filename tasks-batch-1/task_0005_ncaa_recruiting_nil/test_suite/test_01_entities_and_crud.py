"""Entity creation, default-field values, listing pagination, and basic
not-found / invalid-request behavior (PRD §2.2, §2.3, §2.4, §3.1, §3.2).
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_program, assert_student_athlete,
    create_program_payload, create_student_athlete_payload,
    create_nil_deal_payload,
    create_program,
    setup_certified_athlete,
    make_student_athlete_headers,
    TEST_USERS,
)


def test_program_create_returns_201_with_default_computed_fields(api):
    """PRD §3.1: "On creation, the program's `slots_committed` and
    `slots_projected` are both initialized to 0, its `penalty_tier` is
    initialized to `NONE`, and its `version` is set to 1."

    Design: Corner/entities/program_create_returns_201_and_default_computed_fields
    """
    payload = create_program_payload(
        sport_code="FOOTBALL",
        school_name="Greenfield U",
        scholarship_slot_cap=85,
    )
    res = api.create_program(payload, TEST_USERS["compliance_officer_headers"])
    data = validate_success(res, 201)
    assert_program(data)
    assert data["slots_committed"] == 0
    assert data["slots_projected"] == 0
    assert data["penalty_tier"] == "NONE"
    assert data["version"] == 1


def test_student_athlete_default_eligibility_uncertified(api):
    """PRD §3.2: "On creation, the athlete's `eligibility_status` is
    `UNCERTIFIED`, `in_transfer_portal` is `false`, `enrolled_program_id`
    is null, and `version` is 1."

    Design: Corner/entities/student_athlete_default_eligibility_uncertified
    """
    payload = create_student_athlete_payload(
        full_name="Newbie",
        sport_code="FOOTBALL",
        gpa=3.500,
        amateurism_flag=True,
    )
    res = api.create_student_athlete(payload, TEST_USERS["compliance_officer_headers"])
    data = validate_success(res, 201)
    assert_student_athlete(data)
    assert data["eligibility_status"] == "UNCERTIFIED"
    assert data["in_transfer_portal"] is False
    assert data["enrolled_program_id"] is None
    assert data["version"] == 1


def test_program_get_nonexistent_id_returns_not_found(api):
    """PRD §2.7: "if the first identifier in the path does not resolve to
    an existing row, the request is rejected with `ERR_NOT_FOUND` before
    the system attempts to resolve any subsequent identifier."

    Design: Corner/entities/program_get_nonexistent_id_returns_not_found
    """
    res = api.get_program(NON_EXISTENT_UUID, TEST_USERS["compliance_officer_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_nildeal_missing_gross_value_returns_invalid_request(api):
    """PRD §2.6: "and finally, body-shape validation of types and required
    fields (`ERR_INVALID_REQUEST`)."
    PRD §3.5: "A `StudentAthlete` proposes a NIL endorsement deal by
    supplying their own `student_athlete_id` (which must equal `X-User-ID`
    for entity-backed ownership), the sponsor's `brand_name`, the
    `gross_value_cents` of the deal, and an optional `agent_fee_pct`"

    Design: Corner/entities/nildeal_missing_gross_value_returns_invalid_request
    """
    athlete = setup_certified_athlete(sport_code="MBB")
    # gross_value_cents omitted — it is a required input per PRD §3.5.
    payload = {
        "student_athlete_id": athlete["id"],
        "brand_name": "Brand",
        "agent_fee_pct": 0.0,
    }
    res = api.create_nil_deal(payload, make_student_athlete_headers(athlete["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_invalid_enum_sport_code_rejected(api):
    """PRD §3.1: "a `sport_code` (one of `FOOTBALL`, `MBB`, `WBB`,
    `BASEBALL`, or `SOFTBALL`)".
    PRD §2.6: body-shape validation of types and required fields returns
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/invalid_enum_sport_code_rejected
    """
    payload = create_student_athlete_payload(
        full_name="X", sport_code="LACROSSE", gpa=3.000,
    )
    res = api.create_student_athlete(payload, TEST_USERS["compliance_officer_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_programs_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_programs_pagination_envelope
    """
    create_program(sport_code="FOOTBALL", school_name="U1", scholarship_slot_cap=85)
    create_program(sport_code="MBB", school_name="U2", scholarship_slot_cap=13)

    res = api.list_programs(
        TEST_USERS["compliance_officer_headers"],
        params={"limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["has_more"] is True
    assert len(data) == 1


def test_program_immediate_visibility_after_create(api):
    """PRD §3.1: "A `ComplianceOfficer` creates a program by supplying a
    `sport_code` (one of `FOOTBALL`, `MBB`, `WBB`, `BASEBALL`, or
    `SOFTBALL`), a `school_name`, and a `scholarship_slot_cap`."
    PRD §2.4: "`version` (integer): begins at 1 on creation and is
    incremented by 1 on every mutation of the row"

    Design: Corner/consistency_model/immediate_visibility_after_create
    """
    payload = create_program_payload(
        sport_code="SOFTBALL", school_name="Now U", scholarship_slot_cap=12,
    )
    created = validate_success(
        api.create_program(payload, TEST_USERS["compliance_officer_headers"]),
        201,
    )
    assert created["version"] == 1

    read = validate_success(
        api.get_program(created["id"], TEST_USERS["compliance_officer_headers"]),
        200,
    )
    assert read["school_name"] == "Now U"
    assert read["version"] == 1
    assert read["id"] == created["id"]
