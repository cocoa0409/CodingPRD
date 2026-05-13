"""Wallet ledger projection and debit/credit/refund helpers."""
from clock import now, end_of_day_after_days
from db import state, new_id, next_order
from errors import raise_err


def _txn_create(member_id, kind, amount_cents, bucket, service_type=None,
                ref_entity=None, expires_at=None):
    t = {
        "id": new_id(),
        "member_id": member_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "bucket": bucket,
        "service_type": service_type,
        "ref_entity": ref_entity,
        "expires_at": expires_at,
        "created_at": now(),
        "_order": next_order(),
    }
    state["wallet_transactions"][t["id"]] = t
    return t


def _outstanding_bonus_grants(member_id):
    """Return list of (grant_row, outstanding_cents) for unexpired bonus grants,
    ordered by (expires_at ASC, created_at ASC).

    'Outstanding' = grant amount_cents minus sum of DEBIT(bucket=BONUS) rows
    referencing this grant (DEBIT amounts are negative). Also exclude grants
    that have already expired (expires_at <= now).
    """
    txns = list(state["wallet_transactions"].values())
    grants = []
    for t in txns:
        if t["member_id"] != member_id:
            continue
        if t["kind"] != "BONUS_GRANT":
            continue
        # Total consumed/expired against this grant by following ref_entity
        consumed = 0
        for d in txns:
            if d["member_id"] != member_id:
                continue
            if d["bucket"] != "BONUS":
                continue
            if d["kind"] not in ("DEBIT", "BONUS_EXPIRE"):
                continue
            # ref_entity points at grant id
            ref = d.get("ref_entity") or ""
            if ref == f"BONUS_GRANT:{t['id']}" or ref == t["id"]:
                consumed += -d["amount_cents"]  # debits are negative; flip
        outstanding = t["amount_cents"] - consumed
        if outstanding <= 0:
            continue
        # Skip grants past expiry — they've effectively lapsed
        exp = t.get("expires_at")
        if exp is not None and exp <= now():
            continue
        grants.append((t, outstanding))
    # Sort by (expires_at ASC, created_at ASC, _order ASC)
    def sort_key(item):
        g, _ = item
        exp = g.get("expires_at")
        # None expires_at goes last
        return (
            exp if exp is not None else now().replace(year=9999),
            g["created_at"],
            g["_order"],
        )
    grants.sort(key=sort_key)
    return grants


def project_member_balances(member_id):
    """Compute (principal_balance_cents, bonus_balance_cents, earliest_bonus_expiry_or_None)."""
    txns = [t for t in state["wallet_transactions"].values() if t["member_id"] == member_id]
    principal = sum(t["amount_cents"] for t in txns if t["bucket"] == "PRINCIPAL")
    bonus = sum(t["amount_cents"] for t in txns if t["bucket"] == "BONUS")
    grants = _outstanding_bonus_grants(member_id)
    earliest = None
    for g, _ in grants:
        exp = g.get("expires_at")
        if exp is None:
            continue
        if earliest is None or exp < earliest:
            earliest = exp
    return principal, bonus, earliest


def total_balance(member_id) -> int:
    p, b, _ = project_member_balances(member_id)
    return p + b


def principal_balance(member_id) -> int:
    p, _, _ = project_member_balances(member_id)
    return p


def quote_debit(member_id, amount_cents, service_type=None):
    """Walk FIFO consumption order without mutating ledger.

    Returns dict with planned bonus draws and principal draw.
    """
    grants = _outstanding_bonus_grants(member_id)
    need = amount_cents
    bonus_draws = []
    for g, outstanding in grants:
        if need <= 0:
            break
        take = min(outstanding, need)
        bonus_draws.append({
            "grant_id": g["id"],
            "amount_cents": take,
            "expires_at": g.get("expires_at"),
        })
        need -= take
    principal_needed = need
    p_bal = principal_balance(member_id)
    sufficient = principal_needed <= p_bal
    return {
        "requested_amount_cents": amount_cents,
        "bonus_consumed_cents": amount_cents - principal_needed,
        "principal_consumed_cents": principal_needed,
        "bonus_draws": bonus_draws,
        "sufficient": sufficient,
        "service_type": service_type,
    }


def debit(member_id, amount_cents, service_type=None, ref_entity=None):
    """Perform a wallet debit per §3.4.

    Returns list of WalletTransaction rows appended (in order).
    Raises ERR_INSUFFICIENT_BALANCE if principal cannot cover remainder
    after bonus consumption. No partial appends on failure.
    """
    if amount_cents <= 0:
        return []
    grants = _outstanding_bonus_grants(member_id)
    need = amount_cents
    # Plan first
    planned = []
    for g, outstanding in grants:
        if need <= 0:
            break
        take = min(outstanding, need)
        planned.append(("BONUS", take, g))
        need -= take
    # Principal check
    if need > 0:
        if principal_balance(member_id) < need:
            raise_err("ERR_INSUFFICIENT_BALANCE", "Wallet balance insufficient")
    # Commit
    rows = []
    for bucket, amount, grant in planned:
        rows.append(_txn_create(
            member_id, "DEBIT", -amount, "BONUS",
            service_type=service_type,
            ref_entity=f"BONUS_GRANT:{grant['id']}",
        ))
    if need > 0:
        rows.append(_txn_create(
            member_id, "DEBIT", -need, "PRINCIPAL",
            service_type=service_type,
            ref_entity=ref_entity,
        ))
    return rows


def refund_credit(member_id, amount_cents, ref_entity=None):
    """Refund/credit principal only (per §3.4 second-paragraph rule)."""
    if amount_cents <= 0:
        return None
    return _txn_create(
        member_id, "REFUND", amount_cents, "PRINCIPAL",
        ref_entity=ref_entity,
    )


def recharge(member_id, amount_cents):
    """Per §3.3 + calc.recharge_bonus_grant.
    Appends RECHARGE and possibly BONUS_GRANT. Returns list of rows."""
    from .calc import mul_bp_truncate
    rows = []
    rows.append(_txn_create(
        member_id, "RECHARGE", amount_cents, "PRINCIPAL",
        ref_entity=None,
    ))
    # Tier
    if amount_cents >= 100000:
        bp = 2000
    elif amount_cents >= 50000:
        bp = 1000
    elif amount_cents >= 20000:
        bp = 500
    else:
        bp = 0
    bonus_cents = mul_bp_truncate(amount_cents, bp)
    if bonus_cents > 0:
        expires_at = end_of_day_after_days(now(), 365)
        rows.append(_txn_create(
            member_id, "BONUS_GRANT", bonus_cents, "BONUS",
            expires_at=expires_at,
        ))
    return rows
