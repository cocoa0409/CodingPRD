"""Loss report and grazing contract endpoints (PRD 3.7-3.8)."""
from flask import Blueprint, g, request

import calc
import clock
import db
import serial
import validate as v
from errors import (ERR_CONTRACT_INVALID_STATE, ERR_CONTRACT_WINDOW_CLOSED,
                    ERR_FORBIDDEN, ERR_INSUFFICIENT_HEAD,
                    ERR_REPORT_INVALID_STATE, ERR_STALE_CONTRACT_VERSION,
                    ERR_VALIDATION, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("ops", __name__)

LOSS_TARGETS = ("UNDER_REVIEW", "VERIFIED", "DISMISSED")
_LOSS_TRANSITIONS = {
    ("REPORTED", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "VERIFIED"),
    ("REPORTED", "DISMISSED"),
    ("UNDER_REVIEW", "DISMISSED"),
}

CONTRACT_TARGETS = ("PROPOSED", "ACCEPTED", "ACTIVE", "CANCELLED")
# (from, to) -> allowed actor roles; the endpoint itself allows RM + GC
_CONTRACT_TRANSITIONS = {
    ("DRAFT", "PROPOSED"): {"RanchManager"},
    ("COUNTERED", "PROPOSED"): {"RanchManager"},
    ("PROPOSED", "ACCEPTED"): {"GrazingClient"},
    ("COUNTERED", "ACCEPTED"): {"RanchManager"},
    ("ACCEPTED", "ACTIVE"): {"RanchManager"},
    ("DRAFT", "CANCELLED"): {"RanchManager", "GrazingClient"},
    ("PROPOSED", "CANCELLED"): {"RanchManager", "GrazingClient"},
    ("COUNTERED", "CANCELLED"): {"RanchManager", "GrazingClient"},
    ("ACCEPTED", "CANCELLED"): {"RanchManager", "GrazingClient"},
}


# ------------------------------------------------------------------ loss reports
@bp.post("/api/loss-reports")
def create_loss():
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    loss_date = v.req_dt(b, "loss_date")
    head_lost = v.req_int(b, "head_lost", min=1)
    predator = v.req_enum(b, "predator_type",
                          ("COYOTE", "MOUNTAIN_LION", "BEAR", "DOG", "EAGLE", "UNKNOWN"))
    guardian = v.req_bool(b, "guardian_on_duty")
    flock = db.get_or_404("flocks", flock_id)
    check_flock_active(flock)
    if head_lost > calc.flock_headcount(flock_id):
        raise_err(ERR_INSUFFICIENT_HEAD, "head_lost exceeds flock current_headcount")
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "loss_date": loss_date,
        "head_lost": head_lost,
        "predator_type": predator,
        "guardian_on_duty": guardian,
        "report_status": "REPORTED",
        "reviewed_by_user_id": None,
    })
    db.STORE["losses"][row["id"]] = row
    return success(serial.loss_public(row), status=201)


@bp.get("/api/loss-reports")
def list_losses():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("losses")
    for param, field in (("flock_id", "flock_id"), ("report_status", "report_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.loss_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/loss-reports/<rid>")
def get_loss(rid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("losses", rid)
    return success(serial.loss_public(row))


@bp.post("/api/loss-reports/<rid>/transitions")
def loss_transition(rid):
    require_roles("RanchManager")
    b = v.body()
    to = v.req_enum(b, "to", LOSS_TARGETS)
    row = db.get_or_404("losses", rid)
    cur = row["report_status"]
    if (cur, to) not in _LOSS_TRANSITIONS:
        raise_err(ERR_REPORT_INVALID_STATE,
                  "loss-report transition %s -> %s is not allowed" % (cur, to))
    if to == "UNDER_REVIEW":
        row["report_status"] = "UNDER_REVIEW"
        row["reviewed_by_user_id"] = g.user_id
        db.touch(row)
        return success(serial.loss_public(row))
    row["report_status"] = to
    db.touch(row)
    if to == "VERIFIED":
        _verification_cascade(row)
    return success(serial.loss_public(row))


def _verification_cascade(report):
    """Three links: flock ledger, contract breach sweep, planned-move cleanup."""
    flock_id = report["flock_id"]
    flock = db.STORE["flocks"][flock_id]
    db.touch(flock)  # link 1: headcount recomputed on read; version bumps
    new_headcount = calc.flock_headcount(flock_id)
    # link 2: breach every ACTIVE contract whose min_head now exceeds the headcount
    newly_breached = []
    for c in db.STORE["contracts"].values():
        if (c["flock_id"] == flock_id and c["contract_status"] == "ACTIVE"
                and c["min_head"] > new_headcount and not c["breach_flag"]):
            c["breach_flag"] = True
            db.touch(c)
            newly_breached.append(c["id"])
    # link 3: cancel still-PLANNED moves of the newly breached contracts
    for m in db.STORE["moves"].values():
        if m["contract_id"] in newly_breached and m["move_status"] == "PLANNED":
            m["move_status"] = "CANCELLED"
            db.touch(m)


# ------------------------------------------------------------------ contracts
@bp.post("/api/grazing-contracts")
def create_contract():
    require_roles("RanchManager")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    client = v.req_str(b, "client_org_name")
    parcel = v.req_str(b, "parcel_name")
    start = v.req_dt(b, "service_window_start")
    end = v.req_dt(b, "service_window_end")
    rate = v.req_int(b, "rate_per_head_day_cents", min=1)
    min_head = v.req_int(b, "min_head", min=1)
    max_head = v.req_int(b, "max_head", min=1)
    target = v.req_num(b, "target_cover_reduction_pct", gte=0, lte=100)
    if not start < end:
        raise_err(ERR_VALIDATION, "service_window_start must be strictly before service_window_end")
    if max_head < min_head:
        raise_err(ERR_VALIDATION, "max_head must be at least min_head")
    flock = db.get_or_404("flocks", flock_id)
    check_flock_active(flock)
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "client_org_name": client,
        "parcel_name": parcel,
        "service_window_start": start,
        "service_window_end": end,
        "rate_per_head_day_cents": rate,
        "min_head": min_head,
        "max_head": max_head,
        "target_cover_reduction_pct": target,
        "terms_version": 1,
        "contract_status": "DRAFT",
        "breach_flag": False,
        "achieved_cover_reduction_pct": None,
        "head_days": None,
        "invoice_cents": None,
    })
    db.STORE["contracts"][row["id"]] = row
    return success(serial.contract_public(row), status=201)


@bp.get("/api/grazing-contracts")
def list_contracts():
    require_roles("RanchManager", "GrazingClient")
    limit, offset = v.pagination()
    rows = db.sorted_rows("contracts")
    for param, field in (("flock_id", "flock_id"), ("contract_status", "contract_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.contract_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/grazing-contracts/<cid>")
def get_contract(cid):
    require_roles("RanchManager", "GrazingClient")
    row = db.get_or_404("contracts", cid)
    return success(serial.contract_public(row))


@bp.post("/api/grazing-contracts/<cid>/transitions")
def contract_transition(cid):
    require_roles("RanchManager", "GrazingClient")
    b = v.body()
    to = v.req_enum(b, "to", CONTRACT_TARGETS)
    row = db.get_or_404("contracts", cid)
    cur = row["contract_status"]
    actors = _CONTRACT_TRANSITIONS.get((cur, to))
    if actors is None:
        raise_err(ERR_CONTRACT_INVALID_STATE,
                  "contract transition %s -> %s is not allowed" % (cur, to))
    if g.user_role not in actors:
        raise_err(ERR_FORBIDDEN, "role %s is not the actor for %s -> %s" % (g.user_role, cur, to))
    if to == "PROPOSED" and cur == "DRAFT":
        if calc.flock_headcount(row["flock_id"]) < row["min_head"]:
            raise_err(ERR_INSUFFICIENT_HEAD, "flock current_headcount is below the contract min_head")
    if to == "ACTIVE":
        now = clock.now()
        if not (row["service_window_start"] <= now < row["service_window_end"]):
            raise_err(ERR_CONTRACT_WINDOW_CLOSED, "logical clock is outside the service window")
    row["contract_status"] = to
    db.touch(row)
    return success(serial.contract_public(row))


@bp.post("/api/grazing-contracts/<cid>/counter")
def counter_contract(cid):
    require_roles("GrazingClient")
    b = v.body()
    expected = v.req_int(b, "expected_grazing_contract_version")
    rate = v.opt_int(b, "rate_per_head_day_cents", min=1)
    min_head = v.opt_int(b, "min_head", min=1)
    max_head = v.opt_int(b, "max_head", min=1)
    start = v.opt_dt(b, "service_window_start")
    end = v.opt_dt(b, "service_window_end")
    row = db.get_or_404("contracts", cid)
    # merged terms must stay coherent
    new_min = min_head if min_head is not None else row["min_head"]
    new_max = max_head if max_head is not None else row["max_head"]
    new_start = start if start is not None else row["service_window_start"]
    new_end = end if end is not None else row["service_window_end"]
    if new_max < new_min:
        raise_err(ERR_VALIDATION, "max_head must be at least min_head")
    if not new_start < new_end:
        raise_err(ERR_VALIDATION, "service_window_start must be strictly before service_window_end")
    if row["contract_status"] != "PROPOSED":
        raise_err(ERR_CONTRACT_INVALID_STATE, "only a PROPOSED contract can be countered")
    if expected != row["version"]:
        raise_err(ERR_STALE_CONTRACT_VERSION,
                  "expected_grazing_contract_version does not match the contract's version")
    if rate is not None:
        row["rate_per_head_day_cents"] = rate
    if min_head is not None:
        row["min_head"] = min_head
    if max_head is not None:
        row["max_head"] = max_head
    if start is not None:
        row["service_window_start"] = start
    if end is not None:
        row["service_window_end"] = end
    row["terms_version"] += 1
    row["contract_status"] = "COUNTERED"
    db.touch(row)
    return success(serial.contract_public(row))


@bp.post("/api/grazing-contracts/<cid>/complete")
def complete_contract(cid):
    require_roles("RanchManager")
    b = v.body()
    achieved = v.req_num(b, "achieved_cover_reduction_pct", gte=0, lte=100)
    row = db.get_or_404("contracts", cid)
    if row["contract_status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_INVALID_STATE, "only an ACTIVE contract can be completed")
    if clock.now() < row["service_window_end"]:
        raise_err(ERR_CONTRACT_WINDOW_CLOSED, "the service window has not ended")
    row["achieved_cover_reduction_pct"] = achieved
    head_days, invoice = calc.grazing_invoice(row)
    row["head_days"] = head_days
    row["invoice_cents"] = invoice
    row["contract_status"] = "COMPLETED"
    db.touch(row)
    # cascade: remaining PLANNED moves cancel, ACTIVE moves complete
    for m in db.STORE["moves"].values():
        if m["contract_id"] != cid:
            continue
        if m["move_status"] == "PLANNED":
            m["move_status"] = "CANCELLED"
            db.touch(m)
        elif m["move_status"] == "ACTIVE":
            m["move_status"] = "COMPLETED"
            db.touch(m)
    return success(serial.contract_public(row))
