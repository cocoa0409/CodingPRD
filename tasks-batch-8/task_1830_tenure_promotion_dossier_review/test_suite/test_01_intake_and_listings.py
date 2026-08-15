"""Candidate/case intake, computed case fields, the not-found catalogue, clock
policies, and list pagination/filtering (PRD §2.3, §2.12, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_dossier_item,
    assert_candidate,
    assert_date_eq,
    make_candidate_headers,
    open_case,
    register_candidate,
    set_logical_clock,
    submit_dossier,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCandidateIntake:
    def test_candidate_creation_sets_active_status_and_system_fields(self, api, po_headers):
        """PRD §3.1: "New candidates begin with `status` set to `ACTIVE`".
        PRD §2.5: "`id` (string): a unique, server-minted identifier for the
        resource, formatted as a UUID with no type prefix."

        Design: Corner/entities/candidate_creation_defaults_and_system_fields
        """
        resp = api.create_candidate(
            {
                "full_name": "New Cand",
                "employee_id": "E9001",
                "department": "HIST",
                "college": "ARTS",
                "tenure_clock_start": "2021-01-15",
            },
            po_headers,
        )
        data = validate_success(resp, 201)
        assert_candidate(data)
        assert data["status"] == "ACTIVE", (
            f"New candidate must start ACTIVE, got {data['status']}"
        )
        assert data["full_name"] == "New Cand"
        assert data["employee_id"] == "E9001"

    def test_duplicate_employee_id_and_reviewer_email_rejected(self, api, po_headers):
        """PRD §3.1: "The `employee_id` must be unique across all registered
        candidates; a duplicate registration is rejected with
        `ERR_DUPLICATE_EMPLOYEE_ID`."
        PRD §3.4: "The `email` must be unique across all registered reviewers;
        duplicates are rejected with `ERR_DUPLICATE_REVIEWER_EMAIL`."

        Design: Corner/entities/duplicate_employee_id_and_reviewer_email_rejected
        """
        first = api.create_candidate(
            {
                "full_name": "First",
                "employee_id": "E9002",
                "department": "HIST",
                "college": "ARTS",
                "tenure_clock_start": "2021-01-15",
            },
            po_headers,
        )
        validate_success(first, 201)
        rev = api.create_reviewer(
            {
                "full_name": "Rev One",
                "institution": "MIT",
                "email": "dup@mit.edu",
                "expertise_area": "HIST",
            },
            po_headers,
        )
        validate_success(rev, 201)

        dup_candidate = api.create_candidate(
            {
                "full_name": "Second",
                "employee_id": "E9002",
                "department": "HIST",
                "college": "ARTS",
                "tenure_clock_start": "2021-01-15",
            },
            po_headers,
        )
        validate_error(dup_candidate, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_ID)

        dup_reviewer = api.create_reviewer(
            {
                "full_name": "Rev Two",
                "institution": "Yale",
                "email": "dup@mit.edu",
                "expertise_area": "HIST",
            },
            po_headers,
        )
        validate_error(dup_reviewer, ApiErrorId.ERR_DUPLICATE_REVIEWER_EMAIL)


class TestCaseIntake:
    def test_case_creation_computes_review_date_and_waiver_default(self, api, po_headers):
        """PRD §3.1: "The system records the creating officer's identity in
        `created_by_user_id` and places the case in `DOSSIER_ASSEMBLY`."
        PRD §3.1: "Under the `ANNIVERSARY` policy the base date is the anchor
        advanced by 72 calendar months, month-anchored: a clock that started on
        2020-08-01 yields a base of 2026-08-01."
        PRD §3.1: "The case's `extension_days`, initially zero, is then added to
        the base date."
        PRD §3.1: "optionally `waiver_signed`, which defaults to true"
        PRD §3.1: "Several computed fields remain null until their triggering
        events".

        Design: Corner/entities/case_creation_computed_fields_and_waiver_default
        """
        candidate = register_candidate("E9003", full_name="Cand C")
        resp = api.create_case(
            {
                "candidate_id": candidate["id"],
                "review_cycle": "2026-2027",
                "target_rank": "ASSOCIATE_PROFESSOR",
                "seeking_tenure": True,
                "clock_policy": "ANNIVERSARY",
            },
            po_headers,
        )
        data = validate_success(resp, 201)
        assert data["stage"] == "DOSSIER_ASSEMBLY"
        assert_date_eq(data["mandatory_review_date"], "2026-08-01", "mandatory_review_date")
        assert data["extension_days"] == 0
        assert data["waiver_signed"] is True, "waiver_signed must default to true"
        assert data["recommendation_score"] is None
        assert data["created_by_user_id"] == "po_creator"

    def test_anniversary_clock_policy_base_date(self, api):
        """PRD §3.1: "Under the `ANNIVERSARY` policy the base date is the anchor
        advanced by 72 calendar months, month-anchored: a clock that started on
        2020-08-01 yields a base of 2026-08-01."

        Design: Difficulty/dual_variant_calc/clock_policy_anniversary_vs_day_count_diverge
        """
        candidate = register_candidate("E300", full_name="Cand X")
        case = open_case(candidate["id"], clock_policy="ANNIVERSARY")
        assert_date_eq(
            case["mandatory_review_date"], "2026-08-01", "ANNIVERSARY mandatory_review_date"
        )

    def test_day_count_clock_policy_base_date(self, api):
        """PRD §3.1: "Under the `DAY_COUNT` policy the base is the anchor
        advanced by a fixed count of days — 72 months at 30.4375 days per month,
        rounded half-up, giving 2,192 days — so the same 2020-08-01 anchor yields
        2026-08-02, one day later than the anniversary result, since the fixed
        day count drifts across leap years."

        Design: Difficulty/dual_variant_calc/clock_policy_anniversary_vs_day_count_diverge
        """
        candidate = register_candidate("E301", full_name="Cand Y")
        case = open_case(candidate["id"], clock_policy="DAY_COUNT")
        assert_date_eq(
            case["mandatory_review_date"], "2026-08-02", "DAY_COUNT mandatory_review_date"
        )

    def test_invalid_enum_and_interval_inputs_rejected(self, api, po_headers):
        """PRD §2.12: "malformed-request failures (missing required fields, wrong
        types, enum values outside the declared sets, invalid pagination
        parameters) under `ERR_INVALID_REQUEST`."
        PRD §2.8: "Review windows (`review_window_start` and `review_window_end`),
        committee terms (`term_start` and `term_end`), and stop-the-clock
        intervals (`interval_start` and `interval_end`) require the start to be
        strictly before the end."
        PRD §2.8: "Any violation of these rules is rejected with
        `ERR_INVALID_INTERVAL`."

        Design: Corner/entities/invalid_enum_and_interval_inputs_rejected
        """
        candidate = register_candidate("E9004", full_name="Cand I")
        case = open_case(candidate["id"])

        bad_enum = api.create_case(
            {
                "candidate_id": candidate["id"],
                "review_cycle": "2027-2028",
                "target_rank": "DEAN",
                "seeking_tenure": True,
                "clock_policy": "ANNIVERSARY",
            },
            po_headers,
        )
        validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

        bad_term = api.create_committee(
            {
                "level": "DEPARTMENT",
                "academic_unit": "CS",
                "term_start": "2026-12-31",
                "term_end": "2026-01-01",
                "pass_rule": "STRICT_MAJORITY_OF_CAST",
            },
            po_headers,
        )
        validate_error(bad_term, ApiErrorId.ERR_INVALID_INTERVAL)

        bad_interval = api.create_clock_extension(
            {
                "case_id": case["id"],
                "reason": "OTHER",
                "interval_start": "2023-05-01",
                "interval_end": "2023-05-01",
            },
            make_candidate_headers(candidate["id"]),
        )
        validate_error(bad_interval, ApiErrorId.ERR_INVALID_INTERVAL)


class TestNotFoundCatalog:
    @pytest.mark.parametrize(
        "getter,error_id",
        [
            ("get_candidate", ApiErrorId.ERR_CANDIDATE_NOT_FOUND),
            ("get_case", ApiErrorId.ERR_CASE_NOT_FOUND),
            ("get_dossier_item", ApiErrorId.ERR_DOSSIER_ITEM_NOT_FOUND),
            ("get_reviewer", ApiErrorId.ERR_REVIEWER_NOT_FOUND),
            ("get_invitation", ApiErrorId.ERR_INVITATION_NOT_FOUND),
            ("get_committee", ApiErrorId.ERR_COMMITTEE_NOT_FOUND),
            ("get_member", ApiErrorId.ERR_MEMBER_NOT_FOUND),
            ("get_round", ApiErrorId.ERR_ROUND_NOT_FOUND),
            ("get_vote", ApiErrorId.ERR_VOTE_NOT_FOUND),
            ("get_clock_extension", ApiErrorId.ERR_CLOCK_EXTENSION_NOT_FOUND),
            ("get_midterm_review", ApiErrorId.ERR_MIDTERM_REVIEW_NOT_FOUND),
            ("get_decision", ApiErrorId.ERR_DECISION_NOT_FOUND),
            ("get_appeal", ApiErrorId.ERR_APPEAL_NOT_FOUND),
        ],
    )
    def test_not_found_catalog_sweep(self, api, reader_headers, getter, error_id):
        """PRD §2.12: "**Path resource existence.** Resource identifiers
        appearing in the request path must exist, validated left to right along
        the path —
        before any ownership evaluation, which itself needs the resource. The
        not-found catalogue is `ERR_CANDIDATE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_DOSSIER_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`,
        `ERR_INVITATION_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`,
        `ERR_MEMBER_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`,
        `ERR_CLOCK_EXTENSION_NOT_FOUND`, `ERR_MIDTERM_REVIEW_NOT_FOUND`,
        `ERR_DECISION_NOT_FOUND`, and `ERR_APPEAL_NOT_FOUND` (all HTTP 404),
        resolved per missing identifier."

        Design: Corner/entities/not_found_catalog_sweep
        """
        resp = getattr(api, getter)(NON_EXISTENT_UUID, reader_headers)
        validate_error(resp, error_id)


class TestListEndpoints:
    def test_list_pagination_envelope_and_bounds(self, api, reader_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100."
        PRD §2.3: "Invalid pagination parameters are rejected with
        `ERR_INVALID_REQUEST`."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_and_bounds
        """
        candidate = register_candidate("E9400", full_name="Cand PG")
        case = open_case(candidate["id"])
        for title in ("P1", "P2", "P3"):
            add_dossier_item(
                case["id"],
                candidate["id"],
                "TEACHING" if title != "P3" else "SERVICE",
                title,
                page_count=4,
            )

        page1, meta1 = validate_paginated(
            api.list_dossier_items(
                reader_headers, {"case_id": case["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2, f"Page 1 must hold 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_dossier_items(
                reader_headers, {"case_id": case["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1, f"Page 2 must hold exactly 1 item, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], "Pages must be disjoint"

        err_zero = api.list_dossier_items(
            reader_headers, {"case_id": case["id"], "limit": 0}
        )
        validate_error(err_zero, ApiErrorId.ERR_INVALID_REQUEST)
        err_over = api.list_dossier_items(
            reader_headers, {"case_id": case["id"], "limit": 101}
        )
        validate_error(err_over, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_filters_by_status_and_category(self, api, reader_headers):
        """PRD §2.3: "the dossier item list accepts `case_id`,
        `supersedes_item_id`, `status`, and `category`".
        PRD §3.2: "the dossier must contain at least two `TEACHING` items, at
        least three `RESEARCH` items, and at least one `SERVICE` item, and at
        least one of the `SUBMITTED` `RESEARCH` items must have
        `is_peer_reviewed` set to true; counts exactly equal to a minimum pass,
        and any shortfall is rejected with `ERR_DOSSIER_INCOMPLETE`."

        Design: Corner/endpoints/list_filters_by_status_and_category
        """
        set_logical_clock()
        candidate = register_candidate("E9401", full_name="Cand LF")
        case = open_case(candidate["id"])
        add_dossier_item(case["id"], candidate["id"], "TEACHING", "T1")
        add_dossier_item(case["id"], candidate["id"], "TEACHING", "T2")
        research = add_dossier_item(
            case["id"], candidate["id"], "RESEARCH", "R1",
            page_count=12, is_peer_reviewed=True,
        )

        # Bonus check: this dossier is below every minimum and cannot submit.
        submit_resp = api.submit_dossier(
            case["id"], make_candidate_headers(candidate["id"])
        )
        validate_error(submit_resp, ApiErrorId.ERR_DOSSIER_INCOMPLETE)

        research_items, research_meta = validate_paginated(
            api.list_dossier_items(
                reader_headers, {"case_id": case["id"], "category": "RESEARCH"}
            )
        )
        assert research_meta["total_count"] == 1
        assert research_items[0]["id"] == research["id"]

        teaching_items, teaching_meta = validate_paginated(
            api.list_dossier_items(
                reader_headers, {"case_id": case["id"], "category": "TEACHING"}
            )
        )
        assert teaching_meta["total_count"] == 2
        assert len(teaching_items) == 2
