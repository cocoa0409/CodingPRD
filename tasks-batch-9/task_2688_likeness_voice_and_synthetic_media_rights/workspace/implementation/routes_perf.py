"""Generated performances: submission, the approval right and resubmission."""

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, new_id, now, public,
    respond, touch, want_code_list, want_dt, want_enum, want_int, want_str,
)

bp = Blueprint("performances", __name__)

REJECTION_REASONS = ("OFF_BRAND", "OUT_OF_SCOPE", "QUALITY",
                     "REVIEW_WINDOW_LAPSED", "REVISION_LIMIT_REACHED")
DECISIONS = ("APPROVE", "REQUEST_REVISION", "REJECT")


def _per_use_floor_or_zero(grant, media_type):
    row, floor = calc.per_use_floor(grant, media_type)
    return floor or 0


@bp.post("/generated-performances")
def submit_performance():
    authorize("LicenseeProducer")
    body = body_json()
    digital_replica_id = want_str(body, "digital_replica_id", 1, None)
    licensee_name = want_str(body, "licensee_name", 1, 200)
    media_type = want_enum(body, "media_type", calc.MEDIA_TYPES)
    territory_codes = want_code_list(body, "territory_codes", 20)
    intended_use_description = want_str(body, "intended_use_description", 1, 500)
    projected_impressions = want_int(body, "projected_impressions", 0)
    scheduled_first_use_at = want_dt(body, "scheduled_first_use_at")

    replica = guards.need_replica(digital_replica_id)
    grant = db.consent_grants[replica["consent_grant_id"]]
    talent = db.talents[replica["talent_id"]]

    floor = guards.need_union_per_use_floor(grant, media_type)

    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")
    if replica["status"] != "APPROVED_FOR_USE":
        fail("ERR_INVALID_REPLICA_STATE",
             "only an APPROVED_FOR_USE replica may back a performance")
    guards.block_frozen(talent)

    if media_type not in grant["permitted_media_types"]:
        fail("ERR_MEDIA_TYPE_OUT_OF_SCOPE",
             "%s is outside the grant's permitted media types" % media_type)
    for code in territory_codes:
        if code not in grant["territory_codes"]:
            fail("ERR_TERRITORY_OUT_OF_SCOPE",
                 "territory %s is outside the grant's scope" % code)

    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "digital_replica_id": replica["id"],
        "licensee_user_id": g.user_id,
        "licensee_name": licensee_name,
        "media_type": media_type,
        "territory_codes": territory_codes,
        "intended_use_description": intended_use_description,
        "projected_impressions": projected_impressions,
        "scheduled_first_use_at": scheduled_first_use_at,
        "review_status": "SUBMITTED",
        "revision_round": 0,
        "review_deadline": calc.add_days(stamp, calc.REVIEW_WINDOW_DAYS),
        "reviewed_by_user_id": None,
        "rejection_reason": None,
        "review_note": None,
        "provisional_compensation_cents": 0,
        "_live_provisional_entry_id": None,
        "_seq": db.next_seq(),
    }
    db.generated_performances[row["id"]] = row
    amount = calc.per_use_compensation(grant, media_type, projected_impressions,
                                       territory_codes, floor)
    services.post_provisional(row, grant, amount,
                              "Provisional per-use royalty on submission")
    services.recompute_talent(talent)
    touch(talent)
    return respond(public(row), 201)


@bp.get("/generated-performances/<row_id>")
def read_performance(row_id):
    authorize(*ALL_ROLES)
    return respond(public(guards.need_performance(row_id)))


@bp.get("/generated-performances")
def list_performances():
    authorize(*ALL_ROLES)
    return collection(db.generated_performances.values(), {
        "digital_replica_id": "digital_replica_id",
        "licensee_user_id": "licensee_user_id",
        "review_status": "review_status",
        "media_type": "media_type",
    })


@bp.post("/generated-performances/<row_id>/review")
def review_performance(row_id):
    authorize("TalentRepresentative", "EstateRepresentative")
    body = body_json()
    decision = want_enum(body, "decision", DECISIONS)
    review_note = want_str(body, "review_note", 1, 500, required=False, default=None)
    rejection_reason = want_enum(body, "rejection_reason", REJECTION_REASONS,
                                 required=False, default=None)
    performance = guards.need_performance(row_id)
    replica = db.digital_replicas[performance["digital_replica_id"]]
    grant = db.consent_grants[replica["consent_grant_id"]]
    talent = db.talents[replica["talent_id"]]

    guards.talent_side_ownership(talent, g.role, g.user_id)
    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")
    if performance["review_status"] != "SUBMITTED":
        fail("ERR_INVALID_PERFORMANCE_STATE",
             "only a SUBMITTED performance may be reviewed")
    guards.block_frozen(talent)
    guards.need_verified_estate(talent)

    performance["review_note"] = review_note
    rejected = False
    if decision == "APPROVE":
        performance["review_status"] = "APPROVED"
        performance["reviewed_by_user_id"] = g.user_id
    elif decision == "REQUEST_REVISION":
        performance["reviewed_by_user_id"] = g.user_id
        if int(performance["revision_round"]) >= calc.MAX_REVISION_ROUNDS:
            performance["review_status"] = "REJECTED"
            performance["rejection_reason"] = "REVISION_LIMIT_REACHED"
            rejected = True
        else:
            performance["review_status"] = "REVISION_REQUESTED"
    else:
        performance["review_status"] = "REJECTED"
        performance["reviewed_by_user_id"] = g.user_id
        performance["rejection_reason"] = rejection_reason
        rejected = True

    if rejected:
        services.reverse_live_provisional(
            performance, grant, "Provisional accrual reversed: performance rejected")
        services.recompute_grant_total(grant)
        services.recompute_talent(talent)
        touch(talent)
    touch(performance)
    return respond(public(performance))


@bp.post("/generated-performances/<row_id>/resubmit")
def resubmit_performance(row_id):
    authorize("LicenseeProducer")
    body = body_json()
    intended_use_description = want_str(body, "intended_use_description", 1, 500)
    projected_impressions = want_int(body, "projected_impressions", 0)
    performance = guards.need_performance(row_id)
    replica = db.digital_replicas[performance["digital_replica_id"]]
    grant = db.consent_grants[replica["consent_grant_id"]]
    talent = db.talents[replica["talent_id"]]

    guards.licensee_ownership(performance["licensee_user_id"], g.user_id)
    if grant["status"] != "ACTIVE":
        fail("ERR_CONSENT_NOT_ACTIVE", "the governing consent grant is not ACTIVE")

    exhausted = False
    if performance["review_status"] == "REVISION_REQUESTED":
        if int(performance["revision_round"]) >= calc.MAX_REVISION_ROUNDS:
            exhausted = True
    elif performance["review_status"] == "REJECTED" \
            and performance["rejection_reason"] == "REVISION_LIMIT_REACHED":
        # The performance-state rung defers so the constraint rung can report the
        # more informative refusal.
        exhausted = True
    else:
        fail("ERR_INVALID_PERFORMANCE_STATE",
             "only a REVISION_REQUESTED performance may be resubmitted")
    if exhausted:
        fail("ERR_REVISION_LIMIT_REACHED",
             "this performance has exhausted its revision rounds")

    performance["review_status"] = "SUBMITTED"
    performance["revision_round"] = int(performance["revision_round"]) + 1
    performance["intended_use_description"] = intended_use_description
    performance["projected_impressions"] = projected_impressions
    performance["reviewed_by_user_id"] = None
    performance["review_deadline"] = calc.add_days(now(), calc.REVIEW_WINDOW_DAYS)

    services.reverse_live_provisional(
        performance, grant, "Provisional accrual reversed: performance resubmitted")
    floor = _per_use_floor_or_zero(grant, performance["media_type"])
    amount = calc.per_use_compensation(grant, performance["media_type"],
                                       projected_impressions,
                                       performance["territory_codes"], floor)
    services.post_provisional(performance, grant, amount,
                              "Provisional per-use royalty on resubmission")
    services.recompute_grant_total(grant)
    services.recompute_talent(talent)
    touch(performance)
    touch(talent)
    return respond(public(performance))
