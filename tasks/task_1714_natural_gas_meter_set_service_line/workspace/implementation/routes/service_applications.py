"""ServiceApplication endpoints: CRUD, spine transitions, hold axis, readiness."""

from flask import Blueprint, request

import db
from errors import (
    ERR_BUILDER_SUSPENDED,
    ERR_CIAC_UNPAID,
    ERR_FORBIDDEN_OWNER,
    ERR_GIS_NOT_VALIDATED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_METER_NOT_READY,
    ERR_NO_APPLIANCE_LOADS,
    ERR_NO_CONFIRMED_BOOKING,
    ERR_PERMIT_NOT_APPROVED,
    ERR_STALE_VERSION,
    ERR_TURN_ON_INCOMPLETE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    check_app_not_held,
    check_app_not_terminal,
    get_body,
    new_id,
    paginate,
    require_fields,
    require_roles,
    spine_at_least,
)
from response import success_list, success_object
from services.calculations import delay_penalty_credit, load_calculation
from services.domain import (
    bookings_for_application,
    cancel_application_cascade,
    commitment_for_application,
    get_application,
    get_builder,
    gis_for_application,
    invoice_for_application,
    loads_for_application,
    main_extension_for_application,
    meter_set_for_application,
    permits_for_application,
    touch,
    turn_ons_for_application,
)

bp = Blueprint("service_applications", __name__)

PATCHABLE_FIELDS = ("service_address", "city", "state_code", "postal_code", "requested_in_service_date")


def _check_builder_ownership(user_id, app):
    if app["builder_id"] != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Builder does not own this application")


@bp.route("/service-applications", methods=["POST"])
def create_application():
    user_id, _ = require_roles("Builder")
    body = get_body()
    require_fields(
        body,
        "builder_id",
        "service_address",
        "city",
        "state_code",
        "postal_code",
        "requested_in_service_date",
    )
    builder_id = body["builder_id"]
    if not isinstance(builder_id, str):
        raise_error(ERR_INVALID_REQUEST, "builder_id must be a string")
    # Ownership: a Builder creates applications naming its own builder_id
    if builder_id != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Builder can only create applications for itself")
    builder = get_builder(builder_id)
    if builder["status"] != "ACTIVE":
        raise_error(ERR_BUILDER_SUSPENDED, "Suspended builders cannot create applications")
    pressure = body.get("pressure_class_requested", "LOW")
    if pressure not in ("LOW", "MEDIUM"):
        raise_error(ERR_INVALID_REQUEST, "pressure_class_requested must be LOW or MEDIUM")
    now = db.now_iso()
    app = {
        "id": new_id(),
        "builder_id": builder_id,
        "service_address": body["service_address"],
        "city": body["city"],
        "state_code": body["state_code"],
        "postal_code": body["postal_code"],
        "pressure_class_requested": pressure,
        "requested_in_service_date": body["requested_in_service_date"],
        "status": "DRAFT",
        "hold_status": "NOT_HELD",
        "hold_reason": None,
        "appliance_count": 0,
        "total_connected_load_cfph": 0.0,
        "diversity_adjusted_load_cfph": 0.0,
        "quote_valid_until": None,
        "submitted_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.service_applications[app["id"]] = app
    return success_object(app, 201)


@bp.route("/service-applications/<aid>", methods=["GET"])
def get_one_application(aid):
    require_roles(*ANY_ROLE)
    return success_object(get_application(aid))


@bp.route("/service-applications", methods=["GET"])
def list_applications():
    require_roles(*ANY_ROLE)
    records = list(db.service_applications.values())
    builder_id = request.args.get("builder_id")
    status = request.args.get("status")
    if builder_id is not None:
        records = [a for a in records if a["builder_id"] == builder_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/service-applications/<aid>", methods=["PATCH"])
def patch_application(aid):
    user_id, _ = require_roles("Builder")
    app = get_application(aid)
    _check_builder_ownership(user_id, app)
    body = get_body()
    require_fields(body, "expected_application_version")
    if body["expected_application_version"] != app["version"]:
        raise_error(ERR_STALE_VERSION, "Application version is stale")
    check_app_mutable(app)
    if app["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Only DRAFT applications may be edited")
    for f in PATCHABLE_FIELDS:
        if f in body:
            app[f] = body[f]
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    user_id, _ = require_roles("Builder")
    app = get_application(aid)
    _check_builder_ownership(user_id, app)
    check_app_mutable(app)
    if app["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Only DRAFT applications can be submitted")
    builder = get_builder(app["builder_id"])
    if builder["status"] != "ACTIVE":
        raise_error(ERR_BUILDER_SUSPENDED, "Suspended builders cannot submit applications")
    loads = loads_for_application(aid)
    if len(loads) < 1:
        raise_error(ERR_NO_APPLIANCE_LOADS, "At least one appliance load is required to submit")
    n, total_connected, diversity_adjusted = load_calculation(loads)
    app["appliance_count"] = n
    app["total_connected_load_cfph"] = total_connected
    app["diversity_adjusted_load_cfph"] = diversity_adjusted
    app["status"] = "SUBMITTED"
    app["submitted_at"] = db.now_iso()
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/confirm-load", methods=["POST"])
def confirm_load(aid):
    require_roles("NewBusinessRep")
    app = get_application(aid)
    check_app_mutable(app)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only SUBMITTED applications can be load-confirmed")
    app["status"] = "LOAD_CONFIRMED"
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    require_roles("NewBusinessRep")
    app = get_application(aid)
    check_app_mutable(app)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Only SUBMITTED applications can be rejected")
    app["status"] = "REJECTED"
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/schedule-construction", methods=["POST"])
def schedule_construction(aid):
    require_roles("FieldSupervisor")
    app = get_application(aid)
    check_app_mutable(app)
    if app["status"] not in ("APPROVED_FOR_CONSTRUCTION", "PERMITTING"):
        raise_error(ERR_INVALID_STATE, "Application is not ready for construction scheduling")
    # Referential gates (priority 11) before fiscal gates (priority 12)
    permits = permits_for_application(aid)
    for p in permits:
        if p["status"] not in ("APPROVED", "CLOSED"):
            raise_error(ERR_PERMIT_NOT_APPROVED, "Every permit must be APPROVED or CLOSED")
    me = main_extension_for_application(aid)
    if me is not None and me.get("crossings_count", 0) > 0:
        road_cut_ok = any(
            p["permit_type"] == "ROAD_CUT" and p["status"] in ("APPROVED", "CLOSED") for p in permits
        )
        if not road_cut_ok:
            raise_error(ERR_PERMIT_NOT_APPROVED, "An APPROVED/CLOSED ROAD_CUT permit is required")
    bookings = bookings_for_application(aid)
    if not any(b["status"] == "CONFIRMED" for b in bookings):
        raise_error(ERR_NO_CONFIRMED_BOOKING, "At least one CONFIRMED crew booking is required")
    invoice = invoice_for_application(aid)
    if invoice is None or invoice["status"] != "PAID":
        raise_error(ERR_CIAC_UNPAID, "CIAC invoice must be PAID before scheduling construction")
    app["status"] = "CONSTRUCTION_SCHEDULED"
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/energize", methods=["POST"])
def energize(aid):
    require_roles("MeterTechnician")
    app = get_application(aid)
    check_app_mutable(app)
    if app["status"] != "TURN_ON":
        raise_error(ERR_INVALID_STATE, "Application is not in TURN_ON")
    ms = meter_set_for_application(aid)
    if ms is None or ms["status"] != "READY_FOR_TURN_ON":
        raise_error(ERR_METER_NOT_READY, "Meter set is not READY_FOR_TURN_ON")
    loads = loads_for_application(aid)
    turn_ons = turn_ons_for_application(aid)
    for load in loads:
        if not any(t["appliance_load_id"] == load["id"] and t["status"] == "VERIFIED" for t in turn_ons):
            raise_error(ERR_TURN_ON_INCOMPLETE, "Every appliance load needs a VERIFIED turn-on event")
    ms["status"] = "ENERGIZED"
    touch(ms)
    app["status"] = "ENERGIZED"
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/complete", methods=["POST"])
def complete_application(aid):
    require_roles("NewBusinessRep")
    app = get_application(aid)
    check_app_mutable(app)
    if app["status"] not in ("ENERGIZED", "GIS_REVIEW"):
        raise_error(ERR_INVALID_STATE, "Application is not ready to complete")
    # Referential gates (11) then fiscal (12); ERR_INVALID_STATE for non-finalized main extension
    gis = gis_for_application(aid)
    if gis is None or gis["status"] != "VALIDATED":
        raise_error(ERR_GIS_NOT_VALIDATED, "A VALIDATED GIS as-built is required")
    me = main_extension_for_application(aid)
    if me is None or me["status"] != "FINALIZED":
        raise_error(ERR_INVALID_STATE, "Main extension must be FINALIZED")
    invoice = invoice_for_application(aid)
    if invoice is None or invoice["status"] not in ("SETTLED", "REFUNDED"):
        raise_error(ERR_CIAC_UNPAID, "CIAC invoice must be SETTLED or REFUNDED")
    app["completed_at"] = db.now_iso()
    app["status"] = "COMPLETED"
    touch(app)
    # Resolve timeline commitment: MET or MISSED (+ penalty credit computed at completion)
    commitment = commitment_for_application(aid)
    if commitment is not None and commitment["status"] != "CANCELLED":
        completed_date = db.today_date()
        committed_date_str = commitment["committed_completion_date"]
        import datetime as _dt
        committed_date = _dt.date.fromisoformat(committed_date_str)
        if commitment["status"] not in ("MET", "MISSED"):
            if completed_date <= committed_date:
                commitment["status"] = "MET"
            else:
                commitment["status"] = "MISSED"
                if not commitment.get("delay_attribution"):
                    commitment["delay_attribution"] = "UTILITY"
        # The penalty credit is computed at application completion (§3.7) — including
        # for commitments the clock sweep already moved to MISSED.
        if commitment["status"] == "MISSED":
            commitment["penalty_credit_cents"] = delay_penalty_credit(
                committed_date_str, completed_date, commitment["delay_attribution"]
            )
        touch(commitment)
    return success_object(app)


@bp.route("/service-applications/<aid>/hold", methods=["POST"])
def hold_application(aid):
    user_id, role = require_roles("Builder", "NewBusinessRep", "FieldSupervisor")
    app = get_application(aid)
    if role == "Builder":
        _check_builder_ownership(user_id, app)
    check_app_not_terminal(app)
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason must be a string")
    app["hold_status"] = "HELD_BY_BUILDER" if role == "Builder" else "HELD_BY_UTILITY"
    app["hold_reason"] = reason
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/resume", methods=["POST"])
def resume_application(aid):
    user_id, role = require_roles("Builder", "NewBusinessRep", "FieldSupervisor")
    app = get_application(aid)
    if role == "Builder":
        _check_builder_ownership(user_id, app)
    check_app_not_terminal(app)
    app["hold_status"] = "NOT_HELD"
    app["hold_reason"] = None
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/cancel", methods=["POST"])
def cancel_application(aid):
    user_id, role = require_roles("Builder", "NewBusinessRep")
    app = get_application(aid)
    if role == "Builder":
        _check_builder_ownership(user_id, app)
    check_app_not_terminal(app)
    cancel_application_cascade(app)
    app["status"] = "CANCELLED"
    touch(app)
    return success_object(app)


@bp.route("/service-applications/<aid>/readiness", methods=["GET"])
def readiness(aid):
    require_roles(*ANY_ROLE)
    app = get_application(aid)
    invoice = invoice_for_application(aid)
    unpaid_ciac = invoice["balance_due_cents"] if invoice is not None else 0
    if invoice is not None and invoice["status"] in ("SETTLED", "REFUNDED", "VOID"):
        unpaid_ciac = 0
    permits = permits_for_application(aid)
    open_permits = [p for p in permits if p["status"] not in ("APPROVED", "CLOSED")]
    bookings = bookings_for_application(aid)
    confirmed_count = sum(1 for b in bookings if b["status"] == "CONFIRMED")
    turn_ons = turn_ons_for_application(aid)
    verified_count = sum(1 for t in turn_ons if t["status"] == "VERIFIED")
    loads = loads_for_application(aid)
    gis = gis_for_application(aid)
    gis_validated = gis is not None and gis["status"] == "VALIDATED"
    me = main_extension_for_application(aid)
    ms = meter_set_for_application(aid)

    blockers = []
    if app["hold_status"] != "NOT_HELD":
        blockers.append("ON_HOLD")
    if invoice is None or invoice["status"] != "PAID":
        # CIAC unpaid unless the invoice is fully settled/paid
        if invoice is None or invoice["status"] not in ("PAID", "SETTLED", "REFUNDED", "VOID"):
            blockers.append("CIAC_UNPAID")
    if open_permits:
        blockers.append("PERMIT_NOT_APPROVED")
    if me is not None and me.get("crossings_count", 0) > 0:
        if not any(p["permit_type"] == "ROAD_CUT" and p["status"] in ("APPROVED", "CLOSED") for p in permits):
            if "PERMIT_NOT_APPROVED" not in blockers:
                blockers.append("PERMIT_NOT_APPROVED")
    if confirmed_count == 0:
        blockers.append("NO_CONFIRMED_BOOKING")
    if ms is None or ms["status"] != "READY_FOR_TURN_ON":
        blockers.append("METER_NOT_READY")
    for load in loads:
        if not any(t["appliance_load_id"] == load["id"] and t["status"] == "VERIFIED" for t in turn_ons):
            blockers.append("TURN_ON_INCOMPLETE")
            break
    if not gis_validated:
        blockers.append("GIS_NOT_VALIDATED")

    posture = "BLOCKED" if blockers else "READY"
    data = {
        "readiness_posture": posture,
        "blockers": blockers,
        "unpaid_ciac_cents": unpaid_ciac,
        "open_permit_count": len(open_permits),
        "confirmed_booking_count": confirmed_count,
        "verified_turn_on_count": verified_count,
        "active_load_count": len(loads),
        "gis_validated": gis_validated,
    }
    return success_object(data)
