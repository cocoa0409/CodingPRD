"""Consult scheduling and lifecycle (PRD §3.3 - §3.6)."""
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_CROSS_PRACTICE_REFERENCE,
    ERR_CLIENT_SUSPENDED,
    ERR_NO_PACKAGE_CREDITS,
    ERR_CONSULT_NOT_SCHEDULED,
    ERR_CONSULT_NOT_IN_PROGRESS,
    ERR_CONSULT_NOT_STARTABLE,
    ERR_CONSULT_NOT_CANCELLABLE,
    ERR_NO_FEEDING_ASSESSMENT,
)
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, touch, serialize, get_body,
    require_str, require_enum, paginate, parse_iso,
)
from services.lookups import get_or_404, get_fk_or_404, recompute_credits_remaining
from services.scheduling import check_calendar_conflicts
from services.calculations import sliding_scale_fee
from services.cascade import apply_no_show

bp = Blueprint("consults", __name__)

CONSULT_TYPES = {"PRENATAL", "IN_HOME", "TELEHEALTH"}
PAY_METHODS = {"SELF_PAY", "PACKAGE"}
SCHEDULE_ROLES = {"FrontDesk", "PracticeAdmin"}
READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "FrontDesk", "Client"}


@bp.post("/consults")
def create_consult():
    # Priority 1-2: auth + role.
    _, role = get_auth()
    require_roles(role, SCHEDULE_ROLES)
    body = get_body()

    # Gather body fields (priority 4 FK existence + priority 5 well-formedness
    # below). Collect ids first for FK validation.
    practice_id = require_str(body, "practice_id")
    client_id = require_str(body, "client_id")
    consultant_id = require_str(body, "consultant_id")

    # Priority 4: referenced FK existence (practice_id, client_id, consultant_id).
    practice = get_fk_or_404(db.practices, practice_id)
    client = get_fk_or_404(db.clients, client_id)
    consultant = get_fk_or_404(db.consultants, consultant_id)

    # Priority 5: well-formedness — enums, required fields, end strictly after
    # start.
    consult_type = require_enum(body, "consult_type", CONSULT_TYPES)
    start_iso = require_str(body, "scheduled_start_utc")
    end_iso = require_str(body, "scheduled_end_utc")
    pay_method = require_enum(body, "pay_method", PAY_METHODS)
    start_dt = parse_iso(start_iso)
    end_dt = parse_iso(end_iso)
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_REQUEST,
                  "scheduled_end_utc must be strictly after scheduled_start_utc")

    # Priority 6: cross-practice integrity.
    if client["practice_id"] != practice_id or consultant["practice_id"] != practice_id:
        raise err(ERR_CROSS_PRACTICE_REFERENCE,
                  "Consultant and client must belong to the consult's practice")

    # Priority 8: client must be ACTIVE.
    if client["status"] != "ACTIVE":
        raise err(ERR_CLIENT_SUSPENDED, "Client is suspended")

    # Priority 10 + 10.5: consultant then client calendar conflicts.
    check_calendar_conflicts(practice_id, client_id, consultant_id,
                             consult_type, start_iso, end_iso)

    # Priority 12: package-credit sufficiency.
    if pay_method == "PACKAGE" and client["package_credits_remaining"] < 1:
        raise err(ERR_NO_PACKAGE_CREDITS, "Client has no remaining package credits")

    # Fee: SELF_PAY -> sliding scale; PACKAGE -> 0 (credit committed at
    # completion) (PRD §3.3).
    if pay_method == "SELF_PAY":
        tiers = [t for t in db.sliding_scale_tiers.values()
                 if t["practice_id"] == practice_id]
        fee_cents = sliding_scale_fee(
            tiers, client["household_income_cents"],
            consultant["standard_rate_cents"],
        )
    else:
        fee_cents = 0

    record = {
        "practice_id": practice_id,
        "client_id": client_id,
        "consultant_id": consultant_id,
        "consult_type": consult_type,
        "scheduled_start_utc": start_iso,
        "scheduled_end_utc": end_iso,
        "pay_method": pay_method,
        "fee_cents": fee_cents,
        "package_credit_redeemed": False,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    }
    init_full(record)
    db.consults[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/consults/<rid>")
def get_consult(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.consults, rid)
    return object_response(serialize(record), 200)


@bp.get("/consults")
def list_consults():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    client_id = request.args.get("client_id")
    consultant_id = request.args.get("consultant_id")
    practice_id = request.args.get("practice_id")
    records = []
    for r in db.consults.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if consultant_id is not None and r["consultant_id"] != consultant_id:
            continue
        if practice_id is not None and r["practice_id"] != practice_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.post("/consults/<rid>/reschedule")
def reschedule_consult(rid):
    _, role = get_auth()
    require_roles(role, SCHEDULE_ROLES)
    consult = get_or_404(db.consults, rid)
    body = get_body()
    start_iso = require_str(body, "scheduled_start_utc")
    end_iso = require_str(body, "scheduled_end_utc")
    start_dt = parse_iso(start_iso)
    end_dt = parse_iso(end_iso)
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_REQUEST,
                  "scheduled_end_utc must be strictly after scheduled_start_utc")

    # State: must be SCHEDULED (PRD §3.5).
    if consult["status"] != "SCHEDULED":
        raise err(ERR_CONSULT_NOT_SCHEDULED, "Consult is not SCHEDULED")

    client = db.clients[consult["client_id"]]
    # Client active-status (PRD §3.5).
    if client["status"] != "ACTIVE":
        raise err(ERR_CLIENT_SUSPENDED, "Client is suspended")

    # Calendar conflicts (consultant then client), excluding this consult.
    check_calendar_conflicts(
        consult["practice_id"], consult["client_id"], consult["consultant_id"],
        consult["consult_type"], start_iso, end_iso, exclude_id=consult["id"],
    )

    # SCHEDULED -> RESCHEDULED -> SCHEDULED (auto-confirm in same request).
    consult["scheduled_start_utc"] = start_iso
    consult["scheduled_end_utc"] = end_iso
    consult["reschedule_count"] += 1
    # status stays SCHEDULED after auto-confirm.
    touch(consult)
    return object_response(serialize(consult), 200)


@bp.post("/consults/<rid>/start")
def start_consult(rid):
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    consult = get_or_404(db.consults, rid)
    # State: SCHEDULED (PRD §3.5).
    if consult["status"] != "SCHEDULED":
        raise err(ERR_CONSULT_NOT_SCHEDULED, "Consult is not SCHEDULED")
    # Clock: now_utc >= scheduled_start_utc (PRD §3.5).
    practice = db.practices[consult["practice_id"]]
    if parse_iso(practice["now_utc"]) < parse_iso(consult["scheduled_start_utc"]):
        raise err(ERR_CONSULT_NOT_STARTABLE, "Practice clock is before start")
    consult["status"] = "IN_PROGRESS"
    touch(consult)
    return object_response(serialize(consult), 200)


@bp.post("/consults/<rid>/complete")
def complete_consult(rid):
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    consult = get_or_404(db.consults, rid)
    # State: IN_PROGRESS (PRD §3.5).
    if consult["status"] != "IN_PROGRESS":
        raise err(ERR_CONSULT_NOT_IN_PROGRESS, "Consult is not IN_PROGRESS")
    # A FeedingAssessment must exist for this consult (PRD §3.5).
    has_assessment = any(
        fa["consult_id"] == consult["id"]
        for fa in db.feeding_assessments.values()
    )
    if not has_assessment:
        raise err(ERR_NO_FEEDING_ASSESSMENT, "No feeding assessment for this consult")

    consult["status"] = "COMPLETED"
    # If PACKAGE: commit the credit (PRD §3.5).
    if consult["pay_method"] == "PACKAGE":
        consult["package_credit_redeemed"] = True
        client = db.clients[consult["client_id"]]
        client["package_credits_consumed"] += 1
        recompute_credits_remaining(client)
        touch(client)
    touch(consult)
    return object_response(serialize(consult), 200)


@bp.post("/consults/<rid>/no-show")
def no_show_consult(rid):
    _, role = get_auth()
    require_roles(role, SCHEDULE_ROLES)
    consult = get_or_404(db.consults, rid)
    # State: SCHEDULED (PRD §3.6).
    if consult["status"] != "SCHEDULED":
        raise err(ERR_CONSULT_NOT_SCHEDULED, "Consult is not SCHEDULED")
    # Clock: now_utc >= scheduled_start_utc (PRD §3.6).
    practice = db.practices[consult["practice_id"]]
    if parse_iso(practice["now_utc"]) < parse_iso(consult["scheduled_start_utc"]):
        raise err(ERR_CONSULT_NOT_STARTABLE, "Practice clock is before start")

    # Transition this consult to NO_SHOW, then run the cascade on the client.
    consult["status"] = "NO_SHOW"
    touch(consult)
    client = db.clients[consult["client_id"]]
    apply_no_show(consult, client)
    return object_response(serialize(consult), 200)


@bp.post("/consults/<rid>/cancel")
def cancel_consult(rid):
    _, role = get_auth()
    require_roles(role, SCHEDULE_ROLES)
    consult = get_or_404(db.consults, rid)
    # State: SCHEDULED, else not cancellable (PRD §3.6).
    if consult["status"] != "SCHEDULED":
        raise err(ERR_CONSULT_NOT_CANCELLABLE, "Consult is not SCHEDULED")

    consult["status"] = "CANCELLED"
    # If package credit was committed, return it (PRD §3.6).
    if consult["pay_method"] == "PACKAGE" and consult["package_credit_redeemed"]:
        client = db.clients[consult["client_id"]]
        if client["package_credits_consumed"] > 0:
            client["package_credits_consumed"] -= 1
        recompute_credits_remaining(client)
        touch(client)
    touch(consult)
    return object_response(serialize(consult), 200)
