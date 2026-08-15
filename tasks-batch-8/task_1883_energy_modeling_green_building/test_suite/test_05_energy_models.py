"""Energy models: creation gates, the lock transition, improvement variants,
the PERFORMANCE-path minimum gate, model pinning on mark-ready, and the
supersede cascade (PRD §3.3, §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_energy_model,
    assign_owner,
    create_attempt,
    create_credit_entry,
    create_energy_model,
    create_energy_model_payload,
    create_locked_models,
    create_members,
    create_project,
    drive_attempt_ready,
    get_attempt,
    get_project,
    get_success_data,
    lock_model,
    lock_strategy,
    make_documentation_specialist_headers,
    make_energy_modeler_headers,
    mark_ready,
    setup_model_pinned_ready_attempt,
    setup_project_with_strategy,
    submit_phase,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


class TestModelCreation:
    def test_energy_model_initial_state_and_retrieval(self, api):
        """PRD §3.3: "The server stamps the model's `created_by` with the caller's `X-User-ID`, starts it in `DRAFT`, and increments the owning project's `version` by one."
        PRD §3.3: "Each new model receives a `version_index` that sequences per project and model type — the first baseline on a project is 1, the next baseline 2, independently of the proposed sequence — computed as one more than the largest existing index for that pair."
        PRD §3.3: "Both fields remain null on baseline models and on proposed models that have not locked."

        Design: Corner/state_machines/energy_model_initial_state_and_retrieval
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Init Tower")
        model = validate_success(
            api.create_energy_model(
                create_energy_model_payload(project["id"], project["version"]),
                make_energy_modeler_headers(members["modeler"]["id"])),
            201,
        )
        assert_energy_model(model)
        assert model["status"] == "DRAFT"
        assert model["version_index"] == 1
        assert model["improvement_pct_provisional"] is None
        assert model["improvement_pct_final"] is None
        assert model["created_by"] == members["modeler"]["id"]

        fetched = validate_success(api.get_energy_model(model["id"], ANY))
        assert fetched["annual_energy_cost_modeled_cents"] == 12000000

    def test_model_create_during_submission_blocked(self, api):
        """PRD §3.3: "Creating a model requires the project to be `REGISTERED`, `STRATEGY_LOCKED`, `DESIGN_REVIEWED`, or `CONSTRUCTION_REVIEWED` — modeling is not accepted while a phase is in review or after certification, and the create otherwise fails with `ERR_INVALID_PROJECT_STATE`."

        Design: Corner/validations/model_create_during_submission_blocked
        """
        ctx = setup_project_with_strategy(
            [{"code": "EAp1", "points": 0, "is_prerequisite": True,
              "phase_eligibility": "BOTH"}],
            project_overrides={"project_name": "MidStream Tower"},
        )
        admin_id = ctx["members"]["admin"]["id"]
        spec_id = ctx["members"]["spec"]["id"]
        drive_attempt_ready(ctx["attempts"]["EAp1"]["id"], spec_id, admin_id)
        submit_phase(ctx["project"]["id"], "DESIGN", admin_id)

        fresh_version = get_project(ctx["project"]["id"])["version"]
        resp = api.create_energy_model(
            create_energy_model_payload(ctx["project"]["id"], fresh_version),
            make_energy_modeler_headers(ctx["members"]["modeler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROJECT_STATE)


class TestModelLockStates:
    def test_lock_locked_model_rejected(self, api):
        """PRD §3.3: "Only a `DRAFT` model can be locked; any other state fails with `ERR_INVALID_MODEL_STATE`."

        Design: Corner/state_machines/lock_locked_model_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Lock Tower")
        model = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE")
        lock_model(model["id"], members["modeler"]["id"])

        resp = api.lock_energy_model(
            model["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_MODEL_STATE)
        after = validate_success(api.get_energy_model(model["id"], ANY))
        assert after["status"] == "LOCKED"

    def test_lock_superseded_model_terminal_lockdown(self, api):
        """PRD §3.3: "The previously `LOCKED` model of the same project and model type, if one exists, transitions to `SUPERSEDED`, the terminal state of every model."
        PRD §3.3: "Only a `DRAFT` model can be locked; any other state fails with `ERR_INVALID_MODEL_STATE`."

        Design: Corner/state_machines/lock_superseded_model_terminal_lockdown
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Sup Tower")
        b1 = create_energy_model(project["id"], members["modeler"]["id"], "BASELINE")
        lock_model(b1["id"], members["modeler"]["id"])
        b2 = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE",
            modeled=12100000, confirmed=12100000)
        lock_model(b2["id"], members["modeler"]["id"])

        b1_after = validate_success(api.get_energy_model(b1["id"], ANY))
        assert b1_after["status"] == "SUPERSEDED", (
            "locking B2 supersedes the previously locked baseline")

        resp = api.lock_energy_model(
            b1["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_MODEL_STATE)

        b2_after = validate_success(api.get_energy_model(b2["id"], ANY))
        assert b2_after["version_index"] == 2

    def test_proposed_lock_without_baseline_rejected(self, api):
        """PRD §3.3: "A proposed model cannot lock before its baseline: locking a `PROPOSED` model while the project has no `LOCKED` baseline is rejected with `ERR_BASELINE_MODEL_NOT_LOCKED` (HTTP 409)."

        Design: Corner/validations/proposed_lock_without_baseline_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="NoBase Tower")
        proposed = create_energy_model(
            project["id"], members["modeler"]["id"], "PROPOSED",
            modeled=11400000, confirmed=11400000)

        resp = api.lock_energy_model(
            proposed["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BASELINE_MODEL_NOT_LOCKED)
        after = validate_success(api.get_energy_model(proposed["id"], ANY))
        assert after["status"] == "DRAFT"


class TestImprovementVariants:
    def _performance_project_with_proposed(self, api, proposed_modeled,
                                           proposed_confirmed, includes_unconfirmed):
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="Tower A",
            compliance_path="PERFORMANCE", target_level="SILVER")
        baseline = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE",
            modeled=12000000, confirmed=12000000)
        proposed = create_energy_model(
            project["id"], members["modeler"]["id"], "PROPOSED",
            modeled=proposed_modeled, confirmed=proposed_confirmed,
            includes_unconfirmed=includes_unconfirmed)
        lock_model(baseline["id"], members["modeler"]["id"])
        return members, proposed

    def test_lock_computes_provisional_and_final_variants(self, api):
        """PRD §3.3: "When a `PROPOSED` model locks, two improvement percentages are computed against the project's `LOCKED` baseline, each rounded half up to two decimal places. `improvement_pct_provisional` is the difference between the baseline's and the proposed model's `annual_energy_cost_modeled_cents`, divided by the baseline's `annual_energy_cost_modeled_cents`, multiplied by one hundred. `improvement_pct_final` is the same ratio computed over the two models' `annual_energy_cost_confirmed_only_cents` figures."

        Design: Difficulty/dual_variant_calc/energy_model_provisional_vs_final_improvement
        """
        members, proposed = self._performance_project_with_proposed(
            api, proposed_modeled=10800000, proposed_confirmed=11400000,
            includes_unconfirmed=True)
        locked = validate_success(
            api.lock_energy_model(
                proposed["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        )
        assert locked["status"] == "LOCKED"
        assert locked["improvement_pct_provisional"] == 10.00, (
            "(12000000-10800000)/12000000*100 = 10.00")
        assert locked["improvement_pct_final"] == 5.00, (
            "(12000000-11400000)/12000000*100 = 5.00")
        assert locked["improvement_pct_provisional"] != locked["improvement_pct_final"]

    def test_improvement_variants_null_until_lock(self, api):
        """PRD §3.3: "Both fields remain null on baseline models and on proposed models that have not locked."

        Design: Difficulty/dual_variant_calc/energy_model_provisional_vs_final_improvement
        """
        members, proposed = self._performance_project_with_proposed(
            api, proposed_modeled=10800000, proposed_confirmed=11400000,
            includes_unconfirmed=True)
        draft = validate_success(api.get_energy_model(proposed["id"], ANY))
        assert draft["status"] == "DRAFT"
        assert draft["improvement_pct_provisional"] is None
        assert draft["improvement_pct_final"] is None

        data, meta = validate_paginated(
            api.list_energy_models(
                ANY, params={"project_id": draft["project_id"],
                             "model_type": "BASELINE"}))
        assert meta["total_count"] == 1
        baseline = data[0]
        assert baseline["status"] == "LOCKED"
        assert baseline["improvement_pct_provisional"] is None
        assert baseline["improvement_pct_final"] is None


class TestPerformancePathMinimumGate:
    def test_improvement_exactly_5_lock_allowed(self, api):
        """PRD §3.3: "The final variant gates the performance path: on a `PERFORMANCE`-path project, a proposed model whose `improvement_pct_final` would fall below 5.00 cannot lock — the lock is rejected with `ERR_MINIMUM_IMPROVEMENT_NOT_MET` (HTTP 422), and the boundary is inclusive, so an improvement of exactly 5.00 passes."

        Design: Difficulty/boundary_precision_check/improvement_exactly_5_lock_allowed
        """
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="Tower K", rating_system="LEED_O_M",
            compliance_path="PERFORMANCE")
        baseline = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE")
        proposed = create_energy_model(
            project["id"], members["modeler"]["id"], "PROPOSED",
            modeled=11400000, confirmed=11400000)
        lock_model(baseline["id"], members["modeler"]["id"])

        locked = validate_success(
            api.lock_energy_model(
                proposed["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        )
        assert locked["status"] == "LOCKED", "5.00 >= 5.00: the inclusive boundary passes"
        assert locked["improvement_pct_final"] == 5.00

    def test_prescriptive_path_has_no_minimum_improvement_gate(self, api):
        """PRD §3.3: "The final variant gates the performance path: on a `PERFORMANCE`-path project, a proposed model whose `improvement_pct_final` would fall below 5.00 cannot lock — the lock is rejected with `ERR_MINIMUM_IMPROVEMENT_NOT_MET` (HTTP 422), and the boundary is inclusive, so an improvement of exactly 5.00 passes."
        PRD §3.1: "A `PRESCRIPTIVE` project never needs an energy model to submit a phase. A `PERFORMANCE` project, by contrast, enforces a minimum modeled energy improvement when its proposed model locks (§3.3) and cannot submit its design package without a locked proposed model (§3.4)."

        Design: Difficulty/boundary_precision_check/improvement_exactly_5_lock_allowed
        """
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="Tower K2",
            compliance_path="PRESCRIPTIVE")
        baseline = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE")
        proposed = create_energy_model(
            project["id"], members["modeler"]["id"], "PROPOSED",
            modeled=11404800, confirmed=11404800)
        lock_model(baseline["id"], members["modeler"]["id"])

        locked = validate_success(
            api.lock_energy_model(
                proposed["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        )
        assert locked["status"] == "LOCKED", (
            "the 5.00 gate is scoped to the PERFORMANCE path; PRESCRIPTIVE locks freely")
        assert locked["improvement_pct_final"] == 4.96

    def test_minimum_improvement_below_threshold_blocked(self, api):
        """PRD §3.3: "The final variant gates the performance path: on a `PERFORMANCE`-path project, a proposed model whose `improvement_pct_final` would fall below 5.00 cannot lock — the lock is rejected with `ERR_MINIMUM_IMPROVEMENT_NOT_MET` (HTTP 422), and the boundary is inclusive, so an improvement of exactly 5.00 passes."

        Design: Corner/validations/minimum_improvement_below_threshold_blocked
        """
        members = create_members()
        project = create_project(
            members["admin"]["id"], project_name="LowImp Tower",
            compliance_path="PERFORMANCE")
        baseline = create_energy_model(
            project["id"], members["modeler"]["id"], "BASELINE")
        lock_model(baseline["id"], members["modeler"]["id"])
        proposed = create_energy_model(
            project["id"], members["modeler"]["id"], "PROPOSED",
            modeled=11405000, confirmed=11405000)

        resp = api.lock_energy_model(
            proposed["id"], make_energy_modeler_headers(members["modeler"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MINIMUM_IMPROVEMENT_NOT_MET)
        after = validate_success(api.get_energy_model(proposed["id"], ANY))
        assert after["status"] == "DRAFT"


class TestMarkReadyModelPinning:
    def _project_with_model_credit_attempt(self, api):
        members = create_members()
        entry = create_credit_entry(
            credit_code="EAc1", title="Optimize Energy Performance",
            category="ENERGY_ATMOSPHERE", points_possible=10,
            is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=True)
        project = create_project(members["admin"]["id"], project_name="Tower M")
        attempt = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        assign_owner(attempt["id"], members["spec"]["id"], members["admin"]["id"])
        return members, entry, project, attempt

    def test_mark_ready_without_locked_proposed_model_rejected(self, api):
        """PRD §3.2: "For a credit whose catalog entry has `requires_energy_model` true, readiness additionally requires a `LOCKED` proposed model on the project — otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409) — and the mark-ready act pins that model: `pinned_proposed_model_id` is set to the locked proposed model's `id` and `has_stale_model_pin` to false, freezing the exact model version the documentation references."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_locked_proposed_model
        """
        members, entry, project, attempt = self._project_with_model_credit_attempt(api)
        resp = api.mark_ready(
            attempt["id"],
            make_documentation_specialist_headers(members["spec"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROPOSED_MODEL_NOT_LOCKED)
        assert get_attempt(attempt["id"])["status"] == "DOCUMENTATION_IN_PROGRESS"

    def test_mark_ready_pins_locked_proposed_model(self, api):
        """PRD §3.2: "For a credit whose catalog entry has `requires_energy_model` true, readiness additionally requires a `LOCKED` proposed model on the project — otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409) — and the mark-ready act pins that model: `pinned_proposed_model_id` is set to the locked proposed model's `id` and `has_stale_model_pin` to false, freezing the exact model version the documentation references."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_locked_proposed_model
        """
        members, entry, project, attempt = self._project_with_model_credit_attempt(api)
        baseline, proposed = create_locked_models(
            project["id"], members["modeler"]["id"])

        ready = validate_success(
            api.mark_ready(
                attempt["id"],
                make_documentation_specialist_headers(members["spec"]["id"]))
        )
        assert ready["status"] == "READY_FOR_SUBMITTAL"
        assert ready["pinned_proposed_model_id"] == proposed["id"]
        assert ready["has_stale_model_pin"] is False


class TestSupersedeCascade:
    def test_relock_supersedes_model_and_flags_pinned_attempt(self, api):
        """PRD §3.3: "The previously `LOCKED` model of the same project and model type, if one exists, transitions to `SUPERSEDED`, the terminal state of every model. That supersession cascades into the credit strategy: every attempt whose `pinned_proposed_model_id` names the superseded model is flagged with `has_stale_model_pin` set to true, and among those, any attempt sitting in `READY_FOR_SUBMITTAL` is automatically demoted to `DOCUMENTATION_IN_PROGRESS` — its documentation can no longer truthfully reference the model it pinned."

        Design: Difficulty/transitive_cascade/model_lock_supersede_cascade
        """
        ctx = setup_model_pinned_ready_attempt()
        modeler_id = ctx["members"]["modeler"]["id"]
        m1 = ctx["proposed"]
        attempt = ctx["attempt"]
        assert attempt["pinned_proposed_model_id"] == m1["id"]

        m2 = create_energy_model(
            ctx["project"]["id"], modeler_id, "PROPOSED",
            modeled=11200000, confirmed=11200000)
        lock_model(m2["id"], modeler_id)

        m1_after = validate_success(api.get_energy_model(m1["id"], ANY))
        assert m1_after["status"] == "SUPERSEDED"
        m2_after = validate_success(api.get_energy_model(m2["id"], ANY))
        assert m2_after["version_index"] == 2

        attempt_after = get_attempt(attempt["id"])
        assert attempt_after["has_stale_model_pin"] is True
        assert attempt_after["pinned_proposed_model_id"] == m1["id"], (
            "the pin still names the superseded model")
        assert attempt_after["status"] == "DOCUMENTATION_IN_PROGRESS", (
            "READY attempt demoted by the stale pin")

    def test_stale_pinned_attempt_repinned_by_fresh_mark_ready(self, api):
        """PRD §3.3: "Attempts in other states keep their status but carry the stale flag until they are re-pinned by a fresh mark-ready."
        PRD §3.2: "For a credit whose catalog entry has `requires_energy_model` true, readiness additionally requires a `LOCKED` proposed model on the project — otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409) — and the mark-ready act pins that model: `pinned_proposed_model_id` is set to the locked proposed model's `id` and `has_stale_model_pin` to false, freezing the exact model version the documentation references."

        Design: Difficulty/transitive_cascade/model_lock_supersede_cascade
        """
        ctx = setup_model_pinned_ready_attempt()
        modeler_id = ctx["members"]["modeler"]["id"]
        attempt = ctx["attempt"]

        m2 = create_energy_model(
            ctx["project"]["id"], modeler_id, "PROPOSED",
            modeled=11200000, confirmed=11200000)
        lock_model(m2["id"], modeler_id)
        assert get_attempt(attempt["id"])["has_stale_model_pin"] is True

        repinned = validate_success(
            api.mark_ready(
                attempt["id"],
                make_documentation_specialist_headers(ctx["members"]["spec"]["id"]))
        )
        assert repinned["status"] == "READY_FOR_SUBMITTAL"
        assert repinned["pinned_proposed_model_id"] == m2["id"]
        assert repinned["has_stale_model_pin"] is False
