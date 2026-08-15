"""ClaimSubstantiation attachment and evidence-bound verification
(PRD §3.7)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REPORT_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_CLAIM_ALREADY_VERIFIED, ERR_CLAIM_EVIDENCE_MISMATCH,
    ERR_REPORT_STUDY_MISMATCH,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from services import ser_claim, CLAIM_TYPES, VERDICT_INPUTS
from util import (
    body, opt_str, paginate, req_enum, req_num, req_str,
    round_half_up, sort_created, touch,
)

bp = Blueprint("claims", __name__)


def get_claim(claim_id):
    c = db.store["claims"].get(claim_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"ClaimSubstantiation {claim_id} not found")
    return c


def _accepted_rec_for_arm(study_id, arm_id):
    """Most recent ACCEPTED recommendation of the arm, or None."""
    recs = [r for r in sort_created(db.store["recommendations"].values())
            if r["study_id"] == study_id and r["arm_id"] == arm_id
            and r["status"] == "ACCEPTED"]
    return recs[-1] if recs else None


@bp.route("/claims", methods=["POST"])
@require_roles("SensoryScientist")
def create_claim():
    b = body()
    report_id = req_str(b, "report_id")
    report = db.store["reports"].get(report_id)
    if report is None:
        raise_err(ERR_NOT_FOUND, f"StudyReport {report_id} not found")
    if report["author_user_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only the report author may attach a claim")
    if report["status"] != "DRAFT":
        raise_err(ERR_INVALID_REPORT_STATE,
                  "claims may be attached only while the report is DRAFT")
    claim_type = req_enum(b, "claim_type", CLAIM_TYPES)
    claim_text = req_str(b, "claim_text")
    claimed_value = req_num(b, "claimed_value")
    arm_id = opt_str(b, "arm_id", default=None)
    if claim_type == "PACKAGING_SUPERIORITY" and arm_id is None:
        raise_err(ERR_INVALID_REQUEST,
                  "PACKAGING_SUPERIORITY requires arm_id")
    if arm_id is not None and arm_id not in db.store["arms"]:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    now = clock.now()
    claim = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "report_id": report_id,
        "claim_type": claim_type,
        "claim_text": claim_text,
        "claimed_value": claimed_value,
        "arm_id": arm_id,
        "verdict": "PENDING",
        "verified_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["claims"][claim["id"]] = claim
    return respond(ser_claim(claim), 201)


@bp.route("/claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims():
    items = sort_created(db.store["claims"].values())
    for field in ("report_id", "verdict"):
        v = request.args.get(field)
        if v is not None:
            items = [c for c in items if c[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_claim(c) for c in page], pagination)


@bp.route("/claims/<claim_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_claim(claim_id):
    return respond(ser_claim(get_claim(claim_id)), 200)


@bp.route("/claims/<claim_id>/verify", methods=["POST"])
@require_roles("QAOfficer")
def verify_claim(claim_id):
    claim = get_claim(claim_id)
    report = db.store["reports"][claim["report_id"]]
    if claim["verdict"] != "PENDING":
        raise_err(ERR_CLAIM_ALREADY_VERIFIED,
                  "only a PENDING claim may be verified")
    if report["author_user_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "a QAOfficer may not verify claims on a report they "
                  "authored")
    b = body()
    chosen = req_enum(b, "verdict", VERDICT_INPUTS)
    # Evidence outcome per claim_evidence_evaluation (PRD §3.7).
    if claim["claim_type"] == "SHELF_LIFE_DAYS":
        rec = None
        if report["pinned_recommendation_id"] is not None:
            rec = db.store["recommendations"].get(
                report["pinned_recommendation_id"])
        if rec is not None and rec["status"] == "ACCEPTED" \
                and claim["claimed_value"] <= rec["computed_days"]:
            outcome = "SUPPORTED"
        else:
            outcome = "NOT_SUPPORTED"
    else:  # PACKAGING_SUPERIORITY
        arm = db.store["arms"].get(claim["arm_id"])
        if (arm is None or arm["study_id"] != report["study_id"]
                or arm["is_control"]):
            raise_err(ERR_REPORT_STUDY_MISMATCH,
                      "claim arm_id must name a non-control arm of the "
                      "report's study")
        control_arm = None
        for a in db.store["arms"].values():
            if a["study_id"] == report["study_id"] and a["is_control"]:
                control_arm = a
                break
        control_rec = (_accepted_rec_for_arm(report["study_id"],
                                             control_arm["id"])
                       if control_arm is not None else None)
        variant_rec = _accepted_rec_for_arm(report["study_id"], arm["id"])
        if control_rec is None or variant_rec is None:
            outcome = "INSUFFICIENT_DATA"
        else:
            actual_pct = round_half_up(
                (variant_rec["computed_days"] - control_rec["computed_days"])
                / control_rec["computed_days"] * 100, 2)
            outcome = ("SUPPORTED" if actual_pct >= claim["claimed_value"]
                       else "NOT_SUPPORTED")
    if chosen != outcome:
        raise_err(ERR_CLAIM_EVIDENCE_MISMATCH,
                  f"chosen verdict {chosen} contradicts the computed "
                  f"evidence outcome {outcome}")
    claim["verdict"] = chosen
    claim["verified_by"] = g.user_id
    touch(claim)
    return respond(ser_claim(claim), 200)
