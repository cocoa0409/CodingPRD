"""Thank-you letters and donor reports (PRD §3.9)."""

from flask import Blueprint, g, request

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine
from services.validate import require_fields, req_date

bp = Blueprint("stewardship", __name__)

LETTER_ROLES = ("ScholarshipCoordinator", "Student", "Donor")
REPORT_ROLES = ("ScholarshipCoordinator", "Donor")


def get_letter_or_404(lid):
    t = db.get("thank_you_letters", lid)
    if t is None:
        raise_err("ERR_NOT_FOUND", "ThankYouLetter not found")
    return t


def get_report_or_404(rid):
    r = db.get("donor_reports", rid)
    if r is None:
        raise_err("ERR_NOT_FOUND", "DonorReport not found")
    return r


def _letter_donor_id(letter):
    award = db.get("awards", letter["award_id"])
    program = engine.program_of_award(award) if award else None
    return program["donor_id"] if program else None


def _letter_ownership(letter):
    if g.role == "Student":
        award = db.get("awards", letter["award_id"])
        if award is None or g.user_id != award["student_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own letters")
    elif g.role == "Donor":
        if g.user_id != _letter_donor_id(letter):
            raise_err("ERR_FORBIDDEN_OWNERSHIP", "Donor may only access own programs' letters")


def _report_ownership(report):
    if g.role == "Donor" and g.user_id != report["donor_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Donor may only access own reports")


# ---------------------------------------------------------------------------
# Thank-you letters
# ---------------------------------------------------------------------------

@bp.route("/api/thank-you-letters", methods=["GET"])
@require_roles(*LETTER_ROLES)
def list_letters():
    items = db.all_records("thank_you_letters")
    if g.role == "Student":
        own = {a["id"] for a in db.all_records("awards") if a["student_id"] == g.user_id}
        items = [t for t in items if t["award_id"] in own]
    elif g.role == "Donor":
        items = [t for t in items if _letter_donor_id(t) == g.user_id]
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [t for t in items if t["award_id"] == award_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(t) for t in page], response_type="array", pagination=meta)


@bp.route("/api/thank-you-letters/<lid>", methods=["GET"])
@require_roles(*LETTER_ROLES)
def get_letter(lid):
    letter = get_letter_or_404(lid)
    _letter_ownership(letter)
    return success(db.serialize(letter))


@bp.route("/api/thank-you-letters/<lid>/submit", methods=["POST"])
@require_roles("Student")
def submit_letter(lid):
    letter = get_letter_or_404(lid)
    award = db.get("awards", letter["award_id"])
    if award is None or g.user_id != award["student_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Students may only submit their own letters")
    data = body()
    content_ref = data.get("content_ref")
    if not isinstance(content_ref, str) or not content_ref:
        raise_err("ERR_VALIDATION", "content_ref is required")
    if letter["status"] not in ("REQUIRED", "REVISION_REQUESTED"):
        raise_err("ERR_INVALID_STATE", "Only a REQUIRED or REVISION_REQUESTED letter can be submitted")
    db.mutate(letter, status="SUBMITTED", content_ref=content_ref)
    return success(db.serialize(letter))


@bp.route("/api/thank-you-letters/<lid>/request-revision", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def request_revision(lid):
    letter = get_letter_or_404(lid)
    if letter["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED letter can be sent back for revision")
    db.mutate(letter, status="REVISION_REQUESTED")
    return success(db.serialize(letter))


@bp.route("/api/thank-you-letters/<lid>/approve", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def approve_letter(lid):
    letter = get_letter_or_404(lid)
    if letter["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED letter can be approved")
    db.mutate(letter, status="APPROVED")
    return success(db.serialize(letter))


@bp.route("/api/thank-you-letters/<lid>/deliver", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def deliver_letter(lid):
    letter = get_letter_or_404(lid)
    if letter["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED letter can be delivered")
    db.mutate(letter, status="DELIVERED")
    engine.stale_reports_covered_by_letter(letter)
    return success(db.serialize(letter))


@bp.route("/api/thank-you-letters/<lid>/waive", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def waive_letter(lid):
    letter = get_letter_or_404(lid)
    if letter["status"] != "REQUIRED":
        raise_err("ERR_INVALID_STATE", "Only a REQUIRED letter can be waived")
    award = db.get("awards", letter["award_id"])
    program = engine.program_of_award(award)
    donor = engine.donor_of_program(program)
    if not (donor and donor.get("anonymous")):
        raise_err("ERR_TYL_NOT_WAIVABLE", "Letters are waivable only for anonymous donors")
    db.mutate(letter, status="WAIVED")
    engine.stale_reports_covered_by_letter(letter)
    return success(db.serialize(letter))


# ---------------------------------------------------------------------------
# Donor reports
# ---------------------------------------------------------------------------

@bp.route("/api/donor-reports", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_report():
    data = body()
    require_fields(data, ["donor_id", "period_start", "period_end"])
    donor_id = data["donor_id"]
    if not isinstance(donor_id, str) or db.get("donors", donor_id) is None:
        raise_err("ERR_NOT_FOUND", "Donor not found")
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    if period_end <= period_start:
        raise_err("ERR_INVALID_DATE_RANGE", "period_end must be later than period_start")
    rec = db.create_record("donor_reports", {
        "donor_id": donor_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "total_awards_count": None,
        "total_disbursed_cents": None,
        "thank_you_complete": None,
        "sent_at": None,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/donor-reports", methods=["GET"])
@require_roles(*REPORT_ROLES)
def list_reports():
    items = db.all_records("donor_reports")
    if g.role == "Donor":
        items = [r for r in items if r["donor_id"] == g.user_id]
    donor_id = request.args.get("donor_id")
    status = request.args.get("status")
    if donor_id is not None:
        items = [r for r in items if r["donor_id"] == donor_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(r) for r in page], response_type="array", pagination=meta)


@bp.route("/api/donor-reports/<rid>", methods=["GET"])
@require_roles(*REPORT_ROLES)
def get_report(rid):
    report = get_report_or_404(rid)
    _report_ownership(report)
    if report["status"] != "DRAFT":
        # Reading a report refreshes thank_you_complete against current letter states.
        _count, _total, complete = engine.donor_report_aggregates(report)
        db.mutate(report, thank_you_complete=complete)
    return success(db.serialize(report))


@bp.route("/api/donor-reports/<rid>/generate", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def generate_report(rid):
    report = get_report_or_404(rid)
    if report["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT report can be generated")
    count, total, complete = engine.donor_report_aggregates(report)
    db.mutate(report, status="GENERATED", total_awards_count=count,
              total_disbursed_cents=total, thank_you_complete=complete)
    return success(db.serialize(report))


@bp.route("/api/donor-reports/<rid>/send", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def send_report(rid):
    report = get_report_or_404(rid)
    if report["status"] != "GENERATED":
        raise_err("ERR_INVALID_STATE", "Only a GENERATED report can be sent")
    _count, _total, complete = engine.donor_report_aggregates(report)
    db.mutate(report, thank_you_complete=complete)
    if not complete:
        raise_err("ERR_REPORT_INCOMPLETE",
                  "Covered thank-you letters are not all DELIVERED or WAIVED")
    db.mutate(report, status="SENT", sent_at=clock.now_iso())
    return success(db.serialize(report))


@bp.route("/api/donor-reports/<rid>/acknowledge", methods=["POST"])
@require_roles("Donor")
def acknowledge_report(rid):
    report = get_report_or_404(rid)
    if g.user_id != report["donor_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Donors may only acknowledge their own reports")
    if report["status"] != "SENT":
        raise_err("ERR_INVALID_STATE", "Only a SENT report can be acknowledged")
    db.mutate(report, status="ACKNOWLEDGED")
    return success(db.serialize(report))
