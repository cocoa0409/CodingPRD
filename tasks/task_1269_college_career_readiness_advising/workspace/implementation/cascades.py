"""Cascade side effects (SCAFFOLD §1.2): CERTIFIED-audit AUTO_DRIFT flagging,
student terminal cascades, placement termination, site capacity reduction."""

from store import stores, now, bump, touch


def autoflag_certified_audits(student_id):
    """CERTIFIED audits of the student drop to FLAGGED with flag_reason
    AUTO_DRIFT, certified_at cleared, version += 1 (PRD §3.7)."""
    for audit in stores["audits"].values():
        if audit["student_id"] == student_id and audit["status"] == "CERTIFIED":
            audit["status"] = "FLAGGED"
            audit["flag_reason"] = "AUTO_DRIFT"
            audit["certified_at"] = None
            audit["frozen"] = None
            bump(audit)


def waive_open_milestones(application):
    """Milestones in {PENDING, READY} -> WAIVED (application withdrawal)."""
    for m in stores["milestones"].values():
        if m["application_id"] == application["id"] and m["status"] in ("PENDING", "READY"):
            m["status"] = "WAIVED"
            bump(m)


def withdraw_application(app):
    """Application -> WITHDRAWN with per-from-state side effects."""
    prior = app["submission_status"]
    app["submission_status"] = "WITHDRAWN"
    bump(app)
    if prior in ("DRAFT", "READY"):
        waive_open_milestones(app)
    # SUBMITTED -> WITHDRAWN leaves decision_status and milestones untouched.


def terminate_placement(p, reason):
    p["status"] = "TERMINATED"
    p["terminated_reason"] = reason
    bump(p)


def student_terminal_cascade(student, target_status):
    """Closing cascade for GRADUATED / WITHDRAWN / TRANSFERRED_OUT (PRD §3.7)."""
    sid = student["id"]
    for app in list(stores["applications"].values()):
        if app["student_id"] == sid and app["submission_status"] in ("DRAFT", "READY", "SUBMITTED"):
            withdraw_application(app)
    for rec in list(stores["rec_requests"].values()):
        if rec["student_id"] == sid and rec["status"] in ("REQUESTED", "ACCEPTED"):
            rec["status"] = "WITHDRAWN"
            bump(rec)
    for cert in list(stores["certifications"].values()):
        if cert["student_id"] == sid and cert["status"] in ("REGISTERED", "EXAM_SCHEDULED"):
            cert["status"] = "CANCELLED"
            bump(cert)
    if target_status in ("WITHDRAWN", "TRANSFERRED_OUT"):
        for p in list(stores["placements"].values()):
            if p["student_id"] != sid:
                continue
            if p["status"] == "OFFERED":
                p["status"] = "DECLINED"
                bump(p)
            elif p["status"] in ("CONFIRMED", "ACTIVE"):
                terminate_placement(p, "STUDENT_WITHDRAWN")


def site_capacity_reduction(site, new_max):
    """Force-terminate the excess CONFIRMED/ACTIVE placements when the new
    ceiling falls below the current interval-overlap maximum. Survivors ranked
    created_at ASC (insertion seq tie-break), keep first new_max (PRD §3.6)."""
    from computed import site_overlap_max
    current_max = site_overlap_max(site["id"])
    if new_max >= current_max:
        return
    live = [p for p in stores["placements"].values()
            if p["site_id"] == site["id"] and p["status"] in ("CONFIRMED", "ACTIVE")]
    live.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for p in live[new_max:]:
        terminate_placement(p, "SITE_CAPACITY_REDUCTION")
