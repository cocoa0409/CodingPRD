"""Departure record routes."""

from flask import Blueprint, request
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_BAD_LEAVER_REQUIRES_TERMINATION,
    ERR_CROSS_RESOURCE_MISMATCH, ERR_DEPARTURE_NOT_DRAFT,
    ERR_GRANTEE_ALREADY_DEPARTED,
)
from services.common import (
    init_common, bump_version, check_occ, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_enum, require_iso_datetime,
)
from services.time_util import format_iso, parse_iso, add_days
from services.serializers import serialize_departure
from services.calculations import compute_vested_quantity
from services.audit import append_audit


bp = Blueprint("departures", __name__)


DEP_TYPES = {"RESIGNATION", "TERMINATION", "RETIREMENT", "DEATH"}
LEAVER_CLASSES = {"GOOD_LEAVER", "BAD_LEAVER"}


def _derive_leaver_class(departure_type, supplied):
    if departure_type == "TERMINATION":
        # supplied is required and must be GOOD or BAD
        if supplied not in LEAVER_CLASSES:
            raise_error(ERR_INVALID_REQUEST, "leaver_class required for TERMINATION")
        return supplied
    # For RESIGNATION/RETIREMENT/DEATH, auto-derive GOOD_LEAVER
    # If caller supplied BAD_LEAVER with non-TERMINATION — that's caught upstream
    return "GOOD_LEAVER"


def _post_dep_window(leaver_class, departure_type, jurisdiction):
    if leaver_class == "BAD_LEAVER":
        return 0
    base = {"RESIGNATION": 90, "TERMINATION": 180, "RETIREMENT": 1095, "DEATH": 365}[departure_type]
    if leaver_class == "GOOD_LEAVER" and jurisdiction in ("UK", "SG"):
        base = max(base, 120)
    return base


@bp.post("/option-plans/<plan_id>/grantees/<grantee_id>/departure-records")
@auth_required(["PlanAdministrator"])
def create_departure(plan_id, grantee_id):
    plan = get_or_404("option_plans", plan_id)
    grantee = get_or_404("grantees", grantee_id)
    if grantee["plan_id"] != plan_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Grantee does not belong to plan")
    body = get_body()
    departure_type = require_enum(body, "departure_type", DEP_TYPES)
    supplied_class = body.get("leaver_class")
    if supplied_class == "BAD_LEAVER" and departure_type != "TERMINATION":
        raise_error(ERR_BAD_LEAVER_REQUIRES_TERMINATION,
                    "BAD_LEAVER only permitted for TERMINATION")
    leaver_class = _derive_leaver_class(departure_type, supplied_class)
    departed_dt = require_iso_datetime(body, "departed_ts")
    window_days = _post_dep_window(leaver_class, departure_type, plan["jurisdiction_code"])
    if leaver_class == "BAD_LEAVER":
        deadline = None
    else:
        deadline = add_days(departed_dt, window_days)
    did = new_id()
    record = {
        "id": did,
        "grantee_id": grantee_id,
        "departure_type": departure_type,
        "leaver_class": leaver_class,
        "departed_ts": format_iso(departed_dt),
        "post_departure_window_days": window_days,
        "post_departure_exercise_deadline_ts": format_iso(deadline) if deadline else None,
        "forfeited_options_total": 0,
        "status": "DRAFT",
    }
    init_common(record)
    DB["departure_records"][did] = record
    return success_response(serialize_departure(record), http_status=201)


@bp.post("/grantees/<grantee_id>/departure-records/<dep_id>/settle")
@auth_required(["PlanAdministrator"])
def settle_departure(grantee_id, dep_id):
    grantee = get_or_404("grantees", grantee_id)
    dep = get_or_404("departure_records", dep_id)
    if dep["grantee_id"] != grantee_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Departure does not belong to grantee")
    body = get_body()
    check_occ(dep, body)
    if dep["status"] != "DRAFT":
        raise_error(ERR_DEPARTURE_NOT_DRAFT, "Departure not in DRAFT")
    if grantee["eligibility_status"] != "ELIGIBLE":
        raise_error(ERR_GRANTEE_ALREADY_DEPARTED, "Grantee already departed")
    plan = DB["option_plans"].get(grantee["plan_id"])

    # Forfeiture cascade
    departed_dt = parse_iso(dep["departed_ts"])
    leaver_class = dep["leaver_class"]
    total_unvested = 0
    total_vested_forfeited = 0
    affected = []
    for g in DB["grants"].values():
        if g["grantee_id"] != grantee_id:
            continue
        if g["status"] not in ("LIVE", "FROZEN"):
            continue
        affected.append(g)
    affected.sort(key=lambda g: (g.get("batch_id", ""), g.get("grant_date") or "", g["id"]))
    for g in affected:
        batch = DB["grant_batches"].get(g["batch_id"])
        vested_at_dep = compute_vested_quantity(g, plan, batch, at_clock_dt=departed_dt)
        unvested = int(g["quantity"]) - vested_at_dep - int(g.get("forfeited_quantity", 0))
        if unvested < 0:
            unvested = 0
        outstanding_vested = vested_at_dep - int(g.get("exercised_quantity", 0))
        if outstanding_vested < 0:
            outstanding_vested = 0
        g["forfeited_quantity"] = int(g.get("forfeited_quantity", 0)) + unvested
        total_unvested += unvested
        if leaver_class == "BAD_LEAVER":
            g["forfeited_quantity"] = int(g["forfeited_quantity"]) + outstanding_vested
            total_vested_forfeited += outstanding_vested
            g["status"] = "TERMINATED"
            # Cancel non-terminal applications
            for a in DB["exercise_applications"].values():
                if a["grant_id"] == g["id"] and a["status"] in (
                    "SUBMITTED", "ELIGIBILITY_VERIFIED", "PAYMENT_RECEIVED", "TAX_WITHHELD"
                ):
                    a["status"] = "REJECTED"
                    a["_rejection_note"] = "BAD_LEAVER_FORFEITURE"
                    bump_version(a)
            append_audit(plan, "GRANT_TERMINATED", "Grant", g["id"],
                         {"reason": "BAD_LEAVER", "forfeited_quantity": g["forfeited_quantity"]})
        bump_version(g)

    grantee["eligibility_status"] = "DEPARTED"
    grantee["departed_at"] = dep["departed_ts"]
    bump_version(grantee)
    dep["forfeited_options_total"] = total_unvested + total_vested_forfeited
    dep["status"] = "SETTLED"
    bump_version(dep)
    bump_version(plan)
    append_audit(plan, "DEPARTURE_SETTLED", "DepartureRecord", dep_id,
                 {"grantee_id": grantee_id, "leaver_class": leaver_class,
                  "forfeited_options_total": dep["forfeited_options_total"]})
    return success_response(serialize_departure(dep))


@bp.get("/option-plans/<plan_id>/departure-records")
@auth_required(["PlanAdministrator", "AuditViewer"])
def list_departures(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    items = []
    for d in DB["departure_records"].values():
        g = DB["grantees"].get(d["grantee_id"])
        if g and g["plan_id"] == plan_id:
            items.append(d)
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_departure(d) for d in sliced], total, limit, offset)
