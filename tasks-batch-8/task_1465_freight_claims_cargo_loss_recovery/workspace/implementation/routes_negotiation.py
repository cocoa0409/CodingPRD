"""Routes: appeals, settlements, subrogation cases, reserves, claim events."""

from flask import Blueprint, g, request

from db import STORE, iso, new_id, next_seq, now
from errors import (
    ApiError,
    ERR_APPEAL_INVALID_STATE,
    ERR_APPEAL_NOT_FOUND,
    ERR_APPEAL_ROUND_EXHAUSTED,
    ERR_ASSESSMENT_REQUIRED,
    ERR_AUTHORITY_TIER_INSUFFICIENT,
    ERR_CLAIM_ALREADY_TERMINAL,
    ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
    ERR_CLAIM_INVALID_STATE,
    ERR_CLAIM_NOT_PAID,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_RESERVE_ALREADY_OPEN,
    ERR_RESERVE_INSUFFICIENT,
    ERR_RESERVE_INVALID_STATE,
    ERR_RESERVE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE,
    ERR_SETTLEMENT_INVALID_STATE,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_SUBROGATION_INVALID_STATE,
    ERR_SUBROGATION_NOT_FOUND,
)
from middleware import as_enum, as_int, as_str, req_field, request_body, require_roles
from response import paginate, success_object
from routes_claims import get_claim_or_404
from serializers import ser_appeal, ser_event, ser_reserve, ser_settlement, ser_subrogation
from services import (
    TERMINAL_CLAIM_STATES,
    WORKING_CLAIM_STATES,
    active_open_reserve,
    add_event,
    bump_carrier_counters,
    close_shipment_if_all_terminal,
    role_authority_tier,
    round_half_up_int,
    settlement_authority_tier,
    suggested_reserve_cents,
    touch,
    touch_claim,
    SUBROGATION_RATIO_CAP_BP,
    BASIS_POINT_DENOMINATOR,
)

bp = Blueprint("negotiation", __name__)

APPEAL_DECISIONS = {"PENDING", "UPHOLD_DECLINE", "OVERTURN", "PARTIAL"}
PARTY_KINDS = {"THIRD_PARTY_CARRIER", "WAREHOUSE", "BROKER", "SHIPPER_VENDOR", "OTHER"}
OFFERED_BY_ROLES = {"ClaimsAdjuster": "ADJUSTER", "ClaimsManager": "MANAGER",
                    "FinanceController": "MANAGER"}


def get_appeal_or_404(claim, appeal_id):
    appeal = STORE["appeals"].get(appeal_id)
    if appeal is None or appeal["claim_id"] != claim["id"]:
        raise ApiError(ERR_APPEAL_NOT_FOUND, f"Appeal '{appeal_id}' not found", 404)
    return appeal


def get_settlement_or_404(claim, settlement_id):
    settlement = STORE["settlements"].get(settlement_id)
    if settlement is None or settlement["claim_id"] != claim["id"]:
        raise ApiError(ERR_SETTLEMENT_NOT_FOUND, f"Settlement '{settlement_id}' not found", 404)
    return settlement


def get_case_or_404(claim, case_id):
    case = STORE["subrogation"].get(case_id)
    if case is None or case["claim_id"] != claim["id"]:
        raise ApiError(ERR_SUBROGATION_NOT_FOUND, f"Subrogation case '{case_id}' not found", 404)
    return case


def get_reserve_or_404(claim, reserve_id):
    reserve = STORE["reserves"].get(reserve_id)
    if reserve is None or reserve["claim_id"] != claim["id"]:
        raise ApiError(ERR_RESERVE_NOT_FOUND, f"Reserve '{reserve_id}' not found", 404)
    return reserve


def check_expected_version(claim):
    body = request_body()
    expected = as_int(req_field(body, "expected_claim_version"), "expected_claim_version")
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_claim_version does not match the claim's current version", 412)
    return body


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/appeals")
@require_roles("ClaimsAdjuster")
def create_appeal(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "DECLINED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "An appeal may be opened only on a DECLINED claim", 409)
    body = request_body()
    justification = as_str(req_field(body, "justification"), "justification")
    requested = as_int(req_field(body, "requested_amount_cents"), "requested_amount_cents")
    if requested <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "requested_amount_cents must be > 0", 400)
    expected = as_int(req_field(body, "expected_claim_version"), "expected_claim_version")
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_claim_version does not match the claim's current version", 412)
    if claim["appeal_round"] >= 2:
        raise ApiError(ERR_APPEAL_ROUND_EXHAUSTED,
                       "This claim has exhausted its two appeal rounds", 409)
    claim["appeal_round"] += 1
    stamp = iso(now())
    appeal = {
        "id": new_id(),
        "claim_id": claim["id"],
        "round_number": claim["appeal_round"],
        "opened_by_user_id": g.user_id,
        "justification": justification,
        "requested_amount_cents": requested,
        "decision": "PENDING",
        "decided_amount_cents": None,
        "escalated_to_user_id": None,
        "state": "OPEN",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["appeals"][appeal["id"]] = appeal
    claim["filing_status"] = "APPEALED"
    add_event(claim["id"], "APPEAL_OPENED", g.user_id, {
        "appeal_id": appeal["id"], "round_number": appeal["round_number"],
    })
    touch_claim(claim)
    return success_object(ser_appeal(appeal), status=201)


@bp.get("/freight-claims/claims/<claim_id>/appeals")
@require_roles("Any")
def list_appeals(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [a for a in STORE["appeals"].values() if a["claim_id"] == claim["id"]]
    state = request.args.get("state")
    if state is not None:
        records = [a for a in records if a["state"] == state]
    return paginate(records, ser_appeal)


@bp.get("/freight-claims/claims/<claim_id>/appeals/<appeal_id>")
@require_roles("Any")
def get_appeal(claim_id, appeal_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_appeal(get_appeal_or_404(claim, appeal_id)))


@bp.post("/freight-claims/claims/<claim_id>/appeals/<appeal_id>/escalate")
@require_roles("ClaimsManager")
def escalate_appeal(claim_id, appeal_id):
    claim = get_claim_or_404(claim_id)
    appeal = get_appeal_or_404(claim, appeal_id)
    if claim["filing_status"] != "APPEALED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Appeals may be escalated only while the claim is APPEALED", 409)
    if appeal["state"] != "OPEN":
        raise ApiError(ERR_APPEAL_INVALID_STATE,
                       "Only an OPEN appeal may be escalated", 409)
    body = request_body()
    appeal["escalated_to_user_id"] = as_str(
        req_field(body, "escalated_to_user_id"), "escalated_to_user_id")
    appeal["state"] = "UNDER_ESCALATION"
    touch(appeal)
    return success_object(ser_appeal(appeal))


@bp.post("/freight-claims/claims/<claim_id>/appeals/<appeal_id>/decide")
@require_roles("ClaimsManager")
def decide_appeal(claim_id, appeal_id):
    claim = get_claim_or_404(claim_id)
    appeal = get_appeal_or_404(claim, appeal_id)
    if claim["filing_status"] != "APPEALED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Appeals may be decided only while the claim is APPEALED", 409)
    if appeal["state"] not in ("OPEN", "UNDER_ESCALATION"):
        raise ApiError(ERR_APPEAL_INVALID_STATE,
                       "Appeal must be OPEN or UNDER_ESCALATION to be decided", 409)
    body = request_body()
    decision = as_enum(req_field(body, "decision"), "decision", APPEAL_DECISIONS)
    if decision == "PENDING":
        raise ApiError(ERR_INVALID_REQUEST, "decision must resolve the appeal", 400)
    decided_amount = None
    if decision in ("OVERTURN", "PARTIAL"):
        decided_amount = as_int(req_field(body, "decided_amount_cents"), "decided_amount_cents")
        if decided_amount <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "decided_amount_cents must be > 0", 400)
    if decision == "OVERTURN" and g.user_id == appeal["opened_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                       "The appeal opener may not decide an OVERTURN on their own appeal", 403)
    appeal["decision"] = decision
    appeal["decided_amount_cents"] = decided_amount
    appeal["state"] = "DECIDED"
    touch(appeal)
    if decision in ("OVERTURN", "PARTIAL"):
        claim["computed_liability_cents"] = decided_amount
        claim["net_exposure_cents"] = max(
            claim["computed_liability_cents"] - claim["salvage_credit_cents"], 0)
        claim["filing_status"] = "UNDER_REVIEW"
    else:  # UPHOLD_DECLINE
        claim["filing_status"] = "DECLINED"
    add_event(claim["id"], "APPEAL_DECIDED", g.user_id, {
        "appeal_id": appeal["id"], "decision": decision,
        "decided_amount_cents": decided_amount,
    })
    touch_claim(claim)
    return success_object(ser_appeal(appeal))


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/settlements")
@require_roles("ClaimsAdjuster")
def create_settlement(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "A settlement offer requires the claim to be UNDER_REVIEW", 409)
    if claim["liability_assessment_id"] is None:
        raise ApiError(ERR_ASSESSMENT_REQUIRED,
                       "A liability assessment is required before offering a settlement", 409)
    body = request_body()
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    expected = as_int(req_field(body, "expected_claim_version"), "expected_claim_version")
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_claim_version does not match the claim's current version", 412)
    if amount <= 0 or amount > claim["net_exposure_cents"]:
        raise ApiError(ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
                       "amount_cents must be > 0 and <= claim.net_exposure_cents", 422)
    carrier = STORE["carriers"][claim["carrier_id"]]
    tier = settlement_authority_tier(amount, carrier)
    existing = [s for s in STORE["settlements"].values() if s["claim_id"] == claim["id"]]
    round_number = max((s["round_number"] for s in existing), default=0) + 1
    stamp = iso(now())
    settlement = {
        "id": new_id(),
        "claim_id": claim["id"],
        "round_number": round_number,
        "offered_by_role": OFFERED_BY_ROLES.get(g.role, "CARRIER"),
        "amount_cents": amount,
        "authority_tier_required": tier,
        "approved_by_user_id": None,
        "state": "OFFERED",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_created_by_user_id": g.user_id,
        "_created_dt": now(),
        "_seq": next_seq(),
    }
    STORE["settlements"][settlement["id"]] = settlement
    claim["filing_status"] = "OFFERED"
    add_event(claim["id"], "OFFER_EXTENDED", g.user_id, {
        "settlement_id": settlement["id"], "amount_cents": amount,
        "authority_tier_required": tier,
    })
    touch_claim(claim)
    return success_object(ser_settlement(settlement), status=201)


@bp.get("/freight-claims/claims/<claim_id>/settlements")
@require_roles("Any")
def list_settlements(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [s for s in STORE["settlements"].values() if s["claim_id"] == claim["id"]]
    state = request.args.get("state")
    if state is not None:
        records = [s for s in records if s["state"] == state]
    return paginate(records, ser_settlement)


@bp.get("/freight-claims/claims/<claim_id>/settlements/<settlement_id>")
@require_roles("Any")
def get_settlement(claim_id, settlement_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_settlement(get_settlement_or_404(claim, settlement_id)))


@bp.post("/freight-claims/claims/<claim_id>/settlements/<settlement_id>/accept")
@require_roles("ClaimsManager", "FinanceController")
def accept_settlement(claim_id, settlement_id):
    claim = get_claim_or_404(claim_id)
    settlement = get_settlement_or_404(claim, settlement_id)
    if claim["filing_status"] != "OFFERED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Settlement acceptance requires the claim to be OFFERED", 409)
    if settlement["state"] != "OFFERED":
        raise ApiError(ERR_SETTLEMENT_INVALID_STATE,
                       "Only an OFFERED settlement may be accepted", 409)
    assessment = STORE["assessments"].get(claim["liability_assessment_id"])
    if (g.user_id == settlement["_created_by_user_id"]
            or (assessment is not None and g.user_id == assessment["assessed_by_user_id"])):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                       "The offer creator or assessing adjuster may not accept the offer", 403)
    if settlement["amount_cents"] > claim["net_exposure_cents"]:
        raise ApiError(ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE,
                       "Settlement amount exceeds the claim's net exposure", 422)
    if claim["reserve_amount_cents"] < settlement["amount_cents"]:
        raise ApiError(ERR_RESERVE_INSUFFICIENT,
                       "The claim's reserve does not cover the settlement amount", 402)
    required_tier = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}[settlement["authority_tier_required"]]
    if role_authority_tier(g.role) < required_tier:
        raise ApiError(ERR_AUTHORITY_TIER_INSUFFICIENT,
                       "Actor authority tier is below the required tier", 403)

    amount = settlement["amount_cents"]
    settlement["state"] = "ACCEPTED"
    settlement["approved_by_user_id"] = g.user_id
    touch(settlement)
    claim["settlement_amount_cents"] = amount
    if amount == claim["net_exposure_cents"]:
        claim["filing_status"] = "PAID"
        claim["payment_status"] = "PAID_IN_FULL"
    else:
        claim["filing_status"] = "CLOSED_WITH_PAYMENT"
        claim["payment_status"] = "PARTIAL"
    reserve = active_open_reserve(claim["id"])
    if reserve is not None:
        reserve["state"] = "EXHAUSTED"
        reserve["released_at"] = iso(now())
        touch(reserve)
    claim["reserve_amount_cents"] = 0
    carrier = STORE["carriers"].get(claim["carrier_id"])
    if carrier is not None:
        bump_carrier_counters(carrier, paid_delta=1)
    add_event(claim["id"], "OFFER_ACCEPTED", g.user_id, {
        "settlement_id": settlement["id"], "amount_cents": amount,
    })
    add_event(claim["id"], "PAID_OUT", g.user_id, {"amount_cents": amount})
    touch_claim(claim)
    shipment = STORE["shipments"].get(claim["shipment_id"])
    if shipment is not None:
        close_shipment_if_all_terminal(shipment)
    return success_object(ser_settlement(settlement))


@bp.post("/freight-claims/claims/<claim_id>/settlements/<settlement_id>/counter")
@require_roles("ClaimsAdjuster")
def counter_settlement(claim_id, settlement_id):
    claim = get_claim_or_404(claim_id)
    settlement = get_settlement_or_404(claim, settlement_id)
    if claim["filing_status"] != "OFFERED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Countering requires the claim to be OFFERED", 409)
    if settlement["state"] != "OFFERED":
        raise ApiError(ERR_SETTLEMENT_INVALID_STATE,
                       "Only an OFFERED settlement may be countered", 409)
    settlement["state"] = "COUNTERED"
    touch(settlement)
    claim["filing_status"] = "UNDER_REVIEW"
    touch_claim(claim)
    return success_object(ser_settlement(settlement))


@bp.post("/freight-claims/claims/<claim_id>/settlements/<settlement_id>/reject")
@require_roles("ClaimsManager")
def reject_settlement(claim_id, settlement_id):
    claim = get_claim_or_404(claim_id)
    settlement = get_settlement_or_404(claim, settlement_id)
    if claim["filing_status"] != "OFFERED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Rejecting requires the claim to be OFFERED", 409)
    if settlement["state"] != "OFFERED":
        raise ApiError(ERR_SETTLEMENT_INVALID_STATE,
                       "Only an OFFERED settlement may be rejected", 409)
    settlement["state"] = "REJECTED"
    touch(settlement)
    claim["filing_status"] = "DECLINED"
    add_event(claim["id"], "OFFER_REJECTED", g.user_id, {"settlement_id": settlement["id"]})
    touch_claim(claim)
    return success_object(ser_settlement(settlement))


@bp.post("/freight-claims/claims/<claim_id>/settlements/<settlement_id>/withdraw")
@require_roles("ClaimsAdjuster", "ClaimsManager")
def withdraw_settlement(claim_id, settlement_id):
    claim = get_claim_or_404(claim_id)
    settlement = get_settlement_or_404(claim, settlement_id)
    if claim["filing_status"] != "OFFERED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Withdrawing requires the claim to be OFFERED", 409)
    if settlement["state"] != "OFFERED":
        raise ApiError(ERR_SETTLEMENT_INVALID_STATE,
                       "Only an OFFERED settlement may be withdrawn", 409)
    if g.role == "ClaimsAdjuster" and g.user_id != settlement["_created_by_user_id"]:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS,
                       "Only the offering adjuster or a ClaimsManager may withdraw", 403)
    settlement["state"] = "WITHDRAWN"
    touch(settlement)
    claim["filing_status"] = "UNDER_REVIEW"
    touch_claim(claim)
    return success_object(ser_settlement(settlement))
