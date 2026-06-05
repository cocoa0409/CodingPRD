"""Student registration and its derived profile, listing/pagination, reverse
reachability of goals, and the access-control surface (role denial, unauthenticated)
— PRD §3.1, §2.1, §2.3, §2.6.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_admin_headers,
    make_case_manager_headers,
    make_parent_headers,
    make_headers,
    create_student_payload,
    set_clock,
    create_student,
    make_goal_on_eligible_student,
)

ADMIN = make_admin_headers("adm_1")
CM = make_case_manager_headers("cm_1")
PAR = make_parent_headers("par_1")


class TestStudentCreation:
    def test_create_student_defaults(self, api):
        """PRD §3.1: "A newly registered student has an eligibility status of `NOT_EVALUATED`."
        PRD §3.1: "The `disability_category ... is null while the student is `NOT_EVALUATED` or `INELIGIBLE"
        PRD §3.1: "The `active_iep_id ... is null when no program is on"

        A fresh student returns 201 with eligibility_status NOT_EVALUATED,
        disability_category null, active_iep_id null, version 1.

        Design: Corner/entities/create_student_returns_201_with_defaults
        """
        set_clock("2026-03-01T09:00:00Z")
        stu = validate_success(
            api.create_student(
                create_student_payload(full_name="Quinn Ash",
                                       date_of_birth="2015-01-01", grade_level=3),
                ADMIN,
            ),
            201,
        )
        assert stu["eligibility_status"] == "NOT_EVALUATED", stu["eligibility_status"]
        assert stu["disability_category"] is None, stu["disability_category"]
        assert stu["active_iep_id"] is None, stu["active_iep_id"]
        assert stu["version"] == 1, stu["version"]

    def test_get_student_not_found(self, api):
        """PRD §2.6: "When a path names a resource that does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/get_student_not_found_returns_404
        """
        validate_error(
            api.get_student("00000000-0000-4000-8000-000000000000", ADMIN),
            ApiErrorId.ERR_NOT_FOUND.value,
        )

    def test_create_student_missing_date_of_birth(self, api):
        """PRD §2.8: "required fields must be present and well-typed ...
        (`ERR_INVALID_REQUEST`)"
        PRD §3.1: "A `SpecialEdAdmin` registers a student by supplying the student's legal name in `full_name`, a `date_of_birth` as an ISO 8601 date, and a `grade_level` integer."

        Omitting the required date_of_birth → ERR_INVALID_REQUEST (400).

        Design: Corner/entities/create_student_missing_required_field_returns_invalid_request
        """
        validate_error(
            api.create_student({"full_name": "No DOB", "grade_level": 3}, ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )


class TestStudentListing:
    def test_list_students_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."
        PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        With two students and limit=1, the array carries one item, total_count is 2,
        and has_more is true.

        Design: Corner/endpoints/list_students_pagination_envelope
        """
        set_clock("2026-03-01T09:00:00Z")
        create_student(set_clock_first=False, full_name="S One",
                       date_of_birth="2014-01-01", grade_level=6)
        create_student(set_clock_first=False, full_name="S Two",
                       date_of_birth="2014-02-02", grade_level=6)
        data, meta = validate_paginated(api.list_students(ADMIN, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is True, meta
        assert len(data) == 1, data

    def test_list_goals_reverse_reachability_by_iep(self, api):
        """PRD §3.6: "Goals may be listed (filterable by `iep_id` and by `status`) and fetched individually"

        After creating exactly one goal on one IEP, GET /goals returns that single
        goal — the reverse-reachability listing for Goal.iep_id.

        Design: Corner/endpoints/list_iep_goals_reverse_reachability
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep, goal = make_goal_on_eligible_student(
            student_overrides={"full_name": "Ed Fern", "date_of_birth": "2014-03-03"},
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 100},
        )
        data, _meta = validate_paginated(api.list_goals(CM, params={"iep_id": iep["id"]}))
        assert len(data) == 1, data
        assert data[0]["id"] == goal["id"], data


class TestAccessControl:
    def test_parent_cannot_register_student(self, api):
        """PRD §2.1: "When a request carries a recognized role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /students is authorized for SpecialEdAdmin only.

        Design: Corner/rbac/parent_cannot_register_student
        """
        validate_error(
            api.create_student(
                create_student_payload(full_name="X", date_of_birth="2014-01-01",
                                       grade_level=6),
                PAR,
            ),
            ApiErrorId.ERR_FORBIDDEN.value,
        )

    def test_unknown_role_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which that user is acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        A request bearing an unrecognized role (Intruder) → ERR_UNAUTHENTICATED.

        Design: Corner/rbac/missing_headers_unauthenticated
        """
        intruder = make_headers("intr_1", "Intruder")
        validate_error(
            api.get_student("00000000-0000-4000-8000-000000000000", intruder),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
