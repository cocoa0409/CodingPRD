from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import dump_check, get_run, get_check, oil_for_line, temp_factor, frying_accrual
from errors import ApiError
from store import STORE, new_entity, sort_key
from util import body, ok, paginate, req_num, opt_num, iso, D

bp = Blueprint("checks", __name__)


@bp.post("/snack-mfg/weight-checks")
def create_check():
    uid, _ = require(["QualityTechnician"])
    data = body()
    # tier 3: body FK
    run_id = data.get("run_id")
    run = get_run(STORE, run_id) if isinstance(run_id, str) else None
    if run is None:
        if not isinstance(run_id, str) or run_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: run_id")
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "run not found")
    # tier 5: shape
    bag_weight = req_num(data, "bag_weight_g", gt=0)
    lbs_fried = req_num(data, "lbs_fried_since_last_check", ge=0)
    product = STORE.products.get(run["product_id"])
    if product is not None and product["process_type"] == "FRYER":
        avg_temp = req_num(data, "avg_fry_temp_c")
    else:
        avg_temp = opt_num(data, "avg_fry_temp_c", default=None)
    # tier 6: run must be RUNNING (cross-entity state gate)
    if run["execution_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "run is not RUNNING")
    declared = D(product["declared_net_weight_g"])
    tne = D(product["tne_g"])
    is_reject = bool(bag_weight < declared - 2 * tne)
    chk = new_entity(STORE, with_version=False)
    chk.update({
        "run_id": run["id"], "bag_weight_g": bag_weight,
        "lbs_fried_since_last_check": lbs_fried, "avg_fry_temp_c": avg_temp,
        "is_reject": is_reject, "recorded_at": iso(STORE.clock),
        "checked_by_user_id": uid,
    })
    STORE.checks[chk["id"]] = chk
    # frying accrual to the line's oil (may trigger the TPM hold cascade)
    oil = oil_for_line(STORE, run["line_id"])
    if oil is not None and lbs_fried != 0:
        frying_accrual(STORE, oil, lbs_fried, temp_factor(product, avg_temp))
    return ok(STORE, dump_check(chk), status=201)


@bp.get("/snack-mfg/weight-checks/<wid>")
def get_check_ep(wid):
    require(ALL_ROLES)
    chk = get_check(STORE, wid)
    return ok(STORE, dump_check(chk))


@bp.get("/snack-mfg/weight-checks")
def list_checks():
    require(ALL_ROLES)
    items = list(STORE.checks.values())
    run_id = request.args.get("run_id")
    if run_id is not None:
        items = [c for c in items if c["run_id"] == run_id]
    items.sort(key=sort_key)
    page, meta = paginate([dump_check(c) for c in items])
    return ok(STORE, page, response_type="array", pagination=meta)
