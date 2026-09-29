from flask import Blueprint

import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, own
from routes.common import (check_account_standing, fk, listing, lookup, unique)
from services import projections as proj

bp = Blueprint("distributors", __name__)


@bp.post("/distributors")
def create_distributor():
    authenticate("ProgramAdmin")
    body = v.body()
    legal_name = v.req_str(body, "legal_name")
    state_code = v.req_str(body, "state_code", pattern=v.STATE_RE)
    permit_number = v.req_str(body, "permit_number")
    status = v.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")
    unique(db.distributors, "permit_number", permit_number,
           "ERR_DUPLICATE_PERMIT_NUMBER")
    rec = db.new_record({
        "legal_name": legal_name,
        "state_code": state_code,
        "permit_number": permit_number,
        "status": status,
        "deposits_initiated_cents": 0,
        "containers_initiated_count": 0,
    })
    db.distributors[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/distributors/<rid>")
def get_distributor(rid):
    authenticate("ProgramAdmin", "DistributorAgent")
    own(distributor_id=rid)
    rec = lookup("distributor", rid)
    return response.obj(db.public(rec))


@bp.post("/distributors/<rid>/deposit-initiations")
def create_deposit_initiation(rid):
    authenticate("DistributorAgent", "ProgramAdmin")
    own(distributor_id=rid)
    dist = lookup("distributor", rid)
    body = v.body()
    product = fk("product", body, "product_id")
    if product is not None:
        own(distributor_id=product.get("distributor_id"))
    period = fk("period", body, "period_id")
    v.req_str(body, "product_id")
    container_count = v.req_int(body, "container_count", minimum=1)
    v.req_str(body, "period_id")
    if period["status"] != "OPEN":
        fail("ERR_INVALID_PERIOD_STATE", "The reporting quarter is not OPEN.")
    if product["registration_state"] != "REGISTERED":
        fail("ERR_PRODUCT_NOT_REGISTERED", "The label is not REGISTERED.")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_SUSPENDED", "The distributor is suspended.")

    amount = container_count * product["deposit_cents"]
    entry = proj.append_ledger_entry(period, "DEPOSIT_INITIATED", amount,
                                     container_count, "DISTRIBUTOR", dist["id"])
    dist["deposits_initiated_cents"] += amount
    dist["containers_initiated_count"] += container_count
    touch(dist)
    proj.replay_period(period)
    return response.obj(db.public(entry), 201)


@bp.get("/distributors/<rid>/deposit-initiations")
def list_deposit_initiations(rid):
    authenticate("ProgramAdmin", "DistributorAgent")
    own(distributor_id=rid)
    dist = lookup("distributor", rid)
    rows = db.ordered(
        db.ledger_entries,
        lambda e: (e["source_kind"] == "DISTRIBUTOR"
                   and e["source_ref_id"] == dist["id"]
                   and e["entry_type"] == "DEPOSIT_INITIATED"),
    )
    return listing(rows)
