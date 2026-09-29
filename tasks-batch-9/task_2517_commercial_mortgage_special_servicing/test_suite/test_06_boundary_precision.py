"""Boundary precision: inclusive and strict comparisons decided by a single cent
or a single millisecond.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ARA_ONE_CENT_AMOUNT,
    ARA_UPDATE_AMOUNT,
    CONSULTATION_DEADLINE_SEP,
    CONTROL_NOTIONAL_ONE_CENT_BELOW,
    CONTROL_THRESHOLD_SMALL_TRUST,
    PI_OBLIGATION_WITH_ARA_ONE_CENT,
    PI_OBLIGATION_WITH_ARA_ROUND,
)
from test_helpers.test_users import (
    ASSET_MANAGER,
    MASTER_SERVICER,
    PLATFORM_ADMIN,
    TRUSTEE,
)


# ==========================================================================
# The control test is inclusive on the controlling side
# ==========================================================================
def _trust_with_a_provisional_reduction(api, deal_name, loan_number, appraised_value):
    """An 8,000,000.00 controlling class and a 19,500,000.00 loan carrying an
    unpublished reduction driven by the supplied appraised value."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={
            "deal_name": deal_name,
            "original_controlling_class_balance_usd": 8000000,
        },
        loan_overrides={"loan_number": loan_number, "accrued_unpaid_interest_usd": 0},
        event_factory=fx.record_bankruptcy_event,
    )
    fx.accepted_appraisal(api, built["loan_id"], value_usd=appraised_value)
    built["reduction"] = fx.provisional_reduction(api, built["loan_id"])
    return built


def test_a_notional_exactly_at_the_threshold_retains_control(api):
    """8,000,000.00 less 6,000,000.00 is exactly 25% and control survives.

    The PRD: "The boundary is inclusive on the controlling side: a notional
    exactly equal to the threshold retains control, and one cent less loses it."

    Design: Difficulty/boundary_precision_check/control_termination_at_exact_twenty_five_percent_notional
    """
    built = _trust_with_a_provisional_reduction(api, "CMBS 2026-E1", "L-E01", 15000000)
    a.assert_money(
        built["reduction"]["ara_amount_usd"], ARA_UPDATE_AMOUNT, "ara_amount_usd"
    )

    fx.make_reduction_effective(api, built["reduction"]["id"])

    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(trust["total_ara_usd"], ARA_UPDATE_AMOUNT, "total_ara_usd")
    a.assert_money(
        trust["controlling_class_notional_usd"],
        CONTROL_THRESHOLD_SMALL_TRUST,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust, "CONTROLLING", "control_status")


def test_a_notional_ninety_cents_below_the_threshold_loses_control(api):
    """One dollar off the appraised value moves the trust across the boundary.

    The PRD: "When the notional is greater than or equal to that threshold,
    `control_status` is `CONTROLLING`; when it is strictly below, `control_status`
    is `CONSULTING_ONLY`."

    Design: Difficulty/boundary_precision_check/control_termination_at_exact_twenty_five_percent_notional
    """
    built = _trust_with_a_provisional_reduction(api, "CMBS 2026-F1", "L-F01", 14999999)
    a.assert_money(
        built["reduction"]["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "ara_amount_usd"
    )

    fx.make_reduction_effective(api, built["reduction"]["id"])

    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(trust["total_ara_usd"], ARA_ONE_CENT_AMOUNT, "total_ara_usd")
    a.assert_money(
        trust["controlling_class_notional_usd"],
        CONTROL_NOTIONAL_ONE_CENT_BELOW,
        "controlling_class_notional_usd",
    )
    a.assert_status(trust, "CONSULTING_ONLY", "control_status")


def test_the_two_trusts_differ_by_ninety_cents_across_the_boundary(api):
    """The whole outcome turns on a 0.90 difference in the reduction.

    The PRD: "Compute the control threshold as twenty-five percent of
    `original_controlling_class_balance_usd`, rounded half up to two decimal
    places."

    Design: Difficulty/boundary_precision_check/control_termination_at_exact_twenty_five_percent_notional
    """
    at_threshold = _trust_with_a_provisional_reduction(
        api, "CMBS 2026-E1", "L-E01", 15000000
    )
    below_threshold = _trust_with_a_provisional_reduction(
        api, "CMBS 2026-F1", "L-F01", 14999999
    )
    fx.make_reduction_effective(api, at_threshold["reduction"]["id"])
    fx.make_reduction_effective(api, below_threshold["reduction"]["id"])

    keeps = fx.read_trust(api, at_threshold["trust_id"], TRUSTEE)
    loses = fx.read_trust(api, below_threshold["trust_id"], TRUSTEE)
    a.assert_money(
        loses["total_ara_usd"] - keeps["total_ara_usd"], 0.90, "reduction difference"
    )
    a.assert_status(keeps, "CONTROLLING", "control_status")
    a.assert_status(loses, "CONSULTING_ONLY", "control_status")


# ==========================================================================
# The deemed-consent sweep is strict at millisecond resolution
# ==========================================================================
def _consultation_at_its_deadline(api):
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    trust = fx.create_trust(
        api, deal_name="CMBS 2026-S2", consultation_response_business_days=10
    )
    loan = fx.create_mid_size_loan(api, trust["id"], loan_number="L-S201")
    fx.record_transfer_event(
        api,
        loan["id"],
        event_code="RECEIVERSHIP",
        occurred_on="2026-08-25T00:00:00Z",
        evidence_note="receiver appointed",
        days_delinquent_at_event=None,
    )
    fx.transfer_to_special_servicing(api, loan["id"])

    built = fx.scored_plan(api, loan["id"])
    fx.recommend_plan(api, built["plan_id"], built["plan"]["recommended_alternative_id"])
    consultation = fx.issue_plan_consultation(api, trust["id"], built["plan_id"])

    fx.set_clock(api, CONSULTATION_DEADLINE_SEP)
    return {
        "trust_id": trust["id"],
        "plan_id": built["plan_id"],
        "consultation_id": consultation["id"],
        "consultation": consultation,
    }


def test_a_sweep_at_the_exact_deadline_instant_sweeps_nothing(api):
    """A clock equal to the deadline leaves the consultation pending.

    The PRD: "The `PlatformAdmin` runs a sweep capability that finds every
    `PENDING` consultation whose `deadline_at` is **strictly** before the current
    logical clock — a consultation whose `deadline_at` is exactly equal to the
    clock is left `PENDING`, and a response is still accepted at that instant —
    and moves each `PENDING → DEEMED_CONSENTED`."

    Design: Difficulty/boundary_precision_check/consultation_sweep_at_exact_deadline_instant
    """
    scenario = _consultation_at_its_deadline(api)
    assert scenario["consultation"]["deadline_at"] == CONSULTATION_DEADLINE_SEP
    a.assert_millisecond_timestamp(
        scenario["consultation"]["deadline_at"], "deadline_at"
    )

    swept = validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_id"]}, PLATFORM_ADMIN)
    )
    assert swept["swept_count"] == 0
    assert swept["deemed_consented_ids"] == []

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], ASSET_MANAGER)
    )
    a.assert_status(consultation, "PENDING")
    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "CONSULTATION")


def test_a_sweep_one_millisecond_later_deems_the_consultation_consented(api):
    """Advancing past the deadline sweeps exactly the one consultation.

    The PRD: "The sweep may be narrowed to one trust by supplying `trust_id`,
    processes matching consultations in `deadline_at` ascending order with
    `created_at` ascending as the tie-break, and reports `swept_count` together
    with `deemed_consented_ids`, the identifiers it swept."

    Design: Difficulty/boundary_precision_check/consultation_sweep_at_exact_deadline_instant
    """
    scenario = _consultation_at_its_deadline(api)
    validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_id"]}, PLATFORM_ADMIN)
    )

    fx.set_clock(api, "2026-09-17T00:00:00Z")
    swept = validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_id"]}, PLATFORM_ADMIN)
    )
    assert swept["swept_count"] == 1
    assert swept["deemed_consented_ids"] == [scenario["consultation_id"]]

    consultation = validate_success(
        api.get_consultation(scenario["consultation_id"], ASSET_MANAGER)
    )
    a.assert_status(consultation, "DEEMED_CONSENTED")
    plan = validate_success(api.get_workout_plan(scenario["plan_id"], ASSET_MANAGER))
    a.assert_status(plan, "CONSENT_SATISFIED")


def test_a_repeat_sweep_finds_nothing_because_the_row_is_no_longer_pending(api):
    """Only PENDING consultations are eligible, so the sweep is not repeatable.

    The PRD: "Each swept consultation cascades a workout-plan subject in
    `CONSULTATION` to `CONSENT_SATISFIED`."

    Design: Difficulty/boundary_precision_check/consultation_sweep_at_exact_deadline_instant
    """
    scenario = _consultation_at_its_deadline(api)
    fx.set_clock(api, "2026-09-17T00:00:00Z")
    validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_id"]}, PLATFORM_ADMIN)
    )

    again = validate_success(
        api.sweep_consultations({"trust_id": scenario["trust_id"]}, PLATFORM_ADMIN)
    )
    assert again["swept_count"] == 0
    assert again["deemed_consented_ids"] == []


# ==========================================================================
# The P&I advance ceiling is inclusive to the cent
# ==========================================================================
def _loan_at_the_ara_adjusted_ceiling(api):
    built = fx.loan_in_special_servicing(
        api,
        loan_overrides={"loan_number": "L-A01", "accrued_unpaid_interest_usd": 0},
    )
    fx.effective_reduction(api, built["loan_id"], value_usd=14999999)
    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["ara_amount_usd"], ARA_ONE_CENT_AMOUNT, "ara_amount_usd")
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "required_monthly_pi_advance_usd",
    )
    built["loan"] = loan
    return built


def test_an_advance_exactly_at_the_reduced_obligation_is_accepted(api):
    """The comparison is inclusive at the cent.

    The PRD: "The comparison is inclusive, so an amount exactly equal to the
    obligation is permitted and a single cent more is not — and since the
    obligation shrinks the moment an appraisal reduction becomes effective, an
    advance that would have been fine yesterday can be refused today."

    Design: Difficulty/boundary_precision_check/pi_advance_at_exact_ara_adjusted_obligation_ceiling
    """
    built = _loan_at_the_ara_adjusted_ceiling(api)

    advance = validate_success(
        api.create_advance(
            f.advance_payload(
                built["loan_id"],
                advance_type="PI_ADVANCE",
                amount_usd=PI_OBLIGATION_WITH_ARA_ONE_CENT,
                advanced_on="2026-08-01T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )
    a.assert_status(advance, "OUTSTANDING")
    a.assert_money(advance["amount_usd"], PI_OBLIGATION_WITH_ARA_ONE_CENT, "amount_usd")
    a.assert_money(advance["accrued_interest_usd"], 0.00, "accrued_interest_usd")


def test_an_advance_one_cent_over_the_reduced_obligation_is_refused(api):
    """A single cent past the ceiling is a fiscal breach.

    The PRD: "A `PI_ADVANCE` may not exceed the loan's
    `required_monthly_pi_advance_usd`; one that does is refused with
    `ERR_ADVANCE_EXCEEDS_ARA_ADJUSTED_OBLIGATION`."

    Design: Difficulty/boundary_precision_check/pi_advance_at_exact_ara_adjusted_obligation_ceiling
    """
    built = _loan_at_the_ara_adjusted_ceiling(api)

    response = api.create_advance(
        f.advance_payload(
            built["loan_id"],
            advance_type="PI_ADVANCE",
            amount_usd=PI_OBLIGATION_WITH_ARA_ROUND,
            advanced_on="2026-08-01T00:00:00Z",
        ),
        MASTER_SERVICER,
    )
    validate_error(response, e.ERR_ADVANCE_EXCEEDS_ARA_ADJUSTED_OBLIGATION, 422)

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(loan["advances_outstanding_usd"], 0.00, "advances_outstanding_usd")


def test_the_accepted_advance_does_not_move_the_ceiling_it_was_measured_against(api):
    """The obligation depends on principal and the reduction, not on advances.

    The PRD: "It is recomputed on every change to `ara_amount_usd` — that is,
    whenever a reduction reaches `EFFECTIVE`, `RECALCULATED` or `REVERSED`."

    Design: Difficulty/boundary_precision_check/pi_advance_at_exact_ara_adjusted_obligation_ceiling
    """
    built = _loan_at_the_ara_adjusted_ceiling(api)
    validate_success(
        api.create_advance(
            f.advance_payload(
                built["loan_id"],
                advance_type="PI_ADVANCE",
                amount_usd=PI_OBLIGATION_WITH_ARA_ONE_CENT,
                advanced_on="2026-08-01T00:00:00Z",
            ),
            MASTER_SERVICER,
        ),
        201,
    )

    loan = fx.read_loan(api, built["loan_id"], MASTER_SERVICER)
    a.assert_money(
        loan["required_monthly_pi_advance_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "required_monthly_pi_advance_usd",
    )
    a.assert_money(
        loan["advances_outstanding_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "advances_outstanding_usd",
    )
    trust = fx.read_trust(api, built["trust_id"], TRUSTEE)
    a.assert_money(
        trust["total_advances_outstanding_usd"],
        PI_OBLIGATION_WITH_ARA_ONE_CENT,
        "total_advances_outstanding_usd",
    )
