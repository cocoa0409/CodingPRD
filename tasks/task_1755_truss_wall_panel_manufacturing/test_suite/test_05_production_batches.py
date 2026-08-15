"""Production: cut-list release guards, batch lifecycle, QC loop, build sequencing."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_jig,
    make_batch,
    make_sealed_design,
    explode_cut_list,
    cut_list_line_payload,
    reserve_lumber,
    reserve_plates,
    reserve_standard_cl1,
    seal_revision,
    setup_confirmed_job,
    setup_sealed_roof_design,
    setup_released_cl1,
    setup_batch_built,
    setup_production_preamble,
    create_batch_payload,
    batch_fresh,
    cut_list_fresh,
    line_fresh,
    lot_fresh,
    job_fresh,
    reservation_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
SFL = TEST_USERS["shop_floor_lead_headers"]


class TestBatchCuttingRequiresReleasedListAndCoverage:
    def test_batch_create_on_exploded_list_rejected(self, api):
        """PRD §3.6: "A `ProductionPlanner` schedules production batches against a
        job, naming a `cut_list_id` that must be `RELEASED` (else
        `ERR_CUT_LIST_NOT_RELEASED`)".

        Design: Difficulty/cross_entity_state_dependency/batch_cutting_requires_released_list_and_coverage
        """
        ns = setup_sealed_roof_design(job_name="Coverage Job", contract=100000)
        ns.jig_roof = make_jig()
        cl1, _ = explode_cut_list(ns.dsg1["id"], ns.jig_roof["id"],
                                  [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        resp = api.create_batch(ns.job["id"], create_batch_payload(cl1["id"], ns.jig_roof["id"]), PP)
        validate_error(resp, ApiErrorId.ERR_CUT_LIST_NOT_RELEASED)
        assert cut_list_fresh(cl1["id"])["status"] == "EXPLODED"

    def test_cutting_coverage_shortfall_then_exact_topup(self, api):
        """PRD §3.6: "coverage must be complete — every line of the cut list still in
        `PENDING` must have its `RESERVED` lumber reservations summing to at least the
        line's `required_board_feet`, and the cut list's `RESERVED` plate reservations
        must sum to at least the list's `total_plates` — else
        `ERR_RESERVATION_COVERAGE_SHORT` (HTTP 422). Entering `CUTTING` consumes the
        coverage: every `RESERVED` lumber reservation on the cut list's lines and
        every `RESERVED` plate reservation on the list move to `CONSUMED`".

        Design: Difficulty/cross_entity_state_dependency/batch_cutting_requires_released_list_and_coverage
        """
        ns = setup_released_cl1(job_name="Coverage Job", contract=100000)
        bat = make_batch(ns.job["id"], ns.cl1["id"], ns.jig_roof["id"])
        # Lumber coverage 125.99 < required 126.00 on the TC-1 line.
        r1 = reserve_lumber(ns.lots.lot6["id"], ns.lines["TC-1"]["id"], 125.99)
        r2 = reserve_lumber(ns.lots.lot4["id"], ns.lines["BC-1"]["id"], 72.67)
        r3 = reserve_plates(ns.lots.plot["id"], ns.cl1["id"], 280)
        resp = api.transition_batch(bat["id"], {"to_state": "CUTTING"}, SFL)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_COVERAGE_SHORT)

        # A 0.01 bf top-up reaches exactly 126.00; "at least" admits equality.
        reserve_lumber(ns.lots.lot6["id"], ns.lines["TC-1"]["id"], 0.01)
        cutting = validate_success(api.transition_batch(bat["id"], {"to_state": "CUTTING"}, SFL))
        assert cutting["status"] == "CUTTING"
        for r in (r1, r2, r3):
            assert reservation_fresh(r["id"])["status"] == "CONSUMED", \
                "entering CUTTING auto-consumes the covering reservations"
        lot = lot_fresh(ns.lots.lot6["id"])
        assert lot["consumed_bf"] == pytest.approx(126.00)
        assert lot["reserved_bf"] == pytest.approx(0)


class TestBatchCuttingSafetyBeatsCoverage:
    def _setup_stale_design(self, with_coverage):
        """cl1 RELEASED off TR-01 r1, batch SCHEDULED, then r2 sealed so r1 is stale."""
        ns = setup_released_cl1(job_name="Prio Job", contract=100000)
        if with_coverage:
            reserve_standard_cl1(ns.lots, ns.lines, ns.cl1["id"])
        ns.bat1 = make_batch(ns.job["id"], ns.cl1["id"], ns.jig_roof["id"])
        ns.dsg1r2 = seal_revision(ns.job["id"], ns.eng1, ns.eng2, ns.dsg1,
                                  design_load_psf=42.0)
        return ns

    def test_stale_design_with_zero_coverage_reports_design_not_current(self, api):
        """PRD §3.6: "Entering `CUTTING` from `SCHEDULED` is the heaviest gate in the
        plant and its checks run in a fixed order" and "the cut list's design must be
        `SEALED` and current, else `ERR_DESIGN_NOT_CURRENT`; the job must be
        `IN_PRODUCTION`; and coverage must be complete — every line of the cut list
        still in `PENDING` must have its `RESERVED` lumber reservations summing to at
        least the line's `required_board_feet`, and the cut list's `RESERVED` plate
        reservations must sum to at least the list's `total_plates` — else
        `ERR_RESERVATION_COVERAGE_SHORT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/batch_cutting_safety_beats_coverage_constraint
        """
        ns = self._setup_stale_design(with_coverage=False)
        # Both the design-currency guard and the coverage guard fail; the design
        # guard is named earlier in the fixed order and must be the reported one.
        resp = api.transition_batch(ns.bat1["id"], {"to_state": "CUTTING"}, SFL)
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_CURRENT)
        assert batch_fresh(ns.bat1["id"])["status"] == "SCHEDULED"

    def test_stale_design_with_full_coverage_reports_design_not_current(self, api):
        """PRD §3.6: "the cut list's design must be `SEALED` and current, else
        `ERR_DESIGN_NOT_CURRENT`". PRD §3.3: "A design is considered current when it
        is the `SEALED` revision with the highest `revision_no` for its pair and has
        not been `SUPERSEDED`."

        Design: Difficulty/priority_pair_validation_conflict/batch_cutting_safety_beats_coverage_constraint
        """
        ns = self._setup_stale_design(with_coverage=True)
        # Full reservation coverage cannot rescue a stale design.
        resp = api.transition_batch(ns.bat1["id"], {"to_state": "CUTTING"}, SFL)
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_CURRENT)
        assert batch_fresh(ns.bat1["id"])["status"] == "SCHEDULED"


class TestCutListReleaseRequiresCurrentSealedDesign:
    def _setup_stale_list(self):
        """r1 SEALED with cl1 EXPLODED; r2 then sealed, making r1 no longer current."""
        ns = setup_sealed_roof_design(job_name="Guard Job", contract=100000)
        ns.jig_roof = make_jig()
        ns.cl1, _ = explode_cut_list(ns.dsg1["id"], ns.jig_roof["id"],
                                     [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        ns.dsg1r2 = seal_revision(ns.job["id"], ns.eng1, ns.eng2, ns.dsg1,
                                  design_load_psf=42.0)
        return ns

    def test_release_of_list_on_stale_revision_rejected(self, api):
        """PRD §3.4: "The release re-verifies that the design is `SEALED` and current
        (else `ERR_DESIGN_NOT_CURRENT`)". PRD §3.3: "A design is considered current
        when it is the `SEALED` revision with the highest `revision_no` for its pair
        and has not been `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/cut_list_release_requires_current_sealed_design
        """
        ns = self._setup_stale_list()
        resp = api.release_cut_list(ns.cl1["id"], PP)
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_CURRENT)
        assert cut_list_fresh(ns.cl1["id"])["status"] == "EXPLODED"

    def test_list_from_current_revision_releases_and_starts_production(self, api):
        """PRD §3.4: "When this is the job's first cut list to reach `RELEASED`, the
        job itself advances `CONFIRMED` to `IN_PRODUCTION` per §3.2, and the job's
        posture is recomputed."

        Design: Difficulty/cross_entity_state_dependency/cut_list_release_requires_current_sealed_design
        """
        ns = self._setup_stale_list()
        cl2, _ = explode_cut_list(ns.dsg1r2["id"], ns.jig_roof["id"],
                                  [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        released = validate_success(api.release_cut_list(cl2["id"], PP))
        assert released["status"] == "RELEASED"
        assert job_fresh(ns.job["id"])["status"] == "IN_PRODUCTION", \
            "the first RELEASED cut list advances the job on its own"


class TestBatchQCReworkLoop:
    def test_qc_fail_rework_pass_with_posture(self, api):
        """PRD §3.6: "from `BUILT` either to `QC_PASSED` or to `QC_FAILED` — a failure
        recomputes the job's posture to `AT_RISK` per §2.10. A failed batch enters
        `REWORK` and returns to `QC_PASSED` from there, recomputing posture again."
        and "A `QC_PASSED` batch reaches `STAGED` only once at least one crane slot
        referencing it via `production_batch_id`, with `purpose` `BUILD_PICK` and
        status `COMPLETED`, exists."

        Design: Corner/state_machines/batch_qc_rework_loop_with_posture
        """
        ns = setup_batch_built(job_name="QC Job")
        failed = validate_success(api.transition_batch(ns.bat1["id"], {"to_state": "QC_FAILED"}, SFL))
        assert failed["status"] == "QC_FAILED"
        assert job_fresh(ns.job["id"])["posture"] == "AT_RISK"
        rework = validate_success(api.transition_batch(ns.bat1["id"], {"to_state": "REWORK"}, SFL))
        assert rework["status"] == "REWORK"
        passed = validate_success(api.transition_batch(ns.bat1["id"], {"to_state": "QC_PASSED"}, SFL))
        assert passed["status"] == "QC_PASSED"
        assert job_fresh(ns.job["id"])["posture"] == "GREEN", \
            "no QC_FAILED/REWORK batch remains once the loop closes"
        staged = validate_success(api.transition_batch(ns.bat1["id"], {"to_state": "STAGED"}, SFL))
        assert staged["status"] == "STAGED", "the completed BUILD_PICK slot satisfies the guard"


class TestBatchSystemOnlyTransitions:
    def test_direct_loaded_and_cancel_rejected(self, api):
        """PRD §3.6: "The remaining transitions are system-only: a `STAGED` batch
        moves to `LOADED` when a load it is bundled into enters `LOADING`, and a
        `LOADED` batch returns to `STAGED` when its truck comes back (§3.7); any batch
        not yet `LOADED` or `CANCELLED` moves to `CANCELLED` only through the
        change-order or job-cancel cascades. Requesting `STAGED` to `LOADED` or any
        direct cancellation is rejected with `ERR_BATCH_INVALID_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/batch_system_only_transitions_rejected
        """
        ns = setup_production_preamble(job_name="SysOnly Job")
        resp1 = api.transition_batch(ns.bat1["id"], {"to_state": "LOADED"}, SFL)
        validate_error(resp1, ApiErrorId.ERR_BATCH_INVALID_TRANSITION)
        resp2 = api.transition_batch(ns.bat1["id"], {"to_state": "CANCELLED"}, SFL)
        validate_error(resp2, ApiErrorId.ERR_BATCH_INVALID_TRANSITION)
        assert batch_fresh(ns.bat1["id"])["status"] == "STAGED"


class TestMarkCutGuard:
    def test_mark_cut_requires_batch_in_cutting(self, api):
        """PRD §3.6: "a `ShopFloorLead` marks a `PENDING` line as `CUT`, which requires
        some batch referencing the line's cut list to be in `CUTTING`, else the
        request is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/mark_cut_requires_batch_in_cutting
        """
        ns = setup_released_cl1(job_name="MarkCut Job", contract=100000, with_lots=False)
        make_batch(ns.job["id"], ns.cl1["id"], ns.jig_roof["id"])  # stays SCHEDULED
        line_id = ns.lines["TC-1"]["id"]
        resp = api.mark_cut_line(line_id, SFL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert line_fresh(line_id)["status"] == "PENDING"


class TestBuildSequenceOrdering:
    def test_greedy_changeover_orders_equal_completion_group(self, api):
        """PRD §3.6: "Within a group of exactly equal `requested_completion_at`
        values, the order is chosen greedily by changeover minimization: starting from
        the group anchor — the batch with the earliest `created_at`, which has no
        predecessor — the system repeatedly picks the remaining batch whose jig
        minimizes the changeover from the previously placed batch's jig, where the
        changeover is the target jig's `changeover_minutes_from` entry keyed on the
        previous jig's `setup_code`, defaulting to 60 minutes when that entry is
        missing and counting 0 when the two codes are identical."

        Design: Corner/calculations/build_sequence_changeover_greedy_order
        """
        ns = setup_confirmed_job(job_name="Seq Job", contract=100000)
        jigf = make_jig("JIG-F", "ROOF_TRUSS", "P20", {"JIG-R": 30})
        jigr = make_jig("JIG-R", "ROOF_TRUSS", "P20", {"JIG-F": 45})
        jigf2 = make_jig("JIG-F2", "ROOF_TRUSS", "P20", {})
        dsg = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2)
        cl1, _ = explode_cut_list(dsg["id"], jigf["id"],
                                  [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        validate_success(api.release_cut_list(cl1["id"], PP))
        b1 = make_batch(ns.job["id"], cl1["id"], jigf["id"])
        b2 = make_batch(ns.job["id"], cl1["id"], jigr["id"])
        b3 = make_batch(ns.job["id"], cl1["id"], jigf2["id"])
        seq = {b["id"]: b["build_sequence_no"]
               for b in (batch_fresh(b1["id"]), batch_fresh(b2["id"]), batch_fresh(b3["id"]))}
        assert seq[b1["id"]] == 1, "anchor: earliest created_at keeps position 1"
        # From JIG-F: JIG-R costs 45 (matrix entry), JIG-F2 costs 60 (missing entry
        # defaults to 60) — the cheaper changeover goes first.
        assert seq[b2["id"]] == 2
        assert seq[b3["id"]] == 3


class TestReconcileGuard:
    def test_reconcile_requires_reconciling_state(self, api):
        """PRD §3.4: "A `ProductionPlanner` also reconciles a list in `RECONCILING`
        (a state entered only through the change-order cascade of §3.9):
        reconciliation to `CLOSED` — rejected with `ERR_CUT_LIST_NOT_RECONCILING`
        from any other status".

        Design: Corner/validations/reconcile_requires_reconciling_state
        """
        ns = setup_released_cl1(job_name="Recon Job", contract=100000, with_lots=False)
        resp = api.reconcile_cut_list(ns.cl1["id"], PP)
        validate_error(resp, ApiErrorId.ERR_CUT_LIST_NOT_RECONCILING)
        assert cut_list_fresh(ns.cl1["id"])["status"] == "RELEASED"


class TestJigComponentMismatch:
    def test_mismatch_at_cut_list_create_and_batch_create(self, api):
        """PRD §3.4: "The payload names a `jig_setup_id` whose
        `component_type_supported` must equal the design's `component_type`, else
        `ERR_JIG_COMPONENT_MISMATCH`". PRD §3.6: "a `jig_setup_id` whose
        `component_type_supported` must equal the cut list's design `component_type`
        (else `ERR_JIG_COMPONENT_MISMATCH`; the status guard fires before the jig
        check)".

        Design: Corner/validations/jig_component_mismatch_at_cut_list_and_batch
        """
        ns = setup_confirmed_job(job_name="Jig Job", contract=100000)
        jig_roof = make_jig()
        jig_wall = make_jig("JIG-WALL-A", "WALL_PANEL", "P20", {})
        dsg = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2)
        cl1, _ = explode_cut_list(dsg["id"], jig_roof["id"],
                                  [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        validate_success(api.release_cut_list(cl1["id"], PP))
        resp1 = api.create_cut_list(
            dsg["id"],
            {"jig_setup_id": jig_wall["id"],
             "lines": [cut_list_line_payload("TC-2", "L2X6", 12.0, 10)]},
            PP,
        )
        validate_error(resp1, ApiErrorId.ERR_JIG_COMPONENT_MISMATCH)
        resp2 = api.create_batch(ns.job["id"], create_batch_payload(cl1["id"], jig_wall["id"]), PP)
        validate_error(resp2, ApiErrorId.ERR_JIG_COMPONENT_MISMATCH)
