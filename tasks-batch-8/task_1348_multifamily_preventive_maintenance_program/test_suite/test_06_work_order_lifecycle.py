"""Corrective work order lifecycle: state legality, OCC on conversion, fiscal
gates, role separation, rework and verification-failure cycles, and the
completion cascade onto deficiency, asset, and plan."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    api_client,
    create_plan, create_batch, add_visit, publish_batch, set_clock,
    start_visit, complete_visit, record_deficiency, triage_deficiency,
    create_work_order, create_work_order_payload,
    get_plan, get_asset, get_deficiency, get_work_order,
    wo_ledger_entries, assert_ledger_entries_exactly,
    setup_property_scaffold, setup_work_order, setup_wo_in_review,
    setup_wo_completed, setup_completed_visit,
    make_technician_headers,
)

TEST_PM = TEST_USERS["property_manager_headers"]
TEST_AUD = TEST_USERS["auditor_headers"]

TECH9 = make_technician_headers("tech-9")

WH_SCAFFOLD = dict(
    component_type="WATER_HEATER",
    estimated_labor_minutes=45,
    installed_on="2023-01-01T00:00:00Z",
    replacement_cost_cents=300000,
)


class TestWoApproveFromOpenInvalid:
    def test_approve_from_open_rejected(self, api):
        """PRD §3.5: "Approval is legal only from `IN_REVIEW` — approving an
        `OPEN` work order fails with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/wo_approve_from_open_invalid
        """
        ctx = setup_work_order(**WH_SCAFFOLD)
        resp = api.approve_work_order(ctx["work_order"]["id"], TEST_PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOccStaleVersionOnWoCreate:
    def test_create_with_stale_deficiency_version_rejected(self, api):
        """PRD §2.9: "if another writer has advanced the deficiency's `version`
        since then — for example by converting the same deficiency first, which
        legitimately supersedes the stale intent because a deficiency converts to
        at most one work order — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)." PRD §2.5: "Triaging a deficiency, or attaching a work order
        to it, increments the deficiency's `version` by one." The pre-triage
        version is stale once triage has run.

        Design: Corner/errors/occ_stale_version_on_wo_create
        """
        ctx = setup_completed_visit(actual_minutes=45, condition_score=2,
                                    deficiency={"severity": "HIGH", "description": "Leak"},
                                    **WH_SCAFFOLD)
        deficiency = ctx["deficiency"]
        stale_version = deficiency["version"]  # captured before triage
        triage_deficiency(deficiency["id"])
        resp = api.create_work_order(
            create_work_order_payload(deficiency["id"], ctx["plan"]["id"], stale_version),
            TEST_PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestTechnicianCannotApproveWorkOrder:
    def test_technician_approve_rejected(self, api):
        """PRD §4: POST /pm/work-orders/{wo_id}/approve is admitted for
        PropertyManager only. PRD §2.1: "an authenticated caller whose role is
        not admitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/technician_cannot_approve_work_order
        """
        ctx = setup_wo_in_review(**WH_SCAFFOLD)
        resp = api.approve_work_order(ctx["work_order"]["id"], TECH9)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestWoApproveGatedByPlanAdopted:
    """The visit is funded by an ADOPTED 2026 plan; the work order charges a
    second plan (2027) left in DRAFT."""

    def _setup_wo_on_draft_plan(self):
        ctx = setup_property_scaffold(budget_cents=1000000, plan_year=2026, adopt=True, **WH_SCAFFOLD)
        draft_plan = create_plan(ctx["property"]["id"], plan_year=2027,
                                 budget_cents=1000000, adopt=False)
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-02T09:00:00Z")
        publish_batch(batch["id"])
        set_clock("2026-08-02T09:00:00Z")
        start_visit(visit["id"], technician_id="tech-1")
        deficiency = record_deficiency(visit["id"], ctx["asset"]["id"], technician_id="tech-1",
                                       severity="HIGH", description="Leak at relief valve")
        complete_visit(visit["id"], 45, 2, technician_id="tech-1")
        triage_deficiency(deficiency["id"])
        wo = create_work_order(deficiency["id"], draft_plan["id"], estimated_cost_cents=100000)
        validate_success(api_client.submit_work_order_review(wo["id"], TECH9))
        return ctx, draft_plan, wo

    def test_approve_against_draft_plan_rejected(self, api):
        """PRD §3.5: "the plan must be `ADOPTED`, checked first
        (`ERR_PLAN_NOT_ADOPTED`)".

        Design: Difficulty/cross_entity_state_dependency/wo_approve_gated_by_plan_adopted
        """
        _ctx, _draft_plan, wo = self._setup_wo_on_draft_plan()
        resp = api.approve_work_order(wo["id"], TEST_PM)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ADOPTED)

    def test_approve_succeeds_once_plan_adopted(self, api):
        """PRD §3.5: "on approval the ledger writes a `WO_COMMIT` for the estimate
        and the plan's `committed_cents` recomputes." The 100000 estimate commits
        in full to the newly adopted plan.

        Design: Difficulty/cross_entity_state_dependency/wo_approve_gated_by_plan_adopted
        """
        _ctx, draft_plan, wo = self._setup_wo_on_draft_plan()
        validate_success(api.adopt_plan(draft_plan["id"], TEST_PM))
        approved = validate_success(api.approve_work_order(wo["id"], TEST_PM))
        assert approved["status"] == "APPROVED"
        plan = get_plan(draft_plan["id"])
        assert plan["committed_cents"] == 100000, (
            f"expected WO_COMMIT of 100000 on the plan, got {plan['committed_cents']}"
        )


class TestBudgetExceededOnWoApprove:
    """Plan budget 100000. The visit settles 4500 (spent, not committed). WO1
    (95500) approves within headroom; WO2 (200000) would push committed
    95500 + 200000 over budget."""

    def _setup(self):
        ctx = setup_property_scaffold(budget_cents=100000, **WH_SCAFFOLD)
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-02T09:00:00Z")
        publish_batch(batch["id"])
        set_clock("2026-08-02T09:00:00Z")
        start_visit(visit["id"], technician_id="tech-1")
        d1 = record_deficiency(visit["id"], ctx["asset"]["id"], technician_id="tech-1",
                               severity="HIGH", description="Leak")
        d2 = record_deficiency(visit["id"], ctx["asset"]["id"], technician_id="tech-1",
                               severity="MEDIUM", description="Sediment")
        complete_visit(visit["id"], 45, 2, technician_id="tech-1")
        triage_deficiency(d1["id"])
        triage_deficiency(d2["id"])
        wo1 = create_work_order(d1["id"], ctx["plan"]["id"], estimated_cost_cents=95500)
        validate_success(api_client.submit_work_order_review(wo1["id"], TECH9))
        wo2 = create_work_order(d2["id"], ctx["plan"]["id"], estimated_cost_cents=200000)
        validate_success(api_client.submit_work_order_review(wo2["id"], TECH9))
        return ctx, wo1, wo2

    def test_first_work_order_within_headroom_approves(self, api):
        """PRD §3.5: "the plan's `committed_cents` plus the work order's
        `estimated_cost_cents` must not exceed `budget_cents`, with an exact
        match to the budget permitted (`ERR_BUDGET_EXCEEDED`)". With committed 0
        and budget 100000, an estimate of 95500 is within headroom.

        Design: Corner/validations/budget_exceeded_on_wo_approve
        """
        _ctx, wo1, _wo2 = self._setup()
        approved = validate_success(api.approve_work_order(wo1["id"], TEST_PM))
        assert approved["status"] == "APPROVED"

    def test_second_work_order_over_budget_rejected(self, api):
        """PRD §3.5: "the plan's `committed_cents` plus the work order's
        `estimated_cost_cents` must not exceed `budget_cents`, with an exact
        match to the budget permitted (`ERR_BUDGET_EXCEEDED`)". 95500 + 200000
        exceeds 100000.

        Design: Corner/validations/budget_exceeded_on_wo_approve
        """
        _ctx, wo1, wo2 = self._setup()
        validate_success(api.approve_work_order(wo1["id"], TEST_PM))
        resp = api.approve_work_order(wo2["id"], TEST_PM)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestWorkOrderReworkAndFailedVerificationCycles:
    def test_rework_loop_increments_revision_count(self, api):
        """PRD §3.5: "Returning the work order for rework sends it back from
        `IN_REVIEW` to `OPEN` and increments its `revision_count`, which tallies
        how many times the rework cycle has turned."

        Design: Difficulty/non_linear_state_machine/work_order_rework_and_failed_verification_cycles
        """
        ctx = setup_wo_in_review(estimated_cost_cents=200000, **WH_SCAFFOLD)
        wo_id = ctx["work_order"]["id"]

        first = validate_success(api.return_work_order_rework(wo_id, TEST_PM))
        assert first["status"] == "OPEN"
        assert first["revision_count"] == 1

        validate_success(api.submit_work_order_review(wo_id, TECH9))
        second = validate_success(api.return_work_order_rework(wo_id, TEST_PM))
        assert second["status"] == "OPEN"
        assert second["revision_count"] == 2

    def test_failed_verification_returns_to_in_progress_and_claws_back(self, api):
        """PRD §3.6: "A `FAIL` outcome unwinds the settlement: the work order
        returns to `IN_PROGRESS`, the ledger writes a release-of-settle
        `WO_RELEASE` for the full `actual_cost_cents` (clawing the settled spend
        back out of `spent_cents`, with `committed_cents` and `spent_cents`
        recomputed), the asset returns to `OUT_OF_SERVICE`, and the originating
        deficiency reopens to `TRIAGED`."

        Design: Difficulty/non_linear_state_machine/work_order_rework_and_failed_verification_cycles
        """
        ctx = setup_wo_completed(actual_minutes=45, condition_score=2,
                                 estimated_cost_cents=200000, actual_cost_cents=180000,
                                 **WH_SCAFFOLD)
        wo_id = ctx["work_order"]["id"]
        plan_peak = get_plan(ctx["plan"]["id"])
        assert plan_peak["spent_cents"] == 184500  # 4500 visit settle + 180000 WO settle

        resp = api.verify_work_order(wo_id, {"outcome": "FAIL"}, TEST_AUD)
        wo = validate_success(resp)
        assert wo["status"] == "IN_PROGRESS"

        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["spent_cents"] == 4500, (
            f"clawback must release exactly the 180000 settle, spent={plan_after['spent_cents']}"
        )
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "TRIAGED"
        asset = get_asset(ctx["asset"]["id"])
        assert asset["operational_status"] == "OUT_OF_SERVICE"


class TestWoCompleteCascadesToDeficiencyAndAsset:
    def test_wo_completion_converts_deficiency_and_restores_asset(self, api):
        """PRD §3.5: "it resolves the asset — with `replace_asset` the old asset
        becomes `DECOMMISSIONED` and its `superseded_by_asset_id` is set to
        `new_asset_id`, otherwise the asset returns to `IN_SERVICE`; and it moves
        the originating deficiency to `CONVERTED`".

        Design: Difficulty/transitive_cascade/wo_complete_cascades_to_deficiency_and_asset
        """
        ctx = setup_wo_completed(actual_minutes=45, condition_score=2,
                                 estimated_cost_cents=200000, actual_cost_cents=180000,
                                 **WH_SCAFFOLD)
        wo = ctx["work_order"]
        assert wo["status"] == "COMPLETED"

        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "CONVERTED", (
            f"WO completion must move the deficiency to CONVERTED, got {deficiency['status']}"
        )
        asset = get_asset(ctx["asset"]["id"])
        assert asset["operational_status"] == "IN_SERVICE", (
            f"without replace_asset the asset returns to IN_SERVICE, got {asset['operational_status']}"
        )
        plan = get_plan(ctx["plan"]["id"])
        assert plan["spent_cents"] == 184500, (
            f"expected visit settle 4500 + WO settle 180000, got {plan['spent_cents']}"
        )

    def test_wo_ledger_shows_commit_release_settle_triplet(self, api):
        """PRD §2.8: "For a work order: approval writes a `WO_COMMIT` for the
        positive `estimated_cost_cents`; completion writes a `WO_RELEASE` for the
        negative of that estimate followed by a `WO_SETTLE` for the positive
        `actual_cost_cents`".

        Design: Difficulty/transitive_cascade/wo_complete_cascades_to_deficiency_and_asset
        """
        ctx = setup_wo_completed(actual_minutes=45, condition_score=2,
                                 estimated_cost_cents=200000, actual_cost_cents=180000,
                                 **WH_SCAFFOLD)
        entries = wo_ledger_entries(ctx["work_order"]["id"])
        assert_ledger_entries_exactly(entries, [
            ("WO_COMMIT", 200000),
            ("WO_RELEASE", -200000),
            ("WO_SETTLE", 180000),
        ])
        plan = get_plan(ctx["plan"]["id"])
        assert plan["committed_cents"] == 0
