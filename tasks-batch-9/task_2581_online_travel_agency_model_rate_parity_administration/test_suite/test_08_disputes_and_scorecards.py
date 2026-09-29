"""Settlement arithmetic, the two liability variants and the supplier scorecard."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers.assertions import (
    assert_booking_conserved,
    assert_booking_state,
    assert_pct,
    assert_score,
    assert_settlement_identity,
)
from test_helpers.fixtures import (
    captured_booking,
    certified_hotel,
    hotel_agency_offer,
    parity_case_at,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    COMPLIANCE_OFFICER_USER_ID,
    PLATFORM_ADMIN,
)


def _two_agreement_supplier(b):
    """A supplier whose travel-date agreement is not the one covering the filing date."""
    ctx = certified_hotel(b)
    ctx["agreement_travel"] = b.agreement(
        ctx.supplier["id"],
        model="AGENCY",
        effective_from="2026-08-01",
        effective_to="2026-09-30",
        chargeback_liability_pct_marketplace=0.60,
        fraud_liability_cap_cents=50000,
    )
    ctx["agreement_filing"] = b.agreement(
        ctx.supplier["id"],
        model="MERCHANT",
        effective_from="2026-10-01",
        effective_to="2027-03-31",
        chargeback_liability_pct_marketplace=0.25,
        fraud_liability_cap_cents=900000,
    )
    ctx["rate_plan"] = b.rate_plan(ctx.supplier["id"], ctx.market["id"], tax_fee_pct=0.07)
    ctx["offer"] = b.live_offer(
        ctx.rate_plan["id"], travel_date="2026-09-20", net_rate_cents=185053
    )
    booking = b.booking(offer=ctx.offer)
    b.capture(booking["id"])
    ctx["booking"] = b.read_booking(booking["id"])
    return ctx


def test_dispute_filing_stamps_the_settlement_and_the_preliminary_split(b, client):
    """The fee tier is keyed on the amount at stake and the preliminary split uses the
    agreement covering the filing date.

    PRD 3.9: "`mediation_fee_cents` is a flat base of 2,500 cents plus the product of
    `refund_due_cents` and `mediation_fee_pct` rounded half up to a whole cent" and
    "`preliminary_marketplace_cents` is `settlement_total_cents` multiplied by the
    filing agreement's `chargeback_liability_pct_marketplace`".

    Design: Difficulty/dual_variant_calc/dispute_liability_preliminary_vs_binding_diverge
    """
    ctx = _two_agreement_supplier(b)
    assert ctx.offer["display_total_cents"] == 198007
    assert ctx.offer["taxes_fees_cents"] == 12954
    assert ctx.offer["marketplace_margin_cents"] == 27758
    assert ctx.offer["supplier_payable_cents"] == 157295

    b.set_clock("2026-10-05T00:00:00Z")
    dispute = b.dispute(
        ctx.booking["id"],
        dispute_type="FRAUD",
        claim_cents=198007,
        headers=COMPLIANCE_OFFICER_ALT,
        narrative="card-not-present fraud claim from the issuer",
    )

    assert dispute["refund_due_cents"] == 198007
    assert_pct(dispute["mediation_fee_pct"], 0.035)
    assert dispute["mediation_fee_cents"] == 9430
    assert dispute["settlement_total_cents"] == 207437
    assert dispute["filing_agreement_id"] == ctx.agreement_filing["id"]
    assert dispute["binding_agreement_id"] == ctx.agreement_travel["id"]
    assert dispute["preliminary_marketplace_cents"] == 51859
    assert dispute["preliminary_supplier_cents"] == 155578
    assert dispute["status"] == "FILED"
    assert_settlement_identity(dispute)


def test_the_binding_split_reads_the_travel_date_agreement_and_the_fraud_cap(b, client):
    """Resolution splits against the binding agreement and clamps the fraud share.

    PRD 3.9: "only when `dispute_type` is `FRAUD`, the cap bites:
    `binding_marketplace_cents` is the smaller of `uncapped_marketplace_cents` and the
    binding agreement's `fraud_liability_cap_cents` ... Because the two variants read
    different agreements, the same settlement total can split differently at filing and
    at resolution".

    Design: Difficulty/dual_variant_calc/dispute_liability_preliminary_vs_binding_diverge
    """
    ctx = _two_agreement_supplier(b)
    b.set_clock("2026-10-05T00:00:00Z")
    dispute = b.dispute(
        ctx.booking["id"],
        dispute_type="FRAUD",
        claim_cents=198007,
        headers=COMPLIANCE_OFFICER_ALT,
    )

    resolved = validate_success(
        client.resolve_dispute_case(
            dispute["id"],
            {"outcome": "SPLIT", "note": "shared liability per the travel-date agreement"},
            COMPLIANCE_OFFICER,
        )
    )

    assert resolved["outcome"] == "SPLIT"
    assert resolved["uncapped_marketplace_cents"] == 124462
    assert resolved["binding_marketplace_cents"] == 50000
    assert resolved["binding_supplier_cents"] == 157437
    assert resolved["status"] == "RESOLVED"
    assert resolved["binding_marketplace_cents"] != resolved["preliminary_marketplace_cents"]
    assert_settlement_identity(resolved)


def test_a_partial_refund_leaves_only_the_refunded_amount_at_stake(b, client):
    """Halving the refund inside the cutoff writes the exact reversal ledger.

    PRD 3.8: "The supplier debit is the booking's current `supplier_payable_cents`
    multiplied by the same fraction, rounded half up ... The three amounts are also
    recorded as `last_refund_clawback_cents`, `last_refund_supplier_debit_cents` and
    `last_refund_tax_cents`".

    Design: Difficulty/combinatorial_formula/dispute_fee_tier_keyed_on_availability_clamped_refund_due
    """
    ctx = captured_booking(b, net_rate_cents=200000, tax_fee_pct=0.0)
    assert ctx.offer["display_total_cents"] == 200000

    b.set_clock("2026-09-18T16:00:00Z")
    cancelled = b.cancel(ctx.booking["id"], reason="cancelled inside the cutoff")

    assert_pct(cancelled["cancellation_refund_pct"], 0.50)
    assert cancelled["refunded_cents"] == 100000
    assert cancelled["last_refund_clawback_cents"] == 15000
    assert cancelled["last_refund_supplier_debit_cents"] == 85000
    assert cancelled["last_refund_tax_cents"] == 0
    assert_booking_state(
        cancelled, payment_status="REFUNDED_PARTIAL", fulfillment_status="CANCELLED"
    )
    assert_booking_conserved(cancelled)


def test_the_fee_tier_is_keyed_on_the_clamped_amount_not_on_the_claim(b, client):
    """A wild claim is clamped to what is still at stake before the tier is chosen.

    PRD 3.9: "`refund_due_cents` is the smaller of `claim_cents` and the booking's
    `charged_total_cents` minus its `refunded_cents` ... The tier is keyed on
    `refund_due_cents` and never on the settlement total".

    Design: Difficulty/combinatorial_formula/dispute_fee_tier_keyed_on_availability_clamped_refund_due
    """
    ctx = captured_booking(b, net_rate_cents=200000, tax_fee_pct=0.0)
    b.set_clock("2026-09-18T16:00:00Z")
    b.cancel(ctx.booking["id"], reason="cancelled inside the cutoff")

    dispute = b.dispute(
        ctx.booking["id"],
        dispute_type="REFUND_PASSTHROUGH",
        claim_cents=999999,
        narrative="supplier refuses the pass-through share",
    )

    assert dispute["refund_due_cents"] == 100000
    assert_pct(dispute["mediation_fee_pct"], 0.035)
    assert dispute["mediation_fee_cents"] == 6000
    assert dispute["settlement_total_cents"] == 106000
    assert dispute["status"] == "FILED"
    assert dispute["mediation_rounds"] == 0
    assert_settlement_identity(dispute)


def _reverse_refund_case(b):
    """A half-refunded booking with a dispute filed over exactly the refunded cash."""
    ctx = captured_booking(b)
    b.set_clock("2026-09-18T16:00:00Z")
    ctx["cancelled"] = b.cancel(
        ctx.booking["id"], reason="traveller cancelled inside the cutoff"
    )
    ctx["dispute"] = b.dispute(
        ctx.booking["id"], dispute_type="REFUND_PASSTHROUGH", claim_cents=12120
    )
    return ctx


def test_the_refund_ledger_and_the_filing_split_are_stamped_before_any_reversal(b, client):
    """The cancel writes a replayable ledger and the filing prices the disputed cash.

    PRD 3.8: "before and after any cancellation, `charged_total_cents` equals
    `supplier_payable_cents` plus `marketplace_margin_cents` plus `taxes_fees_cents`
    plus `refunded_cents`"; PRD 3.9 stamps the preliminary split at filing.

    Design: Difficulty/compensating_invariant/cancel_then_reverse_refund_restores_the_charged_total_decomposition
    """
    ctx = _reverse_refund_case(b)
    cancelled = ctx.cancelled

    assert_pct(cancelled["cancellation_refund_pct"], 0.50)
    assert cancelled["refunded_cents"] == 12120
    assert cancelled["marketplace_margin_cents"] == 1800
    assert cancelled["supplier_payable_cents"] == 10200
    assert cancelled["taxes_fees_cents"] == 120
    assert cancelled["last_refund_clawback_cents"] == 1800
    assert cancelled["last_refund_supplier_debit_cents"] == 10200
    assert cancelled["last_refund_tax_cents"] == 120
    assert cancelled["payment_status"] == "REFUNDED_PARTIAL"
    assert_booking_conserved(cancelled)

    dispute = ctx.dispute
    assert dispute["refund_due_cents"] == 12120
    assert_pct(dispute["mediation_fee_pct"], 0.020)
    assert dispute["mediation_fee_cents"] == 2742
    assert dispute["settlement_total_cents"] == 14862
    assert dispute["preliminary_marketplace_cents"] == 8917
    assert dispute["preliminary_supplier_cents"] == 5945


def test_reversing_the_refund_restores_the_original_money_decomposition(b, client):
    """The stored ledger is replayed, so the booking returns to its pre-cancel shape.

    PRD 3.9: "`last_refund_clawback_cents` is added back to
    `marketplace_margin_cents`, `last_refund_supplier_debit_cents` is added back to
    `supplier_payable_cents`, and `last_refund_tax_cents` is added back to
    `taxes_fees_cents`; and only then are all three of those last-refund fields reset to
    0. Replaying the stored amounts rather than recomputing them is what makes the
    reversal exact."

    Design: Difficulty/compensating_invariant/cancel_then_reverse_refund_restores_the_charged_total_decomposition
    """
    ctx = _reverse_refund_case(b)

    resolved = validate_success(
        client.resolve_dispute_case(
            ctx.dispute["id"],
            {
                "outcome": "REVERSE_REFUND",
                "note": "mediation found for the supplier; the refund is reversed in full",
            },
            COMPLIANCE_OFFICER,
        )
    )
    assert resolved["outcome"] == "REVERSE_REFUND"
    assert resolved["uncapped_marketplace_cents"] == 0
    assert resolved["binding_marketplace_cents"] == 0
    assert resolved["binding_supplier_cents"] == 14862
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    booking = b.read_booking(ctx.booking["id"])
    assert booking["payment_status"] == "CAPTURED"
    assert booking["refunded_cents"] == 0
    assert booking["marketplace_margin_cents"] == 3600
    assert booking["supplier_payable_cents"] == 20400
    assert booking["taxes_fees_cents"] == 240
    assert booking["last_refund_clawback_cents"] == 0
    assert booking["last_refund_supplier_debit_cents"] == 0
    assert booking["last_refund_tax_cents"] == 0
    assert_booking_conserved(booking)


def _scorecard_scenario(b):
    """One closed MINOR parity case and one still-open MAJOR case inside the period."""
    ctx = hotel_agency_offer(b)
    ctx["second_offer"] = b.live_offer(
        ctx.rate_plan["id"], travel_date="2026-09-21", net_rate_cents=24000
    )

    minor_obs, minor_case = parity_case_at(b, ctx, 24000, travel_date="2026-09-20")
    assert minor_obs["breach_bps"] == 100
    assert minor_obs["severity"] == "MINOR"
    b.close_parity(minor_case["id"], outcome="COMPLIANT")

    major_obs, major_case = parity_case_at(b, ctx, 23520, travel_date="2026-09-21")
    assert major_obs["breach_bps"] == 306
    assert major_obs["severity"] == "MAJOR"
    b.notify_parity(major_case["id"])

    ctx["minor_case"] = minor_case
    ctx["major_case"] = major_case
    return ctx


def test_the_provisional_scorecard_charges_a_projected_escalation_point(b, client):
    """An open case pays its weight plus one projected point under the provisional variant.

    PRD 3.9: "Under the **provisional** variant every in-period case counts at its
    current severity weight, and any case still sitting in a non-terminal status ...
    adds one further projected escalation point on top of its weight" and
    "`parity_component` is one hundred minus eight points of penalty per point
    accumulated".

    Design: Difficulty/dual_variant_calc/supplier_composite_score_provisional_vs_final_diverge
    """
    ctx = _scorecard_scenario(b)

    scorecard = b.scorecard(
        ctx.supplier["id"], period_start="2026-08-01", period_end="2026-09-30"
    )

    assert scorecard["variant"] == "PROVISIONAL"
    assert scorecard["parity_penalty_points"] == 4
    assert_score(scorecard["parity_component"], 68)
    assert_score(scorecard["content_component"], 88)
    assert_score(scorecard["connectivity_component"], 91)
    assert_score(scorecard["dispute_component"], 100)
    assert scorecard["cases_counted"] == 2
    assert_score(scorecard["composite_score"], 85.60)


def test_finalising_the_scorecard_drops_the_still_open_case(b, client):
    """The final variant admits only closed or escalated cases, so the score diverges.

    PRD 3.9: "Under the **final** variant only cases whose status is
    `RESOLVED_COMPLIANT`, `WAIVED` or `ESCALATED` count at all ... and cases still
    non-terminal are excluded entirely and roll into the next period."

    Design: Difficulty/dual_variant_calc/supplier_composite_score_provisional_vs_final_diverge
    """
    ctx = _scorecard_scenario(b)
    provisional = b.scorecard(
        ctx.supplier["id"], period_start="2026-08-01", period_end="2026-09-30"
    )

    b.set_clock("2026-10-01T00:00:00Z")
    final = validate_success(
        client.finalize_scorecard(provisional["id"], {}, COMPLIANCE_OFFICER)
    )

    assert final["variant"] == "FINAL"
    assert final["parity_penalty_points"] == 1
    assert_score(final["parity_component"], 92)
    assert final["cases_counted"] == 1
    assert_score(final["composite_score"], 92.80)
    assert final["composite_score"] != provisional["composite_score"]
    assert final["finalized_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert final["version"] == provisional["version"] + 1


def test_the_mediation_fee_is_a_flat_base_plus_a_tier_of_the_capped_amount(b, client):
    """Two claims on two bookings show the same flat base under two different amounts.

    PRD 3.9: "`mediation_fee_cents` is a flat base of 2,500 cents plus the
    product of `refund_due_cents` and `mediation_fee_pct` rounded half up to a
    whole cent", over a `refund_due_cents` that is "the smaller of `claim_cents`
    and the booking's `charged_total_cents` minus its `refunded_cents`".

    Design: Corner/calculations/mediation_fee_uses_the_base_cents_constant_plus_the_selected_tier
    """
    ctx = captured_booking(b)
    second = b.booking(offer=ctx.offer)
    b.capture(second["id"])

    small = b.dispute(
        ctx.booking["id"],
        claim_cents=1000,
        headers=COMPLIANCE_OFFICER_ALT,
        narrative="resort fee double charged",
    )
    assert small["refund_due_cents"] == 1000
    assert_pct(small["mediation_fee_pct"], 0.020)
    assert small["mediation_fee_cents"] == 2520
    assert small["settlement_total_cents"] == 3520
    # 2520 less the 20 cents of tier on 1000 leaves the flat base.
    assert small["mediation_fee_cents"] - 20 == 2500

    large = b.dispute(
        second["id"],
        claim_cents=60000,
        headers=COMPLIANCE_OFFICER_ALT,
        narrative="room never delivered, full claim plus damages",
    )
    assert large["refund_due_cents"] == 24240
    assert_pct(large["mediation_fee_pct"], 0.020)
    assert large["mediation_fee_cents"] == 2985
    assert large["settlement_total_cents"] == 27225
    # 2985 less the 485 cents of tier on 24240 leaves the same flat base.
    assert large["mediation_fee_cents"] - 485 == 2500


def test_resolving_an_already_resolved_dispute_is_refused(b, client):
    """RESOLVED is terminal, so a second outcome cannot overwrite the binding split.

    PRD 3.9: resolution "may be reached from `FILED`, from `RESPONSE_REQUESTED` or
    from `MEDIATION`, moving the case to the terminal `RESOLVED`"; PRD 5 lists
    `ERR_DISPUTE_ALREADY_RESOLVED` for a case that is already resolved.

    Design: Corner/state_machines/resolve_an_already_resolved_dispute_is_rejected
    """
    ctx = captured_booking(b)
    dispute = b.dispute(
        ctx.booking["id"], claim_cents=1000, headers=COMPLIANCE_OFFICER_ALT
    )
    assert dispute["refund_due_cents"] == 1000
    assert_pct(dispute["mediation_fee_pct"], 0.020)
    assert dispute["mediation_fee_cents"] == 2520
    assert dispute["settlement_total_cents"] == 3520

    resolved = validate_success(
        client.resolve_dispute_case(
            dispute["id"], {"outcome": "SPLIT"}, COMPLIANCE_OFFICER
        )
    )
    assert resolved["outcome"] == "SPLIT"
    assert resolved["uncapped_marketplace_cents"] == 2112
    assert resolved["binding_marketplace_cents"] == 2112
    assert resolved["binding_supplier_cents"] == 1408
    assert resolved["status"] == "RESOLVED"

    again = client.resolve_dispute_case(
        dispute["id"], {"outcome": "MARKETPLACE_LIABLE"}, COMPLIANCE_OFFICER
    )
    validate_error(again, E.ERR_DISPUTE_ALREADY_RESOLVED, 409)

    after = b.read_dispute(dispute["id"])
    assert after["outcome"] == "SPLIT"
    assert after["binding_marketplace_cents"] == 2112
    assert after["binding_supplier_cents"] == 1408
    assert after["version"] == resolved["version"]


def test_a_fully_refunded_booking_has_nothing_left_to_dispute(b, client):
    """When the whole charge has been returned there is no amount to argue about.

    PRD 3.9: "the booking's `charged_total_cents` minus its `refunded_cents` must be
    at least 1, otherwise `ERR_NOTHING_TO_DISPUTE`."

    Design: Corner/errors/dispute_on_a_fully_refunded_booking_is_rejected
    """
    ctx = captured_booking(b)
    cancelled = b.cancel(ctx.booking["id"], reason="traveller cancelled well in advance")
    assert_pct(cancelled["cancellation_refund_pct"], 1.00)
    assert cancelled["refunded_cents"] == 24240
    assert cancelled["payment_status"] == "REFUNDED_FULL"

    refused = client.create_dispute_case(
        ctx.booking["id"],
        {
            "dispute_type": "REFUND_PASSTHROUGH",
            "claim_cents": 5000,
            "narrative": "supplier disputes the clawback",
        },
        COMPLIANCE_OFFICER_ALT,
    )
    validate_error(refused, E.ERR_NOTHING_TO_DISPUTE, 422)

    _rows, meta = validate_paginated(
        client.list_dispute_cases(
            PLATFORM_ADMIN, params={"booking_id": ctx.booking["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_scorecard_cannot_be_finalised_until_the_period_is_closed(b, client):
    """A period ending today is not yet closed, and the refusal leaves it PROVISIONAL.

    PRD 3.9: finalisation "requires the logical-clock date to be strictly after
    `period_end`, otherwise `ERR_PERIOD_NOT_CLOSED` — a period that is merely ending
    today is not yet closed."

    Design: Corner/errors/finalizing_a_scorecard_before_the_period_closes_is_rejected
    """
    ctx = certified_hotel(b)
    scorecard = b.scorecard(
        ctx.supplier["id"], period_start="2026-07-01", period_end="2026-08-31"
    )
    assert scorecard["variant"] == "PROVISIONAL"
    assert scorecard["parity_penalty_points"] == 0
    assert_score(scorecard["composite_score"], 95.20)

    refused = client.finalize_scorecard(
        scorecard["id"], {"note": "closing early"}, COMPLIANCE_OFFICER
    )
    validate_error(refused, E.ERR_PERIOD_NOT_CLOSED, 409)

    still_open = validate_success(client.get_scorecard(scorecard["id"], PLATFORM_ADMIN))
    assert still_open["variant"] == "PROVISIONAL"
    assert still_open["finalized_by_user_id"] is None
    assert still_open["version"] == scorecard["version"]

    b.set_clock("2026-09-01T00:00:00Z")
    final = validate_success(
        client.finalize_scorecard(
            scorecard["id"], {"note": "period is closed"}, COMPLIANCE_OFFICER
        )
    )
    assert final["variant"] == "FINAL"
    assert final["finalized_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert final["version"] == 2
    assert final["parity_penalty_points"] == 0
    assert_score(final["composite_score"], scorecard["composite_score"])
