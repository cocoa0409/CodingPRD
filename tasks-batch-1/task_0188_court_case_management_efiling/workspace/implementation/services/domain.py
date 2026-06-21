"""Shared domain helpers: lookups, computed-field recomputation, serialization."""
import db
import errors
from services import calc

# Fields that are internal bookkeeping and must not be serialized to clients.
_INTERNAL = {"_seq"}


# ---------------------------------------------------------------------------
# Lookups (existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


def find(store, _id):
    return store.get(_id)


def deadlines_for_case(case_id):
    return [d for d in db.deadlines.values() if d["case_id"] == case_id]


def parties_for_case(case_id):
    return [p for p in db.parties.values() if p["case_id"] == case_id]


def filings_for_case(case_id):
    return [f for f in db.filings.values() if f["case_id"] == case_id]


def motions_for_case(case_id):
    return [m for m in db.motions.values() if m["case_id"] == case_id]


def appeals_for_case(case_id):
    return [a for a in db.appeals.values() if a["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Case computed-field recomputation
# ---------------------------------------------------------------------------
def recompute_open_deadline_count(case):
    case["open_deadline_count"] = sum(
        1 for d in deadlines_for_case(case["id"]) if d["status"] == "PENDING"
    )


def recompute_posture(case):
    """case_posture calculation (PRD 2.7)."""
    if case["status"] == "STAYED":
        case["posture"] = "FROZEN"
        return
    dls = deadlines_for_case(case["id"])
    missed = sum(1 for d in dls if d["status"] == "MISSED")
    pending = sum(1 for d in dls if d["status"] == "PENDING")
    if missed >= 1 or pending >= calc.POSTURE_DEADLINE_LIMIT:
        case["posture"] = "RESTRICTED"
    else:
        case["posture"] = "ACTIVE"


def recompute_fee_aggregates(case):
    case_id = case["id"]
    assessed = 0
    paid = 0
    for f in filings_for_case(case_id):
        if f["status"] == "ACCEPTED" and f["fee_status"] in ("ASSESSED", "PAID"):
            assessed += f["fee_cents"]
        if f["fee_status"] in ("PAID", "WAIVED"):
            paid += f["fee_cents"]
    case["total_fees_assessed_cents"] = assessed
    case["total_fees_paid_cents"] = paid


def bump_case(case):
    """Recompute derived fields, refresh updated_at, increment version."""
    recompute_open_deadline_count(case)
    recompute_fee_aggregates(case)
    recompute_posture(case)
    db.touch(case)


def refresh_case_derived(case):
    """Recompute derived fields WITHOUT bumping version (read-path only)."""
    recompute_open_deadline_count(case)
    recompute_fee_aggregates(case)
    recompute_posture(case)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _clean(record):
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def serialize_case(case):
    refresh_case_derived(case)
    return _clean(case)


def serialize_judgment(judgment):
    out = _clean(judgment)
    out["total_with_interest_cents"] = calc.judgment_interest(judgment, db.now_clock())
    return out


def serialize(record, store):
    if store is db.cases:
        return serialize_case(record)
    if store is db.judgments:
        return serialize_judgment(record)
    return _clean(record)


# ---------------------------------------------------------------------------
# Pagination & list ordering (PRD 2.3)
# ---------------------------------------------------------------------------
def paginate(items, args):
    """Sort by created_at asc (stable by insertion seq), then page."""
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)

    limit = _int_param(args, "limit", 10, 1, 100)
    offset = _int_param(args, "offset", 0, 0, None)

    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, pagination


def _int_param(args, name, default, minimum, maximum):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid %s parameter" % name)
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val
