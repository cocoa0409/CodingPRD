"""The curtailment ladder: projected versus assessed requirements, run totals and late fees."""
from test_helpers import (
    assert_credit_line_capacity_identity,
    assert_curtailment_obligation,
    assert_remittance_money_conservation,
    floor_unit,
    list_unit_obligations,
    read_credit_line,
    read_dealer,
    read_unit,
    remit,
    run_curtailment,
    set_clock,
    setup_active_line,
    unit_schedule,
)

THREE_RUNG_NEW_LADDER = [
    {"inventory_class": "NEW", "age_days_from": 90, "age_days_to": 180,
     "cumulative_paydown_bps": 1000},
    {"inventory_class": "NEW", "age_days_from": 180, "age_days_to": 270,
     "cumulative_paydown_bps": 2500},
    {"inventory_class": "NEW", "age_days_from": 270, "age_days_to": None,
     "cumulative_paydown_bps": 5000},
]
NEW_TIER_1000 = {"inventory_class": "NEW", "age_days_from": 90, "age_days_to": None,
                 "cumulative_paydown_bps": 1000}
USED_TIER_1500 = {"inventory_class": "USED", "age_days_from": 90, "age_days_to": None,
                  "cumulative_paydown_bps": 1500}


def _laddered_unit():
    """An active line with a three-rung NEW ladder and one unit floored for 3,000,000 cents."""
    ctx = setup_active_line(tiers=THREE_RUNG_NEW_LADDER)
    ctx.update(
        floor_unit(
            ctx["dealer"]["id"],
            ctx["credit_line"]["id"],
            "LADDERUNIT000001",
            dealer_headers=ctx["dealer_headers"],
            document_reference="MSO-LADDER",
            invoice_amount_cents=3000000,
        )
    )
    return ctx


def _pay_the_first_rung_and_prepay(ctx):
    """Mature the 90-day rung, satisfy it, then prepay a further 200,000 cents."""
    set_clock("2026-10-30T00:00:00Z")
    run_curtailment(dealer_id=ctx["dealer"]["id"])
    first = list_unit_obligations(ctx["unit"]["id"])[0]
    curtailment = remit(
        ctx["dealer"]["id"],
        "CURTAILMENT",
        300000,
        dealer_headers=ctx["dealer_headers"],
        payment_reference="PAY-LADDER-CURT",
        target_obligation_id=first["id"],
    )
    prepayment = remit(
        ctx["dealer"]["id"],
        "PRINCIPAL_PREPAYMENT",
        200000,
        dealer_headers=ctx["dealer_headers"],
        payment_reference="PAY-LADDER-PREPAY",
        target_unit_id=ctx["unit"]["id"],
    )
    return first, curtailment, prepayment


def test_the_projected_ladder_is_built_from_rounded_cumulative_differences():
    """Rungs of 1,000, 2,500 and 5,000 basis points on a 3,000,000 cent advance project 300,000, 450,000 and 750,000.

    PRD: "As a worked illustration: a unit floored at an advance of 3,000,000 cents against rungs of 1,000, 2,500 and 5,000 basis points at 90, 180 and 270 days yields cumulative figures of 300,000, 750,000 and 1,500,000 cents, and therefore projected requirements of 300,000, 450,000 and 750,000 cents on the three obligations."

    Design: Difficulty/dual_variant_calc/curtailment_projected_versus_assessed_after_voluntary_prepayment
    """
    ctx = _laddered_unit()
    obligations = list_unit_obligations(ctx["unit"]["id"])
    assert len(obligations) == 3
    for obligation in obligations:
        assert_curtailment_obligation(obligation)
        assert obligation["status"] == "SCHEDULED"
        assert obligation["required_principal_cents"] == 0
        assert obligation["late_fee_cents"] == 0
        assert obligation["extension_days_applied"] == 0

    assert [o["tier_cumulative_paydown_bps"] for o in obligations] == [1000, 2500, 5000]
    assert [o["projected_principal_cents"] for o in obligations] == [300000, 450000, 750000]
    assert [str(o["due_date"])[:10] for o in obligations] == [
        "2026-10-30",
        "2027-01-28",
        "2027-04-28",
    ]

    schedule = unit_schedule(ctx["unit"]["id"])
    assert schedule["basis"] == "FORWARD_PROJECTED"
    assert schedule["projected_total_required_cents"] == 1500000
    assert [r["projected_principal_cents"] for r in schedule["projected_obligations"]] == [
        300000,
        450000,
        750000,
    ]


def test_a_voluntary_prepayment_moves_the_paid_figure_without_touching_the_projection():
    """Paying the first rung and prepaying 200,000 leaves the frozen projections alone.

    PRD: "Because the figure is blind to actual payments, it never changes after funding."

    Design: Difficulty/dual_variant_calc/curtailment_projected_versus_assessed_after_voluntary_prepayment
    """
    ctx = _laddered_unit()
    first, curtailment, prepayment = _pay_the_first_rung_and_prepay(ctx)

    assert_remittance_money_conservation(curtailment)
    assert curtailment["status"] == "APPLIED"
    assert curtailment["applied_principal_cents"] == 300000
    assert_remittance_money_conservation(prepayment)
    assert prepayment["status"] == "APPLIED"
    assert prepayment["applied_principal_cents"] == 200000

    unit = read_unit(ctx["unit"]["id"])
    assert unit["principal_paid_cents"] == 500000
    assert unit["outstanding_principal_cents"] == 2500000

    obligations = list_unit_obligations(ctx["unit"]["id"])
    assert obligations[0]["id"] == first["id"]
    assert obligations[0]["status"] == "PAID"
    assert obligations[0]["required_principal_cents"] == 300000
    assert obligations[0]["principal_paid_cents"] == 300000
    assert [o["projected_principal_cents"] for o in obligations] == [300000, 450000, 750000]

    schedule = unit_schedule(ctx["unit"]["id"])
    assert schedule["projected_total_required_cents"] == 1500000


def test_the_second_rung_matures_at_the_assessed_figure_not_the_projected_one():
    """At day 180 the assessed requirement is 250,000 while the same row still projects 450,000.

    PRD: "Continuing the illustration above: if the dealership pays the 90-day obligation of 300,000 cents on time and then voluntarily prepays a further 200,000 cents on day 100, then at day 180 the unit's `principal_paid_cents` is 500,000 and its `outstanding_principal_cents` is 2,500,000, so the second obligation's assessed requirement is 750,000 minus 500,000, capped at 2,500,000, which is 250,000 cents — while the very same row's `projected_principal_cents` still reads 450,000."

    Design: Difficulty/dual_variant_calc/curtailment_projected_versus_assessed_after_voluntary_prepayment
    """
    ctx = _laddered_unit()
    _pay_the_first_rung_and_prepay(ctx)

    set_clock("2027-01-28T00:00:00Z")
    run = run_curtailment(dealer_id=ctx["dealer"]["id"])
    assert run["obligations_marked_due_count"] == 1
    assert run["obligations_marked_delinquent_count"] == 0
    assert run["total_required_paydown_cents"] == 250000
    assert run["units_flagged_delinquent_count"] == 0

    obligations = list_unit_obligations(ctx["unit"]["id"])
    second = obligations[1]
    assert second["status"] == "DUE"
    assert second["required_principal_cents"] == 250000
    assert second["projected_principal_cents"] == 450000
    assert second["total_amount_due_cents"] == 250000
    assert second["late_fee_cents"] == 0

    third = obligations[2]
    assert third["status"] == "SCHEDULED"
    assert third["required_principal_cents"] == 0
    assert third["projected_principal_cents"] == 750000


def _three_units_of_3333333():
    """An active line carrying three NEW units each floored for 3,333,333 cents."""
    ctx = setup_active_line(tiers=[NEW_TIER_1000])
    ctx["units"] = [
        floor_unit(
            ctx["dealer"]["id"],
            ctx["credit_line"]["id"],
            seed,
            dealer_headers=ctx["dealer_headers"],
            document_reference="MSO-ROUNDING",
            invoice_amount_cents=3333333,
        )["unit"]
        for seed in ("ROUNDUNITA000001", "ROUNDUNITB000001", "ROUNDUNITC000001")
    ]
    return ctx


def test_the_run_total_rounds_each_obligation_before_adding_them_up():
    """Three units crossing a 1,000 basis point rung together require 999,999 cents, not 1,000,000.

    PRD: "Summing unrounded products and rounding once at the end is wrong and observably different — three `NEW` units each carrying an advance of 3,333,333 cents crossing a 1,000-basis-point rung in the same sweep produce 333,333 cents each for a total of 999,999, not the 1,000,000 that a sum-then-round implementation reports."

    Design: Difficulty/combinatorial_formula/curtailment_run_total_rounds_per_unit_before_summation_mode_b
    """
    ctx = _three_units_of_3333333()
    set_clock("2026-10-30T00:00:00Z")
    run = run_curtailment(dealer_id=ctx["dealer"]["id"])

    assert run["obligations_marked_due_count"] == 3
    assert run["obligations_marked_delinquent_count"] == 0
    assert run["total_required_paydown_cents"] == 999999
    assert run["units_flagged_delinquent_count"] == 0
    assert run["dealer_ids_processed"] == [ctx["dealer"]["id"]]


def test_each_of_the_three_units_carries_its_own_rounded_requirement():
    """Every unit's own obligation reads 333,333 cents and the line's principal reads 9,999,999.

    PRD: "`total_required_paydown_cents` is the sum of `required_principal_cents` across the obligations that matured to `DUE` in this sweep, and **the rounding order here is pinned**: round each obligation's requirement individually first, then add the already-rounded integers."

    Design: Difficulty/combinatorial_formula/curtailment_run_total_rounds_per_unit_before_summation_mode_b
    """
    ctx = _three_units_of_3333333()
    set_clock("2026-10-30T00:00:00Z")
    run_curtailment(dealer_id=ctx["dealer"]["id"])

    for unit in ctx["units"]:
        obligations = list_unit_obligations(unit["id"])
        assert len(obligations) == 1
        assert obligations[0]["status"] == "DUE"
        assert obligations[0]["required_principal_cents"] == 333333
        assert obligations[0]["projected_principal_cents"] == 333333
        assert obligations[0]["total_amount_due_cents"] == 333333
        assert unit_schedule(unit["id"])["projected_total_required_cents"] == 333333

    line = read_credit_line(ctx["credit_line"]["id"])
    assert line["outstanding_principal_cents"] == 9999999
    assert line["available_credit_cents"] == 490000001
    assert_credit_line_capacity_identity(line)


def _small_and_large_delinquent_units():
    """One 3,000,000 cent NEW unit and one 20,000,000 cent USED unit, both tipped delinquent."""
    ctx = setup_active_line(
        tiers=[NEW_TIER_1000, USED_TIER_1500],
        advance_rate_bps_used=10000,
        max_unit_advance_cents_used=25000000,
    )
    ctx["small"] = floor_unit(
        ctx["dealer"]["id"],
        ctx["credit_line"]["id"],
        "FEESMALLUNIT0001",
        dealer_headers=ctx["dealer_headers"],
        document_reference="MSO-FEESMALL",
        invoice_amount_cents=3000000,
    )["unit"]
    ctx["large"] = floor_unit(
        ctx["dealer"]["id"],
        ctx["credit_line"]["id"],
        "FEELARGEUNIT0001",
        dealer_headers=ctx["dealer_headers"],
        document_reference="TITLE-FEELARGE",
        inventory_class="USED",
        title_document_type="TITLE",
        invoice_amount_cents=20000000,
        odometer_miles=41000,
    )["unit"]
    set_clock("2026-11-05T00:00:00Z")
    ctx["run"] = run_curtailment(dealer_id=ctx["dealer"]["id"])
    return ctx


def test_the_late_fee_is_two_percent_of_the_pre_fee_principal_requirement():
    """A 300,000 cent requirement carries a 6,000 cent fee and a 306,000 cent total.

    PRD: "A required principal of 300,000 cents therefore carries a fee of 6,000 and a total of 306,000; a required principal of 3,000,000 cents would carry an uncapped fee of 60,000, so the ceiling binds at 50,000 and the total is 3,050,000."

    Design: Difficulty/combinatorial_formula/delinquency_late_fee_uses_pre_fee_principal_base_and_binds_the_cap_mode_c
    """
    ctx = _small_and_large_delinquent_units()
    obligations = list_unit_obligations(ctx["small"]["id"])
    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation["status"] == "DELINQUENT"
    assert obligation["required_principal_cents"] == 300000
    assert obligation["late_fee_cents"] == 6000
    assert obligation["total_amount_due_cents"] == 306000
    assert obligation["total_amount_due_cents"] != 306122
    assert obligation["became_delinquent_at"] is not None
    assert read_unit(ctx["small"]["id"])["funding_status"] == "DELINQUENT_CURTAILMENT"


def test_the_late_fee_ceiling_binds_on_a_three_million_cent_requirement():
    """A 3,000,000 cent requirement is capped at a 50,000 cent fee rather than the raw 60,000.

    PRD: "The raw fee is `required_principal_cents` multiplied by 200 basis points (two percent) divided by 10,000; that raw figure is rounded half up to whole cents **before** the ceiling is applied, and the recorded `late_fee_cents` is the smaller of the rounded fee and the ceiling of 50,000 cents (five hundred dollars)."

    Design: Difficulty/combinatorial_formula/delinquency_late_fee_uses_pre_fee_principal_base_and_binds_the_cap_mode_c
    """
    ctx = _small_and_large_delinquent_units()
    obligation = list_unit_obligations(ctx["large"]["id"])[0]
    assert obligation["status"] == "DELINQUENT"
    assert obligation["required_principal_cents"] == 3000000
    assert obligation["late_fee_cents"] == 50000
    assert obligation["late_fee_cents"] != 60000
    assert obligation["total_amount_due_cents"] == 3050000

    run = ctx["run"]
    assert run["obligations_marked_due_count"] == 2
    assert run["obligations_marked_delinquent_count"] == 2
    assert run["units_flagged_delinquent_count"] == 2
    assert run["total_required_paydown_cents"] == 3300000

    dealer = read_dealer(ctx["dealer"]["id"])
    assert dealer["delinquent_unit_count"] == 2
    assert dealer["risk_score"] == 80
    assert dealer["risk_rating"] == "B"
    assert dealer["audit_frequency_days"] == 90


def _two_units_tipped_delinquent():
    """Two NEW units of 3,000,000 cents each, swept past their grace period."""
    ctx = setup_active_line(tiers=[NEW_TIER_1000])
    ctx["units"] = [
        floor_unit(
            ctx["dealer"]["id"],
            ctx["credit_line"]["id"],
            seed,
            dealer_headers=ctx["dealer_headers"],
            document_reference="MSO-CASCADE",
            invoice_amount_cents=3000000,
        )["unit"]
        for seed in ("CASCADEUNITA0001", "CASCADEUNITB0001")
    ]
    return ctx


def test_delinquency_flags_the_units_without_shrinking_the_borrowing_base():
    """Both obligations tip to DELINQUENT with a 6,000 cent fee while eligible collateral holds.

    PRD: "Note what does *not* change: the line's `eligible_collateral_cents` is untouched by delinquency, because a late unit is still on the lot and still eligible collateral."

    Design: Difficulty/transitive_cascade/curtailment_run_cascades_four_hops_from_obligation_to_next_audit_due_at
    """
    ctx = _two_units_tipped_delinquent()
    set_clock("2026-11-05T00:00:00Z")
    run = run_curtailment(dealer_id=ctx["dealer"]["id"])
    assert run["obligations_marked_delinquent_count"] == 2
    assert run["units_flagged_delinquent_count"] == 2
    assert run["total_required_paydown_cents"] == 600000
    assert run["exceptions_expired_count"] == 0

    for unit in ctx["units"]:
        obligation = list_unit_obligations(unit["id"])[0]
        assert obligation["status"] == "DELINQUENT"
        assert obligation["required_principal_cents"] == 300000
        assert obligation["late_fee_cents"] == 6000
        assert obligation["total_amount_due_cents"] == 306000
        assert read_unit(unit["id"])["funding_status"] == "DELINQUENT_CURTAILMENT"

    line = read_credit_line(ctx["credit_line"]["id"])
    assert line["outstanding_principal_cents"] == 6000000
    assert line["eligible_collateral_cents"] == 6000000
    assert line["borrowing_base_deficiency_cents"] == 0
    assert line["status"] == "ACTIVE"
    assert_credit_line_capacity_identity(line)


def test_two_delinquent_units_halve_the_audit_cadence_and_pull_the_due_date_forward():
    """The second delinquent unit drops the dealer to a B rating and re-derives next_audit_due_at.

    PRD: "That unit transition increments the dealership's `delinquent_unit_count`, which re-triggers the risk assessment of §2.10 — rewriting `risk_score`, `risk_rating` and `audit_frequency_days`, and re-deriving `next_audit_due_at` from the unchanged anchor with the new cadence."

    Design: Difficulty/transitive_cascade/curtailment_run_cascades_four_hops_from_obligation_to_next_audit_due_at
    """
    ctx = _two_units_tipped_delinquent()
    before = read_dealer(ctx["dealer"]["id"])
    assert before["risk_rating"] == "A"
    assert before["audit_frequency_days"] == 180
    assert str(before["next_audit_due_at"]).startswith("2027-01-28T00:00:00")

    set_clock("2026-11-05T00:00:00Z")
    run_curtailment(dealer_id=ctx["dealer"]["id"])

    after = read_dealer(ctx["dealer"]["id"])
    assert after["delinquent_unit_count"] == 2
    assert after["risk_score"] == 80
    assert after["risk_rating"] == "B"
    assert after["audit_frequency_days"] == 90
    assert str(after["next_audit_due_at"]).startswith("2026-10-30T00:00:00")
    assert after["status"] == "ACTIVE"
    assert after["open_sot_incident_count"] == 0
    assert after["open_sot_exposure_cents"] == 0
