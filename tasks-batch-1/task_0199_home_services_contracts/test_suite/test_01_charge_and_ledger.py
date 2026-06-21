"""Visit charge assessment, part-charge rounding, and the customer ledger.

Covers Difficulty queue rules dual_variant_calc & combinatorial_formula (part rounding)
plus the calculations/consistency corner variants that exercise the same ledger math.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    make_technician_headers,
    create_part_usage_payload,
    setup_active_membership_with_tech,
    setup_visit_on_site,
    book_visit,
    drive_visit_to_completed,
    drive_visit_to_on_site,
    complete_n_seasonal_visits,
    get_customer,
    get_membership,
)

ADMIN = TEST_USERS["contract_admin_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
def test_third_seasonal_completion_bills_extra_visit_fee(api):
    """PRD §3.8: "If that ordinal position exceeds the plan's `included_visits_per_year`
    — that is, if the count of prior in-term seasonal completions plus one is strictly
    greater than `included_visits_per_year` — the visit bills the plan's
    `extra_visit_fee_cents`; otherwise it bills 0."
    PRD §3.8: "Whenever the assessed `billable_charge_cents` is greater than 0, that
    amount is accrued onto the customer's `billing_balance_cents`."

    Design: Difficulty/dual_variant_calc/visit_charge_seasonal_overage_vs_within_allowance
    """
    ctx = setup_active_membership_with_tech(
        plan_overrides={"included_visits_per_year": 2, "extra_visit_fee_cents": 8500, "annual_fee_cents": 24000}
    )
    # First two seasonal completions are within the included allowance (bill 0).
    complete_n_seasonal_visits(ctx, 2)

    third = book_visit(
        ctx["membership"], visit_kind="SEASONAL",
        requested_at="2026-07-05T08:00:00Z",
        window_start="2026-07-06T09:00:00Z", window_end="2026-07-06T11:00:00Z",
    )
    completed = drive_visit_to_completed(third["id"], ctx["technician"]["id"])
    assert completed["billable_charge_cents"] == 8500, (
        f"3rd seasonal (prior_completed+1=3 > included 2) should bill 8500, got "
        f"{completed['billable_charge_cents']}"
    )

    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 32500, (
        f"balance = 24000 annual fee + 8500 overage = 32500, got {customer['billing_balance_cents']}"
    )
    membership = get_membership(ctx["membership"]["id"])
    assert membership["visits_consumed"] == 3, f"visits_consumed should be 3, got {membership['visits_consumed']}"


def test_first_two_seasonal_completions_within_allowance_bill_zero(api):
    """PRD §3.8: "If that ordinal position exceeds the plan's `included_visits_per_year`
    — that is, if the count of prior in-term seasonal completions plus one is strictly
    greater than `included_visits_per_year` — the visit bills the plan's
    `extra_visit_fee_cents`; otherwise it bills 0."

    Design: Difficulty/dual_variant_calc/visit_charge_seasonal_overage_vs_within_allowance
    """
    ctx = setup_active_membership_with_tech(
        plan_overrides={"included_visits_per_year": 2, "extra_visit_fee_cents": 8500, "annual_fee_cents": 24000}
    )
    completed = complete_n_seasonal_visits(ctx, 2)
    assert completed[0]["billable_charge_cents"] == 0, "1st seasonal within allowance bills 0"
    assert completed[1]["billable_charge_cents"] == 0, "2nd seasonal within allowance bills 0"

    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 24000, (
        f"balance stays at the 24000 annual fee with no overage, got {customer['billing_balance_cents']}"
    )


def test_warranty_settlement_credits_ledger_by_partial_approved_amount(api):
    """PRD §3.10: "The `APPROVED → SETTLED` transition credits the customer's ledger by
    exactly the `approved_amount_cents` — that amount is subtracted from the customer's
    `billing_balance_cents` — and increments the claim's `version` by one."
    PRD §3.10: "when the authorized amount is a partial amount strictly between 0 and the
    claimed amount, only that partial authorized amount is credited and the difference is
    never credited."

    Design: Difficulty/dual_variant_calc/warranty_settlement_partial_vs_full_credit_on_customer_ledger
    """
    from test_helpers import setup_claim_in_state, get_claim
    ctx = setup_claim_in_state("SETTLED", claimed_amount_cents=50000, approved_amount_cents=30000,
                              plan_overrides={"annual_fee_cents": 24000})
    claim = get_claim(ctx["claim"]["id"])
    assert claim["status"] == "SETTLED"
    assert claim["approved_amount_cents"] == 30000, (
        f"partial approval pins approved_amount_cents at 30000, got {claim['approved_amount_cents']}"
    )
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == -6000, (
        f"balance = 24000 annual fee - 30000 partial credit = -6000, got {customer['billing_balance_cents']}"
    )


def test_warranty_settlement_credits_ledger_by_full_claimed_amount(api):
    """PRD §3.10: "The `APPROVED → SETTLED` transition credits the customer's ledger by
    exactly the `approved_amount_cents` — that amount is subtracted from the customer's
    `billing_balance_cents`."
    PRD §3.10: "When the authorized amount equals the full `claimed_amount_cents`, the
    ledger is credited by the full claimed amount; when the authorized amount is a partial
    amount strictly between 0 and the claimed amount, only that partial authorized amount
    is credited and the difference is never credited."

    Design: Difficulty/dual_variant_calc/warranty_settlement_partial_vs_full_credit_on_customer_ledger
    """
    from test_helpers import setup_claim_in_state, get_claim
    # Approve the full claimed amount (approved == claimed), then settle.
    ctx = setup_claim_in_state("SETTLED", claimed_amount_cents=50000, approved_amount_cents=50000,
                              plan_overrides={"annual_fee_cents": 24000})
    claim = get_claim(ctx["claim"]["id"])
    assert claim["approved_amount_cents"] == 50000, "full approval pins approved == claimed"
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == -26000, (
        f"balance = 24000 annual fee - 50000 full credit = -26000, got {customer['billing_balance_cents']}"
    )


# ===========================================================================
# Difficulty / combinatorial_formula (part-charge round-per-line-then-sum)
# ===========================================================================
def test_part_charges_rounded_per_line_then_summed(api):
    """PRD §3.7: "The system computes the line's `charged_cents` by taking the gross line
    amount — `list_price_cents` multiplied by `quantity` — multiplying it by one minus
    the member plan's `parts_discount_pct`, and rounding that discounted amount half-up
    to whole cents."
    PRD §3.7: "Rounding is pinned at the line level: each part usage's `charged_cents` is
    rounded independently, and a membership's parts subtotal is the sum of the
    already-rounded line charges, never a single rounding of an un-rounded sum."

    Design: Difficulty/combinatorial_formula/part_charge_round_per_line_then_sum_order_pinned
    """
    ctx = setup_visit_on_site(plan_overrides={"parts_discount_pct": 0.10, "annual_fee_cents": 24000})
    visit_id = ctx["visit"]["id"]
    tech_headers = make_technician_headers(ctx["technician"]["id"])

    # Line 1: 125 * 1 * 0.90 = 112.5 -> round-half-up -> 113
    p1 = validate_success(
        api.post_part_usage(visit_id, create_part_usage_payload("Capacitor", 1, 125), tech_headers), 201
    )
    assert p1["charged_cents"] == 113, f"125@10% = 112.5 -> 113, got {p1['charged_cents']}"

    # Line 2: 135 * 1 * 0.90 = 121.5 -> round-half-up -> 122
    p2 = validate_success(
        api.post_part_usage(visit_id, create_part_usage_payload("Contactor", 1, 135), tech_headers), 201
    )
    assert p2["charged_cents"] == 122, f"135@10% = 121.5 -> 122, got {p2['charged_cents']}"

    customer = get_customer(ctx["customer"]["id"])
    # 24000 + 113 + 122 = 24235 (round-then-sum). sum-then-round would be 24234.
    assert customer["billing_balance_cents"] == 24235, (
        f"balance = 24000 + 113 + 122 = 24235 (round-per-line-then-sum), got "
        f"{customer['billing_balance_cents']}"
    )


def test_single_part_line_charge_is_round_half_up_of_discounted_amount(api):
    """PRD §3.7: "The system computes the line's `charged_cents` by taking the gross line
    amount — `list_price_cents` multiplied by `quantity` — multiplying it by one minus the
    member plan's `parts_discount_pct`, and rounding that discounted amount half-up to
    whole cents."

    Design: Difficulty/combinatorial_formula/part_charge_round_per_line_then_sum_order_pinned
    """
    ctx = setup_visit_on_site(plan_overrides={"parts_discount_pct": 0.10, "annual_fee_cents": 24000})
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    # 125 * 1 * 0.90 = 112.5; round-half-up -> 113 (not 112).
    p = validate_success(
        api.post_part_usage(ctx["visit"]["id"], create_part_usage_payload("Capacitor", 1, 125), tech_headers), 201
    )
    assert p["charged_cents"] == 113, (
        f"112.5 must round half-up to 113, got {p['charged_cents']}"
    )


def test_part_charge_no_discount_is_exact_price_times_quantity(api):
    """PRD §3.7: "When the plan's `parts_discount_pct` is 0, the charge equals
    `list_price_cents` times `quantity` exactly."
    PRD §3.7: "On posting, the computed `charged_cents` is accrued onto the customer's
    `billing_balance_cents`."

    Design: Corner/calculations/part_charge_no_discount_variant_exact
    """
    ctx = setup_visit_on_site(
        plan_overrides={"tier": "BASIC", "parts_discount_pct": 0.0, "annual_fee_cents": 12000,
                        "included_visits_per_year": 1, "extra_visit_fee_cents": 9000, "sla_response_hours": 24}
    )
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    p = validate_success(
        api.post_part_usage(ctx["visit"]["id"], create_part_usage_payload("Filter", 2, 500), tech_headers), 201
    )
    assert p["charged_cents"] == 1000, f"500*2 with 0 discount = 1000, got {p['charged_cents']}"
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 13000, (
        f"balance = 12000 annual fee + 1000 part = 13000, got {customer['billing_balance_cents']}"
    )


def test_priority_visit_always_bills_extra_fee_even_as_first_visit(api):
    """PRD §3.8: "A `PRIORITY` visit is always treated as out-of-plan and always bills
    the plan's `extra_visit_fee_cents` regardless of how many visits the term has already
    consumed."

    Design: Corner/calculations/priority_visit_always_bills_extra_fee_variant
    """
    ctx = setup_active_membership_with_tech(
        plan_overrides={"included_visits_per_year": 2, "extra_visit_fee_cents": 8500, "annual_fee_cents": 24000}
    )
    visit = book_visit(
        ctx["membership"], visit_kind="PRIORITY",
        requested_at="2026-07-01T09:00:00Z",
        window_start="2026-07-01T11:00:00Z", window_end="2026-07-01T13:00:00Z",
    )
    completed = drive_visit_to_completed(visit["id"], ctx["technician"]["id"])
    assert completed["billable_charge_cents"] == 8500, (
        f"PRIORITY out-of-plan always bills 8500 even as the term's first visit, got "
        f"{completed['billable_charge_cents']}"
    )
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 32500, (
        f"balance = 24000 annual fee + 8500 priority fee = 32500, got {customer['billing_balance_cents']}"
    )


def test_completion_response_and_reads_reflect_charge_and_consumption_immediately(api):
    """PRD §3.8: "Whenever the assessed `billable_charge_cents` is greater than 0, that
    amount is accrued onto the customer's `billing_balance_cents`."
    PRD §3.8: "Second, the membership's `visits_consumed` becomes the recomputed count of
    the membership's visits that have reached `COMPLETED` within the current term window."

    Design: Corner/consistency_model/complete_visit_immediately_reflects_balance_and_consumption
    """
    ctx = setup_active_membership_with_tech(
        plan_overrides={"included_visits_per_year": 2, "extra_visit_fee_cents": 8500, "annual_fee_cents": 24000}
    )
    complete_n_seasonal_visits(ctx, 2)
    third = book_visit(
        ctx["membership"], visit_kind="SEASONAL",
        requested_at="2026-07-05T08:00:00Z",
        window_start="2026-07-06T09:00:00Z", window_end="2026-07-06T11:00:00Z",
    )
    completed = drive_visit_to_completed(third["id"], ctx["technician"]["id"])
    # The same completion response carries the charge.
    assert completed["billable_charge_cents"] == 8500

    # An immediate read reflects balance and consumption with no lag.
    membership = get_membership(ctx["membership"]["id"])
    assert membership["visits_consumed"] == 3, f"visits_consumed should be 3, got {membership['visits_consumed']}"
    customer = get_customer(ctx["customer"]["id"])
    assert customer["billing_balance_cents"] == 32500, (
        f"immediate balance = 24000 + 8500 = 32500, got {customer['billing_balance_cents']}"
    )
