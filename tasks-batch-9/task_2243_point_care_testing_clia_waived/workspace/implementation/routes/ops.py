"""Programme operations: the oversight run and the logical clock (PRD 3.9, 2.9)."""

from flask import Blueprint

import clock
import db
import response
import valid
from middleware import route
from services import derive

bp = Blueprint("ops", __name__)

POSTURE_PENALTY = {"OPEN": 0, "RESTRICTED": 7, "SUSPENDED": 14}


@route(bp, "/oversight-runs", ["POST"], ["ProgramAdmin"])
def oversight_run(user_id, role):
    payload = valid.body()
    valid.opt_str(payload, "note")

    today = clock.today()
    stamp = clock.now_iso()

    stats = {
        "certificates_expired": 0,
        "lots_expired": 0,
        "competencies_lapsed": 0,
        "operators_locked_out": 0,
        "devices_qc_locked": 0,
        "scope_creep_sites": 0,
        "sites_posture_changed": 0,
    }

    # ---- PHASE 0 -- freeze the posture of every site before anything moves.
    posture_before = {site["id"]: site["oversight_posture"]
                      for site in db.rows("sites")}

    # ---- 1. certificate expiry (+ CASCADE-B) -----------------------------
    for certificate in db.rows("certificates"):
        if certificate["status"] != "ACTIVE":
            continue
        expiration = clock.parse_date(certificate["expiration_date"])
        if expiration is None or expiration >= today:
            continue
        snap = db.snapshot(certificate)
        certificate["status"] = "EXPIRED"
        db.touch_if_changed(certificate, snap)
        stats["certificates_expired"] += 1
        derive.cascade_certificate_withdrawal(
            certificate, "SITE_SUSPENDED", stats)

    # ---- 2. reagent-lot expiry -------------------------------------------
    for lot in db.rows("lots"):
        if lot["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
            continue
        expiration = clock.parse_date(lot["expiration_date"])
        if expiration is None or expiration >= today:
            continue
        snap = db.snapshot(lot)
        lot["verification_status"] = "EXPIRED"
        db.touch_if_changed(lot, snap)
        stats["lots_expired"] += 1
        for result in db.rows("results"):
            if result["reagent_lot_id"] != lot["id"]:
                continue
            if result["posting_status"] != "PENDING_REVIEW":
                continue
            rsnap = db.snapshot(result)
            result["posting_status"] = "REJECTED"
            db.touch_if_changed(result, rsnap)

    # ---- 3. competency grace and lock-out --------------------------------
    operators = [o for o in db.data["operators"].values()
                 if o["access_status"] != "DEACTIVATED"]
    operators.sort(key=lambda o: (o["created_at"], o["hire_date"] or "",
                                  o["full_name"], o["_seq"]))

    # PHASE 1 -- grace, evaluated against the frozen snapshot only.
    for operator in operators:
        snap = db.snapshot(operator)
        base = 30 if operator["role_title"] == "PHYSICIAN" else 14
        penalty = POSTURE_PENALTY.get(
            posture_before.get(operator["site_id"], "OPEN"), 0)
        grace = max(0, base - penalty)
        operator["current_grace_days"] = grace
        expires = clock.parse_date(operator["competency_expires_at"])
        if expires is None:
            operator["lapse_deadline"] = None
        else:
            operator["lapse_deadline"] = clock.add_days(expires, grace).isoformat()
        db.touch_if_changed(operator, snap)

    # PHASE 2 -- apply the lock-out.
    for operator in operators:
        if operator["competency_status"] != "COMPETENT":
            continue
        deadline = clock.parse_date(operator["lapse_deadline"])
        if deadline is None or today <= deadline:
            continue
        snap = db.snapshot(operator)
        operator["competency_status"] = "LAPSED"
        operator["access_status"] = "LOCKED_OUT"
        operator["lockout_reason"] = "COMPETENCY_LAPSED"
        db.touch_if_changed(operator, snap)
        stats["competencies_lapsed"] += 1
        stats["operators_locked_out"] += 1

    # ---- 4. quality-control overdue --------------------------------------
    # Results are deliberately NOT held on this branch.
    for site in db.rows("sites"):
        for device in derive.devices_of(site["id"]):
            if device["status"] != "ACTIVE":
                continue
            due = clock.parse_date(device["qc_next_due_at"])
            if due is None or today <= due:
                continue
            snap = db.snapshot(device)
            device["status"] = "QC_LOCKED"
            device["qc_lock_reason"] = "QC_OVERDUE"
            db.touch_if_changed(device, snap)
            stats["devices_qc_locked"] += 1

    # ---- 5. scope creep ---------------------------------------------------
    for site in db.rows("sites"):
        coverage = derive.in_window_coverage(site["id"])
        creep = False
        if coverage is not None \
                and coverage["permitted_complexity_snapshot"] == "WAIVED":
            for device in derive.devices_of(site["id"]):
                if device["status"] != "ACTIVE":
                    continue
                if device["complexity_class"] != "MODERATE":
                    continue
                snap = db.snapshot(device)
                device["status"] = "QC_LOCKED"
                device["qc_lock_reason"] = "CERTIFICATE_SCOPE"
                db.touch_if_changed(device, snap)
                stats["devices_qc_locked"] += 1
                creep = True
        if creep:
            stats["scope_creep_sites"] += 1
        snap = db.snapshot(site)
        if creep:
            site["scope_creep_flag"] = True
        db.touch_if_changed(site, snap)

    # ---- 6. recompute every site -----------------------------------------
    for site in db.rows("sites"):
        derive.recompute_site(site, refresh_device_rates=True)
        snap = db.snapshot(site)
        site["last_oversight_run_at"] = stamp
        db.touch_if_changed(site, snap)
        if site["oversight_posture"] != posture_before.get(site["id"]):
            stats["sites_posture_changed"] += 1

    body = {"evaluated_at": stamp}
    body.update(stats)
    return response.object_response(body)


@route(bp, "/_clock/set_current_utc", ["POST"], ["ProgramAdmin"])
def set_clock(user_id, role):
    payload = valid.body()
    moment = valid.req_datetime(payload, "to_iso8601")
    clock.set_now(moment)
    return response.object_response({"current_utc": clock.now_iso()})
