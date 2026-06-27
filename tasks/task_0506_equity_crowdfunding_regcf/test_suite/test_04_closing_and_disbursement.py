"""Closing a raise: equity vs SAFE issuance, platform-fee disbursement ordering, transitive
cascades, conservation invariants, cap-table immutability, and rolling-close minimum gate.

Queue-A: dual_variant_calc (issuance), combinatorial_formula (fee order), transitive_cascade,
compensating_invariant.
Queue-B: entities (immutability), endpoints (rolling-close minimum) corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_issuer_headers, make_investor_headers, make_compliance_officer_headers,
    create_offering_payload, create_investment_payload,
    create_verified_issuer, create_accredited_investor,
    create_live_offering, set_clock,
    setup_committed_offering,
    api_client,
)

CO = make_compliance_officer_headers()


def _commit_raw(api, offering, investor_id, amount_cents, expected_version):
    return api.create_investment(
        create_investment_payload(offering["id"], investor_id, expected_version, amount_cents=amount_cents),
        headers=make_investor_headers(investor_id))


# ============================================================================
# Equity vs SAFE issuance (queue A: dual_variant_calc)
# ============================================================================

def test_equity_issuance_floor_shares_and_remainder_refund(api):
    """PRD §3.6: "For an `EQUITY` offering, the number of `securities_issued` is the investment's
    `amount_cents` integer-divided by the offering's `price_per_security_cents` — the whole-share
    count, floored. ... the investment's `refund_amount_cents` is set to the whole-share rounding
    remainder, i.e. its `amount_cents` minus that consideration".

    Design: Difficulty/dual_variant_calc/issuance_equity_vs_safe_variants_on_investment
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Acme Eq Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="EQUITY", price_per_security_cents=1075,
                                    min_target_cents=200_000, max_target_cents=1_000_000,
                                    deadline_at="2026-09-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 250_000, v0), expected_status=201)
    validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    after = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    # floor(250000/1075)=232 shares; consideration 232*1075=249,400; remainder 600.
    assert after["securities_issued"] == 232
    assert after["refund_amount_cents"] == 600


def test_safe_issuance_zero_shares_no_remainder(api):
    """PRD §3.6: "For a `SAFE` offering, no share math occurs: `securities_issued` is zero and
    `refund_amount_cents` is zero, and the minted `CapTableEntry` records `instrument` as `SAFE`,
    `quantity` as null, and `principal_cents` as the full `amount_cents`."

    Design: Difficulty/dual_variant_calc/issuance_equity_vs_safe_variants_on_investment
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Acme Safe Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=200_000, max_target_cents=1_000_000,
                                    deadline_at="2026-09-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 250_000, v0), expected_status=201)
    validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    after = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    assert after["securities_issued"] == 0
    assert after["refund_amount_cents"] == 0


# ============================================================================
# Close disbursement fee-on-sum ordering (queue A: combinatorial_formula)
# ============================================================================

def test_close_disbursement_fee_computed_on_batch_sum(api):
    """PRD §3.6: "compute the platform fee on that sum: it is seven and one-half percent of the
    batch gross, i.e. the batch gross multiplied by 750 then divided by 10,000, rounded half up to
    the nearest whole cent."
    PRD §3.6: "The net disbursed to the issuer is the batch gross minus the platform fee minus the
    summed remainders. The escrow account is then updated: its `held_amount_cents` is reduced by
    the batch gross, its `disbursed_amount_cents` is increased by the net disbursed, and its
    `refunded_amount_cents` is increased by the sum of the remainders plus the platform fee."

    Design: Difficulty/combinatorial_formula/close_disbursement_mode_b_fee_round_order
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Safe Fee Co")
    inv_a = create_accredited_investor()
    inv_b = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=200_000, max_target_cents=1_000_000,
                                    deadline_at="2026-09-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_a["id"], 100_001, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_b["id"], 100_006, v1), expected_status=201)
    validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    # batch gross 200,007; fee round_half_up(200,007*7.5%)=15,001; SAFE remainders 0;
    # disbursed 200,007-15,001=185,006; refunded 15,001; held 0.
    assert escrow["disbursed_amount_cents"] == 185_006
    assert escrow["refunded_amount_cents"] == 15_001
    assert escrow["held_amount_cents"] == 0


def test_close_disbursement_refunded_includes_fee_distinct_from_perline(api):
    """PRD §3.6: "(Computing the fee once on the summed gross is required; summing per-line fees
    would diverge by rounding.)"
    PRD §3.6: "its `refunded_amount_cents` is increased by the sum of the remainders plus the
    platform fee."

    Design: Difficulty/combinatorial_formula/close_disbursement_mode_b_fee_round_order
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Safe Fee2 Co")
    inv_a = create_accredited_investor()
    inv_b = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=200_000, max_target_cents=1_000_000,
                                    deadline_at="2026-09-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_a["id"], 100_001, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_b["id"], 100_006, v1), expected_status=201)
    validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    # Fee on the summed gross (15,001c) is 1c larger than summing per-line fees (7,501+7,500=15,000c).
    # refunded == fee since SAFE batch has no sub-share remainders.
    assert escrow["refunded_amount_cents"] == 15_001
    assert escrow["disbursed_amount_cents"] + escrow["refunded_amount_cents"] == 200_007
    assert after_off["swept_amount_cents"] == 200_007


# ============================================================================
# Transitive cascades (queue A: transitive_cascade)
# ============================================================================

def test_rolling_close_cascade_issues_mints_disburses_keeps_live(api):
    """PRD §3.6: "A rolling close additionally requires the offering to be `LIVE` with
    `form_c_status` of `QUALIFIED`; it sweeps the batch exactly as a final close does but leaves
    the offering in `LIVE` (the `LIVE → LIVE` self-loop)".
    PRD §3.6: "For each investment in the batch, its status moves to `ISSUED`".
    PRD §3.6: "the number of `securities_issued` is the investment's `amount_cents` integer-divided
    by the offering's `price_per_security_cents`".

    Design: Difficulty/transitive_cascade/rolling_close_cascade_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Roll Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="EQUITY", price_per_security_cents=1000,
                                    min_target_cents=2_000_000, max_target_cents=10_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 2_500_000, v0), expected_status=201)
    validate_success(api.rolling_close(offering["id"], headers=issuer_headers))
    after_inv = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after_inv["status"] == "ISSUED"
    assert after_inv["securities_issued"] == 2500  # 2,500,000 / 1000
    assert after_off["status"] == "LIVE"
    assert after_off["swept_amount_cents"] == 2_500_000


def test_rolling_close_escrow_disbursed_net_of_fee(api):
    """PRD §3.6: "The escrow account is then updated: its `held_amount_cents` is reduced by the
    batch gross, its `disbursed_amount_cents` is increased by the net disbursed".
    PRD §3.6: "compute the platform fee on that sum: it is seven and one-half percent of the batch
    gross".

    Design: Difficulty/transitive_cascade/rolling_close_cascade_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Roll2 Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="EQUITY", price_per_security_cents=1000,
                                    min_target_cents=2_000_000, max_target_cents=10_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 2_500_000, v0), expected_status=201)
    validate_success(api.rolling_close(offering["id"], headers=issuer_headers))
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    # gross 2,500,000; fee round_half_up(2,500,000*7.5%)=187,500; EQUITY exact (2500 shares, 0 remainder);
    # disbursed 2,500,000-187,500=2,312,500; held 0.
    assert escrow["disbursed_amount_cents"] == 2_312_500
    assert escrow["held_amount_cents"] == 0


def test_material_amendment_flags_committed_investment_for_reconfirm(api):
    """PRD §3.5: "the issuer may file a material amendment, advancing `form_c_status` from
    `QUALIFIED` back to `SUBMITTED`. This amendment cascades: every investment on the offering
    currently in `COMMITTED` has its `reconfirm_required` set to `true`, and the offering's
    `version` is incremented by one."

    Design: Difficulty/transitive_cascade/material_amend_reconfirm_cascade_depth2
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Amend Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 500_000, v0), expected_status=201)
    validate_success(api.amend_form_c(offering["id"], headers=issuer_headers))
    after_inv = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after_inv["reconfirm_required"] is True
    assert after_inv["status"] == "COMMITTED"
    assert after_off["form_c_status"] == "SUBMITTED"


def test_material_amendment_sets_form_c_back_to_submitted(api):
    """PRD §3.5: "While an offering is in `DRAFT` or `LIVE` and its `form_c_status` is `QUALIFIED`,
    the issuer may file a material amendment, advancing `form_c_status` from `QUALIFIED` back to
    `SUBMITTED`."

    Design: Difficulty/transitive_cascade/material_amend_reconfirm_cascade_depth2
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Amend2 Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 500_000, v0), expected_status=201)
    amended = validate_success(api.amend_form_c(offering["id"], headers=issuer_headers))
    assert amended["form_c_status"] == "SUBMITTED"
    after_inv = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    assert after_inv["reconfirm_required"] is True


# ============================================================================
# Compensating invariants (queue A: compensating_invariant)
# ============================================================================

def test_commit_then_withdraw_conserves_escrow_held(api):
    """PRD §3.5: "Withdrawal advances the investment to `CANCELLED`, sets its `refund_amount_cents`
    to the full `amount_cents`, credits that amount back to the investor's wallet, debits escrow
    held, recomputes the offering's `committed_amount_cents`, and increments the investment's
    `version` by one."

    Design: Difficulty/compensating_invariant/commit_then_withdraw_conserves_escrow_held
    """
    issuer, investor, offering, investment = setup_committed_offering(
        amount_cents=300_000,
        offering_overrides={"min_target_cents": 100_000, "max_target_cents": 1_000_000})
    issuer_headers = make_issuer_headers(issuer["id"])
    inv_headers = make_investor_headers(investor["id"])
    withdrawn = validate_success(api.withdraw_investment(investment["id"], headers=inv_headers))
    assert withdrawn["status"] == "CANCELLED"
    assert withdrawn["refund_amount_cents"] == 300_000
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after_off["committed_amount_cents"] == 0
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert escrow["held_amount_cents"] == 0


def test_withdraw_restores_escrow_held_equals_committed(api):
    """PRD §3.4: "the escrow account's `held_amount_cents` is recomputed by the same rule (so that
    escrow held always equals the offering's committed amount)".
    PRD §3.5: "Withdrawal advances the investment to `CANCELLED`, sets its `refund_amount_cents` to
    the full `amount_cents`, credits that amount back to the investor's wallet, debits escrow held,
    recomputes the offering's `committed_amount_cents`".

    Design: Difficulty/compensating_invariant/commit_then_withdraw_conserves_escrow_held
    """
    issuer, investor, offering, investment = setup_committed_offering(
        amount_cents=300_000,
        offering_overrides={"min_target_cents": 100_000, "max_target_cents": 1_000_000})
    issuer_headers = make_issuer_headers(issuer["id"])
    inv_headers = make_investor_headers(investor["id"])
    # Before withdrawal: held == committed == 300,000 (conservation invariant).
    before_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    before_escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert before_escrow["held_amount_cents"] == before_off["committed_amount_cents"] == 300_000
    validate_success(api.withdraw_investment(investment["id"], headers=inv_headers))
    # After withdrawal: held == committed == 0 (zero drift; refund equals the commit exactly).
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    after_escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert after_escrow["held_amount_cents"] == after_off["committed_amount_cents"] == 0


def test_failed_raise_conserves_zero_shares_and_full_capital_return(api):
    """PRD §3.5: "On failure, every investment on the offering in `COMMITTED` or `RECONFIRMED`
    status moves to `REFUNDED` with its `refund_amount_cents` set to the full `amount_cents` and
    that amount credited to the investor's wallet; the escrow account's `held_amount_cents` is
    driven to zero and its `refunded_amount_cents` is advanced by the total refunded ... No
    cap-table position is minted on a failed raise."

    Design: Difficulty/compensating_invariant/failed_raise_conserves_zero_shares_and_full_capital_return
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Fl Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="EQUITY", price_per_security_cents=1000,
                                    min_target_cents=500_000, max_target_cents=2_000_000,
                                    deadline_at="2026-07-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    inv = validate_success(_commit_raw(api, offering, investor["id"], 200_000, v0), expected_status=201)
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FAILED"
    after_inv = validate_success(api.get_investment(inv["id"], headers=issuer_headers))
    assert after_inv["status"] == "REFUNDED"
    assert after_inv["securities_issued"] == 0
    assert after_inv["refund_amount_cents"] == 200_000
    cap = validate_success(api.get_cap_table(offering["id"], headers=issuer_headers))
    assert len(cap) == 0
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert escrow["refunded_amount_cents"] == 200_000


def test_failed_raise_drives_escrow_held_to_zero_no_disbursement(api):
    """PRD §3.5: "the escrow account's `held_amount_cents` is driven to zero and its
    `refunded_amount_cents` is advanced by the total refunded; the offering's `status` is set to
    `FAILED` ... No cap-table position is minted on a failed raise."

    Design: Difficulty/compensating_invariant/failed_raise_conserves_zero_shares_and_full_capital_return
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Fl2 Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=500_000, max_target_cents=2_000_000,
                                    deadline_at="2026-07-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 300_000, v0), expected_status=201)
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FAILED"
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert escrow["held_amount_cents"] == 0
    assert escrow["disbursed_amount_cents"] == 0
    assert escrow["refunded_amount_cents"] == 300_000
    cap = validate_success(api.get_cap_table(offering["id"], headers=issuer_headers))
    assert len(cap) == 0


# ============================================================================
# Cap-table immutability + rolling-close minimum (queue B)
# ============================================================================

def test_cap_table_entry_safe_is_immutable_record(api):
    """PRD §2.4: "a cap-table position is an immutable record minted at close and never edited
    afterward, so it carries only an `id` and a `created_at` — it has neither an `updated_at` field
    nor a `version` field."
    PRD §3.6: "the minted `CapTableEntry` records `instrument` as `SAFE`, `quantity` as null, and
    `principal_cents` as the full `amount_cents`."

    Design: Corner/entities/captable_entry_is_immutable_no_version_field
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Im Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], security_type="SAFE",
                                    min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 200_000, v0), expected_status=201)
    validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    cap = validate_success(api.get_cap_table(offering["id"], headers=issuer_headers))
    assert len(cap) == 1
    entry = cap[0]
    assert entry["instrument"] == "SAFE"
    assert entry["principal_cents"] == 200_000
    assert entry["quantity"] is None
    assert "version" not in entry
    assert "updated_at" not in entry


def test_rolling_close_below_minimum_returns_minimum_not_met(api):
    """PRD §3.6: "A close is permitted only when the offering's `swept_amount_cents` plus the gross
    of the close batch is at least `min_target_cents`; if the cumulative swept total cannot reach
    the minimum, the close is rejected with `ERR_MINIMUM_NOT_MET`."

    Design: Corner/endpoints/rolling_close_below_minimum_returns_minimum_not_met
    """
    issuer, investor, offering, _ = setup_committed_offering(
        amount_cents=100_000,
        offering_overrides={"min_target_cents": 500_000, "max_target_cents": 2_000_000})
    issuer_headers = make_issuer_headers(issuer["id"])
    resp = api.rolling_close(offering["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_MINIMUM_NOT_MET, expected_status=409)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["swept_amount_cents"] == 0
    assert after["status"] == "LIVE"
