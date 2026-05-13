"""Exercise application routes."""

from flask import Blueprint, request, g as flask_g
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_NOT_IN_EXERCISE_WINDOW, ERR_INSUFFICIENT_VESTED_QUANTITY,
    ERR_WINDOW_NOT_OPEN, ERR_GRANT_NOT_LIVE,
    ERR_PERFORMANCE_CONDITION_NOT_MET, ERR_STALE_PRICE_VERSION,
    ERR_CROSS_RESOURCE_MISMATCH,
)
from services.common import (
    init_common, init_append_only, bump_version, check_occ,
    get_body, get_or_404, get_pagination, paginate_list, sort_by_created_at_asc,
    require_enum,
)
from services.time_util import format_iso, parse_iso
from services.serializers import serialize_application
from services.calculations import (
    compute_vested_quantity, compute_tax_for_event,
)
from services.audit import append_audit


bp = Blueprint("applications", __name__)


SETTLEMENT_MODES = {"SHARE_ISSUANCE", "CASH_SETTLEMENT"}


def _tip_for_batch(batch_id):
    best = None
    for v in DB["exercise_price_versions"].values():
        if v["batch_id"] != batch_id:
            continue
        if best is None or v["version_index"] > best["version_index"]:
            best = v
    return best


def _latest_departure_record(grantee_id):
    best = None
    for d in DB["departure_records"].values():
        if d["grantee_id"] != grantee_id:
            continue
        if d["status"] != "SETTLED":
            continue
        if best is None or d.get("departed_ts", "") > best.get("departed_ts", ""):
            best = d
    return best


@bp.post("/grants/<grant_id>/exercise-applications")
@auth_required(["Grantee"])
def submit_application(grant_id):
    grant = get_or_404("grants", grant_id)
    grantee = DB["grantees"].get(grant["grantee_id"])
    if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Caller is not the grant's grantee")
    plan = DB["option_plans"].get(grant["plan_id"])
    batch = DB["grant_batches"].get(grant["batch_id"])
    body = get_body()
    window_id = body.get("window_id")
    if not isinstance(window_id, str) or not window_id:
        raise_error(ERR_INVALID_REQUEST, "window_id required")
    window = DB["exercise_windows"].get(window_id)
    if window is None:
        raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Window not found")
    if window["plan_id"] != grant["plan_id"]:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Window does not belong to grant's plan")
    if window["status"] != "OPEN":
        raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Window not OPEN")
    # If grantee DEPARTED, must be within deadline
    if grantee["eligibility_status"] == "DEPARTED":
        dep = _latest_departure_record(grantee["id"])
        deadline = dep.get("post_departure_exercise_deadline_ts") if dep else None
        if deadline is None:
            raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Departed grantee has no exercise window")
        clock = parse_iso(plan["current_clock_ts"])
        deadline_dt = parse_iso(deadline)
        if clock is None or deadline_dt is None or clock > deadline_dt:
            raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Past post-departure deadline")
    elif grantee["eligibility_status"] != "ELIGIBLE":
        raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Grantee not eligible")
    requested_qty = body.get("requested_quantity")
    if not isinstance(requested_qty, int) or isinstance(requested_qty, bool) or requested_qty < 1:
        raise_error(ERR_INVALID_REQUEST, "requested_quantity must be positive integer")
    mode = require_enum(body, "settlement_mode", SETTLEMENT_MODES)
    pinned_version_id = body.get("pinned_price_version_id")
    if not isinstance(pinned_version_id, str) or not pinned_version_id:
        raise_error(ERR_INVALID_REQUEST, "pinned_price_version_id required")
    # Stale price check: must equal tip of batch
    tip = _tip_for_batch(grant["batch_id"])
    if tip is None or pinned_version_id != tip["id"]:
        raise_error(ERR_STALE_PRICE_VERSION, "Pinned price version is not the current tip")
    # Refresh vested_quantity for downstream readers; PRD §3.8 places the
    # ERR_INSUFFICIENT_VESTED_QUANTITY check at /verify, not at submit, so
    # we do not reject here based on vested availability.
    vested = compute_vested_quantity(grant, plan, batch)
    grant["vested_quantity"] = vested

    aid = new_id()
    pinned = DB["exercise_price_versions"][pinned_version_id]
    gross = requested_qty * int(pinned["price_per_option_cents"])
    app = {
        "id": aid,
        "plan_id": grant["plan_id"],
        "grant_id": grant_id,
        "window_id": window_id,
        "pinned_price_version_id": pinned_version_id,
        "requested_quantity": requested_qty,
        "settlement_mode": mode,
        "gross_proceeds_cents": gross,
        "withholding_tax_cents": None,
        "net_proceeds_cents": None,
        "payment_reference": None,
        "share_registry_reference": None,
        "status": "SUBMITTED",
    }
    init_common(app)
    DB["exercise_applications"][aid] = app
    append_audit(plan, "EXERCISE_SUBMITTED", "ExerciseApplication", aid,
                 {"grant_id": grant_id, "window_id": window_id,
                  "requested_quantity": requested_qty, "settlement_mode": mode})
    return success_response(serialize_application(app), http_status=201)


@bp.get("/option-plans/<plan_id>/exercise-applications")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_applications(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    items = [a for a in DB["exercise_applications"].values() if a["plan_id"] == plan_id]
    grant_id = request.args.get("grant_id")
    status = request.args.get("status")
    window_id = request.args.get("window_id")
    if grant_id:
        items = [a for a in items if a["grant_id"] == grant_id]
    if status:
        items = [a for a in items if a["status"] == status]
    if window_id:
        items = [a for a in items if a["window_id"] == window_id]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_application(a) for a in sliced], total, limit, offset)


def _do_tax_withhold(app, grant, plan, grantee):
    pinned = DB["exercise_price_versions"][app["pinned_price_version_id"]]
    pinned_price = int(pinned["price_per_option_cents"])
    # current fair value (for spread calc) — use grant_date_fair_value_cents as a proxy when nothing else available
    current_fmv = int(grant["grant_date_fair_value_cents"])
    taxable, withheld, deferred = compute_tax_for_event(
        plan, grant, grantee, "EXERCISE",
        exercise_app=app,
        current_fair_value_cents=current_fmv,
        pinned_price_cents=pinned_price,
    )
    # Pin TaxEventRecord
    teid = new_id()
    te = {
        "id": teid,
        "grant_id": grant["id"],
        "exercise_application_id": app["id"],
        "event_type": "EXERCISE",
        "taxable_amount_cents": taxable,
        "withheld_amount_cents": withheld,
        "deferred": deferred,
        "jurisdiction_code": plan["jurisdiction_code"],
        "document_id": None,
        "event_ts": plan.get("current_clock_ts"),
        "payload_summary": {},
    }
    init_append_only(te)
    DB["tax_events"][teid] = te
    app["withholding_tax_cents"] = withheld
    if app["settlement_mode"] == "CASH_SETTLEMENT":
        app["net_proceeds_cents"] = int(app["gross_proceeds_cents"]) - int(withheld)
    app["status"] = "TAX_WITHHELD"
    bump_version(app)


@bp.post("/exercise-applications/<app_id>/verify")
@auth_required(["PlanAdministrator"])
def verify_application(app_id):
    app = get_or_404("exercise_applications", app_id)
    body = get_body()
    check_occ(app, body)
    grant = DB["grants"].get(app["grant_id"])
    plan = DB["option_plans"].get(app["plan_id"])
    batch = DB["grant_batches"].get(grant["batch_id"])
    grantee = DB["grantees"].get(grant["grantee_id"])
    window = DB["exercise_windows"].get(app["window_id"])

    # Per PRD §3.8: first check that grant is LIVE
    if grant["status"] != "LIVE":
        raise_error(ERR_GRANT_NOT_LIVE, "Grant not LIVE")
    if window["status"] != "OPEN":
        raise_error(ERR_WINDOW_NOT_OPEN, "Window not OPEN")
    # Grantee eligibility
    if grantee["eligibility_status"] == "DEPARTED":
        dep = _latest_departure_record(grantee["id"])
        deadline = dep.get("post_departure_exercise_deadline_ts") if dep else None
        clock = parse_iso(plan["current_clock_ts"])
        if not deadline or not clock or clock > parse_iso(deadline):
            raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Past post-departure deadline")
    elif grantee["eligibility_status"] != "ELIGIBLE":
        raise_error(ERR_NOT_IN_EXERCISE_WINDOW, "Grantee not eligible")
    # Stale price re-check
    tip = _tip_for_batch(grant["batch_id"])
    if tip is None or app["pinned_price_version_id"] != tip["id"]:
        raise_error(ERR_STALE_PRICE_VERSION, "Pinned version is stale")
    # Vested quantity re-check
    vested = compute_vested_quantity(grant, plan, batch)
    grant["vested_quantity"] = vested
    if int(app["requested_quantity"]) > (vested - int(grant.get("exercised_quantity", 0))):
        raise_error(ERR_INSUFFICIENT_VESTED_QUANTITY, "Insufficient vested quantity")
    # Performance gate
    if batch.get("performance_condition_required") and grant.get("performance_attested_at") is None:
        raise_error(ERR_PERFORMANCE_CONDITION_NOT_MET, "Performance condition not attested")

    app["status"] = "ELIGIBILITY_VERIFIED"
    bump_version(app)

    # CASH_SETTLEMENT cascades directly to TAX_WITHHELD
    if app["settlement_mode"] == "CASH_SETTLEMENT":
        _do_tax_withhold(app, grant, plan, grantee)

    return success_response(serialize_application(app))


@bp.post("/exercise-applications/<app_id>/pay")
@auth_required(["PlanAdministrator"])
def pay_application(app_id):
    app = get_or_404("exercise_applications", app_id)
    body = get_body()
    check_occ(app, body)
    if app["status"] != "ELIGIBILITY_VERIFIED":
        raise_error(ERR_INVALID_REQUEST, "Application not ELIGIBILITY_VERIFIED")
    if app["settlement_mode"] != "SHARE_ISSUANCE":
        raise_error(ERR_INVALID_REQUEST, "pay only valid for SHARE_ISSUANCE")
    payref = body.get("payment_reference")
    if not isinstance(payref, str) or not payref.strip():
        raise_error(ERR_INVALID_REQUEST, "payment_reference required")
    grant = DB["grants"].get(app["grant_id"])
    plan = DB["option_plans"].get(app["plan_id"])
    grantee = DB["grantees"].get(grant["grantee_id"])
    pinned = DB["exercise_price_versions"][app["pinned_price_version_id"]]
    app["payment_reference"] = payref
    app["gross_proceeds_cents"] = int(app["requested_quantity"]) * int(pinned["price_per_option_cents"])
    app["status"] = "PAYMENT_RECEIVED"
    bump_version(app)
    # auto-cascade to TAX_WITHHELD
    _do_tax_withhold(app, grant, plan, grantee)
    return success_response(serialize_application(app))


@bp.post("/exercise-applications/<app_id>/settle")
@auth_required(["PlanAdministrator"])
def settle_application(app_id):
    app = get_or_404("exercise_applications", app_id)
    body = get_body()
    check_occ(app, body)
    if app["status"] != "TAX_WITHHELD":
        raise_error(ERR_INVALID_REQUEST, "Application not TAX_WITHHELD")
    mode = app["settlement_mode"]
    if mode == "SHARE_ISSUANCE":
        sref = body.get("share_registry_reference")
        if not isinstance(sref, str) or not sref.strip():
            raise_error(ERR_INVALID_REQUEST, "share_registry_reference required")
        app["share_registry_reference"] = sref
    else:  # CASH_SETTLEMENT
        payref = body.get("payment_reference")
        if not isinstance(payref, str) or not payref.strip():
            raise_error(ERR_INVALID_REQUEST, "payment_reference required")
        app["payment_reference"] = payref
    grant = DB["grants"].get(app["grant_id"])
    plan = DB["option_plans"].get(app["plan_id"])
    # Increase exercised and pool decrement happens implicitly via aggregate
    grant["exercised_quantity"] = int(grant.get("exercised_quantity", 0)) + int(app["requested_quantity"])
    bump_version(grant)
    app["status"] = "SETTLED"
    bump_version(app)
    append_audit(plan, "EXERCISE_SETTLED", "ExerciseApplication", app["id"],
                 {"grant_id": grant["id"], "requested_quantity": app["requested_quantity"]})
    return success_response(serialize_application(app))


@bp.post("/exercise-applications/<app_id>/reject")
@auth_required(["PlanAdministrator"])
def reject_application(app_id):
    app = get_or_404("exercise_applications", app_id)
    body = get_body()
    check_occ(app, body)
    if app["status"] not in ("SUBMITTED", "ELIGIBILITY_VERIFIED"):
        raise_error(ERR_INVALID_REQUEST, "Cannot reject from current state")
    reason = body.get("reason")
    app["status"] = "REJECTED"
    if reason is not None:
        app["_rejection_reason"] = str(reason)
    bump_version(app)
    plan = DB["option_plans"].get(app["plan_id"])
    append_audit(plan, "EXERCISE_REJECTED", "ExerciseApplication", app["id"],
                 {"reason": reason})
    return success_response(serialize_application(app))


@bp.post("/exercise-applications/<app_id>/cancel")
@auth_required(["Grantee"])
def cancel_application(app_id):
    app = get_or_404("exercise_applications", app_id)
    body = get_body()
    check_occ(app, body)
    grant = DB["grants"].get(app["grant_id"])
    grantee = DB["grantees"].get(grant["grantee_id"]) if grant else None
    if not grantee or grantee["hr_employee_id"] != flask_g.user_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "Not the grant's grantee")
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_REQUEST, "Only SUBMITTED applications can be cancelled")
    app["status"] = "CANCELLED"
    bump_version(app)
    return success_response(serialize_application(app))
