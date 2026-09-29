"""Exhibitor services, floor-rule citations and lead capture (PRD 3.9)."""
from flask import Blueprint, request

import calc
import guards
import services
import validate
import views
from db import (append_only_row, base_row, by_created, db, fmt_dt, now, parse_date,
                parse_dt, touch)
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination

bp = Blueprint("floor", __name__)

SERVICE_TYPES = ("LABOR", "ELECTRICAL", "MATERIAL_HANDLING")
VIOLATION_TYPES = ("BOOTH_HEIGHT", "NOISE", "AISLE_ENCROACHMENT", "SALES_CONDUCT")


@bp.route("/space-contracts/<contract_id>/service-orders", methods=["POST"])
def create_service_order(contract_id):
    body = validate.body()
    service_type = validate.enum(body, "service_type", SERVICE_TYPES)
    quantity = validate.integer(body, "quantity", minimum=1)
    ordered_at = validate.datetime_field(body, "ordered_at", required=False)

    ctx = authenticate((EXHIBITOR, FLOOR_MANAGER))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, ("SPACE_SELECTION", "SELLING", "ON_SITE"))
    guards.require_contract_status(contract, ("SIGNED",))

    if ordered_at is None:
        ordered_at = now()
    ordered_date = ordered_at.date()
    if ordered_date > parse_date(show["move_out_end"]):
        raise ApiError("ERR_SERVICE_ORDER_WINDOW_CLOSED",
                       "the hall has already been struck for this show")

    venue_contract = db.venue_contracts[show["venue_contract_id"]]
    deadline = show["advance_order_deadline"]
    variant = "FLOOR"
    if deadline is not None and ordered_date <= parse_date(deadline):
        variant = "ADVANCE"
    billable = calc.billable_quantity(service_type, quantity)

    row = base_row()
    row.update({
        "space_contract_id": contract["id"],
        "service_type": service_type,
        "quantity": quantity,
        "billable_quantity": billable,
        "unit_rate_cents": calc.service_unit_rate(venue_contract, service_type),
        "rate_variant": variant,
        "line_total_cents": calc.service_line_total(venue_contract, service_type,
                                                   billable, variant),
        "ordered_at": fmt_dt(ordered_at),
        "status": "SUBMITTED",
    })
    db.service_orders[row["id"]] = row
    return created(views.service_order_view(row))


@bp.route("/space-contracts/<contract_id>/service-orders", methods=["GET"])
def list_service_orders(contract_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    contract = guards.get_contract(contract_id)
    rows = by_created(calc.contract_service_orders(contract["id"]))
    for field in ("status", "service_type"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    return list_response([views.service_order_view(r) for r in rows], limit, offset)


@bp.route("/space-contracts/<contract_id>/rule-violations", methods=["POST"])
def create_violation(contract_id):
    body = validate.body()
    violation_type = validate.enum(body, "violation_type", VIOLATION_TYPES)
    measured_value = validate.number(body, "measured_value", minimum=0, required=False)
    notes = validate.text(body, "notes", 1, 500, required=False)
    if violation_type == "BOOTH_HEIGHT" and measured_value is None:
        validate.bad("measured_value is required for a BOOTH_HEIGHT citation")

    ctx = authenticate((FLOOR_MANAGER, SHOW_DIRECTOR))
    contract = guards.get_contract(contract_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, ("ON_SITE",))
    guards.require_contract_status(contract, ("SIGNED",))

    if violation_type == "BOOTH_HEIGHT":
        booths = services.contract_held_or_assigned_booths(contract)
        limits = [b["max_height_ft"] for b in booths]
        limit_ft = min(limits) if limits else None
        if limit_ft is None or not measured_value > limit_ft:
            raise ApiError("ERR_BOOTH_HEIGHT_LIMIT",
                           "a structure within its permitted height is not a violation")

    row = base_row()
    row.update({
        "space_contract_id": contract["id"],
        "violation_type": violation_type,
        "measured_value": calc.plain(measured_value) if measured_value is not None else None,
        "notes": notes,
        "status": "OPEN",
        "reported_by_user_id": ctx.user_id,
        "adjudicated_by_user_id": None,
        "penalty_points": 0,
        "waiver_reason": None,
    })
    db.rule_violations[row["id"]] = row
    return created(views.rule_violation_view(row))


@bp.route("/space-contracts/<contract_id>/rule-violations", methods=["GET"])
def list_violations(contract_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    contract = guards.get_contract(contract_id)
    rows = by_created(calc.contract_violations(contract["id"]))
    for field in ("status", "violation_type"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    return list_response([views.rule_violation_view(r) for r in rows], limit, offset)


@bp.route("/rule-violations/<violation_id>/adjudicate", methods=["POST"])
def adjudicate_violation(violation_id):
    body = validate.body()
    disposition = validate.enum(body, "disposition", ("UPHELD", "WAIVED"))
    # PRD 3.9 pins the empty-string case to ERR_WAIVER_REASON_REQUIRED, so an
    # empty waiver_reason must not be intercepted as a structural failure.
    waiver_reason = validate.text(body, "waiver_reason", 0, 500, required=False)

    ctx = authenticate((SHOW_DIRECTOR,))
    known = db.rule_violations.get(violation_id)
    if (known is not None and known["reported_by_user_id"] is not None
            and known["reported_by_user_id"] == ctx.user_id):
        raise ApiError("ERR_SOD_VIOLATION_ADJUDICATION",
                       "the operator who wrote the citation may not rule on it")
    violation = guards.get_violation(violation_id)
    guards.require_violation_open(violation)

    if disposition == "WAIVED" and not waiver_reason:
        raise ApiError("ERR_WAIVER_REASON_REQUIRED",
                       "a WAIVED disposition requires a waiver_reason")

    contract = db.space_contracts[violation["space_contract_id"]]
    show = db.shows[contract["show_id"]]
    violation["adjudicated_by_user_id"] = ctx.user_id
    if disposition == "UPHELD":
        violation["status"] = "UPHELD"
        violation["penalty_points"] = calc.PENALTY_POINTS[violation["violation_type"]]
        touch(violation)
        exhibitor = db.exhibitors.get(contract["exhibitor_id"])
        if exhibitor is not None:
            services.add_penalty_points(exhibitor, violation["penalty_points"])
        touch(show)
    else:
        violation["status"] = "WAIVED"
        violation["waiver_reason"] = waiver_reason
        touch(violation)
    return object_response(views.rule_violation_view(violation))


@bp.route("/space-contracts/<contract_id>/lead-scans", methods=["POST"])
def create_lead_scan(contract_id):
    body = validate.body()
    registration_id = validate.text(body, "registration_id", 1, 64)
    scanned_at = validate.datetime_field(body, "scanned_at")

    ctx = authenticate((EXHIBITOR, FLOOR_MANAGER))
    known = db.space_contracts.get(contract_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    contract = guards.get_contract(contract_id)
    registration = guards.get_registration(registration_id)
    show = guards.get_show(contract["show_id"])

    guards.require_show_status(show, ("ON_SITE",))
    guards.require_contract_status(contract, ("SIGNED",))

    if registration["show_id"] != contract["show_id"]:
        raise ApiError("ERR_REGISTRATION_SHOW_MISMATCH",
                       "the badge belongs to a different show")
    for scan in db.lead_scans.values():
        if (scan["space_contract_id"] == contract["id"]
                and scan["registration_id"] == registration["id"]):
            raise ApiError("ERR_DUPLICATE_LEAD_SCAN",
                           "this badge has already been scanned by this exhibitor")
    scanned_date = scanned_at.date()
    if (scanned_date < parse_date(show["move_in_start"])
            or scanned_date > parse_date(show["move_out_end"])):
        raise ApiError("ERR_LEAD_SCAN_OUTSIDE_SHOW_WINDOW",
                       "the scan falls outside the show's occupancy window")

    row = append_only_row()
    row.update({
        "space_contract_id": contract["id"],
        "registration_id": registration["id"],
        "scanned_at": fmt_dt(scanned_at),
    })
    db.lead_scans[row["id"]] = row
    touch(registration)
    return created(views.lead_scan_view(row))


@bp.route("/space-contracts/<contract_id>/lead-scans", methods=["GET"])
def list_contract_lead_scans(contract_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    contract = guards.get_contract(contract_id)
    rows = by_created(calc.contract_scans(contract["id"]))
    return list_response([views.lead_scan_view(r) for r in rows], limit, offset)


@bp.route("/registrations/<registration_id>/lead-scans", methods=["GET"])
def list_registration_lead_scans(registration_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER))
    registration = guards.get_registration(registration_id)
    rows = by_created(calc.registration_scans(registration["id"]))
    return list_response([views.lead_scan_view(r) for r in rows], limit, offset)
