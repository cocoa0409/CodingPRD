"""Shared resource plumbing: path resolution (left-to-right, PRD §2.5),
mutation touch (version/updated_at cascade, PRD §2.11), ReassessmentSchedule
journaling, and vendor risk-score refresh (§3.8).
"""
import db
import errors
import util
from errors import ApiError

NON_TERMINAL_CYCLE = {
    "DRAFT", "ISSUED", "RESPONSE_RECEIVED", "SCORED",
    "EVIDENCE_REVIEW", "REMEDIATION", "RISK_ACCEPTANCE_REVIEW",
}
TERMINAL_CYCLE = {"APPROVED", "REJECTED", "EXPIRED"}

# Entities carrying only id + created_at (append-only, PRD §2.4)
NO_VERSION = ("schedules", "contacts")


def stamp_new(store_name, record):
    """Assign system fields on creation. version starts at 1 (PRD §2.4)."""
    record["id"] = util.new_id()
    record["created_at"] = util.iso(util.now())
    record["_seq"] = db.next_seq()
    if store_name not in NO_VERSION:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(store_name, record):
    """Every mutation — direct, cascaded, or swept — bumps version and
    refreshes updated_at (PRD §2.11). Append-only records are never touched."""
    if store_name in NO_VERSION:
        return
    record["version"] += 1
    record["updated_at"] = util.iso(util.now())


# ---------- path resolution (left-to-right, ERR_NOT_FOUND on first miss) ---

def get_vendor(vid):
    v = db.vendors.get(vid)
    if v is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Vendor %s not found" % vid)
    return v


def get_cycle_for_vendor(vendor, cid):
    c = db.cycles.get(cid)
    if c is None or c["vendor_id"] != vendor["id"]:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "AssessmentCycle %s not found" % cid)
    return c


def get_child(store, cid_key, cycle, child_id, label):
    child = store.get(child_id)
    if child is None or child.get(cid_key) != cycle["id"]:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "%s %s not found" % (label, child_id))
    return child


def get_template(tid):
    t = db.templates.get(tid)
    if t is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "QuestionnaireTemplate %s not found" % tid)
    return t


def get_policy(pid):
    p = db.policies.get(pid)
    if p is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "AssessmentTierPolicy %s not found" % pid)
    return p


def get_vendor_child(store, vendor, child_id, label):
    child = store.get(child_id)
    if child is None or child.get("vendor_id") != vendor["id"]:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "%s %s not found" % (label, child_id))
    return child


# ---------- shared domain helpers ------------------------------------------

def active_policy():
    """The single active AssessmentTierPolicy, or None when none is active."""
    for p in db.policies.values():
        if p.get("active"):
            return p
    return None


def non_terminal_cycle(vendor):
    for c in db.cycles.values():
        if c["vendor_id"] == vendor["id"] and c["status"] in NON_TERMINAL_CYCLE:
            return c
    return None


def vendor_cycles(vendor_id):
    return [c for c in db.cycles.values() if c["vendor_id"] == vendor_id]


def cycle_exceptions(cycle_id):
    return [e for e in db.exceptions.values() if e["cycle_id"] == cycle_id]


def cycle_artifacts(cycle_id):
    return [a for a in db.artifacts.values() if a["cycle_id"] == cycle_id]


def cycle_plans(cycle_id):
    return [p for p in db.plans.values() if p["cycle_id"] == cycle_id]


def cycle_acceptances(cycle_id):
    return [r for r in db.acceptances.values() if r["cycle_id"] == cycle_id]


def cycle_addenda(cycle_id):
    return [a for a in db.addenda.values() if a["cycle_id"] == cycle_id]


def append_schedule(vendor_id, kind, previous_due, new_due, reason_ref):
    rec = {
        "vendor_id": vendor_id,
        "kind": kind,
        "previous_due": util.iso(previous_due) if isinstance(previous_due, type(util.now())) else previous_due,
        "new_due": util.iso(new_due) if isinstance(new_due, type(util.now())) else new_due,
        "reason_ref": reason_ref,
    }
    stamp_new("schedules", rec)
    db.schedules[rec["id"]] = rec
    return rec


def refresh_risk(vendor):
    """vendor_risk_score (PRD §3.8): posture base + alert/acceptance/expiry
    modifiers, clamped to [0, 100], round-half-up 2dp."""
    from calc import vendor_risk_score
    vendor["risk_score"] = util.num(vendor_risk_score(vendor, util.now()))


def reassign_tier(vendor):
    """tier_assignment against the currently active policy (PRD §3.1)."""
    from calc import tier_assignment
    vendor["current_tier"] = tier_assignment(
        vendor["data_sensitivity"], vendor["access_level"], vendor["criticality"],
        active_policy(),
    )
