"""Settlement ingest (single and batch), reserve holds, and the reserve target."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_chargeback,
    assert_reserve_ledger_entry,
    create_merchant,
    create_rule,
    get_merchant,
    get_success_data,
    ingest_chargeback,
    ingest_sale,
    ingest_sales_batch,
    ledger_entries,
    reserve_account_for,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_batch_ingest_mints_deterministic_external_refs(api):
    """PRD §3.3: "given a `merchant_id`, `network`, `count`, `amount_cents`,
    `occurred_at`, and `external_ref_prefix`, it creates `count` identical
    transactions whose `external_ref` is the prefix followed by a hyphen and a
    zero-padded four-digit sequence number running from 0001 up to `count`,
    applying the same per-transaction side effects in ascending sequence order,
    and reports `created_count`, `first_external_ref`, and `last_external_ref`."

    Design: Corner/endpoints/batch_ingest_deterministic_refs
    """
    create_rule(api)
    m = create_merchant(api, legal_name="Batch M", reserve_rate_bps=0)
    result = ingest_sales_batch(api, m["id"], "Q", 3, 10000, "2026-07-10T00:00:00Z")
    assert result["created_count"] == 3
    assert result["first_external_ref"] == "Q-0001"
    assert result["last_external_ref"] == "Q-0003"

    # The batch-minted ref resolves the disputed sale without any id capture.
    cb = ingest_chargeback(api, m["id"], "Q-0002", "NC-Q2", 4000)
    assert_chargeback(cb)
    assert cb["case_status"] == "RECEIVED"


def test_duplicate_external_ref_scoped_per_merchant(api):
    """PRD §3.3: "`AcquirerOps` supplies the `merchant_id`, a merchant-scoped
    `external_ref` (an ARN-style reference, unique within that merchant — a
    duplicate is rejected with `ERR_DUPLICATE_EXTERNAL_REF`)".

    Design: Corner/validations/duplicate_external_ref_scoped_per_merchant
    """
    m1 = create_merchant(api, legal_name="RefA", reserve_rate_bps=0)
    m2 = create_merchant(api, legal_name="RefB", reserve_rate_bps=0)
    ingest_sale(api, m1["id"], "T-1", 10000, "2026-07-10T00:00:00Z")

    dup = api.create_transaction(
        {
            "merchant_id": m1["id"],
            "external_ref": "T-1",
            "network": "VISA",
            "amount_cents": 5000,
            "occurred_at": "2026-07-11T00:00:00Z",
        },
        OPS,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF)

    other = api.create_transaction(
        {
            "merchant_id": m2["id"],
            "external_ref": "T-1",
            "network": "VISA",
            "amount_cents": 5000,
            "occurred_at": "2026-07-11T00:00:00Z",
        },
        OPS,
    )
    data = validate_success(other, 201)
    assert data["status"] == "SETTLED"


def test_transaction_ingest_for_suspended_merchant_rejected(api):
    """PRD §3.3: "Ingest requires the merchant to be `ACTIVE`, failing with
    `ERR_MERCHANT_NOT_ACTIVE` otherwise."

    Design: Corner/validations/txn_ingest_for_suspended_merchant_rejected
    """
    m = create_merchant(api, legal_name="SuspTxn M", reserve_rate_bps=0)
    get_success_data(api.suspend_merchant(m["id"], RISK))

    resp = api.create_transaction(
        {
            "merchant_id": m["id"],
            "external_ref": "T-1",
            "network": "VISA",
            "amount_cents": 10000,
            "occurred_at": "2026-07-25T00:00:00Z",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_MERCHANT_NOT_ACTIVE)


def test_trailing_90d_window_closed_both_ends(api):
    """PRD §3.3: "the trailing window is closed on both ends — transactions
    with `occurred_at` on or after the instant ninety days before now and on or
    before now count."

    Design: Corner/calculations/trailing_90d_window_boundary
    """
    # Default clock 2026-08-01T00:00:00Z -> window start 2026-05-03T00:00:00Z.
    m = create_merchant(api, legal_name="Trail M", reserve_rate_bps=1000)
    ingest_sale(api, m["id"], "T-A", 100000, "2026-05-03T00:00:00Z")
    ingest_sale(api, m["id"], "T-B", 100000, "2026-05-02T23:59:59Z")

    account = reserve_account_for(api, m["id"])
    # Only sale A is inside the closed window: round_half_up(1000 x 100000 / 10000).
    assert account["target_cents"] == 10000
    # Settlement holds accrue per transaction irrespective of the target window.
    assert account["held_cents"] == 20000


def test_reserve_ledger_append_only_across_target_recompute(api):
    """PRD §3.3: "The ledger is append-only" ... "The target is recomputed on
    transaction ingest, on any chargeback funds-axis transition, on a
    reserve-policy patch, and at the monthly sweep; each recomputation stamps
    `last_recomputed_at` and never creates ledger entries by itself."

    Design: Corner/entities/reserve_ledger_append_only
    """
    create_rule(api)
    m = create_merchant(api, legal_name="Ledger M", risk_tier="HIGH_RISK",
                        reserve_rate_bps=500)
    ingest_sale(api, m["id"], "T-1", 10000, "2026-07-25T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "T-1", "NC-L1", 5000)
    assert cb["case_status"] == "RECEIVED"

    ra = reserve_account_for(api, m["id"])
    pre = ledger_entries(api, ra["id"])
    assert len(pre) == 2
    for entry in pre:
        assert_reserve_ledger_entry(entry)
    assert (pre[0]["amount_cents"], pre[0]["source_kind"]) == (500, "TRANSACTION_SETTLEMENT")
    assert (pre[1]["amount_cents"], pre[1]["source_kind"]) == (5000, "CHARGEBACK_RECEIPT")

    version = get_merchant(api, m["id"])["version"]
    resp = api.patch_reserve_policy(
        m["id"], {"reserve_rate_bps": 700, "expected_merchant_version": version}, RISK
    )
    validate_success(resp)

    post = ledger_entries(api, ra["id"])
    assert post == pre, "target recompute must not create or rewrite ledger entries"


def test_occ_stale_reserve_policy_patch_rejected(api):
    """PRD §3.1: "the request must carry `expected_merchant_version`, a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful
    patch bumps the merchant's `version` by one."

    Design: Corner/cross_cutting/occ_stale_reserve_policy_patch_rejected
    """
    m = create_merchant(api, legal_name="OCCP M", reserve_rate_bps=500)
    observed_version = m["version"]

    first = api.patch_reserve_policy(
        m["id"],
        {"reserve_rate_bps": 750, "expected_merchant_version": observed_version},
        RISK,
    )
    patched = validate_success(first)
    assert patched["reserve_rate_bps"] == 750
    assert patched["version"] == observed_version + 1

    replay = api.patch_reserve_policy(
        m["id"],
        {"reserve_rate_bps": 900, "expected_merchant_version": observed_version},
        RISK,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)


def _setup_rounding_pair(api):
    """STANDARD merchant at 333 bps with two 999-cent sales."""
    m = create_merchant(api, legal_name="Round M", reserve_rate_bps=333)
    ingest_sale(api, m["id"], "R-1", 999, "2026-07-25T00:00:00Z")
    ingest_sale(api, m["id"], "R-2", 999, "2026-07-25T00:00:00Z")
    return m


def test_reserve_hold_rounded_per_entry_then_summed(api):
    """PRD §2.6: "One ordering rule is pinned for the rolling reserve: each
    per-transaction hold is rounded to whole cents first, and account balances
    are then folded from those individually rounded entries — rounding only at
    the aggregate level is not permitted (§3.3)."
    PRD §3.3: "The per-transaction hold is the sale's `amount_cents` multiplied
    by the merchant's `reserve_rate_bps` and divided by ten thousand, rounded
    half-up to a whole cent".

    Design: Difficulty/combinatorial_formula/reserve_hold_per_entry_rounding_order
    """
    m = _setup_rounding_pair(api)
    ra = reserve_account_for(api, m["id"])
    entries = ledger_entries(api, ra["id"])
    # round_half_up(999 x 333 / 10000) = round_half_up(33.2667) = 33 per entry.
    assert [e["amount_cents"] for e in entries] == [33, 33]
    # Sum of rounded entries is 66; the sum-then-round value 67 is forbidden.
    assert ra["held_cents"] == 66


def test_reserve_hold_rounding_target_and_clearing_use_same_entries(api):
    """PRD §3.3: "the rate floor: the merchant's `reserve_rate_bps` multiplied
    by the merchant's trailing ninety-day sales total and divided by ten
    thousand, rounded half-up to whole cents" and "Each ingestion credits the
    merchant's `clearing_balance_cents` by the sale amount net of the
    per-transaction reserve hold".

    Design: Difficulty/combinatorial_formula/reserve_hold_per_entry_rounding_order
    """
    m = _setup_rounding_pair(api)
    ra = reserve_account_for(api, m["id"])
    # Aggregate target rounds once over the 1998-cent window total: 67.
    assert ra["target_cents"] == 67
    # Clearing sees the per-entry holds: 2 x (999 - 33) = 1932.
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 1932


def _setup_dual_variant_merchant(api):
    """STANDARD merchant, 1000 bps, 100x10000 + 1x500000 sales occurred
    2026-07-25 (inside the trailing window at the default clock), and one open
    300000-cent chargeback against the large sale. Returns (merchant, account)."""
    create_rule(api)
    m = create_merchant(api, legal_name="Reserve M", reserve_rate_bps=1000)
    ingest_sales_batch(api, m["id"], "B", 100, 10000, "2026-07-25T00:00:00Z")
    ingest_sale(api, m["id"], "BIG-1", 500000, "2026-07-25T00:00:00Z")
    cb = ingest_chargeback(api, m["id"], "BIG-1", "NC-B1", 300000)
    assert cb["funds_status"] == "MERCHANT_DEBITED"
    return m, reserve_account_for(api, m["id"])


def test_reserve_target_fixed_tier_ignores_open_exposure(api):
    """PRD §3.3: "Under `FIXED_TIER`, the target equals this floor and open
    exposure is ignored."

    Design: Difficulty/dual_variant_calc/reserve_target_fixed_tier_vs_exposure_based
    """
    _m, ra = _setup_dual_variant_merchant(api)
    # rate floor: round_half_up(1000 bps x 1,500,000 trailing sales / 10000).
    assert ra["target_cents"] == 150000
    # 100 holds of 1000 plus one hold of 50000; STANDARD has no receipt holdback.
    assert ra["held_cents"] == 150000


def test_reserve_target_exposure_based_takes_max_with_open_exposure(api):
    """PRD §3.3: "Under `EXPOSURE_BASED`, the target is the greater of the rate
    floor and two times the merchant's open exposure, where open exposure is
    the sum of `amount_cents` over the merchant's chargebacks whose
    `case_status` is `RECEIVED`, `MERCHANT_NOTIFIED`, `REPRESENTED`, or
    `PRE_ARBITRATION` and whose `funds_status` is `MERCHANT_DEBITED`."
    PRD §3.1: "The patch also recomputes the reserve account's `target_cents`
    under the newly written policy; a target recomputation never creates ledger
    entries by itself."

    Design: Difficulty/dual_variant_calc/reserve_target_fixed_tier_vs_exposure_based
    """
    m, ra = _setup_dual_variant_merchant(api)
    entries_before = ledger_entries(api, ra["id"])
    version = get_merchant(api, m["id"])["version"]
    resp = api.patch_reserve_policy(
        m["id"], {"reserve_mode": "EXPOSURE_BASED", "expected_merchant_version": version},
        RISK,
    )
    validate_success(resp)

    after = get_success_data(api.get_reserve_account(ra["id"], RISK))
    # max(150000 rate floor, 2 x 300000 open exposure) — variant-selected divergence.
    assert after["target_cents"] == 600000
    assert after["held_cents"] == 150000
    # The target recompute created no ledger entries.
    assert ledger_entries(api, ra["id"]) == entries_before
