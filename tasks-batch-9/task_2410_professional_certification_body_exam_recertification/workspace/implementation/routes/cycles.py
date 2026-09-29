"""RecertificationCycle endpoints (PRD 3.11)."""

from decimal import Decimal

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CERTIFICANT,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_ETHICS_OFFICER,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_enum,
    req_int,
    req_num,
    req_str,
    req_ts,
)
from response import apply_filters, bool_filter, created_response, object_response, paginate, \
    read_pagination
from services import calc, cascades, derive, lookup
from util import add_days

bp = Blueprint("cycles", __name__)

CEU_CATEGORIES = ("LIVE_INSTRUCTION", "SELF_STUDY", "PRESENTING", "PUBLICATION", "VOLUNTEER")


def own_certificant(actor, certificant):
    """Layer 6: a Certificant-role caller acts only on their own credential."""
    if actor.role == ROLE_CERTIFICANT and certificant["candidate_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


@bp.get("/recertification-cycles/<cycle_id>")
@api
def read_cycle(cycle_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT,
                  ROLE_ELIGIBILITY_REVIEWER])
    return object_response(serialize.cycle(lookup.cycle(cycle_id)))


@bp.get("/recertification-cycles")
@api
def list_cycles():
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ETHICS_OFFICER, ROLE_CERTIFICANT,
                  ROLE_ELIGIBILITY_REVIEWER])
    limit, offset = read_pagination()
    rows = ordered(DB.cycles.values())
    rows = apply_filters(rows, {
        "certificant_id": "certificant_id",
        "reexam_registration_id": "reexam_registration_id",
        "status": "status",
        "path": "path",
    })
    return paginate(rows, serialize.cycle, limit, offset)


@bp.post("/recertification-cycles/<cycle_id>/close")
@api
def close_cycle(cycle_id):
    actor = authenticate([ROLE_CERTIFICANT, ROLE_PROGRAM_ADMIN])
    cycle = lookup.cycle(cycle_id)
    certificant = lookup.certificant_of_cycle(cycle)

    # Layer 6.
    own_certificant(actor, certificant)

    body = ensure_body(peek_body())
    expected_certificant_version = req_int(body, "expected_certificant_version", minimum=0)

    # Layer 11.
    if expected_certificant_version != certificant["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Layer 16.
    if certificant["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICANT_NOT_ACTIVE")

    # Layer 39: a cycle is closable only once it is SATISFIED.
    if cycle["status"] != "SATISFIED":
        raise ApiError("ERR_CREDITS_NOT_SATISFIED")

    program = lookup.program_of_certificant(certificant)
    cascades.cascade_cycle_closed(cycle, certificant, program)
    return object_response(serialize.cycle(cycle))


@bp.post("/recertification-cycles/<cycle_id>/elect-reexam")
@api
def elect_reexam(cycle_id):
    actor = authenticate([ROLE_CERTIFICANT])
    cycle = lookup.cycle(cycle_id)
    certificant = lookup.certificant_of_cycle(cycle)
    own_certificant(actor, certificant)
    body = ensure_body(peek_body())
    opt_str(body, "election_note")

    # Layer 12.
    if cycle["status"] not in ("OPEN", "LAPSED") or cycle["path"] != "CEU":
        raise ApiError("ERR_INVALID_STATE")

    cascades.cascade_elect_reexam(cycle)
    derive.refresh_certificant_projection(certificant)
    return object_response(serialize.cycle(cycle))


@bp.post("/recertification-cycles/<cycle_id>/reinstate")
@api
def reinstate_cycle(cycle_id):
    actor = authenticate([ROLE_CERTIFICANT])
    cycle = lookup.cycle(cycle_id)
    certificant = lookup.certificant_of_cycle(cycle)
    own_certificant(actor, certificant)
    body = ensure_body(peek_body())
    payment_cents = req_int(body, "payment_cents", minimum=0)

    # Layer 12.
    if cycle["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE")

    # Layer 17.
    if certificant["status"] == "REVOKED":
        raise ApiError("ERR_CERTIFICANT_ALREADY_REVOKED")

    # Layer 45.
    assessed = cycle["reinstatement_fee_cents"]
    if assessed is not None and payment_cents < assessed:
        raise ApiError("ERR_REINSTATEMENT_FEE_UNPAID")

    program = lookup.program_of_certificant(certificant)
    cycle["status"] = "OPEN"
    cycle["grace_ends_on"] = add_days(cycle["grace_ends_on"], program["recert_grace_days"])
    cycle["reinstatement_fee_cents"] = None
    touch(cycle)

    if certificant["status"] == "EXPIRED":
        certificant["status"] = "ACTIVE"
        touch(certificant)
    derive.refresh_certificant_projection(certificant)
    return object_response(serialize.cycle(cycle))


@bp.post("/recertification-cycles/<cycle_id>/ceu-activities")
@api
def claim_credit(cycle_id):
    actor = authenticate([ROLE_CERTIFICANT])
    cycle = lookup.cycle(cycle_id)
    certificant = lookup.certificant_of_cycle(cycle)

    # Layer 6.
    own_certificant(actor, certificant)

    body = ensure_body(peek_body())
    activity_date = req_ts(body, "activity_date")
    category = req_enum(body, "category", CEU_CATEGORIES)
    provider = req_str(body, "provider")
    contact_hours = req_num(body, "contact_hours", exclusive_minimum=0, max_places=2)

    # Layer 12.
    if cycle["status"] not in ("OPEN", "SATISFIED"):
        raise ApiError("ERR_INVALID_STATE")

    # Layer 16.
    if certificant["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICANT_NOT_ACTIVE")

    # Layer 33: the accrual window, whose shape depends on the cycle's snapshot.
    if not calc.in_accrual_window(cycle, activity_date):
        raise ApiError("ERR_ACTIVITY_OUTSIDE_CYCLE")

    activity = new_record(
        cycle_id=cycle["id"],
        activity_date=activity_date,
        category=category,
        provider=provider,
        contact_hours=contact_hours,
        credits_awarded=Decimal("0.00"),
        credits_counted=Decimal("0.00"),
        counted=False,
        status="SUBMITTED",
        reviewer_user_id=None,
        audit_verifier_user_id=None,
        review_note=None,
    )
    activity["credits_awarded"] = calc.ceu_award(activity)
    mark_created(activity)
    DB.activities[activity["id"]] = activity
    return created_response(serialize.activity(activity))


@bp.get("/recertification-cycles/<cycle_id>/ceu-activities")
@api
def list_cycle_activities(cycle_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ELIGIBILITY_REVIEWER, ROLE_CERTIFICANT])
    cycle = lookup.cycle(cycle_id)
    limit, offset = read_pagination()
    counted = bool_filter("counted")
    rows = derive.activities_of_cycle(cycle["id"])
    rows = apply_filters(rows, {"status": "status", "category": "category"})
    if counted is not None:
        rows = [r for r in rows if r["counted"] is counted]
    return paginate(rows, serialize.activity, limit, offset)
