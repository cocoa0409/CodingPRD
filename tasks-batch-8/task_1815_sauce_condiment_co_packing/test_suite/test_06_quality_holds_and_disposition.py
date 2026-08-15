"""Quality holds: auto-hold deviation metrics, the rework cycle, destroy
cascade, statutory gate, owner routing, and segregation of duties
(PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    complete_run,
    confirm_run,
    create_kettle_line,
    create_manual_hold,
    create_run,
    get_customer,
    get_hold,
    get_packaging_component,
    get_run,
    list_run_holds,
    make_customer_headers,
    make_qa_reviewer_headers,
    release_run,
    setup_approved_acidified_formula,
    setup_completed_clean_run,
    setup_confirmed_run,
    setup_run_on_hold,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


class TestAutoHoldDeviationMetrics:

    def test_deviating_ph_creates_auto_hold_and_blocks_completion(self):
        """PRD §3.6: "When the run's formula has an `ACTIVE` process-authority letter and the recorded measurements deviate from it — `measured_ph` exceeding the letter's `max_ph`, or `measured_water_activity` reaching or exceeding the letter's `max_water_activity` — the system does not let the run reach `COMPLETED`. Instead it creates a `QualityHold` whose `created_by_user_id` is the literal string `system`, whose measurements are copied from the completion call, and whose `reason_category` is `PH_DEVIATION` when the pH deviates, otherwise `AW_DEVIATION` (pH takes precedence when both deviate), and the run moves to `ON_HOLD` rather than `COMPLETED`."

        Design: Difficulty/dual_variant_calc/hold_deviation_letter_vs_statutory
        """
        ctx = setup_run_on_hold(measured_ph=4.5, actual_units_produced=2000)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "ON_HOLD"
        hold = ctx["hold"]
        assert hold["reason_category"] == "PH_DEVIATION", (
            f"4.5 > 4.2 letter limit must file PH_DEVIATION, got "
            f"{hold['reason_category']}"
        )
        assert hold["created_by_user_id"] == "system"

    def test_hold_metrics_measure_letter_deviation_and_statutory_margin(self):
        """PRD §3.7: "When the hold's reason is `PH_DEVIATION` and the formula has an `ACTIVE` letter, `letter_deviation` is the hold's `measured_ph` minus the letter's `max_ph`, and `statutory_margin` is 4.6 minus the measured pH."
        PRD §3.7: "Every hold, manual or automatic, copies its `disposition_owner` from the owning customer's `default_disposition_owner` at creation, fixing who may later resolve it."

        Design: Difficulty/dual_variant_calc/hold_deviation_letter_vs_statutory
        """
        ctx = setup_run_on_hold(measured_ph=4.5, actual_units_produced=2000)
        hold = get_hold(ctx["hold"]["id"])
        # 4.5 - 4.2 = +0.30 (over the letter limit); 4.6 - 4.5 = +0.10.
        assert hold["letter_deviation"] == pytest.approx(0.3, abs=1e-9), (
            f"letter_deviation must be measured_ph - max_ph, got "
            f"{hold['letter_deviation']}"
        )
        assert hold["statutory_margin"] == pytest.approx(0.1, abs=1e-9), (
            f"statutory_margin must be 4.6 - measured_ph, got "
            f"{hold['statutory_margin']}"
        )
        assert hold["disposition_owner"] == "CUSTOMER"


class TestReworkCycle:

    def test_rework_disposition_returns_run_to_completable_state(self):
        """PRD §3.7: "`REWORK` moves the run from `ON_HOLD` to `REWORK`, making it completable again under §3.6 with fresh actuals, a recomputed final charge, and a billing delta against the prior final."

        Design: Difficulty/non_linear_state_machine/run_hold_rework_cycle
        """
        ctx = setup_run_on_hold(measured_ph=4.4, with_label=True)
        resp = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "REWORK"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        hold_after = validate_success(resp, 200)
        assert hold_after["status"] == "DISPOSITIONED"
        assert hold_after["disposition"] == "REWORK"
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "REWORK", (
            f"REWORK disposition must make the run completable, got "
            f"{run['status']}"
        )

    def test_recomplete_recomputes_final_and_consumes_packaging_again(self):
        """PRD §3.6: "For each requirement line, `on_hand_units` falls by `quantity_per_unit` multiplied by `actual_units_produced` on every completion; the corresponding release of `reserved_units` by `quantity_per_unit` multiplied by `planned_units` happens on the first completion only, since the reservation is already zero by the time a rework re-completion runs."
        PRD §3.6: "Billing then moves by the delta: the customer's `outstanding_billed_cents` increases by the final charge minus the previously applied charge, where "previously applied" means `estimated_charge_cents` on the first completion and the prior `final_charge_cents` on a re-completion after rework."
        PRD §3.7: "`REWORK` moves the run from `ON_HOLD` to `REWORK`, making it completable again under §3.6 with fresh actuals, a recomputed final charge, and a billing delta against the prior final."

        Design: Difficulty/non_linear_state_machine/run_hold_rework_cycle
        """
        ctx = setup_run_on_hold(measured_ph=4.4, with_label=True)
        validate_success(
            api_client.disposition_quality_hold(
                ctx["hold"]["id"],
                {"disposition": "REWORK"},
                make_customer_headers(ctx["customer"]["id"]),
            ),
            200,
        )
        complete_run(ctx["run"]["id"], 1900, 4.1, 0.88)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "COMPLETED", (
            f"re-completion within letter limits must complete, got "
            f"{run['status']}"
        )
        # 1900*120 + 15000 + round(0.8*1900*300) + 1900*50 + 1900*12
        assert run["final_charge_cents"] == 816800, (
            f"final must recompute against new actuals, got "
            f"{run['final_charge_cents']}"
        )
        bottle = get_packaging_component(ctx["bottle"]["id"])
        assert bottle["on_hand_units"] == 96100, (
            f"packaging is consumed on every completion "
            f"(100000 - 2000 - 1900), got {bottle['on_hand_units']}"
        )
        released = release_run(ctx["run"]["id"])
        assert released["status"] == "RELEASED"


class TestDestroyCascade:

    def _setup_two_holds_on_run(self):
        ctx = setup_run_on_hold(measured_ph=4.5, actual_units_produced=1800)
        ctx["hold2"] = create_manual_hold(
            ctx["run"]["id"], reason_category="FOREIGN_MATERIAL", qa_user_id="qa-7"
        )
        return ctx

    def test_destroy_disposition_moves_run_to_destroyed(self):
        """PRD §3.7: "`DESTROY` moves the run from `ON_HOLD` to `DESTROYED`, and the system sweeps every other `OPEN` hold on that run into `DISPOSITIONED` with a `DESTROY` disposition of its own; because destroyed goods are not billable, the customer's `outstanding_billed_cents` is reduced by the run's `final_charge_cents`."

        Design: Difficulty/transitive_cascade/hold_destroy_run_billing_cascade
        """
        ctx = self._setup_two_holds_on_run()
        resp = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "DESTROY"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        hold1_after = validate_success(resp, 200)
        assert hold1_after["status"] == "DISPOSITIONED"
        assert hold1_after["disposition"] == "DESTROY"
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "DESTROYED"
        hold2_after = get_hold(ctx["hold2"]["id"])
        assert hold2_after["status"] == "DISPOSITIONED", (
            f"sibling OPEN hold must be swept to DISPOSITIONED, got "
            f"{hold2_after['status']}"
        )
        assert hold2_after["disposition"] == "DESTROY"

    def test_destroy_reverses_final_billing_without_returning_packaging(self):
        """PRD §3.7: "`DESTROY` moves the run from `ON_HOLD` to `DESTROYED`, and the system sweeps every other `OPEN` hold on that run into `DISPOSITIONED` with a `DESTROY` disposition of its own; because destroyed goods are not billable, the customer's `outstanding_billed_cents` is reduced by the run's `final_charge_cents`."
        PRD §3.1: "That figure is the account's live billing exposure: it rises by a run's estimate at confirmation, moves by the difference between the final charge and whatever was previously applied at each completion, falls by the estimate when a confirmed run is cancelled, and falls by the final charge when a produced batch is destroyed."

        Design: Difficulty/transitive_cascade/hold_destroy_run_billing_cascade
        """
        ctx = self._setup_two_holds_on_run()
        # First completion billed the final charge: 774600.
        pre = get_customer(ctx["customer"]["id"])
        assert pre["outstanding_billed_cents"] == 774600

        validate_success(
            api_client.disposition_quality_hold(
                ctx["hold"]["id"],
                {"disposition": "DESTROY"},
                make_customer_headers(ctx["customer"]["id"]),
            ),
            200,
        )
        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_billed_cents"] == 0, (
            f"destroyed goods are not billable; the final charge must be "
            f"reversed, got {customer['outstanding_billed_cents']}"
        )
        bottle = get_packaging_component(ctx["bottle"]["id"])
        assert bottle["on_hand_units"] == 98200, (
            f"consumed packaging of destroyed goods is not returned "
            f"(100000 - 1800), got {bottle['on_hand_units']}"
        )


class TestStatutoryGatePrecedence:

    def _setup_margin_breaching_hold(self):
        # ph 4.7 -> statutory_margin 4.6 - 4.7 = -0.1 (not strictly positive).
        return setup_run_on_hold(measured_ph=4.7, actual_units_produced=2000)

    def test_release_blocked_when_statutory_margin_non_positive(self):
        """PRD §3.7: "The statutory gate is evaluated before any actor check: a `RELEASE` or `REWORK` disposition on a `PH_DEVIATION` or `AW_DEVIATION` hold requires a strictly positive `statutory_margin` — without it the batch may only be destroyed, and the request is rejected with `ERR_STATUTORY_DESTROY_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/disposition_safety_beats_owner_constraint
        """
        ctx = self._setup_margin_breaching_hold()
        # QAReviewer is also the wrong actor for a CUSTOMER-owned hold; the
        # statutory gate (earlier pipeline stage) must fire first.
        resp = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "RELEASE"},
            make_qa_reviewer_headers("qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_STATUTORY_DESTROY_REQUIRED)

    def test_failed_statutory_gate_leaves_hold_open_and_run_on_hold(self):
        """PRD §3.7: "The statutory gate is evaluated before any actor check: a `RELEASE` or `REWORK` disposition on a `PH_DEVIATION` or `AW_DEVIATION` hold requires a strictly positive `statutory_margin` — without it the batch may only be destroyed, and the request is rejected with `ERR_STATUTORY_DESTROY_REQUIRED`."
        PRD §3.7: "The hold must be `OPEN` (`ERR_HOLD_NOT_OPEN`)."

        Design: Difficulty/priority_pair_validation_conflict/disposition_safety_beats_owner_constraint
        """
        ctx = self._setup_margin_breaching_hold()
        validate_error(
            api_client.disposition_quality_hold(
                ctx["hold"]["id"],
                {"disposition": "RELEASE"},
                make_qa_reviewer_headers("qa-1"),
            ),
            ApiErrorId.ERR_STATUTORY_DESTROY_REQUIRED,
        )
        hold_after = get_hold(ctx["hold"]["id"])
        assert hold_after["status"] == "OPEN", (
            f"a rejected disposition must leave the hold OPEN, got "
            f"{hold_after['status']}"
        )
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "ON_HOLD"


class TestAwBoundary:

    def test_aw_at_letter_limit_triggers_hold(self):
        """PRD §3.3: "Within the statutory bounds, the letter's thresholds are the contract's deviation lines: a batch's pH deviates when its measured value exceeds `max_ph`, while water activity deviates when its measured value reaches or exceeds `max_water_activity`."
        PRD §3.7: "When the reason is `AW_DEVIATION` and a letter is active, `letter_deviation` is the measured water activity minus the letter's `max_water_activity`, and `statutory_margin` is 0.85 minus the measured water activity."

        Design: Corner/calculations/aw_equality_triggers_hold
        """
        ctx = setup_approved_acidified_formula()
        ctx["kettle"] = create_kettle_line()
        ctx["run"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            packaging_requirements=[],
        )
        confirm_run(ctx["run"]["id"])
        complete_run(ctx["run"]["id"], 2000, 4.1, 0.9)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "ON_HOLD", (
            f"measured_aw 0.90 reaches max_water_activity 0.90 and must "
            f"trigger a hold, got {run['status']}"
        )
        holds, _meta = list_run_holds(ctx["run"]["id"])
        assert len(holds) == 1
        hold = holds[0]
        assert hold["reason_category"] == "AW_DEVIATION"
        assert hold["letter_deviation"] == pytest.approx(0.0, abs=1e-9)
        assert hold["statutory_margin"] == pytest.approx(-0.05, abs=1e-9)


class TestDispositionRouting:

    def test_customer_disposition_rejected_on_copacker_owned_hold(self):
        """PRD §3.7: "Owner routing enforces the hold's `disposition_owner`: a value of `CUSTOMER` requires a caller of role `Customer` whose `X-User-ID` equals the run's formula's `customer_id`, while `COPACKER` requires a `QAReviewer`; a mismatch is `ERR_DISPOSITION_OWNER_MISMATCH`."
        PRD §3.7: "`RELEASE` returns the run from `ON_HOLD` to `COMPLETED`, but only once no other `OPEN` holds remain on that run — a release that leaves sibling holds open does not free the run."

        Design: Corner/validations/copacker_owned_hold_customer_disposition_rejected
        """
        ctx = setup_run_on_hold(measured_ph=4.4, disposition_owner="COPACKER")
        assert ctx["hold"]["disposition_owner"] == "COPACKER"

        wrong = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "RELEASE"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(wrong, ApiErrorId.ERR_DISPOSITION_OWNER_MISMATCH)

        right = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "RELEASE"},
            make_qa_reviewer_headers("qa-1"),
        )
        hold_after = validate_success(right, 200)
        assert hold_after["status"] == "DISPOSITIONED"
        assert hold_after["disposition"] == "RELEASE"
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "COMPLETED", (
            f"releasing the only OPEN hold must free the run, got "
            f"{run['status']}"
        )

    def test_hold_creator_cannot_disposition_own_hold(self):
        """PRD §3.7: "Segregation of duties then forbids self-resolution: the disposition caller's `X-User-ID` must differ from the hold's `created_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/hold_segregation_of_duties
        """
        ctx = setup_completed_clean_run(disposition_owner="COPACKER")
        hold = create_manual_hold(
            ctx["run"]["id"], reason_category="FOREIGN_MATERIAL", qa_user_id="qa-7"
        )
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "ON_HOLD"

        own = api_client.disposition_quality_hold(
            hold["id"],
            {"disposition": "RELEASE"},
            make_qa_reviewer_headers("qa-7"),
        )
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other = api_client.disposition_quality_hold(
            hold["id"],
            {"disposition": "RELEASE"},
            make_qa_reviewer_headers("qa-9"),
        )
        hold_after = validate_success(other, 200)
        assert hold_after["status"] == "DISPOSITIONED"
        run_after = get_run(ctx["run"]["id"])
        assert run_after["status"] == "COMPLETED"


class TestHoldStateGates:

    def test_disposition_twice_rejected(self):
        """PRD §3.7: "The hold must be `OPEN` (`ERR_HOLD_NOT_OPEN`)."
        PRD §3.7: "`RELEASED`, `CANCELLED`, and `DESTROYED` are the terminal states of a run, and `DISPOSITIONED` is terminal for a hold."

        Design: Corner/state_machines/hold_disposition_twice_rejected
        """
        ctx = setup_run_on_hold(measured_ph=4.4)
        first = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "REWORK"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_success(first, 200)

        second = api_client.disposition_quality_hold(
            ctx["hold"]["id"],
            {"disposition": "RELEASE"},
            make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_HOLD_NOT_OPEN)
        hold_after = get_hold(ctx["hold"]["id"])
        assert hold_after["status"] == "DISPOSITIONED"
        assert hold_after["disposition"] == "REWORK"
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "REWORK"

    def test_manual_hold_requires_completed_run(self):
        """PRD §3.7: "Beyond the automatic holds of completion, a `QAReviewer` may place a manual **QualityHold** on a run in `COMPLETED` or `ON_HOLD` — against any other run status the creation is rejected with `ERR_RUN_NOT_COMPLETED`."

        Design: Corner/state_machines/hold_create_requires_completed_run
        """
        ctx = setup_confirmed_run(packaging=None)
        resp = api_client.create_quality_hold(
            {
                "production_run_id": ctx["run"]["id"],
                "reason_category": "LABEL_MISMATCH",
            },
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_COMPLETED)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "CONFIRMED"
