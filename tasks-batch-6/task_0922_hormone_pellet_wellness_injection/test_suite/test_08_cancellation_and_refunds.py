"""The lead-time fee ladder, the two refund numbers, and the money they settle."""

from test_helpers import (
    TEST_USERS,
    assert_financing_money_conservation,
    assert_schedule_entry,
    make_patient_headers,
    new_financing_plan,
    activate_financing_plan,
    pay_installment,
    read_financing_plan,
    read_procedure,
    set_clock,
    setup_active_financing_plan,
    setup_pellet_procedure,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def _supply_opened_estradiol_with_paid_installment(api):
    """An 85 mg estradiol tray already opened, financed, with installment one paid."""
    ctx = setup_pellet_procedure(
        api, target_status="SUPPLY_OPENED", hormone_type="ESTRADIOL",
        prescribed_dose_mg=80, consented_max_dose_mg=150,
        patient_name="Pat Two", patient_email="p2@example.com", sex_at_birth="FEMALE",
        room_code="RM2", scheduled_start="2026-05-20T10:00:00Z",
        lot_specs=[
            {"lot_code": "E25-A", "strength_mg": 25, "qty_received": 10},
            {"lot_code": "E10-A", "strength_mg": 10, "qty_received": 10},
        ],
    )
    plan = new_financing_plan(
        api, ctx["patient_id"], ctx["procedure_id"],
        principal_cents=47482, down_payment_cents=25000, installment_count=4,
        first_due_date="2026-06-20T00:00:00Z",
    )
    activate_financing_plan(api, plan["id"])
    pay_installment(api, plan["id"], 1, 5620)
    set_clock(api, "2026-05-20T00:00:00Z")
    ctx["plan_id"] = plan["id"]
    return ctx


def test_refund_quote_reports_the_provisional_variant_before_the_cancel(api):
    """PRD §3.6: "Both start from the same base: the amount paid to date, which is zero when
    the procedure has no financing plan and otherwise is the plan's `down_payment_cents` plus
    its `paid_installment_cents`; and the cancellation fee computed by the lead-time ladder
    against the logical clock at the moment of the call. The **provisional quote** is the
    paid-to-date amount minus the cancellation fee, clamped at zero from below."
    PRD §3.6: "The provisional number is available as a read-only quote to `FrontDesk`,
    `Physician` and the `Patient`, reporting `procedure_id`, a `variant` of
    `PROVISIONAL_QUOTE`, `paid_to_date_cents`, the `cancel_tier` and `cancel_fee_cents` the
    ladder would produce right now, `wasted_pellet_charge_cents`, and the resulting
    `refund_cents`. It writes nothing."
    PRD §3.6: "When it is greater than zero but less than 24 hours, the tier is `TIER2` and
    the base fee is 12500 cents."

    Design: Difficulty/dual_variant_calc/refund_quote_vs_final_settlement_on_procedure
    """
    ctx = _supply_opened_estradiol_with_paid_installment(api)

    quote = validate_success(api.get_refund_quote(ctx["procedure_id"], FRONT_DESK), 200)

    assert quote["procedure_id"] == ctx["procedure_id"]
    assert quote["variant"] == "PROVISIONAL_QUOTE"
    assert quote["paid_to_date_cents"] == 30620
    assert quote["cancel_tier"] == "TIER2"
    assert quote["cancel_fee_cents"] == 12500
    assert quote["wasted_pellet_charge_cents"] == 0, (
        "A procedure sitting in SUPPLY_OPENED has no wasted allocations yet"
    )
    assert quote["refund_cents"] == 18120

    assert read_procedure(api, ctx["procedure_id"])["status"] == "SUPPLY_OPENED", (
        "The quote writes nothing"
    )


def test_final_settlement_subtracts_the_wasted_pellet_charge_the_quote_could_not_see(api):
    """PRD §3.6: "The **final settlement** subtracts one further term: the wasted-pellet
    charge, computed as the sum over this procedure's allocation rows whose status is exactly
    `WASTED` of that row's `quantity` multiplied by its `strength_mg` multiplied by the
    hormone's price per milligram (21.5 cents for testosterone, 176.25 cents for estradiol),
    rounded half up **per allocation row** and then summed. The final settlement is
    paid-to-date minus cancellation fee minus wasted-pellet charge, again clamped at zero from
    below."
    PRD §3.6: "From `SUPPLY_OPENED`, every allocation in `OPENED` moves to `WASTED` and its
    quantity moves from `qty_reserved` to `qty_wasted` — an opened sterile tray cannot go back
    on the shelf, so `qty_on_hand` does not rise — and the procedure's `pellets_wasted` is set
    to its `pellets_opened`."
    PRD §3.6: "If the procedure carries a financing plan in `DRAFT`, `ACTIVE` or `DELINQUENT`,
    that plan moves to `CANCELLED`, every schedule entry still in `PENDING` or `MISSED` flips
    to `WAIVED` with `waived_cents` recomputed so that the second conservation leg still
    balances, and `refunded_cents` is written from the **final settlement** figure."

    Design: Difficulty/dual_variant_calc/refund_quote_vs_final_settlement_on_procedure
    """
    ctx = _supply_opened_estradiol_with_paid_installment(api)
    quote = validate_success(api.get_refund_quote(ctx["procedure_id"], FRONT_DESK), 200)

    cancelled = validate_success(
        api.cancel_procedure(
            ctx["procedure_id"], {"reason": "Patient declined at the door"}, FRONT_DESK
        ),
        200,
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["pellets_wasted"] == 4
    assert cancelled["cancel_tier"] == "TIER2"
    assert cancelled["cancel_fee_cents"] == 12500

    plan = read_financing_plan(api, ctx["plan_id"])
    assert plan["status"] == "CANCELLED"
    assert plan["refunded_cents"] == 3138
    assert plan["refunded_cents"] < quote["refund_cents"], (
        "Cancelling from SUPPLY_OPENED settles below the quote by the wasted-pellet charge"
    )


def test_cancelling_a_financed_procedure_waives_every_unpaid_installment(api):
    """PRD §3.9: "One last financing leg belongs to the cancellation story of §3.6. When the
    financed procedure is cancelled, a plan in `DRAFT` moves `DRAFT → CANCELLED` with every
    `PENDING` entry flipped to `WAIVED` and `refunded_cents` set to the down payment less the
    cancellation fee; a plan in `ACTIVE` moves `ACTIVE → CANCELLED` with every `PENDING` or
    `MISSED` entry flipped to `WAIVED`, `waived_cents` recomputed so the second conservation
    leg still balances, and `refunded_cents` written from the final settlement; and a plan in
    `DELINQUENT` moves `DELINQUENT → CANCELLED` on identical terms except that accrued
    `late_fee_cents` is retained and never refunded."
    PRD §3.9: "Every installment from the first through the second-to-last carries exactly the
    base amount; the **final** installment carries the base plus the entire residual."

    Design: Difficulty/compensating_invariant/procedure_cancel_waives_schedule_and_holds_financing_money_conservation
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-09-01T00:00:00Z", scheduled_start="2026-08-01T09:00:00Z",
        patient_email="p30@example.com", pay_first_installment=7773,
    )
    set_clock(api, "2026-06-15T00:00:00Z")

    validate_success(
        api.cancel_procedure(
            ctx["procedure_id"], {"reason": "Relocating out of state"}, FRONT_DESK
        ),
        200,
    )

    plan = read_financing_plan(api, ctx["plan_id"])
    assert plan["status"] == "CANCELLED"
    assert plan["paid_installment_cents"] == 7773
    assert plan["outstanding_cents"] == 0
    assert plan["waived_cents"] == 38867

    assert_schedule_entry(plan, 1, amount_cents=7773, status="PAID")
    for index in (2, 3, 4, 5):
        assert_schedule_entry(plan, index, amount_cents=7773, status="WAIVED")
    assert_schedule_entry(plan, 6, amount_cents=7775, status="WAIVED")


def test_both_financing_conservation_legs_hold_after_the_cancel(api):
    """PRD §2.10: "**Cents of financed principal.** For every `FinancingPlan`, two legs hold
    simultaneously. The first: `principal_cents` equals `down_payment_cents` plus the sum of
    `amount_cents` across every entry of the `schedule`. The second: that same schedule sum
    equals `paid_installment_cents` plus `outstanding_cents` plus `waived_cents`."
    PRD §2.10: "`late_fee_cents` and `refunded_cents` sit deliberately **outside** both legs:
    a late fee is new money owed rather than a redistribution of principal, and a refund is
    money returned to the patient that never re-enters the schedule."
    PRD §3.6: "When the lead is 48 hours or more, `cancel_tier` is `NONE` and the base fee is 0."

    Design: Difficulty/compensating_invariant/procedure_cancel_waives_schedule_and_holds_financing_money_conservation
    """
    ctx = setup_active_financing_plan(
        api, first_due_date="2026-09-01T00:00:00Z", scheduled_start="2026-08-01T09:00:00Z",
        patient_email="p30@example.com", pay_first_installment=7773,
    )
    set_clock(api, "2026-06-15T00:00:00Z")

    cancelled = validate_success(
        api.cancel_procedure(
            ctx["procedure_id"], {"reason": "Relocating out of state"}, FRONT_DESK
        ),
        200,
    )
    assert cancelled["cancel_tier"] == "NONE"
    assert cancelled["cancel_fee_cents"] == 0

    plan = read_financing_plan(api, ctx["plan_id"])
    assert_financing_money_conservation(plan)

    schedule_sum = sum(entry["amount_cents"] for entry in plan["schedule"])
    assert schedule_sum == 46640
    assert plan["down_payment_cents"] + schedule_sum == 58300
    assert (
        plan["paid_installment_cents"] + plan["outstanding_cents"] + plan["waived_cents"]
        == 46640
    )
    assert plan["refunded_cents"] == 19433, (
        "The final settlement is paid-to-date 19433 less a zero fee and no wasted pellets"
    )
    assert plan["late_fee_cents"] == 0


def test_tier_one_cancellation_fee_is_discounted_by_an_active_plus_membership(api):
    """PRD §3.6: "The cancellation fee is a lead-time ladder. Let the lead be the exact number
    of hours from now to the procedure's `scheduled_start`, kept unfloored. When the lead is
    48 hours or more, `cancel_tier` is `NONE` and the base fee is 0. When it is at least 24
    hours but less than 48, the tier is `TIER1` and the base fee is 5000 cents."
    PRD §3.6: "A membership discount then applies: take the membership's `discount_pct` when
    the procedure names a `membership_id` and that membership's `status` is `ACTIVE`, or zero
    otherwise, multiply the base fee by one minus that rate, and round half up once to whole
    cents. That figure is written to `cancel_fee_cents` and the tier to `cancel_tier`."

    Design: Corner/calculations/late_cancel_tier1_fee_is_discounted_by_active_plus_membership
    """
    ctx = setup_pellet_procedure(
        api, target_status="SCHEDULED", prescribed_dose_mg=1000,
        patient_name="Corner Seventeen", patient_email="c17@example.com",
        membership_tier="PLUS", attach_membership=True,
        room_code="RM42", scheduled_start="2026-06-03T09:00:00Z",
    )
    set_clock(api, "2026-06-01T13:00:00Z")

    cancelled = validate_success(
        api.cancel_procedure(
            ctx["procedure_id"], {"reason": "Travel"}, make_patient_headers(ctx["patient_id"])
        ),
        200,
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_tier"] == "TIER1", "44 hours of lead time selects TIER1"
    assert cancelled["cancel_fee_cents"] == 4500
