"""Lien endpoints (PRD §3.3): filing, retrieval, OCC-guarded amend, release."""

from flask import Blueprint, request

from db import CASES, LIENS, POSTINGS, new_entity, now_iso, pub, touch
from errors import (
    ApiError,
    ERR_ATTORNEY_NOT_NOTIFIED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LIEN_ALREADY_EXISTS,
    ERR_LIEN_EXCEEDS_CAP,
    ERR_LIEN_NOT_AMENDABLE,
    ERR_NOT_FOUND,
    ERR_SOL_EXPIRED,
    ERR_NEGOTIATION_FREEZE,
    ERR_STALE_VERSION,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import (
    ACTIVE_LIEN_STATUSES,
    STATUTORY_LIEN_CAP_CENTS,
    active_lien_for_case,
    create_notice,
    fire_sol_expiry,
    lien_perfected_amount,
    negotiation_frozen,
    recompute_lien_outstanding,
    sol_expired,
)
from util import body, paginate, req_int

bp = Blueprint("liens", __name__)


@bp.post("/recovery/cases/<string:caseId>/liens")
@require_roles("RecoverySpecialist")
def file_lien(caseId):
    c = CASES.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    # §3.3: filing while still IDENTIFIED is the specialized state error.
    if c["status"] == "IDENTIFIED":
        raise ApiError(
            ERR_ATTORNEY_NOT_NOTIFIED,
            "Attorney notification has not been recorded for this case",
            409,
        )
    # §3.3: only one active lien per case.
    if active_lien_for_case(caseId) is not None:
        raise ApiError(
            ERR_LIEN_ALREADY_EXISTS,
            "A lien with status FILED or AMENDED already exists for this case",
            409,
        )
    # Filing from any later or terminal status is a generic state error.
    if c["status"] != "ATTORNEY_NOTIFIED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Lien filing requires the case to be ATTORNEY_NOTIFIED",
            409,
        )
    amount = lien_perfected_amount(c)
    lien = new_entity()
    lien.update(
        {
            "case_id": caseId,
            "lien_amount_cents": amount,
            # Cap snapshot at filing time (audit immutability).
            "statutory_cap_cents": STATUTORY_LIEN_CAP_CENTS,
            "outstanding_cents": amount,
            "status": "FILED",
            "filed_at": now_iso(),
            "amended_count": 0,
        }
    )
    LIENS[lien["id"]] = lien
    c["status"] = "LIEN_FILED"
    touch(c)
    # §2.11: lien filing queues a LIEN_FILED_NOTICE to the member.
    create_notice(c["member_id"], caseId, None, "LIEN_FILED_NOTICE")
    return success_object(pub(lien), 201)


@bp.get("/recovery/liens/<string:lienId>")
@require_roles(*ALL_ROLES)
def get_lien(lienId):
    lien = LIENS.get(lienId)
    if lien is None:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    return success_object(pub(lien))


@bp.get("/recovery/liens")
@require_roles(*ALL_ROLES)
def list_liens():
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = []
    for lien in LIENS.values():
        if case_id is not None and lien["case_id"] != case_id:
            continue
        if status is not None and lien["status"] != status:
            continue
        items.append(lien)
    ordered, limit, offset = paginate(items)
    page = [pub(l) for l in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/liens/<string:lienId>/amend")
@require_roles("RecoverySpecialist")
def amend_lien(lienId):
    b = body()
    new_amount_cents = req_int(b, "new_amount_cents", minimum=0)
    expected_lien_version = req_int(b, "expected_lien_version")
    lien = LIENS.get(lienId)
    if lien is None:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    # Priority 6 (state) — on a terminal lien this is ERR_LIEN_NOT_AMENDABLE
    # and no lazy-expiry side effect fires.
    if lien["status"] not in ACTIVE_LIEN_STATUSES:
        raise ApiError(
            ERR_LIEN_NOT_AMENDABLE,
            "Only a FILED or AMENDED lien may be amended",
            409,
        )
    case = CASES[lien["case_id"]]
    # Priority 7 (temporal), PRD §3.3 pinned order: freeze first, then SOL.
    if negotiation_frozen(lien["case_id"]):
        raise ApiError(
            ERR_NEGOTIATION_FREEZE,
            "Lien amendment is blocked during the 14-day negotiation freeze",
            409,
        )
    if sol_expired(case):
        fire_sol_expiry(case)
        raise ApiError(ERR_SOL_EXPIRED, "The statute of limitations has expired", 409)
    # Priority 9 (fiscal): the cap snapshot at filing governs amendments.
    if new_amount_cents > lien["statutory_cap_cents"]:
        raise ApiError(
            ERR_LIEN_EXCEEDS_CAP,
            "Amended lien amount exceeds the statutory cap",
            409,
        )
    # OCC guard runs last (§2.8).
    if expected_lien_version != lien["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_lien_version does not match the lien's current version",
            412,
        )
    lien["lien_amount_cents"] = new_amount_cents
    recompute_lien_outstanding(lien)
    lien["amended_count"] += 1
    if lien["status"] == "FILED":
        lien["status"] = "AMENDED"
    touch(lien)
    return success_object(pub(lien))


@bp.post("/recovery/liens/<string:lienId>/release")
@require_roles("RecoverySupervisor")
def release_lien(lienId):
    lien = LIENS.get(lienId)
    if lien is None:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    if lien["status"] not in ACTIVE_LIEN_STATUSES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Only a FILED or AMENDED lien may be released",
            409,
        )
    # §3.3: release is barred while posted money stands against the lien.
    for p in POSTINGS.values():
        if p["lien_id"] == lienId and p["status"] == "POSTED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "A lien with POSTED recovery postings cannot be released",
                409,
            )
    lien["status"] = "RELEASED"
    touch(lien)
    # §3.3: feedback into the case — LIEN_FILED reverts to ATTORNEY_NOTIFIED;
    # SETTLEMENT_PENDING is left unchanged.
    case = CASES[lien["case_id"]]
    if case["status"] == "LIEN_FILED":
        case["status"] = "ATTORNEY_NOTIFIED"
        touch(case)
    return success_object(pub(lien))
