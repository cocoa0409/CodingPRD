"""The recovery cascade upward and the teardown cascade downward (PRD §2.6,
§3.3, §3.5).  Every link is a real mutation: the touched row's `updated_at` is
refreshed and its `version` incremented exactly once per request.
"""
import calc
import clock
import db

OPEN_OUTAGE_STATES = calc.OPEN_OUTAGE_STATES
LIVE_DISPATCH_STATES = calc.LIVE_DISPATCH_STATES


# ------------------------------------------------------------------- suspension
def maybe_auto_suspend(station):
    if station is None:
        return
    if station["status"] != "OPERATIONAL":
        return
    if calc.out_of_service_port_count(station["id"]) >= 1:
        station["status"] = "SUSPENDED"
        station["suspension_source"] = "AUTOMATIC"
        db.touch(station)


def maybe_auto_resume(station):
    if station is None:
        return
    if station["status"] != "SUSPENDED":
        return
    if station["suspension_source"] != "AUTOMATIC":
        return
    if calc.out_of_service_port_count(station["id"]) == 0:
        station["status"] = "OPERATIONAL"
        station["suspension_source"] = "NONE"
        db.touch(station)


# ------------------------------------------------------------- port availability
def port_out_of_service(port):
    """Drive a dispenser IN_SERVICE -> OUT_OF_SERVICE and suspend its station if
    that was the station's first out-of-service dispenser."""
    if port["service_state"] != "IN_SERVICE":
        return False
    port["service_state"] = "OUT_OF_SERVICE"
    db.touch(port)
    maybe_auto_suspend(db.stations.get(port["station_id"]))
    return True


def port_may_return_to_service(port):
    if port["service_state"] != "OUT_OF_SERVICE":
        return False
    if port["terminal_certification_status"] == "REVOKED":
        return False
    for outage in db.outages_of_port(port["id"]):
        if outage["state"] in OPEN_OUTAGE_STATES:
            return False
    return True


def port_back_in_service(port):
    """Return a dispenser to service when nothing keeps it out, then lift an
    automatic station suspension if it was the last one out."""
    if not port_may_return_to_service(port):
        return False
    port["service_state"] = "IN_SERVICE"
    db.touch(port)
    maybe_auto_resume(db.stations.get(port["station_id"]))
    return True


def rederive_maintenance_state(port, excluding_dispatch_id=None):
    """The dispenser's aggregate repair posture after a dispatch leaves the live
    set: DISPATCH_PENDING while another dispatch is still live, else NONE."""
    for dispatch in db.dispatches_of_port(port["id"]):
        if excluding_dispatch_id is not None and dispatch["id"] == excluding_dispatch_id:
            continue
        if dispatch["state"] in LIVE_DISPATCH_STATES:
            return "DISPATCH_PENDING"
    return "NONE"


# ---------------------------------------------------------------- system outages
def create_system_outage(port, fault_code, fault_class):
    row = db.base_record()
    row.update({
        "port_id": port["id"],
        "fault_code": fault_code,
        "fault_class": fault_class,
        "detected_at": clock.now(),
        "cleared_at": None,
        "excluded_cause_claim": "NONE",
        "state": "DETECTED",
        "pre_exclusion_state": None,
        "excluded_at": None,
        "dispatch_created_by_user_id": None,
        "is_system_generated": True,
    })
    db.outages[row["id"]] = row
    db.mark_fresh(row)
    return row


# ------------------------------------------------------------- report invalidation
REPORT_COMPUTED_FIELDS = (
    "methodology",
    "eligible_port_count",
    "total_port_minutes",
    "excluded_minutes",
    "billable_downtime_minutes",
    "uptime_pct",
)


def invalidate_provisional_reports(station_id):
    """An exclusion approval or revocation moves the ledger under the station, so
    every PROVISIONAL report goes back to DRAFT with its figures cleared."""
    for report in db.reports_of_station(station_id):
        if report["state"] != "PROVISIONAL":
            continue
        report["state"] = "DRAFT"
        for field in REPORT_COMPUTED_FIELDS:
            report[field] = None
        db.touch(report)


# ------------------------------------------------------------------- part release
def release_reservation(reservation):
    reservation["state"] = "RELEASED"
    reservation["expected_available_at"] = None
    db.touch(reservation)
    part = db.spare_parts.get(reservation["spare_part_id"])
    if part is not None:
        db.touch(part)


# ---------------------------------------------------------------------- teardown
_PRE_EXCLUSION_NORMALISATION = {
    "DETECTED": "CLASSIFIED",
    "CLASSIFIED": "CLASSIFIED",
    "EXCLUSION_REVIEW": "CLASSIFIED",
    "DISPATCHED": "RESOLVED",
}


def teardown_station(station):
    """Decommissioning: retire dispensers -> exclude their open outages ->
    cancel the dispatches sent against them -> release the depot stock those
    dispatches earmarked (PRD §3.3 links 1-3)."""
    stamp = clock.now()

    for port in db.ports_of_station(station["id"]):
        if port["service_state"] not in ("IN_SERVICE", "OUT_OF_SERVICE"):
            continue
        port["service_state"] = "RETIRED"
        port["retired_at"] = stamp
        port["maintenance_state"] = "NONE"
        db.touch(port)

        for outage in db.outages_of_port(port["id"]):
            if outage["state"] not in OPEN_OUTAGE_STATES:
                continue
            outage["pre_exclusion_state"] = _PRE_EXCLUSION_NORMALISATION[outage["state"]]
            outage["state"] = "EXCLUDED"
            outage["excluded_cause_claim"] = "HOST_SITE_CLOSURE"
            outage["excluded_at"] = stamp
            if outage["cleared_at"] is None:
                outage["cleared_at"] = stamp
            db.touch(outage)

            for dispatch in db.dispatches_of_outage(outage["id"]):
                if dispatch["state"] not in LIVE_DISPATCH_STATES:
                    continue
                dispatch["state"] = "CANCELLED"
                db.touch(dispatch)
                for reservation in db.reservations_of_dispatch(dispatch["id"]):
                    if reservation["state"] not in ("RESERVED", "BACKORDERED"):
                        continue
                    release_reservation(reservation)

    station["status"] = "DECOMMISSIONED"
    station["suspension_source"] = "NONE"
    db.touch(station)
