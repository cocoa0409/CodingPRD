"""Cross-cutting business services: jurisdiction scope, cluster evaluation,
contact void cascade."""
from db import db
from errors import err
from helpers import touch, parse_dt, to_iso, day_diff
from calculations import find_condition, compute_completeness, compute_isolation_end


# ---------------------------------------------------------------------------
# Jurisdiction scope check (validation priority 5)
# ---------------------------------------------------------------------------
def check_case_scope(user_id, role, case):
    """Scoped roles may only act on cases in their own jurisdiction."""
    if role in ("IntakeProcessor", "CaseInvestigator", "ContactTracer"):
        if case["jurisdiction_id"] != user_id:
            raise err("ERR_JURISDICTION_SCOPE_VIOLATION",
                      "Scoped role acting outside its jurisdiction")


def check_contact_scope(user_id, role, contact):
    if role in ("IntakeProcessor", "CaseInvestigator", "ContactTracer"):
        if contact["monitoring_jurisdiction_id"] != user_id:
            raise err("ERR_JURISDICTION_SCOPE_VIOLATION",
                      "Scoped role acting outside its jurisdiction")


# ---------------------------------------------------------------------------
# Active monitoring count helpers (conserved counter, invariant 9b)
# ---------------------------------------------------------------------------
def inc_active_monitoring(jurisdiction_id):
    j = db.jurisdictions.get(jurisdiction_id)
    if j is not None:
        j["active_monitoring_count"] = j.get("active_monitoring_count", 0) + 1
        touch(j)


def dec_active_monitoring(jurisdiction_id):
    j = db.jurisdictions.get(jurisdiction_id)
    if j is not None:
        j["active_monitoring_count"] = max(0, j.get("active_monitoring_count", 0) - 1)
        touch(j)


def active_monitoring_period_for(contact_id):
    for m in db.monitoring_periods.values():
        if m["contact_id"] == contact_id and m["status"] == "ACTIVE":
            return m
    return None


# ---------------------------------------------------------------------------
# Outbreak cluster membership (calc: outbreak_cluster_membership)
# ---------------------------------------------------------------------------
def evaluate_cluster(case):
    """Run on confirm of a case that carries exposure_setting_location_id."""
    location = case.get("exposure_setting_location_id")
    if not location:
        return
    program_id = case["program_id"]
    condition_code = case["condition_code"]
    cond = find_condition(program_id, condition_code)
    if cond is None:
        return
    window = cond["cluster_window_days"]
    min_cases = cond["cluster_min_cases"]

    this_onset = parse_dt(case.get("symptom_onset_date"))

    # candidate peers: other CONFIRMED cases sharing K within window
    peers = []
    for c in db.cases.values():
        if c["id"] == case["id"]:
            continue
        if c["program_id"] != program_id:
            continue
        if c["classification"] != "CONFIRMED":
            continue
        if c["condition_code"] != condition_code:
            continue
        if c.get("exposure_setting_location_id") != location:
            continue
        c_onset = parse_dt(c.get("symptom_onset_date"))
        if this_onset is None or c_onset is None:
            continue
        if day_diff(this_onset, c_onset) <= window:
            peers.append(c)

    def sort_key(c):
        return (c.get("symptom_onset_date") or "", c["created_at"], c.get("_seq", 0))

    peers.sort(key=sort_key)
    group = peers + [case]

    # existing ACTIVE cluster sharing K whose anchor case is within window of this case
    existing = None
    for cl in db.clusters.values():
        if cl["program_id"] != program_id:
            continue
        if cl["status"] != "ACTIVE":
            continue
        if cl["condition_code"] != condition_code:
            continue
        if cl["exposure_setting_location_id"] != location:
            continue
        anchor = db.cases.get(cl["anchor_case_id"])
        if anchor is None:
            continue
        anchor_onset = parse_dt(anchor.get("symptom_onset_date"))
        if this_onset is None or anchor_onset is None:
            continue
        if day_diff(this_onset, anchor_onset) <= window:
            existing = cl
            break

    if existing is not None:
        case["cluster_id"] = existing["id"]
        existing["member_case_count"] = existing.get("member_case_count", 0) + 1
        _recompute_cluster_onsets(existing)
        touch(existing)
        return

    if len(group) >= min_cases:
        from helpers import base_entity
        cl = base_entity(common_fields=True)
        # anchor = earliest symptom_onset_date, tie-break created_at ASC
        anchor_case = min(
            group,
            key=lambda c: (c.get("symptom_onset_date") or "", c["created_at"], c.get("_seq", 0)),
        )
        cl.update({
            "program_id": program_id,
            "condition_code": condition_code,
            "exposure_setting_location_id": location,
            "anchor_case_id": anchor_case["id"],
            "member_case_count": len(group),
            "earliest_onset_date": None,
            "latest_onset_date": None,
            "status": "ACTIVE",
        })
        db.clusters[cl["id"]] = cl
        for member in group:
            member["cluster_id"] = cl["id"]
            if member["id"] != case["id"]:
                touch(member)
        _recompute_cluster_onsets(cl)
        return
    # else: no cluster change


def _recompute_cluster_onsets(cluster):
    onsets = []
    for c in db.cases.values():
        if c.get("cluster_id") == cluster["id"]:
            o = c.get("symptom_onset_date")
            if o:
                onsets.append(o)
    if onsets:
        cluster["earliest_onset_date"] = min(onsets)
        cluster["latest_onset_date"] = max(onsets)
    # member_case_count is maintained by paired actions (conserved); leave as-is


# ---------------------------------------------------------------------------
# Contact void (used by manual void and NOT_A_CASE cascade)
# ---------------------------------------------------------------------------
def void_contact(contact):
    """Void a single contact, applying compensating counter actions.

    Caller is responsible for state-legality checks for manual void.
    """
    was_active = contact["status"] == "MONITORING_ACTIVE"
    contact["status"] = "VOIDED"
    if was_active:
        mp = active_monitoring_period_for(contact["id"])
        if mp is not None:
            mp["status"] = "RELEASED_EARLY"
            touch(mp)
        dec_active_monitoring(contact["monitoring_jurisdiction_id"])
    touch(contact)
    # decrement source case contact_count + recompute completeness
    src = db.cases.get(contact["source_case_id"])
    if src is not None:
        src["contact_count"] = max(0, src.get("contact_count", 0) - 1)
        src["completeness_score"] = compute_completeness(src)
        touch(src)
