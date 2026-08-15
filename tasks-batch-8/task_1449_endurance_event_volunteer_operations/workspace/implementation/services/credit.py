"""Fundraising credit, sponsor match, and recognition point calculations."""
from decimal import Decimal

from db import store
from util import round_half_up, dec_to_number
from services.core import serialize_shift  # noqa: F401  (kept for symmetry)


def _role_for_log(log):
    signup = store.signups.get(log["signup_id"])
    if signup is None:
        return None
    shift = store.shifts.get(signup["shift_id"])
    if shift is None:
        return None
    return store.role_catalog_entries.get(shift["role_entry_id"])


def _signup_for_log(log):
    return store.signups.get(log["signup_id"])


def _group_logs(group_id):
    """Hour logs whose signup's volunteer is affiliated with this group."""
    out = []
    for log in store.hour_logs.values():
        su = store.signups.get(log["signup_id"])
        if su is None:
            continue
        vol = store.volunteers.get(su["volunteer_id"])
        if vol is None:
            continue
        if vol.get("group_id") == group_id:
            out.append(log)
    return out


def _tier_credit(hours):
    """Marginal 3-slice pricing with per-slice round-half-up to whole cents."""
    h = Decimal(hours)
    slice1 = min(h, Decimal(100))
    cents1 = round_half_up(slice1 * Decimal(500), 0)
    slice2 = min(max(h - Decimal(100), Decimal(0)), Decimal(400))
    cents2 = round_half_up(slice2 * Decimal(800), 0)
    slice3 = max(h - Decimal(500), Decimal(0))
    cents3 = round_half_up(slice3 * Decimal(1200), 0)
    return int(cents1 + cents2 + cents3)


def _effective(log, field):
    """effective hours = log.<field> * role.credit_weight, round_half_up 2dp."""
    role = _role_for_log(log)
    weight = Decimal(str(role["credit_weight"])) if role else Decimal(1)
    return round_half_up(Decimal(log[field]) * weight, 2)


def credit_summary(group):
    logs = _group_logs(group["id"])
    provisional_pool = [l for l in logs if l["status"] in {"PENDING_VERIFICATION", "VERIFIED", "DISPUTED"}]
    settled_pool = [l for l in logs if l["status"] == "VERIFIED"]

    provisional_effective = sum((_effective(l, "claimed_hours") for l in provisional_pool), Decimal(0))
    settled_effective = sum((_effective(l, "credited_hours") for l in settled_pool), Decimal(0))

    provisional_credit_cents = _tier_credit(provisional_effective)
    settled_credit_cents = _tier_credit(settled_effective)

    base = settled_credit_cents
    if base >= 250000:
        match_pct = Decimal("0.25")
    elif base >= 50000:
        match_pct = Decimal("0.15")
    else:
        match_pct = Decimal("0.05")
    sponsor_match_cents = int(round_half_up(Decimal(base) * match_pct, 0))
    total_settled = base + sponsor_match_cents

    return {
        "provisional_effective_hours": dec_to_number(provisional_effective),
        "settled_effective_hours": dec_to_number(settled_effective),
        "provisional_credit_cents": provisional_credit_cents,
        "settled_credit_cents": settled_credit_cents,
        "sponsor_match_cents": sponsor_match_cents,
        "total_settled_credit_cents": total_settled,
    }


def recognition_summary(volunteer):
    signups = [
        su for su in store.signups.values()
        if su["volunteer_id"] == volunteer["id"] and su["event_id"] == volunteer["event_id"]
    ]
    projected = 0
    official = 0
    captain_shift_count = 0
    no_show_count = 0
    for su in signups:
        if su["status"] == "CANCELLED":
            continue
        logs = [l for l in store.hour_logs.values() if l["signup_id"] == su["id"]]
        for log in logs:
            if log["status"] == "VERIFIED":
                # VERIFIED logs contribute credited hours to BOTH projected and official
                pts = int(Decimal(log["credited_hours"]) * 10)
                official += pts
                projected += pts
            elif log["status"] in {"PENDING_VERIFICATION", "DISPUTED"}:
                # unverified logs contribute claimed hours to projected only
                projected += int(Decimal(log["claimed_hours"]) * 10)
            # REJECTED contributes 0
        if su.get("is_captain") and su["status"] != "CANCELLED":
            captain_shift_count += 1
            projected += 25
            official += 25
        if su["status"] == "NO_SHOW":
            no_show_count += 1
            projected -= 15
            official -= 15
    if volunteer.get("is_returning"):
        projected += 50
        official += 50

    if official >= 600:
        tier = "PLATINUM"
    elif official >= 300:
        tier = "GOLD"
    elif official >= 150:
        tier = "SILVER"
    elif official >= 50:
        tier = "BRONZE"
    else:
        tier = "NONE"

    return {
        "projected_points": projected,
        "official_points": official,
        "recognition_tier": tier,
        "captain_shift_count": captain_shift_count,
        "no_show_count": no_show_count,
    }
