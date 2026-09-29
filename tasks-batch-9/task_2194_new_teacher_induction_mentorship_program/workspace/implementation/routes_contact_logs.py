"""Contact logs: submission, review, resubmission and voiding."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, MENTOR, NOVICE, actor, guard, own_match,
                  own_mentor, own_site, role, scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field, fk,
                        int_field, path_row, str_field)

bp = Blueprint("contact_logs", __name__)


def _match_of(log):
    return db.matches.get(log.get("match_id"))


@bp.post("/contact-logs")
@guard([MENTOR, LEAD])
def create_contact_log():
    data = body()
    match = fk("matches", data, "match_id")
    str_field(data, "match_id", 1, None)
    contact_date = datetime_field(data, "contact_date")
    minutes = int_field(data, "minutes", 1, 300)
    contact_type = enum_field(data, "contact_type", calc.CONTACT_TYPES)
    description = str_field(data, "description", 20, 1000)
    novice = domain.novice_of_match(match)
    mentor = domain.mentor_of_match(match)
    if role() == MENTOR:
        own_mentor(match.get("mentor_id"))
    elif novice is not None:
        own_site(novice.get("site_id"))

    if match.get("match_status") != "ACTIVE":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    if mentor is None or mentor.get("certification_status") != "CERTIFIED":
        raise ApiError("ERR_MENTOR_NOT_CERTIFIED")

    activated = parse_iso(match.get("activated_at"))
    ended = parse_iso(match.get("ended_at"))
    day = contact_date.date()
    if activated is None or day < activated.date():
        raise ApiError("ERR_CONTACT_DATE_OUT_OF_WINDOW")
    if ended is not None and day > ended.date():
        raise ApiError("ERR_CONTACT_DATE_OUT_OF_WINDOW")
    if day > now().date():
        raise ApiError("ERR_CONTACT_DATE_OUT_OF_WINDOW")

    row = new_row({
        "match_id": match["id"],
        "contact_date": iso(contact_date),
        "minutes": minutes,
        "contact_type": contact_type,
        "description": description,
        "verification_status": "SUBMITTED",
        "credited_minutes": 0,
        "stipend_cents": 0,
        "rate_tier_at_verification": None,
        "cert_multiplier_at_verification": None,
        "submitted_by_user_id": actor(),
        "verified_by_user_id": None,
        "verified_at": None,
        "dispute_reason": None,
        "reject_reason": None,
        "void_reason": None,
        "resubmit_count": 0,
    })
    db.contact_logs[row["id"]] = row
    domain.recompute_mentor_totals(mentor)
    touch(mentor)
    return row_response(row, 201)


@bp.get("/contact-logs")
@guard([ADMIN, LEAD, MENTOR])
def list_contact_logs():
    rows = sorted_rows(list(db.contact_logs.values()))
    rows = scope_rows(rows, match_getter=_match_of)
    rows = apply_filters(rows, {
        "match_id": ("match_id", "str"),
        "verification_status": ("verification_status", "str"),
        "contact_date": ("contact_date", "date"),
    })
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/contact-logs/<row_id>")
@guard([ADMIN, LEAD, MENTOR, NOVICE])
def get_contact_log(row_id):
    row = path_row("contact_logs", row_id)
    own_match(_match_of(row))
    return row_response(row)


@bp.post("/contact-logs/<row_id>/review")
@guard([ADMIN, LEAD])
def review_contact_log(row_id):
    log = path_row("contact_logs", row_id)
    data = body()
    decision = enum_field(data, "decision", ("VERIFY", "DISPUTE", "REJECT"))
    note = str_field(data, "note", 1, 1000,
                     required=decision in ("DISPUTE", "REJECT"))
    match = _match_of(log)
    novice = domain.novice_of_match(match)
    mentor = domain.mentor_of_match(match)
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))

    if decision == "VERIFY" and match.get("match_status") != "ACTIVE":
        raise ApiError("ERR_MATCH_STATE_INVALID")
    needed = {"VERIFY": "SUBMITTED", "DISPUTE": "SUBMITTED", "REJECT": "DISPUTED"}[decision]
    if log.get("verification_status") != needed:
        raise ApiError("ERR_CONTACT_LOG_STATE_INVALID")
    if actor() is not None and actor() == log.get("submitted_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "VERIFY":
        already = domain.day_already_credited(match["id"], log.get("contact_date"), log["id"])
        room = calc.day_room(already)
        if room <= 0:
            raise ApiError("ERR_DAILY_CREDIT_CAP_REACHED")
        credited = min(calc.weighted_minutes(log.get("minutes"), log.get("contact_type")), room)
        tier = match.get("subject_match_tier")
        multiplier = (Decimal("1.00")
                      if mentor is not None and mentor.get("certification_status") == "CERTIFIED"
                      else Decimal("0.50"))
        log["verification_status"] = "VERIFIED"
        log["credited_minutes"] = credited
        log["rate_tier_at_verification"] = tier
        log["cert_multiplier_at_verification"] = float(multiplier)
        log["stipend_cents"] = calc.stipend_cents(credited, tier, multiplier)
        log["verified_by_user_id"] = actor()
        log["verified_at"] = iso(now())
        log["dispute_reason"] = None
        touch(log)
    elif decision == "DISPUTE":
        log["verification_status"] = "DISPUTED"
        log["dispute_reason"] = note
        touch(log)
    else:
        log["verification_status"] = "REJECTED"
        log["reject_reason"] = note
        log["credited_minutes"] = 0
        log["stipend_cents"] = 0
        touch(log)

    domain.recompute_match_totals(match)
    domain.recompute_mentor_totals(mentor)
    if decision == "VERIFY":
        touch(match)
        touch(mentor)
        domain.refresh_novice(novice)
    else:
        touch(mentor)
    return row_response(log)


@bp.post("/contact-logs/<row_id>/resubmit")
@guard([MENTOR])
def resubmit_contact_log(row_id):
    log = path_row("contact_logs", row_id)
    data = body()
    minutes = int_field(data, "minutes", 1, 300)
    contact_type = enum_field(data, "contact_type", calc.CONTACT_TYPES)
    description = str_field(data, "description", 20, 1000)
    match = _match_of(log)
    own_mentor(match.get("mentor_id") if match else None)
    if log.get("verification_status") != "DISPUTED":
        raise ApiError("ERR_CONTACT_LOG_STATE_INVALID")
    if int(log.get("resubmit_count") or 0) >= 2:
        raise ApiError("ERR_RESUBMIT_LIMIT_REACHED")
    log["minutes"] = minutes
    log["contact_type"] = contact_type
    log["description"] = description
    log["verification_status"] = "SUBMITTED"
    log["resubmit_count"] = int(log.get("resubmit_count") or 0) + 1
    log["dispute_reason"] = None
    log["submitted_by_user_id"] = actor()
    touch(log)
    mentor = domain.mentor_of_match(match)
    domain.recompute_mentor_totals(mentor)
    touch(mentor)
    return row_response(log)


@bp.post("/contact-logs/<row_id>/void")
@guard([ADMIN])
def void_contact_log(row_id):
    log = path_row("contact_logs", row_id)
    data = body()
    void_reason = str_field(data, "void_reason", 1, 1000)
    match = _match_of(log)
    mentor = domain.mentor_of_match(match)
    novice = domain.novice_of_match(match)
    if log.get("verification_status") != "VERIFIED":
        raise ApiError("ERR_CONTACT_LOG_STATE_INVALID")
    verified_at = parse_iso(log.get("verified_at"))
    if mentor is not None and verified_at is not None:
        for row in domain.disbursements_of_mentor(mentor["id"]):
            if row.get("status") not in ("APPROVED", "PAID"):
                continue
            start = parse_iso(row.get("period_start"))
            end = parse_iso(row.get("period_end"))
            if start is not None and end is not None and start <= verified_at <= end:
                raise ApiError("ERR_DISBURSEMENT_STATE_INVALID")

    log["verification_status"] = "VOIDED"
    log["void_reason"] = void_reason
    log["credited_minutes"] = 0
    log["stipend_cents"] = 0
    touch(log)
    domain.recompute_match_totals(match)
    touch(match)
    domain.recompute_mentor_totals(mentor)
    touch(mentor)
    domain.refresh_novice(novice)
    cascades.revoke_unsupported_attainments(novice)
    domain.refresh_snapshot_only(novice)
    return row_response(log)
