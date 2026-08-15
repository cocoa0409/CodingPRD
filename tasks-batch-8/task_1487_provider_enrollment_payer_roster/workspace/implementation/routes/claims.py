"""Claims: intake gating via the coverage test, and recoupment reversal."""
from flask import Blueprint, request

from db import base_fields, store, touch
from errors import (
    ApiError,
    ERR_CLAIM_NOT_RECOUPED,
    ERR_FUTURE_SERVICE_DATE,
    ERR_PROVIDER_TERMINATED,
    invalid_request,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import pub
from services import covering_record
from validate import body, req_date, req_int, req_str

bp = Blueprint("claims", __name__)


def _get_claim(cid):
    c = store.claims.get(cid)
    if c is None:
        raise not_found("Claim")
    return c


@bp.post("/api/claims")
@require_roles("EnrollmentSpecialist")
def create_claim():
    b = body()
    # Existence (tier 3) of body FKs before schema (tier 4).
    pid_raw = b.get("provider_id")
    yid_raw = b.get("payer_id")
    if isinstance(pid_raw, str) and pid_raw not in store.providers:
        raise not_found("Provider")
    if isinstance(yid_raw, str) and yid_raw not in store.payers:
        raise not_found("Payer")
    pid = req_str(b, "provider_id")
    yid = req_str(b, "payer_id")
    service_date = req_date(b, "service_date")
    amount_cents = req_int(b, "amount_cents")
    if amount_cents <= 0:
        raise invalid_request("amount_cents must be a positive integer")
    # Compliance gate (tier 8).
    prov = store.providers[pid]
    if prov["status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_TERMINATED, 409, "Provider is TERMINATED")
    # Temporal (tier 10).
    if service_date > store.clock.date().isoformat():
        raise ApiError(
            ERR_FUTURE_SERVICE_DATE,
            422,
            "service_date is later than the current logical date",
        )
    # claim_hold_evaluation: initial status is computed, never supplied.
    payer = store.payers[yid]
    if covering_record(pid, yid, service_date) is not None:
        status = "RELEASED"
        denial_reason = None
    elif payer["claims_hold_enabled"]:
        status = "HELD"
        denial_reason = None
    else:
        status = "DENIED"
        denial_reason = "PAYER_HOLD_DISABLED"
    claim = base_fields()
    claim.update(
        {
            "provider_id": pid,
            "payer_id": yid,
            "service_date": service_date,
            "amount_cents": amount_cents,
            "status": status,
            "denial_reason": denial_reason,
            "recoupment_fee_cents": 0,
        }
    )
    store.claims[claim["id"]] = claim
    return success_object(pub(claim), 201)


@bp.get("/api/claims/<cid>")
@require_roles(*ALL_ROLES)
def get_claim(cid):
    return success_object(pub(_get_claim(cid)))


@bp.get("/api/claims")
@require_roles(*ALL_ROLES)
def list_claims():
    provider_id = request.args.get("provider_id")
    payer_id = request.args.get("payer_id")
    status = request.args.get("status")
    items = [
        c for c in store.claims.values()
        if (provider_id is None or c["provider_id"] == provider_id)
        and (payer_id is None or c["payer_id"] == payer_id)
        and (status is None or c["status"] == status)
    ]
    return list_response(items, pub)


@bp.post("/api/claims/<cid>/reverse-recoupment")
@require_roles("ComplianceOfficer")
def reverse_recoupment(cid):
    claim = _get_claim(cid)
    if claim["status"] != "RECOUPED":
        raise ApiError(ERR_CLAIM_NOT_RECOUPED, 409, "The claim is not RECOUPED")
    # RECOUPED -> RELEASED; the provider balance is derived from RECOUPED claims,
    # so flipping status + zeroing the fee decrements it by (amount + fee).
    claim["status"] = "RELEASED"
    claim["recoupment_fee_cents"] = 0
    touch(claim)
    return success_object(pub(claim))
