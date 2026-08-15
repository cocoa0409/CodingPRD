"""PatentFamily routes and the computed budget forecast (PRD §3.1, §3.9)."""

from flask import Blueprint

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CLIENT_SUSPENDED,
    ERR_FAMILY_HAS_APPROVED_REVIEWS,
    ERR_FAMILY_HAS_OPEN_APPLICATIONS,
)
from middleware import require_roles, get_json_body, parse_pagination, query_param, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, bump, get_client, get_family,
    check_allowed_fields, req_str, req_int, req_date, ensure_transition,
)
from services import calc

bp = Blueprint("families", __name__)

APPLICATION_TERMINAL = {"ABANDONED", "LAPSED", "WITHDRAWN"}


@bp.post("/clients/<client_id>/families")
def create_family(client_id):
    require_roles(["DocketingManager"])
    client = get_client(client_id)
    body = get_json_body()
    check_allowed_fields(body, {"title", "first_priority_date", "budget_cap_cents"})
    title = req_str(body, "title")
    first_priority_date = req_date(body, "first_priority_date")
    budget_cap_cents = req_int(body, "budget_cap_cents")
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    rec = stamp_new({
        "id": new_id(),
        "client_id": client["id"],
        "title": title,
        "first_priority_date": first_priority_date,
        "budget_cap_cents": budget_cap_cents,
        "status": "ACTIVE",
        "committed_forecast_cents": 0,
    })
    dbmod.DB["families"][rec["id"]] = rec
    return success_object(serialize.family(rec), 201)


@bp.get("/clients/<client_id>/families")
def list_client_families(client_id):
    require_roles(ALL_ROLES)
    client = get_client(client_id)
    limit, offset = parse_pagination()
    items = [f for f in dbmod.DB["families"].values() if f["client_id"] == client["id"]]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.family(r) for r in page], total, limit, offset)


@bp.get("/families/<family_id>")
def get_family_route(family_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.family(get_family(family_id)))


@bp.post("/families/<family_id>/enter-pruning-review")
def enter_pruning_review(family_id):
    require_roles(["DocketingManager"])
    rec = get_family(family_id)
    ensure_transition(rec, {"ACTIVE"}, "families", "PatentFamily")
    rec["status"] = "PRUNING_REVIEW"
    bump(rec)
    return success_object(serialize.family(rec))


@bp.post("/families/<family_id>/exit-pruning-review")
def exit_pruning_review(family_id):
    require_roles(["DocketingManager"])
    rec = get_family(family_id)
    ensure_transition(rec, {"PRUNING_REVIEW"}, "families", "PatentFamily")
    app_ids = {
        a["id"] for a in dbmod.DB["applications"].values() if a["family_id"] == rec["id"]
    }
    has_approved = any(
        rv["application_id"] in app_ids and rv["status"] == "APPROVED"
        for rv in dbmod.DB["reviews"].values()
    )
    if has_approved:
        raise_err(
            ERR_FAMILY_HAS_APPROVED_REVIEWS,
            "An AbandonmentReview in APPROVED status exists under this family",
        )
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(serialize.family(rec))


@bp.post("/families/<family_id>/close")
def close_family(family_id):
    require_roles(["DocketingManager"])
    rec = get_family(family_id)
    ensure_transition(rec, {"ACTIVE", "PRUNING_REVIEW"}, "families", "PatentFamily")
    has_open = any(
        a["family_id"] == rec["id"] and a["status"] not in APPLICATION_TERMINAL
        for a in dbmod.DB["applications"].values()
    )
    if has_open:
        raise_err(
            ERR_FAMILY_HAS_OPEN_APPLICATIONS,
            "Every application of the family must be terminal before close",
        )
    rec["status"] = "CLOSED"
    bump(rec)
    return success_object(serialize.family(rec))


@bp.get("/families/<family_id>/budget-forecast")
def budget_forecast(family_id):
    require_roles(ALL_ROLES)
    rec = get_family(family_id)
    variant = query_param("variant")
    if variant not in ("COMMITTED", "PROJECTED"):
        raise_err(ERR_INVALID_REQUEST, "variant must be one of COMMITTED, PROJECTED")
    total, per_application = calc.budget_forecast(rec, variant)
    return success_object({
        "variant": variant,
        "total_usd_cents": total,
        "per_application": per_application,
    })
