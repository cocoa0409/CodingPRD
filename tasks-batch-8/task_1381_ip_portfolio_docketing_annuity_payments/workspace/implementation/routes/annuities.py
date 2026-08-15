"""AnnuityObligation and PaymentAuthorization routes (PRD §3.4, §3.5)."""

from flask import Blueprint, request

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_SCOPE_VIOLATION,
    ERR_CLIENT_SUSPENDED,
    ERR_SURCHARGE_WINDOW_CLOSED,
    ERR_AUTHORIZATION_NOT_RELEASED,
    ERR_ASSIGNMENT_RECORDATION_REQUIRED,
    ERR_COUNSEL_INSTRUCTION_REQUIRED,
    ERR_FAMILY_BUDGET_EXCEEDED,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list, success_list_all
from services.common import (
    new_id, stamp_new, bump, get_application, get_obligation, get_authorization,
    application_of_obligation, family_of_obligation, client_of_application,
    rule_for_jurisdiction, check_allowed_fields, req_int, req_date,
    ensure_transition,
)
from services import calc
from services.cascade import current_authorization

bp = Blueprint("annuities", __name__)


def _require_client_active_for_obligation(ob):
    client = client_of_application(application_of_obligation(ob))
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")


# --- AnnuityObligation -------------------------------------------------------

@bp.get("/applications/<application_id>/annuity-obligations")
def list_application_obligations(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [o for o in dbmod.DB["obligations"].values() if o["application_id"] == app["id"]]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    # Per-application obligation list is ordered by period_year ASC (PRD §2.3).
    items.sort(key=lambda r: (r["period_year"], r["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.obligation(r) for r in page], total, limit, offset)


@bp.get("/annuity-obligations/<obligation_id>")
def get_obligation_route(obligation_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.obligation(get_obligation(obligation_id)))


@bp.post("/annuity-obligations/<obligation_id>/authorizations")
def create_authorization(obligation_id):
    user_id, _ = require_roles(["DocketingManager", "FinanceOfficer"])
    ob = get_obligation(obligation_id)
    body = get_json_body()
    # OCC (priority 5) precedes body-shape validation (priority 6).
    expected = body.get("expected_annuity_obligation_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != ob["version"]:
            raise_err(ERR_STALE_VERSION, "expected_annuity_obligation_version is stale")
    check_allowed_fields(body, {"amount_cents", "expected_annuity_obligation_version"})
    amount_cents = req_int(body, "amount_cents")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_annuity_obligation_version is required and must be an integer")
    ensure_transition(ob, {"SCHEDULED"}, "obligations", "AnnuityObligation")
    _require_client_active_for_obligation(ob)
    rec = stamp_new({
        "id": new_id(),
        "annuity_obligation_id": ob["id"],
        "amount_cents": amount_cents,
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "status": "REQUESTED",
    })
    dbmod.DB["authorizations"][rec["id"]] = rec
    ob["status"] = "PENDING_AUTHORIZATION"
    bump(ob)  # increments AnnuityObligation.version by 1
    return success_object(serialize.authorization(rec), 201)


@bp.get("/annuity-obligations/<obligation_id>/authorizations")
def list_obligation_authorizations(obligation_id):
    require_roles(ALL_ROLES)
    ob = get_obligation(obligation_id)
    items = [
        a for a in dbmod.DB["authorizations"].values()
        if a["annuity_obligation_id"] == ob["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.authorization(r) for r in items])


@bp.post("/annuity-obligations/<obligation_id>/deauthorize")
def deauthorize(obligation_id):
    require_roles(["DocketingManager"])
    ob = get_obligation(obligation_id)
    ensure_transition(ob, {"AUTHORIZED"}, "obligations", "AnnuityObligation")
    family = family_of_obligation(ob)
    family["committed_forecast_cents"] -= ob["authorized_amount_cents"]
    bump(family)
    ob["authorized_amount_cents"] = None
    ob["status"] = "SCHEDULED"
    bump(ob)
    auth = current_authorization(ob["id"])
    if auth is not None and auth["status"] in ("APPROVED", "RELEASED"):
        auth["status"] = "SUPERSEDED"
        bump(auth)
    return success_object(serialize.obligation(ob))


@bp.post("/annuity-obligations/<obligation_id>/instruct-payment")
def instruct_payment(obligation_id):
    require_roles(["FinanceOfficer"])
    ob = get_obligation(obligation_id)
    ensure_transition(ob, {"AUTHORIZED"}, "obligations", "AnnuityObligation")
    auth = current_authorization(ob["id"])
    if auth is None or auth["status"] != "RELEASED":
        raise_err(ERR_AUTHORIZATION_NOT_RELEASED, "Current authorization is not RELEASED")
    app = application_of_obligation(ob)
    rule = rule_for_jurisdiction(app["jurisdiction"])
    if rule["requires_recorded_assignment_for_payment"]:
        recorded = any(
            a["application_id"] == app["id"] and a["status"] == "RECORDED"
            for a in dbmod.DB["assignments"].values()
        )
        if not recorded:
            raise_err(
                ERR_ASSIGNMENT_RECORDATION_REQUIRED,
                "Jurisdiction requires a RECORDED assignment before payment instruction",
            )
    if rule["requires_confirmed_instruction_for_payment"]:
        confirmed = any(
            ins["application_id"] == app["id"]
            and ins["instruction_type"] == "ANNUITY_PAYMENT"
            and ins["status"] in ("CONFIRMED", "COMPLETED")
            for ins in dbmod.DB["instructions"].values()
        )
        if not confirmed:
            raise_err(
                ERR_COUNSEL_INSTRUCTION_REQUIRED,
                "Jurisdiction requires a CONFIRMED ANNUITY_PAYMENT instruction",
            )
    ob["status"] = "PAYMENT_INSTRUCTED"
    bump(ob)
    return success_object(serialize.obligation(ob))


@bp.post("/annuity-obligations/<obligation_id>/raise-confirmation-query")
def raise_confirmation_query(obligation_id):
    require_roles(["FinanceOfficer"])
    ob = get_obligation(obligation_id)
    ensure_transition(ob, {"PAYMENT_INSTRUCTED"}, "obligations", "AnnuityObligation")
    ob["status"] = "CONFIRMATION_QUERY"
    bump(ob)
    return success_object(serialize.obligation(ob))


@bp.post("/annuity-obligations/<obligation_id>/reinstruct")
def reinstruct(obligation_id):
    require_roles(["FinanceOfficer"])
    ob = get_obligation(obligation_id)
    ensure_transition(ob, {"CONFIRMATION_QUERY"}, "obligations", "AnnuityObligation")
    ob["status"] = "PAYMENT_INSTRUCTED"
    bump(ob)
    return success_object(serialize.obligation(ob))


@bp.post("/annuity-obligations/<obligation_id>/confirm-payment")
def confirm_payment(obligation_id):
    require_roles(["FinanceOfficer"])
    ob = get_obligation(obligation_id)
    body = get_json_body()
    check_allowed_fields(body, {"paid_date"})
    paid_date = req_date(body, "paid_date")
    ensure_transition(ob, {"PAYMENT_INSTRUCTED"}, "obligations", "AnnuityObligation")
    if paid_date > ob["surcharge_window_end"]:
        raise_err(ERR_SURCHARGE_WINDOW_CLOSED, "paid_date is beyond surcharge_window_end")
    app = application_of_obligation(ob)
    rule = rule_for_jurisdiction(app["jurisdiction"])
    _, _, paid_usd = calc.annuity_fee_amount(
        rule, app["entity_size"], ob["period_year"], ob["due_date"], paid_date
    )
    family = family_of_obligation(ob)
    family["committed_forecast_cents"] += paid_usd - ob["authorized_amount_cents"]
    bump(family)
    ob["paid_amount_cents"] = paid_usd
    ob["authorized_amount_cents"] = None
    ob["status"] = "PAID_CONFIRMED"
    bump(ob)
    return success_object(serialize.obligation(ob))


# --- PaymentAuthorization -----------------------------------------------------

@bp.get("/authorizations/<authorization_id>")
def get_authorization_route(authorization_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.authorization(get_authorization(authorization_id)))


def _scope_check_client_approver(user_id, auth):
    """Priority 3: acting ClientContact.client_id must equal the family client."""
    contact = dbmod.DB["contacts"][user_id]
    ob = dbmod.DB["obligations"][auth["annuity_obligation_id"]]
    family = family_of_obligation(ob)
    if contact["client_id"] != family["client_id"]:
        raise_err(ERR_SCOPE_VIOLATION, "ClientApprover contact belongs to a different client")


@bp.post("/authorizations/<authorization_id>/approve")
def approve_authorization(authorization_id):
    user_id, _ = require_roles(["ClientApprover"])
    auth = get_authorization(authorization_id)
    _scope_check_client_approver(user_id, auth)
    ensure_transition(auth, {"REQUESTED"}, "authorizations", "PaymentAuthorization")
    ob = dbmod.DB["obligations"][auth["annuity_obligation_id"]]
    if ob["status"] != "PENDING_AUTHORIZATION":
        raise_err(ERR_INVALID_STATE, "Obligation is not PENDING_AUTHORIZATION")
    family = family_of_obligation(ob)
    committed_after = family["committed_forecast_cents"] + auth["amount_cents"]
    if committed_after > family["budget_cap_cents"]:
        raise_err(ERR_FAMILY_BUDGET_EXCEEDED, "Approval would exceed the family budget cap")
    auth["decided_by_user_id"] = user_id
    auth["status"] = "APPROVED"
    bump(auth)
    ob["status"] = "AUTHORIZED"
    ob["authorized_amount_cents"] = auth["amount_cents"]
    bump(ob)
    family["committed_forecast_cents"] += auth["amount_cents"]
    bump(family)
    return success_object(serialize.authorization(auth))


@bp.post("/authorizations/<authorization_id>/reject")
def reject_authorization(authorization_id):
    user_id, _ = require_roles(["ClientApprover"])
    auth = get_authorization(authorization_id)
    _scope_check_client_approver(user_id, auth)
    ensure_transition(auth, {"REQUESTED"}, "authorizations", "PaymentAuthorization")
    ob = dbmod.DB["obligations"][auth["annuity_obligation_id"]]
    auth["decided_by_user_id"] = user_id
    auth["status"] = "REJECTED"
    bump(auth)
    ob["status"] = "SCHEDULED"
    bump(ob)
    return success_object(serialize.authorization(auth))


@bp.post("/authorizations/<authorization_id>/release")
def release_authorization(authorization_id):
    require_roles(["FinanceOfficer"])
    auth = get_authorization(authorization_id)
    ensure_transition(auth, {"APPROVED"}, "authorizations", "PaymentAuthorization")
    auth["status"] = "RELEASED"
    bump(auth)
    return success_object(serialize.authorization(auth))
