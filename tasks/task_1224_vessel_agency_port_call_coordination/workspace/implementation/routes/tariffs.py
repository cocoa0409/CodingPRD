"""Tariff endpoints with publication supersession."""
from flask import Blueprint, request

from errors import invalid_request, not_found
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import (is_int, is_num, new_entity, paginate, pagination_args, parse_dt,
                   sort_created, touch)

bp = Blueprint("tariffs", __name__)

COMPONENTS = {"PORT_DUES", "BERTH_HIRE", "PILOTAGE"}


def _valid_tiers(tiers):
    if not isinstance(tiers, list) or not tiers:
        return False
    prev = -1
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            return False
        upper = tier.get("gt_up_to")
        rate = tier.get("rate_cents")
        if not is_num(rate) or rate < 0:
            return False
        if upper is None:
            if i != len(tiers) - 1:
                return False
        else:
            if not is_int(upper) or upper <= 0 or upper <= prev:
                return False
            prev = upper
    return True


@bp.post("/tariffs")
def create_tariff():
    require_roles(["PortAuthority"])
    body = request.get_json(silent=True) or {}
    effective_from = parse_dt(body.get("effective_from"))
    tiers = body.get("gt_tiers")
    night_pct = body.get("night_surcharge_pct")
    hazmat_pct = body.get("hazmat_surcharge_pct")
    if (not isinstance(body.get("port_code"), str) or not body.get("port_code")
            or body.get("component") not in COMPONENTS
            or effective_from is None
            or not is_num(night_pct) or night_pct < 0
            or not is_num(hazmat_pct) or hazmat_pct < 0
            or not _valid_tiers(tiers)):
        invalid_request("invalid tariff payload")
    # Supersede every PUBLISHED tariff of the same (port_code, component)
    for other in domain.all_of("tariffs"):
        if (other["port_code"] == body["port_code"]
                and other["component"] == body["component"]
                and other["status"] == "PUBLISHED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    ent = new_entity("tariffs", {
        "port_code": body["port_code"],
        "component": body["component"],
        "effective_from": effective_from,
        "night_surcharge_pct": night_pct,
        "hazmat_surcharge_pct": hazmat_pct,
        "gt_tiers": [{"gt_up_to": t.get("gt_up_to"), "rate_cents": t["rate_cents"]} for t in tiers],
        "status": "PUBLISHED",
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/tariffs")
def list_tariffs():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("tariffs"))
    for param in ("port_code", "component", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/tariffs/<tid>")
def get_tariff(tid):
    require_roles(ANY_ROLE)
    ent = domain.get("tariffs", tid)
    if ent is None:
        not_found("tariff")
    return ok_object(serialize(ent))


@bp.get("/tariffs/<tid>/da-lines")
def tariff_da_lines(tid):
    require_roles(ANY_ROLE)
    ent = domain.get("tariffs", tid)
    if ent is None:
        not_found("tariff")
    items = [l for l in domain.all_of("da_lines") if l.get("tariff_id") == tid]
    items = sorted(items, key=lambda l: (l["created_at"], l["category"], l["_seq"]))
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)
