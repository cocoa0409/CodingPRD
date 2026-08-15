"""Business logic: calculations (scaffold §1.3), serializers, lazy system actions."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import DB, clock_now, logical_iso, new_id, next_seq, now_wall, wall_iso

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

VOICE_PROFILES = ["MALE_DEEP", "MALE_LIGHT", "FEMALE_DEEP", "FEMALE_LIGHT", "NONBINARY", "CHILD"]
UNION_STATUSES = ["UNION", "NON_UNION", "FICORE"]
ROSTER_STATUSES = ["ACTIVE", "SUSPENDED", "OFFBOARDED"]
CURRENCIES = ["USD", "EUR", "GBP"]
CATEGORIES = ["AUTOMOTIVE", "PHARMA", "FAST_FOOD", "FINANCE", "TECH", "RETAIL", "ALCOHOL", "GAMING"]
USAGE_TYPES = ["BROADCAST", "DIGITAL", "TERM"]
SESSION_KINDS = ["PRIMARY", "PICKUP", "RETAKE"]

UNION_SCALE_SESSION_FEE_CENTS = 65000
REVISION_WINDOW_HOURS = 72

TIER1_MAX_CENTS = 500000
TIER2_MAX_CENTS = 1500000


# --------------------------------------------------------------------------
# Generic record helpers
# --------------------------------------------------------------------------

def base_record():
    now = now_wall()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Bump optimistic-concurrency field and updated_at on a mutation."""
    rec["version"] += 1
    rec["updated_at"] = now_wall()


def sorted_rows(table):
    return sorted(DB[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, args):
    """limit/offset per PRD §2.3: limit default 10, min 1, max 100; offset default 0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return rows[offset:offset + limit], len(rows), limit, offset


# --------------------------------------------------------------------------
# Calculations (scaffold §1.3)
# --------------------------------------------------------------------------

def _rhu(x):
    """Round half-up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _usage_mult(usage_type, term_months):
    if usage_type == "BROADCAST":
        return Decimal("2.50")
    if usage_type == "DIGITAL":
        return Decimal("1.50")
    return Decimal("1.00") + Decimal("0.10") * int(term_months or 0)


def _spot_mult(spots_count):
    return Decimal("1.00") + Decimal("0.20") * max(0, int(spots_count) - 1)


def _union_mult(union_status):
    return Decimal("0.85") if union_status == "NON_UNION" else Decimal("1.00")


def buyout_quote(project):
    """Provisional quote at CASTING entry; union scale 65000 assumed."""
    total = Decimal(UNION_SCALE_SESSION_FEE_CENTS) \
        * _usage_mult(project["usage_type"], project["term_months"]) \
        * _spot_mult(project["spots_count"])
    return _rhu(total)


def buyout_final(project, talent):
    """Final buyout: round each line item half-up, then sum (order is contractual)."""
    line1 = Decimal(talent["base_session_fee_cents"]) \
        * _usage_mult(project["usage_type"], project["term_months"]) \
        * _union_mult(talent["union_status"])
    line2 = line1 * (_spot_mult(project["spots_count"]) - Decimal("1.00"))
    return _rhu(line1) + _rhu(line2)


def agent_commission(buyout_final_cents, union_status):
    """Tiered waterfall commission; UNION gets a 2-point reduction, floor 5%."""
    if buyout_final_cents < TIER1_MAX_CENTS:
        pct = Decimal("0.10")
    elif buyout_final_cents < TIER2_MAX_CENTS:
        pct = Decimal("0.15")
    else:
        pct = Decimal("0.20")
    if union_status == "UNION":
        pct = max(Decimal("0.05"), pct - Decimal("0.02"))
    commission = _rhu(Decimal(buyout_final_cents) * pct)
    return commission, buyout_final_cents - commission


def session_fee_final(session):
    """Final fee at COMPLETED: elapsed time, 15-min minimum, 5-min granularity,
    25% directed-patch surcharge (base rounded to cents before the surcharge)."""
    studio = DB["studios"].get(session["studio_id"])
    rate = studio["hourly_rate_cents"] if studio else 0
    elapsed_seconds = Decimal((session["_completed_at"] - session["start_at"]).total_seconds())
    elapsed_minutes = elapsed_seconds / Decimal(60)
    blocks = int((elapsed_minutes / Decimal(5)).to_integral_value(rounding=ROUND_CEILING))
    billed_minutes = max(15, blocks * 5)
    base = _rhu(Decimal(rate) * Decimal(billed_minutes) / Decimal(60))
    if session["directed_patch"]:
        base = _rhu(Decimal(base) * Decimal("1.25"))
    return base


def add_months(dt, months):
    """Calendar month addition with day clamping."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        next_month_first = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_month_first = dt.replace(year=year, month=month + 1, day=1)
    last_day = (next_month_first - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


# --------------------------------------------------------------------------
# Lazy system actions (conflict expiry + delivery-window auto close)
# --------------------------------------------------------------------------

def expire_exclusions():
    """ACTIVE exclusions whose ends_at <= clock flip to EXPIRED (lazy expiry)."""
    now = clock_now()
    for ce in DB["conflict_exclusions"].values():
        if ce["status"] == "ACTIVE" and ce["ends_at"] <= now:
            ce["status"] = "EXPIRED"
            touch(ce)


def latest_delivery(project_id):
    ds = [d for d in DB["deliveries"].values() if d["project_id"] == project_id]
    if not ds:
        return None
    return max(ds, key=lambda d: d["_seq"])


def close_project(project):
    """DELIVERED -> CLOSED; all PENDING invoices -> ISSUED with issued_at=clock."""
    project["status"] = "CLOSED"
    touch(project)
    for inv in DB["invoices"].values():
        if inv["project_id"] == project["id"] and inv["status"] == "PENDING":
            inv["status"] = "ISSUED"
            inv["issued_at"] = clock_now()
            touch(inv)


def auto_close_projects():
    """System close path: clock strictly past revision_window_closes_at and no
    revision requested. Evaluated lazily on reads (PRD §2.5 grants the clock-set
    endpoint exactly one housekeeping effect: conflict-exclusion expiry)."""
    now = clock_now()
    for p in list(DB["projects"].values()):
        if p["status"] != "DELIVERED":
            continue
        d = latest_delivery(p["id"])
        if d is not None and not d["revision_requested"] and now > d["revision_window_closes_at"]:
            close_project(p)


def lazy_read_tick():
    expire_exclusions()
    auto_close_projects()


# --------------------------------------------------------------------------
# Derived fields
# --------------------------------------------------------------------------

def active_conflict_categories(talent_id):
    """Distinct categories of ACTIVE exclusions whose window contains the clock,
    ordered by ends_at ASC, ties by created_at ASC (scaffold calculation)."""
    now = clock_now()
    rows = [
        ce for ce in DB["conflict_exclusions"].values()
        if ce["talent_id"] == talent_id
        and ce["status"] == "ACTIVE"
        and ce["starts_at"] <= now < ce["ends_at"]
    ]
    rows.sort(key=lambda ce: (ce["ends_at"], ce["created_at"], ce["_seq"]))
    seen = set()
    out = []
    for ce in rows:
        if ce["product_category"] not in seen:
            seen.add(ce["product_category"])
            out.append(ce["product_category"])
    return out


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": wall_iso(rec["created_at"]),
        "updated_at": wall_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def talent_json(t):
    out = {
        "id": t["id"],
        "stage_name": t["stage_name"],
        "email": t["email"],
        "voice_profile": t["voice_profile"],
        "languages": list(t["languages"]),
        "union_status": t["union_status"],
        "base_session_fee_cents": t["base_session_fee_cents"],
        "roster_status": t["roster_status"],
        "active_conflict_categories": active_conflict_categories(t["id"]),
    }
    out.update(_common(t))
    return out


def client_json(c):
    out = {
        "id": c["id"],
        "company_name": c["company_name"],
        "contact_email": c["contact_email"],
        "billing_email": c["billing_email"],
        "default_currency": c["default_currency"],
        "account_status": c["account_status"],
    }
    out.update(_common(c))
    return out


def project_json(p):
    out = {
        "id": p["id"],
        "client_id": p["client_id"],
        "title": p["title"],
        "product_category": p["product_category"],
        "usage_type": p["usage_type"],
        "term_months": p["term_months"],
        "spots_count": p["spots_count"],
        "exclusivity_required": p["exclusivity_required"],
        "brief_text": p["brief_text"],
        "audition_deadline": logical_iso(p["audition_deadline"]),
        "status": p["status"],
        "selected_talent_id": p["selected_talent_id"],
        "buyout_quote_cents": p["buyout_quote_cents"],
        "buyout_final_cents": p["buyout_final_cents"],
    }
    out.update(_common(p))
    return out


def audition_json(a):
    out = {
        "id": a["id"],
        "project_id": a["project_id"],
        "talent_id": a["talent_id"],
        "audio_file_url": a["audio_file_url"],
        "slate_text": a["slate_text"],
        "submitted_at": logical_iso(a["submitted_at"]),
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def studio_json(s):
    out = {
        "id": s["id"],
        "studio_name": s["studio_name"],
        "location": s["location"],
        "has_directed_patch": s["has_directed_patch"],
        "hourly_rate_cents": s["hourly_rate_cents"],
        "operating_tz": s["operating_tz"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def session_json(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "talent_id": s["talent_id"],
        "studio_id": s["studio_id"],
        "session_kind": s["session_kind"],
        "directed_patch": s["directed_patch"],
        "start_at": logical_iso(s["start_at"]),
        "duration_minutes": s["duration_minutes"],
        "status": s["status"],
        "end_at": logical_iso(s["end_at"]),
    }
    out.update(_common(s))
    return out


def usage_terms_json(u):
    out = {
        "id": u["id"],
        "project_id": u["project_id"],
        "usage_type": u["usage_type"],
        "term_months": u["term_months"],
        "broadcast_regions": list(u["broadcast_regions"]),
        "digital_placements": list(u["digital_placements"]),
        "buyout_cents": u["buyout_cents"],
        "agent_commission_cents": u["agent_commission_cents"],
        "talent_payout_cents": u["talent_payout_cents"],
        "locked_at_cast": u["locked_at_cast"],
    }
    out.update(_common(u))
    return out


def invoice_json(inv):
    out = {
        "id": inv["id"],
        "project_id": inv["project_id"],
        "invoice_kind": inv["invoice_kind"],
        "talent_amount_cents": inv["talent_amount_cents"],
        "agent_commission_cents": inv["agent_commission_cents"],
        "total_cents": inv["total_cents"],
        "status": inv["status"],
        "issued_at": logical_iso(inv["issued_at"]) if inv["issued_at"] else None,
    }
    out.update(_common(inv))
    return out


def conflict_json(ce):
    out = {
        "id": ce["id"],
        "talent_id": ce["talent_id"],
        "product_category": ce["product_category"],
        "starts_at": logical_iso(ce["starts_at"]),
        "ends_at": logical_iso(ce["ends_at"]),
        "source": ce["source"],
        "status": ce["status"],
    }
    out.update(_common(ce))
    return out


def delivery_json(d):
    # Delivery carries only id and created_at (PRD §2.4): no updated_at/version.
    return {
        "id": d["id"],
        "project_id": d["project_id"],
        "session_id": d["session_id"],
        "file_url": d["file_url"],
        "delivered_at": logical_iso(d["delivered_at"]),
        "revision_window_hours": d["revision_window_hours"],
        "revision_window_closes_at": logical_iso(d["revision_window_closes_at"]),
        "revision_requested": d["revision_requested"],
        "created_at": wall_iso(d["created_at"]),
    }


def clock_json():
    from db import CLOCK
    return {
        "id": CLOCK["id"],
        "created_at": wall_iso(CLOCK["created_at"]),
        "current_utc": logical_iso(CLOCK["current_utc"]),
    }
