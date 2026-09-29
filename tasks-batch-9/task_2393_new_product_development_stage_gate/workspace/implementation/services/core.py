"""Row minting, derived-field maintenance and the three cascades.

Nothing here talks HTTP; the route modules do the band-ordered checking and call
into these helpers once a write is accepted. Two rules govern the whole module:

* Derived fields are **recomputed from their live basis**, never accumulated, so
  a release is exact and drift-free (PRD §2.10).
* Any row whose stored fields actually change refreshes ``updated_at`` and
  increments ``version`` (PRD §2.4), including rows nobody named in the request.
"""

import uuid
from decimal import Decimal

import calc
import clock
import db
import validation as V

STAGE_ORDER = ("IDEA", "SCREENED", "PILOT_QUALIFIED", "LAUNCH_READY")
TERMINAL_DEV = ("KILLED", "DISCONTINUED")

LIVE_RUN = ("SCHEDULED", "RUNNING", "COMPLETED")
LIVE_STUDY = ("ACTIVE", "PASSED", "FAILED")
SLOT_HOLDING = ("PLANNED", "PRESENTED", "DEFERRED", "ACCEPTED")

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
HUNDRED = Decimal("100.00")


# ---------------------------------------------------------------------------
# row minting
# ---------------------------------------------------------------------------
def new_row(store, fields, common=True):
    """Insert a row: server-minted uuid, audit fields, insertion ordinal."""
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    now = clock.audit_stamp()
    row["created_at"] = now
    if common:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    store[row["id"]] = row
    return row


def touch(row):
    """Record a write against ``row``: fresh ``updated_at``, ``version`` + 1."""
    row["updated_at"] = clock.audit_stamp()
    row["version"] = row.get("version", 1) + 1
    return row


def apply(row, changes):
    """Write ``changes`` and touch the row, but only if something really moved."""
    moved = False
    for key, value in changes.items():
        if row.get(key) != value or key not in row:
            row[key] = value
            moved = True
    if moved:
        touch(row)
    return moved


def set_dt(row, field, raw, parsed):
    row[field] = raw
    row["_dt_" + field] = parsed


def dt_of(row, field):
    return row.get("_dt_" + field)


# ---------------------------------------------------------------------------
# child lookups
# ---------------------------------------------------------------------------
def project_cases(project_id):
    return db.children(db.business_cases, "project_id", project_id)


def project_formulations(project_id):
    return db.children(db.formulations, "project_id", project_id)


def project_deliverables(project_id):
    return db.children(db.deliverables, "project_id", project_id)


def project_presentations(project_id):
    return db.children(db.sell_in_presentations, "project_id", project_id)


def project_periods(project_id):
    return db.children(db.post_launch_periods, "project_id", project_id)


def formulation_runs(formulation_id):
    return db.children(db.pilot_runs, "formulation_id", formulation_id)


def formulation_studies(formulation_id):
    return db.children(db.shelf_life_studies, "formulation_id", formulation_id)


def case_lines(business_case_id):
    return db.children(db.forecast_lines, "business_case_id", business_case_id)


def review_votes(gate_review_id):
    return db.children(db.gate_votes, "gate_review_id", gate_review_id)


def project_runs(project_id):
    ids = {f["id"] for f in project_formulations(project_id)}
    return [r for r in db.rows(db.pilot_runs) if r["formulation_id"] in ids]


def project_studies(project_id):
    ids = {f["id"] for f in project_formulations(project_id)}
    return [s for s in db.rows(db.shelf_life_studies) if s["formulation_id"] in ids]


def project_of_formulation(formulation):
    return db.projects.get(formulation["project_id"])


# ---------------------------------------------------------------------------
# the two derived notions of PRD §2.11
# ---------------------------------------------------------------------------
def authoritative_case(project_id):
    """Most recently created case that is not SUPERSEDED; created_at ASC, last."""
    live = [c for c in project_cases(project_id) if c["status"] != "SUPERSEDED"]
    return live[-1] if live else None


def current_formulation(project_id):
    """Highest ``revision`` whose status is not SUPERSEDED."""
    live = [f for f in project_formulations(project_id) if f["status"] != "SUPERSEDED"]
    if not live:
        return None
    best = live[0]
    for row in live[1:]:
        if row["revision"] > best["revision"]:
            best = row
    return best


def authoritative_concept_test(project_id):
    """Greatest ``fielded_at``; earliest created among ties."""
    tests = db.children(db.concept_tests, "project_id", project_id)
    if not tests:
        return None
    best = tests[0]
    for row in tests[1:]:
        if dt_of(row, "fielded_at") > dt_of(best, "fielded_at"):
            best = row
    return best


def refresh_concept_authority(project_id):
    winner = authoritative_concept_test(project_id)
    for row in db.children(db.concept_tests, "project_id", project_id):
        apply(row, {"is_authoritative": winner is not None and row["id"] == winner["id"]})


# ---------------------------------------------------------------------------
# conserved quantities
# ---------------------------------------------------------------------------
def committed_budget(project_id, skip_run=None, skip_study=None):
    total = ZERO2
    for run in project_runs(project_id):
        if run["status"] in LIVE_RUN and run["id"] != skip_run:
            total += run["committed_cost_usd"]
    for study in project_studies(project_id):
        if study["status"] in LIVE_STUDY and study["id"] != skip_study:
            total += study["committed_cost_usd"]
    return calc.money(total)


def recompute_ledger(project):
    apply(project, {"development_budget_committed_usd":
                    committed_budget(project["id"])})


def recompute_slots(window):
    count = 0
    for row in db.rows(db.sell_in_presentations):
        if row["shelf_reset_window_id"] == window["id"] and row["status"] in SLOT_HOLDING:
            count += 1
    apply(window, {"booked_slot_count": count})


def recompute_acv(project, extra=None):
    total = ZERO2
    for row in project_presentations(project["id"]):
        if row["status"] == "ACCEPTED":
            retailer = db.retailers.get(row["retailer_id"])
            if retailer:
                total += retailer["acv_contribution_pct"]
    total = calc.money(total)
    if total > HUNDRED:
        total = HUNDRED
    changes = {"authorized_acv_pct": total}
    if extra:
        changes.update(extra)
    apply(project, changes)


def recompute_best_yield(formulation):
    best = ZERO2
    for run in formulation_runs(formulation["id"]):
        if run["status"] == "COMPLETED" and run.get("yield_pct") is not None:
            if run["yield_pct"] > best:
                best = run["yield_pct"]
    apply(formulation, {"best_pilot_yield_pct": calc.money(best)})


# ---------------------------------------------------------------------------
# gate configuration lookups
# ---------------------------------------------------------------------------
def gate_for(category, gate_number):
    """The gate configuration registered for a (category, gate_number) pair."""
    for row in db.rows(db.stage_gates):
        if row["category"] == category and row["gate_number"] == gate_number:
            return row
    return None


def commercialization_gate(category):
    """The gate whose ``stage_to`` is LAUNCH_READY, lowest gate_number first."""
    best = None
    for row in db.rows(db.stage_gates):
        if row["category"] == category and row["stage_to"] == "LAUNCH_READY":
            if best is None or row["gate_number"] < best["gate_number"]:
                best = row
    return best


# ---------------------------------------------------------------------------
# checklists
# ---------------------------------------------------------------------------
def create_checklist(project, gate):
    """Auto-create the gate's checklist, skipping pairs already on the project."""
    if gate is None:
        return []
    existing = {(d["gate_id"], d["deliverable_type"])
                for d in project_deliverables(project["id"])}
    made = []
    for kind in gate["required_deliverable_types"]:
        if (gate["id"], kind) in existing:
            continue
        made.append(new_row(db.deliverables, {
            "project_id": project["id"],
            "gate_id": gate["id"],
            "deliverable_type": kind,
            "owner_function": V.DELIVERABLE_OWNER_MAP[kind],
            "prerequisite_deliverable_id": None,
            "status": "PENDING",
            "due_at": None,
            "evidence_url": None,
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "submission_count": 0,
        }))
        existing.add((gate["id"], kind))
    return made


def create_next_checklist(project):
    """Create the checklist of the gate the project must convene next, if apt."""
    gate = gate_for(project["category"], project["next_gate_number"])
    if gate is not None and gate["stage_from"] == project["dev_status"]:
        create_checklist(project, gate)


def auto_approve(project_id, deliverable_type):
    """Evidence-driven auto-approval: PENDING -> APPROVED, nobody credited."""
    hit = False
    for row in project_deliverables(project_id):
        if row["deliverable_type"] == deliverable_type and row["status"] == "PENDING":
            apply(row, {
                "status": "APPROVED",
                "evidence_url": V.AUTO_EVIDENCE_URL,
                "submitted_by_user_id": None,
                "decided_by_user_id": None,
            })
            hit = True
    if hit and deliverable_type in V.READINESS_TYPES:
        project = db.projects.get(project_id)
        if project is not None:
            recompute_launch_readiness(project)
    return hit


def completeness_for(project_id, gate):
    """deliverable_completeness_pct of a gate's own checklist."""
    required = gate["required_deliverable_types"]
    if not required:
        return calc.EMPTY_CHECKLIST_RESULT
    satisfied = set()
    for row in project_deliverables(project_id):
        if row["gate_id"] == gate["id"] and row["status"] in ("APPROVED", "WAIVED"):
            satisfied.add(row["deliverable_type"])
    return calc.deliverable_completeness_pct(required, satisfied)


# ---------------------------------------------------------------------------
# launch readiness
# ---------------------------------------------------------------------------
def readiness_picture(project):
    """``(pct, blocking_types)`` over the commercialisation gate's demands."""
    gate = commercialization_gate(project["category"])
    required = []
    if gate is not None:
        required = [t for t in gate["required_deliverable_types"]
                    if t in calc.LAUNCH_READINESS_WEIGHTS]
    approved = set()
    for row in project_deliverables(project["id"]):
        if row["status"] == "APPROVED" and row["deliverable_type"] in required:
            approved.add(row["deliverable_type"])
    pct = calc.launch_readiness_pct(required, approved)
    blocking = [t for t in required if t not in approved]
    return pct, blocking


def recompute_launch_readiness(project):
    pct, _ = readiness_picture(project)
    apply(project, {"launch_readiness_pct": pct})


# ---------------------------------------------------------------------------
# business-case hurdles and the readiness index
# ---------------------------------------------------------------------------
def hurdles_cleared(case, gate):
    """How many of the gate's three financial bars the case clears."""
    if case is None:
        return 0
    cleared = 0
    if case["npv_usd"] >= gate["npv_hurdle_usd"]:
        cleared += 1
    if case["payback_months"] <= gate["payback_months_max"]:
        cleared += 1
    if case["gross_margin_pct"] >= gate["gross_margin_floor_pct"]:
        cleared += 1
    return cleared


def readiness_index_for(project, gate, completeness):
    case = authoritative_case(project["id"])
    cleared = hurdles_cleared(case, gate)
    if cleared == 3:
        hurdle = Decimal("100.00")
    elif cleared == 2:
        hurdle = Decimal("50.00")
    else:
        hurdle = ZERO2

    test = authoritative_concept_test(project["id"])
    concept = test["concept_score"] if test is not None else ZERO2

    formulation = current_formulation(project["id"])
    yield_sub = formulation["best_pilot_yield_pct"] if formulation is not None else ZERO2

    return calc.gate_readiness_index(
        project["project_type"], project["category"],
        completeness, concept, hurdle, yield_sub,
    )


# ---------------------------------------------------------------------------
# business-case recomputation
# ---------------------------------------------------------------------------
def recompute_case(case, extra=None):
    lines = case_lines(case["id"])
    for line in lines:
        units, revenue = calc.forecast_line_figures(line)
        apply(line, {"line_units": units, "line_revenue_usd": revenue})

    annual_units, gross, avg_price = calc.forecast_volume_and_revenue(case, lines)
    financials = calc.business_case_financials(
        annual_units, gross, case["cogs_per_unit_usd"],
        case["slotting_fees_usd"], case["capex_usd"], case["discount_rate_pct"],
    )
    changes = {
        "annual_units": annual_units,
        "gross_revenue_usd": gross,
        "avg_list_price_usd": avg_price,
    }
    changes.update(financials)
    if extra:
        changes.update(extra)
    apply(case, changes)


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def release_presentation(row, project, withdraw_acv):
    """Move a slot-holding presentation to WITHDRAWN and release what it held."""
    was_accepted = row["status"] == "ACCEPTED"
    apply(row, {"status": "WITHDRAWN"})
    window = db.shelf_reset_windows.get(row["shelf_reset_window_id"])
    if window is not None:
        recompute_slots(window)
    if was_accepted and withdraw_acv:
        recompute_acv(project)


def kill_cascade(project, source_review_id=None):
    """§3.6 — a vetoed gate decision unwinds the whole project."""
    for row in project_deliverables(project["id"]):
        if row["status"] in ("PENDING", "SUBMITTED", "REJECTED"):
            apply(row, {"status": "CANCELLED"})
    for row in db.children(db.gate_reviews, "project_id", project["id"]):
        if row["id"] != source_review_id and row["status"] == "SCHEDULED":
            apply(row, {"status": "CANCELLED"})
    for row in project_presentations(project["id"]):
        if row["status"] in SLOT_HOLDING:
            release_presentation(row, project, True)
    apply(project, {
        "commercial_status": "NOT_STARTED",
        "launch_date": None,
        "shelf_reset_window_id": None,
    })
    project["_dt_launch_date"] = None


def winddown_cascade(project):
    """§3.9 — a DISCONTINUE decision withdraws only the not-yet-accepted slots."""
    for row in project_presentations(project["id"]):
        if row["status"] in ("PLANNED", "PRESENTED", "DEFERRED"):
            release_presentation(row, project, False)


def step_back(project, gate, extra=None):
    """§3.6 — one rung down the ladder, floored at SCREENED."""
    try:
        index = STAGE_ORDER.index(gate["stage_from"])
    except ValueError:
        index = 1
    target = STAGE_ORDER[max(1, index - 1)]
    changes = {
        "dev_status": target,
        "next_gate_number": max(2, gate["gate_number"] - 1),
        "recycle_count": project["recycle_count"] + 1,
    }
    if extra:
        changes.update(extra)
    apply(project, changes)
    create_next_checklist(project)


def supersede_cascade(project, old):
    """§3.7 — the depth-four invalidation behind a new formulation revision."""
    apply(old, {"status": "SUPERSEDED"})

    for run in formulation_runs(old["id"]):
        if run["status"] in ("SCHEDULED", "RUNNING"):
            apply(run, {"status": "CANCELLED"})
    for study in formulation_studies(old["id"]):
        if study["status"] == "ACTIVE":
            apply(study, {"status": "ABANDONED"})
    recompute_ledger(project)

    cleared_label = False
    for label in db.children(db.label_approvals, "formulation_id", old["id"]):
        if label["status"] in ("APPROVED", "CONDITIONAL"):
            apply(label, {"status": "INVALIDATED"})
            cleared_label = True

    if cleared_label:
        for row in project_deliverables(project["id"]):
            if (row["deliverable_type"] == "REGULATORY_CLEARANCE"
                    and row["status"] == "APPROVED"):
                apply(row, {"status": "PENDING", "evidence_url": None})

    if cleared_label and project["commercial_status"] == "LAUNCH_LOCKED":
        apply(project, {
            "commercial_status": "LOCK_SLIPPED",
            "launch_date": None,
            "shelf_reset_window_id": None,
        })
        project["_dt_launch_date"] = None
        recompute_launch_readiness(project)
