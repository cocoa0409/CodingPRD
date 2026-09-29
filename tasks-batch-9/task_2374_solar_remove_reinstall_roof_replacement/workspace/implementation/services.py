"""Derived-field reconciliation, posture, phase advancement and cascades."""

import calc
from db import db, ordered, touch

PROJECT_TRACKED_FIELDS = (
    "phase",
    "posture",
    "negotiation_round",
    "required_approval_party_count",
    "authorized_at",
    "deenergized_at",
    "reenergized_at",
    "provisional_credit_cents",
    "final_credit_cents",
    "credit_authorized_cents",
    "credit_reserved_cents",
    "credit_settled_cents",
    "credit_released_cents",
    "weather_abort_count",
    "warranty_notice_status",
    "warranty_notice_filed_at",
    "warranty_notice_reference",
    "warranty_preserved",
    "registered_unit_count",
    "stored_unit_count",
    "reinstalled_unit_count",
    "scrapped_unit_count",
    "damaged_unit_count",
    "open_critical_finding_count",
    "scoped_upgrade_cost_cents",
    "downtime_days_actual",
)


# --------------------------------------------------------------------------
# Child-collection accessors
# --------------------------------------------------------------------------
def project_approvals(project_id):
    return ordered([a for a in db.approvals.values() if a["project_id"] == project_id])


def project_circuits(project_id):
    return ordered([c for c in db.circuits.values() if c["project_id"] == project_id])


def project_bins(project_id):
    return ordered([b for b in db.bins.values() if b["project_id"] == project_id])


def project_units(project_id):
    return ordered([u for u in db.units.values() if u["project_id"] == project_id])


def project_findings(project_id):
    return ordered([f for f in db.findings.values() if f["project_id"] == project_id])


def project_permits(project_id):
    return ordered([p for p in db.permits.values() if p["project_id"] == project_id])


def project_windows(project_id):
    return ordered([w for w in db.windows.values() if w["project_id"] == project_id])


def permit_inspections(permit_id):
    return ordered(
        [i for i in db.inspections.values() if i["permit_application_id"] == permit_id]
    )


def project_inspections(project_id):
    permit_ids = set(p["id"] for p in project_permits(project_id))
    return ordered(
        [i for i in db.inspections.values() if i["permit_application_id"] in permit_ids]
    )


def circuit_units(circuit_id):
    return ordered([u for u in db.units.values() if u["array_circuit_id"] == circuit_id])


def unit_project(unit):
    return db.projects.get(unit["project_id"])


def permit_project(permit):
    return db.projects.get(permit["project_id"])


def inspection_permit(inspection):
    return db.permits.get(inspection["permit_application_id"])


# --------------------------------------------------------------------------
# Project snapshot / commit (PRD 2.4 + 2.10 version discipline)
# --------------------------------------------------------------------------
def project_snapshot(project):
    if project is None:
        return None
    return dict((k, project.get(k)) for k in PROJECT_TRACKED_FIELDS)


def commit_project(project, snapshot, force=False):
    """Bump updated_at / version when the project row actually changed."""
    if project is None:
        return
    changed = force
    if not changed and snapshot is not None:
        for key in PROJECT_TRACKED_FIELDS:
            if snapshot.get(key) != project.get(key):
                changed = True
                break
    if changed:
        touch(project)


# --------------------------------------------------------------------------
# project_posture (PRD 2.6)
# --------------------------------------------------------------------------
def compute_posture(project):
    project_id = project["id"]
    findings = project_findings(project_id)
    permits = project_permits(project_id)

    for finding in findings:
        if finding["status"] == "OPEN" and finding["severity"] == "CRITICAL":
            return "FROZEN"
    for permit in permits:
        if permit["status"] == "REJECTED":
            return "FROZEN"

    for finding in findings:
        if finding["severity"] == "HIGH" and finding["status"] in ("OPEN", "UPGRADE_SCOPED"):
            return "RESTRICTED"
    for permit in permits:
        if permit["status"] in ("DRAFT", "SUBMITTED"):
            jurisdiction = db.jurisdictions.get(permit["jurisdiction_id"])
            if jurisdiction and jurisdiction["repermit_required_for_reinstall"]:
                return "RESTRICTED"
    for inspection in project_inspections(project_id):
        if inspection["status"] in ("FAILED", "CORRECTION_REQUIRED"):
            return "RESTRICTED"
    if project["weather_abort_count"] >= calc.WEATHER_ABORT_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------
# storage_bin_occupancy
# --------------------------------------------------------------------------
def recompute_bin_occupancy(storage_bin):
    if storage_bin is None:
        return
    occupied = len(
        [
            u
            for u in db.units.values()
            if u["storage_bin_id"] == storage_bin["id"] and u["handling_status"] == "STORED"
        ]
    )
    if storage_bin["occupied_slots"] != occupied:
        storage_bin["occupied_slots"] = occupied
        touch(storage_bin)


# --------------------------------------------------------------------------
# Project roll-up (PRD 2.10)
# --------------------------------------------------------------------------
def rollup_project(project):
    project_id = project["id"]
    units = project_units(project_id)
    findings = project_findings(project_id)

    project["required_approval_party_count"] = (
        3 if project.get("system_owner_party_id") else 2
    )
    project["registered_unit_count"] = len(units)
    project["stored_unit_count"] = len(
        [u for u in units if u["handling_status"] == "STORED"]
    )
    project["reinstalled_unit_count"] = len(
        [u for u in units if u["handling_status"] == "REINSTALLED"]
    )
    project["scrapped_unit_count"] = len(
        [u for u in units if u["handling_status"] == "SCRAPPED"]
    )
    project["damaged_unit_count"] = len(
        [u for u in units if u["condition_grade"] == "DAMAGED"]
    )
    project["open_critical_finding_count"] = len(
        [f for f in findings if f["status"] == "OPEN" and f["severity"] == "CRITICAL"]
    )
    project["scoped_upgrade_cost_cents"] = sum(
        f["upgrade_cost_cents"]
        for f in findings
        if f["status"] in ("UPGRADE_SCOPED", "UPGRADE_COMPLETED")
    )

    reinstalled = [u for u in units if u["handling_status"] == "REINSTALLED"]
    preserved = True
    for unit in reinstalled:
        if not unit.get("warranty_preserved"):
            preserved = False
    project["warranty_preserved"] = preserved

    project["downtime_days_actual"] = len(
        calc.downtime_dates(project["deenergized_at"], project["reenergized_at"])
    )

    project["posture"] = compute_posture(project)


# --------------------------------------------------------------------------
# Phase advancement (evaluated at the end of the triggering mutation)
# --------------------------------------------------------------------------
def evaluate_authorized(project):
    if project["phase"] != "APPROVALS_OPEN":
        return
    approved = len(
        [
            a
            for a in project_approvals(project["id"])
            if a["status"] == "APPROVED"
            and a["round_recorded"] == project["negotiation_round"]
        ]
    )
    if approved != project["required_approval_party_count"]:
        return
    project["authorized_at"] = db.now()
    project["phase"] = "AUTHORIZED"
    rollup_project(project)
    evaluate_deenergized(project)


def evaluate_deenergized(project):
    if project["phase"] != "AUTHORIZED":
        return
    circuits = project_circuits(project["id"])
    if len(circuits) < 1:
        return
    if any(c["status"] != "ISOLATED" for c in circuits):
        return
    project["deenergized_at"] = db.now()
    project["phase"] = "DEENERGIZED"
    provisional = calc.provisional_credit_cents(project)
    project["provisional_credit_cents"] = provisional
    project["credit_authorized_cents"] += provisional
    project["credit_reserved_cents"] += provisional
    rollup_project(project)


def evaluate_deck_work(project):
    if project["phase"] != "DEENERGIZED":
        return
    units = project_units(project["id"])
    if len(units) < 1:
        return
    if any(u["handling_status"] not in ("STORED", "SCRAPPED") for u in units):
        return
    project["phase"] = "DECK_WORK"
    rollup_project(project)


def evaluate_reinstall(project):
    if project["phase"] != "DECK_WORK":
        return
    findings = project_findings(project["id"])
    if any(f["status"] not in ("UPGRADE_COMPLETED", "WAIVED") for f in findings):
        return
    structural_completed = any(
        f["requires_repermit"] and f["status"] == "UPGRADE_COMPLETED" for f in findings
    )
    if structural_completed:
        permits = project_permits(project["id"])
        if not any(p["status"] == "APPROVED" for p in permits):
            return
    project["phase"] = "REINSTALL"
    rollup_project(project)


def reinspection_gate_satisfied(project):
    permits = project_permits(project["id"])
    if not permits:
        return True
    requires = False
    for permit in permits:
        jurisdiction = db.jurisdictions.get(permit["jurisdiction_id"])
        if jurisdiction and jurisdiction["reinspection_required"]:
            requires = True
            break
    if not requires:
        return True
    approved_ids = set(p["id"] for p in permits if p["status"] == "APPROVED")
    for inspection in db.inspections.values():
        if (
            inspection["permit_application_id"] in approved_ids
            and inspection["inspection_type"] == "ELECTRICAL_FINAL"
            and inspection["status"] == "PASSED"
        ):
            return True
    return False


def evaluate_commissioned(project):
    if project["phase"] != "REINSTALL":
        return
    circuits = project_circuits(project["id"])
    if any(c["status"] != "ENERGIZED" for c in circuits):
        return
    if not reinspection_gate_satisfied(project):
        return
    project["reenergized_at"] = db.now()
    project["phase"] = "COMMISSIONED"
    rollup_project(project)


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def revoke_scheduled_windows(project, only_from_now=False):
    now = db.now()
    for window in project_windows(project["id"]):
        if window["status"] != "SCHEDULED":
            continue
        if only_from_now and window["start_utc"] < now:
            continue
        window["status"] = "REVOKED"
        touch(window)


def release_reserved_credit(project):
    released = project["credit_reserved_cents"]
    project["credit_reserved_cents"] = 0
    project["credit_released_cents"] += released


def ledger_balanced(project):
    return project["credit_authorized_cents"] == (
        project["credit_reserved_cents"]
        + project["credit_settled_cents"]
        + project["credit_released_cents"]
    )
