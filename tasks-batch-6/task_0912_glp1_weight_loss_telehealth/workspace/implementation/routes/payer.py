"""Prior authorisation, denial, appeal and the cash fallback (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard
from errors import ApiError
from store import format_iso, new_record, ordered, store, touch

bp = Blueprint("payer", __name__)

DECISIONS = ("APPROVED", "DENIED")


@bp.post("/prior-authorizations")
def create_prior_authorization():
    guard(["Provider"])
    body = v.body()

    prescription_id = v.string_field(body, "prescription_id", required=True)
    payer_reference = v.string_field(body, "payer_reference", required=True)

    services.get_prescription(prescription_id)

    authorization = new_record(store.prior_authorizations, {
        "prescription_id": prescription_id,
        "payer_reference": payer_reference,
        "status": "SUBMITTED",
        "appeal_count": 0,
        "decided_at": None,
        "denial_reason": None,
        "approved_through_at": None,
    })
    return envelope.success(serializers.dump("prior_authorization", authorization), 201)


@bp.get("/prior-authorizations/<prior_authorization_id>")
def read_prior_authorization(prior_authorization_id):
    guard(ANY_ROLE)
    authorization = services.get_prior_authorization(prior_authorization_id)
    return envelope.success(serializers.dump("prior_authorization", authorization), 200)


@bp.get("/prior-authorizations")
def list_prior_authorizations():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("prescription_id", "status")
    records = v.apply_filters(ordered(list(store.prior_authorizations.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("prior_authorization", page),
                               limit, offset, total)


@bp.post("/prior-authorizations/<prior_authorization_id>/decide")
def decide_prior_authorization(prior_authorization_id):
    guard(["BillingAdmin"])
    authorization = services.get_prior_authorization(prior_authorization_id)

    body = v.body()
    decision = v.enum_field(body, "decision", DECISIONS, required=True)
    denial_reason = v.string_field(body, "denial_reason", required=False, default=None)

    if authorization["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError(errors.ERR_INVALID_STATE)

    prescription = services.get_prescription(authorization["prescription_id"])
    if prescription["clinical_status"] not in ("ACTIVE", "HELD"):
        raise ApiError(errors.ERR_INVALID_STATE)

    now_iso = store.now_iso()
    authorization["decided_at"] = now_iso

    if decision == "APPROVED":
        authorization["status"] = "APPROVED"
        authorization["approved_through_at"] = format_iso(
            store.now_dt() + timedelta(days=calc.PA_VALIDITY_DAYS))
        touch(authorization)
        prescription["active_route_mode"] = "INSURANCE"
        touch(prescription)
    else:
        authorization["status"] = "DENIED"
        authorization["denial_reason"] = denial_reason
        touch(authorization)
        prescription["active_route_mode"] = "CASH"
        touch(prescription)
        for order in services.orders_of_prescription(prescription["id"]):
            if order["dispense_type_at_route"] == "BRANDED" \
                    and order["status"] in ("CREATED", "RESERVED"):
                services.cancel_order(order, "PA_DENIED")

    return envelope.success(serializers.dump("prior_authorization", authorization), 200)


@bp.post("/prior-authorizations/<prior_authorization_id>/appeal")
def appeal_prior_authorization(prior_authorization_id):
    guard(["Provider"])
    authorization = services.get_prior_authorization(prior_authorization_id)

    body = v.body()
    payer_reference = v.string_field(body, "payer_reference", required=False,
                                     default=None)

    if authorization["status"] != "DENIED":
        raise ApiError(errors.ERR_INVALID_STATE)
    if authorization["appeal_count"] >= calc.MAX_PA_APPEALS:
        raise ApiError(errors.ERR_APPEAL_LIMIT_REACHED)

    if payer_reference is not None:
        authorization["payer_reference"] = payer_reference
    authorization["status"] = "APPEALED"
    authorization["appeal_count"] += 1
    authorization["decided_at"] = None
    authorization["denial_reason"] = None
    touch(authorization)

    return envelope.success(serializers.dump("prior_authorization", authorization), 200)
