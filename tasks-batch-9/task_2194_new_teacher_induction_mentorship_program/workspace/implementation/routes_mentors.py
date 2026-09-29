"""Mentor registration, training ledger and certification lifecycle."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import domain
from auth import (ADMIN, LEAD, MENTOR, actor, guard, own_mentor, own_site,
                  role, scope_rows)
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import add_days, db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field,
                        enum_list_field, fk, int_field, number_field, path_row,
                        str_field)

bp = Blueprint("mentors", __name__)


@bp.post("/mentors")
@guard([ADMIN, LEAD])
def register_mentor():
    data = body()
    site = fk("sites", data, "site_id")
    str_field(data, "site_id", 1, None)
    full_name = str_field(data, "full_name", 1, 120)
    endorsements = enum_list_field(data, "subject_endorsements", calc.SUBJECTS,
                                   min_items=1, max_items=len(calc.SUBJECTS))
    caseload_cap = int_field(data, "caseload_cap", 1, 4, required=False, default=2)
    own_site(site["id"])
    if site.get("status") != "OPEN":
        raise ApiError("ERR_SITE_CLOSED")
    row = new_row({
        "site_id": site["id"],
        "full_name": full_name,
        "subject_endorsements": list(endorsements),
        "caseload_cap": caseload_cap,
        "certification_status": "UNCERTIFIED",
        "certification_expires_on": None,
        "suspension_reason": None,
        "active_caseload_count": 0,
        "training_hours_current_cycle": 0.0,
        "training_modules_current_cycle": [],
        "verified_minutes_lifetime": 0,
        "stipend_accrued_cents": 0,
        "stipend_paid_cents": 0,
        "stipend_clawed_back_cents": 0,
    })
    db.mentors[row["id"]] = row
    return row_response(row, 201)


@bp.get("/mentors")
@guard([ADMIN, LEAD])
def list_mentors():
    rows = sorted_rows(list(db.mentors.values()))
    rows = scope_rows(rows, site_getter=lambda r: r.get("site_id"),
                      mentor_getter=lambda r: r.get("id"),
                      novice_id_getter=lambda r: None)
    rows = apply_filters(rows, {
        "site_id": ("site_id", "str"),
        "certification_status": ("certification_status", "str"),
        "subject_endorsement": ("subject_endorsements", "list"),
    })
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/mentors/<row_id>")
@guard([ADMIN, LEAD, MENTOR])
def get_mentor(row_id):
    row = path_row("mentors", row_id)
    if role() == LEAD:
        own_site(row.get("site_id"))
    else:
        own_mentor(row["id"])
    return row_response(row)


@bp.post("/mentors/<row_id>/training-credits")
@guard([ADMIN, LEAD])
def add_training_credit(row_id):
    mentor = path_row("mentors", row_id)
    data = body()
    module_code = enum_field(data, "module_code", calc.TRAINING_MODULES)
    hours = number_field(data, "hours")
    datetime_field(data, "completed_on")
    if role() == LEAD:
        own_site(mentor.get("site_id"))
    if mentor.get("certification_status") == "RETIRED":
        raise ApiError("ERR_MENTOR_CERT_STATE_INVALID")
    credit = calc.round_half_up(hours, 2)
    total = calc.round_half_up(
        Decimal(str(mentor.get("training_hours_current_cycle") or 0)) + credit, 2)
    mentor["training_hours_current_cycle"] = float(total)
    modules = list(mentor.get("training_modules_current_cycle") or [])
    if module_code not in modules:
        modules.append(module_code)
    mentor["training_modules_current_cycle"] = modules
    touch(mentor)
    return row_response(mentor)


def _reset_cycle(mentor):
    mentor["certification_expires_on"] = iso(add_days(now(), calc.CERTIFICATION_TERM_DAYS))
    mentor["training_hours_current_cycle"] = 0.0
    mentor["training_modules_current_cycle"] = []
    mentor["suspension_reason"] = None


def _training_ok(mentor, hours_required, modules_required):
    have = Decimal(str(mentor.get("training_hours_current_cycle") or 0))
    if calc.round_half_up(have, 2) < hours_required:
        return False
    modules = set(mentor.get("training_modules_current_cycle") or [])
    return all(m in modules for m in modules_required)


@bp.post("/mentors/<row_id>/certification")
@guard([ADMIN])
def certification_action(row_id):
    mentor = path_row("mentors", row_id)
    data = body()
    action = enum_field(data, "action",
                        ("CERTIFY", "RECERTIFY", "SUSPEND", "REINSTATE", "RETIRE"))
    required_reason = action == "SUSPEND"
    reason = str_field(data, "reason", 1, 1000, required=required_reason)
    status = mentor.get("certification_status")

    allowed = {
        "CERTIFY": ("UNCERTIFIED",),
        "RECERTIFY": ("LAPSED",),
        "SUSPEND": ("CERTIFIED",),
        "REINSTATE": ("SUSPENDED",),
        "RETIRE": ("UNCERTIFIED", "CERTIFIED", "LAPSED", "SUSPENDED"),
    }[action]
    if status not in allowed:
        raise ApiError("ERR_MENTOR_CERT_STATE_INVALID")

    if action == "RETIRE":
        for match in domain.matches_of_mentor(mentor["id"]):
            if match.get("match_status") in ("PROPOSED", "ACTIVE"):
                raise ApiError("ERR_MATCH_STATE_INVALID")
    if action == "REINSTATE":
        expires = parse_iso(mentor.get("certification_expires_on"))
        if expires is None or now() > expires:
            raise ApiError("ERR_MENTOR_CERT_STATE_INVALID")
    if action == "CERTIFY" and not _training_ok(mentor, calc.INITIAL_TRAINING_HOURS,
                                                calc.INITIAL_MODULES):
        raise ApiError("ERR_TRAINING_REQUIREMENTS_NOT_MET")
    if action == "RECERTIFY" and not _training_ok(mentor, calc.RECERT_TRAINING_HOURS,
                                                  calc.RECERT_MODULES):
        raise ApiError("ERR_TRAINING_REQUIREMENTS_NOT_MET")

    if action in ("CERTIFY", "RECERTIFY"):
        mentor["certification_status"] = "CERTIFIED"
        _reset_cycle(mentor)
        touch(mentor)
        if action == "RECERTIFY":
            cascades.reactivate_matches(mentor)
    elif action == "SUSPEND":
        mentor["certification_status"] = "SUSPENDED"
        mentor["suspension_reason"] = reason
        touch(mentor)
        cascades.suspend_mentor_matches(mentor)
    elif action == "REINSTATE":
        mentor["certification_status"] = "CERTIFIED"
        mentor["suspension_reason"] = None
        touch(mentor)
        cascades.reactivate_matches(mentor)
    else:
        mentor["certification_status"] = "RETIRED"
        mentor["certification_expires_on"] = None
        touch(mentor)
        for match in domain.matches_of_mentor(mentor["id"]):
            if match.get("match_status") == "SUSPENDED":
                cascades.end_match(match, "MENTOR_RETIRED")
    return row_response(mentor)
