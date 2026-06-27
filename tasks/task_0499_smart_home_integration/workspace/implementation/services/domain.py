"""Cross-entity domain logic: derived-counter reconciliation, cascades,
bubble-ups, and shared scope helpers (PRD §2.6, §3.x).

Every reconciliation that changes a resource is a mutation that refreshes
updated_at and bumps version (PRD §2.6).
"""
import db
from services import calc

LIVE_DEVICE_STATES = {"REGISTERED", "PROVISIONED", "ONLINE", "FAULTED"}


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------
def rack_for_project(project_id):
    for r in db.racks.values():
        if r["project_id"] == project_id:
            return r
    return None


def devices_for_project(project_id):
    rack = rack_for_project(project_id)
    if rack is None:
        return []
    return [d for d in db.devices.values() if d["rack_id"] == rack["id"]]


def devices_for_rack(rack_id):
    return [d for d in db.devices.values() if d["rack_id"] == rack_id]


def project_of_device(device):
    rack = db.racks.get(device["rack_id"])
    if rack is None:
        return None
    return db.projects.get(rack["project_id"])


def active_contract_for_project(project_id):
    """The project's ACTIVE or SUSPENDED contract, if any."""
    for c in db.contracts.values():
        if c["project_id"] == project_id and c["status"] in ("ACTIVE", "SUSPENDED"):
            return c
    return None


def contract_of_rma(rma):
    return db.contracts.get(rma["contract_id"])


# ---------------------------------------------------------------------------
# Rack units (scaffold §1.3 rack_units_used)
# ---------------------------------------------------------------------------
def recompute_rack_units(rack):
    used = 0
    for d in devices_for_rack(rack["id"]):
        if d["status"] in LIVE_DEVICE_STATES:
            used += d["rack_units"]
    if rack["rack_units_used"] != used:
        rack["rack_units_used"] = used
        db.touch(rack)
    else:
        rack["rack_units_used"] = used


# ---------------------------------------------------------------------------
# Project derived counters (PRD §2.6)
# ---------------------------------------------------------------------------
def recompute_project_counters(project):
    """Recompute provisioned_device_count, open_change_order_count,
    contract_balance_cents. Bump project version/updated_at iff any changed."""
    changed = False

    # provisioned_device_count: devices on rack in PROVISIONED or ONLINE
    pdc = 0
    for d in devices_for_project(project["id"]):
        if d["status"] in ("PROVISIONED", "ONLINE"):
            pdc += 1
    if project["provisioned_device_count"] != pdc:
        project["provisioned_device_count"] = pdc
        changed = True

    # open_change_order_count: change orders in SUBMITTED or APPROVED
    occ = 0
    for co in db.change_orders.values():
        if co["project_id"] == project["id"] and co["status"] in ("SUBMITTED", "APPROVED"):
            occ += 1
    if project["open_change_order_count"] != occ:
        project["open_change_order_count"] = occ
        changed = True

    # contract_balance_cents: mirror ACTIVE/SUSPENDED contract balance, else 0
    contract = active_contract_for_project(project["id"])
    cbc = contract["balance_cents"] if contract else 0
    if project["contract_balance_cents"] != cbc:
        project["contract_balance_cents"] = cbc
        changed = True

    if changed:
        db.touch(project)


# ---------------------------------------------------------------------------
# Visit assigned_crew_count
# ---------------------------------------------------------------------------
def recompute_visit_crew_count(visit):
    count = 0
    for a in db.assignments.values():
        if a["visit_id"] == visit["id"] and a["status"] == "ACTIVE":
            count += 1
    if visit["assigned_crew_count"] != count:
        visit["assigned_crew_count"] = count
        db.touch(visit)


def release_visit_assignments(visit):
    """Set all ACTIVE assignments on the visit to RELEASED, then recompute."""
    for a in db.assignments.values():
        if a["visit_id"] == visit["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            db.touch(a)
    recompute_visit_crew_count(visit)


# ---------------------------------------------------------------------------
# Scene de-deploy cascade when a member device goes FAULTED / RETIRED
# ---------------------------------------------------------------------------
def dedeploy_scenes_for_device(device):
    project = project_of_device(device)
    if project is None:
        return
    for s in db.scenes.values():
        if s["project_id"] == project["id"] and s["status"] == "DEPLOYED" \
                and device["id"] in s["device_ids"]:
            s["status"] = "VALIDATED"
            db.touch(s)


# ---------------------------------------------------------------------------
# Device retirement (releases mgmt_ip / rack_units; recomputes counters)
# ---------------------------------------------------------------------------
def retire_device(device):
    was_online = device["status"] == "ONLINE"
    had_ip = device.get("mgmt_ip") is not None
    device["status"] = "RETIRED"
    if had_ip:
        device["mgmt_ip"] = None
    db.touch(device)
    if was_online:
        dedeploy_scenes_for_device(device)
    rack = db.racks.get(device["rack_id"])
    if rack is not None:
        recompute_rack_units(rack)
    project = project_of_device(device)
    if project is not None:
        recompute_project_counters(project)


# ---------------------------------------------------------------------------
# Project commission attempt (bubble-up INSTALLING -> COMMISSIONED)
# Returns (ok, error_id_if_explicit). When called as a bubble-up after a
# COMMISSION visit completes, failure is silent (project stays INSTALLING).
# ---------------------------------------------------------------------------
def can_commission(project):
    """Returns None if commissionable, else the blocking error_id."""
    non_retired = [d for d in devices_for_project(project["id"]) if d["status"] != "RETIRED"]
    for d in non_retired:
        if d["status"] != "ONLINE":
            return "ERR_DEVICES_NOT_ONLINE"
    deployed = [
        s for s in db.scenes.values()
        if s["project_id"] == project["id"] and s["status"] == "DEPLOYED"
    ]
    if not deployed:
        return "ERR_NO_DEPLOYED_SCENE"
    return None


def try_commission(project):
    """Attempt INSTALLING -> COMMISSIONED. Silent no-op if guard not satisfied."""
    if project["status"] != "INSTALLING":
        return
    if can_commission(project) is None:
        project["status"] = "COMMISSIONED"
        db.touch(project)
