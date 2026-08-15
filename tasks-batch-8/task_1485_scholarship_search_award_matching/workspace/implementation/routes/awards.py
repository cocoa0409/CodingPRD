"""Award offers, stacking triggers, waitlist promotion, schedule-split (PRD §3.6-§3.7)."""

from datetime import timedelta

from flask import Blueprint, g, request

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine, calc
from services.validate import require_fields, req_int
from routes.applications import get_application_or_404
from routes.programs import get_program_or_404

bp = Blueprint("awards", __name__)

AWARD_READ_ROLES = ("ScholarshipCoordinator", "Student", "FinancialAidOfficer")


def get_award_or_404(aid):
    a = db.get("awards", aid)
    if a is None:
        raise_err("ERR_NOT_FOUND", "Award not found")
    return a


def award_ownership(award):
    if g.role == "Student" and g.user_id != award["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own awards")


@bp.route("/api/awards", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_award():
    data = body()
    require_fields(data, ["application_id", "student_id", "amount_cents"])
    application_id = data["application_id"]
    student_id = data["student_id"]
    if not isinstance(application_id, str) or db.get("applications", application_id) is None:
        raise_err("ERR_NOT_FOUND", "Application not found")
    if not isinstance(student_id, str) or db.get("students", student_id) is None:
        raise_err("ERR_NOT_FOUND", "Student not found")
    amount = req_int(data, "amount_cents", 1)
    app = db.get("applications", application_id)
    program = get_program_or_404(app["program_id"])
    if amount > program["award_amount_cents"]:
        raise_err("ERR_VALIDATION", "amount_cents exceeds the program's award_amount_cents")
    if student_id != app["student_id"]:
        raise_err("ERR_VALIDATION", "student_id must equal the application's student")
    if app["status"] != "SELECTED":
        raise_err("ERR_INVALID_STATE", "Award offers target SELECTED applications")
    fund = db.get("award_funds", program["fund_id"])
    engine.recompute_fund(fund)
    if amount > fund["available_cents"]:
        raise_err("ERR_INSUFFICIENT_FUNDS", "Offer amount exceeds the fund's available_cents")

    rec = db.create_record("awards", {
        "application_id": application_id,
        "student_id": student_id,
        "amount_cents": amount,
        "offer_status": "OFFERED",
        "funding_status": "NONE",
        "offer_expires_at": clock.iso3(clock.days_from_now(14)),
        "accepted_at": None,
        "renewal_count": 0,
    })
    db.mutate(app, status="AWARDED")
    engine.recompute_fund(fund)
    engine.recompute_student(db.get("students", student_id))
    return success(db.serialize(rec), code=201)


@bp.route("/api/awards", methods=["GET"])
@require_roles(*AWARD_READ_ROLES)
def list_awards():
    items = db.all_records("awards")
    if g.role == "Student":
        items = [a for a in items if a["student_id"] == g.user_id]
    application_id = request.args.get("application_id")
    student_id = request.args.get("student_id")
    offer_status = request.args.get("offer_status")
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if offer_status is not None:
        items = [a for a in items if a["offer_status"] == offer_status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(a) for a in page], response_type="array", pagination=meta)


@bp.route("/api/awards/<aid>", methods=["GET"])
@require_roles(*AWARD_READ_ROLES)
def get_award(aid):
    award = get_award_or_404(aid)
    award_ownership(award)
    return success(db.serialize(award))


@bp.route("/api/awards/<aid>", methods=["PATCH"])
@require_roles("ScholarshipCoordinator")
def patch_award(aid):
    award = get_award_or_404(aid)
    data = body()
    # OCC (priority 5) precedes remaining shape checks and the state gate.
    if "expected_award_version" not in data:
        raise_err("ERR_VALIDATION", "expected_award_version is required")
    expected = data["expected_award_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err("ERR_VALIDATION", "expected_award_version must be an integer")
    if expected != award["version"]:
        raise_err("ERR_STALE_VERSION", "Award version has advanced")
    updates = {}
    if "amount_cents" in data:
        amount = req_int(data, "amount_cents", 1)
        program = engine.program_of_award(award)
        if amount > program["award_amount_cents"]:
            raise_err("ERR_VALIDATION", "amount_cents exceeds the program's award_amount_cents")
        updates["amount_cents"] = amount
    if award["offer_status"] != "OFFERED":
        raise_err("ERR_INVALID_STATE", "Amount may be adjusted only while the offer is OFFERED")
    db.mutate(award, **updates)
    program = engine.program_of_award(award)
    engine.recompute_fund(db.get("award_funds", program["fund_id"]))
    engine.stacking_recompute(db.get("students", award["student_id"]), program)
    return success(db.serialize(award))


@bp.route("/api/awards/<aid>/accept", methods=["POST"])
@require_roles("Student")
def accept_award(aid):
    award = get_award_or_404(aid)
    if g.user_id != award["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Students may only accept their own awards")
    if award["offer_status"] != "OFFERED":
        raise_err("ERR_INVALID_STATE", "Only an OFFERED award can be accepted")
    db.mutate(award, offer_status="ACCEPTED", funding_status="ENCUMBERED",
              accepted_at=clock.now_iso())
    program = engine.program_of_award(award)
    student = db.get("students", award["student_id"])
    engine.recompute_fund(db.get("award_funds", program["fund_id"]))
    engine.stacking_recompute(student, program)
    return success(db.serialize(award))


@bp.route("/api/awards/<aid>/decline", methods=["POST"])
@require_roles("Student")
def decline_award(aid):
    award = get_award_or_404(aid)
    if g.user_id != award["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Students may only decline their own awards")
    if award["offer_status"] != "OFFERED":
        raise_err("ERR_INVALID_STATE", "Only an OFFERED award can be declined")
    db.mutate(award, offer_status="DECLINED")
    program = engine.program_of_award(award)
    engine.recompute_fund(db.get("award_funds", program["fund_id"]))
    engine.recompute_student(db.get("students", award["student_id"]))
    engine.waitlist_promotion(award)
    return success(db.serialize(award))


@bp.route("/api/awards/<aid>/revoke", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def revoke_award(aid):
    award = get_award_or_404(aid)
    if award["offer_status"] not in ("OFFERED", "ACCEPTED"):
        raise_err("ERR_INVALID_STATE", "Only an OFFERED or ACCEPTED award can be revoked")
    was_accepted = award["offer_status"] == "ACCEPTED"
    net = engine.net_confirmed(aid)
    updates = {"offer_status": "REVOKED"}
    if was_accepted and net > 0:
        updates["funding_status"] = "OVER_DISBURSED"
    db.mutate(award, **updates)
    program = engine.program_of_award(award)
    engine.recompute_fund(db.get("award_funds", program["fund_id"]))
    engine.recompute_student(db.get("students", award["student_id"]))
    has_confirmed = any(d["status"] == "CONFIRMED"
                        for d in engine.disbursements_of_award(aid))
    if not has_confirmed:
        engine.waitlist_promotion(award)
    return success(db.serialize(award))


@bp.route("/api/awards/<aid>/schedule-split", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def schedule_split(aid):
    award = get_award_or_404(aid)
    data = body()
    term_count = req_int(data, "term_count", 1)
    if award["offer_status"] != "ACCEPTED":
        raise_err("ERR_INVALID_STATE", "Split plans require an ACCEPTED award")
    existing = [d for d in engine.disbursements_of_award(aid) if d["status"] != "CANCELLED"]
    if existing:
        raise_err("ERR_AMOUNT_EXCEEDS_REMAINING", "A disbursement plan already exists for this award")
    student = db.get("students", award["student_id"])
    accepted_date = clock.parse_iso(award["accepted_at"]).date()
    amounts = calc.split_amounts(award["amount_cents"], term_count)
    created = []
    for i, amt in enumerate(amounts, start=1):
        term_start = accepted_date + timedelta(days=(i - 1) * 180)
        term_end = accepted_date + timedelta(days=i * 180 - 1)
        created.append(db.create_record("disbursements", {
            "award_id": aid,
            "term_seq": i,
            "amount_cents": amt,
            "scheduled_date": term_start.isoformat(),
            "term_start_date": term_start.isoformat(),
            "term_end_date": term_end.isoformat(),
            "institution_name": student["institution_name"],
            "status": "SCHEDULED",
            "sent_by_user_id": None,
            "sent_at": None,
            "confirmed_at": None,
            "returned_at": None,
            "returned_reason": None,
            "_ever_confirmed": False,
            "_returned_from_confirmed": False,
        }))
    return success([db.serialize(d) for d in created], response_type="array")
