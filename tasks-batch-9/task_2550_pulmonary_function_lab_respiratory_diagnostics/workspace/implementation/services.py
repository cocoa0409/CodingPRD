"""Shared domain services: lookups, gates, selectors, recomputes, cascades."""
from datetime import timedelta

import calc
from calc import D, num, rnd, rnd_int, trunc_int
from errors import ApiError
from store import (db, iso, iso_date, parse_date, parse_iso, day_start,
                   public, touch, by_created)


# ------------------------------------------------------------------- lookups

def _find(bucket, key, error_id):
    if key is None or not isinstance(key, str):
        raise ApiError(error_id)
    record = bucket.get(key)
    if record is None:
        raise ApiError(error_id)
    return record


def get_device(device_id):
    return _find(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")


def get_staff(staff_id):
    return _find(db.staff, staff_id, "ERR_STAFF_NOT_FOUND")


def get_patient(patient_id):
    return _find(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")


def get_order(order_id):
    return _find(db.orders, order_id, "ERR_ORDER_NOT_FOUND")


def get_hold(hold_id):
    return _find(db.holds, hold_id, "ERR_HOLD_NOT_FOUND")


def get_session(session_id):
    return _find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")


def get_run(run_id):
    return _find(db.runs, run_id, "ERR_RUN_NOT_FOUND")


def get_report(report_id):
    return _find(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def get_quality_event(event_id):
    return _find(db.quality_events, event_id, "ERR_QUALITY_EVENT_NOT_FOUND")


def get_lot(lot_id):
    return _find(db.lots, lot_id, "ERR_LOT_NOT_FOUND")


def get_maneuver(maneuver_id):
    return _find(db.maneuvers, maneuver_id, "ERR_MANEUVER_NOT_FOUND")


def get_custody_event(event_id):
    return _find(db.custody_events, event_id, "ERR_CUSTODY_EVENT_NOT_FOUND")


# --------------------------------------------------------------- serialisers

def ser_device(rec):
    return public(rec)


def ser_quality_event(rec):
    return public(rec)


def ser_staff(rec):
    return public(rec)


def age_years_of(patient):
    birth = parse_date(patient["birth_date"])
    today = db.clock.date()
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def ser_patient(rec):
    return public(rec, {"age_years": age_years_of(rec)})


def ser_equation(rec):
    return public(rec)


def ser_lot(rec):
    return public(rec)


def ser_order(rec):
    return public(rec)


def ser_hold(rec):
    return public(rec)


def ser_session(rec):
    return public(rec)


def ser_maneuver(rec):
    return public(rec)


def ser_run(rec):
    return public(rec)


def ser_report(rec):
    return public(rec)


def ser_custody_event(rec):
    return public(rec)


# ------------------------------------------------------- device quality gates

def device_events(device_id, event_type=None, outcomes=None):
    result = []
    for event in db.quality_events.values():
        if event["device_id"] != device_id:
            continue
        if event_type is not None and event["event_type"] != event_type:
            continue
        if outcomes is not None and event["outcome"] not in outcomes:
            continue
        result.append(event)
    return result


def _performed(event):
    return parse_iso(event["performed_at"])


def has_same_day_pass_calibration(device):
    start = day_start(db.clock)
    for event in device_events(device["id"], "VOLUME_CALIBRATION", ("PASS",)):
        if _performed(event) >= start:
            return True
    return False


def has_same_day_leak_check(device):
    start = day_start(db.clock)
    for event in device_events(device["id"], "LEAK_CHECK", ("COMPLETE",)):
        if _performed(event) >= start:
            return True
    return False


def infection_control_satisfied(device, boundary_iso=None):
    """A COMPLETE filter replacement and a COMPLETE high-level disinfection,
    both strictly after the boundary (or at any time when it is null)."""
    if boundary_iso is None:
        boundary_iso = device.get("last_session_end_at")
    boundary = parse_iso(boundary_iso) if boundary_iso else None

    def satisfied(event_type):
        for event in device_events(device["id"], event_type, ("COMPLETE",)):
            if boundary is None or _performed(event) > boundary:
                return True
        return False

    return satisfied("FILTER_REPLACEMENT") and satisfied("HIGH_LEVEL_DISINFECT")


def maybe_return_soiled_device(device):
    """SOILED devices clear themselves once the infection-control pair is
    complete relative to the last session end."""
    if device.get("status") != "SOILED":
        return False
    if infection_control_satisfied(device):
        device["status"] = "AVAILABLE"
        return True
    return False


# ------------------------------------------------------------------ cascades

def quarantine_device(device, reason, trigger_staff_id):
    """Drive a device to QUARANTINED and cascade onto its live studies."""
    device["status"] = "QUARANTINED"
    device["quarantined_at"] = iso(db.clock)
    device["quarantine_reason"] = reason
    device["quarantine_trigger_staff_id"] = trigger_staff_id


def cascade_device_quarantine(device):
    live = [s for s in db.sessions.values()
            if s["device_id"] == device["id"]
            and s["session_status"] in ("SCHEDULED", "IN_PROGRESS")]
    for session in by_created(live):
        abort_session(session, "DEVICE_QUARANTINED")


def close_device_after_session(device, session):
    """A study leaving the live state soils the instrument."""
    device["last_session_end_at"] = session.get("scheduled_end_at")
    device["sessions_since_filter_change"] = int(
        device.get("sessions_since_filter_change") or 0) + 1
    if device.get("status") != "QUARANTINED":
        device["status"] = "SOILED"
    touch(device)


def abort_session(session, reason):
    if session["session_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        return
    was_in_progress = session["session_status"] == "IN_PROGRESS"
    session["session_status"] = "ABORTED"
    session["abort_reason"] = reason
    touch(session)

    order = db.orders.get(session["order_id"])
    if order is not None and order["status"] == "IN_TESTING":
        order["status"] = "READY"
        order["abort_count"] = int(order.get("abort_count") or 0) + 1
        touch(order)

    for run in by_created([r for r in db.runs.values()
                           if r["session_id"] == session["id"]
                           and r["status"] in ("ARMED", "IN_PROGRESS")]):
        run["status"] = "ABORTED_SAFETY"
        run["stop_reason"] = "SESSION_ABORTED"
        settle_run_ledger(run)
        touch(run)

    for report in by_created([r for r in db.reports.values()
                              if r["session_id"] == session["id"]
                              and r["status"] == "ASSIGNED"]):
        report["status"] = "REASSIGNED"
        touch(report)
        adjust_open_reports(report.get("interpreter_staff_id"), -1)

    if was_in_progress:
        device = db.devices.get(session["device_id"])
        if device is not None:
            close_device_after_session(device, session)


def adjust_open_reports(staff_id, delta):
    staff = db.staff.get(staff_id) if staff_id else None
    if staff is None:
        return
    staff["open_report_count"] = max(
        0, int(staff.get("open_report_count") or 0) + delta)
    touch(staff)


def settle_run_ledger(run):
    """Reconcile the rescue ledger when a run reaches a terminal state."""
    lot = db.lots.get(run.get("rescue_lot_id"))
    administered = int(run.get("current_step_index") or 0) >= 1 or \
        run["status"] in ("STOPPED_PC20", "COMPLETED_NEGATIVE")
    if administered:
        run["rescue_doses_administered"] = calc.RESCUE_ADMIN_DOSES
    if lot is None:
        return
    if administered:
        lot["doses_remaining"] = int(lot["doses_remaining"]) - \
            calc.RESCUE_ADMIN_DOSES
    lot["doses_reserved"] = int(lot["doses_reserved"]) - \
        calc.RESCUE_RESERVE_DOSES
    if int(lot["doses_remaining"]) == 0 and lot["status"] == "STOCKED":
        lot["status"] = "DEPLETED"
    touch(lot)


# ------------------------------------------------------- medication hold logic

def order_holds(order_id):
    return [h for h in db.holds.values() if h["order_id"] == order_id]


def recompute_hold_release(order):
    """hold_release_at is the maximum release point over every PENDING or
    ATTESTED hold on the order; null when that set is empty."""
    latest = None
    for hold in order_holds(order["id"]):
        if hold["status"] not in ("PENDING", "ATTESTED"):
            continue
        instructed = parse_iso(hold["instructed_at"])
        release = instructed + timedelta(
            hours=int(hold["required_hold_hours"]))
        if latest is None or release > latest:
            latest = release
    order["hold_release_at"] = iso(latest) if latest is not None else None


# ------------------------------------------------------ session recomputation

def session_maneuvers(session_id):
    return [m for m in db.maneuvers.values() if m["session_id"] == session_id]


def _best_two(pool, field):
    """Highest and next-highest values; ties broken by performed_at then
    created_at ascending."""
    ordered = sorted(pool, key=lambda m: (-D(m[field]),
                                          m["performed_at"] or "",
                                          m.get("_seq") or 0))
    if not ordered:
        return None, None
    if len(ordered) == 1:
        return ordered[0][field], None
    return ordered[0][field], ordered[1][field]


def _delta_ml(best, second):
    if best is None or second is None:
        return None
    return rnd_int(abs(D(best) - D(second)) * D(1000))


def recompute_session_quality(session):
    maneuvers = session_maneuvers(session["id"])
    pre = [m for m in maneuvers if m["phase"] == "PRE_BD"]
    fev1_pool = [m for m in pre
                 if m["acceptability"] in ("ACCEPTABLE", "USABLE_FEV1_ONLY")]
    fvc_pool = [m for m in pre if m["acceptability"] == "ACCEPTABLE"]
    post_pool = [m for m in maneuvers
                 if m["phase"] == "POST_BD"
                 and m["acceptability"] in ("ACCEPTABLE",
                                            "USABLE_FEV1_ONLY")]

    best_fev1, second_fev1 = _best_two(fev1_pool, "fev1_l")
    best_fvc, second_fvc = _best_two(fvc_pool, "fvc_l")
    best_post, _ = _best_two(post_pool, "fev1_l")

    session["best_fev1_l"] = best_fev1
    session["best_fvc_l"] = best_fvc
    session["best_fev1_post_l"] = best_post
    session["acceptable_maneuver_count"] = len(
        [m for m in pre if m["acceptability"] == "ACCEPTABLE"])

    rep = _delta_ml(best_fev1, second_fev1)
    fvc_rep = _delta_ml(best_fvc, second_fvc)
    session["repeatability_delta_ml"] = rep
    session["fvc_repeatability_delta_ml"] = fvc_rep
    session["quality_grade"] = calc.quality_grade(
        session["acceptable_maneuver_count"], rep, fvc_rep)

    predicted_fev1 = session.get("predicted_fev1_l")
    predicted_fvc = session.get("predicted_fvc_l")
    if best_fev1 is not None and predicted_fev1:
        session["fev1_pct_predicted"] = num(
            rnd(D(best_fev1) / D(predicted_fev1) * D(100), 1))
    else:
        session["fev1_pct_predicted"] = None
    if best_fvc is not None and predicted_fvc:
        session["fvc_pct_predicted"] = num(
            rnd(D(best_fvc) / D(predicted_fvc) * D(100), 1))
    else:
        session["fvc_pct_predicted"] = None
    if best_fev1 is not None and best_fvc is not None:
        session["fev1_fvc_ratio"] = num(
            rnd(D(best_fev1) / D(best_fvc), 3))
    else:
        session["fev1_fvc_ratio"] = None


def apply_bronchodilator_response(session, order):
    """Computed when the study is accepted, the order asked for a
    bronchodilator and a post-bronchodilator best exists."""
    if not order.get("bronchodilator_requested"):
        return
    pre = session.get("best_fev1_l")
    post = session.get("best_fev1_post_l")
    if pre is None or post is None:
        return
    equation = db.equations.get(session.get("reference_equation_id"))
    criterion = (equation or {}).get("bd_criterion") or "PCT_BASELINE_2005"
    pct, delta_ml, variant, positive = calc.bronchodilator_response(
        criterion, pre, post, session.get("predicted_fev1_l"))
    session["bd_response_pct"] = num(pct)
    session["bd_response_ml"] = delta_ml
    session["bd_response_variant"] = variant
    session["bd_response_positive"] = positive


# ------------------------------------------------------ reference equation set

def select_reference_equation(device, patient):
    """Narrowest applicable age band wins, then the lowest lln_percentile,
    then the earliest created_at. Ids are never consulted."""
    age = age_years_of(patient)
    pool = []
    for equation in db.equations.values():
        if equation["status"] != "ACTIVE":
            continue
        if device["modality"] not in equation["modality_scope"]:
            continue
        if not (D(equation["applicable_age_min"]) <= D(age)
                <= D(equation["applicable_age_max"])):
            continue
        scope = equation["sex_scope"]
        if scope != "ANY" and scope != patient["sex"]:
            continue
        pool.append(equation)
    if not pool:
        raise ApiError("ERR_NO_REFERENCE_EQUATION")
    pool.sort(key=lambda e: (
        D(e["applicable_age_max"]) - D(e["applicable_age_min"]),
        D(e["lln_percentile"]),
        e["created_at"],
        e.get("_seq") or 0,
    ))
    return pool[0]


# ---------------------------------------------------------- interpreter policy

def select_interpreter(session, device, pending_release_staff_ids=None):
    """Lightest declared open workload wins, then the earliest created_at."""
    released = pending_release_staff_ids or {}
    pool = []
    for staff in db.staff.values():
        if staff["role_type"] != "INTERPRETING_PHYSICIAN":
            continue
        if staff["status"] != "ON_DUTY":
            continue
        if device["modality"] not in staff["credentialed_modalities"]:
            continue
        effective = int(staff.get("open_report_count") or 0) \
            - int(released.get(staff["id"], 0))
        if effective >= int(staff.get("max_concurrent_reports") or 1):
            continue
        if staff["id"] == session.get("technologist_staff_id"):
            continue
        pool.append((effective, staff))
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_INTERPRETER")
    pool.sort(key=lambda item: (item[0], item[1]["created_at"],
                                item[1].get("_seq") or 0))
    return pool[0][1]


def roster_capacity():
    total = 0
    for staff in db.staff.values():
        if staff["role_type"] != "INTERPRETING_PHYSICIAN":
            continue
        if staff["status"] != "ON_DUTY":
            continue
        total += int(staff.get("max_concurrent_reports") or 0)
    return total


def open_report_total():
    return len([r for r in db.reports.values()
                if r["status"] in ("ASSIGNED", "AMENDED")])
