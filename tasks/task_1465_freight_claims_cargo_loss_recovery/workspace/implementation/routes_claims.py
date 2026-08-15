"""Routes: claims CRUD and claim-level actions
(submit / acknowledge / decline / withdraw / close / liability-preview)."""

from datetime import timedelta

from flask import g, request

from db import STORE, iso, new_id, next_seq, now
from errors import (
    ApiError,
    ERR_APPEAL_PENDING,
    ERR_ASSESSMENT_REQUIRED,
    ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
    ERR_CLAIM_INVALID_STATE,
    ERR_CLAIM_NOT_FOUND,
    ERR_FILING_DEADLINE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_REQUIRED_DOCUMENT_MISSING,
    ERR_SHIPMENT_NOT_DELIVERED,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import as_enum, as_int, as_str, req_field, request_body, require_roles
from response import paginate, success_object
from serializers import ser_claim
from services import (
    add_event,
    bump_carrier_counters,
    bump_lane_counters,
    close_shipment_if_all_terminal,
    find_assignment,
    liability_pipeline,
    revert_shipment_after_withdraw,
    touch,
    touch_claim,
)
from flask import Blueprint

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"LOSS", "DAMAGE", "SHORTAGE", "CONCEALED_DAMAGE", "DELAY"}


def get_claim_or_404(claim_id):
    claim = STORE["claims"].get(claim_id)
    if claim is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, f"Claim '{claim_id}' not found", 404)
    return claim


@bp.post("/freight-claims/claims")
@require_roles("ClaimsClerk")
def create_claim():
    body = request_body()
    shipment_id = as_str(req_field(body, "shipment_id"), "shipment_id")
    claim_type = as_enum(req_field(body, "claim_type"), "claim_type", CLAIM_TYPES)
    claimed_amount = as_int(req_field(body, "claimed_amount_cents"), "claimed_amount_cents")
    shipment = STORE["shipments"].get(shipment_id)
    if shipment is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, f"Shipment '{shipment_id}' not found", 404)
    if claimed_amount <= 0 or claimed_amount > shipment["declared_value_cents"]:
        raise ApiError(
            ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
            "claimed_amount_cents must be > 0 and <= shipment.declared_value_cents",
            422,
        )
    carrier = STORE["carriers"].get(shipment["carrier_id"])
    lane = STORE["lanes"].get(shipment["lane_id"])
    assignment = find_assignment(shipment["carrier_id"], shipment["lane_id"],
                                 shipment["_ship_date_dt"])
    if (shipment["status"] != "DELIVERED"
            or carrier is None or carrier["status"] != "ACTIVE"
            or lane is None or lane["status"] != "ACTIVE"
            or assignment is None):
        raise ApiError(
            ERR_SHIPMENT_NOT_DELIVERED,
            "Claim opening requires a DELIVERED shipment, an ACTIVE carrier, an ACTIVE lane,"
            " and a carrier-lane assignment covering the ship_date",
            409,
        )
    stamp = iso(now())
    deadline_dt = shipment["_ship_date_dt"] + timedelta(days=carrier["carmack_filing_days"])
    claim = {
        "id": new_id(),
        "shipment_id": shipment["id"],
        "carrier_id": shipment["carrier_id"],
        "lane_id": shipment["lane_id"],
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount,
        "filing_received_at": None,
        "filing_deadline_at": iso(deadline_dt),
        "acknowledgment_due_at": None,
        "acknowledged_at": None,
        "acknowledgment_late": False,
        "liability_assessment_id": None,
        "computed_liability_cents": 0,
        "salvage_credit_cents": 0,
        "net_exposure_cents": 0,
        "reserve_amount_cents": 0,
        "settlement_amount_cents": None,
        "appeal_round": 0,
        "filing_status": "DRAFT",
        "payment_status": "UNPAID",
        "concurrency_token": 1,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_filing_deadline_dt": deadline_dt,
        "_ack_due_dt": None,
        "_filing_received_dt": None,
        "_seq": next_seq(),
    }
    STORE["claims"][claim["id"]] = claim
    return success_object(ser_claim(claim), status=201)


@bp.get("/freight-claims/claims")
@require_roles("Any")
def list_claims():
    records = list(STORE["claims"].values())
    for param in ("carrier_id", "lane_id", "shipment_id", "filing_status",
                  "payment_status", "liability_assessment_id"):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c.get(param) == value]
    return paginate(records, ser_claim)


@bp.get("/freight-claims/claims/<claim_id>")
@require_roles("Any")
def get_claim(claim_id):
    return success_object(ser_claim(get_claim_or_404(claim_id)))


@bp.post("/freight-claims/claims/<claim_id>/submit")
@require_roles("ClaimsClerk")
def submit_claim(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "DRAFT":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Only a DRAFT claim may be submitted", 409)
    if now() > claim["_filing_deadline_dt"]:
        raise ApiError(ERR_FILING_DEADLINE_PASSED,
                       "The Carmack filing deadline has passed", 422)
    docs = [d for d in STORE["documents"].values() if d["claim_id"] == claim["id"]]
    has_bol = any(d["document_kind"] == "BOL" and d["verification_status"] != "REJECTED"
                  for d in docs)
    has_invoice = any(d["document_kind"] == "COMMERCIAL_INVOICE"
                      and d["verification_status"] != "REJECTED" for d in docs)
    if not has_bol or not has_invoice:
        raise ApiError(ERR_REQUIRED_DOCUMENT_MISSING,
                       "A non-rejected BOL and COMMERCIAL_INVOICE are required", 422)
    shipment = STORE["shipments"][claim["shipment_id"]]
    if claim["claimed_amount_cents"] > shipment["declared_value_cents"]:
        raise ApiError(ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
                       "claimed_amount_cents exceeds shipment.declared_value_cents", 422)
    carrier = STORE["carriers"][claim["carrier_id"]]
    lane = STORE["lanes"][claim["lane_id"]]

    current = now()
    claim["filing_received_at"] = iso(current)
    claim["_filing_received_dt"] = current
    deadline_dt = shipment["_ship_date_dt"] + timedelta(days=carrier["carmack_filing_days"])
    claim["filing_deadline_at"] = iso(deadline_dt)
    claim["_filing_deadline_dt"] = deadline_dt
    ack_due_dt = current + timedelta(days=carrier["carmack_acknowledgment_days"])
    claim["acknowledgment_due_at"] = iso(ack_due_dt)
    claim["_ack_due_dt"] = ack_due_dt
    claim["filing_status"] = "SUBMITTED"
    bump_carrier_counters(carrier, filed_delta=1)
    bump_lane_counters(lane, claims_delta=1)
    shipment["status"] = "CLAIMED"
    touch(shipment)
    add_event(claim["id"], "FILED", g.user_id, {
        "claimed_amount_cents": claim["claimed_amount_cents"],
        "filing_deadline_at": claim["filing_deadline_at"],
    })
    touch_claim(claim)
    return success_object(ser_claim(claim))


@bp.post("/freight-claims/claims/<claim_id>/acknowledge")
@require_roles("ClaimsAdjuster")
def acknowledge_claim(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Only a SUBMITTED claim may be acknowledged", 409)
    current = now()
    claim["acknowledged_at"] = iso(current)
    if claim["_ack_due_dt"] is not None and current > claim["_ack_due_dt"]:
        claim["acknowledgment_late"] = True
        add_event(claim["id"], "ACK_LATE_FLAGGED", g.user_id, {
            "acknowledgment_due_at": claim["acknowledgment_due_at"],
        })
    claim["filing_status"] = "ACKNOWLEDGED"
    add_event(claim["id"], "ACKNOWLEDGED", g.user_id, {
        "acknowledged_at": claim["acknowledged_at"],
    })
    touch_claim(claim)
    return success_object(ser_claim(claim))


@bp.post("/freight-claims/claims/<claim_id>/decline")
@require_roles("ClaimsAdjuster")
def decline_claim(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Only an UNDER_REVIEW claim may be declined", 409)
    if claim["liability_assessment_id"] is None:
        raise ApiError(ERR_ASSESSMENT_REQUIRED,
                       "A liability assessment is required before declining", 409)
    body = request_body()
    expected = as_int(req_field(body, "expected_claim_version"), "expected_claim_version")
    if expected != claim["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_claim_version does not match the claim's current version", 412)
    claim["filing_status"] = "DECLINED"
    add_event(claim["id"], "DECLINED", g.user_id, {})
    touch_claim(claim)
    return success_object(ser_claim(claim))


@bp.post("/freight-claims/claims/<claim_id>/withdraw")
@require_roles("ClaimsClerk")
def withdraw_claim(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] not in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"):
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Only DRAFT, SUBMITTED or ACKNOWLEDGED claims may be withdrawn", 409)
    was_filed = claim["filing_status"] in ("SUBMITTED", "ACKNOWLEDGED")
    claim["filing_status"] = "WITHDRAWN"
    if was_filed:
        carrier = STORE["carriers"].get(claim["carrier_id"])
        if carrier is not None:
            bump_carrier_counters(carrier, filed_delta=-1)
        lane = STORE["lanes"].get(claim["lane_id"])
        if lane is not None:
            bump_lane_counters(lane, claims_delta=-1)
    shipment = STORE["shipments"].get(claim["shipment_id"])
    if shipment is not None:
        revert_shipment_after_withdraw(shipment, claim["id"])
    add_event(claim["id"], "WITHDRAWN", g.user_id, {})
    touch_claim(claim)
    return success_object(ser_claim(claim))


@bp.post("/freight-claims/claims/<claim_id>/close")
@require_roles("ClaimsManager")
def close_claim(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "DECLINED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Only a DECLINED claim may be closed", 409)
    body = request_body()
    waive = body.get("waive_appeal", False)
    if not isinstance(waive, bool):
        raise ApiError(ERR_INVALID_REQUEST, "waive_appeal must be a boolean", 400)
    if claim["appeal_round"] < 2 and not waive:
        raise ApiError(ERR_APPEAL_PENDING,
                       "Appeal rounds remain; pass waive_appeal=true to close now", 409)
    reserve = None
    for candidate in STORE["reserves"].values():
        if candidate["claim_id"] == claim["id"] and candidate["state"] == "OPEN":
            reserve = candidate
            break
    if reserve is not None:
        reserve["state"] = "RELEASED"
        reserve["released_at"] = iso(now())
        touch(reserve)
        claim["reserve_amount_cents"] = 0
        add_event(claim["id"], "RESERVE_RELEASED", g.user_id, {"reserve_id": reserve["id"]})
    claim["filing_status"] = "CLOSED_NO_PAYMENT"
    touch_claim(claim)
    shipment = STORE["shipments"].get(claim["shipment_id"])
    if shipment is not None:
        close_shipment_if_all_terminal(shipment)
    return success_object(ser_claim(claim))


@bp.get("/freight-claims/claims/<claim_id>/liability-preview")
@require_roles("ClaimsClerk", "ClaimsAdjuster", "ClaimsManager")
def liability_preview(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "DRAFT":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Liability preview is available only on DRAFT claims", 409)
    shipment = STORE["shipments"][claim["shipment_id"]]
    carrier = STORE["carriers"][claim["carrier_id"]]
    basis, carrier_limit, discount_pct, computed = liability_pipeline(
        claim, shipment, carrier, negligence_flag=None)
    return success_object({
        "basis_cents": basis,
        "carrier_limit_cents": carrier_limit,
        "lane_discount_pct": discount_pct,
        "computed_liability_cents": computed,
    })
