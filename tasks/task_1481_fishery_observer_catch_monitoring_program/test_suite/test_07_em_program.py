"""Electronic monitoring: enrollment uniqueness and termination guard, the
activation cascade, review-progress thresholding, catch extrapolation, and
the acceptance plan gate."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_notice_day_invariant,
    create_deployment_for_notice,
    create_em_enrollment_payload,
    create_em_trip_payload,
    make_completed_plan,
    make_coverage_plan,
    make_em_reviewer_headers,
    make_fishery,
    make_operator,
    make_vessel,
    make_vessel_operator_headers,
    publish_plan,
    record_pass_inspection,
    setup_em_active_vessel_scenario,
    setup_em_trip_in_review_scenario,
    setup_notice_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["program_coordinator_headers"]


def _setup_reviewed_trip(api, *, with_completed_plan):
    """EM-active vessel + trip in REVIEWED (40.00 of 100.00 hours, 120.50 kg
    sampled); optionally a SELECTION_COMPLETED plan covering the trip window."""
    bundle = setup_em_trip_in_review_scenario()
    plan = None
    if with_completed_plan:
        plan = make_completed_plan(
            bundle["fishery"],
            projected_fleet_effort_days=100,
            projected_em_effort_days=40,
        )
    rev = make_em_reviewer_headers(bundle["reviewer"]["id"])
    trip = validate_success(
        api.record_review(
            bundle["trip"]["id"],
            {"additional_reviewed_hours": 40.00, "sampled_catch_kg_delta": 120.50},
            rev,
        )
    )
    return bundle, plan, trip


class TestEMEnrollment:
    def test_second_open_enrollment_rejected(self, api, coordinator_headers):
        """PRD §3.8: "a vessel may hold only one open enrollment at a time —
        one in `PENDING_REVIEW`, `APPROVED`, `ACTIVE`, or `SUSPENDED` — and a
        second application against such a vessel is rejected with
        `ERR_EM_ENROLLMENT_OPEN_EXISTS`."

        Design: Corner/validations/em_enrollment_open_exists_uniqueness
        """
        fishery = make_fishery()
        operator = make_operator()
        vessel = make_vessel(operator, fishery)
        op = make_vessel_operator_headers(operator["id"])
        first = api.create_em_enrollment(
            create_em_enrollment_payload(vessel_id=vessel["id"]), op
        )
        validate_success(first, 201)
        dup = api.create_em_enrollment(
            create_em_enrollment_payload(
                vessel_id=vessel["id"], equipment_vendor="RivalCam LLC",
                equipment_install_date="2026-08-20T00:00:00Z",
            ),
            op,
        )
        validate_error(dup, ApiErrorId.ERR_EM_ENROLLMENT_OPEN_EXISTS, 409)
        rows, meta = validate_paginated(
            api.list_em_enrollments(coordinator_headers, params={"vessel_id": vessel["id"]})
        )
        assert meta["total_count"] == 1

    def test_terminate_blocked_while_trip_open(self, api, coordinator_headers):
        """PRD §3.8: "An administrator may suspend an active enrollment
        (`ACTIVE` → `SUSPENDED`), and may terminate one from either `ACTIVE` or
        `SUSPENDED` — termination is refused while any of the enrollment's
        trips remains in `DECLARED`, `FOOTAGE_SUBMITTED`, `IN_REVIEW`, or
        `REVIEWED` — which lands the enrollment in the terminal `TERMINATED`
        and flips the vessel's `monitoring_mode` back to `HUMAN_OBSERVER`."

        Design: Corner/state_machines/em_enrollment_terminate_blocked_while_trip_open
        """
        bundle = setup_em_active_vessel_scenario()
        op = make_vessel_operator_headers(bundle["operator"]["id"])
        trip = api.create_em_trip(
            create_em_trip_payload(vessel_id=bundle["vessel"]["id"]), op
        )
        validate_success(trip, 201)
        resp = api.terminate_em_enrollment(bundle["enrollment"]["id"], {}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        enrollment = validate_success(
            api.get_em_enrollment(bundle["enrollment"]["id"], coordinator_headers)
        )
        assert enrollment["status"] == "ACTIVE"
        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["monitoring_mode"] == "ELECTRONIC_MONITORING"


class TestEMActivationCascade:
    def _setup_with_ready_deployment(self, api):
        bundle = setup_notice_scenario(with_debriefer=False)
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], bundle["observer"]["id"])
        op = make_vessel_operator_headers(bundle["operator"]["id"])
        enrollment = validate_success(
            api.create_em_enrollment(
                create_em_enrollment_payload(vessel_id=bundle["vessel"]["id"]), op
            ),
            201,
        )
        validate_success(api.approve_em_enrollment(enrollment["id"], {}, ADMIN))
        return bundle, deployment, enrollment

    def test_activation_cascade_statuses(self, api, coordinator_headers):
        """PRD §2.10: "Activating a vessel's electronic-monitoring enrollment
        flips the vessel's `monitoring_mode` to `ELECTRONIC_MONITORING`, voids
        every open selection notice of that vessel (`ISSUED` or `ACCEPTED` →
        `VOIDED`), and cancels each deployment of a voided notice still in
        `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY`, releasing reserved
        days per §2.9."

        Design: Difficulty/transitive_cascade/em_activation_cascade_voids_notices_cancels_deployments_depth3
        """
        bundle, deployment, enrollment = self._setup_with_ready_deployment(api)
        activated = validate_success(api.activate_em_enrollment(enrollment["id"], {}, COORD))
        assert activated["status"] == "ACTIVE"

        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["monitoring_mode"] == "ELECTRONIC_MONITORING"
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["status"] == "VOIDED"
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "CANCELLED"

    def test_activation_cascade_releases_reserved_days(self, api, coordinator_headers):
        """PRD §2.10: "Activating a vessel's electronic-monitoring enrollment
        flips the vessel's `monitoring_mode` to `ELECTRONIC_MONITORING`, voids
        every open selection notice of that vessel (`ISSUED` or `ACCEPTED` →
        `VOIDED`), and cancels each deployment of a voided notice still in
        `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY`, releasing reserved
        days per §2.9." PRD §2.9: "Cancelling a deployment releases its
        reservation wholesale: `reserved_sea_days` drops by `planned_sea_days` and
        `remaining_sea_days` rises by the same."

        Design: Difficulty/transitive_cascade/em_activation_cascade_voids_notices_cancels_deployments_depth3
        """
        bundle, deployment, enrollment = self._setup_with_ready_deployment(api)
        validate_success(api.activate_em_enrollment(enrollment["id"], {}, COORD))
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["reserved_sea_days"] == 0
        assert notice["remaining_sea_days"] == 30
        assert notice["consumed_sea_days"] == 0
        assert notice["allocated_sea_days"] == 30
        assert_notice_day_invariant(notice)


class TestEMReviewThreshold:
    def test_below_threshold_stays_in_review(self, api, coordinator_headers):
        """PRD §3.8: "The moment `reviewed_pct` reaches 0.3000, the trip
        promotes itself `IN_REVIEW` → `REVIEWED` — 0.2999 stays `IN_REVIEW`,
        0.3000 promotes." and "Acceptance requires the trip to be `REVIEWED` —
        attempting it earlier yields `ERR_EM_REVIEW_MIN_NOT_MET`"

        Design: Difficulty/boundary_precision_check/em_reviewed_pct_02999_stays_03000_promotes
        """
        bundle = setup_em_trip_in_review_scenario()
        rev = make_em_reviewer_headers(bundle["reviewer"]["id"])
        recorded = validate_success(
            api.record_review(
                bundle["trip"]["id"],
                {"additional_reviewed_hours": 29.99, "sampled_catch_kg_delta": 50.0},
                rev,
            )
        )
        assert recorded["reviewed_pct"] == pytest.approx(0.2999, abs=1e-6)
        assert recorded["status"] == "IN_REVIEW"
        accept = api.accept_em_trip(bundle["trip"]["id"], {}, COORD)
        validate_error(accept, ApiErrorId.ERR_EM_REVIEW_MIN_NOT_MET, 409)

    def test_at_threshold_promotes_to_reviewed(self, api, coordinator_headers):
        """PRD §3.8: "Review then proceeds in increments: the assigned reviewer
        records batches of `additional_reviewed_hours` and
        `sampled_catch_kg_delta`, each call adding to `reviewed_hours` and
        `sampled_catch_kg` and recomputing `reviewed_pct` as `reviewed_hours`
        divided by `video_hours`, rounded half-up to four decimals." PRD §3.8: "The
        moment `reviewed_pct` reaches 0.3000, the trip promotes itself
        `IN_REVIEW` → `REVIEWED` — 0.2999 stays `IN_REVIEW`, 0.3000
        promotes."

        Design: Difficulty/boundary_precision_check/em_reviewed_pct_02999_stays_03000_promotes
        """
        bundle = setup_em_trip_in_review_scenario()
        rev = make_em_reviewer_headers(bundle["reviewer"]["id"])
        validate_success(
            api.record_review(
                bundle["trip"]["id"],
                {"additional_reviewed_hours": 29.99, "sampled_catch_kg_delta": 50.0},
                rev,
            )
        )
        promoted = validate_success(
            api.record_review(
                bundle["trip"]["id"],
                {"additional_reviewed_hours": 0.01, "sampled_catch_kg_delta": 0.0},
                rev,
            )
        )
        assert promoted["reviewed_hours"] == pytest.approx(30.00, abs=1e-6)
        assert promoted["reviewed_pct"] == pytest.approx(0.3000, abs=1e-6)
        assert promoted["status"] == "REVIEWED"


class TestEMAcceptanceOutputs:
    def test_reviewed_pct_and_extrapolated_catch_variants(self, api, coordinator_headers):
        """PRD §3.8: "On acceptance, the trip's `estimated_total_catch_kg` —
        null until this moment — is extrapolated as `sampled_catch_kg` scaled
        by `video_hours` over `reviewed_hours`, rounded half-up to two decimals,
        and the plan's `actual_em_sea_days` grows by `trip_sea_days`; the trip
        lands in the terminal `ACCEPTED`."

        Design: Difficulty/dual_variant_calc/em_review_progress_pct_vs_catch_extrapolation_variants
        """
        bundle, plan, trip = _setup_reviewed_trip(api, with_completed_plan=True)
        # 40.00 / 100.00 -> reviewed_pct 0.4000 (4-decimal variant).
        assert trip["reviewed_pct"] == pytest.approx(0.4000, abs=1e-6)
        assert trip["status"] == "REVIEWED"

        accepted = validate_success(api.accept_em_trip(trip["id"], {}, COORD))
        assert accepted["status"] == "ACCEPTED"
        # round_half_up(120.50 * 100.00 / 40.00, 2) == 301.25 (2-decimal
        # extrapolation variant, distinct value and precision from the ratio).
        assert accepted["estimated_total_catch_kg"] == pytest.approx(301.25, abs=1e-6)

    def test_accept_credits_plan_em_sea_days(self, api, coordinator_headers):
        """PRD §3.8: "On acceptance, the trip's `estimated_total_catch_kg` —
        null until this moment — is extrapolated as `sampled_catch_kg` scaled
        by `video_hours` over `reviewed_hours`, rounded half-up to two decimals,
        and the plan's `actual_em_sea_days` grows by `trip_sea_days`; the trip
        lands in the terminal `ACCEPTED`."

        Design: Difficulty/dual_variant_calc/em_review_progress_pct_vs_catch_extrapolation_variants
        """
        bundle, plan, trip = _setup_reviewed_trip(api, with_completed_plan=True)
        assert trip["trip_sea_days"] == 8
        accepted = validate_success(api.accept_em_trip(trip["id"], {}, COORD))
        assert accepted["status"] == "ACCEPTED"
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["actual_em_sea_days"] == 8


class TestEMAcceptancePlanGate:
    def test_accept_rejected_when_plan_only_published(self, api, coordinator_headers):
        """PRD §3.8: "Acceptance requires the trip to be `REVIEWED` —
        attempting it earlier yields `ERR_EM_REVIEW_MIN_NOT_MET` — and requires
        that exactly one coverage plan exists for the vessel's fishery whose
        window contains the trip's `departure_date` through `return_date` and
        whose status is `SELECTION_COMPLETED`; with no such unique plan the
        accept fails with `ERR_NO_COVERAGE_PLAN_FOR_TRIP`."

        Design: Difficulty/cross_entity_state_dependency/em_trip_accept_gated_on_selection_completed_plan
        """
        bundle, _, trip = _setup_reviewed_trip(api, with_completed_plan=False)
        # Plan exists and covers the trip window, but is only PUBLISHED.
        plan = make_coverage_plan(
            bundle["fishery"],
            projected_fleet_effort_days=100,
            projected_em_effort_days=40,
        )
        publish_plan(plan["id"])
        resp = api.accept_em_trip(trip["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_NO_COVERAGE_PLAN_FOR_TRIP, 409)
        current = validate_success(api.get_em_trip(trip["id"], coordinator_headers))
        assert current["status"] == "REVIEWED"
        plan = validate_success(api.get_coverage_plan(plan["id"], coordinator_headers))
        assert plan["actual_em_sea_days"] == 0

    def test_accept_rejected_when_plan_only_draft(self, api, coordinator_headers):
        """PRD §3.8: "Acceptance requires the trip to be `REVIEWED` —
        attempting it earlier yields `ERR_EM_REVIEW_MIN_NOT_MET` — and requires
        that exactly one coverage plan exists for the vessel's fishery whose
        window contains the trip's `departure_date` through `return_date` and
        whose status is `SELECTION_COMPLETED`; with no such unique plan the
        accept fails with `ERR_NO_COVERAGE_PLAN_FOR_TRIP`."

        Design: Difficulty/cross_entity_state_dependency/em_trip_accept_gated_on_selection_completed_plan
        """
        bundle, _, trip = _setup_reviewed_trip(api, with_completed_plan=False)
        # A DRAFT plan covering the window is not SELECTION_COMPLETED either.
        make_coverage_plan(
            bundle["fishery"],
            projected_fleet_effort_days=100,
            projected_em_effort_days=40,
        )
        resp = api.accept_em_trip(trip["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_NO_COVERAGE_PLAN_FOR_TRIP, 409)
        current = validate_success(api.get_em_trip(trip["id"], coordinator_headers))
        assert current["status"] == "REVIEWED"
