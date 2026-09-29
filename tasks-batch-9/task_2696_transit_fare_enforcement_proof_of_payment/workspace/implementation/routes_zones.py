"""Zone designation, signage audits, the line network and the two registries."""

from flask import Blueprint

import calc
import cascade
import serial
from core import (ApiError, base_record, body, db, lookup, opt_bool, opt_enum,
                  opt_int, opt_str, ordered, page, pagination, query_filter,
                  req_dt, req_enum, req_int, req_str, respond_object, touch,
                  authorize)

bp = Blueprint("zones", __name__)

ALL_ROLES = ("EnforcementPlanner", "EquityAnalyst", "FareInspector",
             "HearingOfficer", "AppealsBoardMember", "Rider")


# ---------------------------------------------------------------------------
# Fare zones
# ---------------------------------------------------------------------------

@bp.post("/fare-zones")
def create_zone():
    authorize("EnforcementPlanner")
    payload = body()
    zone_code = req_str(payload, "zone_code", min_len=3, max_len=32)
    name = req_str(payload, "name", min_len=1)
    required_sign_count = req_int(payload, "required_sign_count", minimum=1)
    penalty_multiplier_bps = opt_int(payload, "penalty_multiplier_bps", default=10000,
                                     minimum=10000, maximum=15000)
    enforcement_policy = opt_enum(payload, "enforcement_policy",
                                  calc.ENFORCEMENT_POLICIES, default="CITATION_IMMEDIATE")
    max_concurrent = opt_int(payload, "max_concurrent_deployments", default=2,
                             minimum=1, maximum=5)

    for existing in db.zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "zone_code '%s' is already registered." % zone_code)

    zone = base_record()
    zone.update({
        "zone_code": zone_code,
        "name": name,
        "required_sign_count": required_sign_count,
        "penalty_multiplier_bps": penalty_multiplier_bps,
        "enforcement_policy": enforcement_policy,
        "max_concurrent_deployments": max_concurrent,
        "designation_status": "DRAFT",
        "designated_at": None,
        "suspension_reason": None,
    })
    db.zones[zone["id"]] = zone
    return respond_object(serial.zone_out(zone), 201)


@bp.post("/fare-zones/<zone_id>/submit-for-signage")
def submit_zone_for_signage(zone_id):
    authorize("EnforcementPlanner")
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["designation_status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ZONE_STATE",
                       "Zone is %s; only DRAFT or SUSPENDED may be submitted."
                       % zone["designation_status"])
    if zone["designation_status"] == "DRAFT":
        attached = any(a["zone_id"] == zone["id"] for a in db.assignments.values())
        if not attached:
            raise ApiError("ERR_INVALID_ZONE_STATE",
                           "Zone has no transit line attached and is not submittable.")
    zone["designation_status"] = "PENDING_SIGNAGE"
    zone["suspension_reason"] = None
    touch(zone)
    return respond_object(serial.zone_out(zone))


@bp.post("/fare-zones/<zone_id>/designate")
def designate_zone(zone_id):
    authorize("EnforcementPlanner")
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["designation_status"] != "PENDING_SIGNAGE":
        raise ApiError("ERR_INVALID_ZONE_STATE",
                       "Zone is %s; only PENDING_SIGNAGE may be designated."
                       % zone["designation_status"])
    audits = calc.zone_audits(zone["id"])
    _verified, pct = calc.zone_signage(zone)
    if not audits or pct < calc.SIGNAGE_MIN_PCT:
        raise ApiError("ERR_SIGNAGE_BELOW_THRESHOLD",
                       "Signage compliance is below the statutory floor of 0.9000.")
    zone["designation_status"] = "DESIGNATED"
    zone["designated_at"] = db.now()
    touch(zone)
    return respond_object(serial.zone_out(zone))


@bp.post("/fare-zones/<zone_id>/suspend")
def suspend_zone(zone_id):
    authorize("EnforcementPlanner")
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["designation_status"] != "DESIGNATED":
        raise ApiError("ERR_INVALID_ZONE_STATE",
                       "Zone is %s; only DESIGNATED may be suspended."
                       % zone["designation_status"])
    zone["designation_status"] = "SUSPENDED"
    zone["suspension_reason"] = "ADMINISTRATIVE_HOLD"
    cascade.zone_suspension_cascade(zone)
    touch(zone)
    return respond_object(serial.zone_out(zone))


@bp.post("/fare-zones/<zone_id>/revoke")
def revoke_zone(zone_id):
    authorize("EnforcementPlanner")
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["designation_status"] not in ("DESIGNATED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ZONE_STATE",
                       "Zone is %s; only DESIGNATED or SUSPENDED may be revoked."
                       % zone["designation_status"])
    zone["designation_status"] = "REVOKED"
    cascade.zone_revocation_cascade(zone)
    touch(zone)
    return respond_object(serial.zone_out(zone))


@bp.get("/fare-zones/<zone_id>")
def get_zone(zone_id):
    authorize(*ALL_ROLES)
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    return respond_object(serial.zone_out(zone))


@bp.get("/fare-zones")
def list_zones():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    status = query_filter("designation_status")
    rows = [z for z in db.zones.values()
            if status is None or z["designation_status"] == status]
    return page(ordered(rows), limit, offset, serial.zone_out)


@bp.get("/fare-zones/<zone_id>/signage-audits")
def list_zone_audits(zone_id):
    authorize("EnforcementPlanner", "EquityAnalyst")
    limit, offset = pagination()
    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    rows = ordered(calc.zone_audits(zone["id"]))
    return page(rows, limit, offset, serial.audit_out)


@bp.post("/signage-audits")
def create_signage_audit():
    actor = authorize("EnforcementPlanner")
    payload = body()
    zone_id = req_str(payload, "zone_id", min_len=1)
    audited_at = req_dt(payload, "audited_at")
    signs_verified_count = req_int(payload, "signs_verified_count", minimum=0)
    deficiency_note = opt_str(payload, "deficiency_note")

    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")

    audit = base_record(versioned=False)
    audit.update({
        "zone_id": zone["id"],
        "audited_at": audited_at,
        "signs_verified_count": signs_verified_count,
        "deficiency_note": deficiency_note,
        "auditor_user_id": actor.user_id,
    })
    db.audits[audit["id"]] = audit

    _verified, pct = calc.zone_signage(zone)
    if zone["designation_status"] == "DESIGNATED" and pct < calc.SIGNAGE_MIN_PCT:
        zone["designation_status"] = "SUSPENDED"
        zone["suspension_reason"] = "SIGNAGE_DEFICIENCY"
        cascade.zone_suspension_cascade(zone)
    touch(zone)
    return respond_object(serial.audit_out(audit), 201)


# ---------------------------------------------------------------------------
# Transit lines and zone-line assignments
# ---------------------------------------------------------------------------

@bp.post("/transit-lines")
def create_line():
    authorize("EnforcementPlanner")
    payload = body()
    line_code = req_str(payload, "line_code", min_len=1)
    mode = req_enum(payload, "mode", calc.LINE_MODES)
    daily_boardings = req_int(payload, "daily_boardings", minimum=1)
    baseline = req_int(payload, "baseline_evasion_rate_bps", minimum=0, maximum=10000)

    for existing in db.lines.values():
        if existing["line_code"] == line_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "line_code '%s' is already registered." % line_code)

    line = base_record()
    line.update({
        "line_code": line_code,
        "mode": mode,
        "daily_boardings": daily_boardings,
        "baseline_evasion_rate_bps": baseline,
    })
    db.lines[line["id"]] = line
    return respond_object(serial.line_out(line), 201)


@bp.get("/transit-lines/<line_id>")
def get_line(line_id):
    authorize("EnforcementPlanner", "EquityAnalyst", "FareInspector")
    line = lookup(db.lines, line_id, "ERR_LINE_NOT_FOUND")
    return respond_object(serial.line_out(line))


@bp.post("/zone-line-assignments")
def create_assignment():
    authorize("EnforcementPlanner")
    payload = body()
    zone_id = req_str(payload, "zone_id", min_len=1)
    line_id = req_str(payload, "line_id", min_len=1)
    platform_segment_count = req_int(payload, "platform_segment_count", minimum=1)
    effective_from = req_dt(payload, "effective_from")

    zone = lookup(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    line = lookup(db.lines, line_id, "ERR_LINE_NOT_FOUND")

    for existing in db.assignments.values():
        if existing["zone_id"] == zone["id"] and existing["line_id"] == line["id"]:
            raise ApiError("ERR_ASSIGNMENT_ALREADY_EXISTS",
                           "This line is already attached to this zone.")

    row = base_record(versioned=False)
    row.update({
        "zone_id": zone["id"],
        "line_id": line["id"],
        "platform_segment_count": platform_segment_count,
        "effective_from": effective_from,
    })
    db.assignments[row["id"]] = row
    return respond_object(serial.assignment_out(row), 201)


@bp.get("/zone-line-assignments/<assignment_id>")
def get_assignment(assignment_id):
    authorize("EnforcementPlanner", "EquityAnalyst")
    row = lookup(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    return respond_object(serial.assignment_out(row))


@bp.get("/zone-line-assignments")
def list_assignments():
    authorize("EnforcementPlanner", "EquityAnalyst")
    limit, offset = pagination()
    zone_id = query_filter("zone_id")
    line_id = query_filter("line_id")
    rows = [a for a in db.assignments.values()
            if (zone_id is None or a["zone_id"] == zone_id)
            and (line_id is None or a["line_id"] == line_id)]
    return page(ordered(rows), limit, offset, serial.assignment_out)


# ---------------------------------------------------------------------------
# Inspector roster and rider registry
# ---------------------------------------------------------------------------

@bp.post("/inspectors")
def create_inspector():
    authorize("EnforcementPlanner")
    payload = body()
    badge_number = req_str(payload, "badge_number", min_len=1)
    display_name = req_str(payload, "display_name", min_len=1)
    certification_expiry = req_dt(payload, "certification_expiry")
    status = opt_enum(payload, "status", calc.INSPECTOR_STATUSES, default="ACTIVE")

    for existing in db.inspectors.values():
        if existing["badge_number"] == badge_number:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "badge_number '%s' is already registered." % badge_number)

    inspector = base_record()
    inspector.update({
        "badge_number": badge_number,
        "display_name": display_name,
        "certification_expiry": certification_expiry,
        "status": status,
    })
    db.inspectors[inspector["id"]] = inspector
    return respond_object(serial.inspector_out(inspector), 201)


@bp.get("/inspectors/<inspector_id>")
def get_inspector(inspector_id):
    authorize("EnforcementPlanner", "EquityAnalyst", "FareInspector", "HearingOfficer")
    inspector = lookup(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    return respond_object(serial.inspector_out(inspector))


@bp.post("/riders")
def create_rider():
    authorize("EnforcementPlanner")
    payload = body()
    rider_ref = req_str(payload, "rider_ref", min_len=1)
    display_name = req_str(payload, "display_name", min_len=1)
    demographic_band = req_enum(payload, "demographic_band", calc.DEMOGRAPHIC_BANDS)
    residence_geo_tract = req_str(payload, "residence_geo_tract", min_len=1)
    fare_assistance_enrolled = opt_bool(payload, "fare_assistance_enrolled", default=False)

    for existing in db.riders.values():
        if existing["rider_ref"] == rider_ref:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "rider_ref '%s' is already registered." % rider_ref)

    rider = base_record()
    rider.update({
        "rider_ref": rider_ref,
        "display_name": display_name,
        "demographic_band": demographic_band,
        "residence_geo_tract": residence_geo_tract,
        "fare_assistance_enrolled": fare_assistance_enrolled,
    })
    db.riders[rider["id"]] = rider
    return respond_object(serial.rider_out(rider), 201)


@bp.get("/riders/<rider_id>")
def get_rider(rider_id):
    authorize("EnforcementPlanner", "EquityAnalyst", "Rider", "HearingOfficer",
              "AppealsBoardMember")
    rider = lookup(db.riders, rider_id, "ERR_RIDER_NOT_FOUND")
    return respond_object(serial.rider_out(rider))
