"""Quality audit sampling, independence and score reconciliation."""

from datetime import timedelta

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, now, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.checklist import turnover_tasks
from services.listing import sort_default
from services.money import dec, round_half_up
from services.pay import find_pay_line, recompute_pay_line, sync_cleaner
from services.serialize import quality_audit_view
from services.window import AUDIT_WINDOW_HOURS

bp = Blueprint("audits", __name__)

AUDIT_STATUSES = ("SAMPLED", "FINALIZED", "VOIDED")

AUDIT_WEIGHT = dec("0.60")
GUEST_WEIGHT = dec("0.40")
GUEST_RATING_SCALE = dec(20)
ROLLING_WEIGHT = dec("0.70")
OBSERVED_WEIGHT = dec("0.30")
AUDIT_BONUS_SCORE = 95
AUDIT_BONUS_CENTS = 1000
AUDIT_PENALTY_SCORE = 70
AUDIT_PENALTY_CENTS = -1200


@bp.post("/quality-audits")
def create_quality_audit():
    actor = authenticate(("QualityAuditor",))
    body = v.json_body()
    turnover_id = v.req_string(body, "turnover_id", allow_empty=False)
    score = v.req_int(body, "score", minimum=0, maximum=100)
    findings = v.opt_string(body, "findings")

    turnover = lookup.get_turnover(turnover_id)

    if turnover["status"] != "COMPLETED":
        fail(errors.ERR_TURNOVER_NOT_COMPLETED,
             "Only a COMPLETED turnover may be sampled.")

    assignment = lookup.turnover_assignment_in(turnover["id"], ("COMPLETED",))
    if assignment is not None and assignment["assigned_by_user_id"] == actor.user_id:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The acting auditor also assigned the cleaner on this turnover.")
    for task in turnover_tasks(turnover["id"]):
        if task["reviewed_by_user_id"] == actor.user_id:
            fail(errors.ERR_SEGREGATION_OF_DUTIES,
                 "The acting auditor also reviewed a checklist task on this turnover.")

    if turnover["finished_at"] is None or (
            now() > turnover["finished_at"] + timedelta(hours=AUDIT_WINDOW_HOURS)):
        fail(errors.ERR_AUDIT_WINDOW_CLOSED,
             "Sampling is permitted only within 72 hours of finished_at.")

    for existing in db.quality_audits.values():
        if existing["turnover_id"] == turnover["id"] and existing["status"] != "VOIDED":
            fail(errors.ERR_AUDIT_ALREADY_EXISTS,
                 "This turnover already carries a live audit.")

    record = base_fields()
    record.update({
        "turnover_id": turnover["id"],
        "cleaner_id": assignment["cleaner_id"] if assignment is not None else None,
        "auditor_user_id": actor.user_id,
        "score": score,
        "findings": findings,
        "variant_applied": None,
        "guest_rating_at_audit": None,
        "observed_score": None,
        "resulting_quality_score": None,
        "pay_adjustment_cents": 0,
        "status": "SAMPLED",
        "finalized_at": None,
    })
    db.quality_audits[record["id"]] = record
    return created(quality_audit_view(record))


@bp.get("/quality-audits")
def list_quality_audits():
    actor = authenticate(("PlatformAdmin", "Coordinator", "QualityAuditor", "PropertyOwner"))
    limit, offset = v.pagination()
    turnover_id = v.query_string("turnover_id")
    cleaner_id = v.query_string("cleaner_id")
    property_id = v.query_string("property_id")
    status = v.query_enum("status", AUDIT_STATUSES)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.quality_audits.values())
    if turnover_id is not None:
        rows = [a for a in rows if a["turnover_id"] == turnover_id]
    if cleaner_id is not None:
        rows = [a for a in rows if a["cleaner_id"] == cleaner_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if property_id is not None:
        rows = [a for a in rows if _audit_property_id(a) == property_id]
    rows = sort_default(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([quality_audit_view(r) for r in page], limit, offset, total)


def _audit_property_id(audit):
    turnover = db.turnovers.get(audit["turnover_id"])
    return turnover["property_id"] if turnover is not None else None


@bp.get("/quality-audits/<audit_id>")
def read_quality_audit(audit_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "QualityAuditor", "PropertyOwner"))
    audit = lookup.get_quality_audit(audit_id)
    lookup.owner_scope_resource(actor, _audit_property_id(audit))
    return ok(quality_audit_view(audit))


@bp.post("/quality-audits/<audit_id>/finalize")
def finalize_quality_audit(audit_id):
    actor = authenticate(("QualityAuditor",))
    audit = lookup.get_quality_audit(audit_id)

    if audit["auditor_user_id"] != actor.user_id:
        fail(errors.ERR_NOT_AUDIT_OWNER, "Only the sampling auditor may finalize this audit.")
    if audit["status"] != "SAMPLED":
        fail(errors.ERR_INVALID_AUDIT_STATE, "Only a SAMPLED audit may be finalized.")

    turnover = db.turnovers[audit["turnover_id"]]
    prop = db.properties[turnover["property_id"]]
    cleaner = db.cleaners.get(audit["cleaner_id"])

    incoming = None
    if turnover.get("incoming_booking_id"):
        incoming = db.bookings.get(turnover["incoming_booking_id"])
    guest_rating = incoming["cleanliness_rating"] if incoming is not None else None

    score = dec(audit["score"])
    if guest_rating is not None:
        audit["variant_applied"] = "BLENDED"
        audit["guest_rating_at_audit"] = guest_rating
        observed = round_half_up(
            AUDIT_WEIGHT * score + GUEST_WEIGHT * (dec(guest_rating) * GUEST_RATING_SCALE), 2)
    else:
        audit["variant_applied"] = "AUDIT_ONLY"
        audit["guest_rating_at_audit"] = None
        observed = round_half_up(score, 2)
    audit["observed_score"] = observed

    if audit["score"] >= AUDIT_BONUS_SCORE:
        adjustment = AUDIT_BONUS_CENTS
    elif audit["score"] < AUDIT_PENALTY_SCORE:
        adjustment = AUDIT_PENALTY_CENTS
    else:
        adjustment = 0
    audit["pay_adjustment_cents"] = adjustment

    if cleaner is not None:
        resulting = round_half_up(
            ROLLING_WEIGHT * dec(cleaner["quality_score"]) + OBSERVED_WEIGHT * observed, 2)
        cleaner["quality_score"] = resulting
        audit["resulting_quality_score"] = resulting
    else:
        audit["resulting_quality_score"] = None

    audit["status"] = "FINALIZED"
    audit["finalized_at"] = now()
    touch(audit)

    if adjustment != 0:
        pay_line = find_pay_line(turnover["id"], ("FINAL",))
        if pay_line is not None:
            pay_line["audit_adjustment_cents"] = adjustment
            pay_line["status"] = "ADJUSTED"
            recompute_pay_line(pay_line, turnover, prop, cleaner, "FINAL")
    sync_cleaner(cleaner, force=cleaner is not None)

    return ok(quality_audit_view(audit))
