"""Payout cycle endpoints."""
from flask import Blueprint, request, g
from clock import from_iso
from db import state, new_id
from errors import raise_err
from response import success_object
from middleware import require_roles
from routes.helpers import get_json
from serializers import serialize_payout_cycle
from services import payout as payout_svc


bp = Blueprint("payouts", __name__)


@bp.route("/payouts", methods=["POST"])
def open_cycle():
    require_roles("PlatformAdmin")
    body = get_json()
    cs = body.get("cycle_start")
    ce = body.get("cycle_end")
    if not cs or not ce:
        raise_err("ERR_VALIDATION", "cycle_start and cycle_end required")
    try:
        cs_dt = from_iso(cs)
        ce_dt = from_iso(ce)
    except ValueError:
        raise_err("ERR_VALIDATION", "invalid timestamp")
    if ce_dt <= cs_dt:
        raise_err("ERR_VALIDATION", "cycle_end must follow cycle_start")
    p = payout_svc.open_cycle(cs_dt, ce_dt)
    return success_object(serialize_payout_cycle(p), status=201)


@bp.route("/payouts/<id_>/close", methods=["POST"])
def close_cycle(id_):
    require_roles("PlatformAdmin")
    p = state["payout_cycles"].get(id_)
    if not p:
        raise_err("ERR_NOT_FOUND", "payout cycle not found")
    payout_svc.close_cycle(p)
    return success_object(serialize_payout_cycle(p))
