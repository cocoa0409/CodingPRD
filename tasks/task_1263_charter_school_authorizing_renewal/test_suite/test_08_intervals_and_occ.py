"""Interval geometry (half-open interviews, closed contract terms) and OCC
stale-version guards (PRD §2.5, §2.7, §3.1, §3.2, §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_application_under_review, create_approved_school, create_open_school,
    create_draft_contract, create_intervention, create_interview_payload,
    create_corrective_plan_payload,
    make_staff_headers, make_school_operator_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _panel_context():
    """Three UNDER_REVIEW applications (no rubric scores); application A holds
    a SCHEDULED interview 2026-06-08T10:00-11:00Z with panelist rev_p1."""
    app_a = create_application_under_review(school_name="TO Panel Academy A",
                                            applicant_id="applicant_to1")
    get_success_data(api_client.schedule_interview(
        app_a["id"],
        create_interview_payload(scheduled_start="2026-06-08T10:00:00Z",
                                 scheduled_end="2026-06-08T11:00:00Z",
                                 panelist_user_ids=["rev_p1"]),
        STAFF))
    app_b = create_application_under_review(school_name="TO Panel Academy B",
                                            applicant_id="applicant_to1")
    app_c = create_application_under_review(school_name="TO Panel Academy C",
                                            applicant_id="applicant_to1")
    return app_a, app_b, app_c


class TestPanelistHalfOpenAdjacency:
    def test_adjacent_interview_starting_at_others_end_allowed(self, api):
        """PRD §2.5: "Capacity interviews occupy half-open intervals: an
        interview runs from its `scheduled_start` up to but not including its
        `scheduled_end`, so one interview ending at the exact instant another
        begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/panelist_half_open_adjacency
        """
        _a, app_b, _c = _panel_context()
        interview = validate_success(
            api.schedule_interview(
                app_b["id"],
                {"scheduled_start": "2026-06-08T11:00:00Z",
                 "scheduled_end": "2026-06-08T12:00:00Z",
                 "panelist_user_ids": ["rev_p1"]},
                STAFF), 201)
        assert interview["status"] == "SCHEDULED"

    def test_strictly_overlapping_interview_rejected(self, api):
        """PRD §3.1: "no panelist may already hold a `SCHEDULED` interview
        whose half-open interval overlaps the new one — under half-open
        semantics adjacency is allowed, so an interview beginning exactly when
        another ends is permitted — with overlaps rejected as
        `ERR_PANEL_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/panelist_half_open_adjacency
        """
        _a, _b, app_c = _panel_context()
        res = api.schedule_interview(
            app_c["id"],
            {"scheduled_start": "2026-06-08T10:30:00Z",
             "scheduled_end": "2026-06-08T11:30:00Z",
             "panelist_user_ids": ["rev_p1"]},
            STAFF)
        validate_error(res, ApiErrorId.ERR_PANEL_TIME_OVERLAP, expected_status=409)


class TestContractTermClosedIntervalOverlap:
    def _school_with_first_contract(self):
        _app, school = create_approved_school(school_name="TO Term Academy",
                                              applicant_id="applicant_to2")
        school = validate_success(api_client.get_school(school["id"], STAFF), 200)
        c1 = create_draft_contract(school["id"], school["version"],
                                   term_start="2027-07-01T00:00:00Z",
                                   term_end="2032-06-30T00:00:00Z")
        school_after = validate_success(api_client.get_school(school["id"], STAFF), 200)
        return school_after, c1

    def test_term_start_equal_to_sibling_term_end_is_overlap(self, api):
        """PRD §3.2: "the new term may not overlap any sibling `DRAFT` or
        `ACTIVE` term — because both boundary days are inclusive, a term
        beginning on the very day a sibling term ends already overlaps and is
        rejected with `ERR_CONTRACT_TERM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_term_closed_interval_overlap
        """
        school, c1 = self._school_with_first_contract()
        res = api.create_contract(
            school["id"],
            {"framework_version": "FW-2", "term_start": "2032-06-30T00:00:00Z",
             "term_end": "2037-06-30T00:00:00Z", "prior_contract_id": c1["id"],
             "expected_school_version": school["version"]},
            STAFF)
        validate_error(res, ApiErrorId.ERR_CONTRACT_TERM_OVERLAP, expected_status=409)

    def test_term_start_one_day_after_sibling_term_end_accepted(self, api):
        """PRD §2.5: "Contract terms are closed intervals: both `term_start`
        and `term_end` are inclusive days, so a term beginning on the very day
        a sibling term ends already overlaps that sibling."

        Design: Difficulty/resource_temporal_overlap/contract_term_closed_interval_overlap
        """
        school, c1 = self._school_with_first_contract()
        c2 = validate_success(
            api.create_contract(
                school["id"],
                {"framework_version": "FW-2", "term_start": "2032-07-01T00:00:00Z",
                 "term_end": "2037-06-30T00:00:00Z", "prior_contract_id": c1["id"],
                 "expected_school_version": school["version"]},
                STAFF), 201)
        assert c2["status"] == "DRAFT"
        assert c2["prior_contract_id"] == c1["id"]


class TestOccContractCreateStaleSchoolVersion:
    def test_stale_school_version_rejected_fresh_version_succeeds(self, api):
        """PRD §2.7: "If another write has advanced the school's `version`
        since that read, the create is rejected with `ERR_STALE_SCHOOL_VERSION`
        (HTTP 412)."
        PRD §2.7: "Both creates are themselves version-advancing writes: a
        successful contract creation increments the school's `version` by one,
        and a successful plan creation increments the notice's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/occ_contract_create_stale_school_version
        """
        _app, school = create_approved_school(school_name="OCC Contract Academy",
                                              applicant_id="applicant_x1")
        observed = validate_success(api.get_school(school["id"], STAFF), 200)
        stale_version = observed["version"]
        c1 = create_draft_contract(school["id"], stale_version)
        assert c1["status"] == "DRAFT"

        res = api.create_contract(
            school["id"],
            {"framework_version": "FW-2", "term_start": "2032-07-01T00:00:00Z",
             "term_end": "2037-06-30T00:00:00Z", "prior_contract_id": c1["id"],
             "expected_school_version": stale_version},
            STAFF)
        validate_error(res, ApiErrorId.ERR_STALE_SCHOOL_VERSION, expected_status=412)

        fresh = validate_success(api.get_school(school["id"], STAFF), 200)
        assert fresh["version"] == stale_version + 1
        c2 = validate_success(
            api.create_contract(
                school["id"],
                {"framework_version": "FW-2", "term_start": "2032-07-01T00:00:00Z",
                 "term_end": "2037-06-30T00:00:00Z", "prior_contract_id": c1["id"],
                 "expected_school_version": fresh["version"]},
                STAFF), 201)
        assert c2["status"] == "DRAFT"


class TestOccPlanCreateStaleInterventionVersion:
    def test_stale_intervention_version_rejected_fresh_version_succeeds(self, api):
        """PRD §2.7: "A mismatch with the notice's current `version` is
        rejected with `ERR_STALE_INTERVENTION_VERSION` (HTTP 412)."
        PRD §3.5: "A successful submission creates the plan in `SUBMITTED`,
        stamps its `intervention_id`, records `submitted_at` from the clock,
        leaves `reviewed_by_user_id` and `review_notes` null, and increments
        the notice's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_intervention_version
        """
        ctx = create_open_school(school_name="OCC Plan Academy",
                                 applicant_id="applicant_x2")
        notice = create_intervention(ctx["school"]["id"], level="PROBATION",
                                     domain="FINANCIAL",
                                     reason="Cash reserve below covenant")
        stale_version = notice["version"]
        issued = validate_success(
            api.issue_intervention(notice["id"], make_staff_headers("staff_a")), 200)
        fresh_version = issued["version"]
        assert fresh_version != stale_version

        res = api.create_corrective_plan(
            notice["id"],
            create_corrective_plan_payload(plan_text="Stale-version plan",
                                           expected_intervention_version=stale_version),
            make_school_operator_headers(ctx["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_INTERVENTION_VERSION, expected_status=412)

        plan = validate_success(
            api.create_corrective_plan(
                notice["id"],
                create_corrective_plan_payload(plan_text="Fresh-version plan",
                                               expected_intervention_version=fresh_version),
                make_school_operator_headers(ctx["school"]["id"])), 201)
        assert plan["status"] == "SUBMITTED"

        notice_after = validate_success(api.get_intervention(notice["id"], STAFF), 200)
        assert notice_after["version"] == fresh_version + 1
