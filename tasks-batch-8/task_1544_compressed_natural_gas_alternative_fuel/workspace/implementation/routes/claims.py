"""TaxCreditClaim endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_TAX_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_FINALIZABLE,
    ERR_CLAIM_NOT_SUBMITTABLE,
    ERR_CLAIM_NOT_DECIDABLE,
    ERR_CLAIM_NOT_REOPENABLE,
    ERR_CLAIM_PERIOD_OVERLAP,
    ERR_STATION_NOT_ACTIVE,
    ERR_OVERDUE_INSPECTION,
    ERR_NO_ELIGIBLE_VOLUME,
    ERR_INVALID_TIME_RANGE,
    ERR_INVALID_REQUEST,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import tax_credit_claim_out
from services.core import touch, station_has_overdue_inspection
from services.pricing import compute_provisional_claim, compute_final_claim
from validators import (
    body, require_fields, require_string, require_datetime, require_enum,
    parse_pagination, paginate,
)

bp = Blueprint("claims", __name__)

_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer"]


def get_claim_or_404(cid: str) -> dict:
    c = STORE.tax_credit_claims.get(cid)
    if c is None:
        raise ApiError(ERR_TAX_CLAIM_NOT_FOUND, 404, "Tax credit claim id does not exist")
    return c


@bp.post("/cng/tax-credit-claims")
def create_claim():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "period_start", "period_end"])
    station_id = require_string(data, "station_id")
    period_start = require_datetime(data, "period_start")
    period_end = require_datetime(data, "period_end")

    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")

    # Overlap with SUBMITTED/APPROVED claim at same station (stage 8)
    for c in STORE.tax_credit_claims.values():
        if c["station_id"] != station_id:
            continue
        if c["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        if period_start < c["period_end"] and c["period_start"] < period_end:
            raise ApiError(ERR_CLAIM_PERIOD_OVERLAP, 409,
                           "Claim period overlaps a SUBMITTED or APPROVED claim at the same station")

    # Temporal (stage 9)
    if not period_start < period_end:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "period_start must be strictly earlier than period_end")

    provisional_gge, provisional_amount = compute_provisional_claim(
        station_id, period_start, period_end)

    now = now_utc()
    claim = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "eligible_gge_provisional": provisional_gge,
        "claim_amount_provisional_cents": provisional_amount,
        "eligible_gge_final": None,
        "claim_amount_final_cents": None,
        "decision_reason": None,
    }
    STORE.tax_credit_claims[claim["id"]] = claim
    return success_object(tax_credit_claim_out(claim), status=201)


@bp.get("/cng/tax-credit-claims")
def list_claims():
    caller = get_caller()
    require_role(caller, _READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = sorted(STORE.tax_credit_claims.values(), key=lambda c: (c["created_at"], c["id"]))
    if station_id is not None:
        items = [c for c in items if c["station_id"] == station_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([tax_credit_claim_out(c) for c in page], limit, offset, total)


@bp.get("/cng/tax-credit-claims/<claimId>")
def get_claim(claimId: str):
    caller = get_caller()
    require_role(caller, _READ)
    return success_object(tax_credit_claim_out(get_claim_or_404(claimId)))


@bp.post("/cng/tax-credit-claims/<claimId>/finalize")
def finalize_claim(claimId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    claim = get_claim_or_404(claimId)
    if claim["status"] != "DRAFT":
        raise ApiError(ERR_CLAIM_NOT_FINALIZABLE, 409,
                       "Claim finalize requires DRAFT")
    final_gge, final_amount = compute_final_claim(
        claim["station_id"], claim["period_start"], claim["period_end"])
    if final_amount == 0 and final_gge == 0:
        raise ApiError(ERR_NO_ELIGIBLE_VOLUME, 422,
                       "Claim finalize found zero eligible SETTLED sessions")
    claim["eligible_gge_final"] = final_gge
    claim["claim_amount_final_cents"] = final_amount
    claim["status"] = "FINALIZED"
    touch(claim)
    return success_object(tax_credit_claim_out(claim))


@bp.post("/cng/tax-credit-claims/<claimId>/submit")
def submit_claim(claimId: str):
    caller = get_caller()
    require_role(caller, ["ComplianceOfficer"])
    claim = get_claim_or_404(claimId)
    if claim["status"] != "FINALIZED":
        raise ApiError(ERR_CLAIM_NOT_SUBMITTABLE, 409,
                       "Claim submit requires FINALIZED")
    station = STORE.stations.get(claim["station_id"])
    if station is None or station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Claim submit requires station ACTIVE")
    if station_has_overdue_inspection(claim["station_id"]):
        raise ApiError(ERR_OVERDUE_INSPECTION, 409,
                       "Station has an OVERDUE safety inspection")
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success_object(tax_credit_claim_out(claim))


@bp.post("/cng/tax-credit-claims/<claimId>/decision")
def decide_claim(claimId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["outcome"])
    outcome = require_enum(data, "outcome", {"APPROVED", "REJECTED"})
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason must be a string")
    claim = get_claim_or_404(claimId)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_NOT_DECIDABLE, 409,
                       "Claim decision requires SUBMITTED")
    claim["status"] = outcome
    claim["decision_reason"] = reason
    touch(claim)
    return success_object(tax_credit_claim_out(claim))


@bp.post("/cng/tax-credit-claims/<claimId>/reopen")
def reopen_claim(claimId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    claim = get_claim_or_404(claimId)
    if claim["status"] != "REJECTED":
        raise ApiError(ERR_CLAIM_NOT_REOPENABLE, 409,
                       "Claim reopen requires REJECTED")
    provisional_gge, provisional_amount = compute_provisional_claim(
        claim["station_id"], claim["period_start"], claim["period_end"])
    claim["status"] = "DRAFT"
    claim["eligible_gge_provisional"] = provisional_gge
    claim["claim_amount_provisional_cents"] = provisional_amount
    claim["eligible_gge_final"] = None
    claim["claim_amount_final_cents"] = None
    touch(claim)
    return success_object(tax_credit_claim_out(claim))
