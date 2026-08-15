"""Dispatch batch endpoints: run auto-callout, get, list per district."""

from flask import Blueprint

import domain
from db import STORE, new_entity, public, now_iso
from errors import raise_err, ERR_DISTRICT_NOT_FOUND, ERR_DISPATCH_BATCH_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from util import parse_date
from validate import body, req_str, opt_date

bp = Blueprint("dispatch", __name__)


@bp.route("/dispatch-batches", methods=["POST"])
def create_dispatch_batch():
    _, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    run_for_date = opt_date(data, "run_for_date")
    require_role(role, ["DistrictAdmin"])
    district = STORE.districts.get(district_id)
    if district is None:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    run_date = parse_date(run_for_date) if run_for_date else domain.now().date()
    counter = domain.run_dispatch_batch(district, run_date)
    b = new_entity(STORE.dispatch_batches, {
        "district_id": district_id,
        "run_for_date": run_for_date,
        "executed_at": now_iso(),
        "absences_considered": counter["considered"],
        "offers_created": counter["created"],
        "offers_expired": counter["expired"],
        "absences_marked_unfilled": counter["unfilled"],
    }, common=False)
    return ok(public(b), status=201)


@bp.route("/dispatch-batches/<bid>", methods=["GET"])
def get_dispatch_batch(bid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    b = STORE.dispatch_batches.get(bid)
    if b is None:
        raise_err(ERR_DISPATCH_BATCH_NOT_FOUND, "dispatch batch id does not exist")
    return ok(public(b))


@bp.route("/districts/<did>/dispatch-batches", methods=["GET"])
def list_district_batches(did):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if did not in STORE.districts:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    items = sorted((b for b in STORE.dispatch_batches.values() if b["district_id"] == did),
                   key=lambda b: (b["created_at"], b["_seq"]))
    page, meta = paginated(items)
    return ok([public(b) for b in page], pagination=meta)
