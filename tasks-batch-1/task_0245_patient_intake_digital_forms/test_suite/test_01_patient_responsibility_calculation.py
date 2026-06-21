"""Patient-responsibility and copay calculations (PRD §3.2, §3.6).

Covers the dual-variant estimate-vs-finalized divergence, the multi-leg
nested min/max formula, the per-line rounding policy, the deductible==0
boundary, and the provisional deductible-unmet variant on the EligibilityCheck.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]


def test_estimate_vs_finalized_responsibility_diverge(api):
    """PRD §3.2: "the estimate deliberately ignores deductible and coinsurance and simply uses the posted office-visit copay, `plan_default_copay_cents`, as the provisional figure."
    PRD §3.6: "When the outcome is `ELIGIBLE`, the responsibility is the sum of five legs, of which three are integer and two are fractional"

    Design: Difficulty/dual_variant_calc/copay_estimate_vs_finalized_diverge
    """
    clinic = fixtures.create_clinic(name="C1", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="2026-06-10T10:00:00.000Z", end_utc="2026-06-10T10:30:00.000Z",
        plan_default_copay_cents=2500,
    )
    assert appt["provisional_copay_cents"] == 2500, "forward-looking estimate uses posted copay"

    session = fixtures.open_session(appt["id"])
    card, _ = fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    assert data["final_patient_responsibility_cents"] == 9100, "finalized four-leg split"
    assert data["final_patient_responsibility_cents"] != appt["provisional_copay_cents"]


def test_finalized_responsibility_nested_minmax(api):
    """PRD §3.6: "The three integer legs are: the **copay leg**, which is the
    smaller of `plan_copay_cents` and `visit_allowed_amount_cents`; the
    **deductible leg**, which is the smaller of `remaining_deductible_cents` and
    `visit_allowed_amount_cents`; and the flat `facility_fee_cents`."

    Design: Difficulty/combinatorial_formula/copay_nested_minmax_mode_a
    """
    clinic = fixtures.create_clinic(name="C3", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # copay 3000 + deductible 5000 + facility 500 + medical coins (3000*20/100=600) = 9100
    assert data["final_patient_responsibility_cents"] == 9100
    assert data["financial_status"] == "COPAY_DUE"


def test_finalized_responsibility_per_line_rounding(api):
    """PRD §3.6: "Under `PER_LINE_THEN_SUM` (the default), each fractional leg is rounded half up to a whole cent on its own, and then the total is the copay leg plus the deductible leg plus the facility fee plus the rounded medical coinsurance leg plus the rounded facility coinsurance leg."

    Design: Difficulty/combinatorial_formula/copay_rounding_order_mode_b
    """
    clinic = fixtures.create_clinic(name="C4", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=1010)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=500, plan_coinsurance_pct=5, facility_coinsurance_pct=5,
        remaining_deductible_cents=0, visit_allowed_amount_cents=2010,
    )

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # copay 500 + deductible 0 + facility 1010 + round(100.5)=101 + round(50.5)=51 = 1662
    assert data["final_patient_responsibility_cents"] == 1662


def test_deductible_zero_boundary_full_coinsurance(api):
    """PRD §3.6: "first find the above-deductible portion of the allowed amount:
    subtract `remaining_deductible_cents` from `visit_allowed_amount_cents`, and if
    that difference is negative use 0 instead (take the larger of that difference
    and 0)."

    Design: Difficulty/boundary_precision_check/deductible_zero_boundary_on_eligibility
    """
    clinic = fixtures.create_clinic(name="C11", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=4000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=10000,
    )

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # deductible 0: copay 4000 + deductible 0 + facility 0 + coins(10000*20/100=2000) = 6000
    assert data["final_patient_responsibility_cents"] == 6000


def test_provisional_responsibility_drops_coinsurance(api):
    """PRD §3.6: "The provisional figure assumes the full deductible is still unmet, so coinsurance is never reached: it is the copay leg plus the deductible leg plus the facility fee — that is, the smaller of `plan_copay_cents` and the allowed amount, plus the smaller of `remaining_deductible_cents` and the allowed amount, plus `facility_fee_cents` — with both coinsurance legs treated as zero."
    PRD §3.6: "the finalized figure exceeds the provisional one because the
    finalized figure adds the coinsurance legs."

    Design: Corner/calculations/provisional_responsibility_recorded_on_check
    """
    clinic = fixtures.create_clinic(name="CE10", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    card, _ = fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )

    checks, _meta = _list_checks(api, card["id"])
    assert len(checks) == 1, "exactly one eligibility check recorded"
    # provisional = min(3000,8000) + min(5000,8000) + facility 0, coinsurance zero = 8000
    assert checks[0]["provisional_responsibility_cents"] == 8000

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # final = copay 3000 + deductible 5000 + facility 0 + medical coins 600 = 8600 (> provisional)
    assert data["final_patient_responsibility_cents"] == 8600
    assert data["final_patient_responsibility_cents"] > checks[0]["provisional_responsibility_cents"]


def test_estimate_diverges_from_finalized_on_session_read(api):
    """PRD §3.2: "for the same visit the two can diverge, because the estimate
    uses only the posted copay while the finalized figure applies the full
    multi-leg split."

    Design: Difficulty/dual_variant_calc/copay_estimate_vs_finalized_diverge
    """
    clinic = fixtures.create_clinic(name="C1b", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"], plan_default_copay_cents=2500
    )
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )
    appt_after = validate_success(api.get_appointment(appt["id"], FRONT))
    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert appt_after["provisional_copay_cents"] == 2500
    assert session_after["final_patient_responsibility_cents"] == 9100
    assert appt_after["provisional_copay_cents"] != session_after["final_patient_responsibility_cents"]


def test_finalized_responsibility_nested_minmax_second_view(api):
    """PRD §3.6: "the **copay leg**, which is the smaller of `plan_copay_cents`
    and `visit_allowed_amount_cents`; the **deductible leg**, which is the smaller
    of `remaining_deductible_cents` and `visit_allowed_amount_cents`; and the flat
    `facility_fee_cents`."

    Design: Difficulty/combinatorial_formula/copay_nested_minmax_mode_a
    """
    # copay leg clamped by allowed: plan_copay 9999 but allowed 8000 -> copay leg 8000.
    clinic = fixtures.create_clinic(name="C3b", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=9999, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=8000,
    )
    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # copay min(9999,8000)=8000 + deductible min(0,8000)=0 + facility 0 + coins 0 = 8000
    assert data["final_patient_responsibility_cents"] == 8000


def test_sum_then_round_policy_differs_by_one_cent(api):
    """PRD §3.6: "Under `SUM_THEN_ROUND`, the copay leg, the deductible leg, the facility fee, and both unrounded fractional legs are added together first, and the single resulting sum is rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/copay_rounding_order_mode_b
    """
    clinic = fixtures.create_clinic(name="C4b", copay_rounding="SUM_THEN_ROUND", facility_fee_cents=1010)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=500, plan_coinsurance_pct=5, facility_coinsurance_pct=5,
        remaining_deductible_cents=0, visit_allowed_amount_cents=2010,
    )
    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # 500 + 0 + 1010 + 100.5 + 50.5 = 1661.0 -> round_half_up -> 1661
    assert data["final_patient_responsibility_cents"] == 1661


def test_deductible_one_cent_above_zero_boundary(api):
    """PRD §3.6: "first find the above-deductible portion of the allowed amount:
    subtract `remaining_deductible_cents` from `visit_allowed_amount_cents`, and if
    that difference is negative use 0 instead (take the larger of that difference
    and 0)."
    PRD §3.6: "The **medical coinsurance leg** is that above-deductible portion
    multiplied by `plan_coinsurance_pct` and divided by 100."

    Design: Difficulty/boundary_precision_check/deductible_zero_boundary_on_eligibility
    """
    # deductible 5 (X+5 relative to the zero edge): the deductible leg adds 5 and
    # the above-deductible portion shrinks by 5, but the 20% coinsurance on that
    # 5 is only 1 cent, so total = 4000 + 5 + 0 + round(9995*20/100=1999.0) = 6004.
    clinic = fixtures.create_clinic(name="C11b", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=4000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5, visit_allowed_amount_cents=10000,
    )
    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # copay 4000 + deductible 5 + facility 0 + coins(9995*20/100=1999.0 -> 1999) = 6004
    assert data["final_patient_responsibility_cents"] == 6004


def _list_checks(api, card_id):
    from test_helpers import validate_paginated
    resp = api.list_eligibility_checks(FRONT, params={"insurance_card_id": card_id})
    return validate_paginated(resp)
