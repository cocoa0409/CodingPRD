"""Wool lot, core test, consignment, and pool statement endpoints (PRD 3.4-3.5)."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import db
import serial
import util
import validate as v
from errors import (ERR_CONSIGNMENT_ALREADY_OPEN, ERR_CONSIGNMENT_INVALID_STATE,
                    ERR_CORE_TEST_INVALID_STATE, ERR_CORE_TEST_SOD,
                    ERR_DUPLICATE_ACTIVE_TEST, ERR_FORBIDDEN, ERR_LOT_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_STALE_LOT_VERSION, ERR_VALIDATION,
                    ERR_WEIGHT_OVER_ALLOCATED, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("wool", __name__)

LOT_TARGETS = ("REGRADING",)
CORE_TEST_TARGETS = ("LOCKED", "REJECTED")
CONSIGNMENT_TARGETS = ("ACCEPTED", "REJECTED", "ADVANCED", "WITHDRAWN", "SETTLED")

_ACTIVE_TEST = {"SUBMITTED", "RESULTED", "LOCKED"}
_OPEN_CONSIGNMENT = {"TENDERED", "ACCEPTED", "ADVANCED", "SOLD"}


def _clip_of(lot):
    return db.STORE["clips"][lot["clip_id"]]


def _has_active_test(lot_id):
    return any(t["lot_id"] == lot_id and t["test_status"] in _ACTIVE_TEST
               for t in db.STORE["core_tests"].values())


def _open_consignment(lot_id):
    for c in db.STORE["consignments"].values():
        if c["lot_id"] == lot_id and c["consignment_status"] in _OPEN_CONSIGNMENT:
            return c
    return None


# ------------------------------------------------------------------ lots
@bp.post("/api/wool-lots")
def create_lot():
    require_roles("RanchManager")
    b = v.body()
    clip_id = v.req_str(b, "clip_id")
    lot_code = v.req_str(b, "lot_code")
    weight = v.req_num(b, "weight_lbs", gt=0)
    clip = db.get_or_404("clips", clip_id)
    if any(l["clip_id"] == clip_id and l["lot_code"] == lot_code
           for l in db.STORE["lots"].values()):
        raise_err(ERR_VALIDATION, "lot_code must be unique within the clip")
    flock = db.STORE["flocks"][clip["flock_id"]]
    check_flock_active(flock)
    _, unallocated, _, _ = calc.clip_aggregates(clip)
    if weight > unallocated:
        raise_err(ERR_WEIGHT_OVER_ALLOCATED, "weight_lbs exceeds the clip's unallocated weight")
    row = db.new_row()
    row.update({
        "clip_id": clip_id,
        "lot_code": lot_code,
        "weight_lbs": weight,
        "estimated_micron": None,
        "certified_micron": None,
        "certified_yield_pct": None,
        "lot_status": "DRAFT",
        "provisional_value_cents": None,
        "certified_value_cents": None,
    })
    db.STORE["lots"][row["id"]] = row
    return success(serial.lot_public(row), status=201)


@bp.get("/api/wool-lots")
def list_lots():
    require_roles("RanchManager", "RangeHand", "WoolPoolOperator")
    limit, offset = v.pagination()
    rows = db.sorted_rows("lots")
    for param, field in (("clip_id", "clip_id"), ("lot_status", "lot_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.lot_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/wool-lots/<lid>")
def get_lot(lid):
    require_roles("RanchManager", "RangeHand", "WoolPoolOperator")
    row = db.get_or_404("lots", lid)
    return success(serial.lot_public(row))


@bp.post("/api/wool-lots/<lid>/grade")
def grade_lot(lid):
    require_roles("RanchManager")
    b = v.body()
    micron = v.req_num(b, "estimated_micron", gt=0)
    row = db.get_or_404("lots", lid)
    if row["lot_status"] != "DRAFT":
        raise_err(ERR_LOT_INVALID_STATE, "only a DRAFT lot can be graded")
    row["estimated_micron"] = micron
    row["provisional_value_cents"] = calc.provisional_value(row)
    row["lot_status"] = "GRADED"
    db.touch(row)
    return success(serial.lot_public(row))


@bp.post("/api/wool-lots/<lid>/transitions")
def lot_transition(lid):
    require_roles("RanchManager")
    b = v.body()
    to = v.req_enum(b, "to", LOT_TARGETS)
    row = db.get_or_404("lots", lid)
    if row["lot_status"] != "GRADED":
        raise_err(ERR_LOT_INVALID_STATE,
                  "lot transition %s -> %s is not allowed" % (row["lot_status"], to))
    if _has_active_test(lid):
        raise_err(ERR_DUPLICATE_ACTIVE_TEST, "lot has a core test in SUBMITTED, RESULTED, or LOCKED")
    row["lot_status"] = "REGRADING"
    db.touch(row)
    return success(serial.lot_public(row))


@bp.post("/api/wool-lots/<lid>/regrade")
def regrade_lot(lid):
    require_roles("RanchManager")
    b = v.body()
    micron = v.req_num(b, "estimated_micron", gt=0)
    expected = v.req_int(b, "expected_wool_lot_version")
    row = db.get_or_404("lots", lid)
    if row["lot_status"] != "REGRADING":
        raise_err(ERR_LOT_INVALID_STATE, "only a REGRADING lot can be regraded")
    if expected != row["version"]:
        raise_err(ERR_STALE_LOT_VERSION, "expected_wool_lot_version does not match the lot's version")
    row["estimated_micron"] = micron
    row["provisional_value_cents"] = calc.provisional_value(row)
    row["lot_status"] = "GRADED"
    db.touch(row)
    return success(serial.lot_public(row))


@bp.delete("/api/wool-lots/<lid>")
def delete_lot(lid):
    require_roles("RanchManager")
    row = db.get_or_404("lots", lid)
    if row["lot_status"] != "DRAFT":
        raise_err(ERR_LOT_INVALID_STATE, "only a DRAFT lot can be deleted")
    del db.STORE["lots"][lid]
    return "", 204


# ------------------------------------------------------------------ core tests
@bp.post("/api/core-tests")
def create_core_test():
    require_roles("WoolPoolOperator")
    b = v.body()
    lot_id = v.req_str(b, "lot_id")
    lab_ref = v.req_str(b, "lab_ref")
    lot = db.get_or_404("lots", lot_id)
    if lot["lot_status"] not in ("GRADED", "CONSIGNED"):
        raise_err(ERR_LOT_INVALID_STATE, "core tests require a GRADED or CONSIGNED lot")
    if _has_active_test(lot_id):
        raise_err(ERR_DUPLICATE_ACTIVE_TEST, "lot already has a core test in SUBMITTED, RESULTED, or LOCKED")
    row = db.new_row()
    row.update({
        "lot_id": lot_id,
        "lab_ref": lab_ref,
        "test_status": "SUBMITTED",
        "measured_micron": None,
        "clean_yield_pct": None,
        "vegetable_matter_pct": None,
        "submitted_by_user_id": g.user_id,
        "locked_by_user_id": None,
    })
    db.STORE["core_tests"][row["id"]] = row
    return success(serial.core_test_public(row), status=201)


@bp.get("/api/core-tests")
def list_core_tests():
    require_roles("RanchManager", "WoolPoolOperator")
    limit, offset = v.pagination()
    rows = db.sorted_rows("core_tests")
    for param, field in (("lot_id", "lot_id"), ("test_status", "test_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.core_test_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/core-tests/<tid>")
def get_core_test(tid):
    require_roles("RanchManager", "WoolPoolOperator")
    row = db.get_or_404("core_tests", tid)
    return success(serial.core_test_public(row))


@bp.post("/api/core-tests/<tid>/results")
def post_results(tid):
    require_roles("WoolPoolOperator")
    b = v.body()
    micron = v.req_num(b, "measured_micron", gt=0)
    yld = v.req_num(b, "clean_yield_pct", gte=0, lte=100)
    vm = v.req_num(b, "vegetable_matter_pct", gte=0, lte=100)
    row = db.get_or_404("core_tests", tid)
    if row["test_status"] != "SUBMITTED":
        raise_err(ERR_CORE_TEST_INVALID_STATE, "results can only be posted on a SUBMITTED test")
    row["measured_micron"] = micron
    row["clean_yield_pct"] = yld
    row["vegetable_matter_pct"] = vm
    row["test_status"] = "RESULTED"
    db.touch(row)
    return success(serial.core_test_public(row))


@bp.post("/api/core-tests/<tid>/transitions")
def core_test_transition(tid):
    require_roles("RanchManager")
    b = v.body()
    to = v.req_enum(b, "to", CORE_TEST_TARGETS)
    row = db.get_or_404("core_tests", tid)
    cur = row["test_status"]
    if (cur, to) not in {("RESULTED", "LOCKED"), ("SUBMITTED", "REJECTED"), ("RESULTED", "REJECTED")}:
        raise_err(ERR_CORE_TEST_INVALID_STATE,
                  "core-test transition %s -> %s is not allowed" % (cur, to))
    if to == "LOCKED":
        if g.user_id == row["submitted_by_user_id"]:
            raise_err(ERR_CORE_TEST_SOD, "the locking manager must differ from the submitting operator")
        row["test_status"] = "LOCKED"
        row["locked_by_user_id"] = g.user_id
        db.touch(row)
        # cascade link 1: reprice the lot on a certified basis
        lot = db.STORE["lots"][row["lot_id"]]
        lot["certified_micron"] = row["measured_micron"]
        lot["certified_yield_pct"] = row["clean_yield_pct"]
        value, _grade = calc.certified_value(lot, row["measured_micron"], row["clean_yield_pct"])
        lot["certified_value_cents"] = value
        db.touch(lot)
        # cascade link 2: reprice open consignments; pending clawback when ADVANCED
        for cons in db.STORE["consignments"].values():
            if cons["lot_id"] != lot["id"] or cons["consignment_status"] not in ("ACCEPTED", "ADVANCED"):
                continue
            if cons["consignment_status"] == "ADVANCED":
                cover = util.cents(Decimal("0.70") * Decimal(lot["certified_value_cents"]))
                cons["pending_clawback_cents"] = max(0, cons["advance_cents"] - cover)
            db.touch(cons)
    else:  # REJECTED
        row["test_status"] = "REJECTED"
        db.touch(row)
    return success(serial.core_test_public(row))


# ------------------------------------------------------------------ consignments
@bp.post("/api/consignments")
def create_consignment():
    require_roles("RanchManager")
    b = v.body()
    lot_id = v.req_str(b, "lot_id")
    pool_ref = v.req_str(b, "pool_ref")
    lot = db.get_or_404("lots", lot_id)
    if lot["lot_status"] not in ("GRADED", "WITHDRAWN"):
        raise_err(ERR_LOT_INVALID_STATE, "only a GRADED or WITHDRAWN lot can be tendered")
    if _open_consignment(lot_id) is not None:
        raise_err(ERR_CONSIGNMENT_ALREADY_OPEN, "lot already has an open consignment")
    row = db.new_row()
    row.update({
        "lot_id": lot_id,
        "pool_ref": pool_ref,
        "consignment_status": "TENDERED",
        "advance_cents": 0,
        "sale_gross_cents": None,
        "pool_fee_cents": None,
        "settlement_cents": None,
        "pending_clawback_cents": 0,
        "clawback_cents": 0,
    })
    db.STORE["consignments"][row["id"]] = row
    lot["lot_status"] = "CONSIGNED"
    db.touch(lot)
    return success(serial.consignment_public(row), status=201)


@bp.get("/api/consignments")
def list_consignments():
    require_roles("RanchManager", "WoolPoolOperator")
    limit, offset = v.pagination()
    rows = db.sorted_rows("consignments")
    for param, field in (("lot_id", "lot_id"), ("pool_ref", "pool_ref"),
                         ("consignment_status", "consignment_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.consignment_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/consignments/<cid>")
def get_consignment(cid):
    require_roles("RanchManager", "WoolPoolOperator")
    row = db.get_or_404("consignments", cid)
    return success(serial.consignment_public(row))


def _consignment_actor_check(to):
    """Per-transition actor: pool operator drives the pool side; manager withdraws."""
    if to in ("ACCEPTED", "REJECTED", "ADVANCED", "SETTLED"):
        if g.user_role != "WoolPoolOperator":
            raise_err(ERR_FORBIDDEN, "transition %s is performed by WoolPoolOperator" % to)
    elif to == "WITHDRAWN":
        if g.user_role != "RanchManager":
            raise_err(ERR_FORBIDDEN, "transition WITHDRAWN is performed by RanchManager")


@bp.post("/api/consignments/<cid>/transitions")
def consignment_transition(cid):
    require_roles("RanchManager", "WoolPoolOperator")
    b = v.body()
    to = v.req_enum(b, "to", CONSIGNMENT_TARGETS)
    row = db.get_or_404("consignments", cid)
    cur = row["consignment_status"]
    allowed_from = {
        "ACCEPTED": {"TENDERED"},
        "REJECTED": {"TENDERED"},
        "ADVANCED": {"ACCEPTED"},
        "WITHDRAWN": {"ACCEPTED", "ADVANCED"},
        "SETTLED": {"SOLD"},
    }[to]
    if cur not in allowed_from:
        raise_err(ERR_CONSIGNMENT_INVALID_STATE,
                  "consignment transition %s -> %s is not allowed" % (cur, to))
    _consignment_actor_check(to)
    lot = db.STORE["lots"][row["lot_id"]]
    if to == "ACCEPTED":
        row["consignment_status"] = "ACCEPTED"
        db.touch(row)
    elif to == "REJECTED":
        row["consignment_status"] = "REJECTED"
        db.touch(row)
        lot["lot_status"] = "GRADED"
        db.touch(lot)
    elif to == "ADVANCED":
        row["consignment_status"] = "ADVANCED"
        row["advance_cents"] = calc.advance_amount(lot)
        db.touch(row)
    elif to == "WITHDRAWN":
        if cur == "ADVANCED":
            row["clawback_cents"] = row["advance_cents"]
        row["consignment_status"] = "WITHDRAWN"
        db.touch(row)
        lot["lot_status"] = "WITHDRAWN"
        db.touch(lot)
    elif to == "SETTLED":
        fee = calc.pool_fee_cents(row["pool_ref"], row["sale_gross_cents"])
        row["pool_fee_cents"] = fee
        row["settlement_cents"] = row["sale_gross_cents"] - fee - row["advance_cents"]
        row["consignment_status"] = "SETTLED"
        db.touch(row)
        lot["lot_status"] = "SETTLED"
        db.touch(lot)
    return success(serial.consignment_public(row))


@bp.post("/api/consignments/<cid>/sell")
def sell_consignment(cid):
    require_roles("WoolPoolOperator")
    b = v.body()
    gross = v.req_int(b, "sale_gross_cents", min=0)
    row = db.get_or_404("consignments", cid)
    if row["consignment_status"] != "ADVANCED":
        raise_err(ERR_CONSIGNMENT_INVALID_STATE, "only an ADVANCED consignment can be sold")
    row["sale_gross_cents"] = gross
    row["consignment_status"] = "SOLD"
    db.touch(row)
    lot = db.STORE["lots"][row["lot_id"]]
    lot["lot_status"] = "SOLD"
    db.touch(lot)
    return success(serial.consignment_public(row))


# ------------------------------------------------------------------ pool statements
@bp.get("/api/pool-statements/<pool_ref>")
def get_pool_statement(pool_ref):
    require_roles("RanchManager", "WoolPoolOperator")
    statement = calc.pool_statement(pool_ref)
    if statement is None:
        raise_err(ERR_NOT_FOUND, "unknown pool_ref: %s" % pool_ref)
    return success(statement)
