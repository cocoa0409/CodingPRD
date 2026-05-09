"""Domain logic: calculations, state transitions, audit log helpers."""
from datetime import timedelta
from decimal import Decimal

from core import (
    AUTO_APPROVAL_THRESHOLD_CENTS,
    AUTO_FRAUD_GATE,
    BLACKLIST_THRESHOLD,
    COLLUSION_PATTERN_THRESHOLD,
    DECAY_PER_FLAG,
    LOOKBACK_DAYS,
    PATTERN_THRESHOLD_CAP,
    W_COLLUSION,
    W_FORGERY,
    W_PATTERN,
    W_RAPID,
    bump,
    db,
    err,
    iso_z,
    new_id,
    now_iso,
    parse_iso,
    round_half_up,
    server_now,
    stamp_create_immutable,
)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def log_audit(claim_id, *, actor_id, actor_role, event_type,
              from_state=None, to_state=None, payload=None):
    rec = stamp_create_immutable()
    rec.update(
        {
            "claim_id": claim_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "event_type": event_type,
            "from_state": from_state,
            "to_state": to_state,
            "payload": payload or {},
        }
    )
    db.audit_log[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Claim number minting
# ---------------------------------------------------------------------------
def mint_claim_number() -> str:
    now = server_now()
    yyyymmdd = now.strftime("%Y%m%d")
    seq = db.claim_daily_seq.get(yyyymmdd, 0) + 1
    db.claim_daily_seq[yyyymmdd] = seq
    return f"CLM-{yyyymmdd}-{seq:04d}"


# ---------------------------------------------------------------------------
# Fraud score
# ---------------------------------------------------------------------------
def compute_fraud_score(claim_id: str) -> Decimal:
    """Weighted-sum fraud score in [0.00, 1.00], 2 decimals, round-half-up once at the end."""
    flags = [f for f in db.fraud_flags.values() if f["claim_id"] == claim_id]
    pattern_sum = Decimal(0)
    collusion_sum = Decimal(0)
    forgery_sum = Decimal(0)
    rapid_sum = Decimal(0)
    for f in flags:
        sev = Decimal(str(f["severity"]))
        sig = f["signal"]
        if sig == "DUPLICATE_PATTERN":
            pattern_sum += sev
        elif sig == "REPAIR_SHOP_COLLUSION":
            collusion_sum += sev
        elif sig == "DOCUMENT_FORGERY":
            forgery_sum += sev
        elif sig == "RAPID_RESUBMISSION":
            rapid_sum += sev
    pattern_capped = min(Decimal(1), pattern_sum)
    collusion_capped = min(Decimal(1), collusion_sum)
    forgery_capped = min(Decimal(1), forgery_sum)
    rapid_capped = min(Decimal(1), rapid_sum)
    raw = (
        W_PATTERN * pattern_capped
        + W_COLLUSION * collusion_capped
        + W_FORGERY * forgery_capped
        + W_RAPID * rapid_capped
    )
    score = round_half_up(raw, 2)
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("1.00"):
        score = Decimal("1.00")
    return score


# ---------------------------------------------------------------------------
# Gross / net payout
# ---------------------------------------------------------------------------
def compute_gross_payout(loss_cents: int, policy: dict) -> int:
    L = int(loss_cents)
    D = int(policy["deductible_cents"])
    C = Decimal(str(policy["coinsurance_ratio"]))
    M = int(policy["coverage_limit_cents"])
    after = max(0, L - D)
    insurer_share_raw = Decimal(after) * C
    insurer_share_cents = int(round_half_up(insurer_share_raw, 0))
    return min(insurer_share_cents, M)


def compute_net_payout(claim: dict) -> int:
    g = int(claim.get("gross_payout_cents") or 0)
    s = int(claim.get("salvage_value_cents") or 0)
    sub = int(claim.get("subrogation_recovery_cents") or 0)
    return max(0, g - s - sub)


# ---------------------------------------------------------------------------
# Repair-shop trust decay (canonical per_flag variant)
# ---------------------------------------------------------------------------
def apply_repair_shop_decay_for_claim(claim_id: str, *, actor_id, actor_role):
    """For each RepairShop implicated in collusion FraudFlags on this claim,
    decay trust_score by DECAY_PER_FLAG per flag (chronological), clamp at 0.
    If new score < BLACKLIST_THRESHOLD, transition to BLACKLISTED.
    """
    flags = [
        f for f in db.fraud_flags.values()
        if f["claim_id"] == claim_id and f["signal"] == "REPAIR_SHOP_COLLUSION"
    ]
    flags.sort(key=lambda f: f["created_at"])
    by_shop = {}
    for f in flags:
        sid = f.get("repair_shop_id")
        if not sid:
            continue
        by_shop.setdefault(sid, []).append(f)
    for shop_id, shop_flags in by_shop.items():
        shop = db.repair_shops.get(shop_id)
        if not shop:
            continue
        cur = Decimal(str(shop["trust_score"]))
        for _ in shop_flags:
            cur = max(Decimal("0.00"), cur - DECAY_PER_FLAG)
        new_score = cur.quantize(Decimal("0.01"))
        prev_status = shop["status"]
        shop["trust_score"] = float(new_score)
        if new_score < BLACKLIST_THRESHOLD and prev_status == "ACTIVE":
            shop["status"] = "BLACKLISTED"
        bump(shop)
        if shop["status"] != prev_status:
            log_audit(
                claim_id,
                actor_id=actor_id, actor_role=actor_role,
                event_type="STATUS_CHANGE",
                from_state=prev_status, to_state=shop["status"],
                payload={"resource": "RepairShop", "repair_shop_id": shop_id, "trust_score": float(new_score)},
            )


def projected_pattern_threshold_score(shop: dict) -> float:
    """Read-only what-if. With >=COLLUSION_PATTERN_THRESHOLD collusion flags
    referencing this shop within the LOOKBACK_DAYS window, projected score
    is min(current_trust_score, PATTERN_THRESHOLD_CAP). Else current_trust_score.
    """
    horizon = server_now() - timedelta(days=LOOKBACK_DAYS)
    cnt = 0
    for f in db.fraud_flags.values():
        if f["signal"] != "REPAIR_SHOP_COLLUSION":
            continue
        if f.get("repair_shop_id") != shop["id"]:
            continue
        try:
            ts = parse_iso(f["created_at"])
        except Exception:
            continue
        if ts >= horizon:
            cnt += 1
    cur = Decimal(str(shop["trust_score"]))
    if cnt >= COLLUSION_PATTERN_THRESHOLD:
        proj = min(cur, PATTERN_THRESHOLD_CAP)
    else:
        proj = cur
    return float(proj.quantize(Decimal("0.01")))


# ---------------------------------------------------------------------------
# Helpers for finding active investigation/payout/appeal
# ---------------------------------------------------------------------------
def get_open_investigation(claim_id: str):
    """Return the OPEN investigation for this claim, if any (max one)."""
    for inv in db.investigations.values():
        if inv["claim_id"] == claim_id and inv["status"] == "OPEN":
            return inv
    return None


def get_active_investigation(claim_id: str):
    """Return any non-REJECTED investigation (OPEN or COMPLETED) for this claim."""
    # Return the most recent non-rejected investigation (used for adjuster-id lookups
    # in segregation-of-duties checks and for review/appeal decision context).
    candidates = [
        inv for inv in db.investigations.values()
        if inv["claim_id"] == claim_id and inv["status"] != "REJECTED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["created_at"], reverse=True)
    return candidates[0]


def get_payout_for_claim(claim_id: str):
    for p in db.payouts.values():
        if p["claim_id"] == claim_id:
            return p
    return None


def get_appeal_for_claim(claim_id: str):
    for a in db.appeals.values():
        if a["claim_id"] == claim_id:
            return a
    return None


def primary_review_decision(claim_id: str):
    rows = [
        d for d in db.review_decisions.values()
        if d["claim_id"] == claim_id and d["review_level"] == "PRIMARY"
    ]
    if not rows:
        return None
    rows.sort(key=lambda x: x["created_at"], reverse=True)
    return rows[0]


def estimate_lines_for_inv(inv_id: str):
    return [e for e in db.estimate_line_items.values() if e["investigation_id"] == inv_id]


# ---------------------------------------------------------------------------
# Days difference
# ---------------------------------------------------------------------------
def whole_days_between(later, earlier) -> int:
    """(later - earlier).days using whole days; both are tz-aware datetimes."""
    return (later - earlier).days
