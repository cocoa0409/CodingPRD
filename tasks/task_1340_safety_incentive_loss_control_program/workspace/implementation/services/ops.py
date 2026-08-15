"""Workflow services: incentive event ledger, hazard auto-transitions with
their close cascade, the operations sweep, and program close-out."""

import db
from clock import CLOCK
from services import calc
from services.core import new_id, stamp_new, touch
from util import D


# --- incentive event ledger ---------------------------------------------------

def create_event(program_id, employee_id, source_type, reference_id,
                 timeliness=None):
    base = calc.EVENT_BASE_POINTS[source_type]
    emp = db.DB["employees"].get(employee_id)
    mult = calc.class_multiplier_for_employee(emp)
    time_mult = D("1.25") if timeliness else D("1.0")
    ev = stamp_new({
        "id": new_id(),
        "program_id": program_id,
        "employee_id": employee_id,
        "source_type": source_type,
        "points_base": base,
        "hazard_class_multiplier": mult,
        "timeliness_multiplier": time_mult,
        "points_awarded": calc.points_awarded(base, mult, time_mult),
        "reference_id": reference_id,
    }, with_version=False)
    db.DB["events"][ev["id"]] = ev
    return ev


# --- derived counters ----------------------------------------------------------

def recompute_pending_training(emp):
    n = sum(1 for t in db.DB["training_assignments"].values()
            if t["employee_id"] == emp["id"] and t["required"]
            and t["status"] in ("ASSIGNED", "EXPIRED"))
    if n != emp["pending_required_training_count"]:
        emp["pending_required_training_count"] = n
        touch(emp)


def recompute_overdue_counts(hazard):
    """Refresh the hazard's and its program's OVERDUE-control counters (PRD 2.11:
    a derivation is recomputed as part of any mutation that changes its inputs)."""
    n = sum(1 for c in db.DB["controls"].values()
            if c["hazard_id"] == hazard["id"] and c["status"] == "OVERDUE")
    if n != hazard["overdue_control_count"]:
        hazard["overdue_control_count"] = n
        touch(hazard)
    program = db.DB["programs"].get(hazard["program_id"])
    if program is not None:
        total = sum(1 for c in db.DB["controls"].values()
                    if c["status"] == "OVERDUE"
                    and (db.DB["hazards"].get(c["hazard_id"]) or {}).get("program_id")
                    == program["id"])
        if total != program["overdue_control_count"]:
            program["overdue_control_count"] = total
            touch(program)


# --- hazard auto-transitions ----------------------------------------------------

def _hazard_controls(hazard):
    return [c for c in db.DB["controls"].values() if c["hazard_id"] == hazard["id"]]


def _close_hazard_cascade(hazard):
    """Hazard reached CLOSED: every LINKED observation naming it closes and pays
    its reporter (scaffold Hazard.CLOSED side effects)."""
    for o in sorted((o for o in db.DB["observations"].values()
                     if o["linked_hazard_id"] == hazard["id"]
                     and o["status"] == "LINKED"),
                    key=lambda r: r["_seq"]):
        o["status"] = "CLOSED"
        touch(o)
        st = "OBSERVATION_VALIDATED" if o["kind"] == "OBSERVATION" \
            else "NEAR_MISS_VALIDATED"
        create_event(hazard["program_id"], o["reporter_id"], st, o["id"])


def advance_hazard(hazard):
    """Run the automatic Hazard transitions as far as they chain. The whole
    request-level advancement is one hazard mutation (one version bump)."""
    changed = False
    closed = False
    while True:
        controls = _hazard_controls(hazard)
        if hazard["status"] == "ASSESSED" and controls:
            hazard["status"] = "CONTROLS_PLANNED"
            changed = True
            continue
        if hazard["status"] == "CONTROLS_PLANNED" and any(
                c["status"] in ("IMPLEMENTED", "VERIFIED") for c in controls):
            hazard["status"] = "IN_PROGRESS"
            changed = True
            continue
        if hazard["status"] == "IN_PROGRESS" and controls \
                and all(c["status"] in ("IMPLEMENTED", "VERIFIED") for c in controls) \
                and any(c["status"] == "IMPLEMENTED" for c in controls):
            hazard["status"] = "PENDING_VERIFICATION"
            changed = True
            continue
        if hazard["status"] == "PENDING_VERIFICATION" and controls \
                and all(c["status"] == "VERIFIED" for c in controls):
            hazard["status"] = "CLOSED"
            changed = True
            closed = True
            continue
        break
    if changed:
        touch(hazard)
    if closed:
        _close_hazard_cascade(hazard)


# --- operations sweep (PRD 3.7) --------------------------------------------------

def sweep_program(program, exposure_hours=None):
    now = CLOCK.now()
    if exposure_hours is not None:
        program["exposure_hours"] = exposure_hours
    pid = program["id"]

    # 1. PLANNED controls past due -> OVERDUE (controls of this program's hazards).
    overdue_controls = 0
    affected_hazards = set()
    for c in sorted(db.DB["controls"].values(), key=lambda r: r["_seq"]):
        if c["status"] != "PLANNED" or not (c["due_date"] < now):
            continue
        h = db.DB["hazards"].get(c["hazard_id"])
        if h is None or h["program_id"] != pid:
            continue
        c["status"] = "OVERDUE"
        touch(c)
        overdue_controls += 1
        affected_hazards.add(h["id"])
    for hid in affected_hazards:
        recompute_overdue_counts(db.DB["hazards"][hid])

    # 2. ASSIGNED action items past due -> ESCALATED (meetings of this program).
    escalated_actions = 0
    for a in sorted(db.DB["action_items"].values(), key=lambda r: r["_seq"]):
        if a["status"] != "ASSIGNED" or not (a["due_date"] < now):
            continue
        m = db.DB["meetings"].get(a["meeting_id"])
        if m is None or m["program_id"] != pid:
            continue
        a["status"] = "ESCALATED"
        touch(a)
        escalated_actions += 1

    # 3. ASSIGNED training assignments past due -> EXPIRED (global: assignments
    #    are not program-linked).
    expired_assignments = 0
    affected_emps = set()
    for t in sorted(db.DB["training_assignments"].values(), key=lambda r: r["_seq"]):
        if t["status"] == "ASSIGNED" and t["due_date"] < now:
            t["status"] = "EXPIRED"
            touch(t)
            expired_assignments += 1
            affected_emps.add(t["employee_id"])
    for eid in affected_emps:
        emp = db.DB["employees"].get(eid)
        if emp is not None:
            recompute_pending_training(emp)

    # 4. ISSUED recommendations past due -> OVERDUE (this program).
    overdue_recommendations = 0
    for r in sorted(db.DB["recommendations"].values(), key=lambda r: r["_seq"]):
        if r["program_id"] == pid and r["status"] == "ISSUED" and r["due_date"] < now:
            r["status"] = "OVERDUE"
            touch(r)
            overdue_recommendations += 1

    # 5. APPROVED contractors past prequal_valid_until -> EXPIRED (global).
    expired_contractors = 0
    for c in sorted(db.DB["contractors"].values(), key=lambda r: r["_seq"]):
        if c["status"] == "APPROVED" and c["prequal_valid_until"] is not None \
                and c["prequal_valid_until"] < now:
            c["status"] = "EXPIRED"
            touch(c)
            expired_contractors += 1

    # 6. SLA breach flags on this program's non-CLOSED hazards.
    for h in sorted((h for h in db.DB["hazards"].values() if h["program_id"] == pid),
                    key=lambda r: r["_seq"]):
        if h["status"] != "CLOSED" and h["response_sla_due"] is not None \
                and h["response_sla_due"] < now and not h["sla_breached"]:
            h["sla_breached"] = True
            touch(h)
    program["sla_breach_count"] = sum(
        1 for h in db.DB["hazards"].values()
        if h["program_id"] == pid and h["status"] != "CLOSED" and h["sla_breached"])

    # 7. Integrity flag refresh (leading-indicator computation, PRD 3.4).
    program["integrity_flag"] = calc.compute_integrity_flag(program)

    # 8. Posture recompute, most severe band down (calculations.program_posture).
    overdue_lcr_count = sum(1 for r in db.DB["recommendations"].values()
                            if r["program_id"] == pid and r["status"] == "OVERDUE")
    program["posture"] = calc.posture_for(
        program["overdue_control_count"], program["sla_breach_count"],
        program["integrity_flag"], overdue_lcr_count)

    program["sweep_index"] += 1
    touch(program)

    return {
        "overdue_controls": overdue_controls,
        "escalated_actions": escalated_actions,
        "expired_assignments": expired_assignments,
        "overdue_recommendations": overdue_recommendations,
        "expired_contractors": expired_contractors,
        "posture": program["posture"],
        "sweep_index": program["sweep_index"],
    }


# --- program close-out (PRD 3.8) -------------------------------------------------

def close_program(program):
    """Run the bonus pass (BALANCED only) then create CALCULATED awards for
    every employee holding at least one event in the program."""
    pid = program["id"]

    if program["scoring_variant"] == "BALANCED":
        claims_present = any(c["program_id"] == pid
                             and c["status"] in ("ACCEPTED", "CLOSED")
                             for c in db.DB["claims"].values())
        integrity = calc.compute_integrity_flag(program)
        program["integrity_flag"] = integrity
        if not claims_present and not integrity:
            recipients = []
            seen = set()
            for ev in sorted(db.DB["events"].values(), key=lambda r: r["_seq"]):
                if ev["program_id"] == pid and ev["employee_id"] not in seen:
                    seen.add(ev["employee_id"])
                    recipients.append(ev["employee_id"])
            for emp_id in recipients:
                create_event(pid, emp_id, "CLAIMS_FREE_BONUS", pid)

    by_emp = {}
    for ev in sorted(db.DB["events"].values(), key=lambda r: r["_seq"]):
        if ev["program_id"] == pid:
            by_emp.setdefault(ev["employee_id"], 0)
            by_emp[ev["employee_id"]] += ev["points_awarded"]
    for emp_id, points in by_emp.items():
        tier = calc.tier_for_points(points)
        award = stamp_new({
            "id": new_id(),
            "program_id": pid,
            "employee_id": emp_id,
            "points_earned": points,
            "tier": tier,
            "payout_cents": calc.payout_for_points(points, tier),
            "void_reason": None,
            "status": "CALCULATED",
        })
        db.DB["awards"][award["id"]] = award

    program["status"] = "CLOSED"
    touch(program)
