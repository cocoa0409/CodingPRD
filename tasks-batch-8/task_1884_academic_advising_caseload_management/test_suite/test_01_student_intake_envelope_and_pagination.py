"""Student intake, response-envelope, pagination and immediate-consistency claims."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_student,
    create_student,
    create_student_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_student_creation_applies_defaults_and_computed(api, director_headers):
    """PRD §3.2: "An optional `advising_required_flag` declares whether an advising session is required before registration; it defaults to false."
    PRD §3.2: "A newly created student starts with `care_status` set to `ENROLLED`, with `enrolled_term_codes` seeded to contain exactly the initial term, and with the four derived fields — `at_risk_score`, `risk_tier`, `advising_requirement_status`, and `registration_clearance` — computed immediately."
    PRD §3.2: "The base comes from the student's GPA band: 40 points when `gpa` is below 2.0, 25 points when it is at least 2.0 but below 2.5, and 10 points when it is 2.5 or higher."
    PRD §3.8: "`advising_requirement_status` is `NOT_REQUIRED` when `advising_required_flag` is false; otherwise it is `SATISFIED` when a `COMPLETED` appointment exists for the student in the student's `current_term_code`, and `REQUIRED` when none does."
    PRD §3.8: "`registration_clearance` is `BLOCKED` whenever any of the student's holds is `ACTIVE`; failing that, it is `BLOCKED` when the advising requirement is `REQUIRED`; otherwise it is `CLEARED`."

    Design: Corner/entities/student_creation_applies_defaults_and_computed
    """
    res = api.create_student(
        create_student_payload(
            full_name="E1", email="e1@x.edu", major_code="CS",
            cohort_year=2026, current_term_code="FA26", gpa=3.5,
        ),
        director_headers,
    )
    student = validate_success(res, 201)
    assert_student(student)
    assert student["advising_required_flag"] is False
    assert student["care_status"] == "ENROLLED"
    assert student["at_risk_score"] == 10, "gpa 3.5 >= 2.5 -> base 10, no other inputs"
    assert student["risk_tier"] == "LOW"
    assert student["advising_requirement_status"] == "NOT_REQUIRED"
    assert student["registration_clearance"] == "CLEARED"
    assert student["enrolled_term_codes"] == ["FA26"]
    assert student["no_show_count"] == 0


def test_student_missing_required_gpa_returns_validation(api, director_headers):
    """PRD §2.10 step 2: "Required input fields must be present, enum values must be in their declared domains, datetimes must parse, `gpa` must lie between 0.0 and 4.0 inclusive, `max_caseload` must be at least 1, and an appointment slot must end strictly after it starts with a duration between 15 and 60 minutes inclusive. Violations yield `ERR_VALIDATION`, or `ERR_INVALID_APPOINTMENT_DURATION` for the duration rule (both HTTP 400)."
    PRD §3.2: "Registration of a student — performed by an `AdvisingDirector` or a `FrontDeskStaff` operator — captures `full_name`, `email`, the declared `major_code`, the entry `cohort_year`, the student's `current_term_code` (a term code such as FA26), and `gpa`, which must lie between 0.0 and 4.0 inclusive (`ERR_VALIDATION` otherwise)."

    Design: Corner/entities/student_missing_required_gpa_returns_validation
    """
    payload = create_student_payload(
        full_name="E2", email="e2@x.edu", major_code="CS",
        cohort_year=2026, current_term_code="FA26",
    )
    del payload["gpa"]
    res = api.create_student(payload, director_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_advisor_get_not_found_returns_404(api, director_headers):
    """PRD §2.10 step 4: "Path identifiers are validated left to right, then body-referenced identifiers such as `student_id`, `advisor_id`, and `referral_id`. The first miss produces the matching 404: `ERR_STUDENT_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND`."

    Design: Corner/entities/advisor_get_not_found_returns_404
    """
    res = api.get_advisor(NON_EXISTENT_UUID, director_headers)
    validate_error(res, ApiErrorId.ERR_ADVISOR_NOT_FOUND)


def test_student_patch_term_change_appends_enrolled_terms(api, director_headers):
    """PRD §3.2: "When the term changes while the student is `ENROLLED` and the new term is not yet listed, the system appends it to `enrolled_term_codes`, building the enrollment history that retention reporting later reads; a `gpa` change recomputes the score and tier."
    PRD §3.2: "Every such student update increments the student's `version` by 1."

    Design: Corner/entities/student_patch_term_change_appends_enrolled_terms
    """
    student = create_student(full_name="E4", email="e4@x.edu")
    created_version = student["version"]
    res = api.update_student(student["id"], {"current_term_code": "SP27"}, director_headers)
    updated = validate_success(res, 200)
    assert updated["enrolled_term_codes"] == ["FA26", "SP27"]
    assert updated["version"] == created_version + 1, (
        "a student update increments version by 1 (PRD §3.2)"
    )


def test_create_student_response_envelope_shape(api, director_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix."
    PRD §4: "Endpoints that create a new resource return a `201 Created` status code."

    Design: Corner/endpoints/create_student_response_envelope_shape
    """
    res = api.create_student(
        create_student_payload(full_name="L4", email="l4@x.edu"), director_headers
    )
    assert res.status_code == 201, f"create must return 201, got {res.status_code}"
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    data = validate_success(res, 201)
    assert is_valid_uuid(data["id"]), "server-minted id must be a UUID"


def test_students_list_pagination_defaults(api, director_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/students_list_pagination_defaults
    """
    for i in (1, 2, 3):
        create_student(full_name=f"L{i}", email=f"l{i}@x.edu")

    res = api.list_students(director_headers, params={"limit": 2})
    data, meta = validate_paginated(res)
    assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["response_type"] == "array"


def test_mutation_immediately_visible_in_response(api, director_headers):
    """PRD §2.7: "All of these are recomputed eagerly whenever a triggering event occurs, and the consistency model is immediate: a mutation and every recomputation it triggers are committed together and are visible in that mutation's own response."
    PRD §3.2: "The base comes from the student's GPA band: 40 points when `gpa` is below 2.0, 25 points when it is at least 2.0 but below 2.5, and 10 points when it is 2.5 or higher."

    Design: Corner/consistency_model/mutation_immediately_visible_in_response
    """
    res = api.create_student(
        create_student_payload(full_name="IM1", email="im1@x.edu", gpa=2.2),
        director_headers,
    )
    student = validate_success(res, 201)
    assert student["at_risk_score"] == 25, "2.0 <= gpa 2.2 < 2.5 -> base 25"
    assert student["risk_tier"] == "LOW", "25 < 40 -> LOW"
