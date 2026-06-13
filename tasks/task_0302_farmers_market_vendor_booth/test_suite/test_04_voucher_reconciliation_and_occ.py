"""Voucher reconciliation, weather reversal, token-overdraw caps, and the
SEASON-booth optimistic-concurrency check.

Covers Difficulty rules compensating_invariant (voucher), boundary_precision_check
(token cap), resource_temporal_overlap (batch capacity), and the corner OCC and
voucher instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_vendor_headers,
    TEST_USERS,
    create_market, create_booth, create_active_vendor, create_open_market_day,
    create_vendor, booth_version, create_booth_assignment_payload,
    setup_open_day_with_batch, submit_redemption, reconcile_redemption,
    setup_reconciled_redemption,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant (voucher cash ledger)
# ---------------------------------------------------------------------------
def test_weather_reversal_restores_voucher_liability(api):
    """PRD 3.7: "A redemption is reversed — from either SUBMITTED or RECONCILED —
    only by the system when the owning market day is cancelled; reversal resets
    reimbursed_cents to 0 and recomputes the batch's tokens_redeemed and the
    market's voucher_liability_cents, returning the voucher cash ledger to its
    pre-redemption value." 40 tokens * 200 = 8000 liability, restored to 0.

    Design: Difficulty/compensating_invariant/voucher_reversal_restores_liability
    """
    base = setup_reconciled_redemption(tokens_issued=100, token_count=40)
    before = get_success_data(api.get_market(base["market"]["id"], ADMIN))
    assert before["voucher_liability_cents"] == 8000

    validate_success(api.cancel_market_day(
        base["day"]["id"], {"cancellation_reason": "WEATHER"}, ADMIN), 200)

    red_after = get_success_data(api.get_voucher_redemption(base["redemption"]["id"], ADMIN))
    assert red_after["status"] == "REVERSED"
    assert red_after["reimbursed_cents"] == 0

    market_after = get_success_data(api.get_market(base["market"]["id"], ADMIN))
    assert market_after["voucher_liability_cents"] == 0, "restored, zero drift"

    batch_after = get_success_data(api.get_voucher_batch(base["batch"]["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 0


def test_weather_reversal_from_submitted_resets_reimbursement(api):
    """PRD 3.7: "A redemption is reversed — from either SUBMITTED or RECONCILED —
    only by the system when the owning market day is cancelled; reversal resets
    reimbursed_cents to 0". A SUBMITTED redemption (reimbursed_cents already 0)
    moves to REVERSED on weather cancel, and the batch's tokens_redeemed stays 0.

    Design: Difficulty/compensating_invariant/voucher_reversal_restores_liability
    """
    base = setup_open_day_with_batch(tokens_issued=100)
    red = submit_redemption(base["market"]["id"], base["batch"]["id"],
                            base["vendor"]["id"], base["day"]["id"], 25)
    assert red["status"] == "SUBMITTED"

    validate_success(api.cancel_market_day(
        base["day"]["id"], {"cancellation_reason": "WEATHER"}, ADMIN), 200)

    red_after = get_success_data(api.get_voucher_redemption(red["id"], ADMIN))
    assert red_after["status"] == "REVERSED"
    assert red_after["reimbursed_cents"] == 0
    market_after = get_success_data(api.get_market(base["market"]["id"], ADMIN))
    assert market_after["voucher_liability_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check (token cap)
# ---------------------------------------------------------------------------
def test_token_overdraw_one_above_issuance_rejected(api):
    """PRD 3.7: "the running total of RECONCILED token_count for the batch, plus
    this redemption's token_count, must not exceed the batch's tokens_issued; a
    reconcile that would push the batch's reconciled total above its issuance is
    rejected with ERR_TOKEN_OVERDRAW." 40 already reconciled + 11 = 51 > 50.

    Design: Difficulty/boundary_precision_check/token_overdraw_at_exact_issuance_boundary
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    v2 = create_vendor(market["id"], legal_name="V2", contact_email="v2@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 50}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 40)
    reconcile_redemption(r1["id"])
    r2 = submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 11)

    res = api.reconcile_voucher_redemption(r2["id"], MANAGER)
    validate_error(res, "ERR_TOKEN_OVERDRAW")


def test_token_reconcile_at_exact_issuance_boundary_succeeds(api):
    """PRD 3.7: "the running total of RECONCILED token_count for the batch, plus
    this redemption's token_count, must not exceed the batch's tokens_issued" — so
    a cumulative total exactly equal to tokens_issued is allowed (the bar is "above
    its issuance"). 40 already reconciled + 10 = 50 == 50 succeeds.

    Design: Difficulty/boundary_precision_check/token_overdraw_at_exact_issuance_boundary
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    v2 = create_vendor(market["id"], legal_name="V2", contact_email="v2@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 50}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 40)
    reconcile_redemption(r1["id"])
    r2 = submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 10)

    done = validate_success(api.reconcile_voucher_redemption(r2["id"], MANAGER), 200)
    assert done["status"] == "RECONCILED"
    batch_after = get_success_data(api.get_voucher_batch(batch["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 50


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap (aggregate batch capacity)
# ---------------------------------------------------------------------------
def test_batch_aggregate_capacity_overdraw_rejected(api):
    """PRD 3.7: "the running total of RECONCILED token_count for the batch, plus
    this redemption's token_count, must not exceed the batch's tokens_issued ...
    is rejected with ERR_TOKEN_OVERDRAW." 45 RECONCILED + 60 = 105 > 100.

    Design: Difficulty/resource_temporal_overlap/voucher_batch_aggregate_capacity_overlap
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    v2 = create_vendor(market["id"], legal_name="V2", contact_email="v2@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 45)
    reconcile_redemption(r1["id"])
    r2 = submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 60)

    res = api.reconcile_voucher_redemption(r2["id"], MANAGER)
    validate_error(res, "ERR_TOKEN_OVERDRAW")
    r2_after = get_success_data(api.get_voucher_redemption(r2["id"], ADMIN))
    assert r2_after["status"] == "SUBMITTED", "unchanged after rejected reconcile"


def test_batch_aggregate_capacity_within_limit_succeeds(api):
    """PRD 3.7: "the running total of RECONCILED token_count for the batch, plus
    this redemption's token_count, must not exceed the batch's tokens_issued" — an
    aggregate capacity, not a per-redemption one. With 45 already RECONCILED, a
    second reconcile of 40 brings the cumulative to 85 <= 100 and succeeds, leaving
    tokens_redeemed at 85.

    Design: Difficulty/resource_temporal_overlap/voucher_batch_aggregate_capacity_overlap
    """
    market = create_market()
    day = create_open_market_day(market["id"], market_date="2026-06-06")
    v1 = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    v2 = create_vendor(market["id"], legal_name="V2", contact_email="v2@x.com")
    batch = get_success_data(api.create_voucher_batch(
        {"market_id": market["id"], "market_day_id": day["id"], "tokens_issued": 100}, MANAGER))
    r1 = submit_redemption(market["id"], batch["id"], v1["id"], day["id"], 45)
    reconcile_redemption(r1["id"])
    r2 = submit_redemption(market["id"], batch["id"], v2["id"], day["id"], 40)

    done = validate_success(api.reconcile_voucher_redemption(r2["id"], MANAGER), 200)
    assert done["status"] == "RECONCILED"
    batch_after = get_success_data(api.get_voucher_batch(batch["id"], ADMIN))
    assert batch_after["tokens_redeemed"] == 85


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers (OCC)
# ---------------------------------------------------------------------------
def test_season_create_with_matching_booth_version_succeeds(api):
    """PRD 2.8: "the create request must carry expected_booth_version, a
    non-optional field for SEASON requests that holds the version of the target
    booth the client last observed." A matching version succeeds; PRD 3.3: a
    season reservation "sets the booth's status to SEASON_HELD".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_booth_version_succeeds
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    vh = make_vendor_headers(vendor["id"])

    asg = validate_success(api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], vendor["id"],
                                        assignment_type="SEASON",
                                        expected_booth_version=booth["version"]), vh), 201)
    assert asg["status"] == "RESERVED"
    booth_after = get_success_data(api.get_booth(booth["id"], ADMIN))
    assert booth_after["status"] == "SEASON_HELD"


def test_season_create_with_stale_booth_version_rejected(api):
    """PRD 2.8: "If that value does not match the booth's current version — for
    instance because another writer has already reserved a season assignment on
    the booth, taking it from OPEN to SEASON_HELD and advancing the booth's
    version — the create is rejected with ERR_STALE_BOOTH_VERSION at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_booth_version_rejected
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    stale_version = booth["version"]
    v1 = create_active_vendor(market["id"], "CRAFTS", "V1", "v1@x.com")
    v2 = create_active_vendor(market["id"], "FLOWERS", "V2", "v2@x.com")
    vh1 = make_vendor_headers(v1["id"])
    vh2 = make_vendor_headers(v2["id"])

    # V1 reserves SEASON, advancing booth.version past `stale_version`.
    validate_success(api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], v1["id"],
                                        assignment_type="SEASON",
                                        expected_booth_version=stale_version), vh1), 201)

    res = api.create_booth_assignment(
        create_booth_assignment_payload(market["id"], booth["id"], v2["id"],
                                        assignment_type="SEASON", allow_waitlist=True,
                                        expected_booth_version=stale_version), vh2)
    validate_error(res, "ERR_STALE_BOOTH_VERSION")
