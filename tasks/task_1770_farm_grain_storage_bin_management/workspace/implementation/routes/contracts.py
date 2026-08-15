"""Storage contract endpoints (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok
from services import core
from util import (as_bu, as_dt, as_enum, as_int, body, present, required,
                  resolve_path)

bp = Blueprint("contracts", __name__)


@bp.route("/grain/contracts", methods=["POST"])
def create_contract():
    require_roles("FarmOwner")
    data = body()
    crop = as_enum(required(data, "crop"), "crop", core.CROPS)
    contracted = as_bu(required(data, "contracted_bu"), "contracted_bu")
    if contracted <= 0:
        raise ApiError("ERR_VALIDATION", 400, "contracted_bu must be > 0")
    window_start = as_dt(required(data, "window_start"), "window_start")
    window_end = as_dt(required(data, "window_end"), "window_end")
    if window_end <= window_start:
        raise ApiError("ERR_VALIDATION", 400,
                       "window_end must be strictly after window_start")
    basis = as_int(required(data, "basis_cents_per_bu"), "basis_cents_per_bu")
    futures = as_int(required(data, "futures_ref_cents_per_bu"),
                     "futures_ref_cents_per_bu")
    if futures <= 0:
        raise ApiError("ERR_VALIDATION", 400,
                       "futures_ref_cents_per_bu must be > 0")
    early_bonus = 0
    if present(data, "early_bonus_cents_per_bu"):
        early_bonus = as_int(data["early_bonus_cents_per_bu"],
                             "early_bonus_cents_per_bu")
    early_cutoff = None
    if present(data, "early_cutoff"):
        early_cutoff = as_dt(data["early_cutoff"], "early_cutoff")

    rec = core.new_common()
    rec.update({
        "crop": crop,
        "contracted_bu": contracted,
        "window_start": window_start,
        "window_end": window_end,
        "basis_cents_per_bu": basis,
        "futures_ref_cents_per_bu": futures,
        "early_bonus_cents_per_bu": early_bonus,
        "early_cutoff": early_cutoff,
        "contract_unit_price_cents": futures + basis,
        "status": "OPEN",
    })
    db.contracts[rec["id"]] = rec
    return ok(core.contract_view(rec), 201)


@bp.route("/grain/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles(*ALL_ROLES)
    return ok(core.contract_view(resolve_path(db.contracts, cid, "contract")))
