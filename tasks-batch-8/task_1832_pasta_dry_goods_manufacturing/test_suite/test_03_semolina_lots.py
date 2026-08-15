"""Semolina lots: grading variants, acceptance gates, mixing quality/weight
gates, depletion boundary, and the mass-conservation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    abort_run,
    advance_run,
    assert_lot_mass_invariant,
    create_accepted_lot,
    create_active_contract,
    create_approved_recipe,
    create_line,
    create_recipe_draft,
    get_lot,
    receive_lot,
    schedule_run,
    set_clock,
    setup_scheduled_run,
    submit_lot_labs,
    validate_error,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]
TECH = TEST_USERS["qa_technician_headers"]
QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


class TestSemolinaGradeCertificateVsLab:
    def test_certificate_grade_at_receipt(self, api):
        """PRD: "The `cert_grade_score` is the weighted blend — 0.40 times the
        protein score, plus 0.25 times the gluten score, plus 0.20 times the
        falling score, plus 0.15 times the moisture score — at 2 decimal places,
        round half-up"
        PRD: "a score of at least 70.0 earns `GRADE_A`, at least 50.0 but below
        70.0 earns `GRADE_B`, and below 50.0 earns `GRADE_REJECT`"
        PRD: "The new lot starts `QUARANTINED`"

        Design: Difficulty/dual_variant_calc/semolina_grade_certificate_vs_lab_divergence
        """
        contract = create_active_contract(contract_code="C-GR1")
        lot = receive_lot(contract["id"], 100.0)

        assert lot["cert_grade_score"] == pytest.approx(63.75), (
            "0.40*75 + 0.25*80 + 0.20*50 + 0.15*25 = 63.75"
        )
        assert lot["cert_grade"] == "GRADE_B"
        assert lot["status"] == "QUARANTINED"

    def test_lab_grade_diverges_from_certificate(self, api):
        """PRD: "which recompute the LAB variant of the same score from the lab
        inputs and store it as `lab_grade_score` and `lab_grade`"
        PRD: "Submitting lab results against a `QUARANTINED` lot refreshes the
        values in place"

        Design: Difficulty/dual_variant_calc/semolina_grade_certificate_vs_lab_divergence
        """
        contract = create_active_contract(contract_code="C-GR1")
        lot = receive_lot(contract["id"], 100.0)

        updated = submit_lot_labs(lot["id"])
        assert updated["lab_grade_score"] == pytest.approx(81.5), (
            "0.40*95 + 0.25*88 + 0.20*70 + 0.15*50 = 81.5"
        )
        assert updated["lab_grade"] == "GRADE_A"
        assert updated["cert_grade_score"] == pytest.approx(63.75), (
            "the certificate variant is untouched by lab submission"
        )
        assert updated["cert_grade"] == "GRADE_B"
        assert updated["status"] == "QUARANTINED", "lab results alone do not accept"


def test_lot_accept_state_and_lab_preconditions(api):
    """PRD: "lab results must exist at all (`ERR_INVALID_REQUEST` if
    `lab_grade` is unrecorded)"
    PRD: "A `QAManager` dispositions a `QUARANTINED` lot."
    PRD: "Rejection moves a `QUARANTINED` lot to `REJECTED`"

    Design: Corner/state_machines/lot_accept_state_and_lab_preconditions
    """
    contract = create_active_contract(contract_code="C-LST")
    fresh = receive_lot(contract["id"], 100.0)
    accepted = create_accepted_lot(contract["id"], 100.0)

    resp1 = api.accept_lot(fresh["id"], QAM)
    validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

    resp2 = api.accept_lot(accepted["id"], QAM)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    resp3 = api.reject_lot(accepted["id"], QAM)
    validate_error(resp3, ApiErrorId.ERR_INVALID_STATE)


def test_lot_accept_moisture_cap_and_grade_reject(api):
    """PRD: "`lab_moisture_pct` may not exceed the safety cap of 15.0
    regardless of how good the grade score is (`ERR_MOISTURE_CAP_EXCEEDED`)"
    PRD: "and `lab_grade` may not be `GRADE_REJECT`
    (`ERR_LOT_GRADE_BELOW_CONTRACT`)"

    Design: Corner/errors/lot_accept_moisture_cap_and_grade_reject
    """
    contract = create_active_contract(contract_code="C-CAP")
    moist = receive_lot(contract["id"], 100.0)
    moist = submit_lot_labs(moist["id"], lab_moisture_pct=15.5)
    assert moist["lab_grade_score"] == pytest.approx(75.25)
    assert moist["lab_grade"] == "GRADE_A"

    resp1 = api.accept_lot(moist["id"], QAM)
    validate_error(resp1, ApiErrorId.ERR_MOISTURE_CAP_EXCEEDED)

    failing = receive_lot(contract["id"], 100.0)
    failing = submit_lot_labs(
        failing["id"], lab_protein_pct=11.5, lab_moisture_pct=14.8,
        lab_gluten_index=60, lab_falling_number_s=260,
    )
    assert failing["lab_grade_score"] == pytest.approx(39.0)
    assert failing["lab_grade"] == "GRADE_REJECT"

    resp2 = api.accept_lot(failing["id"], QAM)
    validate_error(resp2, ApiErrorId.ERR_LOT_GRADE_BELOW_CONTRACT)


def test_lot_not_accepted_and_recipe_not_approved_gates(api):
    """PRD: "The recipe must be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`)."
    PRD: "The semolina lot must be `ACCEPTED` (`ERR_LOT_NOT_ACCEPTED`)."

    Design: Corner/errors/lot_not_accepted_and_recipe_not_approved_gates
    """
    contract = create_active_contract(contract_code="C-NAG")
    quarantined_lot = receive_lot(contract["id"], 1000.0)
    draft_recipe = create_recipe_draft(recipe_name="Draft NAG")
    ok_recipe = create_approved_recipe(recipe_name="Approved NAG")
    line = create_line("L-NAG")

    resp1 = api.create_production_run(
        {
            "recipe_id": draft_recipe["id"],
            "line_id": line["id"],
            "semolina_lot_id": quarantined_lot["id"],
            "planned_input_kg": 100.0,
            "scheduled_start": "2026-08-10T00:00:00Z",
            "scheduled_end": "2026-08-11T00:00:00Z",
            "expected_line_version": line["version"],
        },
        OP,
    )
    validate_error(resp1, ApiErrorId.ERR_RECIPE_NOT_APPROVED)

    run = schedule_run(ok_recipe["id"], line["id"], quarantined_lot["id"], 100.0)
    set_clock("2026-08-10T00:00:00Z")
    resp2 = api.advance_run(run["id"], {}, OP)
    validate_error(resp2, ApiErrorId.ERR_LOT_NOT_ACCEPTED)


def test_lot_quality_minimum_gate_at_mixing(api):
    """PRD: "For every ingredient row of the recipe that names `SEMOLINA` and
    carries a `min_protein_pct`, the lot's `lab_protein_pct` must meet or exceed
    that minimum, else `ERR_LOT_QUALITY_INSUFFICIENT`."

    Design: Corner/validations/lot_quality_minimum_gate_at_mixing
    """
    sc = setup_scheduled_run(
        contract_code="C-LQG",
        recipe_overrides={
            "recipe_name": "HighProtein LQG",
            "ingredients": [
                {"ingredient_type": "SEMOLINA", "percentage": 100.0, "min_protein_pct": 14.0}
            ],
        },
        planned_input_kg=100.0,
    )
    # The world's lot carries lab protein 13.8, below the recipe's 14.0 minimum.
    set_clock("2026-08-10T00:00:00Z")
    resp = api.advance_run(sc["run"]["id"], {}, OP)
    validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_INSUFFICIENT)


class TestTemporalTrumpsFiscal:
    def test_premature_mixing_reports_schedule_not_weight(self, api):
        """PRD: "The clock must have reached at least `scheduled_start` minus
        the run's `changeover_minutes` — an earlier attempt is
        `ERR_INVALID_SCHEDULE`."
        PRD: "and finally the fiscal check on lot consumption,
        `ERR_INSUFFICIENT_LOT_WEIGHT`, evaluated last so that a run blocked for
        several reasons reports the structural or safety problem before the
        budget-of-material one."

        Design: Difficulty/priority_pair_validation_conflict/temporal_trumps_fiscal_on_premature_mixing_advance
        """
        sc = setup_scheduled_run(
            contract_code="C-PV2", lot_weight_kg=100.0,
            planned_input_kg=500.0,
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-02T00:00:00Z",
            with_die=False,
        )
        # Clock stays at the 2026-08-01 default: temporal gate fails, and the
        # fiscal gate (500 kg planned vs 100 kg remaining) fails too.
        resp = api.advance_run(sc["run"]["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_SCHEDULE)

    def test_fiscal_check_fires_when_temporal_satisfied(self, api):
        """PRD: "And finally, evaluated after all structural checks, the lot's
        `remaining_weight_kg` must cover `planned_input_kg`
        (`ERR_INSUFFICIENT_LOT_WEIGHT`, HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_trumps_fiscal_on_premature_mixing_advance
        """
        sc = setup_scheduled_run(
            contract_code="C-PV2B", lot_weight_kg=100.0, planned_input_kg=500.0,
            with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        resp = api.advance_run(sc["run"]["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_WEIGHT)
        lot = get_lot(sc["lot"]["id"])
        assert lot["remaining_weight_kg"] == 100.0, "no partial consumption on rejection"


def test_insufficient_lot_weight_fiscal_error(api):
    """PRD: "the lot's `remaining_weight_kg` must cover `planned_input_kg`
    (`ERR_INSUFFICIENT_LOT_WEIGHT`, HTTP 402)."

    Design: Corner/validations/insufficient_lot_weight_fiscal_error
    """
    sc = setup_scheduled_run(
        contract_code="C-FIS", lot_weight_kg=100.0, planned_input_kg=500.0,
        with_die=False,
    )
    set_clock("2026-08-10T00:00:00Z")
    resp = api.advance_run(sc["run"]["id"], {}, OP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_WEIGHT)

    lot = get_lot(sc["lot"]["id"])
    assert lot["remaining_weight_kg"] == 100.0
    assert lot["status"] == "ACCEPTED"


class TestLotDepletedAtExactlyZero:
    def test_exact_remainder_consumption_depletes_lot(self, api):
        """PRD: "A lot that reaches exactly zero remaining weight through
        consumption transitions itself to `DEPLETED`."
        PRD: "Success stamps `actual_started_at`, moves the run to `MIXING`,
        decrements the lot's `remaining_weight_kg` by `planned_input_kg`, adds
        the same amount to `consumed_kg`, and — if that consumption zeroes the
        lot — flips the lot to `DEPLETED`."

        Design: Difficulty/boundary_precision_check/lot_depleted_at_exactly_zero_remaining
        """
        sc = setup_scheduled_run(
            contract_code="C-DEP", lot_weight_kg=500.0, planned_input_kg=500.0,
            with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        run = advance_run(sc["run"]["id"])
        assert run["production_status"] == "MIXING"

        lot = get_lot(sc["lot"]["id"])
        assert lot["remaining_weight_kg"] == 0.0
        assert lot["consumed_kg"] == 500.0
        assert lot["status"] == "DEPLETED", "zero-remainder auto-transition"
        assert_lot_mass_invariant(lot)

    def test_partial_then_exact_consumption_depletes_only_at_zero(self, api):
        """PRD: "A lot that reaches exactly zero remaining weight through
        consumption transitions itself to `DEPLETED`."
        PRD: "the invariant that received equals remaining plus consumed holds
        from birth and is preserved by every consumption and refund"

        Design: Difficulty/boundary_precision_check/lot_depleted_at_exactly_zero_remaining
        """
        sc = setup_scheduled_run(
            contract_code="C-DEP2", lot_weight_kg=500.0, planned_input_kg=300.0,
            with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        advance_run(sc["run"]["id"])
        lot = get_lot(sc["lot"]["id"])
        assert lot["remaining_weight_kg"] == 200.0
        assert lot["status"] == "ACCEPTED", "partial consumption does not deplete"

        run2 = schedule_run(sc["recipe"]["id"], sc["line"]["id"], sc["lot"]["id"],
                            planned_input_kg=200.0,
                            scheduled_start="2026-08-12T00:00:00Z",
                            scheduled_end="2026-08-13T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")
        advance_run(run2["id"])
        lot = get_lot(sc["lot"]["id"])
        assert lot["remaining_weight_kg"] == 0.0
        assert lot["consumed_kg"] == 500.0
        assert lot["status"] == "DEPLETED"
        assert_lot_mass_invariant(lot)


class TestSemolinaMassConservation:
    def test_mixing_abort_refunds_lot_exactly(self, api):
        """PRD: "Aborting from `MIXING` refunds the semolina lot —
        `remaining_weight_kg` grows by `planned_input_kg` and `consumed_kg`
        shrinks by the same"
        PRD: "the invariant that received equals remaining plus consumed holds
        from birth and is preserved by every consumption and refund"

        Design: Difficulty/compensating_invariant/semolina_mass_conservation_consume_then_refund
        """
        sc = setup_scheduled_run(
            contract_code="C-INV", lot_weight_kg=500.0, planned_input_kg=200.0,
            with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        advance_run(sc["run"]["id"])

        mid = get_lot(sc["lot"]["id"])
        assert mid["remaining_weight_kg"] == 300.0
        assert mid["consumed_kg"] == 200.0
        assert_lot_mass_invariant(mid)

        abort_run(sc["run"]["id"])
        post = get_lot(sc["lot"]["id"])
        assert post["remaining_weight_kg"] == 500.0
        assert post["consumed_kg"] == 0.0
        assert post["status"] == "ACCEPTED", "compensation leaves no drift"
        assert_lot_mass_invariant(post)

    def test_second_full_consume_closes_invariant_at_depleted(self, api):
        """PRD: "the invariant that received equals remaining plus consumed
        holds from birth and is preserved by every consumption and refund"
        PRD: "A lot that reaches exactly zero remaining weight through
        consumption transitions itself to `DEPLETED`."

        Design: Difficulty/compensating_invariant/semolina_mass_conservation_consume_then_refund
        """
        sc = setup_scheduled_run(
            contract_code="C-INV2", lot_weight_kg=500.0, planned_input_kg=200.0,
            with_die=False,
        )
        set_clock("2026-08-10T00:00:00Z")
        advance_run(sc["run"]["id"])
        abort_run(sc["run"]["id"])

        run2 = schedule_run(sc["recipe"]["id"], sc["line"]["id"], sc["lot"]["id"],
                            planned_input_kg=500.0,
                            scheduled_start="2026-08-12T00:00:00Z",
                            scheduled_end="2026-08-13T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")
        advance_run(run2["id"])

        lot = get_lot(sc["lot"]["id"])
        assert lot["remaining_weight_kg"] == 0.0
        assert lot["consumed_kg"] == 500.0
        assert lot["status"] == "DEPLETED", "500 == 0 + 500 closes the invariant"
        assert_lot_mass_invariant(lot)
