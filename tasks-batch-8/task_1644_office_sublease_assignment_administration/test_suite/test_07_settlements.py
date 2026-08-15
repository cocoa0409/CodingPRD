"""Settlements: the profit-share waterfall, the lease ledger, and period overlap (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    B1,
    attest_credit,
    build_documented_transfer,
    build_effective_transfer,
    build_submitted_transfer,
    create_settlement,
    decide_consent,
    document_transfer,
    get_lease,
    get_recognition_of,
    get_settlement,
    get_transfer,
    make_tenant_headers,
    sign_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_FLOOR = {"leased_rsf": 8000}     # certified RSF 8960 >= 8000 -> not partial
PARTIAL_FLOOR = {"leased_rsf": 10000}  # certified RSF 8960 < 10000 -> partial

# Pinned waterfall results for the standard fixture (verified against PRD §3.8):
OCTOBER_FULL = {"passthrough": 3957129, "net": 2042871, "landlord": 1319824}
OCTOBER_PARTIAL = {"passthrough": 4550698, "net": 1449302,
                   "landlord": 874648, "tenant": 574654}
OCTOBER_STRADDLE = {"passthrough": 3957129, "net": 16042871,
                    "landlord": 11819824, "tenant": 4223047}
OCTOBER_TIER1_ONLY = {"passthrough": 3957129, "net": 542871,
                      "landlord": 271435, "tenant": 271436}


def _assert_october_full_floor(settlement: dict):
    assert settlement["passthrough_rent_cents"] == OCTOBER_FULL["passthrough"]
    assert settlement["net_profit_cents"] == OCTOBER_FULL["net"]
    assert settlement["landlord_share_cents"] == OCTOBER_FULL["landlord"]


def test_settlement_zero_profit_boundary(api):
    """PRD §3.8: "The `net_profit_cents` is the collected subrent minus the pass-through, floored at zero."

    Design: Corner/calculations/settlement_zero_profit_boundary_at_exact_passthrough
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=3957129)
    assert settlement["passthrough_rent_cents"] == 3957129
    assert settlement["net_profit_cents"] == 0, "exact equality floors at zero"
    assert settlement["landlord_share_cents"] == 0
    assert settlement["tenant_share_cents"] == 0


def test_provisional_settlement_leaves_ledger_untouched(api):
    """PRD §3.8: "While a settlement sits in `DRAFT`, its computed fields are provisional — recomputed on every read — and the lease ledger is untouched."
    PRD §2.10: "`cumulative_profit_share_cents` is the running total of the landlord's profit share across all `FINALIZED` settlements of the lease; it is debited at the moment a settlement finalizes, voiding a `DRAFT` settlement has no ledger effect, and a finalized settlement cannot be voided at all."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_ledger_divergence
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    assert settlement["status"] == "DRAFT"
    _assert_october_full_floor(settlement)

    reread = get_settlement(settlement["id"])
    _assert_october_full_floor(reread)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["cumulative_profit_share_cents"] == 0, (
        "the provisional variant never touches the ledger"
    )


def test_finalize_debits_ledger_once(api):
    """PRD §3.8: "Finalization, restricted to a transfer that has reached `EFFECTIVE` with no `TERMINATED` instrument, freezes the computed fields, stamps `finalized_at`, and debits the ledger: the lease's `cumulative_profit_share_cents` increases by the settlement's `landlord_share_cents`, and the lease's `version` increments by one."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_ledger_divergence
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    lease_v_pre = get_lease(ctx["lease"]["id"])["version"]

    finalized = validate_success(api.finalize_settlement(settlement["id"], B1), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"] is not None
    _assert_october_full_floor(finalized)

    lease = get_lease(ctx["lease"]["id"])
    assert lease["cumulative_profit_share_cents"] == OCTOBER_FULL["landlord"], (
        "the final variant debits the ledger exactly once"
    )
    assert lease["version"] == lease_v_pre + 1

    reread = get_settlement(settlement["id"])
    _assert_october_full_floor(reread)


def test_partial_floor_nested_rounding(api):
    """PRD §3.8: "When the demised area's `is_partial_floor` is true, the pass-through is then grossed up by 1,500 basis points (fifteen percent) — the base multiplied by eleven thousand five hundred and divided by ten thousand, rounded half-up as a second, nested rounding step — yielding `passthrough_rent_cents`; a full-floor demise skips the gross-up and keeps the base figure."
    PRD §3.8: "Finally `landlord_share_cents` de-annualizes: the annualized landlord share multiplied by the day count and divided by 365, rounded half-up as the third rounding step. The `tenant_share_cents` is the net profit minus the landlord's share"

    Design: Difficulty/combinatorial_formula/settlement_partial_floor_nested_rounding_mode_b
    """
    ctx = build_effective_transfer(lease_overrides=PARTIAL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    assert settlement["passthrough_rent_cents"] == OCTOBER_PARTIAL["passthrough"]
    assert settlement["net_profit_cents"] == OCTOBER_PARTIAL["net"]
    assert settlement["landlord_share_cents"] == OCTOBER_PARTIAL["landlord"]
    assert settlement["tenant_share_cents"] == OCTOBER_PARTIAL["tenant"]


def test_partial_floor_diverges_from_full_floor(api):
    """PRD §3.3: "Third, `is_partial_floor`: true exactly when the `rentable_sf` is strictly less than the lease's `leased_rsf`, a flag that later triggers the partial-floor expense gross-up in settlement math."
    PRD §3.8: "When the demised area's `is_partial_floor` is true, the pass-through is then grossed up by 1,500 basis points (fifteen percent) — the base multiplied by eleven thousand five hundred and divided by ten thousand, rounded half-up as a second, nested rounding step — yielding `passthrough_rent_cents`; a full-floor demise skips the gross-up and keeps the base figure."

    Design: Difficulty/combinatorial_formula/settlement_partial_floor_nested_rounding_mode_b
    """
    partial_ctx = build_effective_transfer(lease_overrides=PARTIAL_FLOOR)
    areas, _ = validate_paginated(
        api.list_transfer_demised_areas(partial_ctx["transfer"]["id"], B1)
    )
    assert areas[0]["is_partial_floor"] is True

    full_ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    areas_full, _ = validate_paginated(
        api.list_transfer_demised_areas(full_ctx["transfer"]["id"], B1)
    )
    assert areas_full[0]["is_partial_floor"] is False

    partial_s = create_settlement(partial_ctx, subrent_collected_cents=6000000)
    full_s = create_settlement(full_ctx, subrent_collected_cents=6000000)
    assert partial_s["landlord_share_cents"] == OCTOBER_PARTIAL["landlord"]
    assert full_s["landlord_share_cents"] == OCTOBER_FULL["landlord"]
    assert partial_s["landlord_share_cents"] != full_s["landlord_share_cents"], (
        "identical collected rent diverges across the partial-floor branch"
    )


def test_tier_straddle_per_tier_rounding(api):
    """PRD §3.8: "The tier-1 base is the lesser of that annualized profit and the lease's `profit_share_tier1_threshold_annual_cents`; the tier-2 base is whatever annualized profit exceeds the threshold, or zero. Each tier's landlord share is its base multiplied by the tier's percentage in basis points and divided by ten thousand, rounded half-up per tier — the per-tier rounding is pinned ahead of summation, never the reverse — and the two rounded tier amounts sum to the annualized landlord share."

    Design: Difficulty/combinatorial_formula/settlement_tier_straddle_per_tier_rounding_mode_a
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=20000000)
    assert settlement["passthrough_rent_cents"] == OCTOBER_STRADDLE["passthrough"]
    assert settlement["net_profit_cents"] == OCTOBER_STRADDLE["net"]
    assert settlement["landlord_share_cents"] == OCTOBER_STRADDLE["landlord"]
    assert settlement["tenant_share_cents"] == OCTOBER_STRADDLE["tenant"]


def test_tier1_only_under_threshold(api):
    """PRD §3.8: "The tier-1 base is the lesser of that annualized profit and the lease's `profit_share_tier1_threshold_annual_cents`; the tier-2 base is whatever annualized profit exceeds the threshold, or zero."
    PRD §3.8: "The annualized profit is the net profit multiplied by 365 and divided by the day count, rounded half-up."

    Design: Difficulty/combinatorial_formula/settlement_tier_straddle_per_tier_rounding_mode_a
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    # Collected 4,500,000 over 31 days annualizes to 6,391,868 — under the
    # 10,000,000 threshold, so only the tier-1 rate engages.
    settlement = create_settlement(ctx, subrent_collected_cents=4500000)
    assert settlement["passthrough_rent_cents"] == OCTOBER_TIER1_ONLY["passthrough"]
    assert settlement["net_profit_cents"] == OCTOBER_TIER1_ONLY["net"]
    assert settlement["landlord_share_cents"] == OCTOBER_TIER1_ONLY["landlord"]
    assert settlement["tenant_share_cents"] == OCTOBER_TIER1_ONLY["tenant"]


def test_overlap_finalize_rejected(api):
    """PRD §3.8: "Finalized periods for the same transfer must not overlap — the check treats each period as half-open, so one period's `period_end` equaling another's `period_start` is permitted adjacency rather than overlap — and an overlapping finalization is rejected with `ERR_DUPLICATE_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/settlement_period_overlap_half_open_adjacency
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    s1 = create_settlement(ctx, period_start="2026-10-01T00:00:00.000Z",
                           period_end="2026-11-01T00:00:00.000Z",
                           subrent_collected_cents=6000000)
    validate_success(api.finalize_settlement(s1["id"], B1), 200)

    s2 = create_settlement(ctx, period_start="2026-10-15T00:00:00.000Z",
                           period_end="2026-11-15T00:00:00.000Z",
                           subrent_collected_cents=3000000)
    resp = api.finalize_settlement(s2["id"], B1)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE, 409)
    assert get_settlement(s2["id"])["status"] == "DRAFT"


def test_adjacent_finalize_permitted(api):
    """PRD §3.8: "Finalized periods for the same transfer must not overlap — the check treats each period as half-open, so one period's `period_end` equaling another's `period_start` is permitted adjacency rather than overlap — and an overlapping finalization is rejected with `ERR_DUPLICATE_ACTIVE`."
    PRD §3.8: "Finalization, restricted to a transfer that has reached `EFFECTIVE` with no `TERMINATED` instrument, freezes the computed fields, stamps `finalized_at`, and debits the ledger: the lease's `cumulative_profit_share_cents` increases by the settlement's `landlord_share_cents`, and the lease's `version` increments by one."

    Design: Difficulty/resource_temporal_overlap/settlement_period_overlap_half_open_adjacency
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    s1 = create_settlement(ctx, period_start="2026-10-01T00:00:00.000Z",
                           period_end="2026-11-01T00:00:00.000Z",
                           subrent_collected_cents=6000000)
    validate_success(api.finalize_settlement(s1["id"], B1), 200)

    # s1.period_end == s3.period_start: touching endpoints do not overlap.
    s3 = create_settlement(ctx, period_start="2026-11-01T00:00:00.000Z",
                           period_end="2026-12-01T00:00:00.000Z",
                           subrent_collected_cents=6000000)
    finalized = validate_success(api.finalize_settlement(s3["id"], B1), 200)
    assert finalized["status"] == "FINALIZED"

    lease = get_lease(ctx["lease"]["id"])
    s1_after = get_settlement(s1["id"])
    assert lease["cumulative_profit_share_cents"] == (
        s1_after["landlord_share_cents"] + finalized["landlord_share_cents"]
    ), "the ledger accumulates each finalized settlement's landlord share"


def test_finalize_gated_on_transfer_effective(api):
    """PRD §3.7: "Effectiveness is what unlocks settlement finalization: draft settlements may be created from `CONSENT_GRANTED` onward, but finalizing one requires the transfer to be `EFFECTIVE`."

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_gated_on_transfer_effective
    """
    ctx = build_documented_transfer(lease_overrides=FULL_FLOOR)
    assert get_transfer(ctx["transfer"]["id"])["status"] == "DOCUMENTED"

    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    assert settlement["status"] == "DRAFT", "creation is permitted from DOCUMENTED"

    resp = api.finalize_settlement(settlement["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_settlement(settlement["id"])["status"] == "DRAFT"
    assert get_lease(ctx["lease"]["id"])["cumulative_profit_share_cents"] == 0


def test_finalize_succeeds_after_effectiveness(api):
    """PRD §3.7: "Effectiveness is what unlocks settlement finalization: draft settlements may be created from `CONSENT_GRANTED` onward, but finalizing one requires the transfer to be `EFFECTIVE`."
    PRD §3.8: "Finalization, restricted to a transfer that has reached `EFFECTIVE` with no `TERMINATED` instrument, freezes the computed fields, stamps `finalized_at`, and debits the ledger: the lease's `cumulative_profit_share_cents` increases by the settlement's `landlord_share_cents`, and the lease's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_gated_on_transfer_effective
    """
    ctx = build_documented_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)

    sign_recognition(ctx["ra_id"], "LANDLORD", ctx["pl"]["id"])
    sign_recognition(ctx["ra_id"], "COUNTERPARTY", ctx["ps"]["id"])
    assert get_transfer(ctx["transfer"]["id"])["status"] == "EFFECTIVE"

    finalized = validate_success(api.finalize_settlement(settlement["id"], B1), 200)
    assert finalized["status"] == "FINALIZED"
    lease = get_lease(ctx["lease"]["id"])
    assert lease["cumulative_profit_share_cents"] == finalized["landlord_share_cents"]


def test_void_draft_conserves_ledger(api):
    """PRD §3.8: "A draft settlement may instead be voided, moving it to `VOID` with no ledger effect; a finalized settlement can never be voided."

    Design: Difficulty/compensating_invariant/finalize_void_preserves_cumulative_profit_share
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)

    voided = validate_success(api.void_settlement(settlement["id"], B1), 200)
    assert voided["status"] == "VOID"
    assert get_lease(ctx["lease"]["id"])["cumulative_profit_share_cents"] == 0, (
        "voiding a DRAFT settlement conserves the ledger"
    )


def test_finalize_after_void_rejected(api):
    """PRD §3.8: "A draft settlement may instead be voided, moving it to `VOID` with no ledger effect; a finalized settlement can never be voided."
    PRD §2.8: "then state validity for the invoked transition (`ERR_INVALID_STATE`)"

    Design: Difficulty/compensating_invariant/finalize_void_preserves_cumulative_profit_share
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    validate_success(api.void_settlement(settlement["id"], B1), 200)

    resp = api.finalize_settlement(settlement["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_settlement(settlement["id"])["status"] == "VOID"
    assert get_lease(ctx["lease"]["id"])["cumulative_profit_share_cents"] == 0


def test_finalized_settlement_cannot_be_voided(api):
    """PRD §3.8: "A draft settlement may instead be voided, moving it to `VOID` with no ledger effect; a finalized settlement can never be voided."
    PRD §2.10: "`cumulative_profit_share_cents` is the running total of the landlord's profit share across all `FINALIZED` settlements of the lease; it is debited at the moment a settlement finalizes, voiding a `DRAFT` settlement has no ledger effect, and a finalized settlement cannot be voided at all."

    Design: Difficulty/compensating_invariant/finalize_void_preserves_cumulative_profit_share
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    validate_success(api.finalize_settlement(settlement["id"], B1), 200)

    resp = api.void_settlement(settlement["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_settlement(settlement["id"])["status"] == "FINALIZED"
    assert get_lease(ctx["lease"]["id"])["cumulative_profit_share_cents"] == (
        OCTOBER_FULL["landlord"]
    ), "the finalized debit survives the rejected void"


def test_sublease_terminate_blocks_settlement_finalize(api):
    """PRD §3.9: "The tenant of record — `X-User-ID` equal to the lease's `tenant_party_id` — may terminate an instrument in `EXECUTED` or in `RECOGNIZED`, moving it to `TERMINATED`; from that point no settlement may be created or finalized against the parent transfer, an existence gate the settlement workflows enforce as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sublease_terminate_blocks_settlement_finalize
    """
    ctx = build_effective_transfer(lease_overrides=FULL_FLOOR)
    settlement = create_settlement(ctx, subrent_collected_cents=6000000)

    terminated = validate_success(api.terminate_sublease_agreement(
        ctx["sa_id"], make_tenant_headers(ctx["pt"]["id"]),
    ), 200)
    assert terminated["status"] == "TERMINATED"

    resp = api.finalize_settlement(settlement["id"], B1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_settlement(settlement["id"])["status"] == "DRAFT"
    assert get_lease(ctx["lease"]["id"])["cumulative_profit_share_cents"] == 0


def test_derived_counters_reconciled_across_lifecycle(api):
    """PRD §2.10: "`open_transfer_count` counts the lease's transfers that sit in a non-terminal status and drives the one-open-transfer gate of §3.2; it is incremented at submission and decremented when a transfer reaches denial, rescission, withdrawal from a post-draft state, or effectiveness."
    PRD §2.10: "`cumulative_profit_share_cents` is the running total of the landlord's profit share across all `FINALIZED` settlements of the lease; it is debited at the moment a settlement finalizes, voiding a `DRAFT` settlement has no ledger effect, and a finalized settlement cannot be voided at all."

    Design: Corner/cross_cutting_layers/derived_counters_reconciled_across_lifecycle
    """
    ctx = build_submitted_transfer(lease_overrides=FULL_FLOOR)
    assert get_lease(ctx["lease"]["id"])["open_transfer_count"] == 1, (
        "0 -> 1 at submission"
    )

    attest_credit(ctx["credit_review"]["id"], 7000)
    decide_consent(ctx["consent_review"]["id"], ctx["pl"]["id"], "GRANTED")
    document_transfer(ctx["transfer"]["id"])
    ra_id = get_recognition_of(ctx["transfer"]["id"])["id"]
    sign_recognition(ra_id, "LANDLORD", ctx["pl"]["id"])
    sign_recognition(ra_id, "COUNTERPARTY", ctx["ps"]["id"])

    lease = get_lease(ctx["lease"]["id"])
    assert lease["open_transfer_count"] == 0, "1 -> 0 at effectiveness"
    assert lease["cumulative_profit_share_cents"] == 0

    settlement = create_settlement(ctx, subrent_collected_cents=6000000)
    finalized = validate_success(api.finalize_settlement(settlement["id"], B1), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"] is not None

    lease = get_lease(ctx["lease"]["id"])
    assert lease["cumulative_profit_share_cents"] == OCTOBER_FULL["landlord"], (
        "ledger sync at finalization"
    )
