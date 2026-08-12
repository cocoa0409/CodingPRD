"""ProductionLot and CureTest endpoints."""
from flask import Blueprint, request, g

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_TEST_INVALID_STATE,
    ERR_LOT_INVALID_STATE, ERR_LOT_ON_HOLD, ERR_RETEST_LIMIT_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES, ERR_BOND_STRENGTH_BELOW_SPEC,
    ERR_FORMULATION_NOT_EFFECTIVE,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_enum, f_list,
)
from services import (
    new_entity, touch, get_lot, get_test, ser_lot, ser_test, sorted_rows,
    assess_test,
)

bp = Blueprint("quality", __name__)

TEST_METHODS = ["QUICK", "FULL"]


# ---------------------------------------------------------------------------
# ProductionLot
# ---------------------------------------------------------------------------

@bp.get("/api/production-lots")
@require_roles(*ALL_ROLES)
def list_lots():
    limit, offset = pagination_params()
    rows = list(store.lots.values())
    bid = request.args.get("batch_id")
    fid = request.args.get("formulation_id")
    if bid is not None:
        rows = [l for l in rows if l["batch_id"] == bid]
    if fid is not None:
        rows = [l for l in rows if l["formulation_id"] == fid]
    return ok_list([ser_lot(l) for l in sorted_rows(rows)], limit, offset)


@bp.get("/api/production-lots/<lid>")
@require_roles(*ALL_ROLES)
def get_one_lot(lid):
    return ok(ser_lot(get_lot(lid)), 200)


@bp.post("/api/production-lots/<lid>/cure-tests")
@require_roles("QATechnician")
def create_cure_test(lid):
    # schema first (priority 3), then path existence (priority 4)
    b = body_json()
    method = f_enum(b, "method", TEST_METHODS)
    specimens = f_list(b, "specimens")
    for s in specimens:
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, "specimens must be numbers (MPa)", 400)
    if method == "QUICK" and len(specimens) != 1:
        raise ApiError(ERR_INVALID_REQUEST, "QUICK requires exactly 1 specimen", 400)
    if method == "FULL" and len(specimens) != 5:
        raise ApiError(ERR_INVALID_REQUEST, "FULL requires exactly 5 specimens", 400)
    lot = get_lot(lid)
    if lot["qa_status"] not in ("AWAITING_TEST", "TESTING"):
        raise ApiError(
            ERR_LOT_INVALID_STATE,
            "Lot qa_status must be AWAITING_TEST or TESTING",
            409,
        )
    t = new_entity()
    t.update({
        "lot_id": lid,
        "method": method,
        "specimens": [float(s) for s in specimens],
        "technician_id": g.user_id,
        "evaluated_value_mpa": None,
        "assessment_pass": None,
        "status": "RECORDED",
    })
    store.tests[t["id"]] = t
    if lot["qa_status"] == "AWAITING_TEST":
        lot["qa_status"] = "TESTING"
        touch(lot)
    return ok(ser_test(t), 201)


def _latest_accepted_test(lot_id):
    accepted = [t for t in store.tests.values()
                if t["lot_id"] == lot_id and t["status"] == "ACCEPTED"]
    if not accepted:
        return None
    return max(accepted, key=lambda t: (t["updated_at"], t.get("_seq", 0)))


@bp.post("/api/production-lots/<lid>/release")
@require_roles("QAManager")
def release_lot(lid):
    body_json()
    lot = get_lot(lid)
    # evaluated in the PRD-pinned order
    if lot["qa_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_LOT_INVALID_STATE, "release requires UNDER_REVIEW", 409)
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_LOT_ON_HOLD, "Lot hold_status must be CLEAR", 409)
    accepted = _latest_accepted_test(lid)
    if (accepted is None or accepted["method"] != "FULL"
            or accepted["assessment_pass"] is not True):
        raise ApiError(
            ERR_BOND_STRENGTH_BELOW_SPEC,
            "Latest ACCEPTED test must be a passing FULL assessment",
            422,
        )
    if g.user_id == accepted["technician_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Releasing user must differ from the recording technician",
            403,
        )
    formulation = store.formulations[lot["formulation_id"]]
    if formulation["status"] != "EFFECTIVE":
        raise ApiError(ERR_FORMULATION_NOT_EFFECTIVE, "Formulation is not EFFECTIVE", 409)
    lot["qa_status"] = "RELEASED"
    lot["released_by"] = g.user_id
    touch(lot)
    return ok(ser_lot(lot), 200)


@bp.post("/api/production-lots/<lid>/reject")
@require_roles("QAManager")
def reject_lot(lid):
    body_json()  # optional reason accepted and not persisted
    lot = get_lot(lid)
    if lot["qa_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_LOT_INVALID_STATE, "reject requires UNDER_REVIEW", 409)
    accepted = _latest_accepted_test(lid)
    if accepted is not None and g.user_id == accepted["technician_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Rejecting user must differ from the recording technician",
            403,
        )
    # condemn the sealed units: units_filled - units_condemned - units_quarantined
    delta = lot["units_filled"] - lot["units_condemned"] - lot["units_quarantined"]
    if delta > 0:
        lot["units_condemned"] += delta
        batch = store.batches.get(lot["batch_id"])
        if batch is not None:
            volume = sum(
                r["total_filled_ml"] or 0
                for r in store.runs.values()
                if r["batch_id"] == batch["id"] and r["status"] == "SEALED"
            )
            batch["written_off_volume_ml"] += volume
            touch(batch)
    lot["qa_status"] = "REJECTED"
    touch(lot)
    return ok(ser_lot(lot), 200)


@bp.post("/api/production-lots/<lid>/request-retest")
@require_roles("QAManager")
def request_retest(lid):
    body_json()
    lot = get_lot(lid)
    if lot["qa_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_LOT_INVALID_STATE, "request-retest requires UNDER_REVIEW", 409)
    if lot["retest_count"] >= 2:
        raise ApiError(ERR_RETEST_LIMIT_EXCEEDED, "retest_count already at the maximum of 2", 409)
    lot["retest_count"] += 1
    lot["qa_status"] = "TESTING"
    touch(lot)
    return ok(ser_lot(lot), 200)


# ---------------------------------------------------------------------------
# CureTest
# ---------------------------------------------------------------------------

@bp.get("/api/cure-tests")
@require_roles(*ALL_ROLES)
def list_tests():
    limit, offset = pagination_params()
    rows = list(store.tests.values())
    lid = request.args.get("lot_id")
    if lid is not None:
        rows = [t for t in rows if t["lot_id"] == lid]
    return ok_list([ser_test(t) for t in sorted_rows(rows)], limit, offset)


@bp.get("/api/cure-tests/<tid>")
@require_roles(*ALL_ROLES)
def get_one_test(tid):
    return ok(ser_test(get_test(tid)), 200)


@bp.post("/api/cure-tests/<tid>/accept")
@require_roles("QAManager")
def accept_test(tid):
    body_json()
    t = get_test(tid)
    if t["status"] != "RECORDED":
        raise ApiError(ERR_TEST_INVALID_STATE, "accept requires RECORDED", 409)
    lot = store.lots[t["lot_id"]]
    if lot["qa_status"] != "TESTING":
        raise ApiError(ERR_LOT_INVALID_STATE, "Lot qa_status must be TESTING", 409)
    formulation = store.formulations[lot["formulation_id"]]
    value, passed = assess_test(t["method"], t["specimens"],
                                formulation["spec_min_bond_strength_mpa"])
    # supersede any previously ACCEPTED test of the same lot
    for other in store.tests.values():
        if other["lot_id"] == t["lot_id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    t["evaluated_value_mpa"] = value
    t["assessment_pass"] = passed
    t["status"] = "ACCEPTED"
    touch(t)
    lot["qa_status"] = "UNDER_REVIEW"
    touch(lot)
    return ok(ser_test(t), 200)


@bp.post("/api/cure-tests/<tid>/void")
@require_roles("QAManager")
def void_test(tid):
    body_json()  # optional reason accepted and not persisted
    t = get_test(tid)
    if t["status"] != "RECORDED":
        raise ApiError(ERR_TEST_INVALID_STATE, "void requires RECORDED", 409)
    t["status"] = "VOIDED"
    touch(t)
    return ok(ser_test(t), 200)
