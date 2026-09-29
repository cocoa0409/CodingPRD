"""Medical evaluations and the record-sharing ledger (PRD 3.4, 2.8, 2.10)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
import versioning
from db import db
from errors import ApiError

bp = Blueprint("medical", __name__)

EVAL_READ_ROLES = ["LeagueDraftAdmin", "ClubMedicalDirector", "CombineMedicalExaminer"]
SHARE_READ_ROLES = [
    "LeagueDraftAdmin",
    "ClubGM",
    "ClubMedicalDirector",
    "ProspectAgent",
]

SCOPE_RANK = {"SUMMARY": 1, "FULL": 2}


# --------------------------------------------------------------------------
# medical evaluations
# --------------------------------------------------------------------------
@bp.post("/medical-evaluations")
def create_evaluation():
    user_id, _role = auth.begin(["CombineMedicalExaminer"])
    data = validate.body()
    booking_id = validate.string(data, "combine_booking_id")
    prospect_id = validate.string(data, "prospect_id")
    findings_code = validate.string(data, "findings_code")
    medical_grade = validate.enum(data, "medical_grade", K.MEDICAL_GRADES)

    booking = logic.fk_lookup(db.combine_bookings, booking_id, "combine booking")
    prospect = logic.fk_lookup(db.prospects, prospect_id, "prospect")
    logic.require_unfrozen(derive.prospect_cycle(prospect))

    if (
        booking["booking_type"] != "MEDICAL_EXAM"
        or booking["status"] != "COMPLETED"
        or booking["prospect_id"] != prospect["id"]
    ):
        raise ApiError(
            "ERR_BOOKING_NOT_MEDICAL_COMPLETED",
            "The referenced booking is not a COMPLETED medical exam for this prospect.",
        )

    tier = (
        "RESTRICTED" if medical_grade in ("FAIL_RECHECK", "RED_FLAG") else "STANDARD"
    )
    rec = db.insert(
        db.medical_evaluations,
        "MedicalEvaluation",
        {
            "combine_booking_id": booking["id"],
            "prospect_id": prospect["id"],
            "filed_by_user_id": user_id,
            "findings_code": findings_code,
            "medical_grade": medical_grade,
            "confidentiality_tier": tier,
            "disclosure_state": "DISCLOSABLE",
        },
    )

    if prospect["medical_clearance_status"] == "PENDING":
        if medical_grade in ("PASS", "PASS_WITH_NOTE"):
            prospect["medical_clearance_status"] = "CLEARED"
        elif medical_grade == "RED_FLAG":
            prospect["medical_clearance_status"] = "FAILED"
    return respond.created(rec)


@bp.get("/medical-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    auth.begin(EVAL_READ_ROLES)
    return respond.one(logic.path_lookup(db.medical_evaluations, evaluation_id))


@bp.get("/medical-evaluations")
def list_evaluations():
    auth.begin(EVAL_READ_ROLES)
    limit, offset = validate.pagination()
    prospect_id = validate.query_str("prospect_id")
    booking_id = validate.query_str("combine_booking_id")
    medical_grade = validate.query_enum("medical_grade", K.MEDICAL_GRADES)
    rows = list(db.medical_evaluations.values())
    if prospect_id is not None:
        rows = [r for r in rows if r["prospect_id"] == prospect_id]
    if booking_id is not None:
        rows = [r for r in rows if r["combine_booking_id"] == booking_id]
    if medical_grade is not None:
        rows = [r for r in rows if r["medical_grade"] == medical_grade]
    return respond.listing(logic.by_created(rows), limit, offset)


# --------------------------------------------------------------------------
# medical record shares
# --------------------------------------------------------------------------
def _consent_guard(prospect, scope):
    if (
        prospect is None
        or prospect["consent_status"] != "GRANTED"
        or prospect["consent_expires_at"] is None
        or prospect["consent_expires_at"] <= db.now
        or SCOPE_RANK[scope] > SCOPE_RANK.get(prospect["consent_scope"], 0)
    ):
        raise ApiError(
            "ERR_CONSENT_NOT_GRANTED",
            "The prospect has not granted consent covering this scope.",
        )


def _tier_guard(evaluation, requested_by_role):
    if (
        evaluation["confidentiality_tier"] == "RESTRICTED"
        and requested_by_role != "ClubMedicalDirector"
    ):
        raise ApiError(
            "ERR_CONFIDENTIALITY_TIER_VIOLATION",
            "A RESTRICTED evaluation is reserved to club medical staff.",
        )


@bp.post("/medical-record-shares")
def create_share():
    user_id, role = auth.begin(["ClubGM", "ClubMedicalDirector"])
    data = validate.body()
    evaluation_id = validate.string(data, "medical_evaluation_id")
    club_id = validate.string(data, "club_id")
    scope = validate.enum(data, "scope", K.CONSENT_SCOPES)
    expected_version = validate.integer(data, "expected_medical_evaluation_version")

    evaluation = logic.fk_lookup(
        db.medical_evaluations, evaluation_id, "medical evaluation"
    )
    club = logic.fk_lookup(db.clubs, club_id, "club")
    logic.own_club(role, user_id, club["id"])
    logic.require_unfrozen(derive.club_cycle(club))

    if expected_version != evaluation["version"]:
        raise ApiError(
            "ERR_STALE_PARENT_VERSION",
            "The supplied evaluation version is not current.",
        )

    prospect = db.prospects.get(evaluation["prospect_id"])
    _consent_guard(prospect, scope)

    if evaluation["disclosure_state"] != "DISCLOSABLE":
        raise ApiError(
            "ERR_EVALUATION_SEALED", "The target evaluation has been sealed."
        )

    _tier_guard(evaluation, role)

    if prospect is not None:
        logic.require_same_cycle(club["draft_cycle_id"], prospect["draft_cycle_id"])

    for prior in derive.evaluation_shares(evaluation["id"]):
        if prior["club_id"] == club["id"] and prior["status"] == "REQUESTED":
            prior["status"] = "SUPERSEDED"

    rec = db.insert(
        db.medical_record_shares,
        "MedicalRecordShare",
        {
            "medical_evaluation_id": evaluation["id"],
            "club_id": club["id"],
            "requested_by_user_id": user_id,
            "requested_by_role": role,
            "scope": scope,
            "status": "REQUESTED",
            "granted_at": None,
            "expires_at": None,
            "denial_reason": None,
        },
    )
    versioning.force(evaluation)
    return respond.created(rec)


@bp.get("/medical-record-shares/<share_id>")
def get_share(share_id):
    auth.begin(SHARE_READ_ROLES)
    return respond.one(logic.path_lookup(db.medical_record_shares, share_id))


@bp.get("/medical-record-shares")
def list_shares():
    auth.begin(SHARE_READ_ROLES)
    limit, offset = validate.pagination()
    evaluation_id = validate.query_str("medical_evaluation_id")
    club_id = validate.query_str("club_id")
    status = validate.query_enum("status", K.SHARE_STATUSES)
    scope = validate.query_enum("scope", K.CONSENT_SCOPES)
    rows = list(db.medical_record_shares.values())
    if evaluation_id is not None:
        rows = [r for r in rows if r["medical_evaluation_id"] == evaluation_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    return respond.listing(logic.by_created(rows), limit, offset)


@bp.post("/medical-record-shares/<share_id>/decision")
def share_decision(share_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    action = validate.enum(data, "action", ("GRANT", "DENY", "REVOKE"))
    denial_reason = None
    if action in ("DENY", "REVOKE"):
        denial_reason = validate.string(data, "denial_reason")

    share = logic.path_lookup(db.medical_record_shares, share_id)
    evaluation = db.medical_evaluations.get(share["medical_evaluation_id"])
    prospect = logic.share_prospect(share) if evaluation is not None else None
    if prospect is not None:
        logic.require_unfrozen(derive.prospect_cycle(prospect))

    current = share["status"]
    if action == "GRANT":
        if current != "REQUESTED":
            raise logic.invalid_transition("Only a REQUESTED share may be granted.")
        _consent_guard(prospect, share["scope"])
        if evaluation["disclosure_state"] != "DISCLOSABLE":
            raise ApiError(
                "ERR_EVALUATION_SEALED", "The target evaluation has been sealed."
            )
        _tier_guard(evaluation, share["requested_by_role"])
        share["status"] = "GRANTED"
        share["granted_at"] = db.now
        share["expires_at"] = logic.share_expiry_instant(share)
        return respond.ok(share)

    if action == "DENY":
        if current != "REQUESTED":
            raise logic.invalid_transition("Only a REQUESTED share may be denied.")
        share["status"] = "DENIED"
        share["denial_reason"] = denial_reason
        return respond.ok(share)

    # REVOKE
    if current != "GRANTED":
        raise logic.invalid_transition("Only a GRANTED share may be revoked.")
    share["status"] = "REVOKED"
    share["denial_reason"] = denial_reason
    if evaluation is not None and derive.active_share_count(evaluation["id"]) == 0:
        evaluation["disclosure_state"] = "SEALED"
    return respond.ok(share)
