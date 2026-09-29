"""Benefit determination: the medical-first and dental-first waterfalls over
identical service lines."""
from test_helpers import (
    assert_determination,
    assert_money_identity,
    clear_case,
    draft_case,
    fetch_determination,
    open_determination,
    service_line,
    setup_practice_with_roster,
    submit_determination,
)

CLOCK = "2026-09-11T10:00:00Z"
TOTAL_CHARGE_CENTS = 111110
# Both plans active, so the route is SPLIT and only procedure_category decides
# which payer goes first. The dental annual maximum is deliberately small.
SPLIT_PATIENT = {
    "medical_plan_active": True,
    "dental_plan_active": True,
    "dental_annual_remaining_cents": 20000,
}
# 12345 + 98765 == 111110, and both halves land on a .5 cent so the per-line
# round-half-up is observable.
SERVICE_LINES = [
    service_line("D7240", 12345, "DENTAL"),
    service_line("21031", 98765, "MEDICAL"),
]


def _verified_case(procedure_category):
    """A LOCAL_ONLY case of the given category whose evaluation is VERIFIED, which
    is the precondition submission checks."""
    env = setup_practice_with_roster(clock=CLOCK, patient_overrides=SPLIT_PATIENT)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        procedure_category=procedure_category,
        total_charge_cents=TOTAL_CHARGE_CENTS,
    )
    clear_case(env, case["id"])
    return env, case


def test_split_route_on_pathology_runs_medical_first(api):
    """PRD 3.7: "on `SPLIT` the `primary_payer` is `MEDICAL` when the case's
    `procedure_category` is `PATHOLOGY`, `TRAUMA`, `TMJ`, or `ORTHOGNATHIC`, and
    `DENTAL` otherwise"
    PRD 3.7: "When `primary_payer` is `MEDICAL`, medical pays first on each line's
    full `charge_cents`: `medical_allowed_cents` is the sum, across lines, of
    eighty percent of the line charge rounded to whole cents."
    PRD 3.7: "In the split case, for each line in order, the residual is the line's
    `charge_cents` less the rounded medical allowance for that same line, the
    dental want is fifty percent of that residual rounded to whole cents, the
    amount actually paid is the smaller of that want and the remaining dental
    balance, the remaining balance is reduced by the amount paid, and the amount
    paid is added to `dental_allowed_cents`."

    Medical first takes 9876 + 79012 = 88888. Dental then sees residuals of 2469
    and 19753, wants 1235 and 9877 after half-up rounding, and can afford both
    inside the 20000 maximum, for 11112. The patient owes the 11110 remainder.

    Design: Difficulty/dual_variant_calc/benefit_medical_first_versus_dental_first_waterfall
    """
    env, case = _verified_case("PATHOLOGY")
    determination = open_determination(case["id"], SERVICE_LINES)
    submitted = submit_determination(determination["id"])

    assert_determination(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["route"] == "SPLIT"
    assert submitted["primary_payer"] == "MEDICAL", (
        f"PATHOLOGY is a medical-first category on the split route, got {submitted['primary_payer']}"
    )
    assert submitted["dental_annual_remaining_snapshot_cents"] == 20000
    assert submitted["medical_allowed_cents"] == 88888, (
        f"eighty percent per line on the gross charges is 9876 + 79012, got {submitted['medical_allowed_cents']}"
    )
    assert submitted["dental_allowed_cents"] == 11112, (
        f"fifty percent of the post-medical residuals is 1235 + 9877, got {submitted['dental_allowed_cents']}"
    )
    assert submitted["patient_responsibility_cents"] == 11110
    assert_money_identity(submitted, TOTAL_CHARGE_CENTS)


def test_split_route_on_third_molar_runs_dental_first_and_exhausts_the_maximum(api):
    """PRD 3.7: "on `SPLIT` the `primary_payer` is `MEDICAL` when the case's
    `procedure_category` is `PATHOLOGY`, `TRAUMA`, `TMJ`, or `ORTHOGNATHIC`, and
    `DENTAL` otherwise — which in practice means `THIRD_MOLAR` and `IMPLANT` cases
    are dental-first."
    PRD 3.7: "Dental pays first on each line's full `charge_cents`: for each line
    in order, the want is fifty percent of the line charge rounded to whole cents,
    the amount paid is the smaller of that want and the remaining dental balance,
    the remaining balance is reduced by it, and it accumulates into
    `dental_allowed_cents` while also being remembered per line."
    PRD 3.7: "`medical_allowed_cents` is the sum, across lines, of eighty percent —
    rounded to whole cents per line — of the line's `charge_cents` less the dental
    amount actually paid for that same line."

    Dental first wants 6173 then 49383, but the 20000 maximum caps the second line
    at 13827, so dental spends exactly 20000. Medical then sees residuals of 6172
    and 84938 for 4938 + 67950 = 72888, and the patient owes 18222 — a different
    split of the very same lines.

    Design: Difficulty/dual_variant_calc/benefit_medical_first_versus_dental_first_waterfall
    """
    env, case = _verified_case("THIRD_MOLAR")
    determination = open_determination(case["id"], SERVICE_LINES)
    submitted = submit_determination(determination["id"])

    assert submitted["route"] == "SPLIT"
    assert submitted["primary_payer"] == "DENTAL", (
        f"THIRD_MOLAR is dental-first on the split route, got {submitted['primary_payer']}"
    )
    assert submitted["dental_annual_remaining_snapshot_cents"] == 20000
    assert submitted["dental_allowed_cents"] == 20000, (
        "dental applied to the gross charge consumes the whole annual maximum, got "
        f"{submitted['dental_allowed_cents']}"
    )
    assert submitted["medical_allowed_cents"] == 72888, (
        f"eighty percent of the post-dental residuals is 4938 + 67950, got {submitted['medical_allowed_cents']}"
    )
    assert submitted["patient_responsibility_cents"] == 18222
    assert_money_identity(submitted, TOTAL_CHARGE_CENTS)
    assert fetch_determination(submitted["id"])["medical_allowed_cents"] == 72888
