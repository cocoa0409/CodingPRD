"""Business logic: calculations (scaffold `calculations`), derived-field
reconciliation, serializers, and shared lookup/list helpers."""

from decimal import ROUND_HALF_UP, Decimal

import db
from clock import logical_clock
from errors import ERR_NOT_FOUND, raise_error
from response import ok_list
from util import new_id, now_iso, pagination_params

BASE_YEAR = 2026
WATCH_FCI_THRESHOLD = Decimal("0.05")
CRITICAL_FCI_THRESHOLD = Decimal("0.10")

SEVERITY_WEIGHT = Decimal("0.6")
URGENCY_WEIGHT = Decimal("0.4")
CODE_BONUS = Decimal(10)
ACCESSIBILITY_BONUS = Decimal(5)


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------

def new_record():
    """Common system-managed properties (PRD section 2.4): version starts
    at 1."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    """Serialize a record: everything except internal underscore fields."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{label} not found: {rid}")
    return rec


def list_response(records):
    """Sorted by created_at ascending (oldest first), then paginated."""
    ordered = sorted(records, key=lambda r: r["created_at"])
    limit, offset = pagination_params()
    page = ordered[offset : offset + limit]
    return ok_list([pub(r) for r in page], limit, offset, len(ordered))


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_rul(install_year, design_life_years, condition_rating):
    """remaining_useful_life (base variant): age-based decay with condition
    overrides. Integer years, no rounding."""
    age_years = logical_clock.year() - install_year
    rul = max(0, design_life_years - age_years)
    if condition_rating == 1:
        rul = 0
    elif condition_rating == 2:
        rul = min(rul, 2)
    return rul


def pessimistic_rul(system):
    """Stress-test variant: base RUL minus a further 2 years, floored at 0.
    Computed from the system's stored (base) remaining useful life."""
    return max(0, system["remaining_useful_life_years"] - 2)


def compute_priority_score(severity, urgency, is_code_violation, is_accessibility_violation):
    """deficiency_priority_score: weighted scoring, round-half-up to 2 dp."""
    score = SEVERITY_WEIGHT * severity + URGENCY_WEIGHT * urgency
    if is_code_violation:
        score += CODE_BONUS
    if is_accessibility_violation:
        score += ACCESSIBILITY_BONUS
    return float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def escalated_cost(cost_estimate_cents, escalation_rate, planned_year):
    """escalated_cost (escalated_to_year_of_need variant): compound forward
    from BASE_YEAR to planned_year, round-half-up to whole cents exactly
    once."""
    years_out = planned_year - BASE_YEAR
    rate = Decimal(str(escalation_rate))
    amount = Decimal(cost_estimate_cents) * ((Decimal(1) + rate) ** years_out)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived-field reconciliation (immediate consistency, PRD section 2.9)
# ---------------------------------------------------------------------------

def recompute_facility(fac):
    """facility_condition_index calculation: persist CRV, backlog, FCI and
    bump the facility's version."""
    systems = [s for s in db.asset_systems.values() if s["facility_id"] == fac["id"]]
    all_ids = {s["id"] for s in systems}
    crv = sum(
        s["replacement_cost_cents"] for s in systems if s["status"] != "RETIRED"
    )
    backlog = sum(
        d["cost_estimate_cents"]
        for d in db.deficiencies.values()
        if d["asset_system_id"] in all_ids
        and d["remediation_status"] in ("OPEN", "IN_PROGRESS")
    )
    if crv == 0:
        fci = 0.0
    else:
        fci = float(
            (Decimal(backlog) / Decimal(crv)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        )
    fac["current_replacement_value_cents"] = crv
    fac["backlog_cost_cents"] = backlog
    fac["facility_condition_index"] = fci
    touch(fac)


def recompute_plan_total(plan):
    """total_programmed_cents = sum of escalated_cost_cents over the plan's
    FUNDED line items."""
    plan["total_programmed_cents"] = sum(
        i["escalated_cost_cents"]
        for i in db.plan_line_items.values()
        if i["capital_plan_id"] == plan["id"] and i["funding_status"] == "FUNDED"
    )
    touch(plan)


def recompute_bundle(bundle):
    """bundled_cost_cents = sum of escalated_cost_cents over attached line
    items that remain FUNDED."""
    bundle["bundled_cost_cents"] = sum(
        i["escalated_cost_cents"]
        for i in db.plan_line_items.values()
        if i.get("project_bundle_id") == bundle["id"]
        and i["funding_status"] == "FUNDED"
    )
    touch(bundle)


# ---------------------------------------------------------------------------
# Refresh-cycle / snapshot helpers
# ---------------------------------------------------------------------------

def open_cycle_for(facility_id):
    for cycle in db.refresh_cycles.values():
        if cycle["facility_id"] == facility_id and cycle["status"] == "OPEN":
            return cycle
    return None


def current_epoch(fac):
    """The facility's current epoch: the OPEN cycle's epoch when one exists,
    otherwise the ratified assessment_epoch."""
    cycle = open_cycle_for(fac["id"])
    return cycle["epoch"] if cycle is not None else fac["assessment_epoch"]


def append_snapshot(system, epoch, note):
    """ConditionSnapshot is immutable: only id and created_at, no
    updated_at/version (PRD section 2.4)."""
    snap = {
        "id": new_id(),
        "created_at": now_iso(),
        "asset_system_id": system["id"],
        "condition_rating": system["condition_rating"],
        "remaining_useful_life_years": system["remaining_useful_life_years"],
        "epoch": epoch,
        "note": note,
    }
    db.condition_snapshots[snap["id"]] = snap
    return snap


# ---------------------------------------------------------------------------
# plan_refresh_health calculation (threshold classification)
# ---------------------------------------------------------------------------

def refresh_health(fac):
    systems = [
        s
        for s in db.asset_systems.values()
        if s["facility_id"] == fac["id"] and s["status"] != "RETIRED"
    ]
    total_systems = len(systems)
    stale_systems = sum(
        1 for s in systems if s["last_assessed_epoch"] < fac["assessment_epoch"]
    )
    sysmap = {
        s["id"]: s
        for s in db.asset_systems.values()
        if s["facility_id"] == fac["id"]
    }
    stressed_backlog = sum(
        d["cost_estimate_cents"]
        for d in db.deficiencies.values()
        if d["asset_system_id"] in sysmap
        and d["remediation_status"] in ("OPEN", "IN_PROGRESS")
        and pessimistic_rul(sysmap[d["asset_system_id"]]) <= 0
    )
    if total_systems == 0:
        health = "NO_DATA"
    elif stale_systems > 0:
        health = "STALE"
    else:
        fci = Decimal(str(fac["facility_condition_index"]))
        if fci >= CRITICAL_FCI_THRESHOLD:
            health = "CRITICAL"
        elif fci >= WATCH_FCI_THRESHOLD:
            health = "WATCH"
        else:
            health = "GOOD"
    return {
        "health": health,
        "stale_systems": stale_systems,
        "total_systems": total_systems,
        "stressed_backlog_cents": stressed_backlog,
    }
