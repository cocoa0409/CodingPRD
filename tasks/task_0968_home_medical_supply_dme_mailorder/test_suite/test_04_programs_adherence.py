"""Resupply programs: lifecycle gates, cycle confirmation, quantity allowance,
eligibility-window boundary, adherence score variants, and return cascade."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_payer_plan,
    create_formulary_item,
    create_active_patient,
    create_program,
    suspend_program,
    confirm_cycle,
    set_logical_clock,
    setup_active_patient_with_item,
    setup_program_with_delivered_cycle,
    setup_two_cycle_adherence_scenario,
    fulfill_program_order,
    deliver_shipment,
    FULFIL,
    INTAKE,
    make_patient_headers,
)


class TestProgramLifecycleGates:
    def test_resume_active_program_rejected(self, api):
        """PRD §3.4: "resuming a program that is not `SUSPENDED` is rejected
        with `ERR_PROGRAM_NOT_SUSPENDED`."

        Design: Corner/state_machines/resume_active_program_rejected
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        program = create_program(patient["id"], category="OSTOMY")
        assert program["status"] == "ACTIVE"

        resp = api.resume_program(program["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_SUSPENDED)

    def test_duplicate_active_program_rejected(self, api):
        """PRD §3.4: "at most one `ACTIVE` program may exist per patient and
        category — a duplicate is rejected with `ERR_DUPLICATE_PROGRAM`
        (HTTP 409)."

        Design: Corner/validations/duplicate_active_program_rejected
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        create_program(patient["id"], category="OSTOMY")

        resp = api.create_resupply_program(
            {"patient_id": patient["id"], "category": "OSTOMY",
             "frequency_days": 14, "start_date": "2026-05-01"},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROGRAM)

        other = validate_success(
            api.create_resupply_program(
                {"patient_id": patient["id"], "category": "WOUND",
                 "frequency_days": 14, "start_date": "2026-05-01"},
                INTAKE,
            ),
            expected_status=201,
        )
        assert other["status"] == "ACTIVE"

    def test_confirm_on_suspended_program_rejected(self, api):
        """PRD §3.7: "a suspended program refuses cycle confirmation with
        `ERR_PROGRAM_SUSPENDED` until it is resumed."

        Design: Corner/validations/confirm_on_suspended_program_rejected
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        program = create_program(patient["id"], category="OSTOMY")
        suspend_program(program["id"], reason="manual hold")

        resp = api.confirm_cycle(program["id"], make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_SUSPENDED)

    def test_confirm_cycle_with_no_eligible_item_rejected(self, api):
        """PRD §3.4: "An empty pool rejects the confirm with
        `ERR_NO_ELIGIBLE_ITEM` (HTTP 422)."

        Design: Corner/validations/confirm_cycle_with_no_eligible_item_rejected
        """
        plan = create_payer_plan()
        # Only an OSTOMY item exists; the program is INCONTINENCE.
        create_formulary_item([plan["id"]], category="OSTOMY")
        patient = create_active_patient(plan["id"])
        program = create_program(patient["id"], category="INCONTINENCE")

        resp = api.confirm_cycle(program["id"], make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ITEM)


class TestResupplyQuantityAllowance:
    """Nested min over Rx cap (monthly_quantity x cycle_months), formulary cap,
    and PA cap."""

    def _setup_wound_program(self, api, plan_type, coinsurance, cycle_months):
        ctx = setup_active_patient_with_item(
            plan_type=plan_type,
            coinsurance_pct=coinsurance,
            cycle_months=cycle_months,
            hcpcs_code="A6250",
            category="WOUND",
            size_code="4X4",
            size_codes=("4X4",),
            pack_fee_cents=999,
            pack_size=8,
            retail_price_cents=650,
            max_units_per_cycle=30,
            requires_pa=True,
            monthly_quantity=20,
            diagnosis_codes=("L89.1",),
            with_pa=True,
            pa_approved_units=45,
            pa_valid_from="2026-05-01",
            pa_valid_to="2026-08-31",
            pa_decision="APPROVED",
        )
        program = create_program(ctx["patient"]["id"], category="WOUND",
                                 frequency_days=30, start_date="2026-05-01")
        return ctx, program

    def test_confirm_cycle_quantity_binds_at_item_cap(self, api):
        """PRD §3.4: "That allowance is the smallest of three caps: the
        prescription cap (the `monthly_quantity` of the `ACTIVE`, currently
        valid prescription covering the item's `hcpcs_code`, multiplied by the
        plan's `cycle_months`), the formulary cap (the item's
        `max_units_per_cycle`), and the prior authorization cap (the
        `approved_units` of the covering `APPROVED` authorization when the item
        requires one, or unlimited when it does not)." — min(20x3=60, 30, 45)
        binds at the formulary cap.

        Design: Difficulty/combinatorial_formula/quantity_allowance_nested_min_mode_a
        """
        ctx, program = self._setup_wound_program(api, "MEDICARE_DMEPOS", 0.20, 3)
        order = confirm_cycle(program["id"], ctx["patient"]["id"])
        assert order["origin"] == "PROGRAM_CYCLE"
        assert order["fulfillment_status"] == "SUBMITTED"

        lines = validate_success(api.list_order_lines(order["id"], INTAKE), expected_status=200)
        assert len(lines) == 1
        assert lines[0]["quantity"] == 30, (
            f"min(60 rx cap, 30 item cap, 45 PA cap) must bind at 30, got {lines[0]['quantity']}"
        )

    def test_confirm_cycle_quantity_binds_at_rx_cap(self, api):
        """PRD §3.4: "That allowance is the smallest of three caps: the
        prescription cap (the `monthly_quantity` ... multiplied by the plan's
        `cycle_months`), the formulary cap ..., and the prior authorization cap
        ..." — min(20x1=20, 30, 45) binds at the prescription cap.

        Design: Difficulty/combinatorial_formula/quantity_allowance_nested_min_mode_a
        """
        ctx, program = self._setup_wound_program(api, "COMMERCIAL", 0.10, 1)
        order = confirm_cycle(program["id"], ctx["patient"]["id"])
        assert order["origin"] == "PROGRAM_CYCLE"
        assert order["fulfillment_status"] == "SUBMITTED"

        lines = validate_success(api.list_order_lines(order["id"], INTAKE), expected_status=200)
        assert len(lines) == 1
        assert lines[0]["quantity"] == 20, (
            f"min(20 rx cap, 30 item cap, 45 PA cap) must bind at 20, got {lines[0]['quantity']}"
        )


class TestResupplyWindowBoundary:
    def test_confirm_one_day_before_window_rejected(self, api):
        """PRD §3.4: "If the current logical date is before the program's
        `next_eligible_date`, it is rejected with
        `ERR_RESUPPLY_WINDOW_NOT_OPEN` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/resupply_window_exact_day_boundary
        """
        ctx = setup_program_with_delivered_cycle()
        # Cycle 1 delivered 2026-05-03, so next_eligible_date == 2026-06-02.
        set_logical_clock("2026-06-01T00:00:00Z")
        resp = api.confirm_cycle(
            ctx["program"]["id"], make_patient_headers(ctx["patient"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESUPPLY_WINDOW_NOT_OPEN)

    def test_confirm_on_exact_eligible_date_succeeds(self, api):
        """PRD §3.4: "the eligible date itself is open — equality qualifies."

        Design: Difficulty/boundary_precision_check/resupply_window_exact_day_boundary
        """
        ctx = setup_program_with_delivered_cycle()
        set_logical_clock("2026-06-02T00:00:00Z")
        order = confirm_cycle(ctx["program"]["id"], ctx["patient"]["id"])
        assert order["origin"] == "PROGRAM_CYCLE"
        assert order["fulfillment_status"] == "SUBMITTED"


class TestDerivedNextEligibleDate:
    def test_derived_next_eligible_date_after_delivery(self, api):
        """PRD §3.4: "with `next_eligible_date` initialized to `start_date`".
        PRD §3.6: "delivery advances the program: `last_delivered_date` is set
        to the delivery date, `next_eligible_date` becomes the delivery date
        plus the program's `frequency_days`".

        Design: Corner/complexity_layers/derived_next_eligible_date_after_delivery
        """
        ctx = setup_active_patient_with_item(on_hand_qty=500)
        program = create_program(ctx["patient"]["id"], category="OSTOMY",
                                 frequency_days=30, start_date="2026-05-01")
        assert program["next_eligible_date"] == "2026-05-01"

        order = confirm_cycle(program["id"], ctx["patient"]["id"])
        shipment = fulfill_program_order(order["id"])
        set_logical_clock("2026-05-03T00:00:00Z")
        deliver_shipment(shipment["id"])

        after = validate_success(
            api.get_resupply_program(program["id"], INTAKE), expected_status=200
        )
        assert after["last_delivered_date"] == "2026-05-03"
        assert after["next_eligible_date"] == "2026-06-02"


class TestAdherenceScoreVariants:
    def test_adherence_provisional_counts_in_transit(self, api):
        """PRD §3.7: "The **provisional** score, `adherence_score_provisional`,
        is delivered plus in-transit cycles divided by cycles due, also rounded
        half up to 2 decimal places". PRD §3.7: "The denominator, `cycles_due`,
        is the number of whole `frequency_days` periods elapsed from
        `start_date` through the current logical date, plus one" — (1 delivered
        + 1 in-transit) / 3 due.

        Design: Difficulty/dual_variant_calc/adherence_provisional_vs_final_variant
        """
        ctx = setup_two_cycle_adherence_scenario()
        program = validate_success(
            api.get_resupply_program(ctx["program"]["id"], INTAKE), expected_status=200
        )
        assert program["adherence_score_provisional"] == pytest.approx(0.67, abs=0.001), (
            f"(1 delivered + 1 in-transit) / 3 due must round to 0.67, "
            f"got {program['adherence_score_provisional']}"
        )

    def test_adherence_final_delivered_only_no_suspend_on_read(self, api):
        """PRD §3.7: "The **final** score, `adherence_score_final`, is delivered
        cycles divided by cycles due, rounded half up to 2 decimal places, and
        it gates suspension." PRD §3.7: "Whenever a shipment return recomputes
        the scores and the final score falls strictly below 0.50, the program
        moves from `ACTIVE` to `SUSPENDED`" — a read alone never suspends.

        Design: Difficulty/dual_variant_calc/adherence_provisional_vs_final_variant
        """
        ctx = setup_two_cycle_adherence_scenario()
        program = validate_success(
            api.get_resupply_program(ctx["program"]["id"], INTAKE), expected_status=200
        )
        assert program["adherence_score_final"] == pytest.approx(0.33, abs=0.001), (
            f"1 delivered / 3 due must round to 0.33, got {program['adherence_score_final']}"
        )
        assert program["adherence_score_provisional"] != program["adherence_score_final"]
        assert program["status"] == "ACTIVE"


class TestReturnAdherenceCascade:
    def test_return_marks_shipment_and_recomputes_final(self, api):
        """PRD §3.6: "A shipment in `SHIPPED` or `DELIVERED` status may be
        returned by a `FulfillmentAgent`, moving it to the terminal `RETURNED`
        state". PRD §3.6: "The returned cycle counts as **non-adherent**, and
        the program's adherence scores are recomputed" — final drops to
        1 delivered / 3 due.

        Design: Difficulty/transitive_cascade/return_adherence_suspend_cascade
        """
        ctx = setup_two_cycle_adherence_scenario()
        returned = validate_success(
            api.return_shipment(ctx["shp2"]["id"], FULFIL), expected_status=200
        )
        assert returned["status"] == "RETURNED"

        program = validate_success(
            api.get_resupply_program(ctx["program"]["id"], INTAKE), expected_status=200
        )
        assert program["adherence_score_final"] == pytest.approx(0.33, abs=0.001)

    def test_return_below_threshold_suspends_program(self, api):
        """PRD §3.7: "Whenever a shipment return recomputes the scores and the
        final score falls strictly below 0.50, the program moves from `ACTIVE`
        to `SUSPENDED` with `suspend_reason` set to `LOW_ADHERENCE` and its
        `version` incremented".

        Design: Difficulty/transitive_cascade/return_adherence_suspend_cascade
        """
        ctx = setup_two_cycle_adherence_scenario()
        validate_success(api.return_shipment(ctx["shp2"]["id"], FULFIL), expected_status=200)

        program = validate_success(
            api.get_resupply_program(ctx["program"]["id"], INTAKE), expected_status=200
        )
        assert program["status"] == "SUSPENDED"
        assert program["suspend_reason"] == "LOW_ADHERENCE"

