"""Temporary practice permits (PRD §3.8)."""
from flask import Blueprint

import clock
import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, PATHWAY_BAR_INDEX, PERMIT_STATUSES, REVIEWABLE_STATUSES,
    ROLE_ADMIN, ROLE_ANALYST, ROLE_DEPUTY,
)
from errors import (
    ERR_APPLICATION_NOT_REVIEWABLE, ERR_DISCIPLINARY_BAR,
    ERR_EVALUATION_REQUIRED_FOR_PERMIT, ERR_FEE_BALANCE_OUTSTANDING,
    ERR_PERMIT_EFFECTIVE_IN_PAST, ERR_PERMIT_NOT_ACTIVE,
    ERR_PERMIT_WINDOW_OVERLAP, ERR_STALE_VERSION, fail,
)
from middleware import authenticate
from services import calculations, lookups, workflow

bp = Blueprint("permits", __name__)

OCCUPYING_STATUSES = ("ACTIVE", "CONVERTED")


@bp.post("/licensure/temporary-permits")
def issue_permit():
    authenticate([ROLE_ANALYST])
    body = v.body()
    application_id = v.f_string(body, "application_id")
    effective_at = v.f_datetime(body, "effective_at")
    expected_application_version = v.f_int(body, "expected_application_version")

    application = lookups.application(application_id)

    # Check 7 — stale-view rejection (PRD §2.6).
    if expected_application_version != application["version"]:
        fail(ERR_STALE_VERSION,
             "The application has moved on; expected version %s but found %s."
             % (expected_application_version, application["version"]))

    if application["status"] not in REVIEWABLE_STATUSES:
        fail(ERR_APPLICATION_NOT_REVIEWABLE,
             "The application is in status %s, which this operation does not "
             "permit." % application["status"])

    applicant = db.applicants[application["applicant_id"]]
    profession = db.professions[application["profession_id"]]

    if not applicant["good_standing_flag"]:
        fail(ERR_DISCIPLINARY_BAR, "The applicant is not in good standing.")
    if calculations.pathway_risk_index(application) >= PATHWAY_BAR_INDEX:
        fail(ERR_DISCIPLINARY_BAR,
             "The application's pathway risk index is at or above the bar.")

    if application["pathway"] != "MILITARY_SPOUSE_EXPEDITED":
        has_evaluation = any(e["application_id"] == application["id"]
                             for e in db.evaluations.values())
        if not has_evaluation:
            fail(ERR_EVALUATION_REQUIRED_FOR_PERMIT,
                 "A credential evaluation must exist before a permit may issue "
                 "on this pathway.")

    now = clock.now()
    if effective_at < now:
        fail(ERR_PERMIT_EFFECTIVE_IN_PAST,
             "A permit may start now or in the future but never in the past.")

    permit_max_days, expires_at, permit_fee_cents = calculations.permit_window(
        application, profession, effective_at)

    # Check 30 — half-open interval collision; touching windows do not collide.
    for other in db.permits.values():
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        other_application = db.applications.get(other["application_id"])
        if other_application is None:
            continue
        if (other_application["applicant_id"] != application["applicant_id"]
                or other_application["profession_id"] != application["profession_id"]):
            continue
        if (effective_at < other["expires_at"]
                and other["effective_at"] < expires_at):
            fail(ERR_PERMIT_WINDOW_OVERLAP,
                 "The requested practice window overlaps an existing permit.")

    if application["fee_balance_cents"] > 0:
        fail(ERR_FEE_BALANCE_OUTSTANDING,
             "The application still owes fees.")

    row = db.make_row({
        "application_id": application["id"],
        "effective_at": effective_at,
        "expires_at": expires_at,
        "permit_max_days": permit_max_days,
        "permit_fee_cents": permit_fee_cents,
        "status": "ACTIVE",
        "converted_at": None,
        "revoked_at": None,
        "revocation_reason_code": None,
    })
    db.permits[row["id"]] = row

    workflow.append_ledger(application, "PERMIT_FEE", permit_fee_cents)
    workflow.recompute_balance(application)
    db.touch(application)
    return response.object_response(serializers.temporary_permit(row), 201)


@bp.get("/licensure/applications/<application_id>/temporary-permits")
def list_application_permits(application_id):
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    status = response.query_enum("status", PERMIT_STATUSES)
    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id,
                                        application["applicant_id"])
    rows = [p for p in db.permits.values()
            if p["application_id"] == application["id"]
            and (status is None or p["status"] == status)]
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.temporary_permit)


@bp.post("/licensure/temporary-permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    authenticate([ROLE_DEPUTY])
    body = v.body()
    reason_code = v.f_string(body, "reason_code")

    permit = lookups.permit(permit_id)
    if permit["status"] != "ACTIVE":
        fail(ERR_PERMIT_NOT_ACTIVE, "Only an ACTIVE permit may be revoked.")

    workflow.revoke_permit(permit, reason_code)
    return response.object_response(serializers.temporary_permit(permit))


@bp.post("/licensure/permit-expiry-runs")
def run_permit_expiry():
    authenticate([ROLE_ADMIN])
    now = clock.now()
    expired_ids = []
    for permit in db.ordered(db.permits.values()):
        if permit["status"] == "ACTIVE" and permit["expires_at"] <= now:
            permit["status"] = "EXPIRED"
            db.touch(permit)
            expired_ids.append(permit["id"])
    return response.object_response({
        "expired_count": len(expired_ids),
        "expired_permit_ids": expired_ids,
    })
