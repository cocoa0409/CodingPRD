"""Member registration and listing; membership-cycle creation guards."""
from test_helpers import (
    ApiErrorId,
    add_member,
    api_client,
    assert_cycle,
    assert_member,
    create_active_chapter,
    create_cycle,
    create_cycle_payload,
    create_member_payload,
    open_cycle_nominations,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestMemberRegistration:
    def test_member_create_missing_student_id_rejected(self):
        """PRD section 3.2: "The advisor — or the activities director —
        registers each prospective member with the school-issued `student_id`,
        the student's `full_name` and `email`, a `grade_level` of 9, 10, 11,
        or 12, and both grade point averages: `weighted_gpa` on the 5.0 scale
        and `unweighted_gpa` on the 4.0 scale, each carried to two decimal
        places."
        PRD section 2.6: "Independently of all of the above, a malformed request
        payload or a missing required field is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/member_create_required_field_validation
        """
        set_clock()
        chapter = create_active_chapter()
        payload = create_member_payload()
        del payload["student_id"]
        resp = api_client.create_member(chapter["id"], payload, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_member_create_computed_fields_start_at_zero(self):
        """PRD section 3.2: "A newly registered student begins in `PROSPECTIVE`
        status, unattached to any cycle, with `inducted_cycle_id` null; as noted
        in §3.3, such a member's `good_standing` starts false."
        PRD section 3.4: "An `is_officer` flag is true exactly when the member
        holds at least one role in `ACTIVE`."
        PRD section 3.7: "their `probation_strikes` — the count of their
        `RESOLVED` cases bearing a confirmed outcome".

        Design: Corner/entities/member_computed_fields_system_generated
        """
        set_clock()
        chapter = create_active_chapter()
        resp = api_client.create_member(chapter["id"], create_member_payload(),
                                        ADVISOR)
        data = validate_success(resp, expected_status=201)
        assert_member(data)
        assert data["status"] == "PROSPECTIVE"
        assert data["is_officer"] is False
        assert data["probation_strikes"] == 0
        assert data["good_standing"] is False

    def test_member_create_then_get_immediately_visible(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."
        PRD section 4: "GET | `/chapters/{chapterId}/members/{memberId}` |
        Fetch a member".

        Design: Corner/consistency_model/immediate_visibility_of_member_creation
        """
        set_clock()
        chapter = create_active_chapter()
        created = add_member(chapter["id"], full_name="Immediate Ivy")
        resp = api_client.get_member(chapter["id"], created["id"], ADVISOR)
        data = validate_success(resp)
        assert_member(data)
        assert data["id"] == created["id"]
        assert data["full_name"] == "Immediate Ivy"
        assert data["status"] == "PROSPECTIVE"


class TestMemberListing:
    def test_members_pagination_with_status_filter(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10 when omitted, accepts a minimum of 1, and
        is bounded above at 100."
        PRD section 2.3: "A filter parameter restricts the result set to
        resources whose corresponding field equals the supplied value."

        Design: Corner/cross_cutting_complexity_layers/pagination_with_status_filter
        """
        set_clock()
        chapter = create_active_chapter()
        add_member(chapter["id"])
        add_member(chapter["id"])
        resp = api_client.list_members(
            chapter["id"], ADVISOR,
            params={"status": "PROSPECTIVE", "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["status"] == "PROSPECTIVE"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestCycleCreation:
    def test_cycle_initial_state_is_planned(self):
        """PRD section 3.2: "A new cycle begins in `PLANNED` with an empty
        `candidate_member_ids` and an `inducted_count` of zero; a cycle's
        `status` walks among `PLANNED`, `NOMINATION`, `REVIEW`, `INDUCTED`,
        and the terminal pair `CLOSED` and `CANCELLED`."

        Design: Corner/state_machines/cycle_initial_state_is_planned
        """
        set_clock()
        chapter = create_active_chapter()
        resp = api_client.create_cycle(chapter["id"], create_cycle_payload(),
                                       ADVISOR)
        data = validate_success(resp, expected_status=201)
        assert_cycle(data)
        assert data["status"] == "PLANNED"
        assert data["candidate_member_ids"] == []
        assert data["inducted_count"] == 0

    def test_cycle_invalid_semester_enum_rejected(self):
        """PRD section 3.2: "An `Advisor` creates a membership cycle under an
        active chapter by supplying a `cycle_label` (for example `2026-FALL`),
        an `academic_year` (for example `2026-2027`), a `semester` of `FALL` or
        `SPRING`, and three dates: `nomination_open_date`,
        `nomination_close_date`, and `induction_date`."
        PRD section 2.6: "Independently of all of the above, a malformed request
        payload or a missing required field is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/cycle_invalid_enum_semester_rejected
        """
        set_clock()
        chapter = create_active_chapter()
        payload = create_cycle_payload(semester="AUTUMN")
        resp = api_client.create_cycle(chapter["id"], payload, ADVISOR)
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_REQUEST,
                                        ApiErrorId.ERR_INVALID_FORMAT])

    def test_second_live_cycle_rejected(self):
        """PRD section 3.2: "First, the single-active-cycle guard: at most one
        cycle per chapter may exist in `PLANNED`, `NOMINATION`, `REVIEW`, or
        `INDUCTED` at a time; a second live cycle is rejected with
        `ERR_ACTIVE_CYCLE_EXISTS` (HTTP 409)."

        Design: Corner/validations/active_cycle_exists_blocks_new_cycle
        """
        set_clock()
        chapter = create_active_chapter()
        cycle = create_cycle(chapter["id"])
        open_cycle_nominations(chapter["id"], cycle["id"])
        resp = api_client.create_cycle(
            chapter["id"],
            create_cycle_payload(cycle_label="2026-SPRING", semester="SPRING",
                                 nomination_open_date="2027-01-15T00:00:00Z",
                                 nomination_close_date="2027-02-01T00:00:00Z",
                                 induction_date="2027-03-01T00:00:00Z"),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CYCLE_EXISTS)
