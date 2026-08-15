"""Domain services: serializers, live-derived fields, reserve recompute,
clock sweeps, funding-threshold re-evaluation, shared lookup helpers."""
from flask import request

import store
from calc import COVERAGE_SOLVENT_BPS
from errors import ApiError
from store import touch
from validate import parse_dt

DOCUMENTED_STATUSES = ("EXECUTED", "FUNDED", "ACTIVE", "SUSPENDED", "MATURED", "SETTLED")
ANNUITY_VEHICLES = ("CGA", "CRT_UNITRUST", "CRT_ANNUITY")
VEHICLES = ("CGA", "CRT_UNITRUST", "CRT_ANNUITY", "BEQUEST")
FREQUENCIES = ("ANNUAL", "SEMIANNUAL", "QUARTERLY", "MONTHLY")
RESTRICTIONS = ("UNRESTRICTED", "SCHOLARSHIP", "FACULTY_SUPPORT", "RESEARCH", "CAPITAL")
SLOTS = ("PRIMARY_1", "PRIMARY_2", "CONTINGENT")
ASSET_KINDS = ("CASH", "SECURITIES", "REAL_ESTATE")
MILESTONE_KINDS = (
    "PETITION",
    "NOTICE_TO_CREDITORS",
    "INVENTORY",
    "APPRAISAL",
    "FINAL_ACCOUNTING",
    "COURT_ORDER",
)


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------
def view(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def donor_view(d):
    out = view(d)
    out["documented_gift_total_cents"] = sum(
        a["gift_amount_cents"]
        for a in store.agreements.values()
        if a["donor_id"] == d["id"] and a["status"] in DOCUMENTED_STATUSES
    )
    return out


def agreement_assets(agreement_id):
    return [x for x in store.assets.values() if x.get("gift_agreement_id") == agreement_id]


def agreement_payments(agreement_id):
    return [p for p in store.payments.values() if p["gift_agreement_id"] == agreement_id]


def received_value_cents(agreement_id):
    """Sum over linked assets in RECEIVED/APPRAISED/LIQUIDATED/DISTRIBUTED:
    CASH -> pledged_value_cents, SECURITIES -> fmv_cents,
    REAL_ESTATE -> appraised_value_cents (0 until appraised)."""
    total = 0
    for x in agreement_assets(agreement_id):
        if x["status"] in ("RECEIVED", "APPRAISED", "LIQUIDATED", "DISTRIBUTED"):
            if x["asset_kind"] == "CASH":
                total += x["pledged_value_cents"]
            elif x["asset_kind"] == "SECURITIES":
                total += x.get("fmv_cents") or 0
            elif x["asset_kind"] == "REAL_ESTATE":
                total += x.get("appraised_value_cents") or 0
    return total


def agreement_view(a):
    out = view(a)
    pays = agreement_payments(a["id"])
    out["received_value_cents"] = received_value_cents(a["id"])
    out["total_paid_cents"] = sum(p["amount_cents"] for p in pays if p["status"] == "PAID")
    out["total_scheduled_cents"] = sum(p["amount_cents"] for p in pays)
    out["liability_released_cents"] = sum(
        p["amount_cents"] for p in pays if p["status"] == "LAPSED"
    )
    return out


def estate_view(e):
    out = view(e)
    out["gross_proceeds_cents"] = sum(
        x["net_proceeds_cents"] or 0
        for x in store.assets.values()
        if x.get("estate_id") == e["id"] and x["status"] in ("LIQUIDATED", "DISTRIBUTED")
    )
    return out


# ---------------------------------------------------------------------------
# reserve fund (PRD 2.8 — pinned evaluation order)
# ---------------------------------------------------------------------------
def compute_reserve_derived():
    booked = sum(
        a.get("reserve_requirement_cents") or 0
        for a in store.agreements.values()
        if a["vehicle_type"] == "CGA" and a["status"] in ("FUNDED", "ACTIVE", "SUSPENDED")
    )
    projected = booked + sum(
        a.get("reserve_requirement_cents") or 0
        for a in store.agreements.values()
        if a["vehicle_type"] == "CGA" and a["status"] == "EXECUTED"
    )
    balance = store.reserve_fund["balance_cents"]
    coverage = None if booked == 0 else (balance * 10000) // booked  # floored
    posture = (
        "SOLVENT"
        if (booked == 0 or coverage >= COVERAGE_SOLVENT_BPS)
        else "RESERVE_DEFICIENT"
    )
    return booked, projected, coverage, posture


def update_reserve(new_balance=None):
    """Apply a balance change (optional) and recompute targets/coverage/posture.
    The reserve fund's version increments once when anything mutated (PRD 2.8)."""
    r = store.reserve_fund
    changed = False
    if new_balance is not None and new_balance != r["balance_cents"]:
        r["balance_cents"] = new_balance
        changed = True
    booked, projected, coverage, posture = compute_reserve_derived()
    if (
        booked != r["booked_target_cents"]
        or projected != r["projected_target_cents"]
        or coverage != r["booked_coverage_bps"]
        or posture != r["posture"]
    ):
        r["booked_target_cents"] = booked
        r["projected_target_cents"] = projected
        r["booked_coverage_bps"] = coverage
        r["posture"] = posture
        changed = True
    if changed:
        touch(r)


# ---------------------------------------------------------------------------
# clock sweeps (PRD 2.4)
# ---------------------------------------------------------------------------
def sweep_payments(target=None):
    """SCHEDULED -> DUE when due_date <= now; DEFERRED -> DUE when
    defer_until <= now. Each flipped payment gets version += 1."""
    t = store.now()
    items = [target] if target is not None else list(store.payments.values())
    for p in items:
        if p is None:
            continue
        if p["status"] == "SCHEDULED" and parse_dt(p["due_date"]) <= t:
            p["status"] = "DUE"
            touch(p)
        elif (
            p["status"] == "DEFERRED"
            and p.get("defer_until")
            and parse_dt(p["defer_until"]) <= t
        ):
            p["status"] = "DUE"
            touch(p)


def sweep_milestones():
    """PENDING/FILED -> OVERDUE when due_date < now (strictly before)."""
    t = store.now()
    for m in store.milestones.values():
        if m["status"] in ("PENDING", "FILED") and parse_dt(m["due_date"]) < t:
            m["status"] = "OVERDUE"
            touch(m)


# ---------------------------------------------------------------------------
# funding threshold (EXECUTED -> FUNDED auto-transition, PRD 3.5)
# ---------------------------------------------------------------------------
def reevaluate_funding(agreement):
    if (
        agreement["status"] == "EXECUTED"
        and agreement["vehicle_type"] != "BEQUEST"
        and received_value_cents(agreement["id"]) >= agreement["gift_amount_cents"]
    ):
        agreement["status"] = "FUNDED"
        touch(agreement)
        update_reserve()


# ---------------------------------------------------------------------------
# lookups + list helpers
# ---------------------------------------------------------------------------
def lookup(table, entity_id, label):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found: %s" % (label, entity_id))
    return entity


def paginate(items):
    """limit default 10 (min 1, max 100), offset default 0 (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


def matches(entity, filters):
    """filters: {query_param: entity_field_or_None_for_identity}."""
    for param, field in filters.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if entity.get(field or param) != raw:
            return False
    return True


# ---------------------------------------------------------------------------
# rate-table helpers (PRD 2.7 — half-open windows)
# ---------------------------------------------------------------------------
def table_window(table):
    start = parse_dt(table["effective_from"])
    end = parse_dt(table["effective_to"]) if table.get("effective_to") else None
    return start, end


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; adjacency is NOT overlap;
    None end reads as +infinity."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


def active_table_covering(moment_dt):
    for t in store.rate_tables.values():
        if t["status"] != "ACTIVE":
            continue
        start, end = table_window(t)
        if start <= moment_dt and (end is None or moment_dt < end):
            return t
    return None
