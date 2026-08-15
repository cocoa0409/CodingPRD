"""Loss events and pool-wide allocation (PRD 3.7)."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_NO_ALLOCATABLE, ERR_LOSS_EXCEEDS, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, body, req_int, req_dt, touch, paginate, ALL_ROLES,
)
from response import success
from services import calc

bp = Blueprint("loss_events", __name__)

ELIGIBLE = {"ACTIVE", "EXCEPTION"}


def _get_event(lid):
    ev = db.loss_events.get(lid)
    if ev is None:
        not_found("LossEvent")
    return ev


def _own_originator_of_offering(uid, offering):
    agreement = db.agreements[offering["servicing_agreement_id"]]
    if agreement["originator_id"] != uid:
        raise_err(ERR_NOT_OWNER, "OriginatorUser must own the agreement behind the offering")
    return agreement


@bp.post("/network/loss-events")
def create_loss_event():
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    b = body()
    oid = b.get("offering_id")
    if oid is not None and oid not in db.offerings:
        not_found("ParticipationOffering")
    o = db.offerings.get(oid) if oid is not None else None
    if o is not None:
        _own_originator_of_offering(uid, o)
    if oid is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: offering_id")
    amount = req_int(b, "loss_amount_cents", minimum=1)
    defaulted = req_dt(b, "defaulted_at")
    ev = db.insert("loss_event", {
        "offering_id": oid,
        "loss_amount_cents": amount,
        "defaulted_at": defaulted,
        "loss_basis_used": None,
        "allocations": None,
        "status": "REPORTED",
    })
    return success(ser.loss_event(ev), 201)


@bp.get("/network/loss-events/<lid>")
def get_loss_event(lid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.loss_event(_get_event(lid)))


@bp.get("/network/loss-events")
def list_loss_events():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.loss_events.values())
    oid = request.args.get("offering_id")
    if oid is not None:
        items = [e for e in items if e["offering_id"] == oid]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    page, meta = paginate(items, ser.loss_event)
    return success(page, 200, meta)


@bp.post("/network/loss-events/<lid>/allocate")
def allocate_loss_event(lid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    ev = _get_event(lid)
    o = db.offerings[ev["offering_id"]]
    _own_originator_of_offering(uid, o)
    if ev["status"] != "REPORTED":
        invalid_state("LossEvent must be REPORTED to allocate")
    eligible = sorted(
        (c for c in db.certificates.values()
         if c["offering_id"] == o["id"] and c["status"] in ELIGIBLE),
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    if not eligible:
        raise_err(ERR_NO_ALLOCATABLE, "No certificates in ACTIVE or EXCEPTION can absorb the loss")
    basis = o["loss_basis"]
    total_weight = sum(
        c["outstanding_principal_cents"] if basis == "OUTSTANDING" else c["committed_amount_cents"]
        for c in eligible
    )
    if ev["loss_amount_cents"] > total_weight:
        raise_err(ERR_LOSS_EXCEEDS, "loss_amount_cents exceeds the total basis weight of eligible certificates")
    allocations, shares = calc.allocate_loss(ev["loss_amount_cents"], eligible, basis)
    ev["loss_basis_used"] = basis
    ev["allocations"] = allocations
    ev["status"] = "ALLOCATED"
    touch("loss_event", ev)
    for c in eligible:
        amt = shares[c["id"]]
        if amt:
            c["outstanding_principal_cents"] -= amt
            c["cumulative_loss_cents"] += amt
            touch("certificate", c)
    return success(ser.loss_event(ev))
