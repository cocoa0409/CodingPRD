"""Distributor registration, reads and the diversion-exposure computed read (PRD §3.3, §3.9)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, STAFF_AND_DISTRIBUTOR, authenticate, require_owner,
)
from calc import diversion_exposure
from envelope import created, ok, ok_list
from store import new_row, serialize, store
from validate import EXPOSURE_VARIANTS, body, query_enum, req_int, req_str

bp = Blueprint("distributors", __name__)


@bp.post("/distributors")
def register_distributor():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    legal_name = req_str(b, "legal_name", 1, None)
    cap = req_int(b, "annual_chargeback_cap_cents", 1, None)
    row = new_row({
        "legal_name": legal_name,
        "annual_chargeback_cap_cents": cap,
        "standing": "GOOD",
        "diversion_score": 0,
        "chargeback_balance_cents": 0,
        "shipped_units_total": 0,
        "probation_entered_at": None,
    })
    store.distributors[row["id"]] = row
    return created(serialize(row))


@bp.get("/distributors/<distributor_id>")
def read_distributor(distributor_id):
    ctx = authenticate(STAFF_AND_DISTRIBUTOR)
    row = lookup.distributor(distributor_id)
    require_owner(ctx, row, distributor_field="id")
    return ok(serialize(row))


@bp.get("/distributors")
def list_distributors():
    authenticate(STAFF_AND_DISTRIBUTOR)
    rows = lookup.filtered("distributors", {"standing": "standing"})
    return ok_list(rows)


@bp.get("/distributors/<distributor_id>/diversion-exposure")
def exposure(distributor_id):
    ctx = authenticate(STAFF_AND_DISTRIBUTOR)
    variant = query_enum("variant", EXPOSURE_VARIANTS, required=True)
    row = lookup.distributor(distributor_id)
    require_owner(ctx, row, distributor_field="id")
    return ok(diversion_exposure(row, variant))
