"""Co-op advertising claims."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_DUPLICATE, ERR_ACCRUAL_EXCEEDED, \
    invalid_state, invalid_request
from middleware import authenticate, authorize, require_owner
from response import success
from serializers import coop_claim as ser
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_int, \
    touch, is_int, period_window
from routes.common import body, get_path, get_ref, new_common, list_response

bp = Blueprint("coop", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser"}
_ADMIN_ACTIONS = {"VERIFY", "APPROVE", "REJECT", "DISPUTE", "PAY"}
_CONTRACTOR_ACTIONS = {"RESUBMIT"}


@bp.post("/coop-claims")
def create_claim():
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"contractor_id", "invoice_reference", "period",
                                "spend_cents"}, struct)
    contractor_id = get_str(data, "contractor_id", struct)
    invoice_reference = get_str(data, "invoice_reference", struct)
    period = get_str(data, "period", struct)
    spend_cents = get_int(data, "spend_cents", struct, minimum=0)
    if period is not None and period_window(period) is None:
        struct.add("period must be of the form YYYY-H1 or YYYY-H2")

    if isinstance(contractor_id, str):
        get_ref(db.contractors, contractor_id, "contractor_id")
    if isinstance(contractor_id, str):
        require_owner(contractor_id, role, user_id)

    # invoice_reference unique per contractor (priority 14).
    if isinstance(contractor_id, str) and isinstance(invoice_reference, str):
        for c in db.coop_claims.values():
            if c["contractor_id"] == contractor_id and \
                    c["invoice_reference"] == invoice_reference:
                raise ApiError(ERR_DUPLICATE, 409,
                               "invoice_reference already exists for this "
                               "contractor")
    struct.raise_if_bad()

    c = new_common()
    c.update({
        "contractor_id": contractor_id,
        "invoice_reference": invoice_reference,
        "period": period,
        "spend_cents": spend_cents,
        "eligible_amount_cents": 0,
        "approved_amount_cents": None,
        "status": "SUBMITTED",
    })
    db.coop_claims[c["id"]] = c
    return success(ser(c), 201)


@bp.get("/coop-claims/<cid>")
def get_claim(cid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    c = get_path(db.coop_claims, cid)
    require_owner(c["contractor_id"], role, user_id)
    return success(ser(c))


@bp.get("/coop-claims")
def list_claims():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"contractor_id": request.args.get("contractor_id"),
               "status": request.args.get("status"),
               "period": request.args.get("period")}
    return list_response(db.coop_claims.values(), ser, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)


@bp.post("/coop-claims/<cid>/decision")
def claim_decision(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin", "ContractorUser"}, role)
    data = body()
    action = data.get("action")
    if not isinstance(action, str) or action not in (
            _ADMIN_ACTIONS | _CONTRACTOR_ACTIONS):
        raise invalid_request("action must be one of %s"
                              % sorted(_ADMIN_ACTIONS | _CONTRACTOR_ACTIONS))
    if action in _ADMIN_ACTIONS:
        authorize({"DistributorAdmin"}, role)
    else:
        authorize({"ContractorUser"}, role)

    c = get_path(db.coop_claims, cid)
    if action == "RESUBMIT":
        require_owner(c["contractor_id"], role, user_id)

    if action == "VERIFY":
        if c["status"] != "SUBMITTED":
            raise invalid_state("Only a SUBMITTED claim may be verified")
        c["eligible_amount_cents"] = core.compute_coop_eligible(c)
        c["status"] = "VERIFIED"
    elif action == "APPROVE":
        if c["status"] != "VERIFIED":
            raise invalid_state("Only a VERIFIED claim may be approved")
        approved = data.get("approved_amount_cents")
        if approved is None or not is_int(approved) or approved < 0:
            raise invalid_request(
                "approved_amount_cents must be a non-negative integer")
        if approved > c["eligible_amount_cents"]:
            raise ApiError(ERR_ACCRUAL_EXCEEDED, 422,
                           "approved_amount_cents exceeds eligible_amount_cents")
        if approved > core.compute_final_accrual(c["contractor_id"]):
            raise ApiError(ERR_ACCRUAL_EXCEEDED, 422,
                           "approved_amount_cents exceeds the current final "
                           "accrual balance")
        c["approved_amount_cents"] = approved
        c["status"] = "APPROVED"
    elif action == "DISPUTE":
        if c["status"] != "VERIFIED":
            raise invalid_state("Only a VERIFIED claim may be disputed")
        c["status"] = "DISPUTED"
    elif action == "REJECT":
        if c["status"] != "VERIFIED":
            raise invalid_state("Only a VERIFIED claim may be rejected")
        c["status"] = "REJECTED"
    elif action == "RESUBMIT":
        if c["status"] != "DISPUTED":
            raise invalid_state("Only a DISPUTED claim may be resubmitted")
        spend = data.get("spend_cents")
        if spend is None or not is_int(spend) or spend < 0:
            raise invalid_request("spend_cents must be a non-negative integer")
        c["spend_cents"] = spend
        c["eligible_amount_cents"] = 0
        c["status"] = "SUBMITTED"
    elif action == "PAY":
        if c["status"] != "APPROVED":
            raise invalid_state("Only an APPROVED claim may be paid")
        c["status"] = "PAID"
        # Payment debits the final accrual (spendable balance).
        contractor = db.contractors.get(c["contractor_id"])
        if contractor is not None:
            core.refresh_contractor_commercials(contractor)
    touch(c)
    return success(ser(c))
