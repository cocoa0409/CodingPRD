"""WaterBalancePeriod endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from services import calc, core
from util import canon, paginate, sort_created, v_dt, v_int, v_num

bp = make_bp("water_balance")

READ_ROLES = {"ProgramDirector", "UtilityAnalyst", "RegulatorLiaison"}


def _get_wbp_or_404(wbp_id):
    rec = db.store["water_balance_periods"].get(wbp_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "water balance period not found")
    return rec


@bp.route("/nrw/water-balance-periods", methods=["POST"])
def create_wbp():
    uid, role = require_roles({"UtilityAnalyst"})
    body = get_body()
    # priority 3: existence of body FK
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 6: DMA posture gate (FROZEN blocks creation)
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    # priority 8: interval arithmetic (needs parseable datetimes)
    start = db.parse_dt(body.get("period_start"))
    end = db.parse_dt(body.get("period_end"))
    if start is not None and end is not None:
        if not end > start:
            raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                           "period_end must be after period_start")
        for other in db.store["water_balance_periods"].values():
            if other["dma_id"] != dma_id:
                continue
            if other["status"] not in ("DRAFT", "SUBMITTED", "FINALIZED"):
                continue
            o_start = db.parse_dt(other["period_start"])
            o_end = db.parse_dt(other["period_end"])
            if core.windows_overlap(start, end, o_start, o_end):
                raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                               "period overlaps an existing balance period for this DMA")
    # priority 9: scalar constraints
    v_dt(body, "period_start")
    v_dt(body, "period_end")
    siv = v_num(body, "system_input_volume_m3", gt=0)
    billed = v_num(body, "billed_authorized_m3", ge=0)
    unbilled = v_num(body, "unbilled_authorized_m3", ge=0)
    unauth = v_num(body, "unauthorized_consumption_m3", ge=0)
    inacc = v_num(body, "metering_inaccuracy_m3", ge=0)
    expected = v_int(body, "expected_dma_version")
    # priority 13: OCC
    if expected != dma["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_dma_version does not match the DMA's current version")

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "period_start": canon(start),
        "period_end": canon(end),
        "system_input_volume_m3": siv,
        "billed_authorized_m3": billed,
        "unbilled_authorized_m3": unbilled,
        "unauthorized_consumption_m3": unauth,
        "metering_inaccuracy_m3": inacc,
        "status": "DRAFT",
        "created_by_user_id": uid,
        "nrw_volume_m3": None,
        "nrw_pct": None,
        "apparent_loss_m3": None,
        "real_loss_m3": None,
        "ili": None,
    })
    calc.compute_water_balance(rec, "PROVISIONAL")
    db.store["water_balance_periods"][rec["id"]] = rec
    # The DMA gains a child: version increments by 1.
    db.touch(dma)
    core.recompute_posture(dma)
    db.append_audit("WaterBalancePeriod", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/water-balance-periods", methods=["GET"])
def list_wbps():
    require_roles(READ_ROLES)
    items = list(db.store["water_balance_periods"].values())
    from flask import request
    dma_id = request.args.get("dma_id")
    if dma_id is not None:
        items = [b for b in items if b["dma_id"] == dma_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(b) for b in page], meta)


@bp.route("/nrw/water-balance-periods/<wbp_id>", methods=["GET"])
def get_wbp(wbp_id):
    require_roles(READ_ROLES)
    rec = _get_wbp_or_404(wbp_id)
    return success_object(db.serialize(rec))


@bp.route("/nrw/water-balance-periods/<wbp_id>/submit", methods=["POST"])
def submit_wbp(wbp_id):
    uid, role = require_roles({"UtilityAnalyst"})
    rec = _get_wbp_or_404(wbp_id)
    # priority 5: state-machine validity
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a DRAFT balance period can be submitted")
    # priority 6: DMA posture gate
    dma = core.get_dma(rec["dma_id"])
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    # priority 12: water-balance consistency
    real_raw = calc.compute_water_balance(rec, "PROVISIONAL")
    if real_raw < 0:
        raise ApiError(errors.ERR_BALANCE_INCONSISTENT, 422,
                       "billed + unbilled + apparent losses exceed system input")
    before = {"status": "DRAFT"}
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    core.recompute_posture(dma)
    db.append_audit("WaterBalancePeriod", rec["id"], "SUBMIT", uid, role,
                    {"before": before, "after": {"status": "SUBMITTED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/water-balance-periods/<wbp_id>/finalize", methods=["POST"])
def finalize_wbp(wbp_id):
    uid, role = require_roles({"UtilityAnalyst"})
    rec = _get_wbp_or_404(wbp_id)
    # priority 5: state-machine validity
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SUBMITTED balance period can be finalized")
    # priority 6: DMA posture gate
    dma = core.get_dma(rec["dma_id"])
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    # priority 7: segregation of duties
    if uid == rec["created_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "the creator of a balance period may not finalize it")

    calc.compute_water_balance(rec, "AUDITED")
    rec["ili"] = calc.compute_ili(rec, dma)
    rec["status"] = "FINALIZED"
    db.touch(rec)

    # Supersede overlapping FINALIZED siblings (system cascade).
    r_start = db.parse_dt(rec["period_start"])
    r_end = db.parse_dt(rec["period_end"])
    for other in list(db.store["water_balance_periods"].values()):
        if other["id"] == rec["id"] or other["dma_id"] != rec["dma_id"]:
            continue
        if other["status"] != "FINALIZED":
            continue
        if core.windows_overlap(r_start, r_end,
                                db.parse_dt(other["period_start"]),
                                db.parse_dt(other["period_end"])):
            other["status"] = "SUPERSEDED"
            db.touch(other)
            db.append_audit("WaterBalancePeriod", other["id"], "SUPERSEDE",
                            "system", "system",
                            {"before": {"status": "FINALIZED"},
                             "after": {"status": "SUPERSEDED"}})

    core.recompute_latest_nrw(dma)
    core.recompute_posture(dma)
    db.append_audit("WaterBalancePeriod", rec["id"], "FINALIZE", uid, role,
                    {"before": {"status": "SUBMITTED"},
                     "after": {"status": "FINALIZED"}})
    return success_object(db.serialize(rec))
