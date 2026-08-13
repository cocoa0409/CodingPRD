"""Lighting plots and rigging points: factored-load computation, capacity
boundaries, the review/revision loops, empty-plot gating, the engineering
deadline, and the two optimistic-concurrency guards."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_planning_production, create_plot, get_plot, add_rigging_point,
    get_rigging_point, submit_plot, approve_plot, transition_point,
    submit_point_for_review, approve_point, set_clock,
    create_rigging_point_payload, create_plot_payload,
)

PM = TEST_USERS["production_manager_headers"]
RIG = TEST_USERS["rigging_supervisor_headers"]
ENG = TEST_USERS["structural_engineer_headers"]


class TestFactoredLoadConditionalFactors:
    def test_factored_load_bridle_vs_straight(self, api):
        """PRD §3.3: "The base load is the `deadweight_kg` multiplied by a dynamic factor that depends on the hang geometry: 1.10 for `STRAIGHT` hangs, 1.10 for `BRIDLE` hangs, and 1.00 for `DEAD_HANG`. To that base the system adds the self-weight of the chain motors — the `motor_count` multiplied by 20 kilograms per motor. For a `BRIDLE` hang, and only for a `BRIDLE` hang, the combined base-plus-motors figure is then multiplied by a 1.15 uncertainty factor; `STRAIGHT` and `DEAD_HANG` points stop at base plus motors."

        Design: Difficulty/combinatorial_formula/rigging_factored_load_conditional_factors
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        # BRIDLE: (100 x 1.10 + 2 x 20) x 1.15 = 172.50 kg; utilization 172.5/500 = 0.3450.
        bridle = add_rigging_point(plot["id"], point_label="B1", hang_type="BRIDLE",
                                   motor_count=2, deadweight_kg=100)
        assert bridle["factored_load_kg"] == pytest.approx(172.50, abs=0.001)
        assert bridle["utilization"] == pytest.approx(0.3450, abs=0.00005)
        mid_plot = get_plot(plot["id"])
        assert mid_plot["total_factored_load_kg"] == pytest.approx(172.50, abs=0.001)
        # STRAIGHT with identical numerics: 100 x 1.10 + 40 = 150.00 kg (no 1.15 hop).
        straight = add_rigging_point(plot["id"], point_label="S1", hang_type="STRAIGHT",
                                     motor_count=2, deadweight_kg=100)
        assert straight["factored_load_kg"] == pytest.approx(150.00, abs=0.001)
        assert straight["utilization"] == pytest.approx(0.3000, abs=0.00005)

    def test_factored_load_dead_hang_counts_motor_self_weight(self, api):
        """PRD §3.3: "To that base the system adds the self-weight of the chain motors — the `motor_count` multiplied by 20 kilograms per motor."

        Design: Difficulty/combinatorial_formula/rigging_factored_load_conditional_factors
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        # DEAD_HANG: 200 x 1.00 + 3 x 20 = 260.00 kg; utilization 260/500 = 0.5200.
        point = add_rigging_point(plot["id"], point_label="D1", hang_type="DEAD_HANG",
                                  motor_count=3, deadweight_kg=200)
        assert point["factored_load_kg"] == pytest.approx(260.00, abs=0.001)
        assert point["utilization"] == pytest.approx(0.5200, abs=0.00005)


class TestPointCapacityBoundary:
    def test_point_load_exactly_at_capacity_passes(self, api):
        """PRD §3.3: "The point capacity check permits the factored load to equal the venue's per-point limit exactly; a factored load strictly greater than `max_point_capacity_kg` rejects the reservation with `ERR_POINT_OVERLOAD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/rigging_utilization_exactly_one_passes
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        ok = add_rigging_point(plot["id"], point_label="EDGE-OK", deadweight_kg=500.00)
        assert ok["utilization"] == pytest.approx(1.0000, abs=0.00005)
        assert ok["status"] == "RESERVED"
        resp = api.create_rigging_point(
            plot["id"],
            create_rigging_point_payload(get_plot(plot["id"])["version"],
                                         point_label="EDGE-FAIL", deadweight_kg=500.01),
            RIG)
        validate_error(resp, ApiErrorId.ERR_POINT_OVERLOAD)
        points, meta = validate_paginated(api.list_plot_rigging_points(plot["id"], PM))
        assert meta["total_count"] == 1, "the overloaded point must not persist"

    def test_point_load_just_below_capacity_passes(self, api):
        """PRD §3.3: "The point capacity check permits the factored load to equal the venue's per-point limit exactly; a factored load strictly greater than `max_point_capacity_kg` rejects the reservation with `ERR_POINT_OVERLOAD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/rigging_utilization_exactly_one_passes
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"], point_label="UNDER", deadweight_kg=499.95)
        assert point["factored_load_kg"] == pytest.approx(499.95, abs=0.001)
        assert point["utilization"] == pytest.approx(0.9999, abs=0.00005)
        assert point["status"] == "RESERVED"


class TestPlotRevisionCycle:
    def test_plot_revision_cycle_reject_resubmit_approve(self, api):
        """PRD §3.3: "An engineer may also return the plot to drafting (`SUBMITTED` → `DRAFT`) — a rejection that requires a `rejection_reason` in the payload, its absence rejected with `ERR_INVALID_REQUEST` — and the reason is stored on the plot until a later resubmission clears it."
        PRD §3.3: "Approval stamps `approved_by_user_id` with the engineer's `X-User-ID` and `approved_at` with the logical clock, then fires the supersede cascade: any other `APPROVED` plot of the same production moves to `SUPERSEDED`, and every rigging point on that superseded plot with status `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` moves to `RELEASED`, which recomputes the superseded plot's `total_factored_load_kg` to 0."

        Design: Difficulty/non_linear_state_machine/lighting_plot_revision_cycle
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        add_rigging_point(plot["id"])
        data = submit_plot(plot["id"])
        assert data["status"] == "SUBMITTED"
        resp = api.transition_plot(plot["id"],
                                   {"to": "DRAFT", "rejection_reason": "Trim heights missing"},
                                   ENG)
        data = validate_success(resp)
        assert data["status"] == "DRAFT"
        assert data["rejection_reason"] == "Trim heights missing"
        data = submit_plot(plot["id"])
        assert data["status"] == "SUBMITTED"
        assert data.get("rejection_reason") is None, "resubmit clears the stored reason"
        data = approve_plot(plot["id"], engineer_id="eng-1")
        assert data["status"] == "APPROVED"
        assert data["approved_by_user_id"] == "eng-1"

    def test_plot_reject_requires_rejection_reason(self, api):
        """PRD §3.3: "An engineer may also return the plot to drafting (`SUBMITTED` → `DRAFT`) — a rejection that requires a `rejection_reason` in the payload, its absence rejected with `ERR_INVALID_REQUEST` — and the reason is stored on the plot until a later resubmission clears it."

        Design: Difficulty/non_linear_state_machine/lighting_plot_revision_cycle
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        resp = api.transition_plot(plot["id"], {"to": "DRAFT"}, ENG)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_plot(plot["id"])
        assert after["status"] == "SUBMITTED"


class TestRiggingPointRejectReviseCycle:
    def test_point_reject_revise_approve_cycle(self, api):
        """PRD §3.3: "The engineer may instead reject the point (`UNDER_REVIEW` → `REJECTED`), and the supervisor may then revise it (`REJECTED` → `RESERVED`) by supplying new `deadweight_kg` and `motor_count` values; the revision recomputes `factored_load_kg` and `utilization`, re-applies the per-point capacity check with the same equality-passes rule (`ERR_POINT_OVERLOAD` on failure), and refreshes the plot's `total_factored_load_kg`."

        Design: Difficulty/non_linear_state_machine/rigging_point_reject_revise_cycle
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"], deadweight_kg=450)
        submit_plot(plot["id"])
        submit_point_for_review(point["id"])
        data = validate_success(api.transition_rigging_point(point["id"], {"to": "REJECTED"}, ENG))
        assert data["status"] == "REJECTED"
        data = transition_point(point["id"],
                                {"to": "RESERVED", "deadweight_kg": 400, "motor_count": 0})
        assert data["status"] == "RESERVED"
        assert data["factored_load_kg"] == pytest.approx(400.00, abs=0.001), \
            "DEAD_HANG factor 1.00 with no motors recomputes to the raw deadweight"
        submit_point_for_review(point["id"])
        data = approve_point(point["id"], engineer_id="eng-1")
        assert data["status"] == "APPROVED"
        assert data["reviewed_by_user_id"] == "eng-1"

    def test_point_revise_over_capacity_rejected(self, api):
        """PRD §3.3: "The engineer may instead reject the point (`UNDER_REVIEW` → `REJECTED`), and the supervisor may then revise it (`REJECTED` → `RESERVED`) by supplying new `deadweight_kg` and `motor_count` values; the revision recomputes `factored_load_kg` and `utilization`, re-applies the per-point capacity check with the same equality-passes rule (`ERR_POINT_OVERLOAD` on failure), and refreshes the plot's `total_factored_load_kg`."

        Design: Difficulty/non_linear_state_machine/rigging_point_reject_revise_cycle
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"], deadweight_kg=450)
        submit_plot(plot["id"])
        submit_point_for_review(point["id"])
        validate_success(api.transition_rigging_point(point["id"], {"to": "REJECTED"}, ENG))
        resp = api.transition_rigging_point(
            point["id"], {"to": "RESERVED", "deadweight_kg": 600, "motor_count": 0}, RIG)
        validate_error(resp, ApiErrorId.ERR_POINT_OVERLOAD)
        after = get_rigging_point(point["id"])
        assert after["status"] == "REJECTED"


class TestEmptyPlotSubmit:
    def test_submit_empty_plot_rejected_then_succeeds_with_one_point(self, api):
        """PRD §3.3: "Submission requires the production to be `PLANNING` (otherwise `ERR_INVALID_STATE`) and requires at least one rigging point in `RESERVED`, `UNDER_REVIEW`, or `APPROVED` status — submitting an empty plot is rejected with `ERR_EMPTY_PLOT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/plot_submit_empty_rejected
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        resp = api.transition_plot(plot["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PLOT)
        assert get_plot(plot["id"])["status"] == "DRAFT"
        add_rigging_point(plot["id"])
        data = submit_plot(plot["id"])
        assert data["status"] == "SUBMITTED"

    def test_submit_plot_with_only_released_point_rejected(self, api):
        """PRD §3.3: "Submission requires the production to be `PLANNING` (otherwise `ERR_INVALID_STATE`) and requires at least one rigging point in `RESERVED`, `UNDER_REVIEW`, or `APPROVED` status — submitting an empty plot is rejected with `ERR_EMPTY_PLOT` (HTTP 422)."
        PRD §3.3: "A supervisor may also release a point outright from `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED`; every release recomputes the plot's `total_factored_load_kg` and frees the `point_label`."

        Design: Difficulty/boundary_precision_check/plot_submit_empty_rejected
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        transition_point(point["id"], {"to": "RELEASED"})
        resp = api.transition_plot(plot["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PLOT)


class TestEngineeringDeadlinePriority:
    def test_engineering_deadline_beats_plot_not_submitted(self, api):
        """PRD §2.6: "Every write request is evaluated against a fixed pipeline of check categories, and a request that fails an earlier category reports that error without ever reaching a later one." (category 12, temporal deadlines, precedes category 13, referential prerequisites).
        PRD §3.3: "the logical clock must not have passed the engineering deadline — submission must occur at or before `load_in_at` minus the venue's `engineering_submission_lead_hours`, else `ERR_ENGINEERING_DEADLINE_PASSED` (HTTP 422) — and the point's plot must be `SUBMITTED` or `APPROVED`, else `ERR_PLOT_NOT_SUBMITTED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_over_referential_on_engineering_submit
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        # Deadline is 2026-09-01T08:00 - 72h = 2026-08-29T08:00; clock is one day past it.
        set_clock("2026-08-30T08:00:00Z")
        resp = api.transition_rigging_point(point["id"], {"to": "UNDER_REVIEW"}, RIG)
        validate_error(resp, ApiErrorId.ERR_ENGINEERING_DEADLINE_PASSED)
        assert get_rigging_point(point["id"])["status"] == "RESERVED"

    def test_engineering_submission_at_exact_deadline_passes(self, api):
        """PRD §3.3: "A `RiggingSupervisor` submits a `RESERVED` point for review (`RESERVED` → `UNDER_REVIEW`), which is gated on two preconditions: the logical clock must not have passed the engineering deadline — submission must occur at or before `load_in_at` minus the venue's `engineering_submission_lead_hours`, else `ERR_ENGINEERING_DEADLINE_PASSED` (HTTP 422) — and the point's plot must be `SUBMITTED` or `APPROVED`, else `ERR_PLOT_NOT_SUBMITTED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_over_referential_on_engineering_submit
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        set_clock("2026-08-29T08:00:00Z")  # exactly load_in_at - 72h: "at or before" passes
        data = submit_point_for_review(point["id"])
        assert data["status"] == "UNDER_REVIEW"


class TestOptimisticConcurrencyGuards:
    def test_occ_plot_create_stale_production_version(self, api):
        """PRD §2.5: "Creating a lighting plot under a production requires the request to include `expected_production_version`, matching the production's current `version`. If the production's version has advanced since the client last read it — for example because another plot was created against it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the production before drafting."

        Design: Corner/errors/occ_plot_create_stale_production_version
        """
        ctx = setup_planning_production()
        observed_version = ctx["production"]["version"]
        payload = create_plot_payload(observed_version, title="Rig v1")
        validate_success(api.create_plot(ctx["production"]["id"], payload, PM),
                         expected_status=201)
        resp = api.create_plot(ctx["production"]["id"],
                               create_plot_payload(observed_version, title="Rig v2"), PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_point_reserve_stale_plot_version(self, api):
        """PRD §2.5: "Reserving a rigging point on a plot requires the request to include `expected_plot_version`, matching the plot's current `version`. Every point reservation mutates the plot — the recomputed `total_factored_load_kg` advances the plot's `version` — so a client holding a stale load picture is rejected with `ERR_STALE_VERSION` (HTTP 412) and must re-read the plot before adding more load."

        Design: Corner/errors/occ_point_reserve_stale_plot_version
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        stale_version = plot["version"]
        validate_success(api.create_rigging_point(
            plot["id"], create_rigging_point_payload(stale_version, point_label="A1"), RIG),
            expected_status=201)
        resp = api.create_rigging_point(
            plot["id"], create_rigging_point_payload(stale_version, point_label="A2"), RIG)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
