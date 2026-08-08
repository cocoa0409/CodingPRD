"""The installment schedule, the delinquency sweep and the cure path."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_schedule_entry,
    make_patient_headers,
    pay_installment,
    read_financing_plan,
    read_patient,
    run_delinquency,
    set_clock,
    setup_active_financing_plan,
    setup_pellet_procedure,
    validate_error,
    validate_paginated,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_delinquency_run_misses_the_overdue_installment_and_marks_the_plan(api):
    """PRD §3.9: "For each entry still `PENDING`, if more than 10 days have elapsed between
    its `due_date` and now, the entry flips to `MISSED` and 2500 cents are added to the plan's
    `late_fee_cents`. The boundary is strict: an installment exactly 10 days late is still
    `PENDING`, and it flips at eleven."
    PRD §3.9: "A plan whose `missed_count` has reached 3 or more moves
    `DELINQUENT → DEFAULTED`; a plan whose `missed_count` is at least 1 but no more than 2
    moves `ACTIVE → DELINQUENT`; a plan with no missed entries keeps its status."
    PRD §3.9: "Worked through: a principal of 58300 cents with a down payment of 11660 over
    six installments finances 46640, gives a base of 7773 and a residual of 2, so installments
    one through five are 7773 each and installment six is 7775 — and 11660 plus five times
    7773 plus 7775 is exactly 58300, as the first conservation leg requires."

    Design: Difficulty/non_linear_state_machine/financing_plan_delinquent_cures_back_to_active
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-06-01T00:00:00Z", scheduled_start="2026-07-01T09:00:00Z",
        patient_email="p9@example.com",
    )
    amounts = [entry["amount_cents"] for entry in sorted(
        ctx["plan"]["schedule"], key=lambda e: e["index"]
    )]
    assert amounts == [7773, 7773, 7773, 7773, 7773, 7775]

    set_clock(api, "2026-06-12T00:00:00Z")
    run_delinquency(api)

    plan = read_financing_plan(api, ctx["plan_id"])
    assert plan["status"] == "DELINQUENT"
    assert plan["missed_count"] == 1
    assert plan["late_fee_cents"] == 2500
    assert_schedule_entry(plan, 1, amount_cents=7773, status="MISSED")


def test_paying_the_last_missed_installment_cures_the_plan_back_to_active(api):
    """PRD §3.9: "A plan in `DELINQUENT` returns `DELINQUENT → ACTIVE` the moment no schedule
    entry remains in `MISSED` — that is the cure path, and it is cyclic, so a plan may fall
    delinquent and cure repeatedly."
    PRD §3.9: "On success the entry moves to `PAID`, `paid_installment_cents` is recomputed as
    the sum of amounts over `PAID` entries, and `outstanding_cents` as the sum over entries
    still in `PENDING` or `MISSED`, keeping the second conservation leg balanced."
    PRD §3.9: "A late fee accrues once per entry, at the moment it flips, so re-running the
    sweep without advancing the clock adds nothing further."

    Design: Difficulty/non_linear_state_machine/financing_plan_delinquent_cures_back_to_active
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-06-01T00:00:00Z", scheduled_start="2026-07-01T09:00:00Z",
        patient_email="p9@example.com",
    )
    set_clock(api, "2026-06-12T00:00:00Z")
    run_delinquency(api)
    assert read_financing_plan(api, ctx["plan_id"])["status"] == "DELINQUENT"

    pay_installment(api, ctx["plan_id"], 1, 7773)

    plan = read_financing_plan(api, ctx["plan_id"])
    assert plan["status"] == "ACTIVE", "Curing the last MISSED entry returns the plan to ACTIVE"
    assert plan["missed_count"] == 0
    assert plan["late_fee_cents"] == 2500, "The accrued fee does not unwind on the cure"
    assert plan["paid_installment_cents"] == 7773
    assert plan["outstanding_cents"] == 38867
    assert_schedule_entry(plan, 1, amount_cents=7773, status="PAID")


def test_installment_exactly_ten_days_late_stays_pending_and_flips_at_eleven(api):
    """PRD §3.9: "For each entry still `PENDING`, if more than 10 days have elapsed between
    its `due_date` and now, the entry flips to `MISSED` and 2500 cents are added to the plan's
    `late_fee_cents`. The boundary is strict: an installment exactly 10 days late is still
    `PENDING`, and it flips at eleven."
    PRD §3.9: "Default fires its own cascade. The patient's `financial_hold` is set true,
    `eligibility_status` is recomputed, and the patient's `version` increments; then every
    procedure of that patient whose `status` is `SCHEDULED` is frozen into `SUPPLY_HOLD` with
    `hold_reason` `PATIENT_FINANCIAL_HOLD`, releasing its `RESERVED` allocations back to
    `qty_on_hand` — which, like the adverse-event cascade, changes allocation outcomes for
    entirely unrelated patients."

    Design: Corner/calculations/delinquency_grace_boundary_exactly_ten_days_stays_pending
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-06-01T00:00:00Z", scheduled_start="2026-08-15T09:00:00Z",
        patient_email="c22@example.com",
    )

    set_clock(api, "2026-06-11T00:00:00Z")
    run_delinquency(api)

    on_the_boundary = read_financing_plan(api, ctx["plan_id"])
    assert on_the_boundary["status"] == "ACTIVE"
    assert on_the_boundary["missed_count"] == 0
    assert on_the_boundary["late_fee_cents"] == 0
    assert_schedule_entry(on_the_boundary, 1, status="PENDING")

    set_clock(api, "2026-06-12T00:00:00Z")
    run_delinquency(api)

    one_day_later = read_financing_plan(api, ctx["plan_id"])
    assert one_day_later["status"] == "DELINQUENT"
    assert one_day_later["missed_count"] == 1
    assert one_day_later["late_fee_cents"] == 2500
    assert one_day_later["outstanding_cents"] == 46640
    assert read_patient(api, ctx["patient_id"])["financial_hold"] is False, (
        "One missed installment is short of the default threshold"
    )


def test_partial_installment_payment_is_refused_and_changes_nothing(api):
    """PRD §3.9: "Payments are made by `FrontDesk` or by the `Patient` and address one
    installment at a time by `installment_index`, supplying an `amount_cents` that must
    **exactly** equal that entry's `amount_cents`; the entry must be in `PENDING` or `MISSED`,
    and any partial payment, over-payment or payment against an already-settled entry is
    refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/installment_payment_amount_must_match_exactly
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-08-01T00:00:00Z", scheduled_start="2026-07-06T09:00:00Z",
        patient_email="c32@example.com",
    )

    response = api.pay_installment(
        ctx["plan_id"], {"installment_index": 1, "amount_cents": 7000},
        make_patient_headers(ctx["patient_id"]),
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    assert response.status_code == 422

    plan = read_financing_plan(api, ctx["plan_id"])
    assert plan["status"] == "ACTIVE"
    assert plan["paid_installment_cents"] == 0
    assert plan["outstanding_cents"] == 46640
    assert_schedule_entry(plan, 1, amount_cents=7773, status="PENDING")


def test_down_payment_gate_is_reported_before_the_installment_count_gate(api):
    """PRD §3.9: "Two fiscal gates apply, in this order: the down payment must be at least
    twenty percent of the principal — computed as the principal multiplied by 0.20 and rounded
    **up** to the next whole cent — and must be strictly less than the principal, failing
    which the answer is `ERR_DOWN_PAYMENT_TOO_LOW`; and `installment_count` must be an integer
    between 2 and 12 inclusive, failing which the answer is `ERR_INSTALLMENT_COUNT_INVALID`."

    Design: Corner/validations/financing_down_payment_and_installment_count_rungs_fire_in_order
    """
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", prescribed_dose_mg=1000,
        patient_name="Corner ThirtyOne", patient_email="c31@example.com",
        room_code="RM54", scheduled_start="2026-07-05T09:00:00Z",
    )

    both_wrong = api.create_financing_plan(
        {
            "patient_id": ctx["patient_id"],
            "procedure_id": ctx["procedure_id"],
            "principal_cents": 58300,
            "down_payment_cents": 5000,
            "installment_count": 24,
            "first_due_date": "2026-08-01T00:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(both_wrong, ApiErrorId.ERR_DOWN_PAYMENT_TOO_LOW.value)
    assert both_wrong.status_code == 422

    count_only = api.create_financing_plan(
        {
            "patient_id": ctx["patient_id"],
            "procedure_id": ctx["procedure_id"],
            "principal_cents": 58300,
            "down_payment_cents": 11660,
            "installment_count": 24,
            "first_due_date": "2026-08-01T00:00:00Z",
        },
        FRONT_DESK,
    )
    validate_error(count_only, ApiErrorId.ERR_INSTALLMENT_COUNT_INVALID.value)
    assert count_only.status_code == 422

    rows, meta = validate_paginated(
        api.list_financing_plans(FRONT_DESK, {"procedure_id": ctx["procedure_id"]})
    )
    assert meta["total_count"] == 0, "Neither rejected plan may be persisted"
