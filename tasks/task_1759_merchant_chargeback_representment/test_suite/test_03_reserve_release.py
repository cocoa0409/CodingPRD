"""Voluntary reserve release: waterfall, program lock, and funds floor. Also
the HIGH_RISK holdback ledger-fold invariant across the win/pre-arb cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_reserve_ledger_fold,
    create_enrollment,
    create_merchant,
    get_merchant,
    get_success_data,
    ingest_sales_batch,
    ledger_entries,
    post_outcome,
    reserve_account_for,
    setup_submitted_case,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def _setup_zero_pool_merchant(api):
    """1000 bps merchant with 10 recent sales (unmatured at the default clock)."""
    m = create_merchant(api, legal_name="Zero Pool M", reserve_rate_bps=1000)
    ingest_sales_batch(api, m["id"], "Z", 10, 10000, "2026-07-25T00:00:00Z")
    return m, reserve_account_for(api, m["id"])


def test_zero_matured_pool_release_rejected(api):
    """PRD §3.3: "the matured pool is the sum of all `HOLD` entries whose
    `source_kind` is `TRANSACTION_SETTLEMENT` and whose `release_eligible_at`
    is on or before now, minus the sum of all prior `RELEASE` entries whose
    `source_kind` is `SCHEDULED_RELEASE`" ... "If the release amount is not
    positive, the release is rejected with `ERR_NO_RELEASABLE_FUNDS`."

    Design: Difficulty/boundary_precision_check/zero_matured_pool_release_rejected
    """
    _m, ra = _setup_zero_pool_merchant(api)
    # Settlement holds exist (10 x 1000) but none has matured at 2026-08-01
    # (release_eligible_at 2026-10-23), and held == target == 10000.
    assert ra["held_cents"] == 10000
    assert ra["target_cents"] == 10000

    resp = api.release_reserve(ra["id"], RISK)
    validate_error(resp, ApiErrorId.ERR_NO_RELEASABLE_FUNDS)


def test_zero_matured_pool_release_creates_no_ledger_entry(api):
    """PRD §3.3: "Otherwise a `RELEASE` entry with `source_kind`
    `SCHEDULED_RELEASE` is posted for the release amount, `held_cents` is
    refolded" — a rejected release is not "otherwise", so the ledger and the
    fold are untouched.

    Design: Difficulty/boundary_precision_check/zero_matured_pool_release_rejected
    """
    _m, ra = _setup_zero_pool_merchant(api)
    before = ledger_entries(api, ra["id"])

    resp = api.release_reserve(ra["id"], RISK)
    validate_error(resp, ApiErrorId.ERR_NO_RELEASABLE_FUNDS)

    after_account = get_success_data(api.get_reserve_account(ra["id"], RISK))
    assert after_account["held_cents"] == 10000
    assert ledger_entries(api, ra["id"]) == before


def _setup_locked_merchant(api):
    """Zero-pool merchant that is also under an ACTIVE program enrollment —
    both the compliance lock and the funds floor are violated at once."""
    m, ra = _setup_zero_pool_merchant(api)
    enr = create_enrollment(api, m["id"], enrolled_month="2026-07")
    assert enr["status"] == "ACTIVE"
    return m, ra, enr


def test_release_program_lock_outranks_funds_floor(api):
    """PRD §3.3: "It is blocked outright while any program enrollment of the
    merchant is `ACTIVE` or in `REMEDIATION` — the compliance lock outranks
    funds availability and rejects with `ERR_PROGRAM_RESERVE_LOCK`."

    Design: Difficulty/priority_pair_validation_conflict/release_safety_outranks_fiscal
    """
    _m, ra, _enr = _setup_locked_merchant(api)
    resp = api.release_reserve(ra["id"], RISK)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_RESERVE_LOCK)


def test_release_program_lock_creates_no_ledger_entry(api):
    """PRD §3.3: "Otherwise a `RELEASE` entry with `source_kind`
    `SCHEDULED_RELEASE` is posted for the release amount, `held_cents` is
    refolded" — the lock rejection posts nothing and leaves the fold intact.

    Design: Difficulty/priority_pair_validation_conflict/release_safety_outranks_fiscal
    """
    _m, ra, _enr = _setup_locked_merchant(api)
    resp = api.release_reserve(ra["id"], RISK)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_RESERVE_LOCK)

    after = get_success_data(api.get_reserve_account(ra["id"], RISK))
    assert after["held_cents"] == 10000
    assert all(e["entry_type"] == "HOLD" for e in ledger_entries(api, ra["id"]))


def test_release_success_releases_matured_pool_down_to_target(api):
    """PRD §3.3: "The releasable amount is the matured pool floored at zero,
    and the release amount is the smaller of that releasable amount and the
    excess of `held_cents` over `target_cents`, the excess likewise floored at
    zero." and "a `RELEASE` entry with `source_kind` `SCHEDULED_RELEASE` is
    posted for the release amount, `held_cents` is refolded, and the merchant's
    `clearing_balance_cents` increases by the released amount."

    Design: Corner/cross_cutting/release_success_matured_partial
    """
    # Default clock 2026-08-01: the 2026-04-15 sales matured on 2026-07-14;
    # the 2026-07-25 sales have not. The trailing-90d window starts
    # 2026-05-03, so only the 20 July sales feed the target.
    m = create_merchant(api, legal_name="Release M", reserve_rate_bps=1000)
    ingest_sales_batch(api, m["id"], "OLD", 10, 10000, "2026-04-15T00:00:00Z")
    ingest_sales_batch(api, m["id"], "NEW", 20, 10000, "2026-07-25T00:00:00Z")
    ra = reserve_account_for(api, m["id"])
    assert ra["held_cents"] == 30000  # 30 holds of 1000
    assert ra["target_cents"] == 20000  # 10% of the 200000 in-window sales

    resp = api.release_reserve(ra["id"], RISK)
    after = validate_success(resp)
    # min(matured pool 10000, held-target headroom 10000) = 10000.
    assert after["held_cents"] == 20000
    assert after["target_cents"] == 20000

    entries = ledger_entries(api, ra["id"])
    release_entries = [e for e in entries if e["source_kind"] == "SCHEDULED_RELEASE"]
    assert len(release_entries) == 1
    assert release_entries[0]["entry_type"] == "RELEASE"
    assert release_entries[0]["amount_cents"] == 10000
    assert release_entries[0]["source_id"] is None

    # 30 x (10000-1000) net settlement credits, plus the 10000 release.
    assert get_merchant(api, m["id"])["clearing_balance_cents"] == 280000


def _setup_fold_cycle(api):
    """HIGH_RISK merchant at rate 0 (no settlement holds; only case-bound
    holdbacks) with one full-amount chargeback fought to SUBMITTED."""
    bundle = setup_submitted_case(
        api,
        required_types=("RECEIPT",),
        merchant_overrides={"risk_tier": "HIGH_RISK", "reserve_rate_bps": 0},
        received_at="2026-07-15T00:00:00Z",
    )
    ra = reserve_account_for(api, bundle["merchant"]["id"])
    return bundle, ra


def test_reserve_hold_release_hold_forfeit_trajectory(api):
    """PRD §3.5: "For a `HIGH_RISK` merchant there is a further cascade: a
    reserve `HOLD` entry for the full disputed amount is posted with
    `source_kind` `CHARGEBACK_RECEIPT`".
    PRD §3.7: "For a `HIGH_RISK` merchant the receipt holdback is unwound: a
    `RELEASE` entry for the disputed amount posts with `source_kind`
    `CHARGEBACK_WON`" and pre-arbitration "restores the holdback with a fresh
    case-bound `HOLD` entry (`source_kind` `CHARGEBACK_RECEIPT`, null
    maturity)".

    Design: Difficulty/compensating_invariant/reserve_units_hold_release_fold_invariant
    """
    bundle, ra = _setup_fold_cycle(api)
    cb_id = bundle["chargeback"]["id"]
    rep_id = bundle["representment"]["id"]

    def held():
        return get_success_data(api.get_reserve_account(ra["id"], RISK))["held_cents"]

    assert held() == 10000  # receipt holdback posted
    post_outcome(api, rep_id, "WON")
    assert held() == 0  # CHARGEBACK_WON RELEASE compensates the receipt HOLD
    get_success_data(api.escalate_pre_arbitration(cb_id, OPS))
    assert held() == 10000  # pre-arb re-debit restores the holdback
    get_success_data(api.pre_arbitration_outcome(cb_id, {"decision": "LOST"}, OPS))
    assert held() == 0  # CHARGEBACK_LOST FORFEIT compensates the restored hold


def test_reserve_ledger_fold_equals_held_after_full_cycle(api):
    """PRD §3.3: "An account's `held_cents` is the fold of its ledger: the sum
    of all `HOLD` amounts minus the sum of all `RELEASE` amounts minus the sum
    of all `FORFEIT` amounts, and it is never negative by construction."
    PRD §3.7: "a `decision` of `LOST` moves the case to the terminal
    `DECIDED_LOST` ... and the holdback forfeited through a `CHARGEBACK_LOST`
    entry."

    Design: Difficulty/compensating_invariant/reserve_units_hold_release_fold_invariant
    """
    bundle, ra = _setup_fold_cycle(api)
    cb_id = bundle["chargeback"]["id"]
    rep_id = bundle["representment"]["id"]
    post_outcome(api, rep_id, "WON")
    get_success_data(api.escalate_pre_arbitration(cb_id, OPS))
    get_success_data(api.pre_arbitration_outcome(cb_id, {"decision": "LOST"}, OPS))

    entries = ledger_entries(api, ra["id"])
    # HOLD(receipt) -> RELEASE(won) -> HOLD(pre-arb restore) -> FORFEIT(lost).
    assert [(e["entry_type"], e["amount_cents"]) for e in entries] == [
        ("HOLD", 10000),
        ("RELEASE", 10000),
        ("HOLD", 10000),
        ("FORFEIT", 10000),
    ]
    assert [e["source_kind"] for e in entries] == [
        "CHARGEBACK_RECEIPT",
        "CHARGEBACK_WON",
        "CHARGEBACK_RECEIPT",
        "CHARGEBACK_LOST",
    ]
    final = get_success_data(api.get_reserve_account(ra["id"], RISK))
    assert_reserve_ledger_fold(entries, final["held_cents"])
    assert final["held_cents"] == 0  # four compensating entries net to zero
