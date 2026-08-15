"""Site visits: the 30-day minimum-gap buffer (both directions, any status)
and completion terminality."""
from test_helpers import (
    ApiErrorId,
    assert_site_visit,
    create_site_visit_payload,
    onboard_association,
    schedule_and_complete_visit,
    schedule_visit,
    validate_error,
    validate_success,
)


class TestSiteVisitGapBoundary:
    def test_visit_twenty_nine_days_apart_rejected(
            self, api, association_manager_headers):
        """PRD §3.2: "the new date must sit at least thirty days away from
        every other visit of the association in either direction; visits of
        any status count toward the gap, a spacing of exactly thirty days is
        acceptable, and a tighter gap is rejected with
        `ERR_SITE_VISIT_TOO_SOON`."

        Design: Difficulty/boundary_precision_check/site_visit_exact_min_gap_boundary
        """
        association = onboard_association("CA", name="Gap HOA")
        schedule_visit(association["id"], "2026-01-15")
        res = api.create_site_visit(
            create_site_visit_payload(association["id"], "2026-02-13"),
            association_manager_headers)
        validate_error(res, ApiErrorId.ERR_SITE_VISIT_TOO_SOON)

    def test_visit_exactly_thirty_days_apart_accepted(
            self, api, association_manager_headers):
        """PRD §3.2: "the new date must sit at least thirty days away from
        every other visit of the association in either direction; visits of
        any status count toward the gap, a spacing of exactly thirty days is
        acceptable, and a tighter gap is rejected with
        `ERR_SITE_VISIT_TOO_SOON`."

        Design: Difficulty/boundary_precision_check/site_visit_exact_min_gap_boundary
        """
        association = onboard_association("CA", name="Gap2 HOA")
        schedule_visit(association["id"], "2026-01-15")
        visit = validate_success(api.create_site_visit(
            create_site_visit_payload(association["id"], "2026-02-14"),
            association_manager_headers), 201)
        assert_site_visit(visit)
        assert visit["status"] == "SCHEDULED", (
            "exactly 30 days satisfies the >= gap; got "
            f"{visit['status']}")


class TestSiteVisitGapBuffer:
    def test_visit_five_days_after_existing_rejected(
            self, api, association_manager_headers):
        """PRD §3.2: "the new date must sit at least thirty days away from
        every other visit of the association in either direction; visits of
        any status count toward the gap, a spacing of exactly thirty days is
        acceptable, and a tighter gap is rejected with
        `ERR_SITE_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/site_visit_min_gap_buffer
        """
        association = onboard_association("CA", name="Buffer HOA")
        schedule_visit(association["id"], "2026-01-15")
        res = api.create_site_visit(
            create_site_visit_payload(association["id"], "2026-01-20"),
            association_manager_headers)
        validate_error(res, ApiErrorId.ERR_SITE_VISIT_TOO_SOON)

    def test_visit_five_days_before_completed_visit_rejected(
            self, api, association_manager_headers):
        """PRD §3.2: "the new date must sit at least thirty days away from
        every other visit of the association in either direction; visits of
        any status count toward the gap, a spacing of exactly thirty days is
        acceptable, and a tighter gap is rejected with
        `ERR_SITE_VISIT_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/site_visit_min_gap_buffer
        """
        association = onboard_association("CA", name="Buffer2 HOA")
        schedule_and_complete_visit(association["id"], "2026-01-15")
        res = api.create_site_visit(
            create_site_visit_payload(association["id"], "2026-01-10"),
            association_manager_headers)
        validate_error(res, ApiErrorId.ERR_SITE_VISIT_TOO_SOON)


class TestSiteVisitCompletion:
    def test_site_visit_complete_twice_rejected(
            self, api, association_manager_headers):
        """PRD §2.8: "The addressed entity sits in the state the action
        requires: the study `DRAFT` or `SUBMITTED` as the operation demands
        (surfacing `ERR_INVALID_STATE` or `ERR_STUDY_NOT_DRAFT`), the plan in
        a compatible status, the visit `SCHEDULED`, the expenditure
        `SUBMITTED` or `APPROVED`, the disclosure `PENDING`, exactly one
        `SELECTED` plan at adoption (`ERR_NO_PLAN_SELECTED`)." and PRD §3.2:
        "Completing the visit stamps `completed_at` from the logical clock,
        moves it to `COMPLETED`, and recomputes the association's
        `next_site_visit_due_date` as the most recent completed `visit_date`
        plus the statutory cadence window — 365 days per year of
        `site_visit_interval_years` — leaving it null when no completed visit
        exists yet; the association's `version` advances with the recompute."

        Design: Corner/state_machines/site_visit_complete_twice_rejected
        """
        association = onboard_association("CA", name="Visit HOA")
        visit = schedule_and_complete_visit(association["id"], "2026-06-30")
        assert visit["status"] == "COMPLETED"

        res = api.complete_site_visit(visit["id"], association_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
