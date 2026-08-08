"""Pricing a billing cycle: the two readings, the fee waiver and the credits."""

from test_helpers import (
    assert_billing_cycle,
    assert_same_instant,
    decide_prior_authorization,
    file_check_in,
    file_prior_authorization,
    billing_admin_headers,
    open_billing_cycle,
    read_billing_cycle,
    set_clock,
    settle_cycle,
    setup_subscription,
    triage_check_in,
    validate_success,
)

INSURED_MEMBER = {"payment_mode": "INSURANCE", "weight_kg": 95.0}


def test_cash_fork_prices_the_first_cycle(api):
    """PRD §3.9: "cash-fork prescriptions are filled with compounded product listed
    at 20,000 cents a pen — which fork applies is read from the prescription's
    `active_route_mode`, exactly the mapping the routing selector of §3.7 uses."
    PRD §3.9: "- The **cash reading** takes 15 percent of the gross amount, rounds
    it half-up to whole cents, and caps that discount at 9,000 cents; the amount due
    is the gross amount less the capped discount."
    PRD §3.9: "otherwise `charge_basis` is written as `CASH_PAY` and
    `medication_charge_cents` takes the cash reading."

    Design: Difficulty/dual_variant_calc/cash_pay_versus_insurance_adjudicated_cycle_total
    """
    scenario = setup_subscription(
        patient={"email": "ava3@example.com", "full_name": "Ava Reed", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert_billing_cycle(priced)
    assert priced["charge_basis"] == "CASH_PAY"
    assert priced["medication_charge_cents"] == 34000
    assert priced["coaching_addon_fee_cents"] == 0
    assert priced["dispensing_fee_cents"] == 2500
    assert priced["total_due_cents"] == 36500


def test_insurance_fork_prices_the_cycle_after_the_payer_approves(api):
    """PRD §3.9: "Insurance-fork prescriptions are filled with branded product
    listed at 25,000 cents a pen"
    PRD §3.9: "When `active_route_mode` is `INSURANCE` the cycle's `charge_basis` is
    written as `INSURANCE_ADJUDICATED` and `medication_charge_cents` takes the
    insurance reading"
    PRD §3.9: "Settlement also rolls the subscription forward: it opens the next
    billing cycle with `period_start_at` exactly equal to this cycle's
    `period_end_at` and `period_end_at` 30 days beyond that, gives it
    `sequence_number` equal to the subscription's `cycle_count` plus one, increments
    `cycle_count`, and — when `coaching_addon_enabled` is true — grants another 4
    coaching credits."

    Design: Difficulty/dual_variant_calc/cash_pay_versus_insurance_adjudicated_cycle_total
    """
    scenario = setup_subscription(
        patient={"email": "ava4@example.com", "full_name": "Ava Reed", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    first = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )
    settle_cycle(first["id"], payment_reference="PAY-0001")

    authorisation = file_prior_authorization(
        scenario["prescription"]["id"],
        scenario["clinician"]["id"],
        payer_reference="PA-77001",
    )
    decide_prior_authorization(authorisation["id"], "APPROVED")

    set_clock("2026-07-01T00:00:00Z")
    second = open_billing_cycle(scenario["subscription"]["id"])
    priced = validate_success(
        api.invoice_billing_cycle(second["id"], {}, billing_admin_headers())
    )

    assert priced["charge_basis"] == "INSURANCE_ADJUDICATED"
    assert priced["medication_charge_cents"] == 9000
    assert priced["dispensing_fee_cents"] == 2500
    assert priced["total_due_cents"] == 11500
    assert_same_instant(
        priced["period_start_at"], first["period_end_at"], "period_start_at"
    )


def test_insurance_reading_at_one_unit_lands_below_the_out_of_pocket_maximum(api):
    """PRD §3.9: "- The **insurance reading** first caps the gross amount at the
    plan-allowed ceiling of 42,000 cents. From that allowed amount it subtracts a
    flat copay of 3,500 cents, floors the difference at zero, takes 20 percent of
    it, and rounds that coinsurance half-up to whole cents. The amount due is the
    copay plus the coinsurance, capped in turn at the per-cycle out-of-pocket
    maximum of 9,000 cents."
    PRD §3.9: "The product is rounded half-up to whole cents to give the per-unit
    price, and **only then** is it multiplied by the prescription's
    `units_per_cycle` to give the gross amount."

    Design: Difficulty/combinatorial_formula/mode_a_nested_allowed_cap_and_out_of_pocket_maximum
    """
    scenario = setup_subscription(
        patient={"email": "una@example.com", "full_name": "Una One", **INSURED_MEMBER},
        prescription={"units_per_cycle": 1},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["charge_basis"] == "INSURANCE_ADJUDICATED"
    assert priced["medication_charge_cents"] == 7800, (
        "25000 gross leaves a 4300-cent coinsurance on top of the 3500-cent copay"
    )
    assert priced["dispensing_fee_cents"] == 2500
    assert priced["total_due_cents"] == 10300


def test_insurance_reading_at_two_units_is_clipped_by_the_out_of_pocket_maximum(api):
    """PRD §3.9: "The amount due is the copay plus the coinsurance, capped in turn
    at the per-cycle out-of-pocket maximum of 9,000 cents. Because of the two caps
    this figure is nearly insensitive to `dose_level`."
    PRD §3.9: "- The **insurance reading** first caps the gross amount at the
    plan-allowed ceiling of 42,000 cents."

    Design: Difficulty/combinatorial_formula/mode_a_nested_allowed_cap_and_out_of_pocket_maximum
    """
    scenario = setup_subscription(
        patient={"email": "dua@example.com", "full_name": "Dua Two", **INSURED_MEMBER},
        prescription={"units_per_cycle": 2},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["medication_charge_cents"] == 9000, (
        "the 42000 allowed cap yields 11200 before the 9000 out-of-pocket maximum clips it"
    )
    assert priced["total_due_cents"] == 11500


def test_dispensing_fee_survives_a_subtotal_that_excludes_it(api):
    """PRD §3.9: "`dispensing_fee_cents` is 0 when that subtotal is at least 36,000
    cents, and 2,500 cents otherwise. The waiver test reads the subtotal *excluding*
    the dispensing fee, even though the fee is part of the total the member
    ultimately sees — this is deliberate and resolves what would otherwise be a fee
    waived on the strength of a total it belongs to."
    PRD §3.9: "The subtotal is `medication_charge_cents` plus
    `coaching_addon_fee_cents`."

    Design: Difficulty/combinatorial_formula/mode_c_dispensing_fee_waiver_keyed_on_subtotal_excluding_itself
    """
    scenario = setup_subscription(
        patient={"email": "fay@example.com", "full_name": "Fay Ortiz", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
        subscription={"coaching_addon_enabled": False},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["medication_charge_cents"] == 34000
    assert priced["coaching_addon_fee_cents"] == 0
    assert priced["dispensing_fee_cents"] == 2500, (
        "the 34000 subtotal excludes the fee and falls short of 36000"
    )
    assert priced["adherence_credit_cents"] == 0
    assert priced["total_due_cents"] == 36500


def test_dispensing_fee_is_waived_once_the_subtotal_reaches_the_threshold(api):
    """PRD §3.9: "`dispensing_fee_cents` is 0 when that subtotal is at least 36,000
    cents, and 2,500 cents otherwise."
    PRD §3.9: "`coaching_addon_fee_cents` is 4,900 cents when the subscription's
    `coaching_addon_enabled` is true at invoice time, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/mode_c_dispensing_fee_waiver_keyed_on_subtotal_excluding_itself
    """
    scenario = setup_subscription(
        patient={"email": "fay2@example.com", "full_name": "Fay Ortiz", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
        subscription={"coaching_addon_enabled": True},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["medication_charge_cents"] == 34000
    assert priced["coaching_addon_fee_cents"] == 4900
    assert priced["dispensing_fee_cents"] == 0, (
        "the 38900 subtotal already reaches the 36000 waiver threshold"
    )
    assert priced["total_due_cents"] == 38900


def test_three_triaged_reports_earn_the_top_adherence_tier(api):
    """PRD §3.9: "`adherence_credit_cents` rewards engagement. Count the check-ins
    for the subscription's `prescription_id` whose status is `CLEARED`, `ESCALATED`
    or `RESOLVED` and whose `triaged_at` falls at or after the cycle's
    `period_start_at` and strictly before its `period_end_at`. Zero such check-ins
    earns nothing; one or two earns 1,500 cents; three or more earns 3,000 cents."
    PRD §3.9: "`total_due_cents` is the subtotal plus `dispensing_fee_cents` minus
    `adherence_credit_cents`, floored at zero so a generous credit can never produce
    a negative invoice."

    Design: Corner/calculations/adherence_credit_reaches_top_tier_at_three_triaged_check_ins
    """
    scenario = setup_subscription(
        patient={"email": "cal2@example.com", "full_name": "Cal Two", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 2},
    )
    set_clock("2026-06-05T00:00:00Z")
    for nausea, vomiting, expected in ((1, 1, 3), (2, 1, 4), (1, 2, 5)):
        report = file_check_in(
            scenario["patient"]["id"],
            scenario["prescription"]["id"],
            nausea_score=nausea,
            vomiting_score=vomiting,
        )
        assert report["severity_score"] == expected
        triaged = triage_check_in(report["id"], scenario["clinician"]["id"])
        assert triaged["status"] == "CLEARED"

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["medication_charge_cents"] == 34000
    assert priced["dispensing_fee_cents"] == 2500
    assert priced["adherence_credit_cents"] == 3000
    assert priced["total_due_cents"] == 33500


def test_cash_discount_is_capped_at_nine_thousand_cents(api):
    """PRD §3.9: "- The **cash reading** takes 15 percent of the gross amount,
    rounds it half-up to whole cents, and caps that discount at 9,000 cents; the
    amount due is the gross amount less the capped discount. No payer cap applies
    here, so the figure scales with both `dose_level` and `units_per_cycle`."
    PRD §3.9: "`dispensing_fee_cents` is 0 when that subtotal is at least 36,000
    cents, and 2,500 cents otherwise."

    Design: Corner/calculations/cash_discount_cap_binds_at_four_units
    """
    scenario = setup_subscription(
        patient={"email": "cal3@example.com", "full_name": "Cal Three", "weight_kg": 86.7},
        screening={"recorded_weight_kg": 86.7, "egfr": 92.0},
        prescription={"units_per_cycle": 4},
    )

    priced = validate_success(
        api.invoice_billing_cycle(
            scenario["cycle"]["id"], {}, billing_admin_headers()
        )
    )

    assert priced["charge_basis"] == "CASH_PAY"
    assert priced["medication_charge_cents"] == 71000, (
        "the raw 12000-cent discount on an 80000-cent gross is clipped to 9000"
    )
    assert priced["dispensing_fee_cents"] == 0
    assert priced["total_due_cents"] == 71000

    stored = read_billing_cycle(priced["id"])
    assert stored["total_due_cents"] == 71000
