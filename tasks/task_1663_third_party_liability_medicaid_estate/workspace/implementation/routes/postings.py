"""RecoveryPosting endpoints (PRD §3.5): record, post, reverse."""

from flask import Blueprint, request

from db import CASES, LIENS, POSTINGS, SETTLEMENTS, new_entity, pub, touch
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_POSTING_EXCEEDS_RECOVERY,
    ERR_SOL_EXPIRED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import (
    active_lien_for_case,
    contractor_commission,
    create_notice,
    fire_sol_expiry,
    recompute_case_total_recovered,
    sol_expired,
)
from util import body, paginate, req_int, req_str

bp = Blueprint("postings", __name__)


@bp.post("/recovery/settlements/<string:settlementId>/postings")
@require_roles("RecoveryAccountant")
def create_posting(settlementId):
    b = body()
    gross_recovery_cents = req_int(b, "gross_recovery_cents", minimum=0, exclusive_min=True)
    contractor_code = req_str(b, "contractor_code")
    s = SETTLEMENTS.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Settlement not found", 404)
    # §3.5: recording is defined only against an ACCEPTED settlement.
    if s["status"] != "ACCEPTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Recovery postings may be recorded only against an ACCEPTED settlement",
            409,
        )
    # Priority 9 (fiscal): cumulative non-REVERSED postings must never exceed
    # the settlement's state_recovery_cents.
    cumulative = sum(
        p["gross_recovery_cents"]
        for p in POSTINGS.values()
        if p["settlement_id"] == settlementId and p["status"] != "REVERSED"
    )
    if cumulative + gross_recovery_cents > s["state_recovery_cents"]:
        raise ApiError(
            ERR_POSTING_EXCEEDS_RECOVERY,
            "Cumulative recovery postings would exceed the settlement's recovery amount",
            409,
        )
    lien = active_lien_for_case(s["case_id"])
    p = new_entity()
    p.update(
        {
            "settlement_id": settlementId,
            # Snapshot of the case's active lien at creation.
            "lien_id": lien["id"] if lien is not None else None,
            "contractor_code": contractor_code,
            "gross_recovery_cents": gross_recovery_cents,
            "commission_cents": None,
            "net_to_state_cents": None,
            "status": "PENDING",
        }
    )
    POSTINGS[p["id"]] = p
    return success_object(pub(p), 201)


@bp.get("/recovery/postings/<string:postingId>")
@require_roles(*ALL_ROLES)
def get_posting(postingId):
    p = POSTINGS.get(postingId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Recovery posting not found", 404)
    return success_object(pub(p))


@bp.get("/recovery/postings")
@require_roles(*ALL_ROLES)
def list_postings():
    settlement_id = request.args.get("settlement_id")
    lien_id = request.args.get("lien_id")
    status = request.args.get("status")
    items = []
    for p in POSTINGS.values():
        if settlement_id is not None and p["settlement_id"] != settlement_id:
            continue
        if lien_id is not None and p["lien_id"] != lien_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    ordered, limit, offset = paginate(items)
    page = [pub(p) for p in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/postings/<string:postingId>/post")
@require_roles("RecoveryAccountant")
def post_posting(postingId):
    p = POSTINGS.get(postingId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Recovery posting not found", 404)
    if p["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Only a PENDING posting may be posted",
            409,
        )
    s = SETTLEMENTS[p["settlement_id"]]
    case = CASES[s["case_id"]]
    # Priority 7 (temporal): the §2.5 SOL gate on the settlement's case.
    if sol_expired(case):
        fire_sol_expiry(case)
        raise ApiError(ERR_SOL_EXPIRED, "The statute of limitations has expired", 409)
    # §3.5: commission computed in tiers, rounded half-up once, at post time.
    p["commission_cents"] = contractor_commission(p["gross_recovery_cents"])
    p["net_to_state_cents"] = p["gross_recovery_cents"] - p["commission_cents"]
    p["status"] = "POSTED"
    touch(p)
    # Lien mutation: outstanding reduced by the gross recovery.
    lien = LIENS.get(p["lien_id"])
    satisfied = False
    if lien is not None:
        lien["outstanding_cents"] -= p["gross_recovery_cents"]
        if lien["outstanding_cents"] == 0 and lien["status"] in ("FILED", "AMENDED"):
            lien["status"] = "SATISFIED"
            satisfied = True
        touch(lien)
    # The first posting to reach POSTED disburses the settlement.
    if s["status"] == "ACCEPTED":
        s["status"] = "DISBURSED"
        touch(s)
    # Lien satisfaction resolves a SETTLEMENT_PENDING case (§3.5).
    recompute_case_total_recovered(case)
    if satisfied and case["status"] == "SETTLEMENT_PENDING":
        case["status"] = "RESOLVED"
        create_notice(case["member_id"], case["id"], None, "CASE_RESOLUTION_NOTICE")
    touch(case)
    return success_object(pub(p))


@bp.post("/recovery/postings/<string:postingId>/reverse")
@require_roles("RecoveryAccountant")
def reverse_posting(postingId):
    p = POSTINGS.get(postingId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Recovery posting not found", 404)
    if p["status"] != "POSTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Only a POSTED posting may be reversed",
            409,
        )
    p["status"] = "REVERSED"
    touch(p)
    s = SETTLEMENTS[p["settlement_id"]]
    case = CASES[s["case_id"]]
    # §3.5 compensating action: outstanding restored; a SATISFIED lien reverts
    # to FILED and a RESOLVED case reverts to SETTLEMENT_PENDING.
    lien = LIENS.get(p["lien_id"])
    if lien is not None:
        lien["outstanding_cents"] += p["gross_recovery_cents"]
        if lien["status"] == "SATISFIED":
            lien["status"] = "FILED"
        touch(lien)
    recompute_case_total_recovered(case)
    if case["status"] == "RESOLVED":
        case["status"] = "SETTLEMENT_PENDING"
    touch(case)
    # If no POSTED postings remain, the settlement falls back to ACCEPTED.
    remaining = any(
        other["settlement_id"] == s["id"] and other["status"] == "POSTED"
        for other in POSTINGS.values()
    )
    if not remaining and s["status"] == "DISBURSED":
        s["status"] = "ACCEPTED"
        touch(s)
    return success_object(pub(p))
