"""UnauthorizedConsumptionCase endpoints (parallel state dimensions)."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_object
from routes import make_bp
from util import canon, v_dt, v_num, v_str

bp = make_bp("cases")

INV = {"Investigator"}
PD = {"ProgramDirector"}


def _get_or_404(case_id):
    rec = db.store["unauthorized_consumption_cases"].get(case_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "unauthorized consumption case not found")
    return rec


def _finish(rec, uid, role, before, action, after):
    db.touch(rec)
    db.append_audit("UnauthorizedConsumptionCase", rec["id"], action, uid, role,
                    {"before": before, "after": after})
    return success_object(db.serialize(rec))


@bp.route("/nrw/unauthorized-consumption-cases", methods=["POST"])
def create_case():
    uid, role = require_roles(INV)
    body = get_body()
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    ref = v_str(body, "service_location_ref")
    opened = v_dt(body, "opened_at")

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "service_location_ref": ref,
        "opened_at": canon(opened),
        "investigation_status": "OPEN",
        "billing_adjustment_status": "NONE",
        "estimated_loss_m3": None,
        "proposed_adjustment_amount": None,
        "substantiated_by_user_id": None,
        "posted_adjustment_amount": None,
    })
    db.store["unauthorized_consumption_cases"][rec["id"]] = rec
    db.append_audit("UnauthorizedConsumptionCase", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_roles({"ProgramDirector", "Investigator"})
    return success_object(db.serialize(_get_or_404(case_id)))


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/begin-evidence", methods=["POST"])
def begin_evidence(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    if rec["investigation_status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an OPEN case can begin evidence gathering")
    rec["investigation_status"] = "EVIDENCE_GATHERING"
    return _finish(rec, uid, role, {"investigation_status": "OPEN"},
                   "BEGIN_EVIDENCE", {"investigation_status": "EVIDENCE_GATHERING"})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/substantiate", methods=["POST"])
def substantiate(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    if rec["investigation_status"] != "EVIDENCE_GATHERING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an EVIDENCE_GATHERING case can be substantiated")
    body = get_body()
    # priority 9: scalar (present-but-invalid), then priority 10: prerequisite (absent)
    if "estimated_loss_m3" in body and body["estimated_loss_m3"] is not None:
        loss = v_num(body, "estimated_loss_m3", ge=0)
    else:
        raise ApiError(errors.ERR_MISSING_PREREQUISITE, 422,
                       "estimated_loss_m3 is required to substantiate a case")
    before = {"investigation_status": "EVIDENCE_GATHERING"}
    rec["estimated_loss_m3"] = loss
    rec["substantiated_by_user_id"] = uid
    rec["investigation_status"] = "SUBSTANTIATED"
    return _finish(rec, uid, role, before, "SUBSTANTIATE",
                   {"investigation_status": "SUBSTANTIATED",
                    "estimated_loss_m3": loss})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/close-unfounded", methods=["POST"])
def close_unfounded(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    if rec["investigation_status"] != "EVIDENCE_GATHERING":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an EVIDENCE_GATHERING case can be closed unfounded")
    rec["investigation_status"] = "UNFOUNDED"
    return _finish(rec, uid, role, {"investigation_status": "EVIDENCE_GATHERING"},
                   "CLOSE_UNFOUNDED", {"investigation_status": "UNFOUNDED"})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    inv = rec["investigation_status"]
    billing = rec["billing_adjustment_status"]
    if inv == "UNFOUNDED":
        if billing != "NONE":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "an UNFOUNDED case can close only while billing is NONE")
    elif inv == "SUBSTANTIATED":
        if billing not in ("NONE", "REJECTED", "POSTED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "a case with a PROPOSED or APPROVED adjustment cannot be closed")
    else:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an UNFOUNDED or SUBSTANTIATED case can be closed")
    rec["investigation_status"] = "CLOSED"
    return _finish(rec, uid, role, {"investigation_status": inv},
                   "CLOSE", {"investigation_status": "CLOSED"})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/propose-adjustment", methods=["POST"])
def propose_adjustment(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    if rec["billing_adjustment_status"] != "NONE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "billing adjustment must be NONE to propose")
    if rec["investigation_status"] != "SUBSTANTIATED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "billing moves are gated on a SUBSTANTIATED investigation")
    body = get_body()
    amount = v_num(body, "proposed_adjustment_amount", gt=0)
    rec["proposed_adjustment_amount"] = amount
    rec["billing_adjustment_status"] = "PROPOSED"
    return _finish(rec, uid, role, {"billing_adjustment_status": "NONE"},
                   "PROPOSE_ADJUSTMENT",
                   {"billing_adjustment_status": "PROPOSED",
                    "proposed_adjustment_amount": amount})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/approve-adjustment", methods=["POST"])
def approve_adjustment(case_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(case_id)
    if rec["billing_adjustment_status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PROPOSED adjustment can be approved")
    # priority 7: segregation of duties
    if uid == rec["substantiated_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "the substantiator of a case may not approve its billing adjustment")
    rec["billing_adjustment_status"] = "APPROVED"
    return _finish(rec, uid, role, {"billing_adjustment_status": "PROPOSED"},
                   "APPROVE_ADJUSTMENT", {"billing_adjustment_status": "APPROVED"})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/reject-adjustment", methods=["POST"])
def reject_adjustment(case_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(case_id)
    if rec["billing_adjustment_status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PROPOSED adjustment can be rejected")
    rec["billing_adjustment_status"] = "REJECTED"
    return _finish(rec, uid, role, {"billing_adjustment_status": "PROPOSED"},
                   "REJECT_ADJUSTMENT", {"billing_adjustment_status": "REJECTED"})


@bp.route("/nrw/unauthorized-consumption-cases/<case_id>/post-adjustment", methods=["POST"])
def post_adjustment(case_id):
    uid, role = require_roles(INV)
    rec = _get_or_404(case_id)
    if rec["billing_adjustment_status"] != "APPROVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an APPROVED adjustment can be posted")
    rec["billing_adjustment_status"] = "POSTED"
    rec["posted_adjustment_amount"] = rec["proposed_adjustment_amount"]
    return _finish(rec, uid, role, {"billing_adjustment_status": "APPROVED"},
                   "POST_ADJUSTMENT",
                   {"billing_adjustment_status": "POSTED",
                    "posted_adjustment_amount": rec["posted_adjustment_amount"]})
