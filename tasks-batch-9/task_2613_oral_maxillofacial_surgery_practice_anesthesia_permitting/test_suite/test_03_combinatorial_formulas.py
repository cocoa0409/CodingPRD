"""Multi-input formulas: the nested risk factor block, per-line benefit rounding,
and the restocking tier keyed on the subtotal."""
import pytest

from test_helpers import (
    create_evaluation_for,
    create_lot,
    dispose_reservation,
    draft_case,
    fetch_practice,
    fetch_reservation,
    open_determination,
    reserve_from_lot,
    service_line,
    setup_practice_with_roster,
    sign_evaluation_as,
    submit_determination,
    clear_case,
    fetch_case,
    assert_reservation,
    assert_money_identity,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- risk_factor_block_nested_cap_and_multiplier -----------------------------

# Born 1954-05-20 is 72 at the clock, so the 70-and-over age band applies; 130 kg
# crosses the 120 kg step.
COMPLEX_PATIENT = {
    "full_name": "Pat Complex",
    "date_of_birth": "1954-05-20T00:00:00Z",
    "asa_class": 3,
    "airway_class": 4,
    "weight_kg": 130,
    "medical_plan_active": True,
    "dental_plan_active": False,
}


def _signed_moderate_evaluation(comorbidity_count):
    env = setup_practice_with_roster(clock=CLOCK, patient_overrides=COMPLEX_PATIENT)
    case = draft_case(
        env,
        planned_anesthesia_level="MODERATE_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T15:00:00Z",
        procedure_category="ORTHOGNATHIC",
        total_charge_cents=400000,
    )
    evaluation = create_evaluation_for(
        env, case["id"], env["monitor"]["id"],
        asa_class_recorded=3, airway_class_recorded=4,
        comorbidity_count=comorbidity_count,
    )
    return env, case, sign_evaluation_as(evaluation["id"], env["monitor"]["id"])


def test_five_risk_inputs_combine_into_one_multiplied_subtotal(api):
    """PRD 3.5: "Airway points are eight times the amount by which
    `airway_class_recorded` exceeds 2, and never negative, so classes 1 and 2
    contribute nothing while class 3 contributes 8 and class 4 contributes 16."
    PRD 3.5: "Age points are 6 when the patient's `age_years` is 70 or more,
    otherwise 4 when `age_years` is under 3 — the very young and the very old both
    carry risk — and otherwise 0."
    PRD 3.5: "Weight points are 5 when the patient's `weight_kg` is 120 kilograms
    or more, otherwise 0."
    PRD 3.5: "Those five contributions are added into a factor subtotal, which is
    then multiplied by the level multiplier of the case's
    `planned_anesthesia_level`: one half for `LOCAL_ONLY`, eight tenths for
    `MINIMAL_SEDATION`, exactly one for `MODERATE_SEDATION`, and one and three
    tenths for `DEEP_SEDATION_GENERAL`."

    30 base + 16 airway + 6 age + 12 capped comorbidity + 5 weight is 69, and the
    MODERATE_SEDATION multiplier of exactly one leaves 69.0 — a PROHIBITIVE band.

    Design: Difficulty/combinatorial_formula/risk_factor_block_nested_cap_and_multiplier
    """
    env, case, signed = _signed_moderate_evaluation(6)

    assert signed["status"] == "SIGNED"
    assert signed["provisional_risk_score"] == pytest.approx(69.0, abs=0.01), (
        f"the five factors sum to 69 and MODERATE_SEDATION scales by one, got {signed['provisional_risk_score']}"
    )
    assert signed["risk_band"] == "PROHIBITIVE", (
        f"69.0 is at or above the 55 floor, got {signed['risk_band']}"
    )
    assert fetch_case(case["id"])["clearance_status"] == "EVALUATED"


def test_comorbidity_points_stop_at_the_twelve_point_cap(api):
    """PRD 3.5: "Comorbidity points are three times `comorbidity_count`, capped at
    12, so the fifth and later comorbidity add nothing."

    Six documented comorbidities score exactly what four score. Without the cap the
    same evaluation would read 75.0 rather than 69.0, so the cap is observable on
    its own.

    Design: Difficulty/combinatorial_formula/risk_factor_block_nested_cap_and_multiplier
    """
    _, _, six = _signed_moderate_evaluation(6)
    _, _, four = _signed_moderate_evaluation(4)

    assert four["provisional_risk_score"] == pytest.approx(69.0, abs=0.01)
    assert six["provisional_risk_score"] == pytest.approx(69.0, abs=0.01)
    assert six["provisional_risk_score"] == four["provisional_risk_score"], (
        "comorbidities beyond the fourth add nothing, so 6 and 4 must score alike"
    )
    assert six["provisional_risk_score"] != pytest.approx(75.0, abs=0.01), (
        "75.0 would mean three points per comorbidity uncapped"
    )


# --- benefit_round_per_line_then_sum -----------------------------------------

PER_LINE_PATIENT = {
    "full_name": "Pat Path",
    "date_of_birth": "1980-03-15T00:00:00Z",
    "asa_class": 2,
    "airway_class": 2,
    "weight_kg": 80,
    "medical_plan_active": True,
    "dental_plan_active": True,
    # Large enough that the annual maximum never binds, isolating the rounding.
    "dental_annual_remaining_cents": 150000,
}
PER_LINE_TOTAL = 111110
PER_LINE_SERVICE_LINES = [
    service_line("D7240", 12345, "DENTAL"),
    service_line("21031", 98765, "MEDICAL"),
]


def _medical_first_determination():
    env = setup_practice_with_roster(clock=CLOCK, patient_overrides=PER_LINE_PATIENT)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="PATHOLOGY",
        total_charge_cents=PER_LINE_TOTAL,
    )
    clear_case(env, case["id"])
    return env, case, open_determination(case["id"], PER_LINE_SERVICE_LINES)


def test_dental_residual_is_rounded_once_per_line_before_it_is_summed(api):
    """PRD 3.7: "In the split case, for each line in order, the residual is the
    line's `charge_cents` less the rounded medical allowance for that same line, the
    dental want is fifty percent of that residual rounded to whole cents, the amount
    actually paid is the smaller of that want and the remaining dental balance, the
    remaining balance is reduced by the amount paid, and the amount paid is added to
    `dental_allowed_cents`."
    PRD 2.5: "Wherever a percentage or coinsurance rate is applied to a cent
    amount, the product is rounded to whole cents using round-half-up."

    Residuals of 2469 and 19753 each round half-up on their own to 1235 and 9877,
    summing to 11112. Rounding the combined 22222 residual once would answer 11111,
    so the pinned order is worth exactly one cent here.

    Design: Difficulty/combinatorial_formula/benefit_round_per_line_then_sum
    """
    env, case, determination = _medical_first_determination()
    submitted = submit_determination(determination["id"])

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1
    assert submitted["medical_allowed_cents"] == 88888, (
        f"eighty percent of 12345 and of 98765 are both exact, got {submitted['medical_allowed_cents']}"
    )
    assert submitted["dental_allowed_cents"] == 11112, (
        f"1235 + 9877 after per-line half-up rounding, got {submitted['dental_allowed_cents']}"
    )
    assert submitted["dental_allowed_cents"] != 11111, (
        "11111 is the sum-then-round answer, which is the wrong order"
    )
    assert submitted["patient_responsibility_cents"] == 11110
    assert_money_identity(submitted, PER_LINE_TOTAL)


def test_creation_already_publishes_the_per_line_rounded_allocation(api):
    """PRD 3.7: "Opening a determination stamps `status` `DRAFT` and
    `submission_count` 0, sets `dental_annual_remaining_snapshot_cents` from the
    patient's current `dental_annual_remaining_cents`, and immediately computes
    `route`, `primary_payer`, and the full allocation, so the specialist can see the
    split before committing to it."
    PRD 3.7: "The resulting identity — medical allowance plus dental allowance plus
    patient responsibility equals the case's `total_charge_cents` — is conserved
    from creation onward in every status, which is precisely why the service lines
    are forced to sum to the case total in the first place: it holds even for a
    `DRAFT` determination that has never been submitted."

    Design: Difficulty/combinatorial_formula/benefit_round_per_line_then_sum
    """
    env, case, determination = _medical_first_determination()

    assert determination["status"] == "DRAFT"
    assert determination["submission_count"] == 0
    assert determination["route"] == "SPLIT"
    assert determination["primary_payer"] == "MEDICAL"
    assert determination["dental_annual_remaining_snapshot_cents"] == 150000
    assert determination["medical_allowed_cents"] == 88888
    assert determination["dental_allowed_cents"] == 11112, (
        f"the DRAFT allocation is already per-line rounded, got {determination['dental_allowed_cents']}"
    )
    assert determination["patient_responsibility_cents"] == 11110
    assert_money_identity(determination, PER_LINE_TOTAL)


# --- consignment_tier_keyed_on_subtotal_not_liability -------------------------

def _held_consignment_reservation():
    """Two fixtures at 30000 each: a 60000 subtotal that sits in the ten percent
    tier, while the 48000 liability it produces would sit in the fifteen."""
    env = setup_practice_with_roster(clock=CLOCK, consignment_credit_limit_cents=500000)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
        total_charge_cents=200000,
        with_monitor=False,
    )
    lot = create_lot(
        env["practice_id"],
        diameter_mm=4.3, length_mm=10.0, unit_cost_cents=30000,
        quantity_on_hand=5, expiry_date="2027-06-30T00:00:00Z",
        is_consignment=True,
    )
    reservation = reserve_from_lot(case["id"], lot["id"], quantity=2)
    return env, case, lot, reservation


def test_restocking_tier_is_selected_from_the_subtotal_not_from_the_liability(api):
    """PRD 3.6: "The restocking tier is then selected once from
    `line_subtotal_cents` — not from the liability, and not marginally across tiers:
    a subtotal at or below 50,000 cents attracts fifteen percent, a subtotal above
    that but at or below 150,000 cents attracts ten percent, and anything above
    150,000 cents attracts five percent."
    PRD 3.6: "`consignment_credit_cents` is twenty percent of `line_subtotal_cents`,
    rounded half-up to whole cents, when the lot's `is_consignment` is true, and 0
    when it is false."
    PRD 3.6: "While `HELD`, and still after it becomes `CONSUMED`, the liability is
    `line_subtotal_cents` less `consignment_credit_cents`."

    Design: Difficulty/combinatorial_formula/consignment_tier_keyed_on_subtotal_not_liability
    """
    env, case, lot, reservation = _held_consignment_reservation()

    assert_reservation(reservation)
    assert reservation["status"] == "HELD"
    assert reservation["line_subtotal_cents"] == 60000
    assert reservation["restocking_fee_cents"] == 6000, (
        f"a 60000 subtotal is in the ten percent tier, got {reservation['restocking_fee_cents']}"
    )
    assert reservation["restocking_fee_cents"] != 7200, (
        "7200 is fifteen percent, the tier the 48000 liability would have selected"
    )
    assert reservation["consignment_credit_cents"] == 12000
    assert reservation["consignment_liability_cents"] == 48000
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 48000


def test_release_charges_the_subtotal_keyed_fee_and_drops_the_exposure(api):
    """PRD 3.6: "On `RELEASED` the liability is exactly `restocking_fee_cents`, and
    `consignment_credit_cents` is reset to 0 — the practice pays only the restocking
    penalty for stock it sent back."
    PRD 3.6: "The practice's rolling `consignment_committed_cents` is the sum of
    `consignment_liability_cents` over the practice's reservations whose `status` is
    `HELD` or `CONSUMED`; released and shorted rows drop out."

    Design: Difficulty/combinatorial_formula/consignment_tier_keyed_on_subtotal_not_liability
    """
    env, case, lot, reservation = _held_consignment_reservation()

    released = dispose_reservation(reservation["id"], "RELEASED")

    assert released["status"] == "RELEASED"
    assert released["restocking_fee_cents"] == 6000
    assert released["consignment_credit_cents"] == 0
    assert released["consignment_liability_cents"] == 6000, (
        f"the released liability is exactly the tiered fee, got {released['consignment_liability_cents']}"
    )
    assert fetch_reservation(reservation["id"])["consignment_liability_cents"] == 6000
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 0, (
        "a released reservation drops out of the rolling exposure entirely"
    )
