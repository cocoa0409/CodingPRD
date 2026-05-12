"""Application submit-time eligibility, materials, advisor, duplicates."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    api_client,
    create_application,
    create_application_payload,
    create_open_scholarship,
    create_reviewer,
    create_submitted_application,
    iso_at,
    make_student_headers,
    new_student_id,
    submit_application,
    validate_error,
    validate_success,
)


class TestEligibilityBoundary:
    """PRD §3.3 eligibility evaluation: GPA inclusive, empty-list
    fallbacks, NEED-only income check."""

    def test_gpa_threshold_exactly_at_boundary_passes(self):
        """PRD §3.3: "the student's `student_gpa_x100` is at least the
        scholarship's `gpa_threshold_x100` (inclusive)".

        Claim: student_gpa_x100 == gpa_threshold_x100 is accepted
        (inclusive comparison). Implements the GPA boundary case from
        eligibility.
        # difficulty: boundary_precision_check/gpa_threshold_inclusive_boundary_on_submit
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            gpa_threshold_x100=350,
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"],
            student_headers=headers,
            student_gpa_x100=350,
            uploaded_materials=["TRANSCRIPT"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"

    def test_gpa_just_below_threshold_fails_eligibility(self):
        """PRD §3.3: "If any of the four fails, ERR_ELIGIBILITY_FAIL is
        returned." Inclusive comparison rejects values < threshold.

        Claim: gpa = threshold - 1 -> ERR_ELIGIBILITY_FAIL.
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            gpa_threshold_x100=350,
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_gpa_x100=349,
            uploaded_materials=["TRANSCRIPT"],
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_FAIL.value)

    def test_empty_eligible_majors_allows_any_major(self):
        """PRD §3.3: "the scholarship's `eligible_majors` is empty or the
        student's `student_major` is one of its elements".

        Claim: empty eligible_majors permits any major.
        # difficulty: boundary_precision_check/empty_eligible_majors_means_all_majors_on_submit
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            gpa_threshold_x100=0,
            eligible_majors=[],
            eligible_grades=[],
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_major="OBSCURE-XYZ",
            uploaded_materials=["TRANSCRIPT"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"

    def test_major_not_in_non_empty_list_fails(self):
        """PRD §3.3: "the scholarship's eligible_majors is empty or the
        student's student_major is one of its elements".

        Claim: major not in non-empty eligible_majors -> ELIGIBILITY_FAIL.
        """
        sch, _ = create_open_scholarship(
            category="MERIT", gpa_threshold_x100=0,
            eligible_majors=["CS"],
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_major="MATH",
            uploaded_materials=["TRANSCRIPT"],
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_FAIL.value)

    def test_need_income_above_ceiling_fails(self):
        """PRD §3.3: "if and only if the scholarship's category is NEED,
        the student's student_family_income_cents is non-null and is at
        most the scholarship's family_income_ceiling_cents (inclusive)."

        Claim: NEED + income > ceiling -> ERR_ELIGIBILITY_FAIL.
        """
        sch, _ = create_open_scholarship(
            category="NEED",
            gpa_threshold_x100=0,
            family_income_ceiling_cents=5_000_000,
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_family_income_cents=5_000_001,
            uploaded_materials=["TRANSCRIPT"],
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_FAIL.value)

    def test_need_income_at_ceiling_passes(self):
        """PRD §3.3: "non-null and is at most the scholarship's
        family_income_ceiling_cents (inclusive)".

        Claim: NEED + income == ceiling is accepted.
        """
        sch, _ = create_open_scholarship(
            category="NEED",
            gpa_threshold_x100=0,
            family_income_ceiling_cents=5_000_000,
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_family_income_cents=5_000_000,
            uploaded_materials=["TRANSCRIPT"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"


class TestSubmitMaterials:

    def test_uploaded_materials_not_superset_of_required_fails(self):
        """PRD §3.3: "the student's uploaded_materials must be a superset
        of the scholarship's required_materials; missing materials
        produce ERR_MATERIAL_MISSING."

        Claim: missing required material -> ERR_MATERIAL_MISSING.
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT", "AWARD_CERT"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_MISSING.value)

    def test_advisor_rec_required_but_missing_fails(self):
        """PRD §3.3: "when ADVISOR_REC is among the required materials,
        advisor_recommendation_id must reference a Reviewer whose status
        is ACTIVE; otherwise ERR_ADVISOR_REC_MISSING."

        Claim: ADVISOR_REC required but advisor_recommendation_id missing
        -> ERR_ADVISOR_REC_MISSING.
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT", "ADVISOR_REC"],
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT", "ADVISOR_REC"],
            advisor_recommendation_id=None,
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ADVISOR_REC_MISSING.value)

    def test_advisor_rec_with_active_reviewer_passes(self):
        """PRD §3.3: "advisor_recommendation_id must reference a Reviewer
        whose status is ACTIVE".

        Claim: ADVISOR_REC + active reviewer id -> submit accepted.
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT", "ADVISOR_REC"],
            gpa_threshold_x100=0,
        )
        advisor = create_reviewer()
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT", "ADVISOR_REC"],
            advisor_recommendation_id=advisor["id"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"


class TestSubmitWindowAndState:

    def test_submit_outside_open_state_rejected(self):
        """PRD §3.3: "First, the parent scholarship's status must be OPEN;
        if it is anything else, the submit is rejected with
        ERR_WINDOW_NOT_OPEN."

        Claim: submit when Scholarship.status==DRAFT (never opened) ->
        ERR_WINDOW_NOT_OPEN.
        """
        # Make scholarship in DRAFT, but create application requires OPEN
        # by §4. We test the inverse: open it, create app, then move to
        # REVIEWING and try to submit the still-DRAFT app.
        sch, _ = create_open_scholarship()
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        # Close the window and transition to REVIEWING.
        advance_clock(sch["application_window_end"])
        validate_success(
            api_client.transition_scholarship(
                sch["id"], {"to_status": "REVIEWING"}, ADMIN,
            ),
        )
        resp = api_client.submit_application(sch["id"], app["id"], headers)
        # PRD §3.3 first clause: 'must be OPEN; if it is anything else,
        # the submit is rejected with ERR_WINDOW_NOT_OPEN.'
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN.value)


class TestDuplicateApplication:

    def test_two_submits_by_same_student_same_scholarship_blocks_second(self):
        """PRD §3.3: "Sixth, the student must have no other application
        against this same scholarship in any non-terminal status — meaning
        anything other than WITHDRAWN, REVOKED, DISBURSED, or NOT_AWARDED;
        otherwise ERR_DUPLICATE_APPLICATION_SAME."

        Claim: a second SUBMITTED application by same student on same
        scholarship -> ERR_DUPLICATE_APPLICATION_SAME.
        """
        sch, _ = create_open_scholarship(category="MERIT")
        sid = new_student_id()
        headers = make_student_headers(sid)
        # First app: submit successfully.
        create_submitted_application(
            sch, student_id=sid,
            uploaded_materials=list(sch["required_materials"]),
        )
        # Second app by same student.
        app2, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=list(sch["required_materials"]),
        )
        resp = api_client.submit_application(
            sch["id"], app2["id"], headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DUPLICATE_APPLICATION_SAME.value,
        )

    def test_cross_application_same_category_buffered_overlap_rejected(self):
        """PRD §3.3: "the buffered interval for each scholarship is the
        closed-closed interval running from its `application_window_start`
        to its `application_window_end` extended by an additional three
        days ... Two scholarships of the same category collide when their
        buffered closed-closed intervals share at least one point in
        common; if the student already has any non-terminal application
        against such a colliding peer, the new submission is rejected
        with `ERR_DUPLICATE_APPLICATION_CROSS`."

        Claim: same student submits a SECOND application to a same-category
        scholarship whose buffered window overlaps -> 409
        ERR_DUPLICATE_APPLICATION_CROSS.
        # difficulty: resource_temporal_overlap/cross_application_buffered_overlap_blocks_submit
        """
        # S-D: 07-01..07-05 -> buffered [07-01, 07-08].
        # S-E: 07-07..07-15 -> buffered [07-07, 07-18]. Overlap [07-07,07-08].
        # Half-open raw windows [07-01,07-05) and [07-07,07-15) are disjoint
        # so scholarship-create-overlap rule does NOT reject.
        sch_d, _ = create_open_scholarship(
            category="NEED",
            family_income_ceiling_cents=10_000_000,
            gpa_threshold_x100=0,
            required_materials=["TRANSCRIPT"],
            application_window_start=iso_at(2026, 7, 1),
            application_window_end=iso_at(2026, 7, 5),
            announcement_window_end=iso_at(2026, 7, 20),
        )
        # Now build S-E.
        # We need to set the clock so S-E open passes. Then the student's
        # FIRST submit happens on S-D, and the SECOND submit on S-E.
        sid = new_student_id()
        # S-D OPEN at 2026-07-01 already; clock is at 07-01 from
        # create_open_scholarship.
        student_headers = make_student_headers(sid)
        # Submit on S-D.
        app_d, _ = create_application(
            sch_d["id"], student_headers=student_headers,
            uploaded_materials=["TRANSCRIPT"],
            student_family_income_cents=1_000_000,
        )
        validate_success(
            api_client.submit_application(
                sch_d["id"], app_d["id"], student_headers,
            ),
        )
        # Create S-E in DRAFT, then open at its window_start.
        from test_helpers import (
            create_scholarship_with_quota,
        )
        sch_e, _ = create_scholarship_with_quota(
            total_quota=1,
            category="NEED",
            family_income_ceiling_cents=10_000_000,
            gpa_threshold_x100=0,
            required_materials=["TRANSCRIPT"],
            application_window_start=iso_at(2026, 7, 7),
            application_window_end=iso_at(2026, 7, 15),
            announcement_window_end=iso_at(2026, 7, 30),
        )
        advance_clock(sch_e["application_window_start"])
        validate_success(
            api_client.transition_scholarship(
                sch_e["id"], {"to_status": "OPEN"}, ADMIN,
            ),
        )
        # Same student creates draft on S-E (allowed) and attempts submit.
        app_e, _ = create_application(
            sch_e["id"], student_headers=student_headers,
            uploaded_materials=["TRANSCRIPT"],
            student_family_income_cents=1_000_000,
        )
        resp = api_client.submit_application(
            sch_e["id"], app_e["id"], student_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DUPLICATE_APPLICATION_CROSS.value,
        )
