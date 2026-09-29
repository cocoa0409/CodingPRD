"""Derived state: counters, posture, compliance rates and the named cascades.

PRD 2.10, 2.11, 2.12, 3.x.
"""

from decimal import Decimal

import clock
import db
from services import calc


# --------------------------------------------------------------------------
# Deterministic walk orders (PRD 2.12)
# --------------------------------------------------------------------------

def operators_of(site_id):
    ops = [o for o in db.data["operators"].values() if o["site_id"] == site_id]
    ops.sort(key=lambda o: (o["created_at"], o["full_name"], o["_seq"]))
    return ops


def devices_of(site_id):
    devices = [d for d in db.data["devices"].values() if d["site_id"] == site_id]
    devices.sort(key=lambda d: (d["created_at"], d["serial_number"], d["_seq"]))
    return devices


def results_of_device(device_id):
    results = [r for r in db.data["results"].values() if r["device_id"] == device_id]
    results.sort(key=lambda r: (r["created_at"], r["patient_mrn"], r["_seq"]))
    return results


def findings_of(site_id):
    findings = [f for f in db.data["findings"].values() if f["site_id"] == site_id]
    findings.sort(key=lambda f: (f["created_at"], f["category"], f["_seq"]))
    return findings


def site_of_device(device):
    return db.get("sites", device["site_id"])


# --------------------------------------------------------------------------
# Certificate coverage
# --------------------------------------------------------------------------

def in_window_coverage(site_id, statuses=("ACTIVE",)):
    """The coverage whose closed window contains today, whose certificate status
    is one of `statuses`.  At most one can exist per the overlap rule."""
    today = clock.today_str()
    for coverage in db.rows("coverages"):
        if coverage["site_id"] != site_id:
            continue
        if not (coverage["coverage_start"] <= today <= coverage["coverage_end"]):
            continue
        certificate = db.get("certificates", coverage["certificate_id"])
        if certificate is not None and certificate["status"] in statuses:
            return coverage
    return None


def has_active_coverage(site_id):
    return in_window_coverage(site_id) is not None


# --------------------------------------------------------------------------
# Device derived fields
# --------------------------------------------------------------------------

def recompute_device_schedule(device):
    """last_two_level_qc_pass_on / qc_next_due_at — derived from QcRun rows only."""
    snap = db.snapshot(device)
    day = calc.two_level_pass_day(device)
    if day is None:
        device["last_two_level_qc_pass_on"] = None
        created = clock.parse_date(device["created_at"][:10])
        device["qc_next_due_at"] = created.isoformat() if created else None
    else:
        device["last_two_level_qc_pass_on"] = day.isoformat()
        device["qc_next_due_at"] = clock.add_days(
            day, int(device["qc_frequency_days"])
        ).isoformat()
    db.touch_if_changed(device, snap)


def recompute_device_rates(device):
    """Both compliance-rate variants + use_day_count against the logical clock."""
    snap = db.snapshot(device)
    calendar, day_of_use, use_days = calc.compliance_rates(device)
    device["qc_compliance_rate_calendar"] = float(calendar)
    device["qc_compliance_rate_day_of_use"] = float(day_of_use)
    device["use_day_count"] = use_days
    day = calc.two_level_pass_day(device)
    if day is None:
        device["last_two_level_qc_pass_on"] = None
        created = clock.parse_date(device["created_at"][:10])
        device["qc_next_due_at"] = created.isoformat() if created else None
    else:
        device["last_two_level_qc_pass_on"] = day.isoformat()
        device["qc_next_due_at"] = clock.add_days(
            day, int(device["qc_frequency_days"])
        ).isoformat()
    db.touch_if_changed(device, snap)


# --------------------------------------------------------------------------
# Site counters, posture, index, readiness
# --------------------------------------------------------------------------

def recompute_counters(site):
    site_id = site["id"]
    site["open_deficiency_weight"] = float(calc.open_deficiency_weight(site_id))

    device_ids = {d["id"] for d in db.data["devices"].values()
                  if d["site_id"] == site_id}
    site["held_result_count"] = sum(
        1 for r in db.data["results"].values()
        if r["device_id"] in device_ids and r["posting_status"] == "HELD"
    )

    ops = [o for o in db.data["operators"].values() if o["site_id"] == site_id]
    # A deactivated operator leaves the roster denominator (PRD 2.11).
    site["total_operator_count"] = sum(
        1 for o in ops if o["access_status"] != "DEACTIVATED")
    site["locked_out_operator_count"] = sum(
        1 for o in ops if o["access_status"] == "LOCKED_OUT")
    site["lapsed_or_locked_operator_count"] = sum(
        1 for o in ops
        if o["competency_status"] == "LAPSED" or o["access_status"] == "LOCKED_OUT")

    site["pt_unsuccessful_count"] = calc.pt_unsuccessful_count(site_id)


def derive_posture(site):
    weight = calc.dec(site["open_deficiency_weight"])
    held = int(site["held_result_count"] or 0)
    locked = int(site["locked_out_operator_count"] or 0)
    total = int(site["total_operator_count"] or 0)

    if (not has_active_coverage(site["id"])) or weight >= Decimal("16.0"):
        posture = "SUSPENDED"
    elif weight >= Decimal("6.0") or held >= 3 or (locked * 2) > total:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    site["oversight_posture"] = posture
    site["manual_entry_blocked"] = posture != "OPEN"
    propagate_manual_entry(site)


def propagate_manual_entry(site):
    for device in devices_of(site["id"]):
        if device["connectivity_mode"] != "MANUAL_ENTRY":
            continue
        snap = db.snapshot(device)
        device["manual_entry_suspended"] = bool(site["manual_entry_blocked"])
        db.touch_if_changed(device, snap)


def recompute_scope_creep(site):
    coverage = in_window_coverage(site["id"])
    flag = False
    if coverage is not None and coverage["permitted_complexity_snapshot"] == "WAIVED":
        flag = any(d["complexity_class"] == "MODERATE" and d["status"] != "RETIRED"
                   for d in devices_of(site["id"]))
    snap = db.snapshot(site)
    site["scope_creep_flag"] = flag
    db.touch_if_changed(site, snap)
    return flag


def recompute_site(site, refresh_device_rates=False):
    if site is None:
        return
    if refresh_device_rates:
        for device in devices_of(site["id"]):
            recompute_device_rates(device)
    snap = db.snapshot(site)
    recompute_counters(site)
    derive_posture(site)
    site["site_qc_compliance_index"] = float(calc.site_qc_compliance_index(site))
    site["inspection_readiness_score"] = calc.readiness(site, "AS_OF_ACTUAL")["score"]
    db.touch_if_changed(site, snap)


def recompute_site_by_id(site_id, refresh_device_rates=False):
    recompute_site(db.get("sites", site_id), refresh_device_rates)


def recompute_all_sites(refresh_device_rates=False):
    for site in db.rows("sites"):
        recompute_site(site, refresh_device_rates)


# --------------------------------------------------------------------------
# Operator derived fields
# --------------------------------------------------------------------------

def recompute_covered_site_count(certificate):
    snap = db.snapshot(certificate)
    certificate["covered_site_count"] = sum(
        1 for c in db.data["coverages"].values()
        if c["certificate_id"] == certificate["id"])
    db.touch_if_changed(certificate, snap)


def recompute_competency_expiry(operator):
    best = None
    for assessment in db.rows("assessments"):
        if assessment["operator_id"] != operator["id"]:
            continue
        if assessment["status"] != "APPROVED":
            continue
        if best is None or assessment["expires_at"] > best:
            best = assessment["expires_at"]
    operator["competency_expires_at"] = best


# --------------------------------------------------------------------------
# CASCADE-A — QC failure
# --------------------------------------------------------------------------

def cascade_qc_failure(device, run):
    """Link 2-4: lock the device, hold its pending results, re-derive the site."""
    snap = db.snapshot(device)
    device["status"] = "QC_LOCKED"
    device["qc_lock_reason"] = "QC_FAILURE"
    db.touch_if_changed(device, snap)

    stamp = clock.now_iso()
    for result in results_of_device(device["id"]):
        if result["posting_status"] != "PENDING_REVIEW":
            continue
        rsnap = db.snapshot(result)
        result["posting_status"] = "HELD"
        result["held_by_device_lock_at"] = stamp
        db.touch_if_changed(result, rsnap)

    recompute_site(site_of_device(device))


# --------------------------------------------------------------------------
# CASCADE-B — certificate withdrawal
# --------------------------------------------------------------------------

def cascade_certificate_withdrawal(certificate, lockout_reason="SITE_SUSPENDED",
                                   stats=None):
    today = clock.today_str()
    site_ids = []
    for coverage in db.rows("coverages"):
        if coverage["certificate_id"] != certificate["id"]:
            continue
        if not (coverage["coverage_start"] <= today <= coverage["coverage_end"]):
            continue
        if coverage["site_id"] not in site_ids:
            site_ids.append(coverage["site_id"])

    for site_id in site_ids:
        site = db.get("sites", site_id)
        if site is None:
            continue

        # Link 2 — every ACTIVE operator is locked out.
        locked_ids = []
        for operator in operators_of(site_id):
            if operator["access_status"] != "ACTIVE":
                continue
            snap = db.snapshot(operator)
            operator["access_status"] = "LOCKED_OUT"
            operator["lockout_reason"] = lockout_reason
            db.touch_if_changed(operator, snap)
            locked_ids.append(operator["id"])
            if stats is not None:
                stats["operators_locked_out"] += 1

        # Link 3 — their SUBMITTED assessments are voided.
        if locked_ids:
            for assessment in db.rows("assessments"):
                if assessment["status"] != "SUBMITTED":
                    continue
                if assessment["operator_id"] not in locked_ids:
                    continue
                snap = db.snapshot(assessment)
                assessment["status"] = "VOIDED"
                assessment["decision_note"] = "voided by site suspension"
                db.touch_if_changed(assessment, snap)

        # Link 4 — every ACTIVE device is QC-locked on certificate scope.
        for device in devices_of(site_id):
            if device["status"] != "ACTIVE":
                continue
            snap = db.snapshot(device)
            device["status"] = "QC_LOCKED"
            device["qc_lock_reason"] = "CERTIFICATE_SCOPE"
            if device["connectivity_mode"] == "MANUAL_ENTRY":
                device["manual_entry_suspended"] = True
            db.touch_if_changed(device, snap)
            if stats is not None:
                stats["devices_qc_locked"] += 1

        recompute_site(site)


# --------------------------------------------------------------------------
# CASCADE-C — temperature excursion
# --------------------------------------------------------------------------

def cascade_temperature_excursion(unit):
    """Link 2-4: quarantine lots, lock devices, reject pending results."""
    quarantined = []
    for lot in db.rows("lots"):
        if lot["storage_unit_id"] != unit["id"]:
            continue
        if lot["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
            continue
        snap = db.snapshot(lot)
        lot["verification_status"] = "QUARANTINED"
        lot["quarantine_reason"] = "TEMPERATURE_EXCURSION"
        db.touch_if_changed(lot, snap)
        quarantined.append(lot)

    usnap = db.snapshot(unit)
    unit["quarantined_lot_count"] = sum(
        1 for lot in db.data["lots"].values()
        if lot["storage_unit_id"] == unit["id"]
        and lot["verification_status"] == "QUARANTINED")
    db.touch_if_changed(unit, usnap)

    quarantined_ids = {lot["id"] for lot in quarantined}
    models = {(lot["site_id"], lot["device_model"]) for lot in quarantined}

    locked_devices = []
    for site_id, model in sorted(models):
        for device in devices_of(site_id):
            if device["device_model"] != model or device["status"] != "ACTIVE":
                continue
            snap = db.snapshot(device)
            device["status"] = "QC_LOCKED"
            device["qc_lock_reason"] = "LOT_QUARANTINE"
            db.touch_if_changed(device, snap)
            locked_devices.append(device)

    for device in locked_devices:
        for result in results_of_device(device["id"]):
            if result["posting_status"] != "PENDING_REVIEW":
                continue
            if result["reagent_lot_id"] not in quarantined_ids:
                continue
            snap = db.snapshot(result)
            result["posting_status"] = "REJECTED"
            db.touch_if_changed(result, snap)

    affected = {device["site_id"] for device in locked_devices}
    affected.add(unit["site_id"])
    for site_id in sorted(affected):
        recompute_site_by_id(site_id)
