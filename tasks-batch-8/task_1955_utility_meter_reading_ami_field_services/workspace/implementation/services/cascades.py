"""Cross-entity cascade helpers shared by route handlers."""
from db import db, touch


def cancel_pending_stops_for_account(account_id):
    """Account suspend cascade: PENDING stops on non-terminal routes -> CANCELLED."""
    for stop in db.stops.values():
        if stop["service_account_id"] != account_id or stop["stop_status"] != "PENDING":
            continue
        route = db.routes.get(stop["route_id"])
        if route and route["route_status"] in ("DRAFT", "ASSIGNED", "IN_PROGRESS"):
            stop["stop_status"] = "CANCELLED"
            touch(stop)


def campaign_autocomplete_check(campaign_id):
    """OPEN campaign -> COMPLETED when >=1 enrollment exists and all are terminal."""
    camp = db.campaigns.get(campaign_id)
    if not camp or camp["campaign_status"] != "OPEN":
        return
    enrs = [e for e in db.enrollments.values() if e["campaign_id"] == campaign_id]
    if enrs and all(e["enrollment_status"] in ("REPLACED", "WITHDRAWN") for e in enrs):
        camp["campaign_status"] = "COMPLETED"
        touch(camp)


def withdraw_enrollments_for_meter(meter_id, cancel_states=("OPEN", "DISPATCHED")):
    """Meter removed/suspected cascade: non-terminal enrollments -> WITHDRAWN and
    their linked work orders (in cancel_states) -> CANCELLED."""
    for e in db.enrollments.values():
        if e["meter_id"] != meter_id:
            continue
        if e["enrollment_status"] not in ("ENROLLED", "WORK_ORDER_CREATED"):
            continue
        e["enrollment_status"] = "WITHDRAWN"
        touch(e)
        if e["work_order_id"]:
            wo = db.work_orders.get(e["work_order_id"])
            if wo and wo["work_order_status"] in cancel_states:
                wo["work_order_status"] = "CANCELLED"
                touch(wo)
        campaign_autocomplete_check(e["campaign_id"])


def suspect_meter(meter):
    """tamper_status NONE -> SUSPECTED plus enrollment-withdrawal cascade."""
    if meter["tamper_status"] == "NONE":
        meter["tamper_status"] = "SUSPECTED"
        touch(meter)
        withdraw_enrollments_for_meter(meter["id"])


def hazard_resolution_cascade(account_id, resolved_flag_id):
    """After a flag clears/expires: when no other ACTIVE flag remains on the
    account, SKIPPED_HAZARD stops citing the resolved flag revert to PENDING
    (route must be ASSIGNED or IN_PROGRESS)."""
    other_active = any(
        h["service_account_id"] == account_id
        and h["flag_status"] == "ACTIVE"
        and h["id"] != resolved_flag_id
        for h in db.hazards.values()
    )
    if other_active:
        return
    for stop in db.stops.values():
        if stop["service_account_id"] != account_id:
            continue
        if stop["stop_status"] != "SKIPPED_HAZARD":
            continue
        if stop["hazard_flag_id"] != resolved_flag_id:
            continue
        route = db.routes.get(stop["route_id"])
        if route and route["route_status"] in ("ASSIGNED", "IN_PROGRESS"):
            stop["stop_status"] = "PENDING"
            stop["hazard_flag_id"] = None
            touch(stop)


def technician_window_conflict(technician_id, date_str, shift, exclude_route_id=None,
                               exclude_order_id=None):
    """Same technician, same date, overlapping shift across assigned routes and
    dispatched work orders."""
    from util import shifts_overlap

    for r in db.routes.values():
        if r["id"] == exclude_route_id:
            continue
        if (
            r["technician_id"] == technician_id
            and r["route_status"] in ("ASSIGNED", "IN_PROGRESS")
            and r["scheduled_date"] == date_str
            and shifts_overlap(r["route_shift"], shift)
        ):
            return True
    for w in db.work_orders.values():
        if w["id"] == exclude_order_id:
            continue
        if (
            w["technician_id"] == technician_id
            and w["work_order_status"] in ("DISPATCHED", "IN_PROGRESS")
            and w["scheduled_date"] == date_str
            and w["work_shift"] is not None
            and shifts_overlap(w["work_shift"], shift)
        ):
            return True
    return False


def non_terminal_investigation_for_meter(meter_id):
    for inv in db.investigations.values():
        if inv["meter_id"] == meter_id and inv["investigation_status"] != "CLOSED":
            return inv
    return None


def evidence_hold_active(meter):
    """Evidence-preservation hold: SUSPECTED meter with a non-terminal investigation."""
    return (
        meter["tamper_status"] == "SUSPECTED"
        and non_terminal_investigation_for_meter(meter["id"]) is not None
    )


def create_read(route_stop_id, service_account_id, meter_id, read_value, read_at,
                read_source, read_status, estimation_method=None,
                tamper_indication=False):
    from db import stamp_new

    rec = {
        "route_stop_id": route_stop_id,
        "service_account_id": service_account_id,
        "meter_id": meter_id,
        "read_value": read_value,
        "read_at": read_at,
        "read_source": read_source,
        "read_status": read_status,
        "estimation_method": estimation_method,
        "tamper_indication": tamper_indication,
        "supersedes_read_id": None,
        "rejection_reason": None,
    }
    stamp_new(rec)
    db.reads[rec["id"]] = rec
    # Any actual read reaching VALIDATED resets the account's estimate streak.
    if read_status == "VALIDATED":
        account = db.accounts.get(service_account_id)
        if account and account["estimated_read_streak"] != 0:
            account["estimated_read_streak"] = 0
            touch(account)
    return rec
