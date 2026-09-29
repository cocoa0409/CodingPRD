"""Provisioning packages: sealing, publication cadence and rollback."""

from flask import Blueprint

import calc
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, sorted_rows, touch

bp = Blueprint("packages", __name__)

CHANNELS = ["DISPATCH_E911", "MAPPING", "PUBLIC"]
PACKAGE_STATUSES = ["DRAFT", "SEALED", "PUBLISHED", "SUPERSEDED", "INVALIDATED", "ROLLED_BACK"]
RECORD_TYPES = ["ADDRESS_POINT", "ROAD_CENTERLINE", "EMERGENCY_SERVICE_BOUNDARY"]
PIN_STATES = ["FRESH", "STALE"]


@bp.post("/provisioning-packages")
def create_package():
    v.auth(["ProvisioningOfficer"])
    data = v.body()
    jurisdiction = v.maybe_find("jurisdiction", v.raw_ref(data, "jurisdiction_id"))
    report = v.maybe_find("report", v.raw_ref(data, "qc_report_id"))
    channel = v.req_enum(data, "channel", CHANNELS)
    v.req_id(data, "jurisdiction_id")
    v.req_id(data, "qc_report_id")

    row = base_record()
    row.update({
        "channel": channel,
        "jurisdiction_id": jurisdiction["id"],
        "qc_report_id": report["id"],
        "status": "DRAFT",
        "package_version": None,
        "sealed_at": None,
        "published_at": None,
        "sealed_by_user_id": None,
        "published_by_user_id": None,
        "invalidated_reason": None,
        "rollback_reason": None,
    })
    db.packages[row["id"]] = row
    return created(ser.package(row))


@bp.get("/provisioning-packages/<identifier>")
def get_package(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("package", identifier)
    return ok(ser.package(row))


@bp.get("/provisioning-packages")
def list_packages():
    v.auth(v.ALL_ROLES)
    channel = v.q_enum("channel", CHANNELS)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    report_id = v.q_str("qc_report_id")
    if report_id is not None:
        v.find("report", report_id)
    status = v.q_enum("status", PACKAGE_STATUSES)
    limit, offset = v.pagination()
    rows = sorted_rows(list(db.packages.values()))
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if report_id is not None:
        rows = [r for r in rows if r["qc_report_id"] == report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.package(r) for r in page], limit, offset, total)


@bp.get("/provisioning-packages/<identifier>/records")
def list_package_records(identifier):
    v.auth(v.ALL_ROLES)
    package = v.find("package", identifier)
    record_type = v.q_enum("record_type", RECORD_TYPES)
    pin_state = v.q_enum("pin_state", PIN_STATES)
    limit, offset = v.pagination()
    rows = calc.package_records(package["id"])
    if record_type is not None:
        rows = [r for r in rows if r["record_type"] == record_type]
    if pin_state is not None:
        rows = [r for r in rows if r["pin_state"] == pin_state]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.package_record(r) for r in page], limit, offset, total)


@bp.post("/provisioning-packages/<identifier>/seal")
def seal_package(identifier):
    user_id, _role = v.auth(["ProvisioningOfficer"])
    package = v.find("package", identifier)
    if package["status"] != "DRAFT":
        raise ApiError("ERR_PACKAGE_INVALID_STATE",
                       "Only a DRAFT package may be sealed; this one is %s." % package["status"])
    report = db.reports.get(package["qc_report_id"])
    if report is None or report["status"] != "CERTIFIED":
        raise ApiError("ERR_QC_REPORT_NOT_CERTIFIED",
                       "The authorising QC report is not CERTIFIED.")
    scope = calc.package_scope_records(package["jurisdiction_id"])
    if not scope:
        raise ApiError("ERR_PACKAGE_EMPTY",
                       "No provisionable records exist for this jurisdiction.")
    scores = calc.report_scores(report["id"])
    if not scores["is_provisioning_eligible"]:
        raise ApiError("ERR_QC_SCORE_BELOW_THRESHOLD",
                       "provisioning_eligibility_score %.2f is below the 90.00 threshold."
                       % scores["provisioning_eligibility_score"])

    package["package_version"] = calc.next_package_version(package["channel"],
                                                           package["jurisdiction_id"])
    for record_type, record_id, live_version in scope:
        pin = base_record()
        pin.update({
            "package_id": package["id"],
            "record_type": record_type,
            "record_id": record_id,
            "pinned_version": live_version,
            "pin_state": "FRESH",
            "staled_at": None,
        })
        db.package_records[pin["id"]] = pin
    package["status"] = "SEALED"
    package["sealed_at"] = db.now()
    package["sealed_by_user_id"] = user_id
    touch(package)
    return ok(ser.package(package))


@bp.post("/provisioning-packages/<identifier>/publish")
def publish_package(identifier):
    user_id, _role = v.auth(["ProvisioningOfficer"])
    package = v.find("package", identifier)
    if package["status"] != "SEALED":
        raise ApiError("ERR_PACKAGE_INVALID_STATE",
                       "Only a SEALED package may be published; this one is %s."
                       % package["status"])
    report = db.reports.get(package["qc_report_id"])
    if report is not None and report["certified_by_user_id"] is not None \
            and user_id == report["certified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The certifier of the authorising report may not publish the package.")
    if package["channel"] == "DISPATCH_E911":
        counters = calc.jurisdiction_counters(package["jurisdiction_id"])
        if counters["forward_gap_pair_count"] > 0:
            raise ApiError("ERR_COVERAGE_GAP_BLOCKS_E911",
                           "%d forward coverage gap pairs block a DISPATCH_E911 release."
                           % counters["forward_gap_pair_count"])
    if calc.package_pin_counts(package["id"])["stale_pin_count"] > 0:
        raise ApiError("ERR_PACKAGE_PINS_STALE",
                       "The snapshot has drifted and must be rebuilt.")
    if not calc.cadence_window_open(package["channel"], package["jurisdiction_id"]):
        raise ApiError("ERR_CADENCE_WINDOW_NOT_OPEN",
                       "The %s cadence window for this jurisdiction is not open yet."
                       % package["channel"])

    package["status"] = "PUBLISHED"
    package["published_at"] = db.now()
    package["published_by_user_id"] = user_id
    touch(package)
    for other in sorted_rows(list(db.packages.values())):
        if other["id"] == package["id"]:
            continue
        if other["channel"] != package["channel"]:
            continue
        if other["jurisdiction_id"] != package["jurisdiction_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)
    return ok(ser.package(package))


@bp.post("/provisioning-packages/<identifier>/rollback")
def rollback_package(identifier):
    v.auth(["ProvisioningOfficer"])
    package = v.find("package", identifier)
    data = v.body()
    reason = v.req_str(data, "rollback_reason", 1)
    if package["status"] != "PUBLISHED":
        raise ApiError("ERR_PACKAGE_INVALID_STATE",
                       "Only a PUBLISHED package may be rolled back; this one is %s."
                       % package["status"])
    predecessors = [r for r in db.packages.values()
                    if r["id"] != package["id"]
                    and r["channel"] == package["channel"]
                    and r["jurisdiction_id"] == package["jurisdiction_id"]
                    and r["status"] == "SUPERSEDED"]
    if not predecessors:
        raise ApiError("ERR_NO_PUBLISHED_PREDECESSOR",
                       "No superseded predecessor exists to restore on this channel.")
    predecessors.sort(key=lambda r: (-(r["package_version"] or 0), r["created_at"], r["_seq"]))
    predecessor = predecessors[0]

    package["status"] = "ROLLED_BACK"
    package["rollback_reason"] = reason
    touch(package)
    predecessor["status"] = "PUBLISHED"
    touch(predecessor)
    return ok(ser.package(package))
