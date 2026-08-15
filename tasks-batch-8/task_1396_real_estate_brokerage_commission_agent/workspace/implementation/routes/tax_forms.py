"""1099 tax form routes (PRD §3.9)."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_TAX_YEAR_INVALID,
    ERR_TAX_FORM_FINALIZED_EXISTS, ERR_TAX_FORM_INVALID_STATE,
)
from middleware import body, forbid_unless_owner, parse_enum_filter, \
    parse_str_filter, parse_int_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.common import new_id, stamp_new, touch
from services.tax import compute_totals

bp = Blueprint("tax_forms", __name__)

TAX_FORM_STATUSES = {"DRAFT", "FINALIZED", "VOIDED"}


def _get_form(form_id):
    f = db.tax_forms.get(form_id)
    if f is None:
        raise ApiError(ERR_NOT_FOUND, 404, "tax form not found")
    return f


@bp.route("/brokerage/agents/<agentId>/tax-forms", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def generate_form(user_id, role, agentId):
    agent = db.agents.get(agentId)
    if agent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "agent not found")
    data = body()
    tax_year = data.get("tax_year")
    if not isinstance(tax_year, int) or isinstance(tax_year, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "tax_year is required and must be an integer")

    # Tax-year bounds: >= join year and <= clock year
    if tax_year < agent["_joined_date"].year or tax_year > db.clock_date().year:
        raise ApiError(ERR_TAX_YEAR_INVALID, 422,
                       "tax_year must be within [join year, clock year]")

    # A FINALIZED (non-VOIDED) form for the same pair blocks regeneration
    existing_draft = None
    for f in db.tax_forms.values():
        if f["agent_id"] != agentId or f["tax_year"] != tax_year:
            continue
        if f["status"] == "FINALIZED":
            raise ApiError(ERR_TAX_FORM_FINALIZED_EXISTS, 409,
                           "a FINALIZED form exists for this agent and tax_year")
        if f["status"] == "DRAFT":
            existing_draft = f

    # An existing DRAFT is superseded (VOIDED) and replaced
    if existing_draft is not None:
        existing_draft["status"] = "VOIDED"
        touch(existing_draft)

    totals = compute_totals(agentId, tax_year)
    form = {
        "id": new_id(),
        "agent_id": agentId,
        "tax_year": tax_year,
        **totals,
        "status": "DRAFT",
    }
    stamp_new(form)
    db.tax_forms[form["id"]] = form
    return success_obj(public(form), status=201)


@bp.route("/brokerage/tax-forms/<taxFormId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_form(user_id, role, taxFormId):
    f = _get_form(taxFormId)
    forbid_unless_owner(role, user_id, f["agent_id"])
    return success_obj(public(f))


@bp.route("/brokerage/tax-forms", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_forms(user_id, role):
    agent_id = parse_str_filter("agent_id")
    tax_year = parse_int_filter("tax_year")
    status = parse_enum_filter("status", TAX_FORM_STATUSES)
    items = list(db.tax_forms.values())
    if role == "Agent":
        items = [f for f in items if f["agent_id"] == user_id]
    if agent_id is not None:
        items = [f for f in items if f["agent_id"] == agent_id]
    if tax_year is not None:
        items = [f for f in items if f["tax_year"] == tax_year]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return list_response(by_created(items))


@bp.route("/brokerage/tax-forms/<taxFormId>/finalize", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def finalize_form(user_id, role, taxFormId):
    f = _get_form(taxFormId)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_TAX_FORM_INVALID_STATE, 409, "only a DRAFT form can be finalized")
    f["status"] = "FINALIZED"
    touch(f)
    return success_obj(public(f))


@bp.route("/brokerage/tax-forms/<taxFormId>/void", methods=["POST"])
@guard(roles=["BrokerAdmin"])
def void_form(user_id, role, taxFormId):
    f = _get_form(taxFormId)
    if f["status"] not in ("DRAFT", "FINALIZED"):
        raise ApiError(ERR_TAX_FORM_INVALID_STATE, 409,
                       "only a DRAFT or FINALIZED form can be voided")
    f["status"] = "VOIDED"
    touch(f)
    return success_obj(public(f))
