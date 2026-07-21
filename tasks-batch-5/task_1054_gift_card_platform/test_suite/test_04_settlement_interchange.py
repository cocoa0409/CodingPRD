"""Settlement lifecycle: provisional-vs-final split, tiered interchange, the
merchant-active finalize guard, period-overlap, unsettled conservation on
cancel, segregation of duties, and the OCC stale-version rejection.

Covers Difficulty dual_variant_calc (settlement), combinatorial_formula
(interchange), cross_entity_state_dependency (finalize), resource_temporal_overlap
(settlement), compensating_invariant (merchant unsettled), plus Corner
segregation-of-duties (settlement) and optimistic_concurrency.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_settlement_batch_payload,
    TEST_USERS, make_settlement_officer_headers,
    setup_provisional_vs_final, setup_two_fully_redeemed_cards, open_settlement,
    setup_open_settlement_suspended_merchant, setup_merchant_with_open_settlement_period,
    setup_card_redeemed_open_settlement, create_active_merchant, merchant_version,
    api_client,
)

ANY = TEST_USERS["any_headers"]
OFFICER_1 = make_settlement_officer_headers("officer-1")
OFFICER_2 = make_settlement_officer_headers("officer-2")


# ─────────── Difficulty: provisional-vs-final payout ───────────

def test_provisional_net_payout_includes_all_swept_redemptions(api):
    """PRD §3.7: "At **open** (the provisional view), the gross includes *every* swept redemption, even ones that a later fraud confirm will flip to `REVERSED`; the resulting provisional net is stored in `provisional_net_payout_cents`, and `net_payout_cents` is also set to this provisional view at open, together with the provisional `gross_redemptions_cents` and `interchange_fee_cents`."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final
    """
    scenario = setup_provisional_vs_final()
    settlement = scenario["settlement"]
    # gross 60000 -> interchange max(2500, 60000*300/10000=1800)=2500 -> net 57500
    assert settlement["provisional_net_payout_cents"] == 57500


def test_final_net_payout_excludes_reversed_redemptions(api):
    """PRD §3.7: "At **finalize** (the final view), the gross includes *only* swept redemptions still in `POSTED` status, excluding any that were reversed in the interim, which lowers both the gross and the net."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final
    """
    scenario = setup_provisional_vs_final()
    settlement = scenario["settlement"]
    finalized = validate_success(api.finalize_settlement_batch(settlement["id"], OFFICER_2), 200)
    # remaining POSTED gross 40000 -> interchange max(2500, 40000*300/10000=1200)=2500 -> net 37500
    assert finalized["gross_redemptions_cents"] == 40000
    assert finalized["net_payout_cents"] == 37500


# ─────────── Difficulty: tiered interchange fee (tier 1) ───────────

def test_interchange_tier1_fee_on_gross_200000(api):
    """PRD §3.7: "The fee rate is 300 basis points when the gross is at most 1,000,000 cents, 250 basis points when the gross is greater than that but at most 5,000,000 cents, and 200 basis points when the gross is above 5,000,000 cents. The raw fee is the gross multiplied by the selected rate in basis points, divided by 10000, rounded half up to a whole cent. The `interchange_fee_cents` is then 0 when the gross is 0, and otherwise the greater of 2500 cents and that raw fee"

    Design: Difficulty/combinatorial_formula/interchange_tiered_fee_mode_a
    """
    merchant, _program, _cards = setup_two_fully_redeemed_cards(100000)
    settlement = open_settlement(merchant["id"], officer_id="officer-1")
    assert settlement["gross_redemptions_cents"] == 200000
    assert settlement["interchange_fee_cents"] == 6000  # 200000*300/10000, above 2500 floor


def test_interchange_tier1_net_payout(api):
    """PRD §3.7: "The `net_payout_cents` is the gross redemptions minus the interchange fee."

    Design: Difficulty/combinatorial_formula/interchange_tiered_fee_mode_a
    """
    merchant, _program, _cards = setup_two_fully_redeemed_cards(100000)
    settlement = open_settlement(merchant["id"], officer_id="officer-1")
    assert settlement["net_payout_cents"] == 194000  # 200000 - 6000


# ─────────── Difficulty: finalize requires merchant ACTIVE ───────────

def test_finalize_with_suspended_merchant_rejected(api):
    """PRD §3.7: "Finalizing a batch is permitted only while it is `OPEN` (else `ERR_INVALID_STATE`), only when the acting `X-User-ID` differs from the batch's `opened_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and only when the owning merchant is `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_merchant_active
    """
    _merchant, _program, _card, settlement = setup_open_settlement_suspended_merchant(
        100000, 20000)
    res = api.finalize_settlement_batch(settlement["id"], OFFICER_2)
    validate_error(res, "ERR_MERCHANT_NOT_ACTIVE")


def test_finalize_with_suspended_merchant_leaves_batch_open(api):
    """PRD §3.7: "Finalizing a batch is permitted only while it is `OPEN` (else `ERR_INVALID_STATE`), only when the acting `X-User-ID` differs from the batch's `opened_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and only when the owning merchant is `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_merchant_active
    """
    _merchant, _program, _card, settlement = setup_open_settlement_suspended_merchant(
        100000, 20000)
    api.finalize_settlement_batch(settlement["id"], OFFICER_2)
    after = validate_success(api.get_settlement_batch(settlement["id"], ANY), 200)
    assert after["status"] == "OPEN"


# ─────────── Difficulty: half-open settlement period overlap ───────────

def test_overlapping_settlement_period_rejected(api):
    """PRD §3.7: "A new period `[period_start, period_end)` must not overlap any other non-`CANCELLED` settlement batch of that merchant; overlap is rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP`, while the half-open convention means two batches that merely touch at an endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/settlement_period_halfopen_overlap
    """
    merchant, _first = setup_merchant_with_open_settlement_period(
        "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    version = merchant_version(merchant["id"])
    res = api.open_settlement_batch(
        create_settlement_batch_payload(
            merchant["id"], "2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z", version), OFFICER_1)
    validate_error(res, "ERR_SETTLEMENT_PERIOD_OVERLAP")


def test_touching_settlement_period_allowed(api):
    """PRD §3.7: "A new period `[period_start, period_end)` must not overlap any other non-`CANCELLED` settlement batch of that merchant; overlap is rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP`, while the half-open convention means two batches that merely touch at an endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/settlement_period_halfopen_overlap
    """
    merchant, _first = setup_merchant_with_open_settlement_period(
        "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    version = merchant_version(merchant["id"])
    res = api.open_settlement_batch(
        create_settlement_batch_payload(
            merchant["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", version), OFFICER_1)
    batch = validate_success(res, 201)
    assert batch["status"] == "OPEN"


# ─────────── Difficulty: merchant unsettled conserved across open+cancel ───────────

def test_cancel_restores_merchant_unsettled_to_preopen_value(api):
    """PRD §3.7: "Cancelling a batch is permitted only while it is `OPEN` (else `ERR_INVALID_STATE`); it releases the sweep by clearing `settlement_batch_id` back to null on every swept `REDEMPTION` entry, restores the merchant's `unsettled_redemptions_cents` to its pre-open value, and moves the batch to the terminal `CANCELLED` state."

    Design: Difficulty/compensating_invariant/merchant_unsettled_conserved_open_cancel
    """
    merchant, _program, _card, settlement = setup_card_redeemed_open_settlement(100000, 20000)
    validate_success(api.cancel_settlement_batch(settlement["id"], OFFICER_1), 200)
    after = validate_success(api.get_merchant(merchant["id"], ANY), 200)
    assert after["unsettled_redemptions_cents"] == 20000


def test_open_drops_then_cancel_restores_merchant_unsettled(api):
    """PRD §3.7: "opening the batch sweeps every one of the merchant's `POSTED` `REDEMPTION` entries whose `settlement_batch_id` is null into the batch (stamping that `settlement_batch_id` onto each), records the officer's `X-User-ID` as `opened_by_user_id`, starts the batch in `OPEN` status, computes the provisional payout, advances the merchant's `version` by 1, and recomputes the merchant's `unsettled_redemptions_cents`."

    Design: Difficulty/compensating_invariant/merchant_unsettled_conserved_open_cancel
    """
    merchant, _program, _card, settlement = setup_card_redeemed_open_settlement(100000, 20000)
    swept = validate_success(api.get_merchant(merchant["id"], ANY), 200)
    assert swept["unsettled_redemptions_cents"] == 0  # the redemption is now inside the batch
    validate_success(api.cancel_settlement_batch(settlement["id"], OFFICER_1), 200)
    restored = validate_success(api.get_merchant(merchant["id"], ANY), 200)
    assert restored["unsettled_redemptions_cents"] == 20000


# ─────────── Corner: SoD on finalize + OCC stale merchant version ───────────

def test_finalize_by_opening_officer_rejected(api):
    """PRD §2.10: "Confirming a fraud hold requires that `X-User-ID` differ from the hold's `opened_by_user_id`; finalizing a settlement batch requires that `X-User-ID` differ from the batch's `opened_by_user_id`. In either case a match — the same operator attempting both sides — is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/settlement_finalize_same_officer_returns_sod
    """
    merchant = create_active_merchant()
    settlement = open_settlement(merchant["id"], officer_id="officer-1")  # empty sweep
    res = api.finalize_settlement_batch(settlement["id"], OFFICER_1)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_open_settlement_with_stale_merchant_version_rejected(api):
    """PRD §2.9: "A request to open a settlement batch must carry `expected_merchant_version`, and this value must equal the merchant's current `version` at the time the request is processed. Opening a batch sweeps the merchant's un-settled redemptions into it and then advances the merchant's `version`; a subsequent open request still carrying the pre-open value is therefore acting on a stale view — the redemptions it means to sweep were already claimed by the batch that advanced the version — and it is rejected with `ERR_STALE_MERCHANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/settlement_open_stale_merchant_version_returns_412
    """
    merchant = create_active_merchant()
    stale_version = merchant_version(merchant["id"])
    # Batch A advances the merchant version.
    validate_success(api.open_settlement_batch(
        create_settlement_batch_payload(
            merchant["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", stale_version),
        OFFICER_1), 201)
    # Batch B, non-overlapping period, still carrying the pre-A version -> stale.
    res = api.open_settlement_batch(
        create_settlement_batch_payload(
            merchant["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", stale_version),
        OFFICER_1)
    validate_error(res, "ERR_STALE_MERCHANT_VERSION")
