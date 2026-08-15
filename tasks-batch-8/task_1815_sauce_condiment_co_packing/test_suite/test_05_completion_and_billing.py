"""Run completion, estimate-vs-final billing, pH boundary compliance, and the
confirm/cancel compensation invariants (PRD §3.5, §3.6, §3.1)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    cancel_run,
    complete_run,
    confirm_run,
    create_kettle_line,
    create_run,
    get_customer,
    get_ingredient_supply,
    get_packaging_component,
    get_run,
    list_run_holds,
    release_run,
    setup_approved_acidified_formula,
    setup_confirmed_run,
    validate_error,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


class TestEstimateVsFinalCharge:
    """One run priced by two variants: the estimate bills planned units, the
    final bills actuals."""

    def test_confirm_computes_estimate_from_planned_units(self):
        """PRD §3.5: "The units billed are the greater of `planned_units` and the formula's `min_run_units` — the contractual minimum run size is billed even when the plan is smaller. The base co-pack fee is those units billed multiplied by `unit_rate_cents`."
        PRD §3.5: "The `estimated_charge_cents` is the base plus the locked changeover fee plus the ingredient total plus the packaging total."

        Design: Difficulty/dual_variant_calc/run_charge_estimate_vs_final
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        run = get_run(ctx["run"]["id"])
        # max(2000, 1000)*120 + 15000 + round(0.8*2000*300) + 2000*50 + 2000*12
        assert run["estimated_charge_cents"] == 859000, (
            f"estimate variant must bill planned units, got "
            f"{run['estimated_charge_cents']}"
        )
        assert run["changeover_fee_cents"] == 15000

    def test_complete_replaces_estimate_with_final_charge(self):
        """PRD §3.6: "The units billed are the greater of `actual_units_produced` and `min_run_units`; the base fee is those units multiplied by `unit_rate_cents`; the changeover fee is the value locked at confirmation, never recomputed."
        PRD §3.6: "Billing then moves by the delta: the customer's `outstanding_billed_cents` increases by the final charge minus the previously applied charge, where "previously applied" means `estimated_charge_cents` on the first completion and the prior `final_charge_cents` on a re-completion after rework."
        PRD §3.6: "Absent any deviation — or absent any `ACTIVE` letter — the run simply moves to `COMPLETED`."

        Design: Difficulty/dual_variant_calc/run_charge_estimate_vs_final
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        complete_run(ctx["run"]["id"], 1800, 4.1, 0.88)
        run = get_run(ctx["run"]["id"])
        # max(1800, 1000)*120 + 15000 + round(0.8*1800*300) + 1800*50 + 1800*12
        assert run["final_charge_cents"] == 774600, (
            f"final variant must bill actual units, got "
            f"{run['final_charge_cents']}"
        )
        assert run["status"] == "COMPLETED", (
            f"4.1 <= 4.2 and 0.88 < 0.9 produce no auto-hold, got "
            f"{run['status']}"
        )
        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_billed_cents"] == 774600, (
            f"the final charge replaces the estimate via the billing delta "
            f"(859000 -> 774600), got {customer['outstanding_billed_cents']}"
        )


class TestPhBoundaryCompliance:

    def _setup_no_packaging_confirmed_run(self):
        ctx = setup_approved_acidified_formula()
        ctx["kettle"] = create_kettle_line()
        ctx["run"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            packaging_requirements=[],
        )
        confirm_run(ctx["run"]["id"])
        return ctx

    def test_ph_equal_to_letter_max_is_compliant(self):
        """PRD §3.3: "Within the statutory bounds, the letter's thresholds are the contract's deviation lines: a batch's pH deviates when its measured value exceeds `max_ph`, while water activity deviates when its measured value reaches or exceeds `max_water_activity`."
        PRD §3.6: "Absent any deviation — or absent any `ACTIVE` letter — the run simply moves to `COMPLETED`."

        Design: Difficulty/boundary_precision_check/ph_equality_is_compliant_at_complete
        """
        ctx = self._setup_no_packaging_confirmed_run()
        complete_run(ctx["run"]["id"], 2000, 4.2, 0.88)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "COMPLETED", (
            f"measured_ph exactly equal to max_ph 4.2 is compliant (strict "
            f"> predicate), got {run['status']}"
        )
        holds, meta = list_run_holds(ctx["run"]["id"])
        assert len(holds) == 0 and meta["total_count"] == 0, (
            f"no auto-hold may be created at the boundary, got {len(holds)}"
        )

    def test_final_charge_at_ph_boundary(self):
        """PRD §3.6: "The units billed are the greater of `actual_units_produced` and `min_run_units`; the base fee is those units multiplied by `unit_rate_cents`; the changeover fee is the value locked at confirmation, never recomputed. Ingredient lines extend against the units billed exactly as in the estimate — `quantity_per_unit` multiplied by the units billed multiplied by `unit_cost_cents`, rounded half-up per line then summed — while packaging lines extend against physical reality: `quantity_per_unit` multiplied by `actual_units_produced` multiplied by the component's `unit_cost_cents`, again rounded per line before summation."

        Design: Difficulty/boundary_precision_check/ph_equality_is_compliant_at_complete
        """
        ctx = self._setup_no_packaging_confirmed_run()
        complete_run(ctx["run"]["id"], 2000, 4.2, 0.88)
        run = get_run(ctx["run"]["id"])
        # max(2000, 1000)*120 + 15000 + round(0.8*2000*300), no packaging
        assert run["final_charge_cents"] == 735000


class TestConfirmCancelPackagingInvariant:

    def test_confirm_reserves_packaging_and_draws_consignment(self):
        """PRD §3.5: "A successful confirmation moves the run to `CONFIRMED`, bumps its `version`, and posts three sets of effects: the customer's `outstanding_billed_cents` increases by `estimated_charge_cents`; each packaging requirement reserves stock, raising the component's `reserved_units` by `quantity_per_unit` multiplied by `planned_units`; and each `CUSTOMER_SUPPLIED` line draws down consignment, reducing `consigned_units_on_hand` by the same per-line quantity."

        Design: Difficulty/compensating_invariant/confirm_cancel_restores_packaging_reserved
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        bottle = get_packaging_component(ctx["bottle"]["id"])
        cap = get_packaging_component(ctx["cap"]["id"])
        assert bottle["reserved_units"] == 2000
        assert cap["reserved_units"] == 2000
        assert bottle["on_hand_units"] == 100_000, (
            "confirm reserves but does not consume on-hand stock"
        )
        pepper = get_ingredient_supply(ctx["pepper"]["id"])
        assert pepper["consigned_units_on_hand"] == 4000, (
            f"confirm must draw 0.5*2000=1000 consigned units, got "
            f"{pepper['consigned_units_on_hand']}"
        )

    def test_cancel_releases_reservations_and_restores_consignment(self):
        """PRD §3.5: "Cancelling a `CONFIRMED` run unwinds everything confirmation posted: each component's `reserved_units` falls by its requirement, each consigned line's `consigned_units_on_hand` is restored by `quantity_per_unit` multiplied by `planned_units`, and the customer's `outstanding_billed_cents` is reduced by `estimated_charge_cents`."

        Design: Difficulty/compensating_invariant/confirm_cancel_restores_packaging_reserved
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        cancel_run(ctx["run"]["id"])
        bottle = get_packaging_component(ctx["bottle"]["id"])
        cap = get_packaging_component(ctx["cap"]["id"])
        assert bottle["reserved_units"] == 0
        assert cap["reserved_units"] == 0
        assert bottle["on_hand_units"] == 100_000, (
            "on_hand is untouched by the confirm/cancel pair"
        )
        pepper = get_ingredient_supply(ctx["pepper"]["id"])
        assert pepper["consigned_units_on_hand"] == 5000


class TestConfirmCancelBillingInvariant:

    def test_confirm_bills_estimate_to_customer(self):
        """PRD §3.1: "That figure is the account's live billing exposure: it rises by a run's estimate at confirmation, moves by the difference between the final charge and whatever was previously applied at each completion, falls by the estimate when a confirmed run is cancelled, and falls by the final charge when a produced batch is destroyed."

        Design: Difficulty/compensating_invariant/confirm_cancel_restores_billed_cents
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_billed_cents"] == 859000, (
            f"confirm must debit the estimate, got "
            f"{customer['outstanding_billed_cents']}"
        )

    def test_cancel_refunds_estimate_exactly(self):
        """PRD §3.5: "Cancelling a `CONFIRMED` run unwinds everything confirmation posted: each component's `reserved_units` falls by its requirement, each consigned line's `consigned_units_on_hand` is restored by `quantity_per_unit` multiplied by `planned_units`, and the customer's `outstanding_billed_cents` is reduced by `estimated_charge_cents`."
        PRD §3.5: "Backing out is possible while a run is in `PLANNED` or `CONFIRMED`; against any other status the cancellation is rejected with `ERR_RUN_NOT_CANCELLABLE`."

        Design: Difficulty/compensating_invariant/confirm_cancel_restores_billed_cents
        """
        ctx = setup_confirmed_run(packaging="bottle_cap")
        cancelled = cancel_run(ctx["run"]["id"])
        assert cancelled["status"] == "CANCELLED"
        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_billed_cents"] == 0, (
            f"cancel must credit the estimate back exactly, got "
            f"{customer['outstanding_billed_cents']}"
        )


class TestTerminalAndStateGuards:

    def test_released_run_cannot_be_cancelled(self):
        """PRD §3.5: "Backing out is possible while a run is in `PLANNED` or `CONFIRMED`; against any other status the cancellation is rejected with `ERR_RUN_NOT_CANCELLABLE`. Cancelling a `PLANNED` run simply moves it to `CANCELLED`."

        Design: Corner/state_machines/released_run_cancel_rejected
        """
        ctx = setup_approved_acidified_formula(with_label=True)
        ctx["kettle"] = create_kettle_line()
        ctx["run"] = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            packaging_requirements=[],
        )
        confirm_run(ctx["run"]["id"])
        complete_run(ctx["run"]["id"], 2000, 4.1, 0.88)
        release_run(ctx["run"]["id"])

        resp = api_client.cancel_production_run(ctx["run"]["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_CANCELLABLE)
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "RELEASED"
        customer = get_customer(ctx["customer"]["id"])
        # billing intact: final 2000*120 + 15000 + round(0.8*2000*300)
        assert customer["outstanding_billed_cents"] == 735000

    def test_complete_rejected_on_planned_run(self):
        """PRD §3.6: "Completion is recorded by an `OpsAdmin` against a run in `CONFIRMED` or `REWORK`; a run in any other status is rejected with `ERR_RUN_NOT_COMPLETABLE`."

        Design: Corner/endpoints/complete_planned_run_rejected
        """
        ctx = setup_approved_acidified_formula()
        ctx["kettle"] = create_kettle_line()
        run = create_run(
            ctx["formula"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T08:00:00Z",
            scheduled_end="2026-09-10T12:00:00Z",
            packaging_requirements=[],
        )
        resp = api_client.complete_production_run(
            run["id"],
            {
                "actual_units_produced": 1000,
                "measured_ph": 4.1,
                "measured_water_activity": 0.88,
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_COMPLETABLE)
        run_after = get_run(run["id"])
        assert run_after["status"] == "PLANNED"
