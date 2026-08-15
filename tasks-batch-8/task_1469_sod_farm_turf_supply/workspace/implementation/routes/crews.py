"""Installation crews: register, list, fetch, deactivate (cascade), referrals."""
from flask import Blueprint, request

import db
import services
from auth import require_roles
from db import common_fields
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from serialize import pub_crew, pub_referral
from util import (as_bool, as_int, as_str, body, ok, ok_list, paged, pagination,
                  require, sort_created)

bp = Blueprint("crews", __name__)


@bp.route("/crews", methods=["POST"])
def create_crew():
    require_roles("FarmManager")
    payload = body()
    name = as_str(require(payload, "name"), "name")
    zones_raw = require(payload, "service_zones")
    if not isinstance(zones_raw, list) or len(zones_raw) == 0:
        raise err(ERR_INVALID_REQUEST, "service_zones must be a non-empty array")
    zones = [as_int(z, "service_zones[]", minimum=1, maximum=3) for z in zones_raw]
    active = True
    if payload.get("active") is not None:
        active = as_bool(payload["active"], "active")
    crew = common_fields()
    crew.update({"name": name, "service_zones": zones, "active": active})
    db.store.crews[crew["id"]] = crew
    return ok(pub_crew(crew), 201)


@bp.route("/crews", methods=["GET"])
def list_crews():
    require_roles("SalesRep", "FarmManager")
    limit, offset = pagination()
    items = sort_created(db.store.crews.values())
    active_filter = request.args.get("active")
    if active_filter is not None:
        token = active_filter.strip().lower()
        if token in ("true", "1", "yes"):
            items = [c for c in items if c["active"]]
        elif token in ("false", "0", "no"):
            items = [c for c in items if not c["active"]]
        else:
            raise err(ERR_INVALID_REQUEST, "active filter must be true or false")
    page, total = paged(items, limit, offset)
    return ok_list([pub_crew(c) for c in page], total, limit, offset)


@bp.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    require_roles("SalesRep", "FarmManager")
    crew = db.store.crews.get(cid)
    if crew is None:
        raise err(ERR_NOT_FOUND, f"crew {cid} not found")
    return ok(pub_crew(crew), 200)


@bp.route("/crews/<cid>/deactivate", methods=["POST"])
def deactivate_crew(cid):
    require_roles("FarmManager")
    crew = db.store.crews.get(cid)
    if crew is None:
        raise err(ERR_NOT_FOUND, f"crew {cid} not found")
    crew["active"] = False
    db.bump(crew)
    services.crew_deactivate_cascade(crew)
    return ok(pub_crew(crew), 200)


@bp.route("/crews/<cid>/crew-referrals", methods=["GET"])
def list_crew_referrals(cid):
    require_roles("SalesRep", "FarmManager")
    crew = db.store.crews.get(cid)
    if crew is None:
        raise err(ERR_NOT_FOUND, f"crew {cid} not found")
    limit, offset = pagination()
    items = sort_created(r for r in db.store.crew_referrals.values() if r["crew_id"] == cid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_referral(r) for r in page], total, limit, offset)
