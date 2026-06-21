"""Aid disbursement release gating, ledger reconciliation, and priority order.

Covers difficulty queue A:
  - priority_pair_validation_conflict / release_gate_unmet_beats_aid_over_award
And corner queue B:
  - calculations / ledger_balance_after_release
  - validations / disbursement_out_of_order_rejected
  - validations / duplicate_disbursement_index_rejected
  - cross_cutting_complexity_layers / aid_over_award_release_rejected
  - cross_cutting_complexity_layers / derived_disbursed_aid_reconciles_after_release
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

FAID = TEST_USERS["financial_aid_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / release_gate_unmet_beats_aid_over_award
# --------------------------------------------------------------------------
def test_release_gate_unmet_beats_aid_over_award(api):
    """PRD §3.6: "the agreement's clock_hours_completed must have reached at least
    this draw's required_clock_hours_gate (else ERR_DISBURSEMENT_GATE_UNMET);
    every lower-index draw of the agreement must already be RELEASED, unless this
    is index 1 (else ERR_DISBURSEMENT_OUT_OF_ORDER); and the sum of
    already-RELEASED amounts plus this draw's planned_amount_cents must not exceed
    the agreement's scheduled_aid_cents (else ERR_AID_OVER_AWARD)."

    Design: Difficulty/priority_pair_validation_conflict/release_gate_unmet_beats_aid_over_award
    """
    # scheduled_aid 100000, 0 clock hours; draw index 1 amount 200000 (over award)
    # with gate 500 (unmet). The gate check is listed before the over-award check.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 800_000},
        agreement_overrides={"contract_tuition_cents": 800_000, "scheduled_aid_cents": 100_000},
    )
    draw = fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                                    planned_amount_cents=200_000, required_clock_hours_gate=500)
    resp = api.release_disbursement(draw["id"], FAID)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_GATE_UNMET.value)


def test_release_gate_unmet_http_422(api):
    """PRD §3.6: "the agreement's clock_hours_completed must have reached at least
    this draw's required_clock_hours_gate (else ERR_DISBURSEMENT_GATE_UNMET) ..."

    Design: Difficulty/priority_pair_validation_conflict/release_gate_unmet_beats_aid_over_award
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 800_000},
        agreement_overrides={"contract_tuition_cents": 800_000, "scheduled_aid_cents": 100_000},
    )
    draw = fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                                    planned_amount_cents=200_000, required_clock_hours_gate=500)
    resp = api.release_disbursement(draw["id"], FAID)
    assert resp.status_code == 422, resp.text
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_GATE_UNMET.value)


# --------------------------------------------------------------------------
# corner: ledger_balance_after_release
# --------------------------------------------------------------------------
def test_ledger_balance_after_release(api):
    """PRD §3.6: "On release the draw's amount_cents is set to planned_amount_cents,
    the agreement's disbursed_aid_cents and ledger_balance_cents are recomputed,
    and the agreement's version increments."
    PRD §3.6: "The agreement's ledger_balance_cents is contract_tuition_cents
    minus disbursed_aid_cents."

    Design: Corner/calculations/ledger_balance_after_release
    """
    # contract 1000000, scheduled_aid 600000, one draw 200000 gate 0.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 1_000_000},
        agreement_overrides={"contract_tuition_cents": 1_000_000, "scheduled_aid_cents": 600_000},
    )
    draw = fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                                    planned_amount_cents=200_000, required_clock_hours_gate=0)
    validate_success(api.release_disbursement(draw["id"], FAID))
    agr = validate_success(api.get_agreement(agreement["id"], FAID))
    assert agr["disbursed_aid_cents"] == 200_000, agr
    assert agr["ledger_balance_cents"] == 800_000, agr


# --------------------------------------------------------------------------
# corner: disbursement_out_of_order_rejected
# --------------------------------------------------------------------------
def test_disbursement_out_of_order_rejected(api):
    """PRD §3.6: "every lower-index draw of the agreement must already be RELEASED,
    unless this is index 1 (else ERR_DISBURSEMENT_OUT_OF_ORDER) ..."

    Design: Corner/validations/disbursement_out_of_order_rejected
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 1_000_000},
        agreement_overrides={"contract_tuition_cents": 1_000_000, "scheduled_aid_cents": 800_000},
    )
    fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                             planned_amount_cents=200_000, required_clock_hours_gate=0)
    d2 = fx.schedule_disbursement(agreement["id"], disbursement_index=2,
                                  planned_amount_cents=200_000, required_clock_hours_gate=0)
    # Release index 2 while index 1 is still SCHEDULED.
    resp = api.release_disbursement(d2["id"], FAID)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_OUT_OF_ORDER.value)


# --------------------------------------------------------------------------
# corner: duplicate_disbursement_index_rejected
# --------------------------------------------------------------------------
def test_duplicate_disbursement_index_rejected(api):
    """PRD §3.6: "a disbursement_index (the 1-based ordinal of this draw in the
    agreement's schedule, an integer of at least 1 and unique within the
    agreement; a collision is rejected with ERR_DUPLICATE_KEY) ..."

    Design: Corner/validations/duplicate_disbursement_index_rejected
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 1_000_000},
        agreement_overrides={"contract_tuition_cents": 1_000_000, "scheduled_aid_cents": 800_000},
    )
    fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                             planned_amount_cents=200_000, required_clock_hours_gate=0)
    resp = api.create_disbursement(
        {"agreement_id": agreement["id"], "disbursement_index": 1,
         "planned_amount_cents": 300_000, "required_clock_hours_gate": 0}, FAID)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# --------------------------------------------------------------------------
# corner: aid_over_award_release_rejected
# --------------------------------------------------------------------------
def test_aid_over_award_release_rejected(api):
    """PRD §3.6: "the sum of already-RELEASED amounts plus this draw's
    planned_amount_cents must not exceed the agreement's scheduled_aid_cents (else
    ERR_AID_OVER_AWARD)."

    Design: Corner/cross_cutting_complexity_layers/aid_over_award_release_rejected
    """
    # scheduled_aid 200000, gate 0; single draw 200001 (one cent over).
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 1_000_000},
        agreement_overrides={"contract_tuition_cents": 1_000_000, "scheduled_aid_cents": 200_000},
    )
    draw = fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                                    planned_amount_cents=200_001, required_clock_hours_gate=0)
    resp = api.release_disbursement(draw["id"], FAID)
    validate_error(resp, ApiErrorId.ERR_AID_OVER_AWARD.value)


# --------------------------------------------------------------------------
# corner: derived_disbursed_aid_reconciles_after_release
# --------------------------------------------------------------------------
def test_derived_disbursed_aid_reconciles_after_two_releases(api):
    """PRD §3.6: "The agreement's disbursed_aid_cents is the sum of amount_cents
    over the agreement's draws whose status is RELEASED (scheduled, returned, and
    cancelled draws are excluded)."
    PRD §3.6: "The agreement's ledger_balance_cents is contract_tuition_cents
    minus disbursed_aid_cents."

    Design: Corner/cross_cutting_complexity_layers/derived_disbursed_aid_reconciles_after_release
    """
    # contract 1000000, scheduled_aid 600000, two draws (200000, 400000).
    _, _, agreement, _ = fx.setup_agreement_with_released_aid(
        draw_amounts=[200_000, 400_000], scheduled_aid_cents=600_000,
        contract_tuition_cents=1_000_000, theory_hours=0)
    agr = validate_success(api.get_agreement(agreement["id"], FAID))
    assert agr["disbursed_aid_cents"] == 600_000, agr
    assert agr["ledger_balance_cents"] == 400_000, agr
