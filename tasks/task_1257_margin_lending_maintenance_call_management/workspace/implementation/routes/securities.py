"""Security profiles and house margin policy (PRD 3.2)."""
from flask import Blueprint

from authz import ANY_ROLE, SUPERVISOR, require_roles
from cascades import recompute_and_evaluate
from db import store
from errors import invalid_request, security_not_found
from response import success
from serialize import ser_security
from store_ops import (
    json_body,
    new_id,
    opt_bool,
    opt_int,
    paginate,
    req_bool,
    req_int,
    req_str,
    sorted_by_creation,
    stamp_new,
    touch,
)

bp = Blueprint("securities", __name__)


def get_security_or_404(security_id):
    sec = store.securities.get(security_id)
    if sec is None:
        raise security_not_found()
    return sec


@bp.route("/margin/security-profiles", methods=["POST"])
def create_security():
    data = json_body()
    symbol = req_str(data, "symbol")
    marginable = req_bool(data, "marginable")
    long_bps = req_int(data, "house_maint_long_bps")
    short_bps = req_int(data, "house_maint_short_bps")
    liquidity_tier = req_int(data, "liquidity_tier")
    conc_bps = req_int(data, "concentration_threshold_bps")
    require_roles([SUPERVISOR])
    if any(s["symbol"] == symbol for s in store.securities.values()):
        raise invalid_request("symbol must be unique across securities")
    sec = {
        "id": new_id(),
        "symbol": symbol,
        "marginable": marginable,
        "house_maint_long_bps": long_bps,
        "house_maint_short_bps": short_bps,
        "liquidity_tier": liquidity_tier,
        "concentration_threshold_bps": conc_bps,
    }
    stamp_new(sec)
    store.securities[sec["id"]] = sec
    return success(ser_security(sec), status=201)


@bp.route("/margin/security-profiles/<sid>", methods=["GET"])
def get_security(sid):
    require_roles(ANY_ROLE)
    return success(ser_security(get_security_or_404(sid)))


@bp.route("/margin/security-profiles", methods=["GET"])
def list_securities():
    require_roles(ANY_ROLE)
    items = sorted_by_creation(list(store.securities.values()))
    page, pagination = paginate(items)
    return success([ser_security(s) for s in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/security-profiles/<sid>", methods=["PATCH"])
def patch_security(sid):
    data = json_body()
    long_bps = opt_int(data, "house_maint_long_bps")
    short_bps = opt_int(data, "house_maint_short_bps")
    conc_bps = opt_int(data, "concentration_threshold_bps")
    marginable = opt_bool(data, "marginable")
    require_roles([SUPERVISOR])
    sec = get_security_or_404(sid)
    if long_bps is not None:
        sec["house_maint_long_bps"] = long_bps
    if short_bps is not None:
        sec["house_maint_short_bps"] = short_bps
    if conc_bps is not None:
        sec["concentration_threshold_bps"] = conc_bps
    if marginable is not None:
        sec["marginable"] = marginable
    touch(sec)
    # House policy change: recompute official requirements for every account
    # holding the security and run full call evaluation for each (PRD 3.2).
    holders = sorted(
        (a for a in store.accounts.values()
         if any(p["security_id"] == sid for p in store.positions.values()
                if p["account_id"] == a["id"])),
        key=lambda a: a["_seq"])
    for account in holders:
        if account["account_status"] == "CLOSED":
            continue
        recompute_and_evaluate(account)
    return success(ser_security(sec))
