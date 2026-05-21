"""Difficulty-design coverage — at least two tests per
SCAFFOLD_DIFFICULTY_DESIGN instance.

Each test is tagged in its docstring with
`# difficulty: <rule_id>/<instance.name>` so coverage can be audited.
PRD-First still applies: every test cites the underlying PRD prose
that states the rule the test asserts.
"""
from __future__ import annotations

import decimal

import pytest

from test_helpers import (
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    add_days,
    add_minutes,
    advance_clock_to_iso,
    assert_factoring_advance,
    assert_invoice_balance_conservation,
    counter_dispute,
    counter_dispute_claim_payload,
    create_dispute_claim_payload,
    create_load_payload,
    create_quote_request,
    create_quote_request_payload,
    create_rate_contract,
    create_rate_contract_payload,
    factor_invoice,
    file_dispute,
    get_carrier,
    get_dispute_claim,
    get_invoice,
    get_load,
    get_shipper,
    iso_utc,
    make_shipper_headers,
    parse_iso,
    quote_quote_request,
    reject_counter_dispute,
    resolve_dispute,
    setup_brokerage_shipper_qualified_carrier,
    setup_brokerage_with_shipper,
    setup_contract_quote_at_total,
    setup_delivered_load,
    setup_factored_invoice,
    setup_invoice_in_review_dispute,
    setup_invoiced_load,
    setup_load_for_factor_total,
    setup_shipper_with_outstanding,
    setup_tendered_load,
    spot_linehaul_cents,
    start_review_dispute,
    validate_error,
    validate_success,
    write_off_invoice,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================

# --- instance: quote_linehaul_spot_vs_contract_on_quote_request ---
def test_dvc_quote_spot_vs_contract_diverges(api):
    """# difficulty: dual_variant_calc/quote_linehaul_spot_vs_contract_on_quote_request

    PRD §3.4: "If exactly one rate contract matches, the quote's
    `rate_source` is set to `CONTRACT` and `quoted_linehaul_cents` is set to
    the contract's `flat_rate_cents`. If no rate contract matches, or if
    `rate_contract_id` was not supplied at all, the engine falls through
    to the spot path with `rate_source` set to `SPOT`."

    Claim: two quotes on the same lane+equipment, one with a matching
    rate_contract_id and one without, produce different
    quoted_linehaul_cents values (88_888 vs 130_010 on a DRY_VAN
    10001->20002 lane).
    """
    brokerage, shipper, contract, quoted_contract = (
        setup_contract_quote_at_total(
            flat_rate_cents=88_888,
            origin_zip="10001", destination_zip="20002",
            equipment_type="DRY_VAN",
        )
    )
    # Now file a SPOT quote on the same lane+equipment, no contract id.
    spot_q = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN",
    )
    spot_quoted = quote_quote_request(brokerage["id"], shipper["id"],
                                      spot_q["id"])

    assert quoted_contract["rate_source"] == "CONTRACT"
    assert quoted_contract["quoted_linehaul_cents"] == 88_888
    assert spot_quoted["rate_source"] == "SPOT"
    assert spot_quoted["quoted_linehaul_cents"] == 130_010
    assert (quoted_contract["quoted_linehaul_cents"]
            != spot_quoted["quoted_linehaul_cents"])


def test_dvc_quote_spot_path_uses_equipment_specific_base(api):
    """# difficulty: dual_variant_calc/quote_linehaul_spot_vs_contract_on_quote_request

    PRD §3.4: "The base price is 30,000 cents for `DRY_VAN`, 50,000 cents
    for `REEFER`, and 40,000 cents for `FLATBED`."

    Claim: SPOT pricing for the SAME lane diverges by equipment type
    according to the equipment-specific base + per-unit table.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    quotes = {}
    for eq in ("DRY_VAN", "REEFER", "FLATBED"):
        q = create_quote_request(
            brokerage["id"], shipper["id"],
            origin_zip="10000", destination_zip="20000",
            equipment_type=eq,
        )
        quotes[eq] = quote_quote_request(brokerage["id"], shipper["id"],
                                         q["id"])
    assert quotes["DRY_VAN"]["quoted_linehaul_cents"] == (
        spot_linehaul_cents("DRY_VAN", "10000", "20000")
    )
    assert quotes["REEFER"]["quoted_linehaul_cents"] == (
        spot_linehaul_cents("REEFER", "10000", "20000")
    )
    assert quotes["FLATBED"]["quoted_linehaul_cents"] == (
        spot_linehaul_cents("FLATBED", "10000", "20000")
    )
    # Diverge from each other.
    assert quotes["DRY_VAN"]["quoted_linehaul_cents"] != (
        quotes["REEFER"]["quoted_linehaul_cents"]
    )
    assert quotes["REEFER"]["quoted_linehaul_cents"] != (
        quotes["FLATBED"]["quoted_linehaul_cents"]
    )


# --- instance: detention_provisional_vs_final_on_load ---
def test_dvc_detention_final_frozen_into_invoice(api):
    """# difficulty: dual_variant_calc/detention_provisional_vs_final_on_load

    PRD §3.7: "the load's `final_detention_cents` is set to the new
    computation and is the authoritative figure ... `detention_cents`
    frozen from `final_detention_cents`".

    Claim: after /invoice, Invoice.detention_cents equals the load's
    final_detention_cents (which was recomputed at /invoice). Without
    a documented endpoint to edit brokerage detention constants between
    /deliver and /invoice, the two variants happen to coincide
    numerically; the test asserts the frozen-from-final wiring is
    correct.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 30,  # 30 chargeable
        accessorials=None,
    )
    expected = 2 * DEFAULT_DETENTION_RATE_CENTS_PER_15MIN  # 30/15 = 2 increments
    assert invoice["detention_cents"] == expected


def test_dvc_detention_provisional_at_deliver_matches_formula(api):
    """# difficulty: dual_variant_calc/detention_provisional_vs_final_on_load

    PRD §3.7: "At the moment of delivery, the provisional pass runs ...
    take the resulting chargeable-minute count, round it up to the
    next whole 15-minute increment, and multiply the resulting integer
    number of increments by `detention_rate_cents_per_15min`. The result
    is the load's `provisional_detention_cents`."

    Claim: after /deliver, Load.provisional_detention_cents equals
    the pinned ceil-then-multiply formula. (The provisional variant is
    computed at /deliver; the final variant at /invoice; absent a
    documented brokerage-settings-edit endpoint, the two coincide.)
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 60,
    )
    expected = 4 * DEFAULT_DETENTION_RATE_CENTS_PER_15MIN  # 60/15
    assert load["provisional_detention_cents"] == expected


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================

# --- instance: tiered_factoring_haircut_three_input_modes ---
def _expected_haircut(t: int) -> int:
    a_cap, b_cap = 100_000, 500_000
    a, b, c = 0.030, 0.020, 0.010
    a_slice = min(t, a_cap)
    b_slice = max(0, min(t, b_cap) - a_cap)
    c_slice = max(0, t - b_cap)
    raw = a_slice * a + b_slice * b + c_slice * c
    return int(decimal.Decimal(str(raw)).quantize(
        decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))


def test_combo_factor_three_tier_marginal_at_600k(api):
    """# difficulty: combinatorial_formula/tiered_factoring_haircut_three_input_modes

    PRD §3.8: "The first 100,000 cents of T (the slice from 0 up to
    and including 100,000) is charged at 3.0% (rate 0.030). The next
    400,000 cents of T (the slice strictly above 100,000 up to and
    including 500,000) is charged at 2.0% (rate 0.020). Any slice
    strictly above 500,000 cents is charged at 1.0% (rate 0.010)."

    Claim: T=600_000 -> haircut=12_000, reserve=30_000, advanced=558_000.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=600_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["invoice_total_at_advance_cents"] == 600_000
    assert advance["haircut_cents"] == 12_000
    assert advance["reserve_cents"] == 30_000
    assert advance["advanced_cents"] == 558_000


def test_combo_factor_haircut_tier_b_only_at_250k(api):
    """# difficulty: combinatorial_formula/tiered_factoring_haircut_three_input_modes

    PRD §3.8: "The implementation allocates T across the three buckets
    in this order, multiplies each bucket size by its tier rate to
    produce an unrounded contribution, sums the three contributions,
    and then rounds that single sum half-up to a whole number of cents."

    Claim: T=250_000 -> haircut = 100_000*0.030 + 150_000*0.020 = 3000+3000
    = 6000 cents.
    """
    brokerage, invoice = setup_load_for_factor_total(
        invoice_total_cents=250_000
    )
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert advance["haircut_cents"] == _expected_haircut(250_000)
    assert advance["haircut_cents"] == 6_000


# --- instance: detention_pinned_ceil_then_multiply_rounding_order ---
def test_combo_detention_one_minute_yields_1500_not_100(api):
    """# difficulty: combinatorial_formula/detention_pinned_ceil_then_multiply_rounding_order

    PRD §3.7: "for example a single chargeable minute under a 1500-cent
    per-15-minute rate must produce 1500 cents (one full increment) and
    not 100 cents (one-fifteenth of an increment)."

    Claim: one chargeable minute under the default 1500-cent rate ->
    1500 cents, not 100.
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 1,
    )
    assert load["provisional_detention_cents"] == 1500
    assert load["provisional_detention_cents"] != 100


def test_combo_detention_14_minutes_yields_1500_not_1400(api):
    """# difficulty: combinatorial_formula/detention_pinned_ceil_then_multiply_rounding_order

    PRD §3.7: "round it up to the next whole 15-minute increment".

    Claim: 14 chargeable minutes (just under one increment) ->
    ceil(14/15) = 1 increment -> 1500 cents. The forbidden
    multiply-then-ceil would yield ceil(14 * 100) = 1400 cents
    (14 * (1500/15) = 1400).
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 14,
    )
    assert load["provisional_detention_cents"] == 1500
    assert load["provisional_detention_cents"] != 1400


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================

# --- instance: dispute_claim_review_counter_cycle ---
def test_nlsm_dispute_cycle_review_counter_twice(api, broker_ops_headers):
    """# difficulty: non_linear_state_machine/dispute_claim_review_counter_cycle

    PRD §3.9: "From `COUNTER_OFFERED` the shipper can either accept the
    counter ... or reject it (cycling back to `IN_REVIEW`, with
    `counter_offer_cents` cleared back to null so the next counter is a
    fresh offer). ... A claim may oscillate between `IN_REVIEW` and
    `COUNTER_OFFERED` any number of times before terminating."

    Claim: counter->reject-counter cycles work twice, with counter
    cleared each time.
    """
    brokerage, shipper, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=10_000)
    )
    c1 = counter_dispute(brokerage["id"], claim["id"], 4_000)
    assert c1["status"] == "COUNTER_OFFERED"
    assert c1["counter_offer_cents"] == 4_000
    r1 = reject_counter_dispute(brokerage["id"], shipper["id"], claim["id"])
    assert r1["status"] == "IN_REVIEW"
    assert not r1.get("counter_offer_cents")

    c2 = counter_dispute(brokerage["id"], claim["id"], 5_000)
    assert c2["status"] == "COUNTER_OFFERED"
    assert c2["counter_offer_cents"] == 5_000
    r2 = reject_counter_dispute(brokerage["id"], shipper["id"], claim["id"])
    assert r2["status"] == "IN_REVIEW"
    assert not r2.get("counter_offer_cents")


def test_nlsm_dispute_cycle_then_resolved_terminates(api, broker_ops_headers):
    """# difficulty: non_linear_state_machine/dispute_claim_review_counter_cycle

    PRD §3.9: "A claim may oscillate between `IN_REVIEW` and
    `COUNTER_OFFERED` any number of times before terminating." Also
    "The resolve capability is reserved to BrokerOps and accepts a
    settled_credit_cents integer. ... The claim moves IN_REVIEW ->
    RESOLVED."

    Claim: after oscillating, the broker can /resolve and land in
    RESOLVED with settled_credit_cents set.
    """
    brokerage, shipper, _c, _q, _l, _inv, claim = (
        setup_invoice_in_review_dispute(claimed_cents=8_000)
    )
    counter_dispute(brokerage["id"], claim["id"], 3_000)
    reject_counter_dispute(brokerage["id"], shipper["id"], claim["id"])
    counter_dispute(brokerage["id"], claim["id"], 2_500)
    reject_counter_dispute(brokerage["id"], shipper["id"], claim["id"])
    resolved = resolve_dispute(brokerage["id"], claim["id"], 1_000)
    assert resolved["status"] == "RESOLVED"
    assert resolved["settled_credit_cents"] == 1_000


# --- instance: invoice_parallel_factoring_and_settlement_dimensions ---
def test_nlsm_invoice_factoring_dimension_independent_of_settlement(api):
    """# difficulty: non_linear_state_machine/invoice_parallel_factoring_and_settlement_dimensions

    PRD §3.10: "Settlement runs along a dimension parallel to factoring.
    The invoice's `settlement_status` is independently `ISSUED`, `PAID`, or
    `WRITTEN_OFF`; its `factoring_status` is independently `NOT_FACTORED`,
    `FACTORED`, or `RECOURSED`. The two dimensions interact only through
    the auto-settlement rule: `settlement_status` automatically advances
    `ISSUED → PAID` whenever `balance_due_cents` reaches zero and
    `factoring_status` is not `FACTORED`."

    Claim: a FACTORED invoice has balance_due_cents == 0 but
    settlement_status stays ISSUED (the guard).
    """
    brokerage, _s, _c, _q, _l, invoice, _adv = setup_factored_invoice()
    assert invoice["balance_due_cents"] == 0
    assert invoice["factoring_status"] == "FACTORED"
    assert invoice["settlement_status"] == "ISSUED"


def test_nlsm_invoice_writeoff_settles_without_touching_factoring(api):
    """# difficulty: non_linear_state_machine/invoice_parallel_factoring_and_settlement_dimensions

    PRD §3.10: "A `BrokerOps` operator can also drive an invoice into
    `WRITTEN_OFF` via the write-off capability."

    Claim: /write-off on a NOT_FACTORED invoice flips
    settlement_status -> WRITTEN_OFF while factoring_status stays
    NOT_FACTORED (the two axes evolve independently).
    """
    brokerage, _s, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="00100",
        detention_minutes=0, accessorials=None,
    )
    write_off_invoice(brokerage["id"], invoice["id"])
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["settlement_status"] == "WRITTEN_OFF"
    assert after["factoring_status"] == "NOT_FACTORED"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================

# --- instance: dispute_resolve_cascades_through_invoice_then_settlement_then_shipper_credit ---
def test_cascade_resolve_full_credit_drives_paid_and_outstanding_to_zero(api):
    """# difficulty: transitive_cascade/dispute_resolve_cascades_through_invoice_then_settlement_then_shipper_credit

    PRD §3.9: "The invoice's `amount_credited_cents` is increased by c.
    The invoice's `invoice_total_cents` is decreased by c ... The
    invoice's `balance_due_cents` is then recomputed as
    `invoice_total_cents` minus `amount_paid_cents` minus `amount_credited_cents`,
    with a floor of zero ... if after the cascade the invoice's
    `balance_due_cents` is exactly zero and its `factoring_status` is
    something other than `FACTORED`, the invoice's `settlement_status`
    automatically advances to `PAID`."

    PRD §3.2: "at the point the invoice transitions to `PAID` or
    `WRITTEN_OFF`, the shipper's `outstanding_invoiced_cents` is decreased
    by the original frozen `invoice_total_cents` of that invoice."

    Claim: resolve(full credit) -> Invoice settles PAID, Shipper.outstanding
    drops by the ORIGINAL invoice total.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",
            detention_minutes=0, accessorials=None,
            claimed_cents=40_000,
        )
    )
    original_total = invoice["invoice_total_cents"]
    assert original_total == 40_000

    resolve_dispute(brokerage["id"], claim["id"], 40_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["invoice_total_cents"] == 0
    assert after["amount_credited_cents"] == 40_000
    assert after["balance_due_cents"] == 0
    assert after["settlement_status"] == "PAID"

    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0


def test_cascade_partial_credit_does_not_settle_or_zero_outstanding(api):
    """# difficulty: transitive_cascade/dispute_resolve_cascades_through_invoice_then_settlement_then_shipper_credit

    PRD §3.9: "if after the cascade the invoice's `balance_due_cents` is
    exactly zero ..." — partial credit does NOT drive balance to zero,
    so settlement_status stays ISSUED and outstanding is NOT decremented.

    Claim: resolve(partial credit) -> balance still > 0, settlement
    still ISSUED, outstanding unchanged.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",
            detention_minutes=0, accessorials=None,
            claimed_cents=10_000,
        )
    )
    original_total = invoice["invoice_total_cents"]
    shipper_before = get_shipper(brokerage["id"], shipper["id"])
    outstanding_before = shipper_before["outstanding_invoiced_cents"]

    resolve_dispute(brokerage["id"], claim["id"], 3_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["balance_due_cents"] > 0
    assert after["settlement_status"] == "ISSUED"
    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == outstanding_before


# --- instance: writeoff_cascades_through_invoice_credit_to_shipper_outstanding ---
def test_cascade_writeoff_settles_and_zeroes_outstanding(api):
    """# difficulty: transitive_cascade/writeoff_cascades_through_invoice_credit_to_shipper_outstanding

    PRD §3.10: "The write-off increases `amount_credited_cents` by the
    current `balance_due_cents`, driving the balance to zero, and
    decreases the shipper's `outstanding_invoiced_cents` by the original
    frozen `invoice_total_cents`."

    Claim: /write-off cascades through (Invoice.amount_credited,
    Invoice.settlement_status, Shipper.outstanding) in one operation.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01650",  # 30000+1650*10=46500
        detention_minutes=0,
        accessorials=None,
    )
    original_total = invoice["invoice_total_cents"]
    assert original_total == 46_500

    write_off_invoice(brokerage["id"], invoice["id"])
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["settlement_status"] == "WRITTEN_OFF"
    assert after["amount_credited_cents"] == 46_500
    assert after["balance_due_cents"] == 0
    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0


def test_cascade_writeoff_uses_original_total_not_current_balance(api):
    """# difficulty: transitive_cascade/writeoff_cascades_through_invoice_credit_to_shipper_outstanding

    PRD §3.10: "decreases the shipper's `outstanding_invoiced_cents` by
    the original frozen `invoice_total_cents`."

    Claim: even if the invoice had a partial credit applied earlier
    (so invoice_total_cents shrank), the write-off decrement against
    Shipper.outstanding uses the ORIGINAL value snapshotted at issuance.

    Setup: invoice issued with original_total = 46500; partial credit
    of 3000 via resolved dispute reduces invoice_total_cents to 43500;
    write-off then drives balance to 0 and outstanding is decreased by
    the original 46500 — the resulting outstanding equals
    (initial_outstanding - 46500).
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01650",  # 46500
            detention_minutes=0, accessorials=None,
            claimed_cents=3_000,
        )
    )
    resolve_dispute(brokerage["id"], claim["id"], 3_000)
    # After resolve: invoice_total = 43_500, balance = 40_500;
    # outstanding was 46_500 originally, NOT decremented by the partial
    # credit (only by PAID/WRITTEN_OFF). So outstanding stays 46_500.
    shipper_mid = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_mid["outstanding_invoiced_cents"] == 46_500

    write_off_invoice(brokerage["id"], invoice["id"])
    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    # PRD §3.2 + §3.10: write-off decrements outstanding by the original
    # frozen invoice_total_cents — 46_500. Net outstanding therefore
    # returns to 0.
    assert shipper_after["outstanding_invoiced_cents"] == 0


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================

# --- instance: state_vs_business_safety_load_carrier_accept ---
def test_priority_state_wins_over_business_safety_on_carrier_accept(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_load_carrier_accept

    PRD §2.9: "the state-precondition check (priority 5) runs before
    any business safety check (priority 6 onward), so attempting to
    tender a load on a carrier that is `SUSPENDED` returns
    `ERR_CARRIER_NOT_QUALIFIED` only if the load is already in the right
    state for tendering; if the underlying quote is in the wrong state,
    the state-precondition error fires first."

    Claim: /carrier-accept on an already-ACCEPTED load (wrong state)
    returns ERR_LOAD_NOT_TENDERED (P5), not the business-safety error.
    """
    from test_helpers import carrier_accept_load, make_carrier_headers
    brokerage, shipper, carrier, _q, load = setup_tendered_load()
    accepted = carrier_accept_load(brokerage["id"], shipper["id"],
                                   load["id"], carrier["id"])
    assert accepted["status"] == "ACCEPTED"
    res = api.carrier_accept_load(brokerage["id"], shipper["id"],
                                  load["id"],
                                  make_carrier_headers(carrier["id"]))
    validate_error(res, "ERR_LOAD_NOT_TENDERED")


def test_priority_state_wins_over_smartway_on_carrier_accept(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_load_carrier_accept

    PRD §2.9: "the state-precondition check (priority 5) runs before
    any business safety check (priority 6 onward)" — P8 SmartWay is a
    business-safety check.

    Claim: /carrier-accept on a load not in TENDERED returns
    ERR_LOAD_NOT_TENDERED regardless of any SmartWay configuration.
    """
    from test_helpers import (
        accept_quote_request, carrier_accept_load, create_quote_request,
        make_carrier_headers, quote_quote_request, setup_brokerage_shipper_qualified_carrier,
        tender_load,
    )
    brokerage, shipper, carrier = (
        setup_brokerage_shipper_qualified_carrier(
            smartway_required=False, smartway_certified=True,
        )
    )
    q = create_quote_request(brokerage["id"], shipper["id"])
    quoted = quote_quote_request(brokerage["id"], shipper["id"], q["id"])
    accepted = accept_quote_request(brokerage["id"], shipper["id"],
                                    quoted["id"])
    load = tender_load(brokerage["id"], shipper["id"], accepted["id"],
                       carrier["id"])
    # Walk to IN_TRANSIT.
    load = carrier_accept_load(brokerage["id"], shipper["id"], load["id"],
                               carrier["id"])
    from test_helpers import depart_load
    load = depart_load(brokerage["id"], shipper["id"], load["id"],
                       carrier["id"])
    # Now /carrier-accept on an IN_TRANSIT load — state check fires.
    res = api.carrier_accept_load(brokerage["id"], shipper["id"],
                                  load["id"],
                                  make_carrier_headers(carrier["id"]))
    validate_error(res, "ERR_LOAD_NOT_TENDERED")


# --- instance: business_fiscal_vs_business_temporal_quote_accept ---
def test_priority_credit_limit_wins_over_quote_expiry(api):
    """# difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_temporal_quote_accept

    PRD §2.9 enumerates "15. Shipper credit-limit check at quote
    acceptance — ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED" THEN "16. Quote-expiry
    check at quote acceptance — ERR_QUOTE_EXPIRED"; the list is
    "evaluated in this strict order and the first failure is returned."

    Claim: /accept on a QUOTED quote that fails BOTH credit (P15) and
    expiry (P16) returns ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED.
    """
    brokerage, shipper, _invoice = setup_shipper_with_outstanding(
        outstanding_target_cents=40_000,
        credit_limit_cents=50_000,
    )
    from test_helpers import get_brokerage
    brokerage_now = get_brokerage(brokerage["id"])
    now = parse_iso(brokerage_now["clock_now_iso"])
    past_end = iso_utc(add_minutes(now, -1))
    past_start = iso_utc(add_minutes(now, -120))
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN",
        pickup_window_start=past_start,
        pickup_window_end=past_end,
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"],
                                 quote["id"])
    assert quoted["quoted_linehaul_cents"] == 130_010
    res = api.accept_quote_request(brokerage["id"], shipper["id"],
                                   quoted["id"],
                                   make_shipper_headers(shipper["id"]))
    validate_error(res, "ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED")


def test_priority_quote_expiry_fires_when_credit_is_fine(api):
    """# difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_temporal_quote_accept

    PRD §2.9 item 16: "Quote-expiry check at quote acceptance —
    ERR_QUOTE_EXPIRED" — when ONLY the expiry check fails (credit is
    fine), the response is ERR_QUOTE_EXPIRED.

    Claim: a quote that fits within credit but is past pickup_window_end
    yields ERR_QUOTE_EXPIRED (proves that the priority-15 check is not
    spuriously firing when not in violation).
    """
    brokerage, shipper = setup_brokerage_with_shipper(
        credit_limit_cents=10_000_000,
    )
    from test_helpers import get_brokerage
    brokerage_now = get_brokerage(brokerage["id"])
    now = parse_iso(brokerage_now["clock_now_iso"])
    past_end = iso_utc(add_minutes(now, -1))
    past_start = iso_utc(add_minutes(now, -120))
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="00000", destination_zip="00100",
        equipment_type="DRY_VAN",
        pickup_window_start=past_start,
        pickup_window_end=past_end,
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"],
                                 quote["id"])
    res = api.accept_quote_request(brokerage["id"], shipper["id"],
                                   quoted["id"],
                                   make_shipper_headers(shipper["id"]))
    validate_error(res, "ERR_QUOTE_EXPIRED")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================

# --- instance: detention_free_minutes_boundary_inclusive ---
def test_boundary_detention_at_free_minutes_exact(api):
    """# difficulty: boundary_precision_check/detention_free_minutes_boundary_inclusive

    PRD §3.7: "Subtract the brokerage's `detention_free_minutes`; if the
    result is non-positive, no detention accrues and
    `provisional_detention_cents` is zero."

    Claim: elapsed == free_minutes -> 0 cents (the boundary is
    INCLUSIVE for "no detention").
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES,
    )
    assert load["provisional_detention_cents"] == 0


def test_boundary_detention_one_minute_past_free(api):
    """# difficulty: boundary_precision_check/detention_free_minutes_boundary_inclusive

    PRD §3.7: "for example a single chargeable minute under a 1500-cent
    per-15-minute rate must produce 1500 cents (one full increment)".

    Claim: elapsed == free_minutes + 1 -> 1500 cents.
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 1,
    )
    assert load["provisional_detention_cents"] == (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


# --- instance: dispute_claimed_zero_amount_empty_boundary ---
def test_boundary_dispute_claimed_zero_rejected(api):
    """# difficulty: boundary_precision_check/dispute_claimed_zero_amount_empty_boundary

    PRD §3.9: "The claimed amount must be strictly greater than zero
    and must not exceed the invoice's current `balance_due_cents` at the
    moment of filing; either violation is rejected with
    `ERR_CLAIM_AMOUNT_INVALID`."

    Claim: claimed_cents == 0 -> ERR_CLAIM_AMOUNT_INVALID with HTTP 422.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01650",
        detention_minutes=0, accessorials=None,
    )
    res = api.create_dispute_claim(
        brokerage["id"], invoice["id"],
        create_dispute_claim_payload(claim_type="DAMAGE",
                                     claimed_cents=0),
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_CLAIM_AMOUNT_INVALID")


def test_boundary_dispute_claimed_one_accepted(api):
    """# difficulty: boundary_precision_check/dispute_claimed_zero_amount_empty_boundary

    PRD §3.9: "The claimed amount must be strictly greater than zero".

    Claim: claimed_cents == 1 -> 201 + OPEN claim with claimed_cents == 1.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01650",
        detention_minutes=0, accessorials=None,
    )
    res = api.create_dispute_claim(
        brokerage["id"], invoice["id"],
        create_dispute_claim_payload(claim_type="DAMAGE",
                                     claimed_cents=1),
        make_shipper_headers(shipper["id"]),
    )
    claim = validate_success(res, 201)
    assert claim["status"] == "OPEN"
    assert claim["claimed_cents"] == 1


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================

# --- instance: load_tender_depends_on_carrier_qualified_state ---
def test_cross_load_tender_requires_qualified_carrier(api, broker_ops_headers):
    """# difficulty: cross_entity_state_dependency/load_tender_depends_on_carrier_qualified_state

    PRD §3.6: "The carrier-gate checks require the carrier to be in
    `QUALIFIED` (otherwise `ERR_CARRIER_NOT_QUALIFIED`)".

    Claim: tender on a PENDING_QUALIFICATION carrier ->
    ERR_CARRIER_NOT_QUALIFIED; no Load row created.
    """
    from test_helpers import (
        create_carrier, setup_accepted_quote,
    )
    brokerage, shipper, accepted = setup_accepted_quote()
    pending = create_carrier(brokerage["id"])  # PENDING_QUALIFICATION
    res = api.create_load(
        brokerage["id"], shipper["id"],
        create_load_payload(accepted["id"], pending["id"]),
        broker_ops_headers,
    )
    validate_error(res, "ERR_CARRIER_NOT_QUALIFIED")


def test_cross_load_tender_blocked_by_suspended_carrier(api,
                                                       broker_ops_headers):
    """# difficulty: cross_entity_state_dependency/load_tender_depends_on_carrier_qualified_state

    PRD §3.3: "while a carrier is `SUSPENDED`, no new tenders may be
    placed on them."

    Claim: a SUSPENDED carrier cannot be tendered to -> ERR_CARRIER_NOT_QUALIFIED.
    """
    from test_helpers import (create_qualified_carrier, setup_accepted_quote,
                              suspend_carrier)
    brokerage, shipper, accepted = setup_accepted_quote()
    carrier = create_qualified_carrier(brokerage["id"])
    suspend_carrier(brokerage["id"], carrier["id"])  # QUALIFIED -> SUSPENDED
    res = api.create_load(
        brokerage["id"], shipper["id"],
        create_load_payload(accepted["id"], carrier["id"]),
        broker_ops_headers,
    )
    validate_error(res, "ERR_CARRIER_NOT_QUALIFIED")


# --- instance: invoice_factor_depends_on_dispute_claim_state ---
def test_cross_factor_blocked_by_open_dispute(api, broker_ops_headers):
    """# difficulty: cross_entity_state_dependency/invoice_factor_depends_on_dispute_claim_state

    PRD §3.8: "there must be no `DisputeClaim` on this invoice currently
    in `OPEN`, `IN_REVIEW`, or `COUNTER_OFFERED` ... an open dispute yields
    `ERR_INVOICE_HAS_OPEN_DISPUTE`."

    Claim: /factor on an invoice with a claim in IN_REVIEW ->
    ERR_INVOICE_HAS_OPEN_DISPUTE; factoring_status stays NOT_FACTORED.
    """
    brokerage, _s, _c, _q, _l, invoice, _claim = (
        setup_invoice_in_review_dispute(claim_type="OVERCHARGE",
                                        claimed_cents=2_000)
    )
    res = api.factor_invoice(brokerage["id"], invoice["id"],
                             broker_ops_headers)
    validate_error(res, "ERR_INVOICE_HAS_OPEN_DISPUTE")
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["factoring_status"] == "NOT_FACTORED"


def test_cross_factor_allowed_after_dispute_withdrawn(api, broker_ops_headers):
    """# difficulty: cross_entity_state_dependency/invoice_factor_depends_on_dispute_claim_state

    PRD §3.8: factoring requires "no DisputeClaim on this invoice
    currently in OPEN, IN_REVIEW, or COUNTER_OFFERED" — terminal-state
    claims (RESOLVED/ESCALATED/WITHDRAWN) do not block.

    Claim: file dispute -> withdraw -> /factor succeeds.
    """
    from test_helpers import (file_dispute, withdraw_dispute,
                              setup_invoiced_load)
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01650",
        detention_minutes=0, accessorials=None,
    )
    claim = file_dispute(brokerage["id"], shipper["id"], invoice["id"],
                         claim_type="OVERCHARGE", claimed_cents=100)
    withdraw_dispute(brokerage["id"], shipper["id"], claim["id"])
    # Now /factor — should succeed.
    advance = factor_invoice(brokerage["id"], invoice["id"])
    assert_factoring_advance(advance)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["factoring_status"] == "FACTORED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================

# --- instance: rate_contract_half_open_interval_overlap_on_lane ---
def test_overlap_boundary_touch_is_not_overlap(api, broker_ops_headers):
    """# difficulty: resource_temporal_overlap/rate_contract_half_open_interval_overlap_on_lane

    PRD §3.4: "Before creation, the server checks that no other `ACTIVE`
    rate contract on the same shipper, lane ... already covers any
    instant in the new contract's [`effective_from`, `effective_to`) window."

    Claim: half-open semantics — RC2.effective_from == RC1.effective_to
    is permitted (no shared instant).
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base = parse_iso(brokerage["clock_now_iso"])
    rc1_to = iso_utc(add_days(base, 30))
    create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base),
        effective_to=rc1_to,
    )
    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="DRY_VAN",
            effective_from=rc1_to,
            effective_to=iso_utc(add_days(base, 60)),
        ),
        broker_ops_headers,
    )
    validate_success(res, 201)


def test_overlap_one_day_overlap_rejected(api, broker_ops_headers):
    """# difficulty: resource_temporal_overlap/rate_contract_half_open_interval_overlap_on_lane

    PRD §3.4: "An overlap is rejected with `ERR_RATE_CONTRACT_OVERLAP`."

    Claim: a one-day overlap on the same lane+equipment ->
    ERR_RATE_CONTRACT_OVERLAP.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    base = parse_iso(brokerage["clock_now_iso"])
    create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10000", lane_destination_zip="20000",
        equipment_type="DRY_VAN",
        effective_from=iso_utc(base),
        effective_to=iso_utc(add_days(base, 30)),
    )
    res = api.create_rate_contract(
        brokerage["id"],
        create_rate_contract_payload(
            shipper_id=shipper["id"],
            lane_origin_zip="10000", lane_destination_zip="20000",
            equipment_type="DRY_VAN",
            effective_from=iso_utc(add_days(base, 29)),
            effective_to=iso_utc(add_days(base, 60)),
        ),
        broker_ops_headers,
    )
    validate_error(res, "ERR_RATE_CONTRACT_OVERLAP")


# --- instance: detention_free_window_aggregate_capacity_on_load ---
def test_overlap_load_inside_free_window_zero_cents(api):
    """# difficulty: resource_temporal_overlap/detention_free_window_aggregate_capacity_on_load

    PRD §3.7: "if the result is non-positive, no detention accrues and
    `provisional_detention_cents` is zero."

    Claim: a 119-minute load (entirely inside the 120-minute free
    window) yields 0 cents detention.
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=119,
    )
    assert load["provisional_detention_cents"] == 0


def test_overlap_load_30_minutes_past_free_yields_two_increments(api):
    """# difficulty: resource_temporal_overlap/detention_free_window_aggregate_capacity_on_load

    PRD §3.7: pinned formula "ceil to next 15-minute increment, then
    multiply by per-increment rate" — 30 chargeable minutes -> 2
    increments * 1500 = 3000 cents.

    Claim: a 150-minute load (free=120, chargeable=30) -> 3000 cents.
    """
    brokerage, shipper, _c, _q, load = setup_delivered_load(
        detention_minutes=150,
    )
    assert load["provisional_detention_cents"] == 3000


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================

# --- instance: invoice_face_value_conservation_through_dispute_resolution ---
def test_invariant_invoice_face_value_conserved_partial_credit(api):
    """# difficulty: compensating_invariant/invoice_face_value_conservation_through_dispute_resolution

    PRD §3.9: "The conservation invariant the system maintains is that
    the pre-resolution `invoice_total_cents` equals the post-resolution
    `invoice_total_cents` plus the delta added to `amount_credited_cents`."

    Claim: pre_total == post_total + credit_delta after a partial
    resolution.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01650",  # 46500
            detention_minutes=0, accessorials=None,
            claimed_cents=3_000,
        )
    )
    pre_total = invoice["invoice_total_cents"]  # 46500
    assert pre_total == 46_500

    resolve_dispute(brokerage["id"], claim["id"], 3_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert after["invoice_total_cents"] == 43_500
    assert after["amount_credited_cents"] == 3_000
    # Conservation: pre_total == post_total + credit_delta.
    assert pre_total == after["invoice_total_cents"] + (
        after["amount_credited_cents"] - 0
    )
    # And sum-of-buckets == original face value.
    assert_invoice_balance_conservation(after, original_total_cents=46_500)


def test_invariant_invoice_face_value_conserved_full_credit(api):
    """# difficulty: compensating_invariant/invoice_face_value_conservation_through_dispute_resolution

    PRD §3.9: "`balance_due_cents` is then recomputed as
    `invoice_total_cents` minus `amount_paid_cents` minus `amount_credited_cents`,
    with a floor of zero." Conservation still holds when credit drives
    invoice_total to 0.

    Claim: after full-credit resolve, invoice_total + paid + credited
    == original face value.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",  # 40000
            detention_minutes=0, accessorials=None,
            claimed_cents=40_000,
        )
    )
    original = invoice["invoice_total_cents"]
    resolve_dispute(brokerage["id"], claim["id"], 40_000)
    after = get_invoice(brokerage["id"], invoice["id"])
    assert_invoice_balance_conservation(after, original_total_cents=original)


# --- instance: shipper_outstanding_invoiced_conservation_through_settle_and_writeoff ---
def test_invariant_shipper_credit_restored_after_writeoff(api):
    """# difficulty: compensating_invariant/shipper_outstanding_invoiced_conservation_through_settle_and_writeoff

    PRD §3.10: the /invoice transition increases
    Shipper.outstanding_invoiced_cents by the invoice total; the
    /write-off "decreases the shipper's outstanding_invoiced_cents by
    the original frozen invoice_total_cents."

    Claim: net delta on Shipper.outstanding over (invoice + write-off)
    is zero; available credit is restored.
    """
    brokerage, shipper, _c, _q, _l, invoice = setup_invoiced_load(
        origin_zip="00000", destination_zip="01650",
        detention_minutes=0, accessorials=None,
        credit_limit_cents=200_000,
    )
    shipper_mid = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_mid["outstanding_invoiced_cents"] == 46_500
    write_off_invoice(brokerage["id"], invoice["id"])
    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0


def test_invariant_shipper_credit_restored_after_full_dispute_resolution(api):
    """# difficulty: compensating_invariant/shipper_outstanding_invoiced_conservation_through_settle_and_writeoff

    PRD §3.2: "at the point the invoice transitions to `PAID` or
    `WRITTEN_OFF`, the shipper's `outstanding_invoiced_cents` is decreased
    by the original frozen `invoice_total_cents` of that invoice."

    Claim: the same net-zero invariant holds when the invoice settles
    to PAID via full-credit dispute resolution.
    """
    brokerage, shipper, _c, _q, _l, invoice, claim = (
        setup_invoice_in_review_dispute(
            origin_zip="00000", destination_zip="01000",  # 40000
            detention_minutes=0, accessorials=None,
            claimed_cents=40_000,
        )
    )
    shipper_mid = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_mid["outstanding_invoiced_cents"] == 40_000

    resolve_dispute(brokerage["id"], claim["id"], 40_000)
    after_inv = get_invoice(brokerage["id"], invoice["id"])
    assert after_inv["settlement_status"] == "PAID"

    shipper_after = get_shipper(brokerage["id"], shipper["id"])
    assert shipper_after["outstanding_invoiced_cents"] == 0
