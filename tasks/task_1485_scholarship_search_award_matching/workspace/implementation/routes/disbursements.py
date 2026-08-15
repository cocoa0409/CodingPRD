"""Disbursements (PRD §3.7)."""

from flask import Blueprint, g, request

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success, paginate, sort_default
from services import engine
from services.validate import require_fields, req_string, req_int, req_date
from routes.awards import get_award_or_404

bp = Blueprint("disbursements", __name__)

DISB_READ_ROLES = ("ScholarshipCoordinator", "FinancialAidOfficer", "Student")
ACTIVE_WINDOW_STATUSES = ("SCHEDULED", "SENT", "CONFIRMED")


def get_disbursement_or_404(did):
    d = db.get("disbursements", did)
    if d is None:
        raise_err("ERR_NOT_FOUND", "Disbursement not found")
    return d


def _disbursement_ownership(disb):
    if g.role == "Student":
        award = db.get("awards", disb["award_id"])
        if award is None or g.user_id != award["student_id"]:
            raise_err("ERR_FORBIDDEN_OWNERSHIP", "Student may only access own disbursements")


def _award_accepted_gate(award):
    if not (award["offer_status"] == "ACCEPTED"
            and award["funding_status"] in ("ENCUMBERED", "DISBURSING")):
        raise_err("ERR_AWARD_NOT_ACCEPTED",
                  "Award must be ACCEPTED with funding ENCUMBERED or DISBURSING")


def _overlap_check(award_id, start, end, exclude_id=None):
    for other in engine.disbursements_of_award(award_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ACTIVE_WINDOW_STATUSES:
            continue
        # Closed intervals: sharing even a single calendar day is overlap.
        if start <= other["term_end_date"] and other["term_start_date"] <= end:
            raise_err("ERR_DISBURSEMENT_WINDOW_OVERLAP",
                      "Term window overlaps another active disbursement of the award")


@bp.route("/api/disbursements", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def create_disbursement():
    data = body()
    require_fields(data, ["award_id", "term_seq", "amount_cents", "scheduled_date",
                          "term_start_date", "term_end_date", "institution_name"])
    award_id = data["award_id"]
    if not isinstance(award_id, str) or db.get("awards", award_id) is None:
        raise_err("ERR_NOT_FOUND", "Award not found")
    term_seq = req_int(data, "term_seq", 1)
    amount = req_int(data, "amount_cents", 1)
    scheduled = req_date(data, "scheduled_date")
    term_start = req_date(data, "term_start_date")
    term_end = req_date(data, "term_end_date")
    institution = req_string(data, "institution_name")
    if term_end < term_start:
        raise_err("ERR_INVALID_DATE_RANGE", "term_end_date must be on or after term_start_date")

    award = db.get("awards", award_id)
    _award_accepted_gate(award)
    _overlap_check(award_id, term_start, term_end)
    committed_sum = sum(d["amount_cents"] for d in engine.disbursements_of_award(award_id)
                        if d["status"] != "CANCELLED")
    if committed_sum + amount > award["amount_cents"]:
        raise_err("ERR_AMOUNT_EXCEEDS_REMAINING",
                  "Non-cancelled disbursements would exceed the award amount")

    rec = db.create_record("disbursements", {
        "award_id": award_id,
        "term_seq": term_seq,
        "amount_cents": amount,
        "scheduled_date": scheduled,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "institution_name": institution,
        "status": "SCHEDULED",
        "sent_by_user_id": None,
        "sent_at": None,
        "confirmed_at": None,
        "returned_at": None,
        "returned_reason": None,
        "_ever_confirmed": False,
        "_returned_from_confirmed": False,
    })
    return success(db.serialize(rec), code=201)


@bp.route("/api/disbursements", methods=["GET"])
@require_roles(*DISB_READ_ROLES)
def list_disbursements():
    items = db.all_records("disbursements")
    if g.role == "Student":
        own = {a["id"] for a in db.all_records("awards") if a["student_id"] == g.user_id}
        items = [d for d in items if d["award_id"] in own]
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    if award_id is not None:
        items = [d for d in items if d["award_id"] == award_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_default(items)
    page, meta = paginate(items)
    return success([db.serialize(d) for d in page], response_type="array", pagination=meta)


@bp.route("/api/disbursements/<did>", methods=["GET"])
@require_roles(*DISB_READ_ROLES)
def get_disbursement(did):
    disb = get_disbursement_or_404(did)
    _disbursement_ownership(disb)
    return success(db.serialize(disb))


@bp.route("/api/disbursements/<did>/send", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def send_disbursement(did):
    disb = get_disbursement_or_404(did)
    if disb["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Only a SCHEDULED disbursement can be sent")
    award = db.get("awards", disb["award_id"])
    _award_accepted_gate(award)
    if clock.today() < clock.parse_date(disb["scheduled_date"]):
        raise_err("ERR_DISBURSEMENT_TOO_EARLY", "Current date is before the scheduled_date")
    db.mutate(disb, status="SENT", sent_at=clock.now_iso(), sent_by_user_id=g.user_id)
    return success(db.serialize(disb))


@bp.route("/api/disbursements/<did>/confirm", methods=["POST"])
@require_roles("FinancialAidOfficer")
def confirm_disbursement(did):
    disb = get_disbursement_or_404(did)
    if disb["status"] != "SENT":
        raise_err("ERR_INVALID_STATE", "Only a SENT disbursement can be confirmed")
    if g.user_id == disb["sent_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The confirmer must differ from the sender")
    # A re-confirm after a return+reschedule retry supersedes the earlier
    # return: the row counts net-positive again (PRD §3.7 retry cycle).
    db.mutate(disb, status="CONFIRMED", confirmed_at=clock.now_iso(),
              _ever_confirmed=True, _returned_from_confirmed=False)
    engine.on_disbursement_confirmed(disb)
    return success(db.serialize(disb))


@bp.route("/api/disbursements/<did>/mark-returned", methods=["POST"])
@require_roles("FinancialAidOfficer")
def mark_returned(did):
    disb = get_disbursement_or_404(did)
    data = body()
    reason = data.get("returned_reason")
    if not isinstance(reason, str) or not reason:
        raise_err("ERR_VALIDATION", "returned_reason is required")
    if disb["status"] not in ("SENT", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE", "Only a SENT or CONFIRMED disbursement can be returned")
    from_confirmed = disb["status"] == "CONFIRMED"
    fields = {"status": "RETURNED", "returned_at": clock.now_iso(), "returned_reason": reason}
    if from_confirmed:
        fields["_returned_from_confirmed"] = True
    db.mutate(disb, **fields)
    engine.on_disbursement_returned(disb, from_confirmed)
    return success(db.serialize(disb))


@bp.route("/api/disbursements/<did>/reschedule", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def reschedule_disbursement(did):
    disb = get_disbursement_or_404(did)
    data = body()
    require_fields(data, ["scheduled_date", "term_start_date", "term_end_date"])
    scheduled = req_date(data, "scheduled_date")
    term_start = req_date(data, "term_start_date")
    term_end = req_date(data, "term_end_date")
    if term_end < term_start:
        raise_err("ERR_INVALID_DATE_RANGE", "term_end_date must be on or after term_start_date")
    if disb["status"] != "RETURNED":
        raise_err("ERR_INVALID_STATE", "Only a RETURNED disbursement can be rescheduled")
    _overlap_check(disb["award_id"], term_start, term_end, exclude_id=did)
    db.mutate(disb, status="SCHEDULED", scheduled_date=scheduled,
              term_start_date=term_start, term_end_date=term_end,
              sent_at=None, confirmed_at=None, returned_at=None)
    return success(db.serialize(disb))


@bp.route("/api/disbursements/<did>/cancel", methods=["POST"])
@require_roles("ScholarshipCoordinator")
def cancel_disbursement(did):
    disb = get_disbursement_or_404(did)
    if disb["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Only a SCHEDULED disbursement can be cancelled")
    db.mutate(disb, status="CANCELLED")
    return success(db.serialize(disb))
