"""Computed fields, lazy time-driven transitions, and serialization."""
import math
from datetime import timedelta

from db import db, iso_now_ms
from clock import clock
from services.common import add_months, parse_iso, touch

COACHING_STRIKE_LIMIT = 3
STRIKE_DECAY_DAYS = 30


# ---------------------------------------------------------------------------
# Member-scoped introduction credit accounting (PRD §3.4 / §2.11)
# ---------------------------------------------------------------------------
def _active_membership(member):
    """Return the member's currently-ACTIVE-or-FROZEN-or-FULFILLED-or-EXPIRED
    membership tracked as active_membership_id, else None.

    The guarantee snapshot lives on the membership identified by
    active_membership_id (set at activation; persists through later states until
    a new activation, which the model does not currently support)."""
    mid = member.get("active_membership_id")
    if mid and mid in db.memberships:
        return db.memberships[mid]
    return None


def committed_consumed_for_member(member_id):
    total = 0
    for intro in db.introductions.values():
        if intro["member_a_id"] != member_id:
            continue
        if intro["status"] == "MUTUAL":
            total += intro.get("credits_consumed", 0)
        elif intro["status"] == "CLOSED" and intro.get("_was_mutual"):
            total += intro.get("credits_consumed", 0)
    return total


def forecast_consumed_for_member(member_id):
    total = 0
    for intro in db.introductions.values():
        if intro["member_a_id"] != member_id:
            continue
        if intro["status"] in ("SUGGESTED", "ONE_SIDED", "MUTUAL"):
            total += intro.get("credits_consumed", 0)
    return total


def guarantee_for_member(member):
    membership = _active_membership(member)
    guaranteed = membership["guaranteed_introductions"] if membership else 0
    committed = committed_consumed_for_member(member["id"])
    forecast = forecast_consumed_for_member(member["id"])
    remaining_committed = max(guaranteed - committed, 0)
    remaining_forecast = max(guaranteed - forecast, 0)
    return remaining_committed, remaining_forecast


# ---------------------------------------------------------------------------
# No-show strike decay (PRD §3.7)
# ---------------------------------------------------------------------------
def effective_strikes(member_id):
    no_shows = [
        s for s in db.coaching_sessions.values()
        if s["member_id"] == member_id and s["status"] == "NO_SHOW"
    ]
    if not no_shows:
        return 0
    recorded = len(no_shows)
    last_no_show_at = max(parse_iso(s["start_at"]) for s in no_shows)
    now = clock.now()
    elapsed_days = (now - last_no_show_at).total_seconds() / 86400.0
    decayed = math.floor(elapsed_days / STRIKE_DECAY_DAYS) if elapsed_days >= 0 else 0
    return max(recorded - decayed, 0)


def coaching_suspended(member_id):
    return effective_strikes(member_id) >= COACHING_STRIKE_LIMIT


# ---------------------------------------------------------------------------
# Term end (PRD §3.2)
# ---------------------------------------------------------------------------
def term_end_for_member(member):
    membership = _active_membership(member)
    if not membership:
        return None
    if membership["status"] in ("CANCELLED",):
        return None
    start = parse_iso(membership["start_at"])
    base = add_months(start, membership["_term_months"])
    end = base + timedelta(days=member.get("frozen_days_total", 0))
    return end


# ---------------------------------------------------------------------------
# Lazy time-driven reconciliation (PRD §2.5)
# ---------------------------------------------------------------------------
def reconcile_member(member):
    """Lazily evaluate freeze activation and membership expiry for this member."""
    _activate_due_freezes_for_member(member)
    _expire_due_membership_for_member(member)


def _activate_due_freezes_for_member(member):
    now = clock.now()
    membership = _active_membership(member)
    if not membership:
        return
    for freeze in db.freezes.values():
        if freeze["membership_id"] != membership["id"]:
            continue
        if freeze["status"] != "SCHEDULED":
            continue
        if now >= parse_iso(freeze["start_at"]):
            freeze["status"] = "ACTIVE"
            touch(freeze)
            if membership["status"] == "ACTIVE":
                membership["status"] = "FROZEN"
                touch(membership)
            if member["status"] == "ACTIVE":
                member["status"] = "FROZEN"
                touch(member)


def _expire_due_membership_for_member(member):
    now = clock.now()
    membership = _active_membership(member)
    if not membership:
        return
    if membership["status"] != "ACTIVE":
        return
    end = term_end_for_member(member)
    if end is None:
        return
    # guarantee unmet check
    committed = committed_consumed_for_member(member["id"])
    guarantee_met = committed >= membership["guaranteed_introductions"]
    if now >= end and not guarantee_met:
        membership["status"] = "EXPIRED"
        touch(membership)


def reconcile_membership(membership):
    member = db.members.get(membership["member_id"])
    if member:
        reconcile_member(member)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def serialize_plan(p):
    out = _common(p)
    out.update({
        "tier": p["tier"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "term_months": p["term_months"],
        "guaranteed_introductions": p["guaranteed_introductions"],
        "priority_match_enabled": p["priority_match_enabled"],
        "included_coaching_sessions": p["included_coaching_sessions"],
        "coaching_value_cents": p["coaching_value_cents"],
        "background_check_addon_cents": p["background_check_addon_cents"],
        "archived": p["archived"],
        "status": p["status"],
    })
    return out


def serialize_member(m):
    remaining_committed, remaining_forecast = guarantee_for_member(m)
    strikes = effective_strikes(m["id"])
    membership = _active_membership(m)
    term_end = term_end_for_member(m)
    out = _common(m)
    out.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "birth_date": m["birth_date"],
        "city": m["city"],
        "gender": m["gender"],
        "status": m["status"],
        "screening_decision": m["screening_decision"],
        "active_membership_id": m.get("active_membership_id"),
        "guarantee_remaining_committed": remaining_committed,
        "guarantee_remaining_forecast": remaining_forecast,
        "no_show_strikes": strikes,
        "coaching_suspended": strikes >= COACHING_STRIKE_LIMIT,
        "wallet_credit_cents": m.get("wallet_credit_cents", 0),
        "frozen_days_total": m.get("frozen_days_total", 0),
        "term_end_at": iso_now_ms(term_end) if term_end else None,
    })
    return out


def serialize_screening(s):
    out = _common(s)
    out.update({
        "member_id": s["member_id"],
        "questionnaire_score": s["questionnaire_score"],
        "identity_verified": s["identity_verified"],
        "decision": s["decision"],
        "decision_note": s["decision_note"],
        "status": s["status"],
    })
    return out


def serialize_preference(p):
    out = _common(p)
    out.update({
        "member_id": p["member_id"],
        "seeking_gender": p["seeking_gender"],
        "min_age": p["min_age"],
        "max_age": p["max_age"],
        "max_distance_band": p["max_distance_band"],
        "attribute_weights": p["attribute_weights"],
        "dealbreaker_tags": p["dealbreaker_tags"],
    })
    return out


def serialize_membership(ms):
    member = db.members.get(ms["member_id"])
    committed = committed_consumed_for_member(ms["member_id"]) if member else 0
    guarantee_met = committed >= ms["guaranteed_introductions"]
    out = _common(ms)
    out.update({
        "member_id": ms["member_id"],
        "plan_id": ms["plan_id"],
        "start_at": ms["start_at"],
        "base_term_end_at": ms["base_term_end_at"],
        "guaranteed_introductions": ms["guaranteed_introductions"],
        "credits_consumed_committed": committed,
        "guarantee_met": guarantee_met,
        "status": ms["status"],
        "refund_cents": ms.get("refund_cents", 0),
    })
    return out


def serialize_freeze(f):
    out = _common(f)
    out.update({
        "membership_id": f["membership_id"],
        "start_at": f["start_at"],
        "end_at": f["end_at"],
        "committed_days": f.get("committed_days"),
        "status": f["status"],
    })
    return out


def serialize_introduction(i):
    out = _common(i)
    out.update({
        "member_a_id": i["member_a_id"],
        "member_b_id": i["member_b_id"],
        "compatibility_score": i["compatibility_score"],
        "credits_consumed": i["credits_consumed"],
        "a_response": i["a_response"],
        "b_response": i["b_response"],
        "status": i["status"],
        "win_back_promo": i["win_back_promo"],
    })
    return out


def serialize_feedback(f):
    out = _common(f)
    out.update({
        "introduction_id": f["introduction_id"],
        "author_member_id": f["author_member_id"],
        "rating": f["rating"],
        "continue_interest": f["continue_interest"],
        "comments": f["comments"],
    })
    return out


def serialize_date_event(d):
    out = _common(d)
    out.update({
        "introduction_id": d["introduction_id"],
        "scheduled_by_member_id": d["scheduled_by_member_id"],
        "start_at": d["start_at"],
        "end_at": d["end_at"],
        "outcome": d["outcome"],
        "status": d["status"],
    })
    return out


def serialize_coaching_session(s):
    out = _common(s)
    out.update({
        "member_id": s["member_id"],
        "coach_user_id": s["coach_user_id"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "status": s["status"],
    })
    return out


def serialize_background_check(c):
    out = _common(c)
    out.update({
        "member_id": c["member_id"],
        "provider_ref": c["provider_ref"],
        "fee_charged_cents": c["fee_charged_cents"],
        "result": c["result"],
        "status": c["status"],
    })
    return out
