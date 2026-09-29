"""Opening inspections, recording attempts, reconditioning and closing (PRD 3.3-3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("inspections", __name__)

READ_ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "InspectionTechnician",
)
OPEN_STATUSES = ("DRAFT", "IN_PROGRESS", "RECONDITIONING_REQUIRED")
TERMINAL_STATUSES = ("PASSED", "FAILED", "VOIDED")


def inspection_or_404(inspection_id):
    row = db.inspections.get(inspection_id)
    if row is None:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", "No inspection with that id.")
    return row


def recon_item_or_404(item_id):
    row = db.recon_items.get(item_id)
    if row is None:
        raise ApiError(
            "ERR_RECONDITIONING_ITEM_NOT_FOUND", "No reconditioning item with that id."
        )
    return row


def check_credential(technician):
    if technician["credential_status"] != "ACTIVE" or not (
        technician["credential_expires_at"] > db.clock
    ):
        raise ApiError(
            "ERR_TECHNICIAN_CREDENTIAL_EXPIRED",
            "The technician's inspector credential is not currently valid.",
        )


# --------------------------------------------------------------------------- #
# POST /cpo/inspections
# --------------------------------------------------------------------------- #
@bp.route("/inspections", methods=["POST"])
def open_inspection():
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    config = cfg()
    body = h.body_dict()
    vehicle_id = h.f_string(body, "vehicle_id")
    technician_id = h.f_string(body, "technician_id")
    template_id = h.f_string(body, "template_id")
    started_at = h.f_instant(body, "started_at")
    odometer = h.f_int(body, "odometer_at_inspection", minimum=0)
    parent_id = h.f_string(body, "parent_inspection_id", required=False)
    complaint_id = h.f_string(body, "complaint_id", required=False)

    # rung 6 — body foreign keys
    vehicle = db.vehicles.get(vehicle_id)
    technician = db.technicians.get(technician_id)
    template = db.templates.get(template_id)
    parent = db.inspections.get(parent_id) if parent_id else None
    complaint = db.complaints.get(complaint_id) if complaint_id else None
    if (
        vehicle is None
        or technician is None
        or template is None
        or (parent_id and parent is None)
        or (complaint_id and complaint is None)
    ):
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND",
            "A foreign key supplied in the request body does not resolve.",
        )

    # rung 7 — dealer scope
    complaint_cert = (
        db.certifications.get(complaint["certification_id"]) if complaint else None
    )
    if technician["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION", "That technician belongs to another dealership."
        )
    if parent is not None and parent["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That parent inspection belongs to another dealership.",
        )
    if complaint_cert is not None and complaint_cert["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That complaint concerns another dealership's certification.",
        )

    if complaint is not None and complaint_cert is not None:
        if complaint_cert["vehicle_id"] != vehicle_id:
            h.bad_request(
                "vehicle_id must name the vehicle of the complained-about certification."
            )

    # rung 8 — state legality
    if vehicle["inventory_state"] != "IN_INVENTORY":
        raise ApiError(
            "ERR_VEHICLE_NOT_IN_INVENTORY",
            "The programme only inspects cars the dealer still holds.",
        )
    if template["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_TEMPLATE_NOT_PUBLISHED",
            "An inspection may only name a PUBLISHED checklist template.",
        )
    if complaint is not None and complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_NOT_OPEN", "That complaint is no longer OPEN.")

    # rungs 10-13 — eligibility screens
    if vehicle["title_brand"] in (config["ineligible_title_brands"] or []):
        raise ApiError(
            "ERR_BRANDED_TITLE_INELIGIBLE",
            "A branded car is permanently outside the programme.",
        )
    if vehicle["prior_use"] in (config["ineligible_prior_uses"] or []):
        raise ApiError(
            "ERR_PRIOR_USE_INELIGIBLE", "That prior use excludes the car from the programme."
        )
    age_days = calc.whole_days(vehicle["in_service_date"], started_at.date())
    if age_days > config["max_age_days"]:
        raise ApiError("ERR_VEHICLE_AGE_EXCEEDED", "The car exceeds the programme age ceiling.")
    if odometer > config["max_odometer_miles"] or odometer < vehicle["odometer_miles"]:
        raise ApiError(
            "ERR_MILEAGE_LIMIT_EXCEEDED",
            "odometer_at_inspection is outside the accepted range.",
        )

    # rung 14 — privilege
    if dealer["privilege_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_DEALER_PRIVILEGE_SUSPENDED", "The dealer's certifying privilege is suspended."
        )

    # rung 15 — one live inspection per vehicle
    for other in db.inspections.values():
        if other["vehicle_id"] != vehicle_id or other["status"] not in OPEN_STATUSES:
            continue
        if parent is not None and other["id"] == parent["id"]:
            continue
        raise ApiError(
            "ERR_INSPECTION_ALREADY_OPEN",
            "Another inspection of this vehicle is still open.",
        )

    # rung 16 — segregation of duties on a complaint re-inspection
    if complaint_cert is not None:
        backing = db.inspections.get(complaint_cert["inspection_id"])
        if backing is not None and backing["technician_id"] == technician_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "A complaint re-inspection needs a fresh pair of eyes.",
            )

    # rung 26 — worksheet not future-dated
    if started_at > db.clock:
        raise ApiError(
            "ERR_INSPECTION_DATE_IN_FUTURE", "started_at may not be after the logical clock."
        )

    # rung 27 — credential validity
    check_credential(technician)

    # rung 28 — technician calendar
    slot_minutes = config["inspection_slot_minutes"]
    buffer_minutes = config["technician_buffer_minutes"]
    candidate = calc.buffered_slot(started_at, slot_minutes, buffer_minutes)
    for other in db.inspections.values():
        if other["technician_id"] != technician_id or other["status"] == "VOIDED":
            continue
        occupied = calc.buffered_slot(other["started_at"], slot_minutes, buffer_minutes)
        if calc.slot_conflicts(candidate, occupied):
            raise ApiError(
                "ERR_TECHNICIAN_SLOT_CONFLICT",
                "The technician's buffered calendar slot is already occupied.",
            )

    # rung 29 — re-inspection deadline
    if complaint is not None and db.clock > complaint["reinspection_deadline_at"]:
        raise ApiError(
            "ERR_REINSPECTION_DEADLINE_PASSED",
            "The complaint's re-inspection deadline has passed.",
        )

    row = h.new_common(
        {
            "id": new_id(),
            "vehicle_id": vehicle_id,
            "dealer_id": dealer["id"],
            "technician_id": technician_id,
            "template_id": template_id,
            "parent_inspection_id": parent_id,
            "complaint_id": complaint_id,
            "purpose": "RE_INSPECTION" if (parent_id or complaint_id) else "INITIAL",
            "status": "DRAFT",
            "started_at": started_at,
            "slot_end_at": started_at + timedelta(minutes=slot_minutes),
            "odometer_at_inspection": odometer,
            "vehicle_age_days_at_inspection": age_days,
            "attempt_count": 0,
            "recorded_item_count": 0,
            "failed_critical_count": 0,
            "failed_recon_count": 0,
            "total_recon_cost_cents": 0,
            "total_reimbursable_cents": 0,
            "submitted_at": None,
            "failure_reason": None,
        }
    )
    db.inspections[row["id"]] = row

    if vehicle["cpo_state"] in ("NOT_CERTIFIED", "DECERTIFIED"):
        vehicle["cpo_state"] = "CERTIFICATION_PENDING"
        h.touch(vehicle)

    # 3.5: the named parent moves to VOIDED *from* DRAFT, IN_PROGRESS or
    # RECONDITIONING_REQUIRED. A parent already out of play is a hop that does
    # not apply, and 2.7 skips such a hop without failing the request.
    if parent is not None and parent["status"] in OPEN_STATUSES:
        parent["status"] = "VOIDED"
        parent["failure_reason"] = "SUPERSEDED_BY_REINSPECTION"
        h.touch(parent)

    if complaint is not None:
        complaint["status"] = "REINSPECTION_ORDERED"
        complaint["reinspection_ordered_at"] = db.clock
        h.touch(complaint)

    return h.object_response(ser.inspection(row), 201)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    h.authorize(READ_ROLES)
    filters = {
        "vehicle_id": h.q_string("vehicle_id"),
        "dealer_id": h.q_string("dealer_id"),
        "technician_id": h.q_string("technician_id"),
        "template_id": h.q_string("template_id"),
        "parent_inspection_id": h.q_string("parent_inspection_id"),
        "complaint_id": h.q_string("complaint_id"),
        "status": h.q_enum("status", enums.INSPECTION_STATUSES),
        "purpose": h.q_enum("purpose", enums.INSPECTION_PURPOSES),
    }
    limit, offset = h.pagination()
    rows = list(db.inspections.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return h.paged(rows, limit, offset, ser.inspection)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    inspection = inspection_or_404(inspection_id)
    h.require_dealer_scope(user_id, role, inspection["dealer_id"])
    return h.object_response(ser.inspection(inspection))


# --------------------------------------------------------------------------- #
# PUT /cpo/inspections/{id}/results
# --------------------------------------------------------------------------- #
@bp.route("/inspections/<inspection_id>/results", methods=["PUT"])
def record_results(inspection_id):
    user_id, _role, technician = h.authorize(("InspectionTechnician",))
    body = h.body_dict()
    results = h.f_list(body, "results", non_empty=True)
    parsed = []
    for entry in results:
        if not isinstance(entry, dict):
            h.bad_request("Each results entry must be an object.")
        parsed.append(
            {
                "item_code": h.f_string(entry, "item_code"),
                "outcome": h.f_enum(entry, "outcome", enums.OUTCOMES),
                "measured_value": h.f_number(entry, "measured_value", required=False),
            }
        )

    inspection = inspection_or_404(inspection_id)

    if (
        technician["dealer_id"] != inspection["dealer_id"]
        or user_id != inspection["technician_id"]
    ):
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "Only the inspection's own technician may record its outcomes.",
        )

    if inspection["status"] in TERMINAL_STATUSES:
        raise ApiError(
            "ERR_INSPECTION_TERMINAL", "This inspection has already reached a verdict."
        )

    # rung 17 — item resolution
    points = {}
    for entry in parsed:
        point = cas.template_item(inspection["template_id"], entry["item_code"])
        if point is None:
            raise ApiError(
                "ERR_UNKNOWN_CHECKLIST_ITEM",
                "item_code %s is not a point of this inspection's template."
                % entry["item_code"],
            )
        points[entry["item_code"]] = point

    # rung 18 — measurement consistency
    for entry in parsed:
        point = points[entry["item_code"]]
        measured = point["min_measure"] is not None or point["max_measure"] is not None
        if not measured:
            entry["measured_value"] = None
            continue
        value = entry["measured_value"]
        if value is None:
            raise ApiError(
                "ERR_MEASUREMENT_CONTRADICTS_OUTCOME",
                "A measured point requires a measured_value.",
            )
        inside = True
        if point["min_measure"] is not None and value < point["min_measure"]:
            inside = False
        if point["max_measure"] is not None and value > point["max_measure"]:
            inside = False
        if entry["outcome"] == "PASS" and not inside:
            raise ApiError(
                "ERR_MEASUREMENT_CONTRADICTS_OUTCOME",
                "A PASS requires a reading inside the declared band.",
            )
        if entry["outcome"] == "FAIL" and inside:
            raise ApiError(
                "ERR_MEASUREMENT_CONTRADICTS_OUTCOME",
                "A FAIL requires a reading outside the declared band.",
            )

    # rung 27 — credential re-checked at every recording
    check_credential(technician)

    attempt_index = inspection["attempt_count"] + 1
    inspection["attempt_count"] = attempt_index
    for entry in parsed:
        row = h.new_evidence(
            {
                "id": new_id(),
                "inspection_id": inspection_id,
                "item_code": entry["item_code"],
                "outcome": entry["outcome"],
                "measured_value": entry["measured_value"],
                "attempt_index": attempt_index,
                "recorded_by_technician_id": user_id,
                "recorded_at": db.clock,
            }
        )
        db.inspection_results[row["id"]] = row

    inspection["status"] = "IN_PROGRESS"
    _recompute_attempt_counters(inspection)
    h.touch(inspection)
    return h.object_response(ser.inspection(inspection))


def _recompute_attempt_counters(inspection):
    rows = cas.attempt_results(inspection["id"], inspection["attempt_count"])
    inspection["recorded_item_count"] = len(set(r["item_code"] for r in rows))
    critical = 0
    reconable = 0
    for row in rows:
        if row["outcome"] != "FAIL":
            continue
        point = cas.template_item(inspection["template_id"], row["item_code"])
        if point is None:
            continue
        if point["severity"] == "CRITICAL":
            critical += 1
        if point["reconditioning_allowed"]:
            reconable += 1
    inspection["failed_critical_count"] = critical
    inspection["failed_recon_count"] = reconable


@bp.route("/inspections/<inspection_id>/results", methods=["GET"])
def list_results(inspection_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    attempt_index = h.q_int("attempt_index", None, 1, None)
    outcome = h.q_enum("outcome", enums.OUTCOMES)
    item_code = h.q_string("item_code")
    limit, offset = h.pagination()
    h.require_dealer_scope(user_id, role, inspection_or_404(inspection_id)["dealer_id"])
    rows = [
        r for r in db.inspection_results.values() if r["inspection_id"] == inspection_id
    ]
    if attempt_index is not None:
        rows = [r for r in rows if r["attempt_index"] == attempt_index]
    if outcome:
        rows = [r for r in rows if r["outcome"] == outcome]
    if item_code:
        rows = [r for r in rows if r["item_code"] == item_code]
    return h.paged(rows, limit, offset, ser.inspection_result)


@bp.route("/inspections/<inspection_id>/reconditioning-items", methods=["GET"])
def list_recon_items(inspection_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    status = h.q_enum("status", enums.RECON_STATUSES)
    severity = h.q_enum("severity", enums.SEVERITIES)
    limit, offset = h.pagination()
    h.require_dealer_scope(user_id, role, inspection_or_404(inspection_id)["dealer_id"])
    rows = cas.inspection_recon_items(inspection_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    return h.paged(rows, limit, offset, ser.reconditioning_item)


# --------------------------------------------------------------------------- #
# POST /cpo/reconditioning-items/{id}/complete
# --------------------------------------------------------------------------- #
@bp.route("/reconditioning-items/<item_id>/complete", methods=["POST"])
def close_recon_item(item_id):
    user_id, role = h.auth_headers()
    h.check_role(role, ("InspectionTechnician", "ProgramAdministrator"))

    body = h.body_dict()
    raw_resolution = body.get("resolution")
    # rung 2 — variant-scoped exclusivity, checked before identity resolution.
    if raw_resolution == "COMPLETED" and role != "InspectionTechnician":
        raise ApiError(
            "ERR_ROLE_FORBIDDEN", "Resolution COMPLETED is InspectionTechnician-exclusive."
        )
    if raw_resolution == "WAIVED" and role != "ProgramAdministrator":
        raise ApiError(
            "ERR_ROLE_FORBIDDEN", "Resolution WAIVED is ProgramAdministrator-exclusive."
        )

    principal = h.resolve_identity(user_id, role)

    resolution = h.f_enum(body, "resolution", enums.RECON_RESOLUTIONS)
    actual_cost = h.f_int(body, "actual_cost_cents", required=False, minimum=0)
    waiver_reason = h.f_string(body, "waiver_reason", required=False)
    if resolution == "COMPLETED" and actual_cost is None:
        h.bad_request("Resolution COMPLETED requires actual_cost_cents.")
    if resolution == "WAIVED" and waiver_reason is None:
        h.bad_request("Resolution WAIVED requires a waiver_reason.")

    item = recon_item_or_404(item_id)
    inspection = db.inspections.get(item["inspection_id"])

    # rung 7 — an acting technician must be employed by the inspection's dealer
    if role == "InspectionTechnician":
        if inspection is None or principal["dealer_id"] != inspection["dealer_id"]:
            raise ApiError(
                "ERR_DEALER_SCOPE_VIOLATION",
                "That reconditioning item belongs to another dealership.",
            )

    # rung 8 — state legality
    if item["status"] != "REQUIRED":
        raise ApiError(
            "ERR_RECONDITIONING_ITEM_CLOSED", "That reconditioning item is already closed."
        )
    if inspection is None or inspection["status"] not in (
        "RECONDITIONING_REQUIRED",
        "IN_PROGRESS",
    ):
        raise ApiError(
            "ERR_INSPECTION_TERMINAL",
            "Repairs on a terminal inspection are unreachable.",
        )

    point = cas.template_item(inspection["template_id"], item["item_code"])

    # rung 16 — segregation of duties on the completion path
    if resolution == "COMPLETED" and user_id == inspection["technician_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The technician who recorded the failure may not sign off its repair.",
        )

    # rung 34 — per-item cost ceiling
    if resolution == "COMPLETED":
        ceiling = point["max_reconditioning_cost_cents"] if point else None
        if ceiling is not None and actual_cost > ceiling:
            raise ApiError(
                "ERR_RECONDITIONING_COST_EXCEEDS_CAP",
                "actual_cost_cents exceeds the point's reimbursable ceiling.",
            )

    # rung 35 — a CRITICAL repair may never be excused
    if resolution == "WAIVED" and item["severity"] == "CRITICAL":
        raise ApiError(
            "ERR_CRITICAL_RECONDITIONING_NOT_WAIVABLE",
            "A CRITICAL repair must be performed and costed, never waived.",
        )

    config = cfg()
    if resolution == "COMPLETED":
        item["status"] = "COMPLETED"
        item["actual_cost_cents"] = actual_cost
        share = calc.half_up_mul(actual_cost, config["recon_reimbursement_share"])
        ceiling = point["max_reconditioning_cost_cents"] if point else share
        item["reimbursable_cents"] = min(share, ceiling)
    else:
        item["status"] = "WAIVED"
        item["actual_cost_cents"] = None
        item["reimbursable_cents"] = 0
        item["waiver_reason"] = waiver_reason
    item["completed_at"] = db.clock
    item["closed_by_user_id"] = user_id
    h.touch(item)

    cas.recompute_inspection_money(inspection)
    h.touch(inspection)
    return h.object_response(ser.reconditioning_item(item))


# --------------------------------------------------------------------------- #
# POST /cpo/inspections/{id}/submit
# --------------------------------------------------------------------------- #
@bp.route("/inspections/<inspection_id>/submit", methods=["POST"])
def submit_inspection(inspection_id):
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    inspection = inspection_or_404(inspection_id)
    if inspection["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION", "That inspection belongs to another dealership."
        )
    if inspection["status"] in TERMINAL_STATUSES:
        raise ApiError(
            "ERR_INSPECTION_TERMINAL", "This inspection has already reached a verdict."
        )

    point_count = len(cas.template_items_of(inspection["template_id"]))
    if inspection["recorded_item_count"] != point_count:
        raise ApiError(
            "ERR_INCOMPLETE_CHECKLIST",
            "The current attempt does not cover the whole checklist.",
        )

    rows = cas.attempt_results(inspection_id, inspection["attempt_count"])
    failed_points = []
    critical_uncurable = False
    other_uncurable = False
    for row in rows:
        if row["outcome"] != "FAIL":
            continue
        point = cas.template_item(inspection["template_id"], row["item_code"])
        if point is None:
            continue
        if point["reconditioning_allowed"]:
            failed_points.append(point)
        elif point["severity"] == "CRITICAL":
            critical_uncurable = True
        else:
            other_uncurable = True

    vehicle = db.vehicles.get(inspection["vehicle_id"])

    # A failure that may not be cured by repair ends the inspection; the
    # declared branch order tries reconditioning before the residual case.
    if critical_uncurable or (other_uncurable and not failed_points):
        inspection["status"] = "FAILED"
        inspection["failure_reason"] = "CRITICAL_ITEM_FAIL"
        inspection["submitted_at"] = db.clock
        h.touch(inspection)
        if vehicle is not None and vehicle["cpo_state"] == "CERTIFICATION_PENDING":
            vehicle["cpo_state"] = "NOT_CERTIFIED"
            h.touch(vehicle)
        _resolve_complaint_on_failure(inspection)
        return h.object_response(ser.inspection(inspection))

    if failed_points:
        inspection["status"] = "RECONDITIONING_REQUIRED"
        cas.generate_reconditioning_items(inspection, failed_points)
        cas.recompute_inspection_money(inspection)
        h.touch(inspection)
        return h.object_response(ser.inspection(inspection))

    # clean attempt — rung 20
    for item in cas.inspection_recon_items(inspection_id):
        if item["status"] == "REQUIRED":
            raise ApiError(
                "ERR_RECONDITIONING_INCOMPLETE",
                "A repair is still outstanding on this inspection.",
            )

    inspection["status"] = "PASSED"
    inspection["submitted_at"] = db.clock
    cas.recompute_inspection_money(inspection)
    h.touch(inspection)
    _resolve_complaint_on_pass(inspection)
    return h.object_response(ser.inspection(inspection))


def _resolve_complaint_on_pass(inspection):
    complaint = db.complaints.get(inspection["complaint_id"] or "")
    if complaint is None or complaint["status"] != "REINSPECTION_ORDERED":
        return
    complaint["status"] = "RESOLVED_UPHELD"
    complaint["resolved_at"] = db.clock
    h.touch(complaint)


def _resolve_complaint_on_failure(inspection):
    complaint = db.complaints.get(inspection["complaint_id"] or "")
    if complaint is None or complaint["status"] != "REINSPECTION_ORDERED":
        return
    complaint["status"] = "RESOLVED_DECERTIFIED"
    complaint["resolved_at"] = db.clock
    h.touch(complaint)
    certification = db.certifications.get(complaint["certification_id"])
    if certification is not None and certification["status"] in ("ACTIVE", "UNDER_AUDIT"):
        cas.decertify_certification(
            certification, "COMPLAINT_REINSPECTION_FAIL", skip_complaint_id=complaint["id"]
        )
