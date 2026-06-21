"""Billing calculations: patient responsibility (cash / wellness / insurance),
no-show fees, adjudication deductible application, and the ledger.

Every test cites the PRD §3.8 / §3.9 rule it pins and ends with the design-index
instance that drove it.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    create_appointment_payload,
    setup_base_practice,
    create_cash_patient,
    create_insurance_patient,
    create_wellness_patient,
    create_wellness_plan,
    add_policy,
    create_attended_appointment,
    setup_attended_cash_visit,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / patient_responsibility_insurance_vs_cash_diverge
# ===========================================================================
def test_cash_patient_responsibility_is_full_cash_rate(api):
    """PRD §3.8: "For a **cash** patient, the patient responsibility is simply
    the fee schedule's `cash_rate_cents` and `insurance_paid_cents` is 0."

    Design: Difficulty/dual_variant_calc/patient_responsibility_insurance_vs_cash_diverge
    """
    ctx = setup_attended_cash_visit(cash_rate_cents=6000)
    appt = ctx["appointment"]
    assert appt["patient_responsibility_cents"] == 6000
    assert appt["insurance_paid_cents"] == 0


def test_insurance_patient_responsibility_diverges_from_cash(api):
    """PRD §3.8: "The patient responsibility is the sum of the amount applied to
    the deductible and the coinsurance, and `insurance_paid_cents` is the allowed
    amount minus the patient responsibility."

    With deductible already met (deductible_total=allowed pre-paid) only the
    coinsurance is owed: round(8000*0.20)=1600, insurance pays 8000-1600=6400 —
    not the 6000 a cash patient would owe.

    Design: Difficulty/dual_variant_calc/patient_responsibility_insurance_vs_cash_diverge
    """
    # Deductible fully met up front: total=allowed=8000, met via a prior adjudicated visit.
    base = setup_base_practice()
    patient = create_insurance_patient("Ins Ida")
    policy = add_policy(
        patient["id"],
        annual_visit_cap=20,
        deductible_total_cents=8000,
        coinsurance_pct=0.20,
        allowed_amount_cents=8000,
    )
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    room_id = base["room"]["id"]

    # Prior visit pays the whole deductible (applied=min(8000,8000)=8000) and is adjudicated.
    prior = create_attended_appointment(
        pid, prov_id, room_id, scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"]
    )
    validate_success(api.adjudicate_appointment(pid, prior["id"], BILLING), 200)

    # Trigger visit: deductible now met, so only coinsurance applies.
    appt = create_attended_appointment(
        pid, prov_id, room_id, scheduled_start="2026-03-04T17:00:00Z", insurance_policy_id=policy["id"]
    )
    assert appt["patient_responsibility_cents"] == 1600
    assert appt["insurance_paid_cents"] == 6400


# ===========================================================================
# Difficulty: combinatorial_formula / insurance_responsibility_mode_a_min_max_nesting
# ===========================================================================
def test_insurance_partial_deductible_min_max_nesting(api):
    """PRD §3.8: "The amount applied to the deductible is the smaller of the
    allowed amount and that remaining deductible, and the patient pays this
    portion dollar-for-dollar."
    PRD §3.8: "the coinsurance is that after-deductible amount multiplied by the
    policy's `coinsurance_pct`, rounded half up to whole cents."

    deductible_total=14000, met=8000 -> remaining=6000; allowed=8000 ->
    applied=min(8000,6000)=6000; after=2000; coins=round(2000*0.20)=400;
    pr=6000+400=6400; insurance_paid=8000-6400=1600.

    Design: Difficulty/combinatorial_formula/insurance_responsibility_mode_a_min_max_nesting
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Ins Ida")
    policy = add_policy(
        patient["id"],
        annual_visit_cap=20,
        deductible_total_cents=14000,
        coinsurance_pct=0.20,
        allowed_amount_cents=8000,
    )
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    room_id = base["room"]["id"]

    # First visit drives deductible_met to 8000 (applied=min(8000,14000)=8000) via adjudication.
    prior = create_attended_appointment(
        pid, prov_id, room_id, scheduled_start="2026-03-02T17:00:00Z", insurance_policy_id=policy["id"]
    )
    validate_success(api.adjudicate_appointment(pid, prior["id"], BILLING), 200)
    policy_after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert policy_after["deductible_met_cents"] == 8000

    # Second visit: partial deductible remaining (6000) plus coinsurance.
    appt = create_attended_appointment(
        pid, prov_id, room_id, scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"]
    )
    assert appt["patient_responsibility_cents"] == 6400
    assert appt["insurance_paid_cents"] == 1600


def test_adjudication_increases_deductible_met_by_applied_amount(api):
    """PRD §3.8: "the policy's `deductible_met_cents` is increased by the amount
    that was applied to the deductible for this visit."

    With deductible_total=14000 and a fresh policy, the first visit applies
    min(8000,14000)=8000 to the deductible; adjudication then raises
    deductible_met_cents to 8000.

    Design: Difficulty/combinatorial_formula/insurance_responsibility_mode_a_min_max_nesting
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Ded Dora")
    policy = add_policy(
        patient["id"],
        annual_visit_cap=20,
        deductible_total_cents=14000,
        coinsurance_pct=0.20,
        allowed_amount_cents=8000,
    )
    pid = patient["id"]
    prior = create_attended_appointment(
        pid, base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-02T17:00:00Z", insurance_policy_id=policy["id"],
    )
    before = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert before["deductible_met_cents"] == 0
    validate_success(api.adjudicate_appointment(pid, prior["id"], BILLING), 200)
    after = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert after["deductible_met_cents"] == 8000


# ===========================================================================
# Difficulty: combinatorial_formula / wellness_overage_mode_c_ordinal_then_branch
# ===========================================================================
def _attend_wellness_adjustment(api, pid, prov_id, room_id, start):
    return create_attended_appointment(
        pid, prov_id, room_id, scheduled_start=start
    )


def test_wellness_included_adjustment_is_free(api):
    """PRD §3.8: "If the ordinal is less than or equal to the wellness plan's
    `included_adjustments_per_month`, the visit is fully included and the patient
    responsibility is 0."

    With included=4, the 4th ADJUSTMENT of the calendar month is still included.

    Design: Difficulty/combinatorial_formula/wellness_overage_mode_c_ordinal_then_branch
    """
    base = setup_base_practice(cash_rate_cents=6000)
    wp = create_wellness_plan(included_adjustments_per_month=4, overage_discount_pct=0.30)
    api.set_clock("2026-04-01T08:00:00Z", base_admin := TEST_USERS["admin_headers"])
    patient = create_wellness_patient(wp["id"], "Well Wendy")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]

    starts = [
        "2026-04-06T15:00:00Z",
        "2026-04-07T15:00:00Z",
        "2026-04-08T15:00:00Z",
        "2026-04-09T15:00:00Z",
    ]
    last = None
    for s in starts:
        last = _attend_wellness_adjustment(api, pid, prov_id, room_id, s)
    assert last["patient_responsibility_cents"] == 0  # ordinal 4 <= included 4
    assert last["insurance_paid_cents"] == 0


def test_wellness_overage_adjustment_gets_discount(api):
    """PRD §3.8: "the discount is the `cash_rate_cents` multiplied by the plan's
    `overage_discount_pct`, rounded half up to whole cents, and the patient
    responsibility is the `cash_rate_cents` minus that discount."

    5th adjustment of the month with included=4, cash=6000, disc=0.30 ->
    discount=round(6000*0.30)=1800, pr=6000-1800=4200.

    Design: Difficulty/combinatorial_formula/wellness_overage_mode_c_ordinal_then_branch
    """
    base = setup_base_practice(cash_rate_cents=6000)
    wp = create_wellness_plan(included_adjustments_per_month=4, overage_discount_pct=0.30)
    api.set_clock("2026-04-01T08:00:00Z", TEST_USERS["admin_headers"])
    patient = create_wellness_patient(wp["id"], "Well Wendy")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]

    starts = [
        "2026-04-06T15:00:00Z",
        "2026-04-07T15:00:00Z",
        "2026-04-08T15:00:00Z",
        "2026-04-09T15:00:00Z",
        "2026-04-10T15:00:00Z",
    ]
    last = None
    for s in starts:
        last = _attend_wellness_adjustment(api, pid, prov_id, room_id, s)
    assert last["patient_responsibility_cents"] == 4200  # ordinal 5 -> overage
    assert last["insurance_paid_cents"] == 0


# ===========================================================================
# Difficulty: dual_variant_calc / no_show_fee_no_show_vs_late_cancel_diverge
# ===========================================================================
def test_no_show_fee_is_full_first_tier(api):
    """PRD §3.8: "With a strike count of 1 or 2 the base fee is 2500 cents ... A
    `NO_SHOW` is charged the full base fee."

    Design: Difficulty/dual_variant_calc/no_show_fee_no_show_vs_late_cancel_diverge
    """
    base = setup_base_practice()
    patient = create_cash_patient("NS Ann")
    pid = patient["id"]
    appt = validate_success(
        api.book_appointment(
            pid,
            create_appointment_payload(
                base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"
            ),
            FRONTDESK,
        ),
        201,
    )
    api.set_clock("2026-03-03T17:30:00Z", TEST_USERS["admin_headers"])
    res = validate_success(api.no_show_appointment(pid, appt["id"], FRONTDESK), 200)
    assert res["attendance_status"] == "NO_SHOW"
    assert res["no_show_fee_cents"] == 2500


def test_late_cancel_fee_is_half_of_first_tier(api):
    """PRD §3.8: "A `LATE_CANCEL` is charged the base fee multiplied by the
    late-cancel multiplier of 0.5, rounded half up to whole cents."

    First-tier base 2500 * 0.5 = 1250.

    Design: Difficulty/dual_variant_calc/no_show_fee_no_show_vs_late_cancel_diverge
    """
    base = setup_base_practice()
    patient = create_cash_patient("LC Bob")
    pid = patient["id"]
    appt = validate_success(
        api.book_appointment(
            pid,
            create_appointment_payload(
                base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-02T20:00:00Z"
            ),
            FRONTDESK,
        ),
        201,
    )
    # Inside the 24h window (between 19:00 wkday window-open and 20:00 start).
    api.set_clock("2026-03-02T12:00:00Z", TEST_USERS["admin_headers"])
    res = validate_success(api.cancel_appointment(pid, appt["id"], FRONTDESK), 200)
    assert res["attendance_status"] == "LATE_CANCEL"
    assert res["no_show_fee_cents"] == 1250


# ===========================================================================
# Difficulty: compensating_invariant / ledger_balance_conserved_charge_then_writeoff
# ===========================================================================
def test_writeoff_reverses_charge_to_zero_balance(api):
    """PRD §3.8: "appends a `WRITE_OFF` ledger entry whose `amount_cents` is the
    negative of `patient_responsibility_cents`, and subtracts that amount from
    the patient's `ledger_balance_cents`, reversing the original charge so the
    patient's net balance returns to where it stood before that visit's charge
    was posted."

    Design: Difficulty/compensating_invariant/ledger_balance_conserved_charge_then_writeoff
    """
    ctx = setup_attended_cash_visit(cash_rate_cents=6000)
    pid = ctx["patient"]["id"]
    appt = ctx["appointment"]
    after_charge = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert after_charge["ledger_balance_cents"] == 6000

    res = validate_success(api.write_off_appointment(pid, appt["id"], BILLING), 200)
    assert res["billing_status"] == "WRITTEN_OFF"
    final = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert final["ledger_balance_cents"] == 0


def test_writeoff_appends_negative_ledger_entry(api):
    """PRD §3.8: "appends a `WRITE_OFF` ledger entry whose `amount_cents` is the
    negative of `patient_responsibility_cents`".

    Design: Difficulty/compensating_invariant/ledger_balance_conserved_charge_then_writeoff
    """
    ctx = setup_attended_cash_visit(cash_rate_cents=6000)
    pid = ctx["patient"]["id"]
    appt = ctx["appointment"]
    validate_success(api.write_off_appointment(pid, appt["id"], BILLING), 200)

    data, _meta = validate_paginated(
        api.list_patient_ledger_entries(pid, BILLING, params={"entry_type": "WRITE_OFF"})
    )
    assert any(e["entry_type"] == "WRITE_OFF" and e["amount_cents"] == -6000 for e in data)


# ===========================================================================
# Corner: endpoints / payment_decrements_ledger_balance
# ===========================================================================
def test_payment_decrements_ledger_balance(api):
    """PRD §3.9: "The payment appends a `PATIENT_PAYMENT` ledger entry carrying
    the negative of `amount_cents` and decrements the patient's
    `ledger_balance_cents` by `amount_cents`."

    Design: Corner/endpoints/payment_decrements_ledger_balance
    """
    patient = create_cash_patient("Pay Pam")
    pid = patient["id"]
    entry = validate_success(api.post_payment(pid, {"amount_cents": 4000}, FRONTDESK), 201)
    assert entry["amount_cents"] == -4000
    refreshed = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert refreshed["ledger_balance_cents"] == -4000
