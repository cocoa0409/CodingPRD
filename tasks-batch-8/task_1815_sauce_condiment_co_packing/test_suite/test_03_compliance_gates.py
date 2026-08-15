"""Process-authority letters, label compliance, reformulation cascade, and
the letter-gated release of production (PRD §3.3, §3.8, §4)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_process_authority_letter,
    create_approved_label,
    create_formula,
    create_kettle_line,
    create_label,
    create_letter,
    create_packaging_component,
    create_run,
    get_formula,
    get_hold,
    get_label,
    get_letter,
    get_run,
    list_run_holds,
    record_trial_results,
    schedule_trial,
    setup_approved_acidified_formula,
    setup_completed_clean_run,
    setup_trial_passed_formula,
    submit_label,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
QA = TEST_USERS["qa_reviewer_headers"]
PA = TEST_USERS["process_authority_headers"]


class TestLetterSubmissionLimits:

    def test_letter_create_rejects_ph_above_statutory_ceiling(self):
        """PRD §3.3: "Submission requires the formula to be in `TRIAL_PASSED` or `APPROVED` — any other formula status is rejected with `ERR_FORMULA_NOT_TRIAL_PASSED` — and the process limits themselves must sit inside statutory bounds: `max_ph` strictly greater than zero and strictly below 4.6, `max_water_activity` strictly greater than zero and strictly below 1.0. A letter whose limits fall outside those bounds is rejected with `ERR_INVALID_PROCESS_LIMITS`."

        Design: Corner/validations/letter_create_ph_limit_enforced
        """
        ctx = setup_trial_passed_formula()
        resp = api_client.create_process_authority_letter(
            {
                "formula_id": ctx["formula"]["id"],
                "formula_revision": 1,
                "authority_name": "Dr. Rosa Kim",
                "letter_number": "PAL-BAD",
                "max_ph": 4.7,
                "max_water_activity": 0.9,
            },
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROCESS_LIMITS)


class TestLetterActivation:

    def test_letter_activate_rejects_stale_revision(self):
        """PRD §3.3: "the letter's `formula_revision` must equal the formula's current `revision` — a letter drafted against an older revision is stale and rejected with `ERR_LETTER_REVISION_STALE`."

        Design: Corner/errors/letter_activate_stale_revision_rejected
        """
        ctx = setup_approved_acidified_formula()
        formula_id = ctx["formula"]["id"]
        # A second letter pinned to revision 1 while the formula is APPROVED.
        letter2 = create_letter(
            formula_id, formula_revision=1, letter_number="PAL-1002", max_ph=4.3
        )
        # Reformulate -> DRAFT at revision 2, then re-trial -> TRIAL_PASSED.
        validate_success(api_client.reformulate_formula(formula_id, OPS), 200)
        trial2 = schedule_trial(
            formula_id,
            ctx["cell"]["id"],
            scheduled_start="2026-09-02T08:00:00Z",
            scheduled_end="2026-09-02T12:00:00Z",
        )
        record_trial_results(trial2["id"], passed=True, yield_units=470)

        resp = api_client.activate_process_authority_letter(letter2["id"], PA)
        validate_error(resp, ApiErrorId.ERR_LETTER_REVISION_STALE)
        letter2_after = get_letter(letter2["id"])
        assert letter2_after["status"] == "SUBMITTED"
        formula_after = get_formula(formula_id)
        assert formula_after["status"] == "TRIAL_PASSED"
        assert formula_after["revision"] == 2

    def test_qa_reviewer_cannot_activate_letter(self):
        """PRD §2.1: "Access to every endpoint is further restricted by role; an attempt to perform an action outside the caller's designated role set is rejected with an `ERR_FORBIDDEN` error."
        PRD §4: "| POST | `/copack/process-authority-letters/{id}/activate` | Activate a `SUBMITTED` letter, superseding others and approving the formula | ProcessAuthority |"

        Design: Corner/rbac/qa_reviewer_cannot_activate_letter
        """
        ctx = setup_trial_passed_formula()
        resp = api_client.activate_process_authority_letter(
            ctx["letter"]["id"], QA
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        letter_after = get_letter(ctx["letter"]["id"])
        assert letter_after["status"] == "SUBMITTED", (
            f"forbidden activation must not change the letter, got "
            f"{letter_after['status']}"
        )


class TestReformulationCascade:

    def _setup_with_planned_and_confirmed_runs(self):
        ctx = setup_approved_acidified_formula()
        ctx["kettle"] = create_kettle_line()
        ctx["bottle"] = create_packaging_component(
            component_name="12oz woozy bottle",
            component_type="BOTTLE",
            unit_cost_cents=50,
            initial_on_hand_units=100_000,
        )
        requirements = [
            {"component_id": ctx["bottle"]["id"], "quantity_per_unit": 1}
        ]
        ctx["run_planned"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-11T08:00:00Z",
            scheduled_end="2026-09-11T12:00:00Z",
            packaging_requirements=requirements,
        )
        ctx["run_confirmed"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            scheduled_start="2026-09-12T08:00:00Z",
            scheduled_end="2026-09-12T16:00:00Z",
            packaging_requirements=requirements,
        )
        resp = api_client.confirm_production_run(ctx["run_confirmed"]["id"], OPS)
        validate_success(resp, 200)
        return ctx

    def test_reformulate_supersedes_letter_and_cancels_runs(self):
        """PRD §3.3: "The cascade is deliberately destructive: the formula's `ACTIVE` letter, if any, becomes `SUPERSEDED`; every production run of the formula in `PLANNED` or `CONFIRMED` is cancelled; and for each such run that was `CONFIRMED`, its packaging reservations are released (each component's `reserved_units` reduced by that run's requirement), its consigned ingredients are restored (each `CUSTOMER_SUPPLIED` line's `consigned_units_on_hand` increased by `quantity_per_unit` multiplied by the run's `planned_units`), and its estimate is refunded (the customer's `outstanding_billed_cents` reduced by the run's `estimated_charge_cents`)."

        Design: Difficulty/transitive_cascade/reformulate_letter_run_packaging_cascade
        """
        ctx = self._setup_with_planned_and_confirmed_runs()
        resp = api_client.reformulate_formula(ctx["formula"]["id"], OPS)
        validate_success(resp, 200)

        formula_after = get_formula(ctx["formula"]["id"])
        assert formula_after["status"] == "DRAFT"
        assert formula_after["revision"] == 2
        letter_after = get_letter(ctx["letter"]["id"])
        assert letter_after["status"] == "SUPERSEDED", (
            f"ACTIVE letter must be SUPERSEDED by reformulation, got "
            f"{letter_after['status']}"
        )
        run_p_after = get_run(ctx["run_planned"]["id"])
        run_c_after = get_run(ctx["run_confirmed"]["id"])
        assert run_p_after["status"] == "CANCELLED"
        assert run_c_after["status"] == "CANCELLED"

    def test_reformulate_releases_reservations_restores_stock_and_refunds(self):
        """PRD §3.3: "The cascade is deliberately destructive: the formula's `ACTIVE` letter, if any, becomes `SUPERSEDED`; every production run of the formula in `PLANNED` or `CONFIRMED` is cancelled; and for each such run that was `CONFIRMED`, its packaging reservations are released (each component's `reserved_units` reduced by that run's requirement), its consigned ingredients are restored (each `CUSTOMER_SUPPLIED` line's `consigned_units_on_hand` increased by `quantity_per_unit` multiplied by the run's `planned_units`), and its estimate is refunded (the customer's `outstanding_billed_cents` reduced by the run's `estimated_charge_cents`)."

        Design: Difficulty/transitive_cascade/reformulate_letter_run_packaging_cascade
        """
        ctx = self._setup_with_planned_and_confirmed_runs()
        # Pre-cascade: confirmed run reserved 2000 bottles, drew 1000 pepper
        # units, and billed its estimate.
        from test_helpers import get_customer, get_ingredient_supply, get_packaging_component

        pre_component = get_packaging_component(ctx["bottle"]["id"])
        assert pre_component["reserved_units"] == 2000

        validate_success(
            api_client.reformulate_formula(ctx["formula"]["id"], OPS), 200
        )

        component_after = get_packaging_component(ctx["bottle"]["id"])
        assert component_after["reserved_units"] == 0, (
            f"reservation must be released by the cascade, got "
            f"{component_after['reserved_units']}"
        )
        assert component_after["on_hand_units"] == 100_000
        customer_after = get_customer(ctx["customer"]["id"])
        assert customer_after["outstanding_billed_cents"] == 0, (
            f"confirmed run's estimate must be refunded, got "
            f"{customer_after['outstanding_billed_cents']}"
        )
        supply_after = get_ingredient_supply(ctx["pepper"]["id"])
        assert supply_after["consigned_units_on_hand"] == 5000, (
            f"drawn consignment must be restored, got "
            f"{supply_after['consigned_units_on_hand']}"
        )


class TestLabelCompliance:

    def test_label_submit_rejects_allergen_mismatch(self):
        """PRD §3.8: "Submitting a draft — again `OpsAdmin` or the owning `Customer` — first requires the label to be in `DRAFT` (`ERR_LABEL_NOT_DRAFT`) and then, evaluated after the state gate, demands that `allergen_declaration` equal the formula's `allergen_class`; a declaration that disagrees with the recipe is rejected with `ERR_LABEL_ALLERGEN_MISMATCH`."

        Design: Corner/validations/label_submit_allergen_mismatch
        """
        ctx_customer = setup_trial_passed_formula()
        label = create_label(
            ctx_customer["formula"]["id"], allergen_declaration="SOY"
        )
        resp = api_client.submit_label_approval(label["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_LABEL_ALLERGEN_MISMATCH)
        label_after = get_label(label["id"])
        assert label_after["status"] == "DRAFT"

    def test_label_submit_twice_rejected(self):
        """PRD §3.8: "Submitting a draft — again `OpsAdmin` or the owning `Customer` — first requires the label to be in `DRAFT` (`ERR_LABEL_NOT_DRAFT`) and then, evaluated after the state gate, demands that `allergen_declaration` equal the formula's `allergen_class`; a declaration that disagrees with the recipe is rejected with `ERR_LABEL_ALLERGEN_MISMATCH`."

        Design: Corner/state_machines/label_submit_twice_rejected
        """
        ctx = setup_trial_passed_formula()
        label = create_label(ctx["formula"]["id"])
        submit_label(label["id"])

        resp = api_client.submit_label_approval(label["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_DRAFT)
        label_after = get_label(label["id"])
        assert label_after["status"] == "SUBMITTED"


class TestReleaseLabelGate:

    def _setup_completed_run_with_submitted_label(self):
        ctx = setup_approved_acidified_formula()
        ctx["label"] = create_label(ctx["formula"]["id"])
        submit_label(ctx["label"]["id"])
        ctx["kettle"] = create_kettle_line()
        ctx["run"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            packaging_requirements=[],
        )
        validate_success(api_client.confirm_production_run(ctx["run"]["id"], OPS), 200)
        complete = api_client.complete_production_run(
            ctx["run"]["id"],
            {
                "actual_units_produced": 2000,
                "measured_ph": 4.1,
                "measured_water_activity": 0.88,
            },
            OPS,
        )
        validate_success(complete, 200)
        return ctx

    def test_release_blocked_until_label_approved(self):
        """PRD §3.8: "Release is the last gate a finished run passes, and it belongs to the `QAReviewer` alone. The run must be in `COMPLETED` (`ERR_RUN_NOT_COMPLETED`), no `OPEN` quality hold may reference it (`ERR_HOLD_BLOCKS_RELEASE`), and at least one label for the run's formula must have reached `APPROVED` (`ERR_LABEL_NOT_APPROVED`)."

        Design: Difficulty/cross_entity_state_dependency/release_requires_label_approved
        """
        ctx = self._setup_completed_run_with_submitted_label()
        resp = api_client.release_production_run(ctx["run"]["id"], QA)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED)
        run_after = get_run(ctx["run"]["id"])
        assert run_after["status"] == "COMPLETED"
        label_after = get_label(ctx["label"]["id"])
        assert label_after["status"] == "SUBMITTED"

    def test_release_succeeds_after_label_approved(self):
        """PRD §3.8: "Release is the last gate a finished run passes, and it belongs to the `QAReviewer` alone. The run must be in `COMPLETED` (`ERR_RUN_NOT_COMPLETED`), no `OPEN` quality hold may reference it (`ERR_HOLD_BLOCKS_RELEASE`), and at least one label for the run's formula must have reached `APPROVED` (`ERR_LABEL_NOT_APPROVED`). A run that clears all three moves to `RELEASED` — shippable, billable, and done."
        PRD §3.8: "The review carries an `approved` flag and an optional `review_note`: approval moves the label to `APPROVED`, rejection to `REJECTED`, both terminal."

        Design: Difficulty/cross_entity_state_dependency/release_requires_label_approved
        """
        ctx = self._setup_completed_run_with_submitted_label()
        validate_success(
            api_client.review_label_approval(
                ctx["label"]["id"], {"approved": True}, QA
            ),
            200,
        )
        resp = api_client.release_production_run(ctx["run"]["id"], QA)
        released = validate_success(resp, 200)
        assert released["status"] == "RELEASED", (
            f"run with an APPROVED label must release, got "
            f"{released['status']}"
        )
