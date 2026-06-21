"""CRUD creation/retrieval, required fields, uniqueness, FK existence, computed
fields, listing/pagination, invalid state transitions, filtered reads, archive,
RBAC, optimistic concurrency, and the readiness-score computed read.

Covers the entities, state_machines (invalid transitions), calculations (readiness),
endpoints, rbac, and cross_cutting (OCC + tier) corner sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    set_clock, create_program, create_member, create_instructor, create_family,
    create_program_with_simple_chain, setup_enrolled_member, setup_family_with_members,
    create_enrollment, sign_contract, schedule_promotion_test, create_class_session,
    check_in, make_member_headers, make_instructor_headers, member_version,
    NON_EXISTENT_UUID, TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


class TestEntityCrud:

    def test_create_program_returns_201_with_fields(self, api):
        """PRD §3.1: "A program is born in `ACTIVE` `status`."
        PRD §2.4: "an integer `version` that begins at 1 and increments by exactly 1
        on each mutation."

        Design: Corner/entities/create_program_returns_201_with_fields
        """
        res = api.create_program(
            {"name": "Kids Karate", "discipline": "KARATE", "base_monthly_tuition_cents": 8000,
             "test_fee_cents": 2500, "min_attendance_for_test": 6, "min_days_in_rank": 14}, FD)
        prog = validate_success(res, 201)
        assert prog["status"] == "ACTIVE", prog
        assert prog["base_monthly_tuition_cents"] == 8000, prog
        assert prog["version"] == 1, prog

    def test_get_member_not_found(self, api):
        """PRD §2.9: "for any endpoint whose URL contains a resource id, that id must
        resolve to an existing resource ... the first that does not resolve yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        res = api.get_member(NON_EXISTENT_UUID, FD)
        validate_error(res, "ERR_NOT_FOUND", 404)

    def test_create_member_missing_email_invalid_request(self, api):
        """PRD §3.3: "A **member** is registered by the front desk with a `full_name`
        (1 to 120 characters), a globally unique `email` (containing an `@`, unique
        across all members), and a `date_of_birth`."
        PRD §2.10: "then structural validity of the body — required fields, types,
        enums, ranges (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/create_member_missing_email_returns_invalid_request
        """
        res = api.create_member({"full_name": "No Email", "date_of_birth": "1990-01-01"}, FD)
        validate_error(res, "ERR_INVALID_REQUEST", 400)

    def test_duplicate_member_email_returns_duplicate(self, api):
        """PRD §3.1: "Attempting to register a member or instructor with a duplicate
        email ... is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/duplicate_member_email_returns_duplicate
        """
        get_success_data(api.create_member(
            {"full_name": "First", "email": "dup@x.com", "date_of_birth": "1990-01-01", "waiver_signed": True}, FD))
        res = api.create_member(
            {"full_name": "Second", "email": "dup@x.com", "date_of_birth": "1991-01-01", "waiver_signed": True}, FD)
        validate_error(res, "ERR_DUPLICATE", 409)

    def test_duplicate_belt_rank_code_returns_duplicate(self, api):
        """PRD §3.1: "or a belt rank whose `code` or `rank_order` collides with one
        already in the program, is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/entities/duplicate_belt_rank_code_within_program_returns_duplicate
        """
        prog = create_program(with_entry_rank=False, discipline="JUDO")
        get_success_data(api.create_belt_rank(
            prog["id"], {"code": "WHITE", "rank_order": 0, "next_rank_code": None, "is_entry_rank": True}, FD))
        res = api.create_belt_rank(
            prog["id"], {"code": "WHITE", "rank_order": 1, "next_rank_code": None}, FD)
        validate_error(res, "ERR_DUPLICATE", 409)

    def test_create_member_bad_family_fk_returns_fk_not_found(self, api):
        """PRD §2.9: "every foreign-key id supplied in a request body — a `member_id`,
        `program_id`, `instructor_id`, `enrollment_id`, `class_session_id`,
        `examiner_instructor_id`, `contract_id`, or `family_id` — must reference an
        existing resource, or the request is rejected with `ERR_FK_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/create_member_with_bad_family_fk_returns_fk_not_found
        """
        res = api.create_member(
            {"full_name": "Orphan", "email": "orphan@x.com", "date_of_birth": "1990-01-01",
             "family_id": NON_EXISTENT_UUID, "waiver_signed": True}, FD)
        validate_error(res, "ERR_FK_NOT_FOUND", 404)

    def test_family_active_member_count_computed(self, api):
        """PRD §2.5: "`Family.active_member_count` is the number of members in a
        household whose `account_status` is either `ACTIVE` or `FROZEN` ... it is
        recomputed on every member add, removal, or status change."

        Design: Corner/entities/family_active_member_count_computed_on_create
        """
        fam, members = setup_family_with_members(2, surname="Count")
        fam_after = validate_success(api.get_family(fam["id"], FD), 200)
        assert fam_after["active_member_count"] == 2, fam_after

    def test_list_members_pagination_envelope(self, api):
        """PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`
        (the total number of records matching the filter, ignoring pagination), and
        `has_more` (true when records remain beyond the current page) inside the
        `meta` object."

        Design: Corner/entities/list_members_pagination_envelope
        """
        for _ in range(3):
            create_member()
        data, meta = validate_paginated(api.list_members(FD, params={"limit": 2, "offset": 0}))
        assert meta["total_count"] == 3, meta
        assert meta["has_more"] is True, meta
        assert len(data) == 2, data

    def test_system_fields_generated_on_create(self, api):
        """PRD §2.4: "Clients must never set `id`, `created_at`, `updated_at`, or
        `version`; the server owns them."
        PRD §3.3: "A member begins `ACTIVE`."

        Design: Corner/entities/system_fields_generated_on_create_input_ignored
        """
        m = validate_success(api.create_member(
            {"full_name": "Sys", "email": "sys@x.com", "date_of_birth": "1990-01-01",
             "waiver_signed": True}, FD), 201)
        from test_helpers import is_valid_uuid
        assert is_valid_uuid(m["id"]), m
        assert m["version"] == 1, m
        assert m["account_status"] == "ACTIVE", m


class TestInvalidStateTransitions:

    def test_cancel_completed_class_invalid_state(self, api):
        """PRD §2.10: "then the state-transition legality check (`ERR_INVALID_STATE`,
        409)."
        PRD §3.4: "Cancelling a class session is available from `SCHEDULED`."

        Design: Corner/state_machines/cancel_class_from_completed_returns_invalid_state
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-02-01T10:00:00Z", "2026-02-01T11:00:00Z", capacity=5)
        completed = get_success_data(api.complete_class_session(
            session["id"], {"expected_class_session_version": session["version"]},
            make_instructor_headers(instructor["id"])))
        res = api.cancel_class_session(
            session["id"], {"expected_class_session_version": completed["version"]}, FD)
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_grade_already_graded_test_invalid_state(self, api):
        """PRD §3.5: "Grading a `SCHEDULED` test is performed by an instructor."
        PRD §2.10: "then the state-transition legality check (`ERR_INVALID_STATE`,
        409)."

        Design: Corner/state_machines/grade_already_graded_test_returns_invalid_state
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-05T00:00:00Z")
        get_success_data(api.grade_promotion_test(
            test["id"], {"score": 40}, make_instructor_headers(instructor["id"])))
        res = api.grade_promotion_test(
            test["id"], {"score": 95}, make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_withdraw_terminal_member_invalid_state(self, api):
        """PRD §3.3: "The member's `version` increments by 1. The transitions out of
        `ACTIVE`, `FROZEN`, and `SUSPENDED` into `WITHDRAWN` all carry these same
        effects; `WITHDRAWN` is terminal."

        Design: Corner/state_machines/withdraw_terminal_member_returns_invalid_state
        """
        member = create_member()
        withdrawn = get_success_data(api.withdraw_member(
            member["id"], {"expected_member_version": member["version"]}, FD))
        res = api.withdraw_member(member["id"], {"expected_member_version": withdrawn["version"]}, FD)
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_unfreeze_unfrozen_member_invalid_state(self, api):
        """PRD §3.3: "Unfreezing is the mirror: available only from `FROZEN` and
        guarded by `expected_member_version`."

        Design: Corner/state_machines/unfreeze_unfrozen_member_returns_invalid_state
        """
        member = create_member()
        res = api.unfreeze_member(member["id"], {"expected_member_version": member["version"]}, FD)
        validate_error(res, "ERR_INVALID_STATE", 409)


class TestComputedReads:

    def test_readiness_score_partial_eligibility(self, api):
        """PRD §3.5: "The score is 40 times the clamped attendance ratio plus 60 times
        the clamped days ratio, rounded half up, and then capped so it never exceeds
        100."
        PRD §3.5: "Eligibility is an AND of six gates, all of which must hold. First,
        the enrollment's `rank_attendance_count` must be at least the program's
        `min_attendance_for_test`."

        Design: Corner/calculations/readiness_score_partial_eligibility
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=10, min_days_in_rank=30)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        # 5 counted attendances across 5 sessions.
        for d in range(2, 7):
            session = create_class_session(prog["id"], instructor["id"],
                                           f"2026-01-{d:02d}T10:00:00Z", f"2026-01-{d:02d}T11:00:00Z", capacity=50)
            check_in(enrollment["id"], session["id"], member["id"])
        # Advance 15 whole days from rank_acquired_at (2026-01-01).
        set_clock("2026-01-16T00:00:00Z")
        elig = validate_success(api.get_test_eligibility(enrollment["id"], make_instructor_headers(instructor["id"])), 200)
        assert elig["readiness"] == 50, elig  # 40*0.5 + 60*0.5
        assert elig["eligible"] is False, elig


class TestFilteredReadsAndArchive:

    def test_enrollment_filtered_list_by_member(self, api):
        """PRD §2.9: "the graph is navigated through filtered list reads rather than
        deep nesting."

        Design: Corner/endpoints/enrollment_filtered_list_by_member
        """
        prog = create_program()
        member, enrollment = setup_enrolled_member(prog["id"])
        data, meta = validate_paginated(api.list_enrollments(FD, params={"member_id": member["id"]}))
        ids = [e["id"] for e in data]
        assert enrollment["id"] in ids, data
        assert all(e["member_id"] == member["id"] for e in data), data

    def test_program_archive_sets_archived(self, api):
        """PRD §3.1: "archiving it transitions its `status` to `ARCHIVED`, after which
        it accepts no new enrollments."

        Design: Corner/endpoints/program_archive_sets_archived
        """
        prog = create_program()
        archived = validate_success(api.archive_program(prog["id"], FD), 200)
        assert archived["status"] == "ARCHIVED", archived


class TestRbac:

    def test_member_cannot_create_program(self, api):
        """PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation ... the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/member_cannot_create_program
        """
        member = create_member()
        res = api.create_program(
            {"name": "Sneaky", "discipline": "BJJ", "base_monthly_tuition_cents": 9000,
             "test_fee_cents": 3000, "min_attendance_for_test": 0, "min_days_in_rank": 0},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_instructor_cannot_signoff_only_chief(self, api):
        """PRD §3.5: "Signoff is exclusive to a `ChiefInstructor`: the acting
        instructor's `rank_level` must be `CHIEF_INSTRUCTOR`."

        Design: Corner/rbac/instructor_cannot_signoff_only_chief
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLACK", terminal_code="BLACK", terminal_requires_signoff=True,
            min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor(rank_level="INSTRUCTOR")
        member, enrollment = setup_enrolled_member(prog["id"])
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-05T00:00:00Z")
        get_success_data(api.grade_promotion_test(
            test["id"], {"score": 90}, make_instructor_headers(instructor["id"])))
        res = api.signoff_promotion_test(test["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "If `X-User-Role` is missing or is not one of the four recognized
        roles ... the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_header_returns_unauthenticated
        """
        res = api.list_programs({"X-User-ID": "x", "X-User-Role": "NoSuchRole",
                                 "Content-Type": "application/json"})
        validate_error(res, "ERR_UNAUTHENTICATED", 401)


class TestOptimisticConcurrency:

    def test_stale_member_version_on_contract_create(self, api):
        """PRD §2.6: "Creating a contract requires `expected_member_version` to match
        the target member's current `version`; if another writer has advanced the
        member's version since the client last read it ... the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_contract_create
        """
        prog = create_program()
        member = create_member(waiver_signed=False)
        stale_v = member["version"]
        # Freeze then unfreeze advances the member version twice.
        frozen = get_success_data(api.freeze_member(member["id"], {"expected_member_version": stale_v}, FD))
        get_success_data(api.unfreeze_member(member["id"], {"expected_member_version": frozen["version"]}, FD))
        res = api.create_contract(
            {"member_id": member["id"], "program_id": prog["id"], "term_months": 12,
             "billing_anchor_day": 1, "expected_member_version": stale_v}, FD)
        validate_error(res, "ERR_STALE_VERSION", 412)

    def test_correct_member_version_on_enrollment_succeeds(self, api):
        """PRD §2.6: "Creating an enrollment likewise requires `expected_member_version`
        to match the member's current `version`."
        PRD §3.4: "A new enrollment is born `ACTIVE`."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_member_version_on_enrollment_succeeds
        """
        prog = create_program()
        member = create_member()
        enr = validate_success(api.create_enrollment(
            {"member_id": member["id"], "program_id": prog["id"],
             "expected_member_version": member["version"]}, FD), 201)
        assert enr["status"] == "ACTIVE", enr

    def test_family_tier_threshold_at_two_members(self, api):
        """PRD §3.2: "exactly two counted members earns 10 percent ... The boundary is
        inclusive on the low side of each tier — two members yields exactly 10 percent,
        not the solo rate."

        Design: Corner/cross_cutting_complexity_layers/family_tier_threshold_at_two_members
        """
        prog = create_program(base_monthly_tuition_cents=10000)
        fam, members = setup_family_with_members(2, surname="TwoTier")
        m1 = members[0]
        contract = sign_contract(m1["id"], prog["id"], m1["version"], term_months=12)
        assert contract["locked_family_discount_pct"] == pytest.approx(0.10), contract
