"""Booking and TaftHartleyReport endpoints."""
from flask import Blueprint, request

import db
from errors import (err_booking_precondition, err_engagement_overlap,
                    err_filing_window, err_invalid_request, err_invalid_state,
                    err_minor_hours, err_not_found, err_permit_required,
                    err_ref_not_found)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_enum, check_string, filter_status, get_payload,
                  logical_now, new_record, paginate, serialize, touch)

S = db.STORE
bp = Blueprint("bookings", __name__)

CANCEL_REASONS = {"PRODUCTION_CANCELLED", "TALENT_CANCELLED", "FORCE_MAJEURE", "PERMIT_REVOKED"}


def _get_booking(bid):
    b = domain.find("bookings", bid)
    if b is None:
        raise err_not_found("Booking not found")
    return b


def _booking_context(booking):
    sub = domain.find("submissions", booking["submission_id"])
    memo = domain.find("deal_memos", booking["deal_memo_id"])
    bd = domain.find("breakdowns", sub["breakdown_id"]) if sub else None
    role = domain.find("roles", bd["role_id"]) if bd else None
    production = domain.find("productions", bd["production_id"]) if bd else None
    talent = domain.find("talents", sub["talent_id"]) if sub else None
    return sub, memo, bd, role, production, talent


def _check_permit_gate(role, production, talent, engagement_end, work_permit_id=None):
    """PRD 3.8 permit gate: when role is_minor_role and talent is_minor, there
    must exist a VERIFIED permit covering that talent and production whose
    valid_until reaches at least the engagement's final day. The rule is
    existential over the (talent, production) permit set — the booking's
    referenced work_permit_id need not itself be the VERIFIED permit."""
    if not (role is not None and role.get("is_minor_role")):
        return None
    if talent is None or not domain.compute_is_minor(talent):
        return None
    permit = domain.permit_covers(talent["id"], production["id"], engagement_end)
    if permit is None:
        raise err_permit_required()
    return permit


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

@bp.post("/casting/bookings")
def create_booking():
    require_roles("ProductionCoordinator")
    body = get_payload()
    # Body FK existence
    sub = None
    if body.get("submission_id") is not None:
        sub = domain.find("submissions", body.get("submission_id"))
        if sub is None:
            raise err_ref_not_found("submission_id does not reference a Submission")
    memo = None
    if body.get("deal_memo_id") is not None:
        memo = domain.find("deal_memos", body.get("deal_memo_id"))
        if memo is None:
            raise err_ref_not_found("deal_memo_id does not reference a DealMemo")
    permit = None
    if body.get("work_permit_id") is not None:
        permit = domain.find("permits", body.get("work_permit_id"))
        if permit is None:
            raise err_ref_not_found("work_permit_id does not reference a MinorWorkPermit")
    # Creation gate (ERR_BOOKING_PRECONDITION): ACCEPTED offer on the
    # submission, EXECUTED memo bound to that offer, no live booking, and the
    # submission ready to move OFFER_PENDING -> BOOKED.
    if sub is not None and memo is not None:
        accepted = [o for o in S["offers"].values()
                    if o["submission_id"] == sub["id"] and o["status"] == "ACCEPTED"]
        has_live_booking = any(
            b["submission_id"] == sub["id"] and b["status"] in ("PENDING", "CONFIRMED")
            for b in S["bookings"].values())
        if sub["status"] != "OFFER_PENDING" or not accepted \
                or memo["status"] != "EXECUTED" or memo["offer_id"] != accepted[0]["id"] \
                or has_live_booking:
            raise err_booking_precondition()
    # Permit gate at creation (PRD 3.8)
    minor_booking = False
    if sub is not None and memo is not None:
        bd = domain.find("breakdowns", sub["breakdown_id"])
        role = domain.find("roles", bd["role_id"]) if bd else None
        production = domain.find("productions", bd["production_id"]) if bd else None
        talent = domain.find("talents", sub["talent_id"])
        minor_booking = role is not None and role.get("is_minor_role") \
            and talent is not None and domain.compute_is_minor(talent)
        _check_permit_gate(role, production, talent, memo["engagement_end"],
                           work_permit_id=body.get("work_permit_id"))
    # Final field validation
    check_string(body, "submission_id")
    check_string(body, "deal_memo_id")
    if body.get("work_permit_id") is not None:
        check_string(body, "work_permit_id", required=False)
    # PRD 3.8: "For such minor bookings the booking's work_permit_id is
    # required at creation; for adult bookings it is simply absent."
    if minor_booking and body.get("work_permit_id") is None:
        raise err_invalid_request("work_permit_id is required for minor bookings")
    rec = new_record({
        "submission_id": sub["id"],
        "deal_memo_id": memo["id"],
        "work_permit_id": body.get("work_permit_id"),
        "confirmed_at": None,
        "cancelled_at": None,
        "cancellation_reason": None,
        "status": "PENDING",
    })
    S["bookings"][rec["id"]] = rec
    # Creation closes out the breakdown race (PRD 3.9)
    bd = domain.find("breakdowns", sub["breakdown_id"])
    role = domain.find("roles", bd["role_id"]) if bd else None
    talent = domain.find("talents", sub["talent_id"])
    sub["status"] = "BOOKED"
    touch(sub)
    if role is not None and role["status"] == "OPEN":
        role["status"] = "CAST"
        touch(role)
    for other in S["submissions"].values():
        if other["id"] == sub["id"] or other["breakdown_id"] != bd["id"]:
            continue
        if other["status"] in ("SUBMITTED", "UNDER_REVIEW", "SHORTLISTED",
                               "CALLBACK_INVITED", "CALLBACK_COMPLETED", "OFFER_PENDING"):
            other["status"] = "NOT_BOOKED"
            touch(other)
            domain.release_active_holds_on_submission(other["id"])
    if talent is not None:
        domain.recompute_union_count(talent)
    return success_object(serialize(rec), 201)


@bp.get("/casting/bookings/<bid>")
def get_booking(bid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent", "Guardian")
    return success_object(serialize(_get_booking(bid)))


@bp.get("/casting/bookings")
def list_bookings():
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator")
    records = filter_status(S["bookings"].values())
    for param in ("submission_id", "deal_memo_id", "work_permit_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/submissions/<sid>/bookings")
def list_submission_bookings(sid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    if domain.find("submissions", sid) is None:
        raise err_not_found("Submission not found")
    records = filter_status(domain.children("bookings", "submission_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/bookings/<bid>/confirm")
def confirm_booking(bid):
    require_roles("ProductionCoordinator")
    booking = _get_booking(bid)
    sub, memo, bd, role, production, talent = _booking_context(booking)
    # state-machine legality
    if booking["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING booking can be confirmed")
    if memo is None or memo["status"] != "EXECUTED":
        raise err_invalid_state("Deal memo must still be EXECUTED to confirm")
    # permit gate
    permit = None
    if role is not None and role.get("is_minor_role") and talent is not None \
            and domain.compute_is_minor(talent):
        permit = _check_permit_gate(role, production, talent, memo["engagement_end"],
                                    work_permit_id=booking.get("work_permit_id"))
    # daily-hours cap (role is_minor_role): 8-hour standard day vs caps
    if role is not None and role.get("is_minor_role"):
        if permit is None and booking.get("work_permit_id") is not None:
            permit = domain.find("permits", booking["work_permit_id"])
        if permit is not None and domain.minor_hours_exceeded(
                permit, memo["engagement_start"], memo["engagement_end"]):
            raise err_minor_hours()
    # engagement overlap: CLOSED day-intervals against other CONFIRMED bookings
    for other in S["bookings"].values():
        if other["id"] == booking["id"] or other["status"] != "CONFIRMED":
            continue
        other_sub = domain.find("submissions", other["submission_id"])
        if other_sub is None or other_sub["talent_id"] != sub["talent_id"]:
            continue
        other_memo = domain.find("deal_memos", other["deal_memo_id"])
        if other_memo is None:
            continue
        if other_memo["engagement_start"] <= memo["engagement_end"] \
                and memo["engagement_start"] <= other_memo["engagement_end"]:
            raise err_engagement_overlap()
    booking["status"] = "CONFIRMED"
    booking["confirmed_at"] = logical_now()
    touch(booking)
    if talent is not None:
        domain.recompute_union_count(talent)
    domain.maybe_auto_taft_hartley(booking)
    return success_object(serialize(booking))


@bp.post("/casting/bookings/<bid>/cancel")
def cancel_booking(bid):
    require_roles("ProductionCoordinator")
    booking = _get_booking(bid)
    body = get_payload()
    if booking["status"] not in ("PENDING", "CONFIRMED"):
        raise err_invalid_state("Only PENDING or CONFIRMED bookings can be cancelled")
    was_confirmed = booking["status"] == "CONFIRMED"
    reason = check_enum(body, "cancellation_reason", CANCEL_REASONS)
    sub, memo, bd, role, production, talent = _booking_context(booking)
    domain.cancel_booking_record(booking, reason, compute_penalty=was_confirmed)
    if was_confirmed:
        # full unwind: submission BOOKED -> NOT_BOOKED, role CAST -> OPEN
        if sub is not None and sub["status"] == "BOOKED":
            sub["status"] = "NOT_BOOKED"
            touch(sub)
        if role is not None and role["status"] == "CAST":
            role["status"] = "OPEN"
            touch(role)
    return success_object(serialize(booking))


# ---------------------------------------------------------------------------
# Taft-Hartley reports
# ---------------------------------------------------------------------------

def _get_report(rid):
    r = domain.find("taft_hartley_reports", rid)
    if r is None:
        raise err_not_found("TaftHartleyReport not found")
    return r


@bp.get("/casting/taft-hartley/<rid>")
def get_report(rid):
    require_roles("CastingDirector", "ProductionCoordinator")
    return success_object(serialize(_get_report(rid)))


@bp.get("/casting/productions/<pid>/taft-hartley")
def list_production_reports(pid):
    require_roles("CastingDirector", "ProductionCoordinator")
    if domain.find("productions", pid) is None:
        raise err_not_found("Production not found")
    records = filter_status(domain.children("taft_hartley_reports", "production_id", pid))
    tid = request.args.get("talent_id")
    if tid is not None:
        records = [r for r in records if r.get("talent_id") == tid]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/taft-hartley")
def list_reports():
    require_roles("CastingDirector", "ProductionCoordinator")
    records = filter_status(S["taft_hartley_reports"].values())
    for param in ("talent_id", "booking_id", "production_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/taft-hartley/<rid>/file")
def file_report(rid):
    require_roles("ProductionCoordinator")
    rep = _get_report(rid)
    if rep["status"] == "PENDING":
        if not logical_now() <= rep["filing_deadline"]:
            raise err_filing_window("PENDING report is past its filing deadline")
    elif rep["status"] == "LATE":
        pass  # late filing still accepted, recorded against the deadline
    else:
        raise err_filing_window("Report cannot be filed from its current state")
    rep["status"] = "FILED"
    rep["filed_at"] = logical_now()
    touch(rep)
    return success_object(serialize(rep))
