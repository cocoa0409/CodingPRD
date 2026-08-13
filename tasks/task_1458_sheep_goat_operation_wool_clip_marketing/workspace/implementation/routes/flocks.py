"""Flock endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
import serial
import validate as v
from errors import (ERR_FLOCK_BUSY, ERR_FLOCK_RETIRED, ERR_VALIDATION, raise_err)
from middleware import require_roles
from response import success

bp = Blueprint("flocks", __name__)

READ_ROLES = ("RanchManager", "RangeHand", "WoolPoolOperator", "GrazingClient")

# busy-children sweep sets for retirement (PRD 3.1)
_BUSY_SEASON = {"PLANNED", "BREEDING", "GESTATION", "LAMBING", "WEANING"}
_BUSY_MOVE = {"PLANNED", "ACTIVE"}
_BUSY_SHEARING = {"SCHEDULED", "IN_PROGRESS"}
_BUSY_DELIVERY = {"PENDING", "LOADED"}
_BUSY_CONTRACT = {"DRAFT", "PROPOSED", "COUNTERED", "ACCEPTED", "ACTIVE"}


def check_flock_active(flock):
    if flock["flock_status"] != "ACTIVE":
        raise_err(ERR_FLOCK_RETIRED, "flock %s is RETIRED" % flock["id"])


@bp.post("/api/flocks")
def create_flock():
    require_roles("RanchManager")
    b = v.body()
    name = v.req_str(b, "flock_name")
    species = v.req_enum(b, "species", ("SHEEP", "GOAT"))
    baseline = v.req_int(b, "baseline_headcount", min=1)
    guardian = v.opt_int(b, "guardian_dog_count", default=0, min=0)
    if any(f["flock_name"] == name for f in db.STORE["flocks"].values()):
        raise_err(ERR_VALIDATION, "flock_name must be unique across all flocks")
    row = db.new_row()
    row.update({
        "flock_name": name,
        "species": species,
        "flock_status": "ACTIVE",
        "baseline_headcount": baseline,
        "guardian_dog_count": guardian,
    })
    db.STORE["flocks"][row["id"]] = row
    return success(serial.flock_public(row), status=201)


@bp.get("/api/flocks")
def list_flocks():
    require_roles(*READ_ROLES)
    limit, offset = v.pagination()
    rows = db.sorted_rows("flocks")
    species = request.args.get("species")
    if species is not None:
        rows = [r for r in rows if r["species"] == species]
    status = request.args.get("flock_status")
    if status is not None:
        rows = [r for r in rows if r["flock_status"] == status]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.flock_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/flocks/<fid>")
def get_flock(fid):
    require_roles(*READ_ROLES)
    row = db.get_or_404("flocks", fid)
    return success(serial.flock_public(row))


@bp.post("/api/flocks/<fid>/retire")
def retire_flock(fid):
    require_roles("RanchManager")
    row = db.get_or_404("flocks", fid)
    if row["flock_status"] != "ACTIVE":
        raise_err(ERR_FLOCK_RETIRED, "flock %s is already RETIRED" % fid)
    fid_ = row["id"]
    if any(s["flock_id"] == fid_ and s["season_status"] in _BUSY_SEASON
           for s in db.STORE["seasons"].values()):
        raise_err(ERR_FLOCK_BUSY, "flock has an open breeding season")
    if any(m["flock_id"] == fid_ and m["move_status"] in _BUSY_MOVE
           for m in db.STORE["moves"].values()):
        raise_err(ERR_FLOCK_BUSY, "flock has a planned or active grazing move")
    if any(e["flock_id"] == fid_ and e["shearing_status"] in _BUSY_SHEARING
           for e in db.STORE["shearings"].values()):
        raise_err(ERR_FLOCK_BUSY, "flock has a scheduled or in-progress shearing event")
    if any(s["flock_id"] == fid_ and s["delivery_status"] in _BUSY_DELIVERY
           for s in db.STORE["sales"].values()):
        raise_err(ERR_FLOCK_BUSY, "flock has an undelivered livestock sale")
    if any(c["flock_id"] == fid_ and c["contract_status"] in _BUSY_CONTRACT
           for c in db.STORE["contracts"].values()):
        raise_err(ERR_FLOCK_BUSY, "flock has a non-terminal grazing contract")
    row["flock_status"] = "RETIRED"
    db.touch(row)
    return success(serial.flock_public(row))
