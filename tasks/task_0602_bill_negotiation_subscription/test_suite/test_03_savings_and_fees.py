"""Success-fee split, refund pursuit, lifetime rollup, savings report, cascades."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_agent_headers,
    setup_proposed_case, setup_confirmed_charge, setup_open_case,
    setup_filed_refund_claim, setup_under_review_claim, setup_won_case,
    get_ledger_entry_for_member, create_member, create_agent,
    create_negotiation_case_payload, create_refund_claim_payload,
    ApiErrorId,
)


# --- Success-fee split: dual variant (negotiation delta vs refund absolute) ---

def test_dual_variant_negotiation_vs_refund_fee_basis(api):
    """PRD §3.6: "First, `gross_annual_savings_cents` is computed as the baseline annual cost minus the agreed annual cost; the gross for a won negotiation is therefore the difference between two annual figures".
    PRD §3.6: "There, the gross is not a delta of two figures but a single absolute amount: the approved refund."
    PRD §3.6: "when the gross is at least 10,000 cents but below 50,000 cents the rate is 0.35 ... when the gross is below 10,000 cents the rate is 0.40".

    Design: Difficulty/dual_variant_calc/success_fee_split_negotiation_vs_refund_basis
    """
    # Negotiation: baseline 60000, agreed 48000 -> gross 12000 (MID 0.35) -> fee 4200
    member, agent, charge, case = setup_proposed_case(48000, charge_amount_cents=5000)
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    assert won["gross_annual_savings_cents"] == 12000
    assert won["success_fee_cents"] == 4200
    assert won["member_net_savings_cents"] == 7800

    # Refund on the SAME member: PRICE_DROP old 2000 new 1500 -> claimed 3000; approve 3000.
    # gross 3000 (LOW 0.40) -> fee 1200, net 1800.
    mh = make_member_headers(member["id"])
    rc2 = validate_success(api.create_recurring_charge(
        {"linked_account_id": charge["linked_account_id"], "merchant_name": "NewsCo",
         "amount_cents": 2000, "cadence": "MONTHLY", "category": "OTHER",
         "first_seen_utc": "2026-01-01T00:00:00Z"}, headers=mh), 201)
    api.confirm_recurring_charge(rc2["id"], headers=mh)
    claim = validate_success(api.create_refund_claim(
        create_refund_claim_payload(member["id"], rc2["id"], claim_type="PRICE_DROP",
                                    observed_old_amount_cents=2000, observed_new_amount_cents=1500),
        headers=mh), 201)
    assert claim["claimed_refund_cents"] == 3000
    ah = make_agent_headers(agent["id"])
    api.start_review_refund_claim(claim["id"], headers=ah)
    refunded = validate_success(api.approve_refund_claim(claim["id"], {"approved_refund_cents": 3000}, headers=ah))
    assert refunded["success_fee_cents"] == 1200
    assert refunded["member_net_savings_cents"] == 1800


def test_success_fee_tier_then_round_then_cap_order(api):
    """PRD §3.6: "Step three — cap**: the fee is reduced to 20,000 cents if the rounded raw fee exceeds that cap."
    PRD §3.6: "when the gross is at least 50,000 cents the rate is 0.30."

    Design: Difficulty/combinatorial_formula/success_fee_split_tier_then_round_then_cap_order
    """
    # ANNUAL 800000 -> baseline 800000; agreed 100000 -> gross 700000 (HIGH 0.30)
    # raw 210000 -> capped to 20000; net 680000.
    member, agent, charge, case = setup_proposed_case(100000, charge_amount_cents=800000, cadence="ANNUAL")
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    assert won["gross_annual_savings_cents"] == 700000
    assert won["success_fee_cents"] == 20000
    assert won["member_net_savings_cents"] == 680000


def test_success_fee_low_tier_rate(api):
    """PRD §3.6: "when the gross is below 10,000 cents the rate is 0.40".
    PRD §3.6: "the raw fee is the gross multiplied by the chosen rate, rounded half-up to whole cents".

    Design: Corner/calculations/success_fee_low_tier_rate_applied
    """
    # ANNUAL 9000 -> baseline 9000; agreed 1000 -> gross 8000 (LOW 0.40) -> fee 3200, net 4800.
    member, agent, charge, case = setup_proposed_case(1000, charge_amount_cents=9000, cadence="ANNUAL")
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    assert won["gross_annual_savings_cents"] == 8000
    assert won["success_fee_cents"] == 3200
    assert won["member_net_savings_cents"] == 4800


# --- Refund pursuit amounts ---

def test_refund_pursuit_price_drop_lookback(api):
    """PRD §3.9: "For a `PRICE_DROP`, the platform pursues the delta retroactively over the lookback window — the per-cycle delta multiplied by **six** already-billed cycles."

    Design: Difficulty/combinatorial_formula/refund_pursuit_pricedrop_multiinput_nonlinear
    """
    member, charge, claim = setup_filed_refund_claim(
        claim_type="PRICE_DROP", observed_old_amount_cents=2000,
        observed_new_amount_cents=1500, charge_amount_cents=2000,
    )
    assert claim["claimed_refund_cents"] == 3000  # (2000-1500)*6
    assert claim["status"] == "FILED"


def test_refund_pursuit_price_drop_value_pinned(api):
    """PRD §3.9: "A new claim has `status` `FILED`, a `dispute_round` of zero, and a computed `claimed_refund_cents` set at creation."
    PRD §3.9: "the per-cycle delta multiplied by **six** already-billed cycles."

    Design: Difficulty/combinatorial_formula/refund_pursuit_pricedrop_multiinput_nonlinear
    """
    member, charge, claim = setup_filed_refund_claim(
        claim_type="PRICE_DROP", observed_old_amount_cents=2000,
        observed_new_amount_cents=1500, charge_amount_cents=2000,
    )
    assert claim["dispute_round"] == 0
    assert claim["claimed_refund_cents"] == 3000


def test_refund_pursuit_double_bill_full_old(api):
    """PRD §3.9: "For a `DOUBLE_BILL`, the platform pursues a single full duplicate charge at the old price — exactly the `observed_old_amount_cents`, once."

    Design: Corner/calculations/refund_pursuit_double_bill_full_old_amount
    """
    member, charge, claim = setup_filed_refund_claim(
        claim_type="DOUBLE_BILL", observed_old_amount_cents=4000,
        observed_new_amount_cents=0, charge_amount_cents=4000,
    )
    assert claim["claimed_refund_cents"] == 4000


def test_refund_pursuit_service_outage_prorated(api):
    """PRD §3.9: "For a `SERVICE_OUTAGE`, the platform pursues a pro-rated credit on the old amount for the outage portion of a thirty-day cycle: the old amount multiplied by **ten** outage days, divided by thirty days, rounded half-up to whole cents."

    Design: Corner/calculations/refund_pursuit_service_outage_prorated_rounded
    """
    member, charge, claim = setup_filed_refund_claim(
        claim_type="SERVICE_OUTAGE", observed_old_amount_cents=6000,
        observed_new_amount_cents=6000, charge_amount_cents=6000,
    )
    assert claim["claimed_refund_cents"] == 2000  # round_half_up(6000*10/30)


# --- Cascades + rollup + report ---

def test_won_cascade_books_ledger_and_rollup(api):
    """PRD §3.6: "The case then books a `SavingsLedgerEntry ... the owning member's lifetime totals are recomputed (Section 3.7)".
    PRD §3.6: "copies the realized amounts ... member_net_cents` (the member's net, equal to the gross savings minus the success fee). Its `transfer_status` begins at `PENDING".
    PRD §3.7: "lifetime_member_savings_cents` is recomputed as the sum of `member_net_savings_cents` across that member's `WON` cases".

    Design: Difficulty/transitive_cascade/negotiation_won_cascade_ledger_member_depth3
    """
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    assert case["member_net_savings_cents"] == 7800
    entry = get_ledger_entry_for_member(member["id"])
    assert entry["negotiation_case_id"] == case["id"]
    assert entry["member_net_cents"] == 7800
    assert entry["transfer_status"] == "PENDING"
    mem = validate_success(api.get_member(member["id"], headers=make_member_headers(member["id"])))
    assert mem["lifetime_member_savings_cents"] == 7800


def test_won_cascade_member_lifetime_gross(api):
    """PRD §3.7: "The member's `lifetime_gross_savings_cents` is recomputed as the sum of `gross_annual_savings_cents` across all of that member's negotiation cases whose status is `WON".

    Design: Difficulty/transitive_cascade/negotiation_won_cascade_ledger_member_depth3
    """
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    mem = validate_success(api.get_member(member["id"], headers=make_member_headers(member["id"])))
    assert mem["lifetime_gross_savings_cents"] == 12000
    assert mem["lifetime_member_savings_cents"] == 7800


def test_lifetime_rollup_vs_savings_report_buckets(api):
    """PRD §3.8: "The report's realized gross is the member's `lifetime_gross_savings_cents` and its realized net is the member's `lifetime_member_savings_cents".
    PRD §3.8: "The pending-transfer figure is the sum of `member_net_cents` across all of the member's savings ledger entries whose `transfer_status` is `PENDING`."
    PRD §3.8: "Total fees are the realized gross minus the realized net."

    Design: Difficulty/dual_variant_calc/lifetime_rollup_vs_savings_report_basis
    """
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    mh = make_member_headers(member["id"])
    mem = validate_success(api.get_member(member["id"], headers=mh))
    assert mem["lifetime_gross_savings_cents"] == 12000
    assert mem["lifetime_member_savings_cents"] == 7800
    report = validate_success(api.get_savings_report(member["id"], headers=mh))
    assert report["realized_net_cents"] == 7800
    assert report["transferred_cents"] == 0
    assert report["pending_transfer_cents"] == 7800
    assert report["total_fees_cents"] == 4200


def test_savings_report_pending_before_transfer(api):
    """PRD §3.8: "The transferred figure is the sum of `member_net_cents` across the member's entries whose `transfer_status` is `TRANSFERRED".
    PRD §3.8: "The pending-transfer figure is the sum of `member_net_cents` across all of the member's savings ledger entries whose `transfer_status` is `PENDING`."

    Design: Difficulty/dual_variant_calc/lifetime_rollup_vs_savings_report_basis
    """
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    report = validate_success(api.get_savings_report(member["id"], headers=make_member_headers(member["id"])))
    assert report["pending_transfer_cents"] == 7800
    assert report["transferred_cents"] == 0


def test_savings_report_empty_zero_buckets(api):
    """PRD §3.8: "All report figures are exact integer cents."
    PRD §3.1: "The two computed lifetime fields a member carries ... both start at zero".
    PRD §3.8: "Total fees are the realized gross minus the realized net."

    Design: Difficulty/boundary_precision_check/savings_report_empty_ledger_zero_buckets
    """
    member = create_member()
    report = validate_success(api.get_savings_report(member["id"], headers=make_member_headers(member["id"])))
    assert report["realized_gross_cents"] == 0
    assert report["realized_net_cents"] == 0
    assert report["pending_transfer_cents"] == 0
    assert report["transferred_cents"] == 0
    assert report["total_fees_cents"] == 0


def test_success_fee_cap_applied_to_member_net(api):
    """PRD §3.6: "Step three — cap**: the fee is reduced to 20,000 cents if the rounded raw fee exceeds that cap."
    PRD §3.6: "member_net_savings_cents` is computed as the gross savings minus the success fee."

    Design: Difficulty/combinatorial_formula/success_fee_split_tier_then_round_then_cap_order
    """
    member, agent, charge, case = setup_proposed_case(100000, charge_amount_cents=800000, cadence="ANNUAL")
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    # raw fee 700000*0.30=210000, capped to 20000; net 700000-20000.
    assert won["success_fee_cents"] == 20000
    assert won["member_net_savings_cents"] == 680000


def test_dual_variant_negotiation_mid_tier_fee(api):
    """PRD §3.6: "when the gross is at least 10,000 cents but below 50,000 cents the rate is 0.35".
    PRD §3.6: "the raw fee is the gross multiplied by the chosen rate, rounded half-up to whole cents (the rounding happens after the multiplication)."

    Design: Difficulty/dual_variant_calc/success_fee_split_negotiation_vs_refund_basis
    """
    # baseline 60000, agreed 48000 -> gross 12000 (MID 0.35) -> fee 4200, net 7800.
    member, agent, charge, case = setup_proposed_case(48000, charge_amount_cents=5000)
    won = validate_success(api.accept_negotiation(case["id"], headers=make_agent_headers(agent["id"])))
    assert won["gross_annual_savings_cents"] == 12000
    assert won["success_fee_cents"] == 4200
    assert won["member_net_savings_cents"] == 7800


def test_savings_report_empty_total_fees_zero(api):
    """PRD §3.8: "Total fees are the realized gross minus the realized net."
    PRD §3.8: "The pending-transfer figure is the sum of `member_net_cents` across all of the member's savings ledger entries whose `transfer_status` is `PENDING`."

    Design: Difficulty/boundary_precision_check/savings_report_empty_ledger_zero_buckets
    """
    member = create_member()
    report = validate_success(api.get_savings_report(member["id"], headers=make_member_headers(member["id"])))
    assert report["total_fees_cents"] == 0
    assert report["pending_transfer_cents"] == 0


def test_fk_reverse_ledger_by_negotiation_case(api):
    """PRD §3.6: "A `SavingsLedgerEntry` booked from a won negotiation records the owning `member_id`, a `source_type` of `NEGOTIATION`, the `negotiation_case_id` of the source case, and copies the realized amounts: `gross_savings_cents`, `success_fee_cents`, and `member_net_cents` (the member's net, equal to the gross savings minus the success fee)."

    Design: Corner/endpoints/fk_reverse_ledger_by_negotiation_case
    """
    member, agent, charge, case = setup_won_case(offered_annual_cost_cents=48000, charge_amount_cents=5000)
    resp = api.list_ledger_entries(headers=make_member_headers(member["id"]),
                                   params={"negotiation_case_id": case["id"]})
    validate_success(resp)
    body = resp.json()
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["member_net_cents"] == 7800
