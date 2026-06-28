"""Job-visit endpoints: fetch, list, depart, start-work, finish, abort."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, parse_pagination, paginate
from services import models, validate, calc

bp = Blueprint("job_visits", __name__)


def _sorted(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def _get_visit(vid):
    v = db.store.job_visits.get(vid)
    if v is None:
        raise errors.not_found("Job visit not found.")
    return v


def _check_mechanic_owner(uid, role, visit):
    if role == "Mechanic" and uid != visit["mechanic_id"]:
        raise errors.not_owner("Mechanic may only drive its own visits.")


@bp.route("/job-visits/<vid>", methods=["GET"])
def get_visit(vid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    v = _get_visit(vid)
    if role == "Customer":
        sr = db.store.service_requests.get(v["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own visits.")
    return response.success(models.serialize(v), 200)


@bp.route("/job-visits", methods=["GET"])
def list_visits():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Mechanic"})
    limit, offset = parse_pagination()
    sr_filter = request.args.get("service_request_id")
    mech_filter = request.args.get("mechanic_id")
    items = list(db.store.job_visits.values())
    if sr_filter is not None:
        items = [v for v in items if v["service_request_id"] == sr_filter]
    if mech_filter is not None:
        items = [v for v in items if v["mechanic_id"] == mech_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(v) for v in page], limit, offset, total)


@bp.route("/job-visits/<vid>/depart", methods=["POST"])
def depart(vid):
    uid, role = authenticate()
    require_role(role, {"Mechanic"})
    v = _get_visit(vid)
    _check_mechanic_owner(uid, role, v)
    if v["visit_status"] != "SCHEDULED":
        raise errors.invalid_state("Visit is not SCHEDULED.")
    mechanic = db.store.mechanics.get(v["mechanic_id"])
    if mechanic is None or mechanic["status"] != "AVAILABLE":
        raise errors.invalid_state("Mechanic is not AVAILABLE.")
    v["visit_status"] = "EN_ROUTE"
    models.touch(v, db.store)
    return response.success(models.serialize(v), 200)


@bp.route("/job-visits/<vid>/start-work", methods=["POST"])
def start_work(vid):
    uid, role = authenticate()
    require_role(role, {"Mechanic"})
    v = _get_visit(vid)
    _check_mechanic_owner(uid, role, v)
    if v["visit_status"] != "EN_ROUTE":
        raise errors.invalid_state("Visit is not EN_ROUTE.")
    sr = db.store.service_requests.get(v["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")
    if v["routing_mode"] == "ON_SITE":
        v["visit_status"] = "ON_SITE_WORKING"
    else:
        v["visit_status"] = "AT_SHOP"
    models.touch(v, db.store)
    # drive request DISPATCHED -> IN_PROGRESS
    sr["status"] = "IN_PROGRESS"
    models.touch(sr, db.store)
    return response.success(models.serialize(v), 200)


@bp.route("/job-visits/<vid>/finish", methods=["POST"])
def finish(vid):
    uid, role = authenticate()
    require_role(role, {"Mechanic"})
    v = _get_visit(vid)
    _check_mechanic_owner(uid, role, v)
    sr = db.store.service_requests.get(v["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")

    # state precondition (priority 5): visit working and request IN_PROGRESS
    if v["visit_status"] not in {"ON_SITE_WORKING", "AT_SHOP"}:
        raise errors.invalid_state("Visit is not in a finishable state.")
    if sr["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Service request is not IN_PROGRESS.")

    # structural validation (priority 6)
    body = validate.get_body()
    logged_hours = validate.require_number(body, "logged_labor_hours", minimum=0)
    payment_method = validate.require_enum(body, "payment_method", {"CARD", "FLEET_CREDIT"})

    # no PROPOSED findings remain (priority 15)
    for f in db.store.inspection_findings.values():
        if f["service_request_id"] == sr["id"] and f["status"] == "PROPOSED":
            raise errors.addons_unresolved()

    # compute final total from actuals
    addon_hours = v.get("_addon_labor_hours", 0)
    mechanic = db.store.mechanics.get(v["mechanic_id"])
    rate = mechanic["labor_rate_cents_per_hour"]
    parts_cents = sum(pl["line_total_cents"] for pl in db.store.part_lines.values()
                      if pl["service_request_id"] == sr["id"] and pl["status"] != "VOIDED")
    tow_cents = 0
    if sr["routing_mode"] == "TOW_TO_SHOP":
        # tow_fee from the approved quote
        for q in db.store.quotes.values():
            if q["service_request_id"] == sr["id"] and q["status"] == "APPROVED":
                tow_cents = q["tow_fee_cents"]
                break

    fleet_id = sr.get("fleet_account_id")
    fleet = db.store.fleet_accounts.get(fleet_id) if fleet_id else None
    discount = fleet["labor_discount_pct"] if fleet is not None else None

    final_total = calc.final_job_total(logged_hours, addon_hours, rate,
                                       parts_cents, tow_cents, discount)

    # fleet headroom re-check at invoice (priority 12), uses the FINAL total
    if fleet is not None:
        if not calc.fleet_headroom_ok(fleet["outstanding_balance_cents"],
                                      final_total, fleet["credit_limit_cents"]):
            raise errors.fleet_credit_exceeded()

    # commit: write actuals, install parts, finish visit, create payment, debit ledger
    v["logged_labor_hours"] = logged_hours
    sr["final_total_cents"] = final_total
    for pl in db.store.part_lines.values():
        if pl["service_request_id"] == sr["id"] and pl["status"] == "SOURCED":
            pl["status"] = "INSTALLED"
            models.touch(pl, db.store)

    payment = models.make_payment(db.store, sr["id"], fleet_id if fleet is not None else None,
                                  final_total, payment_method)
    db.store.payments[payment["id"]] = payment

    if fleet is not None:
        fleet["outstanding_balance_cents"] += final_total
        models.touch(fleet, db.store)

    v["visit_status"] = "FINISHED"
    models.touch(v, db.store)
    sr["status"] = "COMPLETED"
    models.touch(sr, db.store)
    return response.success(models.serialize(v), 200)


@bp.route("/job-visits/<vid>/abort", methods=["POST"])
def abort(vid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    v = _get_visit(vid)
    if v["visit_status"] not in {"SCHEDULED", "EN_ROUTE"}:
        raise errors.invalid_state("Only a SCHEDULED or EN_ROUTE visit may be aborted.")
    sr = db.store.service_requests.get(v["service_request_id"])
    v["visit_status"] = "ABORTED"
    models.touch(v, db.store)
    if sr is not None:
        sr["status"] = "APPROVED"
        sr["routing_mode"] = None
        models.touch(sr, db.store)
    return response.success(models.serialize(v), 200)
