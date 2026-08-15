"""Core business logic for the Shipyard Repair & Drydock API.

Implements the calculation rules (SCAFFOLD 1.3), the cascading side effects
of the state machines (SCAFFOLD 1.2), and the clock sweeps (PRD 2.5).
All monetary math uses Decimal with per-line round-half-up (PRD 2.6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
from errors import raise_err, ERR_PRICING_INPUT_INVALID
from util import dec, fmt_dt, parse_iso8601, round_half_up_int

# --- Calculation constants (SCAFFOLD 1.3) ---
MATERIALS_MARKUP = Decimal("0.15")

TIER1_MAX_LOA_M = Decimal("100")
TIER2_MAX_LOA_M = Decimal("200")
TIER1_MULTIPLIER = Decimal("1.00")
TIER2_MULTIPLIER = Decimal("1.25")
TIER3_MULTIPLIER = Decimal("1.60")
TURNAROUND_BUFFER_HOURS = 12

LD_GRACE_DAYS = 3
LD_CAP_PCT = Decimal("0.10")
LD_TIER1_RATE_CENTS = 200000
LD_TIER1_MAX_PRICE_CENTS = 50000000
LD_TIER2_RATE_CENTS = 500000
LD_TIER2_MAX_PRICE_CENTS = 200000000
LD_TIER3_RATE_CENTS = 1000000

OWNER_APPROVAL_THRESHOLD_CENTS = 5000000
MAX_SUBCONTRACTOR_IN_PROGRESS = 3

SURVEY_TYPES = {"CLASS_RENEWAL", "CLASS_INTERMEDIATE", "USCG_INSPECTION", "LOAD_LINE"}
PERMIT_TYPES = {"HOT_WORK", "PAINT_SPRAY", "BALLAST_DISCHARGE", "HULL_BLASTING"}
PRICING_MODES = {"LUMP_SUM", "TIME_AND_MATERIALS"}


def logical_now_iso() -> str:
    """Current logical time, normalized to ISO 8601 UTC with trailing Z."""
    return fmt_dt(db.clock_dt())


# ---------------------------------------------------------------------------
# calc_bid_line_pricing (per-line rounding, then summation)
# ---------------------------------------------------------------------------

def validate_pricing_inputs(pricing_mode: str, values: dict, allow_negative_unit_price: bool) -> None:
    """Rung-8 mode-conditional pricing validation (ERR_PRICING_INPUT_INVALID).

    `values` carries the effective field values (merged, for revise):
    quantity, unit_price_cents, estimated_hours, hourly_rate_cents,
    materials_cost_cents — each either present or None. Types were already
    checked at rung 3.
    """
    quantity = values.get("quantity")
    unit_price = values.get("unit_price_cents")
    hours = values.get("estimated_hours")
    rate = values.get("hourly_rate_cents")
    materials = values.get("materials_cost_cents")

    if pricing_mode == "LUMP_SUM":
        if quantity is None or unit_price is None:
            raise_err(
                ERR_PRICING_INPUT_INVALID,
                "LUMP_SUM requires quantity and unit_price_cents",
            )
        if dec(quantity) <= 0:
            raise_err(ERR_PRICING_INPUT_INVALID, "quantity must be > 0 for LUMP_SUM")
        if unit_price < 0 and not allow_negative_unit_price:
            raise_err(
                ERR_PRICING_INPUT_INVALID,
                "negative unit_price_cents is only permitted on change orders",
            )
    else:  # TIME_AND_MATERIALS
        if hours is None or rate is None:
            raise_err(
                ERR_PRICING_INPUT_INVALID,
                "TIME_AND_MATERIALS requires estimated_hours and hourly_rate_cents",
            )
        if dec(hours) <= 0:
            raise_err(
                ERR_PRICING_INPUT_INVALID,
                "estimated_hours must be > 0 for TIME_AND_MATERIALS",
            )
        if rate < 0:
            raise_err(ERR_PRICING_INPUT_INVALID, "hourly_rate_cents must be >= 0")
    if rate is not None and rate < 0:
        raise_err(ERR_PRICING_INPUT_INVALID, "hourly_rate_cents must be >= 0")
    if materials is not None and materials < 0:
        raise_err(ERR_PRICING_INPUT_INVALID, "materials_cost_cents must be >= 0")


def price_line(
    pricing_mode: str,
    quantity,
    unit_price_cents,
    estimated_hours,
    hourly_rate_cents,
    materials_cost_cents,
) -> int:
    """line_total_cents / proposed_cost_cents; every line rounded half-up to
    integer cents individually before any summation (PRD 2.6)."""
    if pricing_mode == "LUMP_SUM":
        return round_half_up_int(dec(quantity) * dec(unit_price_cents))
    labour = round_half_up_int(dec(estimated_hours) * dec(hourly_rate_cents))
    materials = round_half_up_int(
        dec(materials_cost_cents or 0) * (Decimal("1") + MATERIALS_MARKUP)
    )
    return labour + materials


# ---------------------------------------------------------------------------
# calc_dockage_fee
# ---------------------------------------------------------------------------

def loa_multiplier(length_m) -> Decimal:
    length = dec(length_m)
    if length < TIER1_MAX_LOA_M:
        return TIER1_MULTIPLIER
    if length < TIER2_MAX_LOA_M:
        return TIER2_MULTIPLIER
    return TIER3_MULTIPLIER


def compute_dockage_fee(dock: dict, vessel: dict, start_dt: datetime, end_dt: datetime) -> int:
    """Booked whole 24-hour nights inside the half-open window x the dock's
    daily rate x the LOA multiplier, rounded half-up; the turnaround buffer
    is never chargeable."""
    seconds = (end_dt - start_dt).total_seconds()
    booked_nights = int(seconds // 86400)
    fee = dec(booked_nights) * dec(dock["daily_rate_cents"]) * loa_multiplier(vessel["length_m"])
    return round_half_up_int(fee)


# ---------------------------------------------------------------------------
# calc_liquidated_damages (tiered daily rate with a 10% price cap)
# ---------------------------------------------------------------------------

def ld_tier_rate(price_cents: int) -> int:
    if price_cents < LD_TIER1_MAX_PRICE_CENTS:
        return LD_TIER1_RATE_CENTS
    if price_cents <= LD_TIER2_MAX_PRICE_CENTS:
        return LD_TIER2_RATE_CENTS
    return LD_TIER3_RATE_CENTS


def compute_liquidated_damages(contracted_price_cents: int, contract_delivery_date: str, delivery_date) -> int:
    contract_date = datetime.strptime(contract_delivery_date, "%Y-%m-%d").date()
    late_days = max(0, (delivery_date - contract_date).days)
    chargeable_days = max(0, late_days - LD_GRACE_DAYS)
    accrued = chargeable_days * ld_tier_rate(contracted_price_cents)
    cap = round_half_up_int(LD_CAP_PCT * dec(contracted_price_cents))
    return min(accrued, cap)


# ---------------------------------------------------------------------------
# calc_critical_path_days (longest chain over the unfinished DAG)
# ---------------------------------------------------------------------------

def project_work_items(project_id: str) -> list:
    return [w for w in db.work_items.values() if w["project_id"] == project_id]


def project_change_orders(project_id: str) -> list:
    return [c for c in db.change_orders.values() if c["project_id"] == project_id]


def compute_critical_path_days(project_id: str) -> int:
    nodes = [
        w
        for w in project_work_items(project_id)
        if w["status"] in ("PLANNED", "IN_PROGRESS")
    ]
    by_id = {w["id"]: w for w in nodes}
    memo: dict[str, int] = {}

    def longest(item: dict) -> int:
        cached = memo.get(item["id"])
        if cached is not None:
            return cached
        best = 0
        for dep_id in item.get("depends_on_ids") or []:
            dep = by_id.get(dep_id)
            if dep is not None:
                best = max(best, longest(dep))
        memo[item["id"]] = item["duration_days"] + best
        return memo[item["id"]]

    return max((longest(w) for w in nodes), default=0)


def approved_schedule_delta_days(project_id: str) -> int:
    return sum(
        c["schedule_delta_days"]
        for c in project_change_orders(project_id)
        if c["status"] == "APPROVED"
    )


def compute_forecast_utc(project: dict) -> str | None:
    if project.get("actual_dock_in_utc") is None:
        return None
    dock_in = parse_iso8601(project["actual_dock_in_utc"], "actual_dock_in_utc")
    days = project["critical_path_days"] + approved_schedule_delta_days(project["id"])
    return fmt_dt(dock_in + timedelta(days=days))


def compute_provisional_ld(project: dict) -> int:
    """Forward-looking variant; frozen once DELIVERED (and stays frozen in
    CLOSED). Stands at zero before a forecast exists or before a contracted
    price exists."""
    if project["status"] in ("DELIVERED", "CLOSED"):
        return project["provisional_ld_cents"]
    forecast = project.get("forecast_delivery_utc")
    contracted = project.get("contracted_price_cents")
    if forecast is None or contracted is None:
        return 0
    forecast_date = parse_iso8601(forecast, "forecast_delivery_utc").date()
    return compute_liquidated_damages(contracted, project["contract_delivery_date"], forecast_date)


def compute_bid_total(project_id: str) -> int:
    return sum(
        w["line_total_cents"]
        for w in project_work_items(project_id)
        if w["origin_kind"] == "BASE_SPEC" and w["status"] != "CANCELLED"
    )


def refresh_project_derived(project: dict, include_bid: bool = True) -> bool:
    """Recompute the project's derived roll-ups in place (bid total, critical
    path, forecast, provisional LD). Returns True if any stored value changed
    (the caller then bumps the project version once, PRD 2.4)."""
    changed = False
    if include_bid:
        bid = compute_bid_total(project["id"])
        if project["bid_total_cents"] != bid:
            project["bid_total_cents"] = bid
            changed = True
    cp = compute_critical_path_days(project["id"])
    if project["critical_path_days"] != cp:
        project["critical_path_days"] = cp
        changed = True
    forecast = compute_forecast_utc(project)
    if project["forecast_delivery_utc"] != forecast:
        project["forecast_delivery_utc"] = forecast
        changed = True
    provisional = compute_provisional_ld(project)
    if project["provisional_ld_cents"] != provisional:
        project["provisional_ld_cents"] = provisional
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Dependency-graph acyclicity (ERR_DEPENDENCY_CYCLE)
# ---------------------------------------------------------------------------

def dependency_graph_has_cycle(project_id: str, overrides: dict | None = None) -> bool:
    """True if the project's work-item dependency graph contains a cycle or a
    self-reference. `overrides` maps item id -> prospective depends_on_ids."""
    graph: dict[str, list] = {}
    for w in project_work_items(project_id):
        graph[w["id"]] = list(w.get("depends_on_ids") or [])
    if overrides:
        for item_id, deps in overrides.items():
            graph[item_id] = list(deps)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for dep in graph.get(node, []):
            if dep == node:
                return True  # self-reference
            if dep not in color:
                continue  # dependency outside the project graph
            if color[dep] == GRAY:
                return True
            if color[dep] == WHITE and visit(dep):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and visit(n) for n in list(graph))


# ---------------------------------------------------------------------------
# Project completion gate (IN_DOCK -> WORK_COMPLETE, PRD 3.7)
# ---------------------------------------------------------------------------

def completion_gate_satisfied(project: dict) -> bool:
    items = project_work_items(project["id"])
    if not all(w["status"] in ("COMPLETE", "CANCELLED") for w in items):
        return False
    for survey_type in project.get("required_survey_types") or []:
        typed = [
            s
            for s in db.surveys.values()
            if s["project_id"] == project["id"] and s["survey_type"] == survey_type
        ]
        if not typed:
            return False
        latest = max(typed, key=lambda s: (s["created_at"], s["_seq"]))
        if latest["status"] != "PASSED":
            return False
    return True


def try_auto_complete_project(project: dict) -> bool:
    """Fire the IN_DOCK -> WORK_COMPLETE auto-transition when the gate opens.
    Cascades the ACTIVE reservation release. Does not bump the project
    version itself — the caller folds it into the request's single bump."""
    if project["status"] != "IN_DOCK":
        return False
    if not completion_gate_satisfied(project):
        return False
    project["status"] = "WORK_COMPLETE"
    for reservation in db.reservations.values():
        if reservation["project_id"] == project["id"] and reservation["status"] == "ACTIVE":
            reservation["status"] = "RELEASED"
            reservation["released_at_utc"] = logical_now_iso()
            db.touch(reservation)
    return True


# ---------------------------------------------------------------------------
# Change-order final-approval cascade (PRD 3.5, three links)
# ---------------------------------------------------------------------------

def fire_change_order_approval(change_order: dict, project: dict) -> None:
    """Materialise the growth work item and run the contracted-price / tier /
    schedule cascade. Caller bumps the change-order and project versions."""
    now = logical_now_iso()
    change_order["status"] = "APPROVED"
    change_order["approved_at_utc"] = now

    # Link 1: materialise the growth WorkItem from the change order's spec.
    growth = {
        "project_id": project["id"],
        "description": change_order["description"],
        "trade_code": change_order["trade_code"],
        "pricing_mode": change_order["pricing_mode"],
        "quantity": change_order.get("quantity"),
        "unit_price_cents": change_order.get("unit_price_cents"),
        "estimated_hours": change_order.get("estimated_hours"),
        "hourly_rate_cents": change_order.get("hourly_rate_cents"),
        "materials_cost_cents": change_order.get("materials_cost_cents", 0),
        "duration_days": change_order["duration_days"],
        "depends_on_ids": [],
        "requires_hot_work": False,
        "subcontractor_id": None,
        "origin_kind": "CHANGE_ORDER",
        "origin_change_order_id": change_order["id"],
        "line_total_cents": change_order["proposed_cost_cents"],
        "status": "PLANNED",
        "completed_at_utc": None,
    }
    db.stamp_new(growth)
    db.work_items[growth["id"]] = growth

    # Link 2: contracted price = awarded + sum(APPROVED proposed_cost_cents);
    # the new price re-selects the LD tier.
    approved_sum = sum(
        c["proposed_cost_cents"]
        for c in project_change_orders(project["id"])
        if c["status"] == "APPROVED"
    )
    project["contracted_price_cents"] = project["awarded_price_cents"] + approved_sum
    project["ld_daily_rate_cents"] = ld_tier_rate(project["contracted_price_cents"])

    # Link 3: the schedule delta joins the approved-delta sum; the growth item
    # joins the critical-path DAG; forecast and provisional LD recompute.
    refresh_project_derived(project, include_bid=False)


# ---------------------------------------------------------------------------
# Hot-work gate (PRD 3.4)
# ---------------------------------------------------------------------------

def hot_work_permit_covers(project_id: str, now: datetime) -> bool:
    for permit in db.permits.values():
        if (
            permit["project_id"] == project_id
            and permit["permit_type"] == "HOT_WORK"
            and permit["status"] == "GRANTED"
            and parse_iso8601(permit["valid_from"], "valid_from") <= now
            and now <= parse_iso8601(permit["valid_to"], "valid_to")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Clock sweeps (PRD 2.5)
# ---------------------------------------------------------------------------

def run_clock_sweeps(new_dt: datetime) -> None:
    # Non-terminal permits strictly past valid_to -> EXPIRED.
    for permit in db.permits.values():
        if permit["status"] in ("APPLIED", "GRANTED", "SUSPENDED"):
            valid_to = parse_iso8601(permit["valid_to"], "valid_to")
            if valid_to < new_dt:
                permit["status"] = "EXPIRED"
                db.touch(permit)
    # DELIVERED projects strictly past warranty_end_utc -> CLOSED (+version).
    for project in db.projects.values():
        if project["status"] == "DELIVERED" and project.get("warranty_end_utc"):
            warranty_end = parse_iso8601(project["warranty_end_utc"], "warranty_end_utc")
            if warranty_end < new_dt:
                project["status"] = "CLOSED"
                db.touch(project)
