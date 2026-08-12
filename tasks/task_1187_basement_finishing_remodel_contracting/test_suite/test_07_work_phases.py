"""Work-phase sequencing: zone/dust-buffer, crew capacity, rough-in gate, DAG."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_inspection_payload,
    create_started_phase,
    create_work_phase_payload,
    get_success_data,
    make_contractor_headers,
    make_subcontractor_headers,
    register_subcontractor,
    setup_in_progress_project,
    setup_scheduling_project,
    validate_error,
    validate_success,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def _create_phase(api, project_id, ctr_h, sub_id, **overrides):
    return api.create_work_phase(
        project_id, create_work_phase_payload(sub_id, **overrides), ctr_h
    )


class TestZoneOverlapAndDrywallBuffer:
    def _setup_drywall_zone(self, api):
        """SCHEDULING project with a DRYWALL phase in REC_ROOM [06-01, 06-10)."""
        ctx = setup_scheduling_project(address="17 Q St", basement_sqft=1000,
                                       base_contract_cents=6000000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub1 = register_subcontractor(trade="DRYWALL", name="Dust Co")
        sub2 = register_subcontractor(trade="PAINT", name="Brush Co")
        wp1 = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="DRYWALL", zone="REC_ROOM",
                start_date="2026-06-01", end_date="2026-06-10", crew_count=2,
            ),
            201,
        )
        return ctx, ctr_h, sub2, wp1

    def test_drywall_buffer_rejects_adjacent_start(self, api):
        """PRD §3.6: "The dust buffer tightens this around drywall: when the existing
        same-zone phase is a `DRYWALL` phase, the new phase's `start_date` must fall
        at least two full days after that phase's `end_date`, mere adjacency being
        insufficient, and the buffer applies symmetrically when the existing drywall
        phase is scheduled after the new one."
        PRD §3.6: "two phases whose intervals merely touch, one ending exactly when
        the other begins, do not overlap; a collision is rejected with
        `ERR_ZONE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/zone_overlap_half_open_and_drywall_buffer
        """
        ctx, ctr_h, sub2, _wp1 = self._setup_drywall_zone(api)
        # Touching endpoint (start == existing end) is legal half-open adjacency for
        # other trades, but the DRYWALL buffer demands start >= 2026-06-12.
        res = _create_phase(
            api, ctx["project"]["id"], ctr_h, sub2["id"],
            trade="PAINT", zone="REC_ROOM",
            start_date="2026-06-10", end_date="2026-06-15", crew_count=1,
        )
        validate_error(res, ApiErrorId.ERR_ZONE_SCHEDULE_OVERLAP)

    def test_start_two_days_after_drywall_end_accepted(self, api):
        """PRD §3.6: "when the existing same-zone phase is a `DRYWALL` phase, the new
        phase's `start_date` must fall at least two full days after that phase's
        `end_date`"
        PRD §3.6: "A phase created with an empty `predecessor_ids` starts life
        `READY`"

        Design: Difficulty/resource_temporal_overlap/zone_overlap_half_open_and_drywall_buffer
        """
        ctx, ctr_h, sub2, _wp1 = self._setup_drywall_zone(api)
        wp2 = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub2["id"],
                trade="PAINT", zone="REC_ROOM",
                start_date="2026-06-12", end_date="2026-06-18", crew_count=1,
            ),
            201,
        )
        assert wp2["status"] == "READY"
        phases = api.list_work_phases(ctx["project"]["id"], ctr_h).json()["data"]
        in_zone = [p for p in phases if p["zone"] == "REC_ROOM"]
        assert len(in_zone) == 2


class TestDailyCrewCapacity:
    def _setup_two_crews(self, api):
        """SCHEDULING project; phase A (crew 2, Z1, [06-01,06-10)) and phase B
        (crew 2, Z2, [06-05,06-12)) — daily sum exactly 4 on the shared dates."""
        ctx = setup_scheduling_project(address="18 R St", basement_sqft=1100,
                                       base_contract_cents=6500000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub1 = register_subcontractor(trade="FRAMING", name="Frame Co")
        sub2 = register_subcontractor(trade="PLUMBING", name="Pipe Co")
        sub3 = register_subcontractor(trade="ELECTRICAL", name="Wire2 Co")
        wp_a = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="FRAMING", zone="Z1",
                start_date="2026-06-01", end_date="2026-06-10", crew_count=2,
            ),
            201,
        )
        wp_b = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub2["id"],
                trade="PLUMBING", zone="Z2",
                start_date="2026-06-05", end_date="2026-06-12", crew_count=2,
            ),
            201,
        )
        return ctx, ctr_h, sub3, wp_a, wp_b

    def test_crew_sum_exactly_four_accepted(self, api):
        """PRD §3.6: "on every calendar date covered by the new phase's interval, the
        summed `crew_count` of all non-`CANCELLED` phases of the project covering
        that date, including the new phase, must not exceed 4 — a sum of exactly 4 is
        permitted — or creation is rejected with `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/daily_crew_capacity_aggregate
        """
        ctx, ctr_h, _sub3, wp_a, wp_b = self._setup_two_crews(api)
        # Both creations succeeded above: the inclusive cap allows sum == 4.
        assert wp_a["status"] == "READY"
        assert wp_b["status"] == "READY"

    def test_five_crew_on_a_date_rejected_then_non_overlapping_accepted(self, api):
        """PRD §3.6: "must not exceed 4 — a sum of exactly 4 is permitted — or
        creation is rejected with `ERR_CREW_CAPACITY_EXCEEDED`. The cap is
        project-wide per day, with no per-zone decomposition, and dates are whole
        days."

        Design: Difficulty/resource_temporal_overlap/daily_crew_capacity_aggregate
        """
        ctx, ctr_h, sub3, _a, _b = self._setup_two_crews(api)
        # [06-06, 06-08) overlaps both existing intervals: 2 + 2 + 1 = 5 > 4.
        res = _create_phase(
            api, ctx["project"]["id"], ctr_h, sub3["id"],
            trade="ELECTRICAL", zone="Z3",
            start_date="2026-06-06", end_date="2026-06-08", crew_count=1,
        )
        validate_error(res, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)

        # [06-12, 06-20) starts when B's half-open interval has ended; only crew 1.
        wp_c = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub3["id"],
                trade="ELECTRICAL", zone="Z3",
                start_date="2026-06-12", end_date="2026-06-20", crew_count=1,
            ),
            201,
        )
        assert wp_c["status"] == "READY"


class TestRoughInGate:
    def _setup_electrical_in_progress(self, api):
        """IN_PROGRESS project with a started ELECTRICAL phase (requires rough-in)."""
        ctx = setup_in_progress_project(
            trade="ELECTRICAL", zone="MEDIA", address="16 P St",
            basement_sqft=900, base_contract_cents=5200000,
            phase_overrides={"start_date": "2026-06-01", "end_date": "2026-06-10"},
        )
        return ctx

    def _request_rough_in(self, api, ctx, outcome=None):
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        insp = get_success_data(
            api.create_inspection(
                ctx["project"]["id"],
                create_inspection_payload(
                    type="ROUGH_IN", work_phase_id=ctx["phase"]["id"]
                ),
                ctr_h,
            )
        )
        if outcome:
            validate_success(
                api.record_inspection_result(insp["id"], {"outcome": outcome},
                                             INSPECTOR),
                200,
            )
        return insp

    def test_rough_in_trade_completion_blocked_until_inspection_passed(self, api):
        """PRD §3.6: "The derived `requires_rough_in` flag is true exactly when the
        trade is `PLUMBING`, `ELECTRICAL`, or `HVAC`."
        PRD §3.6: "when `requires_rough_in` is true, a `PASSED` rough-in inspection
        tied to this phase through its `work_phase_id` must already exist, otherwise
        completion is rejected with `ERR_ROUGH_IN_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/rough_in_trade_completion_blocked_until_inspection_passed
        """
        ctx = self._setup_electrical_in_progress(api)
        assert ctx["phase"]["requires_rough_in"] is True
        sub_h = make_subcontractor_headers(ctx["subcontractor"]["id"])
        self._request_rough_in(api, ctx, outcome="FAILED")
        self._request_rough_in(api, ctx)  # second request still outstanding

        res = api.complete_work_phase(ctx["phase"]["id"], sub_h)
        validate_error(res, ApiErrorId.ERR_ROUGH_IN_REQUIRED)

    def test_completion_succeeds_after_rough_in_passed(self, api):
        """PRD §3.6: "Completion moves an `IN_PROGRESS` phase to `COMPLETED` under the
        same ownership rule, with one trade-specific gate: when `requires_rough_in`
        is true, a `PASSED` rough-in inspection tied to this phase through its
        `work_phase_id` must already exist, otherwise completion is rejected with
        `ERR_ROUGH_IN_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/rough_in_trade_completion_blocked_until_inspection_passed
        """
        ctx = self._setup_electrical_in_progress(api)
        sub_h = make_subcontractor_headers(ctx["subcontractor"]["id"])
        self._request_rough_in(api, ctx, outcome="FAILED")
        insp2 = self._request_rough_in(api, ctx)
        validate_success(
            api.record_inspection_result(insp2["id"], {"outcome": "PASSED"},
                                         INSPECTOR),
            200,
        )
        completed = validate_success(
            api.complete_work_phase(ctx["phase"]["id"], sub_h), 200
        )
        assert completed["status"] == "COMPLETED"


class TestPhaseGraph:
    def test_predecessor_promotion_on_completion(self, api):
        """PRD §3.6: "A phase created with an empty `predecessor_ids` starts life
        `READY`; one with predecessors starts `PLANNED` and is promoted to `READY` by
        the system when its last incomplete predecessor completes."
        PRD §3.6: "the first phase start on a `SCHEDULING` project moves the project
        itself to `IN_PROGRESS`."

        Design: Corner/state_machines/phase_predecessor_promotion_on_completion
        """
        ctx = setup_scheduling_project(address="14 Corner Way", basement_sqft=900,
                                       base_contract_cents=5000000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub1 = register_subcontractor(trade="FRAMING", name="Frame C14")
        sub2 = register_subcontractor(trade="DRYWALL", name="Dust C14")
        wp_a = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="FRAMING", zone="REC",
                start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
            ),
            201,
        )
        assert wp_a["status"] == "READY"
        wp_b = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub2["id"],
                trade="DRYWALL", zone="REC",
                start_date="2026-06-10", end_date="2026-06-18", crew_count=2,
                predecessor_ids=[wp_a["id"]],
            ),
            201,
        )
        assert wp_b["status"] == "PLANNED"

        sub1_h = make_subcontractor_headers(sub1["id"])
        validate_success(api.start_work_phase(wp_a["id"], sub1_h), 200)
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["status"] == "IN_PROGRESS"
        validate_success(api.complete_work_phase(wp_a["id"], sub1_h), 200)
        wp_b_after = get_success_data(api.get_work_phase(wp_b["id"], ctr_h))
        assert wp_b_after["status"] == "READY"

    def test_work_phase_cancel_from_ready_excluded_from_overlap(self, api):
        """PRD §3.6: "The contractor may cancel a phase only while it is `PLANNED` or
        `READY`, optionally giving a `reason`, and only for a project they own
        (`ERR_NOT_RESOURCE_OWNER`)."
        PRD §3.6: "the new phase's interval must not intersect any non-`CANCELLED`
        phase's interval in the same zone"

        Design: Corner/state_machines/work_phase_cancel_from_ready
        """
        ctx = setup_scheduling_project(address="15 Corner Way", basement_sqft=900,
                                       base_contract_cents=5000000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub1 = register_subcontractor(trade="FRAMING", name="Frame C15")
        wp_a = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="FRAMING", zone="REC",
                start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
            ),
            201,
        )
        cancelled = validate_success(
            api.cancel_work_phase(wp_a["id"], {"reason": "scope removed"}, ctr_h), 200
        )
        assert cancelled["status"] == "CANCELLED"
        # The cancelled phase no longer blocks the same zone/interval.
        wp_b = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="FRAMING", zone="REC",
                start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
            ),
            201,
        )
        assert wp_b["status"] == "READY"

    def test_cancelled_phase_rejected_as_predecessor(self, api):
        """PRD §3.6: "every entry in `predecessor_ids` must reference an existing,
        non-`CANCELLED` phase of the same project, and adding an edge from each
        predecessor to the new phase must keep the project's phase graph acyclic —
        any path leading from the new phase back to one of its predecessors through
        existing edges rejects the creation with `ERR_PHASE_CYCLE`."

        Design: Corner/validations/phase_cancelled_predecessor_rejected
        """
        ctx = setup_scheduling_project(address="V1 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        sub1 = register_subcontractor(trade="FRAMING", name="Frame V1")
        wp_a = validate_success(
            _create_phase(
                api, ctx["project"]["id"], ctr_h, sub1["id"],
                trade="FRAMING", zone="Z1",
                start_date="2026-06-01", end_date="2026-06-08", crew_count=2,
            ),
            201,
        )
        validate_success(
            api.cancel_work_phase(wp_a["id"], {"reason": "decommit"}, ctr_h), 200
        )
        res = _create_phase(
            api, ctx["project"]["id"], ctr_h, sub1["id"],
            trade="DRYWALL", zone="Z2",
            start_date="2026-06-10", end_date="2026-06-15", crew_count=2,
            predecessor_ids=[wp_a["id"]],
        )
        validate_error(res, ApiErrorId.ERR_PHASE_CYCLE)
