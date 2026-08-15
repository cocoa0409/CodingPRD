from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import (dump_oil, dump_movement, get_oil, get_movement, oil_state_reeval,
                    FILTRATION_FACTOR, FRESH_TPM)
from errors import ApiError
from store import STORE, new_entity, touch, sort_key
from util import body, ok, paginate, req_enum, req_int, is_number, iso, D, rhu

bp = Blueprint("oils", __name__)


@bp.get("/snack-mfg/fryer-oils/<oid>")
def get_oil_ep(oid):
    require(ALL_ROLES)
    oil = get_oil(STORE, oid)
    return ok(STORE, dump_oil(STORE, oil))


@bp.get("/snack-mfg/fryer-oils")
def list_oils():
    require(ALL_ROLES)
    items = list(STORE.oils.values())
    line_id = request.args.get("line_id")
    if line_id is not None:
        items = [o for o in items if o["line_id"] == line_id]
    items.sort(key=sort_key)
    page, meta = paginate([dump_oil(STORE, o) for o in items])
    return ok(STORE, page, response_type="array", pagination=meta)


@bp.post("/snack-mfg/oil-movements")
def create_movement():
    uid, _ = require(["LineOperator"])
    data = body()
    # tier 3: body FK
    oil_id = data.get("fryer_oil_id")
    oil = get_oil(STORE, oil_id) if isinstance(oil_id, str) else None
    if oil is None:
        if not isinstance(oil_id, str) or oil_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: fryer_oil_id")
        raise ApiError("ERR_OIL_NOT_FOUND", 404, "fryer oil not found")
    line = STORE.lines.get(oil["line_id"])
    capacity = D(line["oil_capacity_gallons"]) if line is not None else None
    # tier 5: shape + per-type field rules
    mtype = req_enum(data, "movement_type", {"TOP_OFF", "DISCARD", "FILTRATION", "FULL_REPLACE"})
    g_raw = data.get("gallons")
    if not is_number(g_raw):
        raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: gallons")
    gallons = D(g_raw)
    price_present = "unit_price_cents_per_gal" in data and data.get("unit_price_cents_per_gal") is not None
    price = None
    if mtype in ("TOP_OFF", "DISCARD"):
        if not (gallons > 0):
            raise ApiError("ERR_VALIDATION", 400, "gallons must be > 0 for TOP_OFF/DISCARD")
    elif mtype == "FILTRATION":
        if gallons != 0:
            raise ApiError("ERR_VALIDATION", 400, "gallons must be exactly 0 for FILTRATION")
    elif mtype == "FULL_REPLACE":
        if capacity is None or gallons != capacity:
            raise ApiError("ERR_VALIDATION", 400,
                           "gallons must equal line oil_capacity_gallons for FULL_REPLACE")
    if mtype in ("TOP_OFF", "FULL_REPLACE"):
        if not price_present:
            raise ApiError("ERR_VALIDATION", 400,
                           f"unit_price_cents_per_gal is required for {mtype}")
        price = req_int(data, "unit_price_cents_per_gal", ge=0)
    else:
        if price_present:
            raise ApiError("ERR_VALIDATION", 400,
                           f"unit_price_cents_per_gal is forbidden for {mtype}")
    expected_oil_version = req_int(data, "expected_oil_version")
    # tier 6: from-state for FULL_REPLACE, then OCC
    if mtype == "FULL_REPLACE" and oil["state"] != "DRAINING":
        raise ApiError("ERR_INVALID_STATE", 409, "FULL_REPLACE requires oil state DRAINING")
    if expected_oil_version != oil["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "oil version has advanced since observation")
    # tier 6 cross-entity: a full-drain DISCARD is a drain and is forbidden
    # while any run on the line is RUNNING
    if (mtype == "DISCARD" and oil["state"] in ("ACTIVE", "QUALITY_HOLD")
            and gallons == oil["current_gallons"]):
        for r in STORE.runs.values():
            if r["line_id"] == oil["line_id"] and r["execution_status"] == "RUNNING":
                raise ApiError("ERR_INVALID_STATE", 409, "cannot drain under a RUNNING run")
    # tier 9: sump overflow / underflow
    if mtype == "TOP_OFF" and capacity is not None and oil["current_gallons"] + gallons > capacity:
        raise ApiError("ERR_OIL_OVERFLOW", 422, "top-off would exceed oil_capacity_gallons")
    if mtype == "DISCARD" and gallons > oil["current_gallons"]:
        raise ApiError("ERR_INSUFFICIENT_OIL", 422, "discard exceeds current_gallons")
    # apply the movement
    if mtype == "TOP_OFF":
        pre = oil["current_gallons"]
        oil["tpm_pct"] = rhu(oil["tpm_pct"] * pre / (pre + gallons), 2)
        oil["current_gallons"] = pre + gallons
    elif mtype == "DISCARD":
        full_drain = (gallons == oil["current_gallons"])
        oil["current_gallons"] = oil["current_gallons"] - gallons
        if full_drain and oil["state"] in ("ACTIVE", "QUALITY_HOLD"):
            oil["state"] = "DRAINING"
    elif mtype == "FILTRATION":
        oil["tpm_pct"] = rhu(oil["tpm_pct"] * FILTRATION_FACTOR, 2)
    elif mtype == "FULL_REPLACE":
        oil["tpm_pct"] = FRESH_TPM
        oil["total_lbs_since_replace"] = D(0)
        oil["current_gallons"] = capacity
        oil["state"] = "ACTIVE"
    oil_state_reeval(STORE, oil)
    touch(STORE, oil)
    m = new_entity(STORE, with_version=False)
    m.update({
        "fryer_oil_id": oil["id"], "movement_type": mtype, "gallons": gallons,
        "unit_price_cents_per_gal": price, "tpm_after_pct": oil["tpm_pct"],
        "recorded_at": iso(STORE.clock), "recorded_by_user_id": uid,
        "_recorded_dt": STORE.clock,
    })
    STORE.movements[m["id"]] = m
    return ok(STORE, dump_movement(m), status=201)


@bp.get("/snack-mfg/oil-movements/<mid>")
def get_movement_ep(mid):
    require(ALL_ROLES)
    m = get_movement(STORE, mid)
    return ok(STORE, dump_movement(m))


@bp.get("/snack-mfg/oil-movements")
def list_movements():
    require(ALL_ROLES)
    items = list(STORE.movements.values())
    oil_id = request.args.get("fryer_oil_id")
    if oil_id is not None:
        items = [m for m in items if m["fryer_oil_id"] == oil_id]
    items.sort(key=sort_key)
    page, meta = paginate([dump_movement(m) for m in items])
    return ok(STORE, page, response_type="array", pagination=meta)


@bp.post("/snack-mfg/fryer-oils/<oid>/begin-change")
def begin_change(oid):
    uid, _ = require(["LineOperator"])
    oil = get_oil(STORE, oid)
    if oil["state"] not in ("ACTIVE", "QUALITY_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "oil is not ACTIVE or QUALITY_HOLD")
    for r in STORE.runs.values():
        if r["line_id"] == oil["line_id"] and r["execution_status"] == "RUNNING":
            raise ApiError("ERR_INVALID_STATE", 409, "cannot drain under a RUNNING run")
    oil["state"] = "DRAINING"
    touch(STORE, oil)
    return ok(STORE, dump_oil(STORE, oil))
