"""Cross-entity reconciliation and cascade helpers.

These are invoked as side effects of triggering operations: when a unit's
low-income contribution changes, the owning building is reconciled; when a
finding is created / reported / corrected, the owning project's posture and
open_finding_count are recomputed.
"""

from datetime import datetime, timedelta, timezone

from db import db, new_id, stamp_create, touch
from clock import clock
from services import calc

import errors


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_project(pid):
    return db.projects.get(pid)


def get_building(bid):
    return db.buildings.get(bid)


def get_unit(uid):
    return db.units.get(uid)


def units_for_building(building_id):
    return [u for u in db.units.values() if u["building_id"] == building_id]


def findings_for_project(project_id):
    return [f for f in db.findings.values() if f["project_id"] == project_id]


def buildings_for_project(project_id):
    return [b for b in db.buildings.values() if b["project_id"] == project_id]


def units_for_project(project_id):
    building_ids = {b["id"] for b in buildings_for_project(project_id)}
    return [u for u in db.units.values() if u["building_id"] in building_ids]


# ---------------------------------------------------------------------------
# Building credit reconciliation (§3.5)
# ---------------------------------------------------------------------------

def reconcile_building(building):
    """Recompute applicable_fraction, qualified_basis_cents, annual_credit_cents.

    Mutates the building (touch) only when a derived field actually changes.
    """
    units = units_for_building(building["id"])
    af, qb, credit = calc.building_applicable_fraction_and_credit(building, units)
    af_f = float(af)
    changed = (
        building.get("applicable_fraction") != af_f
        or building.get("qualified_basis_cents") != qb
        or building.get("annual_credit_cents") != credit
    )
    building["applicable_fraction"] = af_f
    building["qualified_basis_cents"] = qb
    building["annual_credit_cents"] = credit
    if changed:
        touch(building)
    return building


# ---------------------------------------------------------------------------
# Project posture (§2.8 / §1.3 project_posture)
# ---------------------------------------------------------------------------

def recompute_project_posture(project):
    """Recompute posture and open_finding_count from findings under the project."""
    findings = findings_for_project(project["id"])
    open_count = sum(1 for f in findings if f["status"] == "OPEN")
    reported_count = sum(1 for f in findings if f["status"] == "REPORTED_8823")
    unresolved = open_count + reported_count
    if reported_count >= 1:
        posture = "NONCOMPLIANT"
    elif open_count >= 1:
        posture = "AT_RISK"
    else:
        posture = "COMPLIANT"
    changed = (
        project.get("posture") != posture
        or project.get("open_finding_count") != unresolved
    )
    project["posture"] = posture
    project["open_finding_count"] = unresolved
    if changed:
        touch(project)
    return project


# ---------------------------------------------------------------------------
# Finding creation
# ---------------------------------------------------------------------------

def create_finding(project_id, building_id, inspection_id, category, discovered_on, origin_agent_id):
    finding = {
        "id": new_id(),
        "project_id": project_id,
        "building_id": building_id,
        "inspection_id": inspection_id,
        "category": category,
        "discovered_on": discovered_on,
        "origin_agent_id": origin_agent_id,
        "status": "OPEN",
        "reported_8823_on": None,
    }
    stamp_create(finding)
    db.findings[finding["id"]] = finding
    # Cascade: the new finding bumps the project's posture/open_finding_count.
    project = db.projects.get(project_id)
    if project is not None:
        recompute_project_posture(project)
    return finding


# ---------------------------------------------------------------------------
# Interval / datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    s = str(value).strip()
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        raise errors.validation("Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lease_overlaps(new_start, new_end, e_start, e_end):
    """Half-open, zero-buffer overlap: (new_start < e_end) AND (e_start < new_end)."""
    return (new_start < e_end) and (e_start < new_end)


def inspection_conflicts(new_start, new_end, e_start, e_end):
    """Closed intervals expanded by a 7-day buffer.

    conflicts := (new_start <= e_end + BUFFER) AND (e_start <= new_end + BUFFER)
    """
    buffer = timedelta(days=calc.INSPECTION_BUFFER_DAYS)
    return (new_start <= e_end + buffer) and (e_start <= new_end + buffer)
