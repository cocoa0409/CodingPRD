"""Shared helpers: entity construction, mutation stamps (updated_at/version),
payload validation, and cross-aggregate recomputations."""

import db
import errors as err

# --- enum domains (from scaffold entity constraints) -------------------------
NICHE_ENUM = {"BEAUTY", "FASHION", "TECH", "FINANCE", "GAMING", "FITNESS",
              "FOOD", "TRAVEL", "OTHER"}
PLATFORM_ENUM = {"YOUTUBE", "INSTAGRAM", "TIKTOK", "TWITCH"}
INDUSTRY_ENUM = {"CPG", "TECH", "FINANCE", "FASHION", "AUTOMOTIVE", "GAMING",
                 "OTHER"}
EXCLUSIVITY_ENUM = {"NONE", "BEVERAGES", "SNACKS", "SKINCARE", "SOFTWARE",
                    "FINTECH", "AUTOMOTIVE", "GAMING", "APPAREL"}
DISPUTE_REASON_ENUM = {"RESHOOT_REQUEST", "NON_PAYMENT", "DISCLOSURE_VIOLATION",
                       "SCOPE_CREEP", "OTHER"}
DISPUTE_REMEDY_ENUM = {"NONE", "RESHOOT", "FEE_REDUCTION", "TERMINATE"}
CREATOR_STATUS_ENUM = {"APPLIED", "SCREENING", "ACTIVE", "SUSPENDED", "EXITED"}
BRAND_STATUS_ENUM = {"ACTIVE", "SUSPENDED"}

# --- system constants (from scaffold calculations/payout_schedule) -----------
STRIKE_LIMIT = 3
MAX_DISCLOSURE_RECHECKS = 2
MAX_RESHOOTS_PER_DELIVERABLE = 1
MAX_PITCH_NEGOTIATION_ROUNDS = 3
MAX_DEAL_NEGOTIATION_ROUNDS = 4
MIN_PUBLISH_GAP_HOURS = 48
INVOICE_NET_DAYS = 30
PAYOUT_NET_DAYS = 7


# --- payload validation ------------------------------------------------------

def body():
    """Return the JSON request body as a dict. A truly absent body (no
    content) is treated as {}; malformed JSON or a non-object payload raises
    ERR_VALIDATION."""
    from flask import request
    raw = request.get_data()
    if raw is None or raw == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err.validation("Request body must be a JSON object")
    if not isinstance(data, dict):
        raise err.validation("Request body must be a JSON object")
    return data


def req_fields(payload, fields):
    missing = [f for f in fields if payload.get(f) is None]
    if missing:
        raise err.validation("Missing required field(s): %s" % ", ".join(missing))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def require_int(payload, name, minimum=None, maximum=None):
    v = payload.get(name)
    if not is_int(v):
        raise err.validation(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err.validation(f"{name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err.validation(f"{name} must be <= {maximum}")
    return v


def opt_int(payload, name, minimum=None, maximum=None, default=None):
    if payload.get(name) is None:
        return default
    return require_int(payload, name, minimum, maximum)


def require_str(payload, name):
    v = payload.get(name)
    if not isinstance(v, str) or v == "":
        raise err.validation(f"{name} must be a non-empty string")
    return v


def opt_str(payload, name, default=None):
    v = payload.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err.validation(f"{name} must be a string")
    return v


def require_enum(payload, name, domain):
    v = payload.get(name)
    if v not in domain:
        raise err.validation(f"{name} must be one of {sorted(domain)}")
    return v


def opt_enum(payload, name, domain, default=None):
    if payload.get(name) is None:
        return default
    return require_enum(payload, name, domain)


def require_bool(payload, name):
    v = payload.get(name)
    if not isinstance(v, bool):
        raise err.validation(f"{name} must be a boolean")
    return v


def opt_bool(payload, name, default=None):
    if payload.get(name) is None:
        return default
    return require_bool(payload, name)


def require_dt(payload, name):
    v = payload.get(name)
    dt = db.parse_iso(v)
    if dt is None:
        raise err.validation(f"{name} must be an ISO-8601 datetime string")
    return dt


# --- entity plumbing ----------------------------------------------------------

def new_entity():
    eid = db.new_id()
    return {
        "id": eid,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }


def touch(entity):
    """Every mutation moves updated_at and version (PRD §2.4)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1


def get_or_404(store, eid, what="resource"):
    entity = store.get(eid)
    if entity is None:
        raise err.not_found(f"{what} not found: {eid}")
    return entity


def iso_or_none(dt):
    return db.iso_format(dt) if dt is not None else None


# --- cross-aggregate recomputations ------------------------------------------

def recompute_slots_committed(brief_id):
    """COUNT(Pitch WHERE brief_id = brief AND status = ACCEPTED AND its
    Deal.status != TERMINATED)."""
    count = 0
    for p in db.pitches.values():
        if p["brief_id"] != brief_id or p["status"] != "ACCEPTED":
            continue
        deal = db.deals.get(p.get("deal_id") or "")
        if deal is not None and deal["status"] != "TERMINATED":
            count += 1
    brief = db.briefs.get(brief_id)
    if brief is not None:
        brief["slots_committed"] = count
    return count


def recompute_pending_disclosure_count(creator_id):
    """COUNT(DisclosureCheck on this creator's deliverables with status IN
    {QUEUED, FAILED})."""
    count = 0
    for chk in db.disclosure_checks.values():
        if chk["status"] not in ("QUEUED", "FAILED"):
            continue
        d = db.deliverables.get(chk["deliverable_id"])
        if d is None:
            continue
        deal = db.deals.get(d["deal_id"])
        if deal is not None and deal["creator_id"] == creator_id:
            count += 1
    creator = db.creators.get(creator_id)
    if creator is not None:
        creator["pending_disclosure_count"] = count
    return count


def recompute_bonus_accrued(deal_id):
    """SUM(final_bonus_cents) of FINAL PerformanceReports for this deal not
    yet billed on a non-VOID invoice."""
    billed = set()
    for inv in db.invoices.values():
        if inv["deal_id"] == deal_id and inv["status"] != "VOID":
            billed.update(inv.get("billed_report_ids") or [])
    total = 0
    for r in db.performance_reports.values():
        if r["deal_id"] == deal_id and r["status"] == "FINAL" and r["id"] not in billed:
            total += int(r.get("final_bonus_cents") or 0)
    deal = db.deals.get(deal_id)
    if deal is not None:
        deal["bonus_accrued_cents"] = total
    return total
