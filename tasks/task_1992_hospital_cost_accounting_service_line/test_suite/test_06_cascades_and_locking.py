"""Transitive cascades, budget-period locking, staleness gates (PRD §2.8, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_budget_period,
    create_case,
    create_payer_contract,
    get_success_data,
    post_case,
    propose_refresh,
    setup_card_rvu,
    setup_case_with_lines,
    setup_ortho_tdabc,
    setup_posted_card_case,
    validate_error,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestRefreshApplyCascade:
    def test_refresh_apply_cascade_depth3(self, api):
        """PRD §3.6: "each referenced cost center's `allocated_cost`,
        `practical_capacity_minutes`, and `total_rvu` are set to the proposed
        values; every `POSTED` case priced by the target model whose `period` is
        on or after the refresh's `period` is recomputed through the pinned
        pipeline of §3.4, regenerating its activity lines and refreshing its
        totals; each recomputed case's service line has its rollups refreshed;
        every affected budget period has its `actual_indirect_volume`,
        `flexed_overhead`, and variance recomputed; and the target model's
        `version` increments by one."

        Design: Difficulty/transitive_cascade/refresh_apply_cascade_depth3
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        bp = scenario["budget_period"]
        # Post the case: LAB 4*2500 = 10000.00, RAD 6*3000 = 18000.00,
        # activity 28000.00 + pool 7000.00 -> indirect 35000.00.
        case = setup_posted_card_case(scenario, lab_qty=4, rad_qty=6)
        assert case["version_at_post"] == scenario["model_version"]

        # Refresh LAB 5000 -> 5150 (2575/rvu, +3.00% exactly: allowed).
        refresh = propose_refresh(
            scenario["model"]["id"], "2026-08",
            [{"cost_center_id": scenario["cc_lab"]["id"],
              "allocated_cost": 5150.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        validate_success(
            api.approve_cost_model_refresh(
                refresh["id"], {"expected_model_version": scenario["model_version"]}, FC
            )
        )
        applied = validate_success(api.apply_cost_model_refresh(refresh["id"], FC))
        assert applied["status"] == "APPLIED"

        # Hop 1: center rate updated.
        lab = validate_success(api.get_cost_center(scenario["cc_lab"]["id"], FC))
        assert lab["allocated_cost"] == pytest.approx(5150.00, abs=0.005)

        # Hop 2: case recomputed — LAB 4*2575 = 10300.00 + RAD 18000.00 = 28300.00
        # activity + 7000.00 pool -> indirect 35300.00; version_at_post advanced.
        recomputed = validate_success(api.get_case(case["id"], CA))
        assert recomputed["total_indirect_allocated"] == pytest.approx(35300.00, abs=0.005)
        assert recomputed["version_at_post"] == scenario["model_version"] + 1

        # Hop 3: budget period recomputed — 0.35 * 28300.00 = 9905.00.
        bp_after = validate_success(api.get_budget_period(bp["id"], FC))
        assert bp_after["actual_indirect_volume"] == pytest.approx(28300.00, abs=0.005)
        assert bp_after["flexed_overhead"] == pytest.approx(9905.00, abs=0.005)

    def test_refresh_apply_bumps_model_version(self, api):
        """PRD §3.6: "the target model's `version` increments by one. That final
        increment is what makes the staleness machinery honest: any case whose
        `version_at_post` predates it no longer satisfies the freshness check at
        lock time, and must be voided and re-posted under the new rates before
        it, or its budget period, can be locked."

        Design: Difficulty/transitive_cascade/refresh_apply_cascade_depth3
        """
        scenario = setup_card_rvu(period="2026-08")
        setup_posted_card_case(scenario, lab_qty=4, rad_qty=6)
        refresh = propose_refresh(
            scenario["model"]["id"], "2026-08",
            [{"cost_center_id": scenario["cc_lab"]["id"],
              "allocated_cost": 5150.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        validate_success(
            api.approve_cost_model_refresh(
                refresh["id"], {"expected_model_version": scenario["model_version"]}, FC
            )
        )
        validate_success(api.apply_cost_model_refresh(refresh["id"], FC))

        model_after = validate_success(api.get_cost_model(scenario["model"]["id"], FC))
        assert model_after["version"] == scenario["model_version"] + 1


class TestServiceLineArchiveCascade:
    def test_service_line_archive_cascade_depth2(self, api):
        """PRD §3.1: "When archival succeeds, every `ACTIVE` cost model of the
        line transitions to `ARCHIVED` and every `ACTIVE` payer contract of the
        line transitions to `TERMINATED`, and the line's `version` increments."

        Design: Difficulty/transitive_cascade/service_line_archive_cascade_depth2
        """
        from test_helpers import create_draft_cost_model, create_service_line
        sl = create_service_line(name="Neurosurgery", code="NEURO",
                                 base_direct_cost=5000.00, budgeted_volume=40)
        from test_helpers import create_overhead_center
        cc_periop = create_overhead_center(name="Periop N", code="PERIOP2",
                                           allocated_cost=100.00)
        # DRAFT model (never approved) — the archive precondition only excludes
        # ACTIVE models, and the cascade sweeps this model to ARCHIVED.
        model = create_draft_cost_model(
            name="NEURO-DRAFT", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        contract = create_payer_contract(
            service_line_id=sl["id"], payer_name="Medicare", payer_type="MEDICARE",
            contracted_rate=30000.00, effective_period="2026-01")

        archived = validate_success(api.archive_service_line(sl["id"], FC))
        assert archived["status"] == "ARCHIVED"

        model_after = validate_success(api.get_cost_model(model["id"], FC))
        assert model_after["status"] == "ARCHIVED"

        contract_after = validate_success(api.get_payer_contract(contract["id"], FC))
        assert contract_after["status"] == "TERMINATED"

    def test_service_line_archive_terminates_only_line_children(self, api):
        """PRD §3.1: "When archival succeeds, every `ACTIVE` cost model of the
        line transitions to `ARCHIVED` and every `ACTIVE` payer contract of the
        line transitions to `TERMINATED`, and the line's `version` increments."

        Design: Difficulty/transitive_cascade/service_line_archive_cascade_depth2
        """
        scenario = setup_ortho_tdabc()
        sl = scenario["service_line"]
        model = scenario["model"]
        contract = create_payer_contract(
            service_line_id=sl["id"], payer_name="Medicare", payer_type="MEDICARE",
            contracted_rate=30000.00, effective_period="2026-01")
        # Archive the ACTIVE model first so the line's archive precondition holds.
        validate_success(api.archive_cost_model(model["id"], FC))

        archived = validate_success(api.archive_service_line(sl["id"], FC))
        assert archived["status"] == "ARCHIVED"
        model_after = validate_success(api.get_cost_model(model["id"], FC))
        assert model_after["status"] == "ARCHIVED"
        contract_after = validate_success(api.get_payer_contract(contract["id"], FC))
        assert contract_after["status"] == "TERMINATED"


class TestCrossEntityStateDependency:
    def test_case_post_depends_on_model_active(self, api):
        """PRD §3.4: "Three further preconditions guard the transition: at least
        one activity cost line must exist for the case (else
        `ERR_CASE_NO_ACTIVITY`); the case's `period` must not precede the model's
        `effective_period` (else `ERR_CASE_PERIOD_BEFORE_MODEL`); and the model
        must be `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/case_post_depends_on_model_active
        """
        scenario = setup_ortho_tdabc()
        case = setup_case_with_lines(scenario, [100])
        # Make the case's model non-ACTIVE via the PRD §3.2 supersession path:
        # approving a successor model moves the original to SUPERSEDED while the
        # DRAFT case still references it. (Direct archival is refused here —
        # §3.2 blocks archiving an ACTIVE model referenced by a DRAFT case.)
        from test_helpers import create_draft_cost_model
        successor = create_draft_cost_model(
            name="ORTHO-TDABC-2", service_line_id=scenario["service_line"]["id"],
            allocation_basis="TDABC", rate_factor=1.00,
            overhead_cost_center_id=scenario["cc_overhead"]["id"],
            effective_period="2026-01",
            supersedes_model_id=scenario["model"]["id"])
        validate_success(api.approve_cost_model(successor["id"], FC))

        stale = validate_success(api.get_cost_model(scenario["model"]["id"], FC))
        assert stale["status"] == "SUPERSEDED"

        # The OCC check is evaluated against the model's current version; with
        # the fresh version carried, the model-active gate is what fires.
        resp = api.post_case(
            case["id"], {"expected_model_version": stale["version"]}, CA
        )
        validate_error(resp, ApiErrorId.ERR_MODEL_NOT_ACTIVE)

    def test_case_post_blocked_when_model_archived_with_case_draft(self, api):
        """PRD §3.2: "An `ACTIVE` model may be archived only when no `DRAFT` or
        `POSTED` case references it (else `ERR_MODEL_HAS_OPEN_CASES`)"
        PRD §3.4: "and the model must be `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/case_post_depends_on_model_active
        """
        scenario = setup_ortho_tdabc()
        case = setup_case_with_lines(scenario, [100])
        # The DRAFT case blocks archiving the model, proving the dependency edge.
        blocked = api.archive_cost_model(scenario["model"]["id"], FC)
        validate_error(blocked, ApiErrorId.ERR_MODEL_HAS_OPEN_CASES)
        # Posting against the still-ACTIVE model succeeds.
        posted = post_case(case["id"], scenario["model_version"])
        assert posted["status"] == "POSTED"

    def test_service_line_archive_depends_on_case_states(self, api):
        """PRD §3.1: "Archiving a service line — a `FinanceController` action
        moving it from `ACTIVE` to `ARCHIVED` — is refused with
        `ERR_SERVICE_LINE_HAS_OPEN_CASES` while any case of the line is still in
        `DRAFT` or `POSTED` (only lines whose cases are all `LOCKED` or `VOIDED`
        may archive)"

        Design: Difficulty/cross_entity_state_dependency/service_line_archive_depends_on_case_states
        """
        scenario = setup_ortho_tdabc()
        # DRAFT case on the line (never posted).
        create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        resp = api.archive_service_line(scenario["service_line"]["id"], FC)
        validate_error(resp, ApiErrorId.ERR_SERVICE_LINE_HAS_OPEN_CASES)

    def test_service_line_archive_blocked_by_posted_case(self, api):
        """PRD §3.1: "Archiving a service line — a `FinanceController` action
        moving it from `ACTIVE` to `ARCHIVED` — is refused with
        `ERR_SERVICE_LINE_HAS_OPEN_CASES` while any case of the line is still in
        `DRAFT` or `POSTED` (only lines whose cases are all `LOCKED` or `VOIDED`
        may archive)"

        Design: Difficulty/cross_entity_state_dependency/service_line_archive_depends_on_case_states
        """
        scenario = setup_ortho_tdabc()
        case = setup_case_with_lines(scenario, [100])
        post_case(case["id"], scenario["model_version"])

        resp = api.archive_service_line(scenario["service_line"]["id"], FC)
        validate_error(resp, ApiErrorId.ERR_SERVICE_LINE_HAS_OPEN_CASES)


class TestCaseLockStaleness:
    def test_case_lock_requires_fresh_model_version(self, api):
        """PRD §3.4: "Locking moves a `POSTED` case to `LOCKED` under the
        `FinanceController`'s hand and is allowed only while the case is priced
        against the current model: the case's `version_at_post` must equal the
        cost model's current `version`. A case priced under an outdated model
        fails with `ERR_CASE_STALE_MODEL` and must be voided and re-posted under
        current rates rather than locked."

        Design: Corner/state_machines/case_lock_requires_fresh_model_version
        """
        scenario = setup_card_rvu(period="2026-08")
        # Case posted in 2026-08 under model version V.
        case = setup_posted_card_case(scenario, lab_qty=4, rad_qty=None)
        assert case["version_at_post"] == scenario["model_version"]

        # Refresh scoped to 2026-09: does NOT recompute the 2026-08 case, but the
        # apply still advances the model version, leaving version_at_post stale.
        refresh = propose_refresh(
            scenario["model"]["id"], "2026-09",
            [{"cost_center_id": scenario["cc_lab"]["id"],
              "allocated_cost": 5100.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        validate_success(
            api.approve_cost_model_refresh(
                refresh["id"], {"expected_model_version": scenario["model_version"]}, FC
            )
        )
        validate_success(api.apply_cost_model_refresh(refresh["id"], FC))

        model_after = validate_success(api.get_cost_model(scenario["model"]["id"], FC))
        assert model_after["version"] == scenario["model_version"] + 1
        case_after = validate_success(api.get_case(case["id"], FC))
        assert case_after["version_at_post"] == scenario["model_version"]

        resp = api.lock_case(case["id"], FC)
        validate_error(resp, ApiErrorId.ERR_CASE_STALE_MODEL)


class TestBudgetPeriodLock:
    def test_budget_period_lock_cascades_cases_to_locked(self, api):
        """PRD §3.5: "When the lock succeeds, every `POSTED` case in the period
        priced by a model using this pool transitions to `LOCKED` alongside it."

        Design: Corner/state_machines/budget_period_lock_cascades_cases_to_locked
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        case = setup_posted_card_case(scenario, lab_qty=4, rad_qty=None)
        assert case["status"] == "POSTED"

        locked_bp = validate_success(
            api.lock_budget_period(scenario["budget_period"]["id"], FC)
        )
        assert locked_bp["status"] == "LOCKED"

        case_after = validate_success(api.get_case(case["id"], FC))
        assert case_after["status"] == "LOCKED"
