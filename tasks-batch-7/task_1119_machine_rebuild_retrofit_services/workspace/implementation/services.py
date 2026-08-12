"""Cross-entity business services: cascades and shared lookups."""

from db import bump, new_record, sorted_records, store
import constants as C


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def project_lines(project_id):
    return [l for l in sorted_records(store.part_lines) if l["project_id"] == project_id]


def machine_assessments(machine_id):
    return [a for a in sorted_records(store.assessments) if a["machine_id"] == machine_id]


def latest_assessment(machine_id):
    """Most recently created assessment of the machine, whatever its status."""
    items = machine_assessments(machine_id)
    return items[-1] if items else None


def machine_projects(machine_id):
    return [p for p in sorted_records(store.projects) if p["machine_id"] == machine_id]


def project_stages(project_id):
    return [s for s in sorted_records(store.stages) if s["project_id"] == project_id]


def project_tests(project_id):
    return [t for t in sorted_records(store.tests) if t["project_id"] == project_id]


def project_claims(project_id):
    return [c for c in sorted_records(store.claims) if c["project_id"] == project_id]


def project_training_record(project_id):
    for rec in sorted_records(store.training_records):
        if rec["project_id"] == project_id:
            return rec
    return None


def machine_offers(machine_id):
    return [o for o in sorted_records(store.offers) if o["machine_id"] == machine_id]


def line_re_jobs(part_line_id):
    return [j for j in sorted_records(store.re_jobs) if j["part_line_id"] == part_line_id]


def offer_applied_to_project(project_id):
    for offer in store.offers.values():
        if offer["applied_project_id"] == project_id:
            return offer
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cancel_project_cascade(project):
    """Release cascade shared by manual cancel, escalation CANCEL and the
    trade-in acceptance cascade (PRD §3.3/§3.6/§3.9).

    Lines in {PENDING, RESERVED, RE_PENDING} -> CANCELLED; RESERVED lines
    release their reservation; RE jobs of RE_PENDING lines -> CANCELLED;
    ShipmentStages in {PLANNED, ON_HOLD} -> CANCELLED.
    """
    for line in project_lines(project["id"]):
        if line["status"] in ("PENDING", "RESERVED", "RE_PENDING"):
            was_reserved = line["status"] == "RESERVED"
            was_re_pending = line["status"] == "RE_PENDING"
            line["status"] = "CANCELLED"
            bump(line)
            if was_reserved:
                part = store.parts[line["part_id"]]
                part["reserved_quantity"] -= line["quantity"]
                part["available_quantity"] = (
                    part["stock_quantity"] - part["reserved_quantity"]
                )
                bump(part)
            if was_re_pending:
                for job in line_re_jobs(line["id"]):
                    if job["status"] not in ("VALIDATED", "CANCELLED"):
                        job["status"] = "CANCELLED"
                        bump(job)
    for stage in project_stages(project["id"]):
        if stage["status"] in ("PLANNED", "ON_HOLD"):
            stage["status"] = "CANCELLED"
            bump(stage)


def park_planned_stages(project_id):
    """Acceptance-failure cascade link 2: PLANNED stages -> ON_HOLD."""
    for stage in project_stages(project_id):
        if stage["status"] == "PLANNED":
            stage["status"] = "ON_HOLD"
            bump(stage)


def create_training_record(project):
    """Bubble-up cascade on acceptance: TrainingRecord auto-created PLANNED."""
    rec = new_record(
        {
            "project_id": project["id"],
            "trainer_id": None,
            "sessions_required": C.SESSIONS_REQUIRED[project["decision"]],
            "sessions_completed": 0,
            "documentation_delivered": False,
            "status": "PLANNED",
        }
    )
    store.training_records[rec["id"]] = rec
    return rec


def maybe_complete_training(rec):
    """Re-evaluate completion after a session log or documentation delivery."""
    if (
        rec["status"] in ("PLANNED", "IN_PROGRESS")
        and rec["sessions_completed"] >= rec["sessions_required"]
        and rec["documentation_delivered"]
    ):
        rec["status"] = "COMPLETED"
        bump(rec)
        project = store.projects.get(rec["project_id"])
        if project is not None and project["work_status"] == "TRAINING_IN_PROGRESS":
            project["work_status"] = "HANDOVER_READY"
            bump(project)


def trade_in_acceptance_cascade(machine):
    """PRD §3.9: machine -> TRADED_IN; early-stage projects of the machine
    -> CANCELLED with the release cascade on each."""
    if machine["status"] == "REGISTERED":
        machine["status"] = "TRADED_IN"
        bump(machine)
    for project in machine_projects(machine["id"]):
        if project["work_status"] in ("SCOPED", "DECIDED", "PARTS_SOURCING"):
            project["work_status"] = "CANCELLED"
            bump(project)
            cancel_project_cascade(project)


def sweep_clock(clock_now):
    """Temporal sweeps on clock advance (PRD §2.7). Strictly-past boundaries
    only; trade-in offers are never swept (lazy expiry on accept)."""
    for window in store.windows.values():
        if window["status"] in ("OPEN", "LOCKED") and clock_now > window["_ends_dt"]:
            window["status"] = "CLOSED"
            bump(window)
    for project in store.projects.values():
        if project["work_status"] != "WARRANTY_ACTIVE":
            continue
        if project["_warranty_end_dt"] is None or clock_now <= project["_warranty_end_dt"]:
            continue
        open_claim = any(
            c["status"] in ("FILED", "APPROVED") for c in project_claims(project["id"])
        )
        if not open_claim:
            project["work_status"] = "CLOSED"
            bump(project)
