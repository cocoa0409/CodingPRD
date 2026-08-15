"""Pasture, grazing move, and parasite treatment endpoints (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
import db
import serial
import validate as v
from errors import (ERR_CAPACITY_EXCEEDED, ERR_CONTRACT_INVALID_STATE,
                    ERR_HEAD_OUT_OF_CONTRACT_RANGE, ERR_INSUFFICIENT_HEAD,
                    ERR_MOVE_INVALID_STATE, ERR_PASTURE_OVERLAP,
                    ERR_VALIDATION, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("grazing", __name__)

MOVE_TARGETS = ("ACTIVE", "COMPLETED", "CANCELLED")
_MOVE_TRANSITIONS = {
    ("PLANNED", "ACTIVE"),
    ("ACTIVE", "COMPLETED"),
    ("PLANNED", "CANCELLED"),
}


# ------------------------------------------------------------------ pastures
@bp.post("/api/pastures")
def create_pasture():
    require_roles("RanchManager")
    b = v.body()
    name = v.req_str(b, "pasture_name")
    acres = v.req_num(b, "acres", gt=0)
    capacity = v.req_int(b, "carrying_capacity_head", min=1)
    rest_days = v.opt_int(b, "rest_days", default=21, min=0)
    if any(p["pasture_name"] == name for p in db.STORE["pastures"].values()):
        raise_err(ERR_VALIDATION, "pasture_name must be unique")
    row = db.new_row()
    row.update({
        "pasture_name": name,
        "acres": acres,
        "carrying_capacity_head": capacity,
        "rest_days": rest_days,
    })
    db.STORE["pastures"][row["id"]] = row
    return success(serial.pasture_public(row), status=201)


@bp.get("/api/pastures/<pid>")
def get_pasture(pid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("pastures", pid)
    return success(serial.pasture_public(row))


# ------------------------------------------------------------------ moves
@bp.post("/api/grazing-moves")
def create_move():
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    start = v.req_dt(b, "move_start")
    end = v.req_dt(b, "move_end")
    head = v.req_int(b, "head_count", min=1)
    has_pasture = v.present(b, "pasture_id")
    has_contract = v.present(b, "contract_id")
    if has_pasture == has_contract:
        raise_err(ERR_VALIDATION, "exactly one of pasture_id or contract_id must be supplied")
    if not start < end:
        raise_err(ERR_VALIDATION, "move_start must be strictly before move_end")
    flock = db.get_or_404("flocks", flock_id)
    pasture = db.get_or_404("pastures", b["pasture_id"]) if has_pasture else None
    contract = db.get_or_404("contracts", b["contract_id"]) if has_contract else None
    check_flock_active(flock)
    if contract is not None and contract["contract_status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_INVALID_STATE, "contract moves require an ACTIVE contract")
    if pasture is not None:
        for other in db.STORE["moves"].values():
            if (other["pasture_id"] == pasture["id"]
                    and other["move_status"] in ("PLANNED", "ACTIVE")
                    and other["move_start"] < end and start < other["move_end"]):
                raise_err(ERR_PASTURE_OVERLAP, "move window overlaps another planned/active move on this pasture")
        if head > pasture["carrying_capacity_head"]:
            raise_err(ERR_CAPACITY_EXCEEDED, "head_count exceeds pasture carrying capacity")
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "pasture_id": pasture["id"] if pasture else None,
        "contract_id": contract["id"] if contract else None,
        "move_start": start,
        "move_end": end,
        "head_count": head,
        "move_status": "PLANNED",
    })
    db.STORE["moves"][row["id"]] = row
    return success(serial.move_public(row), status=201)


@bp.get("/api/grazing-moves")
def list_moves():
    require_roles("RanchManager", "RangeHand", "GrazingClient")
    limit, offset = v.pagination()
    rows = db.sorted_rows("moves")
    for param, field in (("flock_id", "flock_id"), ("pasture_id", "pasture_id"),
                         ("contract_id", "contract_id"), ("move_status", "move_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.move_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/grazing-moves/<mid>")
def get_move(mid):
    require_roles("RanchManager", "RangeHand", "GrazingClient")
    row = db.get_or_404("moves", mid)
    return success(serial.move_public(row))


@bp.post("/api/grazing-moves/<mid>/transitions")
def move_transition(mid):
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    to = v.req_enum(b, "to", MOVE_TARGETS)
    row = db.get_or_404("moves", mid)
    cur = row["move_status"]
    if (cur, to) not in _MOVE_TRANSITIONS:
        raise_err(ERR_MOVE_INVALID_STATE, "move transition %s -> %s is not allowed" % (cur, to))
    if to == "ACTIVE":
        now = clock.now()
        if not (row["move_start"] <= now < row["move_end"]):
            raise_err(ERR_MOVE_INVALID_STATE, "logical clock is outside the move window")
        if row["contract_id"] is not None:
            contract = db.STORE["contracts"][row["contract_id"]]
            if contract["contract_status"] != "ACTIVE":
                raise_err(ERR_CONTRACT_INVALID_STATE, "contract is not ACTIVE")
            if not (contract["min_head"] <= row["head_count"] <= contract["max_head"]):
                raise_err(ERR_HEAD_OUT_OF_CONTRACT_RANGE,
                          "head_count outside the contract head band")
        if row["head_count"] > calc.flock_headcount(row["flock_id"]):
            raise_err(ERR_INSUFFICIENT_HEAD, "head_count exceeds flock current_headcount")
    row["move_status"] = to
    db.touch(row)
    return success(serial.move_public(row))


# ------------------------------------------------------------------ treatments
@bp.post("/api/parasite-treatments")
def create_treatment():
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    product = v.req_str(b, "product_name")
    treatment_date = v.req_dt(b, "treatment_date")
    withdrawal_days = v.req_int(b, "withdrawal_days", min=0)
    fec_before = v.req_int(b, "fecal_egg_count_before", min=0)
    flock = db.get_or_404("flocks", flock_id)
    check_flock_active(flock)
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "product_name": product,
        "treatment_date": treatment_date,
        "withdrawal_days": withdrawal_days,
        "withdrawal_until": treatment_date + timedelta(days=withdrawal_days),
        "fecal_egg_count_before": fec_before,
        "fecal_egg_count_after": None,
    })
    db.STORE["treatments"][row["id"]] = row
    return success(serial.treatment_public(row), status=201)


@bp.get("/api/parasite-treatments")
def list_treatments():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("treatments")
    flock_id = request.args.get("flock_id")
    if flock_id is not None:
        rows = [r for r in rows if r["flock_id"] == flock_id]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.treatment_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/parasite-treatments/<tid>")
def get_treatment(tid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("treatments", tid)
    return success(serial.treatment_public(row))


@bp.post("/api/parasite-treatments/<tid>/follow-up")
def treatment_follow_up(tid):
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    after = v.req_int(b, "fecal_egg_count_after", min=0)
    row = db.get_or_404("treatments", tid)
    row["fecal_egg_count_after"] = after
    db.touch(row)
    return success(serial.treatment_public(row))
