"""Renewal evaluations (PRD §3.8)."""

from flask import Blueprint, g, request

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine
from services.validate import require_fields, req_string, req_int, req_enum

bp = Blueprint("renewals", __name__)

RENEWAL_READ_ROLES = ("ScholarshipCoordinator", "Student")
TERMINAL_EVAL_STATUSES = {"RENEWED", "LAPSED"}


def get_evaluation_or_404(eid):
    e = db.get("renewal_evaluations", eid)
    if e is None:
        raise_err("ERR_NOT_FOUND", "RenewalEvaluation not found")
    return e


def _evaluation_ownership(ev):
    if g.role == "Student":
        award = db.get("awards", ev["award_id"])
        if award is None or g.user_id != award["student_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own renewal evaluations")


@bp.route("/api/renewal-evaluations", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def create_evaluation():
    data = body()
    require_fields(data, ["award_id", "term_label", "reported_gpa_hundredths", "reported_credits"])
    award_id = data["award_id"]
    if not isinstance(award_id, str) or db.get("awards", award_id) is None:
        raise_err("ERR_NOT_FOUND", "Award not found")
    award = db.get("awards", award_id)
    if g.role == "Student" and g.user_id != award["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only open evaluations on own awards")
    term_label = req_string(data, "term_label")
    gpa = req_int(data, "reported_gpa_hundredths", 0, 500)
    credits = req_int(data, "reported_credits", 0)

    program = engine.program_of_award(award)
    if not program.get("renewable"):
        raise_err("ERR_INVALID_STATE", "The award's program is not renewable")
    if award["funding_status"] != "FULLY_DISBURSED":
        raise_err("ERR_INVALID_STATE", "The award must be FULLY_DISBURSED")
    for other in db.all_records("renewal_evaluations"):
        if other["award_id"] == award_id and other["status"] not in TERMINAL_EVAL_STATUSES:
            raise_err("ERR_DUPLICATE_RENEWAL_EVALUATION",
                      "An open renewal evaluation already exists for this award")
    if award["renewal_count"] >= (program.get("max_renewals") or 0):
        raise_err("ERR_MAX_RENEWALS_REACHED", "The award has reached the program's renewal cap")

    rec = db.create_record("renewal_evaluations", {
        "award_id": award_id,
        "term_label": term_label,
        "reported_gpa_hundredths": gpa,
        "reported_credits": credits,
        "registrar_gpa_hundredths": None,
        "registrar_credits": None,
        "status": "PENDING",
        "verified_by_user_id": None,
        "decided_at": None,
        "appeal_note": None,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/renewal-evaluations", methods=["GET"])
@require_roles(*RENEWAL_READ_ROLES)
def list_evaluations():
    items = db.all_records("renewal_evaluations")
    if g.role == "Student":
        own = {a["id"] for a in db.all_records("awards") if a["student_id"] == g.user_id}
        items = [e for e in items if e["award_id"] in own]
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [e for e in items if e["award_id"] == award_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(e) for e in page], response_type="array", pagination=meta)


@bp.route("/api/renewal-evaluations/<eid>", methods=["GET"])
@require_roles(*RENEWAL_READ_ROLES)
def get_evaluation(eid):
    ev = get_evaluation_or_404(eid)
    _evaluation_ownership(ev)
    return success(db.serialize(ev))


@bp.route("/api/renewal-evaluations/<eid>/verify", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def verify_evaluation(eid):
    ev = get_evaluation_or_404(eid)
    data = body()
    require_fields(data, ["registrar_gpa_hundredths", "registrar_credits"])
    gpa = req_int(data, "registrar_gpa_hundredths", 0, 500)
    credits = req_int(data, "registrar_credits", 0)
    if ev["status"] not in ("PENDING", "APPEALED"):
        raise_err("ERR_INVALID_STATE", "Only a PENDING or APPEALED evaluation can be verified")
    award = db.get("awards", ev["award_id"])
    program = engine.program_of_award(award)
    min_gpa = program.get("renewal_min_gpa_hundredths")
    min_credits = program.get("renewal_min_credits")
    # Inclusive thresholds: a figure exactly at the threshold passes.
    eligible = True
    if min_gpa is not None and gpa < min_gpa:
        eligible = False
    if min_credits is not None and credits < min_credits:
        eligible = False
    db.mutate(ev, status="VERIFIED_ELIGIBLE" if eligible else "VERIFIED_INELIGIBLE",
              registrar_gpa_hundredths=gpa, registrar_credits=credits,
              verified_by_user_id=g.user_id)
    return success(db.serialize(ev))


@bp.route("/api/renewal-evaluations/<eid>/appeal", methods=["POST"])
@require_roles("ScholarshipCoordinator", "Student")
def appeal_evaluation(eid):
    ev = get_evaluation_or_404(eid)
    _evaluation_ownership(ev)
    data = body()
    note = data.get("appeal_note")
    if not isinstance(note, str) or not note:
        raise_err("ERR_VALIDATION", "appeal_note is required")
    if ev["status"] != "VERIFIED_INELIGIBLE":
        raise_err("ERR_INVALID_STATE", "Only a VERIFIED_INELIGIBLE evaluation can be appealed")
    db.mutate(ev, status="APPEALED", appeal_note=note)
    return success(db.serialize(ev))


@bp.route("/api/renewal-evaluations/<eid>/finalize-renewal", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def finalize_renewal(eid):
    ev = get_evaluation_or_404(eid)
    data = body()
    decision = req_enum(data, "decision", {"RENEW", "LAPSE"})
    award = db.get("awards", ev["award_id"])
    program = engine.program_of_award(award)
    if decision == "RENEW":
        if ev["status"] != "VERIFIED_ELIGIBLE":
            raise_err("ERR_RENEWAL_NOT_ELIGIBLE", "RENEW requires a VERIFIED_ELIGIBLE evaluation")
        if award["renewal_count"] >= (program.get("max_renewals") or 0):
            raise_err("ERR_MAX_RENEWALS_REACHED", "The award has reached the program's renewal cap")
        db.mutate(ev, status="RENEWED", decided_at=clock.now_iso())
        db.mutate(award, renewal_count=award["renewal_count"] + 1,
                  amount_cents=award["amount_cents"] + program["award_amount_cents"])
        engine.recompute_fund(db.get("award_funds", program["fund_id"]))
        engine.stacking_recompute(db.get("students", award["student_id"]), program)
    else:  # LAPSE
        if ev["status"] != "VERIFIED_INELIGIBLE":
            raise_err("ERR_RENEWAL_NOT_ELIGIBLE", "LAPSE requires a VERIFIED_INELIGIBLE evaluation")
        db.mutate(ev, status="LAPSED", decided_at=clock.now_iso())
    return success(db.serialize(ev))
