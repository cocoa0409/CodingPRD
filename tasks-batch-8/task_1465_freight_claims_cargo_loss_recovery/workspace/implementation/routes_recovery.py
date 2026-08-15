"""Routes: subrogation cases, reserves, claim event log."""

from flask import Blueprint, g, request

from db import STORE, iso, new_id, next_seq, now
from errors import (
    ApiError,
    ERR_CLAIM_ALREADY_TERMINAL,
    ERR_CLAIM_NOT_PAID,
    ERR_INVALID_REQUEST,
    ERR_RESERVE_ALREADY_OPEN,
    ERR_RESERVE_INVALID_STATE,
    ERR_SUBROGATION_INVALID_STATE,
)
from middleware import as_enum, as_int, as_str, req_field, request_body, require_roles
from response import paginate, success_object
from routes_claims import get_claim_or_404
from routes_negotiation import get_case_or_404, get_reserve_or_404
from serializers import ser_event, ser_reserve, ser_subrogation
from services import (
    BASIS_POINT_DENOMINATOR,
    SUBROGATION_RATIO_CAP_BP,
    TERMINAL_CLAIM_STATES,
    WORKING_CLAIM_STATES,
    add_event,
    round_half_up_int,
    suggested_reserve_cents,
    touch,
    touch_claim,
)

bp = Blueprint("recovery", __name__)

PARTY_KINDS = {"THIRD_PARTY_CARRIER", "WAREHOUSE", "BROKER", "SHIPPER_VENDOR", "OTHER"}
SUBROGATION_ACTIVE_STATES = {"OPEN", "DEMAND_SENT", "IN_LITIGATION"}


def _mark_first_departure(claim, case, actor):
    """The first transition out of OPEN appends SUBROGATION_OPENED."""
    if case["state"] == "OPEN":
        add_event(claim["id"], "SUBROGATION_OPENED", actor, {
            "subrogation_case_id": case["id"],
        })


# ---------------------------------------------------------------------------
# SubrogationCase
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/subrogation")
@require_roles("SubrogationSpecialist")
def create_subrogation(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] not in ("PAID", "CLOSED_WITH_PAYMENT"):
        raise ApiError(ERR_CLAIM_NOT_PAID,
                       "Subrogation requires the claim to be PAID or CLOSED_WITH_PAYMENT", 409)
    body = request_body()
    party_kind = as_enum(req_field(body, "responsible_party_kind"),
                         "responsible_party_kind", PARTY_KINDS)
    party_name = as_str(req_field(body, "responsible_party_name"), "responsible_party_name")
    target = as_int(req_field(body, "target_recovery_cents"), "target_recovery_cents")
    if target <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "target_recovery_cents must be > 0", 400)
    stamp = iso(now())
    case = {
        "id": new_id(),
        "claim_id": claim["id"],
        "responsible_party_kind": party_kind,
        "responsible_party_name": party_name,
        "target_recovery_cents": target,
        "recovered_cents": 0,
        "recovery_ratio_bp": 0,
        "state": "OPEN",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["subrogation"][case["id"]] = case
    return success_object(ser_subrogation(case), status=201)


@bp.get("/freight-claims/claims/<claim_id>/subrogation")
@require_roles("Any")
def list_subrogation(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [c for c in STORE["subrogation"].values() if c["claim_id"] == claim["id"]]
    state = request.args.get("state")
    if state is not None:
        records = [c for c in records if c["state"] == state]
    return paginate(records, ser_subrogation)


@bp.get("/freight-claims/claims/<claim_id>/subrogation/<case_id>")
@require_roles("Any")
def get_subrogation(claim_id, case_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_subrogation(get_case_or_404(claim, case_id)))


@bp.post("/freight-claims/claims/<claim_id>/subrogation/<case_id>/send-demand")
@require_roles("SubrogationSpecialist")
def send_demand(claim_id, case_id):
    claim = get_claim_or_404(claim_id)
    case = get_case_or_404(claim, case_id)
    if case["state"] != "OPEN":
        raise ApiError(ERR_SUBROGATION_INVALID_STATE,
                       "Only an OPEN case may send a demand", 409)
    _mark_first_departure(claim, case, g.user_id)
    case["state"] = "DEMAND_SENT"
    touch(case)
    return success_object(ser_subrogation(case))


@bp.post("/freight-claims/claims/<claim_id>/subrogation/<case_id>/litigate")
@require_roles("SubrogationSpecialist")
def litigate(claim_id, case_id):
    claim = get_claim_or_404(claim_id)
    case = get_case_or_404(claim, case_id)
    if case["state"] != "DEMAND_SENT":
        raise ApiError(ERR_SUBROGATION_INVALID_STATE,
                       "Only a DEMAND_SENT case may move to litigation", 409)
    case["state"] = "IN_LITIGATION"
    touch(case)
    return success_object(ser_subrogation(case))


@bp.post("/freight-claims/claims/<claim_id>/subrogation/<case_id>/settle")
@require_roles("SubrogationSpecialist")
def settle_subrogation(claim_id, case_id):
    claim = get_claim_or_404(claim_id)
    case = get_case_or_404(claim, case_id)
    if case["state"] not in SUBROGATION_ACTIVE_STATES:
        raise ApiError(ERR_SUBROGATION_INVALID_STATE,
                       "Only an active subrogation case may settle", 409)
    body = request_body()
    recovered = as_int(req_field(body, "recovered_cents"), "recovered_cents")
    if recovered < 0:
        raise ApiError(ERR_INVALID_REQUEST, "recovered_cents must be >= 0", 400)
    _mark_first_departure(claim, case, g.user_id)
    case["recovered_cents"] = recovered
    ratio = round_half_up_int(recovered * BASIS_POINT_DENOMINATOR,
                              max(case["target_recovery_cents"], 1))
    case["recovery_ratio_bp"] = min(ratio, SUBROGATION_RATIO_CAP_BP)
    case["state"] = "SETTLED"
    touch(case)
    claim["net_exposure_cents"] = max(claim["net_exposure_cents"] - recovered, 0)
    add_event(claim["id"], "SUBROGATION_RECOVERY", g.user_id, {
        "subrogation_case_id": case["id"], "recovered_cents": recovered,
    })
    touch_claim(claim)
    return success_object(ser_subrogation(case))


@bp.post("/freight-claims/claims/<claim_id>/subrogation/<case_id>/close-unrecoverable")
@require_roles("SubrogationSpecialist")
def close_unrecoverable(claim_id, case_id):
    claim = get_claim_or_404(claim_id)
    case = get_case_or_404(claim, case_id)
    if case["state"] not in SUBROGATION_ACTIVE_STATES:
        raise ApiError(ERR_SUBROGATION_INVALID_STATE,
                       "Only an active subrogation case may be closed unrecoverable", 409)
    _mark_first_departure(claim, case, g.user_id)
    case["state"] = "CLOSED_UNRECOVERABLE"
    touch(case)
    return success_object(ser_subrogation(case))


# ---------------------------------------------------------------------------
# Reserve
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/reserves")
@require_roles("FinanceController")
def create_reserve(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] in TERMINAL_CLAIM_STATES:
        raise ApiError(ERR_CLAIM_ALREADY_TERMINAL,
                       "A terminal claim forbids reserve mutations", 409)
    body = request_body()
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount < 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be >= 0", 400)
    for existing in STORE["reserves"].values():
        if existing["claim_id"] == claim["id"] and existing["state"] == "OPEN":
            raise ApiError(ERR_RESERVE_ALREADY_OPEN,
                           "Only one OPEN reserve per claim is permitted", 409)
    stamp = iso(now())
    reserve = {
        "id": new_id(),
        "claim_id": claim["id"],
        "amount_cents": amount,
        "posted_by_user_id": g.user_id,
        "posted_at": stamp,
        "released_at": None,
        "state": "OPEN",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["reserves"][reserve["id"]] = reserve
    claim["reserve_amount_cents"] = amount
    add_event(claim["id"], "RESERVE_POSTED", g.user_id, {
        "reserve_id": reserve["id"], "amount_cents": amount,
    })
    touch_claim(claim)
    shipment = STORE["shipments"].get(claim["shipment_id"])
    carrier = STORE["carriers"].get(claim["carrier_id"])
    lane = STORE["lanes"].get(claim["lane_id"])
    suggested = None
    if shipment is not None and carrier is not None and lane is not None:
        suggested = suggested_reserve_cents(claim, shipment, carrier, lane)
    return success_object(ser_reserve(reserve, suggested=suggested), status=201)


@bp.get("/freight-claims/claims/<claim_id>/reserves")
@require_roles("Any")
def list_reserves(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [r for r in STORE["reserves"].values() if r["claim_id"] == claim["id"]]
    state = request.args.get("state")
    if state is not None:
        records = [r for r in records if r["state"] == state]
    return paginate(records, ser_reserve)


@bp.get("/freight-claims/claims/<claim_id>/reserves/<reserve_id>")
@require_roles("Any")
def get_reserve(claim_id, reserve_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_reserve(get_reserve_or_404(claim, reserve_id)))


@bp.post("/freight-claims/claims/<claim_id>/reserves/<reserve_id>/release")
@require_roles("FinanceController")
def release_reserve(claim_id, reserve_id):
    claim = get_claim_or_404(claim_id)
    reserve = get_reserve_or_404(claim, reserve_id)
    if reserve["state"] != "OPEN":
        raise ApiError(ERR_RESERVE_INVALID_STATE,
                       "Only an OPEN reserve may be released", 409)
    if claim["filing_status"] not in WORKING_CLAIM_STATES:
        raise ApiError(ERR_CLAIM_ALREADY_TERMINAL,
                       "A terminal claim forbids reserve release", 409)
    reserve["state"] = "RELEASED"
    reserve["released_at"] = iso(now())
    touch(reserve)
    claim["reserve_amount_cents"] = 0
    add_event(claim["id"], "RESERVE_RELEASED", g.user_id, {"reserve_id": reserve["id"]})
    touch_claim(claim)
    return success_object(ser_reserve(reserve))


# ---------------------------------------------------------------------------
# ClaimEvent log
# ---------------------------------------------------------------------------

@bp.get("/freight-claims/claims/<claim_id>/events")
@require_roles("Any")
def list_events(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [e for e in STORE["events"].values() if e["claim_id"] == claim["id"]]
    event_kind = request.args.get("event_kind")
    if event_kind is not None:
        records = [e for e in records if e["event_kind"] == event_kind]
    return paginate(records, ser_event)
