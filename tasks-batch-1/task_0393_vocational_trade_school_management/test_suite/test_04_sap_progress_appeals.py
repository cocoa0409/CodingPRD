"""SAP review pace/classification and appeal dimensions.

Covers difficulty queue A:
  - dual_variant_calc / sap_first_offense_vs_repeat_offense_diverge
  - combinatorial_formula / sap_pace_nested_min_max_conditional
  - non_linear_state_machine / sap_parallel_standing_and_appeal_dimensions
And corner queue B:
  - state_machines / appeal_on_good_standing_rejected
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

ADVISOR = TEST_USERS["academic_advisor_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# combinatorial_formula / sap_pace_nested_min_max_conditional
# --------------------------------------------------------------------------
def test_sap_pace_combines_checkpoint_span_and_program_hours(api):
    """PRD §3.5: "The expected hours are the elapsed fraction multiplied by the
    program's required_clock_hours. When the expected hours are 0,
    measured_pace_pct is exactly 1.0; otherwise measured_pace_pct is
    clock_hours_completed divided by the expected hours."
    PRD §3.5: "The elapsed fraction is checkpoint_term_index minus the cohort's
    start_term_index, divided by that span, then clamped to lie between a floor of
    0.0 and a cap of 1.0."

    Design: Difficulty/combinatorial_formula/sap_pace_nested_min_max_conditional
    """
    # 1000h program, span 8, 250 hours, checkpoint 4 -> elapsed 0.5 -> expected
    # 500 -> pace 250/500 = 0.5.
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 900_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 900_000},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=250, attended_hours=250, term_index=1)
    sap = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 4}, ADVISOR),
        expected_status=201)
    assert sap["measured_pace_pct"] == pytest.approx(0.5, abs=1e-9), sap


def test_sap_pace_05_classifies_warning(api):
    """PRD §3.5: "If measured_pace_pct is at least sap_warning_min_pace_pct, the
    standing is GOOD (a pace exactly equal to the warning threshold is GOOD).
    Otherwise, if measured_pace_pct is at least sap_probation_min_pace_pct, the
    standing is WARNING."

    Design: Difficulty/combinatorial_formula/sap_pace_nested_min_max_conditional
    """
    # pace 0.5: < warning 0.667, >= probation 0.5 -> WARNING.
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 900_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 900_000},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=250, attended_hours=250, term_index=1)
    sap = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 4}, ADVISOR),
        expected_status=201)
    assert sap["standing"] == "WARNING", sap


# --------------------------------------------------------------------------
# dual_variant_calc / sap_first_offense_vs_repeat_offense_diverge
# --------------------------------------------------------------------------
def test_sap_first_offense_yields_probation(api):
    """PRD §3.5: "Otherwise — the pace is below the probation floor — the result
    depends on history: if the prior standing was either WARNING or PROBATION, the
    standing escalates straight to DISMISSED, because a consecutive sub-floor
    review is a repeat offense; but if the prior standing was GOOD, this first
    sub-floor review yields PROBATION rather than DISMISSED."

    Design: Difficulty/dual_variant_calc/sap_first_offense_vs_repeat_offense_diverge
    """
    # 200 hours, checkpoint 6 -> expected (6/8)*1000 = 750 -> pace 0.2667 (<0.5),
    # prior GOOD (no prior review) -> PROBATION.
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 800_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 800_000},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=200, attended_hours=200, term_index=1)
    sap = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 6}, ADVISOR),
        expected_status=201)
    assert sap["standing"] == "PROBATION", sap


def test_sap_repeat_offense_escalates_to_dismissed(api):
    """PRD §3.5: "if the prior standing was either WARNING or PROBATION, the
    standing escalates straight to DISMISSED, because a consecutive sub-floor
    review is a repeat offense ..."
    PRD §3.5: "These two branches must be treated with equal weight: a first
    offense lands on PROBATION, a repeat offense lands on DISMISSED."

    Design: Difficulty/dual_variant_calc/sap_first_offense_vs_repeat_offense_diverge
    """
    # 250 hours: checkpoint 4 pace 0.5 -> WARNING; checkpoint 6 pace 250/750=0.3333
    # (<0.5) with prior WARNING -> DISMISSED.
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 800_000},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 800_000},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=250, attended_hours=250, term_index=1)
    first = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 4}, ADVISOR),
        expected_status=201)
    assert first["standing"] == "WARNING", first
    second = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 6}, ADVISOR),
        expected_status=201)
    assert second["standing"] == "DISMISSED", second


# --------------------------------------------------------------------------
# non_linear_state_machine / sap_parallel_standing_and_appeal_dimensions
# --------------------------------------------------------------------------
def test_appeal_grant_keeps_frozen_standing_and_overturns_mirror(api):
    """PRD §3.5: "appeal_status is a parallel dimension on the same review row,
    independent of the frozen standing, cycling NONE → APPEALED →
    {APPEAL_GRANTED, APPEAL_DENIED} and defaulting to NONE."
    PRD §3.5: "A GRANT moves appeal_status to APPEAL_GRANTED; if this review is
    the agreement's latest SapStanding and its standing is DISMISSED, the
    agreement's mirror sap_standing is recomputed to PROBATION (the grant
    overturns dismissal down to probation) and the agreement's version
    increments."

    Design: Difficulty/non_linear_state_machine/sap_parallel_standing_and_appeal_dimensions
    """
    _, _, agreement, dismissed = fx.setup_dismissed_sap_standing()
    assert dismissed["standing"] == "DISMISSED", dismissed

    appealed = validate_success(api.appeal_sap_standing(dismissed["id"], ADVISOR))
    assert appealed["appeal_status"] == "APPEALED", appealed

    granted = validate_success(api.resolve_appeal(dismissed["id"], {"decision": "GRANT"}, ADVISOR))
    # appeal_status moves; the frozen standing dimension stays DISMISSED.
    assert granted["appeal_status"] == "APPEAL_GRANTED", granted
    assert granted["standing"] == "DISMISSED", granted

    agr_after = validate_success(api.get_agreement(agreement["id"], REGISTRAR))
    assert agr_after["sap_standing"] == "PROBATION", agr_after


def test_appeal_status_cycles_independently_of_standing(api):
    """PRD §3.5: "appeal_status is a parallel dimension on the same review row,
    independent of the frozen standing, cycling NONE → APPEALED →
    {APPEAL_GRANTED, APPEAL_DENIED} and defaulting to NONE."
    PRD §3.5: "Filing an appeal moves appeal_status NONE → APPEALED: it requires
    appeal_status to currently be NONE (else ERR_INVALID_STATE) and the review's
    standing to be PROBATION or DISMISSED (else ERR_SAP_NOT_APPEALABLE) ..."

    Design: Difficulty/non_linear_state_machine/sap_parallel_standing_and_appeal_dimensions
    """
    _, _, agreement, dismissed = fx.setup_dismissed_sap_standing()
    # Before any appeal action the parallel dimension is NONE while standing is DISMISSED.
    assert dismissed["appeal_status"] == "NONE", dismissed
    assert dismissed["standing"] == "DISMISSED", dismissed
    appealed = validate_success(api.appeal_sap_standing(dismissed["id"], ADVISOR))
    assert appealed["appeal_status"] == "APPEALED", appealed
    assert appealed["standing"] == "DISMISSED", appealed


# --------------------------------------------------------------------------
# corner: appeal_on_good_standing_rejected
# --------------------------------------------------------------------------
def test_appeal_on_good_standing_rejected(api):
    """PRD §3.5: "Filing an appeal moves appeal_status NONE → APPEALED: it
    requires appeal_status to currently be NONE (else ERR_INVALID_STATE) and the
    review's standing to be PROBATION or DISMISSED (else ERR_SAP_NOT_APPEALABLE);
    appeals are meaningful only on a probation or dismissal standing."

    Design: Corner/state_machines/appeal_on_good_standing_rejected
    """
    # Full-pace hours at checkpoint 4: 500 hours, expected 500 -> pace 1.0 -> GOOD.
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=500, attended_hours=500, term_index=1)
    sap = validate_success(
        api.create_sap_standing({"agreement_id": agreement["id"], "checkpoint_term_index": 4}, ADVISOR),
        expected_status=201)
    assert sap["standing"] == "GOOD", sap
    resp = api.appeal_sap_standing(sap["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_SAP_NOT_APPEALABLE.value)
