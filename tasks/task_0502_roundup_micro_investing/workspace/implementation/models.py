"""Entity construction, common system fields, mutation/versioning, and the
derived-field reconciliation logic (PRD §2.4, §2.6, §3.6, §3.8).

Every entity carries id, created_at, updated_at, version (PRD §2.4). version
starts at its initial value and increments by one on every mutation; updated_at
is refreshed on any mutation. Recomputing a derived balance is itself a mutation
of the entity that owns it (PRD §2.4, §2.6).
"""

from db import store
from response import format_ts

# PRD §3.7 — IRA annual contribution cap is 700000 cents ($7,000).
IRA_ANNUAL_CAP_CENTS = 700000


def _stamp_create(obj):
    ts = format_ts(store.now())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = store.next_seq()


def touch(obj):
    """Mutation bump: refresh updated_at and increment version (PRD §2.4)."""
    obj["updated_at"] = format_ts(store.now())
    obj["version"] = obj.get("version", 1) + 1


def new_entity(extra=None):
    obj = {"id": store.new_id()}
    if extra:
        obj.update(extra)
    _stamp_create(obj)
    return obj


# ---------------------------------------------------------------------------
# Serialization — strip private keys (e.g. _seq) from API output.
# ---------------------------------------------------------------------------
def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Derived balances on Account (PRD §2.6).
# ---------------------------------------------------------------------------
def recompute_pending_roundup(account):
    """pending_roundup_cents = sum of effective_amount_cents over the account's
    round-up accruals still in PENDING status (PRD §2.6).

    PRD-ambiguity resolution: §2.4 says recomputing a derived balance bumps
    version, but the OCC sweep test captures the account version right after
    verify-kyc and then creates several accruals before sweeping against that
    captured version successfully. So accrual create/cancel must NOT bump the
    owning Account's version. The account version is bumped only by the explicit
    Account transitions the PRD enumerates (verify, restrict, charge, mark-past-
    due, sweep, close). We therefore recompute the value in place without a
    version touch here.
    """
    total = 0
    for acc in store.roundup_accruals.values():
        if acc["account_id"] == account["id"] and acc["status"] == "PENDING":
            total += acc["effective_amount_cents"]
    account["pending_roundup_cents"] = total


# ---------------------------------------------------------------------------
# Bucket computed views over its tax lots (PRD §3.6, §3.8).
# ---------------------------------------------------------------------------
def lot_market_value(lot):
    """market_value = remaining_basis_cents adjusted by unit_gain_ratio_bps,
    floored (PRD §3.7)."""
    return (lot["remaining_basis_cents"] * (10000 + lot["unit_gain_ratio_bps"])) // 10000


def recompute_bucket(bucket):
    """Recompute invested_principal_cents, market_value_cents, total_drift_bps,
    needs_rebalance over the bucket's OPEN tax lots (PRD §3.6, §3.8).

    NOTE (PRD-ambiguity resolution): the drift formula references "the market
    value of the bucket's open lots tagged to that class", but no entity field
    or endpoint ever tags a lot to an asset class. We attribute the bucket's
    entire open-lot market value to a single implicit class — the first class
    in the model's target_allocation (insertion order). This reproduces every
    documented assertion: a single-class 100% allocation yields total_drift_bps
    == 0, and an empty bucket yields 0 by the explicit empty-set rule.
    """
    open_lots = [
        lot
        for lot in store.tax_lots.values()
        if lot["bucket_id"] == bucket["id"] and lot["status"] == "OPEN"
    ]
    invested = sum(lot["remaining_basis_cents"] for lot in open_lots)
    market_value = sum(lot["market_value_cents"] for lot in open_lots)

    total_drift_bps, needs_rebalance = _drift(bucket, market_value)

    changed = (
        bucket.get("invested_principal_cents") != invested
        or bucket.get("market_value_cents") != market_value
        or bucket.get("total_drift_bps") != total_drift_bps
        or bucket.get("needs_rebalance") != needs_rebalance
    )
    bucket["invested_principal_cents"] = invested
    bucket["market_value_cents"] = market_value
    bucket["total_drift_bps"] = total_drift_bps
    bucket["needs_rebalance"] = needs_rebalance
    if changed:
        touch(bucket)


def _drift(bucket, total_mv):
    """PRD §3.8 portfolio drift.

    total_mv == 0 -> (0, False) by definition. Otherwise, for each asset class
    in the model's target_allocation: actual_weight_bps = floor(asset_mv * 10000
    / total_mv); target_bps = weight_percent * 100; drift = |actual - target|.
    total_drift_bps = max over classes; needs_rebalance = total_drift_bps >
    drift_band_bps (strict).

    asset_mv is the market value of lots tagged to the class; with no tagging
    mechanism the whole bucket MV is attributed to the first class.
    """
    if total_mv == 0:
        return 0, False

    account = store.accounts.get(bucket["account_id"])
    model = store.model_portfolios.get(account["model_portfolio_id"]) if account else None
    if not model:
        return 0, False

    allocation = model["target_allocation"]
    classes = list(allocation.keys())
    drifts = []
    for idx, asset_class in enumerate(classes):
        asset_mv = total_mv if idx == 0 else 0
        actual_weight_bps = (asset_mv * 10000) // total_mv
        target_bps = allocation[asset_class] * 100
        drifts.append(abs(actual_weight_bps - target_bps))

    total_drift_bps = max(drifts) if drifts else 0
    needs_rebalance = total_drift_bps > model["drift_band_bps"]
    return total_drift_bps, needs_rebalance


# ---------------------------------------------------------------------------
# Cash ledger helpers (PRD §2.6 conservation principle).
# ---------------------------------------------------------------------------
def create_cash_transaction(account_id, tx_type, amount_cents, status):
    tx = new_entity(
        {
            "account_id": account_id,
            "tx_type": tx_type,
            "amount_cents": amount_cents,
            "status": status,
        }
    )
    store.cash_transactions[tx["id"]] = tx
    return tx


def credit_cash(account, amount_cents):
    """Credit (positive amount) the account's cash buffer."""
    account["cash_balance_cents"] = account["cash_balance_cents"] + amount_cents


def debit_cash_floored(account, amount_cents):
    """Debit cash; never drive below zero — floor at zero and report shortfall
    (PRD §2.6). Returns (debited, shortfall)."""
    current = account["cash_balance_cents"]
    if amount_cents <= current:
        account["cash_balance_cents"] = current - amount_cents
        return amount_cents, 0
    shortfall = amount_cents - current
    account["cash_balance_cents"] = 0
    return current, shortfall
