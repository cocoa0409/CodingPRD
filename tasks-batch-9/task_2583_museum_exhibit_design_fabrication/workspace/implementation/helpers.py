"""Shared lookups, cascade bookkeeping, derived counters and posture (PRD §2.4-§2.10)."""

from flask import g

import calc
from errors import ApiError
from store import db, order_created

PHASE_LADDER = (
    "INTERPRETIVE",
    "SCHEMATIC",
    "DESIGN_DEV",
    "FABRICATION",
    "INSTALLATION",
    "COMMISSIONING",
    "CLOSEOUT",
    "WARRANTY_CLOSED",
)

# Only these six advances are reachable through advance-phase; the final step to
# WARRANTY_CLOSED is the settlement operation, not an advance (PRD §3.1).
PHASE_SUCCESSOR = {
    "INTERPRETIVE": "SCHEMATIC",
    "SCHEMATIC": "DESIGN_DEV",
    "DESIGN_DEV": "FABRICATION",
    "FABRICATION": "INSTALLATION",
    "INSTALLATION": "COMMISSIONING",
    "COMMISSIONING": "CLOSEOUT",
}

MOUNT_LADDER = ("NOT_STARTED", "MOUNT_DESIGN", "MOUNT_FABRICATED", "MOUNT_INSTALLED")
MOUNT_SUCCESSOR = {
    "NOT_STARTED": "MOUNT_DESIGN",
    "MOUNT_DESIGN": "MOUNT_FABRICATED",
    "MOUNT_FABRICATED": "MOUNT_INSTALLED",
}


# --- cascade bookkeeping -------------------------------------------------
def touch(row):
    """Refresh updated_at and advance version by exactly one (PRD §2.4, §2.10).

    Idempotent within a single request: a row mutated twice by one request still
    advances its version by exactly 1.
    """
    if row is None:
        return
    seen = g.get("touched", None)
    if seen is None:
        seen = set()
        g.touched = seen
    key = (row["_kind"], row["id"])
    if key in seen:
        return
    seen.add(key)
    row["updated_at"] = db.now()
    row["version"] = row["version"] + 1


# --- existence lookups (PRD §2.5, ladder step 5) ------------------------
def _lookup(table, key, error_id):
    if key is None:
        return None
    row = table.get(key, None)
    if row is None:
        raise ApiError(error_id)
    return row


def get_project(pid):
    return _lookup(db.projects, pid, "ERR_PROJECT_NOT_FOUND")


def get_package(pid):
    return _lookup(db.packages, pid, "ERR_PACKAGE_NOT_FOUND")


def get_round(rid):
    return _lookup(db.rounds, rid, "ERR_ROUND_NOT_FOUND")


def get_zone(zid):
    return _lookup(db.zones, zid, "ERR_ZONE_NOT_FOUND")


def get_case(cid):
    return _lookup(db.cases, cid, "ERR_CASE_NOT_FOUND")


def get_artifact(aid):
    return _lookup(db.artifacts, aid, "ERR_ARTIFACT_NOT_FOUND")


def get_interactive(iid):
    return _lookup(db.interactives, iid, "ERR_INTERACTIVE_NOT_FOUND")


def get_material(mid):
    return _lookup(db.materials, mid, "ERR_MATERIAL_NOT_FOUND")


def get_drawing(did):
    return _lookup(db.drawings, did, "ERR_DRAWING_NOT_FOUND")


def get_window(wid):
    return _lookup(db.windows, wid, "ERR_WINDOW_NOT_FOUND")


def get_punch_item(pid):
    return _lookup(db.punch_items, pid, "ERR_PUNCH_ITEM_NOT_FOUND")


def owning_project(row):
    return db.projects[row["project_id"]]


def require_same_project(project, row):
    """Ladder step 6: a row that exists but is misfiled under another commission."""
    if row is None:
        return
    if row["project_id"] != project["id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE")


# --- collection helpers -------------------------------------------------
def rows_of_project(table, project_id):
    return sorted((r for r in table.values() if r["project_id"] == project_id), key=order_created)


def packages_of_project(project_id):
    return rows_of_project(db.packages, project_id)


def rounds_of_package(package_id):
    return sorted((r for r in db.rounds.values() if r["package_id"] == package_id), key=order_created)


def rounds_of_project(project_id):
    ids = set(p["id"] for p in db.packages.values() if p["project_id"] == project_id)
    return sorted((r for r in db.rounds.values() if r["package_id"] in ids), key=order_created)


def votes_of_round(round_id):
    return sorted((v for v in db.votes.values() if v["round_id"] == round_id), key=order_created)


def cases_of_zone(zone_id):
    return sorted((c for c in db.cases.values() if c["zone_id"] == zone_id), key=order_created)


def windows_of_zone(zone_id):
    return sorted((w for w in db.windows.values() if w["zone_id"] == zone_id), key=order_created)


def artifacts_assigned_to_case(case_id):
    return sorted((a for a in db.artifacts.values() if a["assigned_case_id"] == case_id),
                  key=order_created)


def envelope_set(case_id):
    """Objects currently RESERVED or PLACED in the case (PRD §3.4)."""
    return [a for a in artifacts_assigned_to_case(case_id)
            if a["placement_status"] in ("RESERVED", "PLACED")]


def drawings_of_material(material_id):
    return sorted((d for d in db.drawings.values() if d["material_spec_id"] == material_id),
                  key=order_created)


def drawings_of_case(case_id):
    return sorted((d for d in db.drawings.values() if d["subject_case_id"] == case_id),
                  key=order_created)


# --- derived quantities -------------------------------------------------
def case_envelope_of(case, extra=None):
    members = envelope_set(case["id"])
    if extra is not None:
        members = members + [extra]
    return calc.case_envelope(case, members)


def placed_artifact_count(case):
    return len(envelope_set(case["id"]))


def zone_reserved_slots(zone):
    return len([c for c in db.cases.values()
                if c["zone_id"] == zone["id"] and c["status"] in ("APPROVED", "CONDITIONALLY_APPROVED")])


def zone_available_slots(zone):
    return zone["case_slot_capacity"] - zone_reserved_slots(zone)


def project_counters(project, exclude_case_id=None, exclude_material_id=None):
    """Derived counters of PRD §2.9.

    ``exclude_case_id`` / ``exclude_material_id`` drop one row's own rejection
    from ``conservation_block_count``.  §3.5 states that resubmitting a rejected
    case is "only reachable once every *other* conservation block on the project
    has already been cleared", and §3.6 says resubmitting a rejected material
    "clears that rejection's contribution to conservation_block_count", so the
    freeze test guarding those two submissions ignores the row being resubmitted.
    """
    pid = project["id"]
    rejected_cases = len([c for c in db.cases.values()
                          if c["project_id"] == pid and c["status"] == "REJECTED"
                          and c["id"] != exclude_case_id])
    rejected_materials = len([m for m in db.materials.values()
                              if m["project_id"] == pid and m["status"] == "REJECTED"
                              and m["id"] != exclude_material_id])
    veto_count = project["conservation_veto_count"]
    counters = {
        "conservation_veto_count": veto_count,
        "conservation_block_count": rejected_cases + rejected_materials + veto_count,
        "open_revision_count": len([p for p in db.packages.values()
                                    if p["project_id"] == pid and p["status"] == "REVISION_REQUESTED"]),
        "conditional_case_count": len([c for c in db.cases.values()
                                       if c["project_id"] == pid
                                       and c["status"] == "CONDITIONALLY_APPROVED"]),
        "pending_material_count": len([m for m in db.materials.values()
                                       if m["project_id"] == pid
                                       and m["status"] in ("SUBMITTED", "CONSERVATOR_REVIEW")]),
        "blocking_punch_count": len([p for p in db.punch_items.values()
                                     if p["project_id"] == pid
                                     and p["severity"] == "BLOCKING" and p["status"] == "OPEN"]),
    }
    return counters


def project_posture(project, exclude_case_id=None, exclude_material_id=None):
    counters = project_counters(project, exclude_case_id=exclude_case_id,
                                exclude_material_id=exclude_material_id)
    return calc.posture_from_counters(
        counters["conservation_block_count"], counters["open_revision_count"],
        counters["conditional_case_count"], counters["pending_material_count"],
    )


def uncommitted_cents(project):
    return (project["contract_value_cents"]
            - project["committed_fabrication_cents"]
            - project["retainage_held_cents"]
            - project["warranty_reserve_cents"]
            - project["released_cents"])


# --- ladder steps 10 and 11 --------------------------------------------
def require_phase(project, allowed):
    if project["phase"] not in allowed:
        raise ApiError("ERR_INVALID_PROJECT_PHASE",
                       "The project is in phase %s." % project["phase"])


def require_not_frozen(project, exclude_case_id=None, exclude_material_id=None):
    posture = project_posture(project, exclude_case_id=exclude_case_id,
                              exclude_material_id=exclude_material_id)
    if posture == "FROZEN_CONSERVATION":
        raise ApiError("ERR_PROJECT_FROZEN_CONSERVATION")


def require_posture_open(project):
    posture = project_posture(project)
    if posture == "FROZEN_CONSERVATION":
        raise ApiError("ERR_PROJECT_FROZEN_CONSERVATION")
    if posture == "RESTRICTED":
        raise ApiError("ERR_PROJECT_POSTURE_RESTRICTED")


def require_unique(table, project_id, field, value, extra=None):
    """Ladder step 8: scoped uniqueness of human-authored codes, compared exactly."""
    for row in table.values():
        if row["project_id"] != project_id:
            continue
        if extra is not None and not extra(row):
            continue
        if row[field] == value:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "%s '%s' already exists in this project." % (field, value))
