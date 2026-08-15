"""Compliance status engine (next_due_date mapping, PRD §3.7) and plan/ledger
aggregates (budget_burn + labor_hour_aggregation, PRD §2.8/§3.2)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, touch, new_append_fields, fmt_ts
from .core import age_months  # noqa: F401  (re-export convenience)

DUE_SOON_WINDOW_OCCUPIED_DAYS = 7
DUE_SOON_WINDOW_VACANT_DAYS = 1

OPEN_VISIT_STATES = ("SCHEDULED", "NOTIFIED", "IN_PROGRESS")


def current_template_for(asset):
    """The component's current (non-retired) template in the asset's property.

    When several current templates share (property, component_type), the most
    recently created one governs. None when no current template exists.
    """
    prop = _property_of_asset(asset)
    if prop is None:
        return None
    candidates = [
        t for t in store.templates.values()
        if t["property_id"] == prop["id"]
        and t["component_type"] == asset["component_type"]
        and t["retired_at"] is None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t["_seq"])
    return candidates[-1]


def _property_of_asset(asset):
    unit = store.units.get(asset["unit_id"])
    if unit is None:
        return None
    building = store.buildings.get(unit["building_id"])
    if building is None:
        return None
    return store.properties.get(building["property_id"])


def _unit_of_asset(asset):
    return store.units.get(asset["unit_id"])


def _latest_completed_visit(asset, template):
    visits = [
        v for v in store.visits.values()
        if v["asset_id"] == asset["id"]
        and v["template_id"] == template["id"]
        and v["visit_status"] == "COMPLETED"
    ]
    if not visits:
        return None
    visits.sort(key=lambda v: (v["_sched_dt"], v["_seq"]))
    return visits[-1]


def _open_visit_exists(asset, template):
    return any(
        v for v in store.visits.values()
        if v["asset_id"] == asset["id"]
        and v["template_id"] == template["id"]
        and v["visit_status"] in OPEN_VISIT_STATES
    )


def _audit_of_visit(visit_id):
    for a in store.audits.values():
        if a["visit_id"] == visit_id:
            return a
    return None


def compute_compliance_status(asset, clock=None):
    """Pure mapping per PRD §3.7, evaluated in strict order."""
    clock = clock or now()
    template = current_template_for(asset)
    if template is None:
        return "COMPLIANT"
    latest = _latest_completed_visit(asset, template)
    if latest is not None:
        last_completed = latest["_sched_dt"]
    else:
        inst = asset["_installed_dt"]
        last_completed = datetime(inst.year, inst.month, inst.day, tzinfo=timezone.utc)
    next_due = last_completed + timedelta(days=template["frequency_days"])

    # 1. Outstanding failed audit on the latest completed visit.
    if latest is not None:
        audit = _audit_of_visit(latest["id"])
        if audit is not None and audit["outcome"] == "FAIL":
            return "NON_COMPLIANT"
    # 2. clock >= next_due (inclusive) -> OVERDUE.
    if clock >= next_due:
        return "OVERDUE"
    # 3. Inside due-soon window and no open visit -> DUE.
    unit = _unit_of_asset(asset)
    window_days = (DUE_SOON_WINDOW_OCCUPIED_DAYS
                   if unit is not None and unit["occupancy_status"] == "OCCUPIED"
                   else DUE_SOON_WINDOW_VACANT_DAYS)
    if next_due - timedelta(days=window_days) <= clock < next_due:
        if not _open_visit_exists(asset, template):
            return "DUE"
    # 4. Otherwise compliant.
    return "COMPLIANT"


def recompute_asset_compliance(asset, bump=True):
    """Recompute and persist compliance_status; cascade-mutate on change."""
    new_status = compute_compliance_status(asset)
    if new_status != asset["compliance_status"]:
        asset["compliance_status"] = new_status
        if bump:
            touch(asset)
        return True
    return False


def recompute_all_assets():
    for asset in store.assets.values():
        recompute_asset_compliance(asset)


# ---------------------------------------------------------------------------
# Ledger + plan aggregates (budget_burn, labor_hour_aggregation)
# ---------------------------------------------------------------------------

def add_ledger_entry(plan_id, entry_kind, amount_cents,
                     source_visit_id=None, source_work_order_id=None, memo=""):
    rec = new_append_fields()
    rec.update({
        "plan_id": plan_id,
        "entry_kind": entry_kind,
        "amount_cents": int(amount_cents),
        "source_visit_id": source_visit_id,
        "source_work_order_id": source_work_order_id,
        "memo": memo,
    })
    store.ledger[rec["id"]] = rec
    return rec


def _plan_entries(plan_id):
    return [e for e in store.ledger.values() if e["plan_id"] == plan_id]


def committed_cents(plan_id):
    total = 0
    for e in _plan_entries(plan_id):
        if e["entry_kind"] in ("VISIT_COMMIT", "WO_COMMIT"):
            total += e["amount_cents"]
        elif e["entry_kind"] in ("VISIT_RELEASE", "WO_RELEASE") \
                and "release-of-commit" in e["memo"]:
            total += e["amount_cents"]
    return total


def spent_cents(plan_id):
    total = 0
    for e in _plan_entries(plan_id):
        if e["entry_kind"] in ("VISIT_SETTLE", "WO_SETTLE"):
            total += e["amount_cents"]
        elif e["entry_kind"] == "WO_RELEASE" and "release-of-settle" in e["memo"]:
            total += e["amount_cents"]
    return total


def planned_labor_hours(plan_id):
    minutes = 0
    for v in store.visits.values():
        if v["plan_id"] == plan_id and v["visit_status"] in (
                "SCHEDULED", "NOTIFIED", "IN_PROGRESS", "COMPLETED"):
            tpl = store.templates.get(v["template_id"])
            if tpl is not None:
                minutes += tpl["estimated_labor_minutes"]
    if minutes <= 0:
        return 0
    return -(-minutes // 60)  # ceiling


def actual_labor_minutes(plan_id):
    return sum(
        v["actual_minutes"] or 0
        for v in store.visits.values()
        if v["plan_id"] == plan_id and v["visit_status"] == "COMPLETED"
    )


def plan_aggregates(plan_id):
    return {
        "planned_labor_hours": planned_labor_hours(plan_id),
        "actual_labor_minutes": actual_labor_minutes(plan_id),
        "committed_cents": committed_cents(plan_id),
        "spent_cents": spent_cents(plan_id),
    }


# ---------------------------------------------------------------------------
# Batch auto-execution
# ---------------------------------------------------------------------------

def maybe_execute_batch(batch):
    if batch["status"] not in ("PUBLISHED", "LOCKED"):
        return False
    open_visits = [
        v for v in store.visits.values()
        if v["batch_id"] == batch["id"] and v["visit_status"] != "CANCELLED"
    ]
    if all(v["visit_status"] in ("COMPLETED", "NO_ACCESS") for v in open_visits):
        batch["status"] = "EXECUTED"
        touch(batch)
        return True
    return False


# ---------------------------------------------------------------------------
# Compliance summary (compliance_rate)
# ---------------------------------------------------------------------------

def compliance_summary(property_id):
    assessed = []
    for a in store.assets.values():
        if a["operational_status"] not in ("IN_SERVICE", "OUT_OF_SERVICE"):
            continue
        prop = _property_of_asset(a)
        if prop is not None and prop["id"] == property_id:
            assessed.append(a)
    assessed_count = len(assessed)
    compliant_count = sum(1 for a in assessed if a["compliance_status"] == "COMPLIANT")
    if assessed_count == 0:
        rate = Decimal("100.00")
    else:
        rate = (Decimal(compliant_count * 10000) / Decimal(assessed_count)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP) / Decimal(100)
    return {
        "compliance_rate_pct": float(rate),
        "compliant_count": compliant_count,
        "assessed_count": assessed_count,
    }
