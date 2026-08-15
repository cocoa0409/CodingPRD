"""InterventionProposal endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_object
from routes import make_bp
from services import calc, core
from util import D, v_enum, v_num

bp = make_bp("proposals")

UA = {"UtilityAnalyst"}
PD = {"ProgramDirector"}
KINDS = ("LEAK_REPAIR_PROGRAM", "METER_REPLACEMENT_PROGRAM",
         "PRESSURE_MANAGEMENT", "UNAUTHORIZED_USE_ENFORCEMENT")


def _get_or_404(prop_id):
    rec = db.store["intervention_proposals"].get(prop_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "intervention proposal not found")
    return rec


@bp.route("/nrw/intervention-proposals", methods=["POST"])
def create_proposal():
    uid, role = require_roles(UA)
    body = get_body()
    # priority 3: existence
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 6: posture gate
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    # priority 9: scalar
    kind = v_enum(body, "kind", KINDS)
    capital = v_num(body, "capital_cost", ge=0)
    om = v_num(body, "annual_om_cost", ge=0)
    volume = v_num(body, "expected_volume_saved_m3_per_year", gt=0)

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "kind": kind,
        "capital_cost": capital,
        "annual_om_cost": om,
        "expected_volume_saved_m3_per_year": volume,
        "status": "DRAFT",
        "benefit_cost_ratio": None,
        "payback_years": None,
    })
    calc.compute_bcr(rec, "PROVISIONAL")
    db.store["intervention_proposals"][rec["id"]] = rec
    db.append_audit("InterventionProposal", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/intervention-proposals/<prop_id>", methods=["GET"])
def get_proposal(prop_id):
    require_roles({"ProgramDirector", "UtilityAnalyst"})
    return success_object(db.serialize(_get_or_404(prop_id)))


@bp.route("/nrw/intervention-proposals/<prop_id>/submit", methods=["POST"])
def submit_proposal(prop_id):
    uid, role = require_roles(UA)
    rec = _get_or_404(prop_id)
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a DRAFT proposal can be submitted")
    dma = core.get_dma(rec["dma_id"])
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    calc.compute_bcr(rec, "PROVISIONAL")
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    db.append_audit("InterventionProposal", rec["id"], "SUBMIT", uid, role,
                    {"before": {"status": "DRAFT"}, "after": {"status": "SUBMITTED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/intervention-proposals/<prop_id>/approve", methods=["POST"])
def approve_proposal(prop_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(prop_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SUBMITTED proposal can be approved")
    # priority 11: benefit-cost approval gate on the PROVISIONAL value last
    # computed at submission (inclusive boundary).
    if rec["benefit_cost_ratio"] is None or \
            D(rec["benefit_cost_ratio"]) < calc.BCR_APPROVAL_THRESHOLD:
        raise ApiError(errors.ERR_BCR_BELOW_THRESHOLD, 422,
                       "benefit_cost_ratio is below the approval threshold")
    rec["status"] = "APPROVED"
    calc.compute_bcr(rec, "BANKABLE")
    db.touch(rec)
    db.append_audit("InterventionProposal", rec["id"], "APPROVE", uid, role,
                    {"before": {"status": "SUBMITTED"},
                     "after": {"status": "APPROVED"}})
    # Supersede cascade: other APPROVED same-kind proposals for this DMA archive.
    for other in list(db.store["intervention_proposals"].values()):
        if (other["id"] != rec["id"] and other["dma_id"] == rec["dma_id"]
                and other["kind"] == rec["kind"] and other["status"] == "APPROVED"):
            other["status"] = "ARCHIVED"
            db.touch(other)
            db.append_audit("InterventionProposal", other["id"], "ARCHIVE",
                            "system", "system",
                            {"before": {"status": "APPROVED"},
                             "after": {"status": "ARCHIVED"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/intervention-proposals/<prop_id>/reject", methods=["POST"])
def reject_proposal(prop_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(prop_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SUBMITTED proposal can be rejected")
    rec["status"] = "REJECTED"
    db.touch(rec)
    db.append_audit("InterventionProposal", rec["id"], "REJECT", uid, role,
                    {"before": {"status": "SUBMITTED"},
                     "after": {"status": "REJECTED"}})
    return success_object(db.serialize(rec))
