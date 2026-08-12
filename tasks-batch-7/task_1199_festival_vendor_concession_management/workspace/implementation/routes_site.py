"""Zones, booths, booth assignments, and inspection records."""
from flask import Blueprint

import serialize
from calc import ACTIVE_ASSIGNMENT_STATES, issue_system_fine, release_assignment, zone_reserved
from store import db
from util import (ALL_ROLES, body_json, err, get_or_404, list_response, new_id,
                  opt_str, req_bool, req_int, req_str, req_enum, require_role,
                  stamp_new, success, touch)

bp = Blueprint("site", __name__)

INSPECTION_TYPES = ("HEALTH_PREOPEN", "HEALTH_SPOT", "FIRE_SAFETY")
INSPECTION_RESULTS = ("PASS", "CONDITIONAL_PASS", "FAIL")


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@bp.route("/zones", methods=["POST"])
def create_zone():
    require_role("OperationsLead")
    b = body_json()
    festival = None
    if b.get("festival_id") is not None:
        festival = get_or_404(db.festivals, b.get("festival_id"),
                              "ERR_FESTIVAL_NOT_FOUND", "Festival")
    name = req_str(b, "name")
    power_capacity = req_int(b, "power_capacity_amps", min_v=1)
    water_total = req_int(b, "water_hookup_total", min_v=0)
    if festival is None:
        get_or_404(db.festivals, b.get("festival_id"), "ERR_FESTIVAL_NOT_FOUND", "Festival")
    zone = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "festival_id": festival["id"],
        "name": name,
        "power_capacity_amps": power_capacity,
        "water_hookup_total": water_total,
    })
    db.zones[zone["id"]] = zone
    return success(serialize.serialize_zone(zone), 201)


@bp.route("/zones", methods=["GET"])
def list_zones():
    require_role(*ALL_ROLES)
    return list_response(list(db.zones.values()), serialize.serialize_zone,
                         {"festival_id": "festival_id"})


@bp.route("/zones/<zoneId>", methods=["GET"])
def get_zone(zoneId):
    require_role(*ALL_ROLES)
    zone = get_or_404(db.zones, zoneId, "ERR_ZONE_NOT_FOUND", "Zone")
    return success(serialize.serialize_zone(zone))


# ---------------------------------------------------------------------------
# Booths
# ---------------------------------------------------------------------------

@bp.route("/booths", methods=["POST"])
def create_booth():
    require_role("OperationsLead")
    b = body_json()
    zone = None
    if b.get("zone_id") is not None:
        zone = get_or_404(db.zones, b.get("zone_id"), "ERR_ZONE_NOT_FOUND", "Zone")
    label = req_str(b, "label")
    outlet = req_int(b, "power_outlet_max_amps", min_v=1)
    has_water = req_bool(b, "has_water_hookup")
    if zone is None:
        get_or_404(db.zones, b.get("zone_id"), "ERR_ZONE_NOT_FOUND", "Zone")
    booth = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "zone_id": zone["id"],
        "label": label,
        "power_outlet_max_amps": outlet,
        "has_water_hookup": has_water,
        "status": "AVAILABLE",
    })
    db.booths[booth["id"]] = booth
    return success(serialize.serialize_booth(booth), 201)


@bp.route("/booths", methods=["GET"])
def list_booths():
    require_role(*ALL_ROLES)
    return list_response(list(db.booths.values()), serialize.serialize_booth,
                         {"zone_id": "zone_id", "status": "status"})


@bp.route("/booths/<boothId>", methods=["GET"])
def get_booth(boothId):
    require_role(*ALL_ROLES)
    booth = get_or_404(db.booths, boothId, "ERR_BOOTH_NOT_FOUND", "Booth")
    return success(serialize.serialize_booth(booth))


# ---------------------------------------------------------------------------
# Booth assignments
# ---------------------------------------------------------------------------

def _admission_checks(assignment_app, booth, power_draw, requires_water,
                      exclude_assignment_id=None):
    """Priority-12 admission checks against a booth and its zone (PRD §3.3 order)."""
    zone = db.zones[booth["zone_id"]]
    if booth["status"] != "AVAILABLE":
        err("ERR_BOOTH_NOT_AVAILABLE", 409, "Booth is not AVAILABLE")
    if power_draw > booth["power_outlet_max_amps"]:
        err("ERR_POWER_DRAW_EXCEEDS_OUTLET", 400,
            "power_draw_amps exceeds the booth's power_outlet_max_amps")
    if requires_water and not booth["has_water_hookup"]:
        err("ERR_WATER_HOOKUP_UNAVAILABLE", 400,
            "requires_water but the booth has no water hookup")
    conflict = any(
        a["zone_id"] == zone["id"]
        and a["status"] in ACTIVE_ASSIGNMENT_STATES
        and a["id"] != exclude_assignment_id
        and db.applications[a["application_id"]]["category"] == assignment_app["category"]
        for a in db.assignments.values()
    )
    if conflict:
        err("ERR_CATEGORY_EXCLUSIVITY_CONFLICT", 409,
            "An active assignment with this category already exists in the zone")
    reserved_power, reserved_water = zone_reserved(
        zone["id"], exclude_assignment_id=exclude_assignment_id)
    if reserved_power + power_draw > zone["power_capacity_amps"]:
        err("ERR_POWER_CAPACITY_EXCEEDED", 409,
            "Zone power capacity would be exceeded")
    if requires_water and reserved_water + 1 > zone["water_hookup_total"]:
        err("ERR_WATER_CAPACITY_EXCEEDED", 409,
            "Zone water hookup capacity would be exceeded")


@bp.route("/booth-assignments", methods=["POST"])
def create_assignment():
    require_role("OperationsLead")
    b = body_json()
    # (4) Body FK existence.
    app = None
    if b.get("application_id") is not None:
        app = get_or_404(db.applications, b.get("application_id"),
                         "ERR_APPLICATION_NOT_FOUND", "Application")
    booth = None
    if b.get("booth_id") is not None:
        booth = get_or_404(db.booths, b.get("booth_id"),
                           "ERR_BOOTH_NOT_FOUND", "Booth")

    # (6) Festival posture gate.
    if app is not None:
        festival = db.festivals[app["festival_id"]]
        if festival["status"] != "CURATED":
            err("ERR_FESTIVAL_NOT_ACCEPTING_ASSIGNMENTS", 409,
                "Festival is not in CURATED")

    # (8) State legality + request shape.
    if app is not None and app["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            "Application must be ACCEPTED to reserve a booth")
    power_draw = req_int(b, "power_draw_amps", min_v=1)
    requires_water = req_bool(b, "requires_water")
    if app is None:
        get_or_404(db.applications, b.get("application_id"),
                   "ERR_APPLICATION_NOT_FOUND", "Application")
    if booth is None:
        get_or_404(db.booths, b.get("booth_id"), "ERR_BOOTH_NOT_FOUND", "Booth")

    # (9) Cross-festival integrity.
    zone = db.zones[booth["zone_id"]]
    if zone["festival_id"] != app["festival_id"]:
        err("ERR_CROSS_FESTIVAL_REFERENCE", 409,
            "Application and booth belong to different festivals")

    # (12) Admission checks.
    _admission_checks(app, booth, power_draw, requires_water)

    assignment = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "application_id": app["id"],
        "booth_id": booth["id"],
        "festival_id": zone["festival_id"],
        "zone_id": zone["id"],
        "status": "RESERVED",
        "utility_status": "PENDING",
        "power_draw_amps": power_draw,
        "requires_water": requires_water,
        "fee_model": None,
        "flat_fee_cents": None,
        "revenue_share_pct_bp": None,
        "tier_mode": None,
        "minimum_guarantee_cents": None,
        "free_allowance_cents": None,
    })
    db.assignments[assignment["id"]] = assignment
    booth["status"] = "RESERVED"
    touch(booth)
    return success(serialize.serialize_assignment(assignment), 201)


@bp.route("/booth-assignments", methods=["GET"])
def list_assignments():
    require_role(*ALL_ROLES)
    return list_response(list(db.assignments.values()),
                         serialize.serialize_assignment, {
                             "festival_id": "festival_id",
                             "application_id": "application_id",
                             "booth_id": "booth_id",
                             "zone_id": "zone_id",
                             "status": "status",
                         })


@bp.route("/booth-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    require_role(*ALL_ROLES)
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    return success(serialize.serialize_assignment(assignment))


@bp.route("/booth-assignments/<assignmentId>/confirm", methods=["POST"])
def confirm_assignment(assignmentId):
    require_role("OperationsLead")
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    if assignment["status"] != "RESERVED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"confirm is not permitted from {assignment['status']}")
    app = db.applications[assignment["application_id"]]
    assignment["fee_model"] = app["curated_fee_model"]
    assignment["flat_fee_cents"] = app["curated_flat_fee_cents"]
    assignment["revenue_share_pct_bp"] = app["curated_revenue_share_pct_bp"]
    assignment["tier_mode"] = app["curated_tier_mode"]
    assignment["minimum_guarantee_cents"] = app["curated_minimum_guarantee_cents"]
    assignment["free_allowance_cents"] = app["curated_free_allowance_cents"]
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    booth = db.booths[assignment["booth_id"]]
    booth["status"] = "ASSIGNED"
    touch(booth)
    return success(serialize.serialize_assignment(assignment))


@bp.route("/booth-assignments/<assignmentId>/reassign", methods=["POST"])
def reassign_assignment(assignmentId):
    require_role("OperationsLead")
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    b = body_json()
    # (4) Body FK existence.
    new_booth = None
    if b.get("new_booth_id") is not None:
        new_booth = get_or_404(db.booths, b.get("new_booth_id"),
                               "ERR_BOOTH_NOT_FOUND", "Booth")

    # (8) State legality + request shape.
    if assignment["status"] not in ("RESERVED", "CONFIRMED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"reassign is not permitted from {assignment['status']}")
    req_str(b, "new_booth_id")
    expected_version = req_int(b, "expected_assignment_version")
    if new_booth is None:
        get_or_404(db.booths, b.get("new_booth_id"), "ERR_BOOTH_NOT_FOUND", "Booth")

    # (9) Cross-festival integrity.
    new_zone = db.zones[new_booth["zone_id"]]
    if new_zone["festival_id"] != assignment["festival_id"]:
        err("ERR_CROSS_FESTIVAL_REFERENCE", 409,
            "New booth belongs to a different festival")

    # (12) Admission checks against the new booth and its zone (excluding self).
    app = db.applications[assignment["application_id"]]
    _admission_checks(app, new_booth, assignment["power_draw_amps"],
                      assignment["requires_water"],
                      exclude_assignment_id=assignment["id"])

    # (13) Optimistic concurrency.
    if expected_version != assignment["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_assignment_version does not match the assignment's version")

    old_booth = db.booths[assignment["booth_id"]]
    old_booth["status"] = "AVAILABLE"
    touch(old_booth)
    new_booth["status"] = "RESERVED"
    touch(new_booth)
    assignment["booth_id"] = new_booth["id"]
    assignment["zone_id"] = new_zone["id"]
    touch(assignment)
    return success(serialize.serialize_assignment(assignment))


@bp.route("/booth-assignments/<assignmentId>/provision-utilities", methods=["POST"])
def provision_utilities(assignmentId):
    require_role("OperationsLead")
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    if assignment["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"provision-utilities requires status CONFIRMED, not {assignment['status']}")
    if assignment["utility_status"] != "PENDING":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"utility_status is already {assignment['utility_status']}")
    # Re-validate the zone budget (the assignment already counts toward it).
    zone = db.zones[assignment["zone_id"]]
    reserved_power, reserved_water = zone_reserved(zone["id"])
    if reserved_power > zone["power_capacity_amps"]:
        err("ERR_POWER_CAPACITY_EXCEEDED", 409,
            "Zone power capacity would be exceeded")
    if assignment["requires_water"] and reserved_water > zone["water_hookup_total"]:
        err("ERR_WATER_CAPACITY_EXCEEDED", 409,
            "Zone water hookup capacity would be exceeded")
    assignment["utility_status"] = "PROVISIONED"
    touch(assignment)
    return success(serialize.serialize_assignment(assignment))


@bp.route("/booth-assignments/<assignmentId>/activate", methods=["POST"])
def activate_assignment(assignmentId):
    require_role("OperationsLead")
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    # (6) Festival posture gate.
    festival = db.festivals[assignment["festival_id"]]
    if festival["status"] != "LIVE":
        err("ERR_FESTIVAL_NOT_LIVE", 409, "Festival is not LIVE")
    # (8) State legality.
    if assignment["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"activate is not permitted from {assignment['status']}")
    if assignment["utility_status"] != "PROVISIONED":
        err("ERR_UTILITIES_NOT_PROVISIONED", 409,
            "Utilities have not been provisioned")
    # (10) Public-safety gate: latest HEALTH_PREOPEN must be PASS.
    preopens = [i for i in db.inspections.values()
                if i["assignment_id"] == assignment["id"]
                and i["type"] == "HEALTH_PREOPEN"]
    latest = max(preopens, key=lambda i: (i["created_at"], i["_seq"]), default=None)
    if latest is None or latest["result"] != "PASS":
        err("ERR_PREOPEN_INSPECTION_MISSING", 409,
            "Latest HEALTH_PREOPEN inspection is not PASS")
    assignment["status"] = "ACTIVE"
    touch(assignment)
    return success(serialize.serialize_assignment(assignment))


@bp.route("/booth-assignments/<assignmentId>/release", methods=["POST"])
def release_assignment_route(assignmentId):
    require_role("OperationsLead")
    assignment = get_or_404(db.assignments, assignmentId,
                            "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    if assignment["status"] not in ("RESERVED", "CONFIRMED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"release is not permitted from {assignment['status']}")
    release_assignment(assignment)
    return success(serialize.serialize_assignment(assignment))


# ---------------------------------------------------------------------------
# Inspection records (immutable events)
# ---------------------------------------------------------------------------

@bp.route("/inspection-records", methods=["POST"])
def create_inspection():
    require_role("HealthInspector")
    b = body_json()
    assignment = None
    if b.get("assignment_id") is not None:
        assignment = get_or_404(db.assignments, b.get("assignment_id"),
                                "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    itype = req_enum(b, "type", INSPECTION_TYPES)
    result = req_enum(b, "result", INSPECTION_RESULTS)
    notes = opt_str(b, "notes")
    if assignment is None:
        get_or_404(db.assignments, b.get("assignment_id"),
                   "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    record = {
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment["id"],
        "festival_id": assignment["festival_id"],
        "type": itype,
        "result": result,
        "notes": notes,
        "status": "COMPLETED",
        "created_at": db.clock,
    }
    db.inspections[record["id"]] = record
    if itype == "HEALTH_SPOT" and result == "FAIL":
        issue_system_fine(assignment["id"], "HEALTH_VIOLATION", 50000,
                          "Health spot inspection failed")
    return success(serialize.serialize_inspection(record), 201)


INSPECTION_READ_ROLES = ("FestivalDirector", "VendorManager", "OperationsLead",
                         "HealthInspector", "FinanceLead", "Vendor")


@bp.route("/inspection-records", methods=["GET"])
def list_inspections():
    require_role(*INSPECTION_READ_ROLES)
    return list_response(list(db.inspections.values()),
                         serialize.serialize_inspection, {
                             "assignment_id": "assignment_id",
                             "festival_id": "festival_id",
                             "type": "type",
                             "result": "result",
                         })


@bp.route("/inspection-records/<inspectionId>", methods=["GET"])
def get_inspection(inspectionId):
    require_role(*INSPECTION_READ_ROLES)
    record = get_or_404(db.inspections, inspectionId,
                        "ERR_INSPECTION_NOT_FOUND", "Inspection record")
    return success(serialize.serialize_inspection(record))
