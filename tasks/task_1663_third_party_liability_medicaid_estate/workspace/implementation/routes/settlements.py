"""Settlement endpoints (PRD §3.4): negotiation, acceptance, rejection."""

from flask import Blueprint, g, request

from db import CASES, SETTLEMENTS, new_entity, now_iso, pub, touch
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LIEN_NOT_ACTIVE,
    ERR_NEGOTIATION_IN_PROGRESS,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SOL_EXPIRED,
    ERR_STALE_VERSION,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import (
    OPEN_SETTLEMENT_STATUSES,
    active_lien_for_case,
    create_notice,
    fire_sol_expiry,
    member_of_case,
    settlement_recovery_amount,
    sol_expired,
)
from util import body, paginate, req_enum, req_int, req_pct

bp = Blueprint("settlements", __name__)

OFFERED_BY = ("INSURER", "STATE")


def _offer_fields(b, require_version):
    gross = req_int(b, "gross_amount_cents", minimum=0, exclusive_min=True)
    fee_pct = req_pct(b, "attorney_fee_pct")
    costs = req_int(b, "litigation_costs_cents", minimum=0)
    offered_by = req_enum(b, "offered_by", OFFERED_BY)
    version = req_int(b, "expected_case_version") if require_version else None
    return gross, fee_pct, costs, offered_by, version


def _recompute(settlement, case, lien_outstanding):
    member = member_of_case(case)
    fee, cost_share, recovery, member_net = settlement_recovery_amount(
        settlement["gross_amount_cents"],
        settlement["attorney_fee_pct"],
        settlement["litigation_costs_cents"],
        member["recovery_approach"],
        lien_outstanding,
    )
    settlement["fee_amount_cents"] = fee
    settlement["cost_share_cents"] = cost_share
    settlement["state_recovery_cents"] = recovery
    settlement["member_net_cents"] = member_net


@bp.post("/recovery/cases/<string:caseId>/settlements")
@require_roles("RecoverySpecialist", "RecoverySupervisor")
def create_settlement(caseId):
    b = body()
    gross, fee_pct, costs, offered_by, expected_case_version = _offer_fields(b, True)
    case = CASES.get(caseId)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, "Case not found", 404)
    # Priority 6 (state): a lien in FILED or AMENDED status must stand behind
    # the case; a case that has left LIEN_FILED is a generic state error.
    lien = active_lien_for_case(caseId)
    if lien is None:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Settlement negotiation requires an active lien on the case",
            409,
        )
    # Priority 7 (temporal): the §2.5 statute-of-limitations gate.
    if sol_expired(case):
        fire_sol_expiry(case)
        raise ApiError(ERR_SOL_EXPIRED, "The statute of limitations has expired", 409)
    # Priority 8 (aggregate): only one live negotiation per case.
    for s in SETTLEMENTS.values():
        if s["case_id"] == caseId and s["status"] in OPEN_SETTLEMENT_STATUSES:
            raise ApiError(
                ERR_NEGOTIATION_IN_PROGRESS,
                "A settlement with status OFFERED or COUNTERED already exists",
                409,
            )
    # OCC guard runs last (§2.8).
    if expected_case_version != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_case_version does not match the case's current version",
            412,
        )
    s = new_entity()
    s.update(
        {
            "case_id": caseId,
            "round_number": 1,
            "status": "OFFERED",
            "gross_amount_cents": gross,
            "attorney_fee_pct": fee_pct,
            "litigation_costs_cents": costs,
            "offered_by": offered_by,
            "created_by_user_id": g.user_id,
            "fee_amount_cents": None,
            "cost_share_cents": None,
            "state_recovery_cents": None,
            "member_net_cents": None,
            "accepted_at": None,
        }
    )
    _recompute(s, case, lien["outstanding_cents"])
    SETTLEMENTS[s["id"]] = s
    case["status"] = "SETTLEMENT_PENDING"
    touch(case)
    return success_object(pub(s), 201)


@bp.get("/recovery/settlements/<string:settlementId>")
@require_roles(*ALL_ROLES)
def get_settlement(settlementId):
    s = SETTLEMENTS.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Settlement not found", 404)
    return success_object(pub(s))


@bp.get("/recovery/settlements")
@require_roles(*ALL_ROLES)
def list_settlements():
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = []
    for s in SETTLEMENTS.values():
        if case_id is not None and s["case_id"] != case_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    ordered, limit, offset = paginate(items)
    page = [pub(s) for s in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/settlements/<string:settlementId>/counter")
@require_roles("RecoverySpecialist", "RecoverySupervisor")
def counter_settlement(settlementId):
    b = body()
    gross, fee_pct, costs, offered_by, _ = _offer_fields(b, False)
    s = SETTLEMENTS.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Settlement not found", 404)
    # §3.4: countering alternates OFFERED <-> COUNTERED; any other status is a
    # generic state error.
    if s["status"] not in OPEN_SETTLEMENT_STATUSES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Counter requires the settlement to be OFFERED or COUNTERED",
            409,
        )
    s["round_number"] += 1
    s["gross_amount_cents"] = gross
    s["attorney_fee_pct"] = fee_pct
    s["litigation_costs_cents"] = costs
    s["offered_by"] = offered_by
    s["status"] = "COUNTERED" if s["status"] == "OFFERED" else "OFFERED"
    case = CASES[s["case_id"]]
    lien = active_lien_for_case(s["case_id"])
    _recompute(s, case, lien["outstanding_cents"] if lien is not None else 0)
    touch(s)
    return success_object(pub(s))


@bp.post("/recovery/settlements/<string:settlementId>/accept")
@require_roles("RecoverySupervisor")
def accept_settlement(settlementId):
    s = SETTLEMENTS.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Settlement not found", 404)
    # Priority 5: segregation of duties vs the settlement's creator.
    if g.user_id == s["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "A supervisor cannot accept a settlement they created",
            403,
        )
    # Priority 6 (state).
    if s["status"] not in OPEN_SETTLEMENT_STATUSES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Accept requires the settlement to be OFFERED or COUNTERED",
            409,
        )
    case = CASES[s["case_id"]]
    lien = active_lien_for_case(s["case_id"])
    if lien is None:
        raise ApiError(
            ERR_LIEN_NOT_ACTIVE,
            "No lien on the case is in FILED or AMENDED status",
            409,
        )
    # Priority 7 (temporal): §2.5 SOL gate with lazy expiry.
    if sol_expired(case):
        fire_sol_expiry(case)
        raise ApiError(ERR_SOL_EXPIRED, "The statute of limitations has expired", 409)
    # §3.4: on acceptance the recovery is recomputed against the lien's CURRENT
    # outstanding (derived-field reconciliation), and the other derived
    # amounts are recomputed with it.
    _recompute(s, case, lien["outstanding_cents"])
    s["status"] = "ACCEPTED"
    s["accepted_at"] = now_iso()
    touch(s)
    # §2.11: settlement acceptance queues a SETTLEMENT_NOTICE to the member.
    create_notice(case["member_id"], case["id"], None, "SETTLEMENT_NOTICE")
    return success_object(pub(s))


@bp.post("/recovery/settlements/<string:settlementId>/reject")
@require_roles("RecoverySupervisor")
def reject_settlement(settlementId):
    s = SETTLEMENTS.get(settlementId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Settlement not found", 404)
    if s["status"] not in OPEN_SETTLEMENT_STATUSES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Reject requires the settlement to be OFFERED or COUNTERED",
            409,
        )
    s["status"] = "REJECTED"
    touch(s)
    # §3.4: the case falls back from SETTLEMENT_PENDING to LIEN_FILED.
    case = CASES[s["case_id"]]
    if case["status"] == "SETTLEMENT_PENDING":
        case["status"] = "LIEN_FILED"
        touch(case)
    return success_object(pub(s))
