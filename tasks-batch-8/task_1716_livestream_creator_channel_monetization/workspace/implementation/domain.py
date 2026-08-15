"""Domain logic: derived (computed) fields, channel posture machine and its
payout hold/release cascades, viewer standing, score/balance derivations, and
per-entity serializers.

Derivation policy: every `source: computed` field is derived on read from the
store + logical clock, so reads can never go stale. Cascades (payout holds,
subscription cancels, perk voids) mutate child rows eagerly at the moment the
triggering transition executes, each with its own version bump + updated_at.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db
from core import iso, month_label, rhu

SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 2, "SEVERE": 3}
ACTIVE_STRIKE_STATUSES = ("ISSUED", "UNDER_APPEAL", "UPHELD")
IN_FLIGHT_PAYOUT = ("SCHEDULED", "PROCESSING", "FAILED", "HELD")

VOLUME_REBATE_THRESHOLD_CENTS = 5000000
VOLUME_REBATE_BPS = 250
WITHHOLDING_BPS_W8 = 3000
FEE_TIER_HIGH_CENTS = 1000000
FEE_TIER_MID_CENTS = 100000
FEE_BPS_HIGH = 25
FEE_BPS_MID = 50
FEE_BPS_LOW = 100


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def channel_events(ch_id):
    return [e for e in db.store.revenue_events.values() if e["channel_id"] == ch_id]


def channel_payouts(ch_id):
    return [p for p in db.store.payouts.values() if p["channel_id"] == ch_id]


def channel_strikes(ch_id):
    return [s for s in db.store.strikes.values() if s["channel_id"] == ch_id]


def get_channel(ch_id):
    return db.store.channels.get(ch_id)


# ---------------------------------------------------------------------------
# Channel computed fields
# ---------------------------------------------------------------------------
def balance_pending_cents(ch_id):
    return sum(e["net_cents"] for e in channel_events(ch_id)
               if e["recognition_status"] == "PENDING")


def balance_payable_cents(ch_id):
    cleared = sum(e["net_cents"] for e in channel_events(ch_id)
                  if e["recognition_status"] == "CLEARED")
    reserved = sum(p["amount_cents"] for p in channel_payouts(ch_id)
                   if p["payout_status"] in IN_FLIGHT_PAYOUT or p["payout_status"] == "PAID")
    return cleared - reserved


def lifetime_paid_cents(ch_id):
    return sum(p["net_transfer_cents"] for p in channel_payouts(ch_id)
               if p["payout_status"] == "PAID")


def current_tax_form(ch):
    fid = ch.get("tax_form_current_id")
    return db.store.tax_forms.get(fid) if fid else None


def active_strike_weight(ch_id):
    """Canonical hard-window variant: severity sum over ISSUED/UNDER_APPEAL/UPHELD
    strikes whose expires_at is still in the future."""
    now = db.now()
    return sum(SEVERITY_WEIGHT[s["severity"]] for s in channel_strikes(ch_id)
               if s["strike_status"] in ACTIVE_STRIKE_STATUSES and s["expires_at"] > now)


def active_strike_count(ch_id):
    return sum(1 for s in channel_strikes(ch_id) if s["strike_status"] in ACTIVE_STRIKE_STATUSES)


def trust_score_bp(ch_id):
    return max(0, 10000 - 2500 * active_strike_weight(ch_id))


def projected_strike_weight(ch_id):
    """Analytics-only continuous decay: sum(severity * 2^(-age_days/30)) over
    ISSUED/UNDER_APPEAL/UPHELD/EXPIRED strikes issued within the last 180 days.
    4 decimal places, round half up. NEVER gates posture."""
    now = db.now()
    cutoff = now - timedelta(days=180)
    total = 0.0
    for s in channel_strikes(ch_id):
        if s["strike_status"] in ("ISSUED", "UNDER_APPEAL", "UPHELD", "EXPIRED") \
                and s["issued_at"] >= cutoff:
            age_days = (now - s["issued_at"]).total_seconds() / 86400.0
            total += SEVERITY_WEIGHT[s["severity"]] * (2.0 ** (-age_days / 30.0))
    q = Decimal(str(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def monetization_posture(ch):
    w = active_strike_weight(ch["id"])
    if w >= 3:
        return "SUSPENDED"
    form = current_tax_form(ch)
    if w == 0 and form is not None and form["tax_status"] == "VERIFIED":
        return "STANDARD"
    return "RESTRICTED"


def consistency_score_bps(ch_id):
    """Schedule consistency over the trailing 28-day window, in basis points.
    Exact rational arithmetic; rounded half up once at the end; clamped."""
    now = db.now()
    start = now - timedelta(days=28)
    window = [s for s in db.store.streams.values()
              if s["channel_id"] == ch_id and start <= s["scheduled_start"] <= now]
    scheduled = [s for s in window
                 if s["stream_status"] in ("LIVE", "ENDED", "NO_SHOW", "CANCELLED")]
    if not scheduled:
        return 10000
    ended = [s for s in scheduled if s["stream_status"] == "ENDED"]
    attendance = Fraction(len(ended), len(scheduled))
    if ended:
        avg_late = Fraction(sum(s["punctuality_minutes_late"] for s in ended), len(ended))
        ratios = []
        for s in ended:
            actual = (s["actual_end"] - s["actual_start"]).total_seconds()
            planned = (s["scheduled_end"] - s["scheduled_start"]).total_seconds()
            ratios.append(Fraction(int(actual), int(planned)))
        avg_dur = sum(ratios, Fraction(0)) / len(ended)
    else:
        avg_late = Fraction(0)
        avg_dur = Fraction(1)
    punctuality_factor = max(Fraction(0), 1 - avg_late / 30)
    duration_factor = min(Fraction(1), avg_dur)
    score = 10000 * attendance * (Fraction(1, 2)
                                  + Fraction(3, 10) * punctuality_factor
                                  + Fraction(1, 5) * duration_factor)
    rounded = (2 * score + 1) // 2  # round half up for non-negative rationals
    return max(0, min(10000, int(rounded)))


# ---------------------------------------------------------------------------
# Posture cascades (payout holds / releases)
# ---------------------------------------------------------------------------
def hold_scheduled_payouts(ch_id, reason):
    for p in channel_payouts(ch_id):
        if p["payout_status"] == "SCHEDULED":
            p["payout_status"] = "HELD"
            p["hold_reason"] = reason
            db.touch(p)


def release_held_payouts(ch_id, reason):
    """Release HELD payouts with the given hold_reason back to SCHEDULED.
    Returns the number released (ops-run payouts_released counter)."""
    n = 0
    for p in channel_payouts(ch_id):
        if p["payout_status"] == "HELD" and p["hold_reason"] == reason:
            p["payout_status"] = "SCHEDULED"
            p["hold_reason"] = "NONE"
            db.touch(p)
            n += 1
    return n


def posture_cascade(ch, old_posture, cause):
    """After a strike/tax mutation, hold SCHEDULED payouts when the channel
    leaves STANDARD. cause is 'TAX_FORM' or 'POSTURE'; a drop to SUSPENDED
    always stamps POSTURE."""
    new_posture = monetization_posture(ch)
    if new_posture == old_posture:
        return new_posture
    if new_posture == "SUSPENDED" and old_posture != "SUSPENDED":
        hold_scheduled_payouts(ch["id"], "POSTURE")
    elif old_posture == "STANDARD" and new_posture == "RESTRICTED":
        hold_scheduled_payouts(ch["id"], "TAX_FORM" if cause == "TAX_FORM" else "POSTURE")
    return new_posture


# ---------------------------------------------------------------------------
# Viewer / moderation derivations
# ---------------------------------------------------------------------------
def viewer_standing(viewer):
    acts = [a for a in db.store.mod_actions.values()
            if a["viewer_id"] == viewer["id"] and a["channel_id"] == viewer["channel_id"]
            and a["action_status"] == "ACTIVE"]
    if any(a["action_kind"] == "BAN" for a in acts):
        return "BANNED"
    if any(a["action_kind"] == "TIMEOUT" for a in acts):
        return "TIMED_OUT"
    return "GOOD_STANDING"


def moderator_actions_issued_count(mod_id):
    return sum(1 for a in db.store.mod_actions.values()
               if a.get("moderator_id") == mod_id and a["action_status"] != "REVERSED")


def prior_timeout_count(ch_id, viewer_id):
    """Progressive discipline: TIMEOUTs in ACTIVE or EXPIRED status count;
    REVERSED ones do not."""
    return sum(1 for a in db.store.mod_actions.values()
               if a["channel_id"] == ch_id and a["viewer_id"] == viewer_id
               and a["action_kind"] == "TIMEOUT"
               and a["action_status"] in ("ACTIVE", "EXPIRED"))


def ban_cascade(viewer):
    """The moment a viewer becomes BANNED: their ACTIVE/PAST_DUE subscriptions
    on the channel -> CANCELLED; those subs' PENDING/FAILED grants -> VOIDED."""
    for sub in db.store.subscriptions.values():
        if sub["viewer_id"] == viewer["id"] and sub["channel_id"] == viewer["channel_id"] \
                and sub["sub_status"] in ("ACTIVE", "PAST_DUE"):
            cancel_subscription(sub)


def cancel_subscription(sub):
    sub["sub_status"] = "CANCELLED"
    db.touch(sub)
    void_open_perks(sub)


def void_open_perks(sub):
    """Cascade voiding applies only to PENDING/FAILED grants and restores no
    inventory (FULFILLED grants are untouched)."""
    for g in db.store.perk_grants.values():
        if g["subscription_id"] == sub["id"] and g["perk_status"] in ("PENDING", "FAILED"):
            g["perk_status"] = "VOIDED"
            db.touch(g)


def recompute_standing_and_cascade(viewer, before):
    """After a moderation-action mutation, derive the viewer's new standing;
    fire the ban cascade only on entry into BANNED."""
    after = viewer_standing(viewer)
    if after == "BANNED" and before != "BANNED":
        ban_cascade(viewer)
    return after


# ---------------------------------------------------------------------------
# Tier / perk derivations
# ---------------------------------------------------------------------------
def tier_inventory_remaining(tier):
    fulfilled = 0
    for g in db.store.perk_grants.values():
        if g["perk_status"] != "FULFILLED":
            continue
        sub = db.store.subscriptions.get(g["subscription_id"])
        if sub is not None and sub["tier_id"] == tier["id"]:
            fulfilled += 1
    return tier["perk_inventory_total"] - fulfilled


# ---------------------------------------------------------------------------
# Deal derivations
# ---------------------------------------------------------------------------
def deal_deliverables(deal_id):
    return [d for d in db.store.deliverables.values() if d["deal_id"] == deal_id]


def deal_verified_count(deal_id):
    return sum(1 for d in deal_deliverables(deal_id) if d["performance_status"] == "VERIFIED")


def deal_disclosure_compliant(deal_id):
    return not any(d["disclosure_status"] in ("DISCLOSED_LATE", "MISSING")
                   for d in deal_deliverables(deal_id))


# ---------------------------------------------------------------------------
# Revenue recognition + payout settlement (§3.2 / §3.3)
# ---------------------------------------------------------------------------
def provisional_net_cents(gross_cents, platform_fee_bps):
    """Ingestion-time net: plain fee, never the volume rebate."""
    return rhu(gross_cents * (10000 - platform_fee_bps), 10000)


def create_revenue_event(channel_id, kind, gross_cents, platform_fee_bps,
                         occurred_at, reverses_event_id=None):
    status = "CLEARED" if kind == "CHARGEBACK" else "PENDING"
    e = db.new_ledger_event(
        channel_id=channel_id,
        kind=kind,
        gross_cents=gross_cents,
        platform_fee_bps=platform_fee_bps,
        occurred_at=occurred_at,
        recognition_status=status,
        settlement_month=month_label(occurred_at),
        reverses_event_id=reverses_event_id,
        net_cents=provisional_net_cents(gross_cents, platform_fee_bps),
        withholding_cents=0,
        _swept=False,
    )
    db.store.revenue_events[e["id"]] = e
    return e


def unswept_cleared_events(ch_id):
    return [e for e in channel_events(ch_id)
            if e["recognition_status"] == "CLEARED" and not e.get("_swept")]


def per_event_withholding(event, w8):
    return rhu(event["net_cents"] * WITHHOLDING_BPS_W8, 10000) if w8 else 0


def open_payout(ch):
    """Pinned evaluation order (§3.3): withholding per swept event (rounded per
    event, then summed) -> snapshot = payable - withholding -> fee tier on the
    pre-fee snapshot -> fee -> net transfer. Swept events are reserved so a
    later payout cannot re-sweep them."""
    form = current_tax_form(ch)
    w8 = form is not None and form["form_type"] in ("W8BEN", "W8BENE")
    swept = sorted(unswept_cleared_events(ch["id"]), key=lambda e: (e["created_at"], e["_seq"]))
    withholding = sum(per_event_withholding(e, w8) for e in swept)
    snapshot = balance_payable_cents(ch["id"]) - withholding
    if snapshot >= FEE_TIER_HIGH_CENTS:
        fee_bps = FEE_BPS_HIGH
    elif snapshot >= FEE_TIER_MID_CENTS:
        fee_bps = FEE_BPS_MID
    else:
        fee_bps = FEE_BPS_LOW
    fee = rhu(snapshot * fee_bps, 10000)
    payout = db.new_entity(
        channel_id=ch["id"],
        payout_status="SCHEDULED",
        amount_cents=snapshot,
        withholding_cents=withholding,
        fee_cents=fee,
        net_transfer_cents=snapshot - fee,
        settled_event_count=len(swept),
        retry_count=0,
        failure_reason=None,
        hold_reason="NONE",
        scheduled_for=db.now(),
        _swept_event_ids=[e["id"] for e in swept],
    )
    for e in swept:
        e["_swept"] = True
        e["withholding_cents"] = per_event_withholding(e, w8)
    db.store.payouts[payout["id"]] = payout
    return payout


def unsweep_payout(payout):
    """Compensating half of the open pair: cancellation leaves the ledger as if
    the payout had never been opened."""
    for eid in payout.get("_swept_event_ids", []):
        e = db.store.revenue_events.get(eid)
        if e is not None:
            e["_swept"] = False
            e["withholding_cents"] = 0
    payout["_swept_event_ids"] = []


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def channel_json(ch):
    cid = ch["id"]
    return {
        "id": ch["id"],
        "handle": ch["handle"],
        "display_name": ch["display_name"],
        "home_platform": ch["home_platform"],
        "payout_schedule": ch["payout_schedule"],
        "payout_threshold_cents": ch["payout_threshold_cents"],
        "monetization_posture": monetization_posture(ch),
        "balance_pending_cents": balance_pending_cents(cid),
        "balance_payable_cents": balance_payable_cents(cid),
        "lifetime_paid_cents": lifetime_paid_cents(cid),
        "trust_score_bp": trust_score_bp(cid),
        "projected_strike_weight": projected_strike_weight(cid),
        "consistency_score_bps": consistency_score_bps(cid),
        "active_strike_count": active_strike_count(cid),
        "tax_form_current_id": ch.get("tax_form_current_id"),
        "created_at": iso(ch["created_at"]),
        "updated_at": iso(ch["updated_at"]),
        "version": ch["version"],
    }


def tax_form_json(f):
    return {
        "id": f["id"],
        "channel_id": f["channel_id"],
        "form_type": f["form_type"],
        "legal_name": f["legal_name"],
        "tax_id_last4": f["tax_id_last4"],
        "tax_status": f["tax_status"],
        "submitted_at": iso(f["submitted_at"]),
        "verified_at": iso(f["verified_at"]),
        "rejection_reason": f["rejection_reason"],
        "expires_on": iso(f["expires_on"]),
        "prior_form_id": f["prior_form_id"],
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def revenue_event_json(e):
    return {
        "id": e["id"],
        "channel_id": e["channel_id"],
        "kind": e["kind"],
        "gross_cents": e["gross_cents"],
        "platform_fee_bps": e["platform_fee_bps"],
        "occurred_at": iso(e["occurred_at"]),
        "recognition_status": e["recognition_status"],
        "settlement_month": e["settlement_month"],
        "reverses_event_id": e["reverses_event_id"],
        "net_cents": e["net_cents"],
        "withholding_cents": e["withholding_cents"],
        "created_at": iso(e["created_at"]),
    }


def payout_json(p):
    return {
        "id": p["id"],
        "channel_id": p["channel_id"],
        "payout_status": p["payout_status"],
        "amount_cents": p["amount_cents"],
        "withholding_cents": p["withholding_cents"],
        "fee_cents": p["fee_cents"],
        "net_transfer_cents": p["net_transfer_cents"],
        "settled_event_count": p["settled_event_count"],
        "retry_count": p["retry_count"],
        "failure_reason": p["failure_reason"],
        "hold_reason": p["hold_reason"],
        "scheduled_for": iso(p["scheduled_for"]),
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def tier_json(t):
    return {
        "id": t["id"],
        "channel_id": t["channel_id"],
        "tier_code": t["tier_code"],
        "monthly_price_cents": t["monthly_price_cents"],
        "revenue_share_bps": t["revenue_share_bps"],
        "perk_inventory_total": t["perk_inventory_total"],
        "perk_inventory_remaining": tier_inventory_remaining(t),
        "tier_status": t["tier_status"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def viewer_json(v):
    return {
        "id": v["id"],
        "channel_id": v["channel_id"],
        "handle": v["handle"],
        "standing": viewer_standing(v),
        "lifetime_spend_cents": v["lifetime_spend_cents"],
        "created_at": iso(v["created_at"]),
        "updated_at": iso(v["updated_at"]),
        "version": v["version"],
    }


def subscription_json(s):
    return {
        "id": s["id"],
        "channel_id": s["channel_id"],
        "viewer_id": s["viewer_id"],
        "tier_id": s["tier_id"],
        "sub_status": s["sub_status"],
        "started_at": iso(s["started_at"]),
        "current_period_end": iso(s["current_period_end"]),
        "cycles_paid": s["cycles_paid"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def perk_grant_json(g):
    return {
        "id": g["id"],
        "subscription_id": g["subscription_id"],
        "perk_kind": g["perk_kind"],
        "perk_status": g["perk_status"],
        "due_at": iso(g["due_at"]),
        "failure_count": g["failure_count"],
        "fulfilled_at": iso(g["fulfilled_at"]),
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }


def moderator_json(m):
    return {
        "id": m["id"],
        "channel_id": m["channel_id"],
        "moderator_handle": m["moderator_handle"],
        "scopes": list(m["scopes"]),
        "moderator_status": m["moderator_status"],
        "actions_issued_count": moderator_actions_issued_count(m["id"]),
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def mod_action_json(a):
    return {
        "id": a["id"],
        "channel_id": a["channel_id"],
        "viewer_id": a["viewer_id"],
        "moderator_id": a["moderator_id"],
        "action_kind": a["action_kind"],
        "duration_minutes": a["duration_minutes"],
        "reason": a["reason"],
        "action_status": a["action_status"],
        "issued_at": iso(a["issued_at"]),
        "expires_at": iso(a["expires_at"]),
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def strike_json(s):
    return {
        "id": s["id"],
        "channel_id": s["channel_id"],
        "policy_code": s["policy_code"],
        "severity": s["severity"],
        "evidence_ref": s["evidence_ref"],
        "strike_status": s["strike_status"],
        "issued_at": iso(s["issued_at"]),
        "expires_at": iso(s["expires_at"]),
        "appeal_deadline": iso(s["appeal_deadline"]),
        "appeal_round": s["appeal_round"],
        "issued_by_user_id": s["issued_by_user_id"],
        "resolved_by_user_id": s["resolved_by_user_id"],
        "upheld_at": iso(s["upheld_at"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def deal_json(d):
    return {
        "id": d["id"],
        "channel_id": d["channel_id"],
        "sponsor_ref": d["sponsor_ref"],
        "title": d["title"],
        "category": d["category"],
        "total_value_cents": d["total_value_cents"],
        "flight_start": iso(d["flight_start"]),
        "flight_end": iso(d["flight_end"]),
        "required_deliverable_count": d["required_deliverable_count"],
        "deal_status": d["deal_status"],
        "miss_count": d["miss_count"],
        "verified_deliverable_count": deal_verified_count(d["id"]),
        "disclosure_compliant": deal_disclosure_compliant(d["id"]),
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def deliverable_json(d):
    return {
        "id": d["id"],
        "deal_id": d["deal_id"],
        "stream_id": d["stream_id"],
        "kind": d["kind"],
        "due_at": iso(d["due_at"]),
        "performance_status": d["performance_status"],
        "disclosure_status": d["disclosure_status"],
        "performed_at": iso(d["performed_at"]),
        "disclosure_deadline": iso(d["disclosure_deadline"]),
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "version": d["version"],
    }


def stream_json(s):
    return {
        "id": s["id"],
        "channel_id": s["channel_id"],
        "title": s["title"],
        "scheduled_start": iso(s["scheduled_start"]),
        "scheduled_end": iso(s["scheduled_end"]),
        "simulcast": s["simulcast"],
        "stream_status": s["stream_status"],
        "actual_start": iso(s["actual_start"]),
        "actual_end": iso(s["actual_end"]),
        "peak_viewers": s["peak_viewers"],
        "avg_viewers": s["avg_viewers"],
        "punctuality_minutes_late": s["punctuality_minutes_late"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def grant_json(g):
    return {
        "id": g["id"],
        "channel_id": g["channel_id"],
        "platform": g["platform"],
        "window_start": iso(g["window_start"]),
        "window_end": iso(g["window_end"]),
        "exclusive": g["exclusive"],
        "grant_status": g["grant_status"],
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }
