"""Cross-entity workflows: quote acceptance, cancellation cascade, delivery
and commissioning bubble-ups, service-agency selection, exposure ledger,
fabrication cost reconciliation, and punch-list closeout.

Every mutated entity gets exactly one db.touch() (updated_at refresh and
version +1) per logical operation, per PRD section 2.4.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from services.pricing import compute_quote_pricing, round_cents, snapshot_lines

# fabrication_cost_reconciliation constants
SCHEDULE_ALLOWANCE_DAYS = 30
OVERTIME_PENALTY_RATE = Decimal("0.04")
MAX_OVERTIME_PENALTY_PCT = Decimal("0.40")

MAX_REVIEW_CYCLES = 3

PROJECT_TERMINAL = ("COMPLETED", "CANCELLED")
PROJECT_CANCELLABLE = ("DESIGN", "QUOTED", "CONTRACTED", "FABRICATION", "DELIVERED", "COMMISSIONED")
QUOTE_OPEN = ("DRAFT", "PRESENTED")
FAB_NONTERMINAL = ("PENDING_SHOP_DRAWING", "SHOP_DRAWING_APPROVED", "IN_PRODUCTION")
JOB_NONTERMINAL = ("PLANNED", "DISPATCHED")
ITEM_NONTERMINAL = ("SCHEDULED", "ORDERED", "RECEIVED", "INSTALLED")


def items_of_project(project_id: str, include_cancelled: bool = False) -> list[dict]:
    out = [it for it in db.items.values() if it["project_id"] == project_id]
    if not include_cancelled:
        out = [it for it in out if it["status"] != "CANCELLED"]
    out.sort(key=lambda it: it["_seq"])
    return out


def adjust_exposure(customer: dict, delta: int) -> None:
    if delta:
        customer["outstanding_exposure_cents"] = int(
            customer.get("outstanding_exposure_cents", 0)
        ) + int(delta)
        db.touch(customer)


# ---------------------------------------------------------------------------
# Quote acceptance (PRD 3.3)
# ---------------------------------------------------------------------------

def accept_quote(project: dict, quote: dict, customer: dict) -> None:
    layout_id = quote["layout_id"]

    # FINAL variant: recompute every monetary field against current item state.
    lines = snapshot_lines(layout_id)
    amounts = compute_quote_pricing(lines, project["health_jurisdiction"])
    quote.update(amounts)
    quote["variant"] = "FINAL"
    quote["status"] = "ACCEPTED"
    db.touch(quote)

    # Open sibling quotes on this project are superseded.
    for q in db.quotes.values():
        if (
            q["project_id"] == project["id"]
            and q["id"] != quote["id"]
            and q["status"] in QUOTE_OPEN
        ):
            q["status"] = "SUPERSEDED"
            db.touch(q)

    # Project freezes the baseline and withholds retainage.
    project["quote_baseline_cents"] = amounts["grand_total_cents"]
    project["retainage_held_cents"] = round_cents(
        Decimal(amounts["grand_total_cents"]) * Decimal(str(project["retainage_pct"]))
    )
    project["status"] = "CONTRACTED"
    db.touch(project)

    # Items on the referenced layout move SCHEDULED -> ORDERED; each custom
    # fabrication item spawns a FabricationOrder in PENDING_SHOP_DRAWING.
    for it in db.items.values():
        if it["layout_id"] == layout_id and it["status"] == "SCHEDULED":
            it["status"] = "ORDERED"
            db.touch(it)
            if it["item_kind"] == "CUSTOM_FABRICATION":
                fab = db.stamp_new({
                    "project_id": project["id"],
                    "equipment_item_id": it["id"],
                    "shop_drawing_ref": "",
                    "quoted_fab_cost_cents": round_cents(
                        Decimal(int(it["quantity"])) * Decimal(int(it["unit_price_cents"]))
                    ),
                    "final_fab_cost_cents": None,
                    "status": "PENDING_SHOP_DRAWING",
                })
                db.fab_orders[fab["id"]] = fab

    # Exposure ledger: accepted net balance plus withheld retainage.
    adjust_exposure(
        customer,
        amounts["grand_total_cents"] + project["retainage_held_cents"],
    )


# ---------------------------------------------------------------------------
# Project cancellation cascade (PRD 3.9)
# ---------------------------------------------------------------------------

def cancel_project(project: dict, customer: dict | None) -> None:
    status = project["status"]
    baseline = int(project.get("quote_baseline_cents", 0) or 0)
    retainage = int(project.get("retainage_held_cents", 0) or 0)
    accepted = status in ("CONTRACTED", "FABRICATION", "DELIVERED", "COMMISSIONED")
    contribution = (baseline + retainage) if accepted else 0

    for q in db.quotes.values():
        if q["project_id"] == project["id"] and q["status"] in QUOTE_OPEN:
            q["status"] = "SUPERSEDED"
            db.touch(q)
    for f in db.fab_orders.values():
        if f["project_id"] == project["id"] and f["status"] in FAB_NONTERMINAL:
            f["status"] = "CANCELLED"
            db.touch(f)
    for j in db.jobs.values():
        if j["project_id"] == project["id"] and j["status"] in JOB_NONTERMINAL:
            j["status"] = "CANCELLED"
            db.touch(j)
    for it in db.items.values():
        if it["project_id"] == project["id"] and it["status"] in ITEM_NONTERMINAL:
            it["status"] = "CANCELLED"
            db.touch(it)
    for p in db.punch_items.values():
        if p["project_id"] == project["id"] and p["status"] == "OPEN":
            p["status"] = "VOID"
            db.touch(p)
    for a in db.assignments.values():
        if a["project_id"] == project["id"] and a["status"] == "OPEN":
            a["status"] = "CLOSED"
            db.touch(a)
            agency = db.agencies.get(a["agency_id"])
            if agency is not None and agency["open_assignment_count"] > 0:
                agency["open_assignment_count"] -= 1
                db.touch(agency)

    project["retainage_held_cents"] = 0
    project["status"] = "CANCELLED"
    db.touch(project)
    if customer is not None:
        adjust_exposure(customer, -contribution)


# ---------------------------------------------------------------------------
# Layout approval: supersede siblings (PRD 3.2)
# ---------------------------------------------------------------------------

def supersede_sibling_layouts(project: dict, approved_layout: dict) -> None:
    for ly in db.layouts.values():
        if (
            ly["project_id"] == project["id"]
            and ly["id"] != approved_layout["id"]
            and ly["status"] in ("SUBMITTED", "APPROVED")
        ):
            ly["status"] = "SUPERSEDED"
            db.touch(ly)
            # Layout supersede cascades to its SCHEDULED items.
            for it in db.items.values():
                if it["layout_id"] == ly["id"] and it["status"] == "SCHEDULED":
                    it["status"] = "CANCELLED"
                    db.touch(it)


# ---------------------------------------------------------------------------
# Fabrication completion: cost reconciliation (PRD 3.4)
# ---------------------------------------------------------------------------

def reconcile_fab_cost(fab: dict, item: dict) -> int:
    Q = int(fab["quoted_fab_cost_cents"])
    L = int(item.get("lead_time_days", 0))
    approved_dt = fab.get("_approved_dt") or db.now_dt()
    elapsed = db.now_dt() - approved_dt
    D = int(elapsed.total_seconds() // 86400)  # calendar days elapsed
    over = max(0, D - (L + SCHEDULE_ALLOWANCE_DAYS))
    raw_penalty = Decimal(Q) * OVERTIME_PENALTY_RATE * over
    penalty = min(raw_penalty, Decimal(Q) * MAX_OVERTIME_PENALTY_PCT)
    return round_cents(Decimal(Q) + penalty)


# ---------------------------------------------------------------------------
# Delivery bubble-up: FABRICATION/CONTRACTED -> DELIVERED (PRD 3.6)
# ---------------------------------------------------------------------------

def maybe_deliver_project(project: dict) -> None:
    if project["status"] not in ("CONTRACTED", "FABRICATION"):
        return
    for f in db.fab_orders.values():
        if f["project_id"] == project["id"] and f["status"] not in ("FAB_COMPLETE", "CANCELLED"):
            return
    for j in db.jobs.values():
        if j["project_id"] == project["id"] and j["status"] in JOB_NONTERMINAL:
            return
    project["status"] = "DELIVERED"
    db.touch(project)


# ---------------------------------------------------------------------------
# Commissioning + service-agency handoff (PRD 3.7)
# ---------------------------------------------------------------------------

def eligible_agencies(project: dict) -> list[dict]:
    out = []
    for ag in db.agencies.values():
        if ag["status"] != "ACTIVE":
            continue
        if project["health_jurisdiction"] not in (ag.get("covered_jurisdictions") or []):
            continue
        if int(ag["open_assignment_count"]) >= int(ag["capacity"]):
            continue
        out.append(ag)
    # Least loaded first; ties broken by oldest created_at (never id).
    out.sort(key=lambda a: (int(a["open_assignment_count"]), a["created_at"], a["_seq"]))
    return out


def commission_if_possible(project: dict) -> bool:
    """DELIVERED -> COMMISSIONED once every non-CANCELLED item is STARTED and
    REGISTERED, then auto-open a ServiceAssignment. If no agency qualifies the
    project stays DELIVERED and the handoff is deferred (no error)."""
    if project["status"] != "DELIVERED":
        return False
    items = items_of_project(project["id"])
    if any(
        it["status"] != "STARTED" or it["warranty_status"] != "REGISTERED"
        for it in items
    ):
        return False
    candidates = eligible_agencies(project)
    if not candidates:
        return False
    winner = candidates[0]
    assignment = db.stamp_new({
        "project_id": project["id"],
        "agency_id": winner["id"],
        "opened_at": db.now_iso(),
        "status": "OPEN",
    })
    db.assignments[assignment["id"]] = assignment
    winner["open_assignment_count"] = int(winner["open_assignment_count"]) + 1
    db.touch(winner)
    project["status"] = "COMMISSIONED"
    db.touch(project)
    return True


def retry_deferred_commissions() -> None:
    """A qualifying agency became available: retry deferred bubble-ups for
    DELIVERED projects whose items are all STARTED + REGISTERED."""
    projects = sorted(db.projects.values(), key=lambda p: (p["created_at"], p["_seq"]))
    for project in projects:
        if project["status"] == "DELIVERED":
            commission_if_possible(project)


# ---------------------------------------------------------------------------
# Closeout (PRD 3.8)
# ---------------------------------------------------------------------------

def close_punch_list(project: dict, customer: dict | None) -> None:
    released = int(project.get("retainage_held_cents", 0) or 0)
    for p in db.punch_items.values():
        if (
            p["project_id"] == project["id"]
            and p["status"] == "OPEN"
            and p["severity"] == "COSMETIC"
        ):
            p["status"] = "VOID"
            db.touch(p)
    project["retainage_held_cents"] = 0
    project["status"] = "PUNCH_CLOSED"
    db.touch(project)
    if customer is not None:
        adjust_exposure(customer, -released)


def complete_project(project: dict, customer: dict | None) -> None:
    baseline = int(project.get("quote_baseline_cents", 0) or 0)
    project["status"] = "COMPLETED"
    db.touch(project)
    if customer is not None:
        adjust_exposure(customer, -baseline)
