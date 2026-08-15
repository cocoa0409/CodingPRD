"""Cross-entity workflows: ledger aggregation, allocation (re)computation,
snapshot-certification cascade (depths 1-3), and the finding/visit/grant
bubble-up. All side effects are atomic within the triggering request.
"""

import db
from services import calc


# --- lookup helpers -----------------------------------------------------------
def grant_allocations(grant_id):
    return [a for a in db.allocations.values() if a["grant_id"] == grant_id]


def grant_set_asides(grant_id):
    return [s for s in db.set_asides.values() if s["grant_id"] == grant_id]


def grant_expenditures(grant_id):
    return [e for e in db.expenditures.values() if e["grant_id"] == grant_id]


def grant_snapshots(grant_id):
    return [s for s in db.snapshots.values() if s["grant_id"] == grant_id]


def grant_visits(grant_id):
    return [v for v in db.visits.values() if v["grant_id"] == grant_id]


def visit_findings(visit_id):
    return [f for f in db.findings.values() if f["visit_id"] == visit_id]


# --- ledger_aggregation ---------------------------------------------------------
def recompute_ledgers(grant):
    """Recompute grant/allocation/set-aside ledger totals eagerly.
    Returns the list of resources whose stored totals changed."""
    exps = grant_expenditures(grant["id"])
    changed = []

    def _set(resource, field, value):
        if resource[field] != value:
            resource[field] = value
            if resource not in changed:
                changed.append(resource)

    _set(grant, "liquidated_cents",
         sum(e["amount_cents"] for e in exps if e["status"] == "ALLOWED"))
    _set(grant, "pending_cents",
         sum(e["amount_cents"] for e in exps if e["status"] == "PENDING_REVIEW"))
    for alloc in grant_allocations(grant["id"]):
        own = [e for e in exps if e["school_allocation_id"] == alloc["id"]]
        _set(alloc, "liquidated_cents",
             sum(e["amount_cents"] for e in own if e["status"] == "ALLOWED"))
        _set(alloc, "pending_cents",
             sum(e["amount_cents"] for e in own if e["status"] == "PENDING_REVIEW"))
    for sa in grant_set_asides(grant["id"]):
        own = [e for e in exps if e["set_aside_id"] == sa["id"]]
        _set(sa, "liquidated_cents",
             sum(e["amount_cents"] for e in own if e["status"] == "ALLOWED"))
    return changed


def set_aside_pending_cents(set_aside_id):
    return sum(
        e["amount_cents"]
        for e in db.expenditures.values()
        if e["set_aside_id"] == set_aside_id and e["status"] == "PENDING_REVIEW"
    )


def refresh_supplement_ok(allocation):
    allocation["supplement_ok"] = any(
        d for d in db.sns_docs.values()
        if d["school_allocation_id"] == allocation["id"] and d["status"] == "ACCEPTED"
    )


# --- allocation figure computation ----------------------------------------------
def _apply_ranking_figures(allocation, entry, figures):
    f = figures[allocation["school_id"]]
    allocation["snapshot_id"] = allocation.get("snapshot_id")
    allocation["low_income_student_count"] = entry["low_income_student_count"]
    allocation["total_student_count"] = entry["total_student_count"]
    allocation["poverty_pct_bp"] = f["poverty_pct_bp"]
    allocation["rank_position"] = f["rank_position"]
    allocation["eligibility_flag"] = f["eligibility_flag"]
    allocation["program_model"] = f["program_model"]


def create_allocations_from_snapshot(grant, snapshot):
    """lock-rankings side effect: one PENDING SchoolAllocation per entry."""
    figures = calc.compute_ranking(snapshot["entries"], db.schools)
    for entry in snapshot["entries"]:
        alloc = db.init_common({
            "grant_id": grant["id"],
            "school_id": entry["school_id"],
            "snapshot_id": snapshot["id"],
            "serve_elected": False,
            "per_pupil_cents": 0,
            "allocation_amount_cents": 0,
            "liquidated_cents": 0,
            "pending_cents": 0,
            "supplement_ok": False,
            "status": "PENDING",
        })
        _apply_ranking_figures(alloc, entry, figures)
        alloc["snapshot_id"] = snapshot["id"]
        db.allocations[alloc["id"]] = alloc


def run_finalize_arithmetic(grant):
    """Set-aside minimums + equitable share + waterfall over the served set."""
    mins = calc.non_equitable_minimums(grant)
    allocs = grant_allocations(grant["id"])
    served = [
        a for a in allocs
        if a["eligibility_flag"] != "BELOW_THRESHOLD" or a["serve_elected"]
    ]
    li_public = sum(a["low_income_student_count"] for a in served)
    li_private = calc.private_low_income_count(
        grant, list(db.consultations.values()), list(db.private_schools.values())
    )
    eq_min, school_pool = calc.equitable_minimum(grant, li_private, li_public)
    mins["EQUITABLE_SERVICES"] = eq_min

    for sa in grant_set_asides(grant["id"]):
        if sa["category"] in mins:
            sa["minimum_cents"] = mins[sa["category"]]
        if sa["category"] == "PARENT_ENGAGEMENT":
            sa["school_distributed_minimum_cents"] = calc.pe_school_distributed_minimum(
                sa["reserved_cents"]
            )
        db.touch(sa)

    for a in allocs:
        if a not in served:
            a["per_pupil_cents"] = 0
            a["allocation_amount_cents"] = 0
    calc.run_waterfall(served, school_pool)
    for a in allocs:
        db.touch(a)


def create_set_asides(grant):
    for category in (
        "PARENT_ENGAGEMENT", "HOMELESS_SERVICES",
        "PROFESSIONAL_DEVELOPMENT", "EQUITABLE_SERVICES",
    ):
        sa = db.init_common({
            "grant_id": grant["id"],
            "category": category,
            "minimum_cents": 0,
            "reserved_cents": 0,
            "school_distributed_minimum_cents": 0,
            "liquidated_cents": 0,
        })
        db.set_asides[sa["id"]] = sa
    # Fill minimums + reserved via the finalize arithmetic.
    mins = calc.non_equitable_minimums(grant)
    allocs = grant_allocations(grant["id"])
    served = [
        a for a in allocs
        if a["eligibility_flag"] != "BELOW_THRESHOLD" or a["serve_elected"]
    ]
    li_public = sum(a["low_income_student_count"] for a in served)
    li_private = calc.private_low_income_count(
        grant, list(db.consultations.values()), list(db.private_schools.values())
    )
    eq_min, _pool = calc.equitable_minimum(grant, li_private, li_public)
    mins["EQUITABLE_SERVICES"] = eq_min
    for sa in grant_set_asides(grant["id"]):
        sa["minimum_cents"] = mins[sa["category"]]
        sa["reserved_cents"] = mins[sa["category"]]
        if sa["category"] == "PARENT_ENGAGEMENT":
            sa["school_distributed_minimum_cents"] = calc.pe_school_distributed_minimum(
                sa["reserved_cents"]
            )


def finalize_allocations(grant):
    create_set_asides(grant)
    allocs = grant_allocations(grant["id"])
    served = [
        a for a in allocs
        if a["eligibility_flag"] != "BELOW_THRESHOLD" or a["serve_elected"]
    ]
    li_public = sum(a["low_income_student_count"] for a in served)
    li_private = calc.private_low_income_count(
        grant, list(db.consultations.values()), list(db.private_schools.values())
    )
    _eq, school_pool = calc.equitable_minimum(grant, li_private, li_public)
    for a in allocs:
        if a not in served:
            a["per_pupil_cents"] = 0
            a["allocation_amount_cents"] = 0
    calc.run_waterfall(served, school_pool)
    for a in allocs:
        db.touch(a)
    for sa in grant_set_asides(grant["id"]):
        db.touch(sa)


# --- snapshot certification cascade ---------------------------------------------
def certify_snapshot_cascade(snapshot, grant):
    """Depths 1-3 per PRD 3.2, executed atomically."""
    now = db.now_ts()
    snapshot["status"] = "CERTIFIED"
    snapshot["certified_at"] = now
    db.touch(snapshot)

    # Depth 1: certified-cardinality invariant.
    for other in grant_snapshots(grant["id"]):
        if other["id"] != snapshot["id"] and other["status"] == "CERTIFIED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    if grant["status"] in ("RANKING_LOCKED", "ALLOCATED"):
        figures = calc.compute_ranking(snapshot["entries"], db.schools)
        entry_by_school = {e["school_id"]: e for e in snapshot["entries"]}
        existing = grant_allocations(grant["id"])
        flipped = []
        for alloc in existing:
            entry = entry_by_school[alloc["school_id"]]
            was = alloc["status"]
            _apply_ranking_figures(alloc, entry, figures)
            alloc["snapshot_id"] = snapshot["id"]
            if was == "CERTIFIED":
                alloc["status"] = "PENDING"
                flipped.append(alloc)
            db.touch(alloc)
        known_school_ids = {a["school_id"] for a in existing}
        for entry in snapshot["entries"]:
            if entry["school_id"] not in known_school_ids:
                alloc = db.init_common({
                    "grant_id": grant["id"],
                    "school_id": entry["school_id"],
                    "snapshot_id": snapshot["id"],
                    "serve_elected": False,
                    "per_pupil_cents": 0,
                    "allocation_amount_cents": 0,
                    "liquidated_cents": 0,
                    "pending_cents": 0,
                    "supplement_ok": False,
                    "status": "PENDING",
                })
                _apply_ranking_figures(alloc, entry, figures)
                alloc["snapshot_id"] = snapshot["id"]
                db.allocations[alloc["id"]] = alloc

        # Depth 3: SNS STALE cascade + screened-expenditure disallowal.
        for alloc in flipped:
            for doc in db.sns_docs.values():
                if doc["school_allocation_id"] == alloc["id"] and doc["status"] == "ACCEPTED":
                    doc["status"] = "STALE"
                    db.touch(doc)
            alloc["supplement_ok"] = False
            for exp in db.expenditures.values():
                if (
                    exp["school_allocation_id"] == alloc["id"]
                    and exp["status"] == "PENDING_REVIEW"
                    and exp["supplant_screen"]
                ):
                    exp["status"] = "DISALLOWED"
                    exp["disallow_reason"] = "SNS_STALE_CASCADE"
                    db.touch(exp)
        recompute_ledgers(grant)

        if grant["status"] == "ALLOCATED":
            # Re-run set-aside minimums, the equitable share, and the waterfall.
            run_finalize_arithmetic(grant)

    grant["ranking_version"] += 1
    db.touch(grant)


# --- monitoring bubble-up ---------------------------------------------------------
def recompute_clearance(grant):
    grant["monitoring_clearance"] = calc.monitoring_clearance(
        grant["id"], list(db.visits.values()), list(db.findings.values())
    )


def finding_terminal_bubble_up(finding):
    """Depth 2-3 bubble-up when a finding reaches a terminal state."""
    visit = db.visits[finding["visit_id"]]
    grant = db.grants[visit["grant_id"]]
    if visit["status"] == "REPORT_ISSUED":
        siblings = visit_findings(visit["id"])
        if all(f["status"] in ("VERIFIED", "CLOSED_NO_ACTION") for f in siblings):
            visit["status"] = "CLOSED"
            db.touch(visit)
    recompute_clearance(grant)
    db.touch(grant)
