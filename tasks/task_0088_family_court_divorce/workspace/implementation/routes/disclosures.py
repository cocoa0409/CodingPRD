"""FinancialDisclosure endpoints + state machine (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NEGATIVE_NET_INCOME,
    ERR_FORBIDDEN_ROLE,
)
from middleware import (
    require_auth,
    get_json_body,
    paginate_params,
    slice_page,
    current_role,
    current_user_id,
)
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    get_party,
    assert_case_not_terminal,
    recompute_disclosure_flags,
    require,
)
from services.calculations import net_disposable_income

bp = Blueprint("disclosures", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


@bp.post("/api/financial-disclosures")
def create_disclosure():
    require_auth(["Clerk", "Petitioner", "Respondent"])()
    body = get_json_body()

    party_id = body.get("party_id")
    party = get_party(party_id)  # 404 left-to-right (party first per input order)
    case_id = body.get("case_id")
    case = get_case(case_id)
    if party["case_id"] != case_id:
        raise APIError(ERR_INVALID_REQUEST, 422, "party_id not on this case")

    assert_case_not_terminal(case)

    for f in ("gross_monthly_income_cents", "tax_withholding_cents",
              "mandatory_retirement_cents", "health_insurance_cents"):
        v = body.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise APIError(ERR_INVALID_REQUEST, 422, f"{f} must be an integer >= 0")

    # Ownership for entity-backed roles.
    _check_party_ownership(party)

    disc = {
        "party_id": party_id,
        "case_id": case_id,
        "gross_monthly_income_cents": body["gross_monthly_income_cents"],
        "tax_withholding_cents": body["tax_withholding_cents"],
        "mandatory_retirement_cents": body["mandatory_retirement_cents"],
        "health_insurance_cents": body["health_insurance_cents"],
        "net_monthly_income_cents": None,
        "status": "DRAFT",
    }
    db.stamp_common(disc)
    db.financial_disclosures[disc["id"]] = disc
    return ok_object(serialize(disc), 201)


def _check_party_ownership(party):
    role = current_role()
    if role in ("Petitioner", "Respondent"):
        expected_role = "PETITIONER" if role == "Petitioner" else "RESPONDENT"
        if party["role"] != expected_role or party["user_id"] != current_user_id():
            raise APIError(ERR_FORBIDDEN_ROLE, 403, "Acting role does not own this party")


@bp.get("/api/financial-disclosures/<rid>")
def get_disclosure(rid):
    require_auth(READ_ROLES)()
    disc = require(db.financial_disclosures, rid, "FinancialDisclosure")
    return ok_object(serialize(disc), 200)


@bp.get("/api/financial-disclosures")
def list_disclosures():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.financial_disclosures.values()))
    party_id = request.args.get("party_id")
    case_id = request.args.get("case_id")
    if party_id is not None:
        items = [d for d in items if d["party_id"] == party_id]
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/api/financial-disclosures/<rid>/submit")
def submit_disclosure(rid):
    require_auth(["Petitioner", "Respondent"])()
    disc = require(db.financial_disclosures, rid, "FinancialDisclosure")
    party = get_party(disc["party_id"])

    # Ownership (entity-backed): acting party must own the disclosure.
    _check_party_ownership(party)

    if disc["status"] not in ("DRAFT", "RETURNED"):
        raise APIError(ERR_INVALID_STATE, 409, "Submit requires DRAFT or RETURNED")

    # Non-negative net (ERR_NEGATIVE_NET_INCOME).
    deductions = (
        disc["tax_withholding_cents"]
        + disc["mandatory_retirement_cents"]
        + disc["health_insurance_cents"]
    )
    if disc["gross_monthly_income_cents"] < deductions:
        raise APIError(ERR_NEGATIVE_NET_INCOME, 422, "Net income would be negative")

    disc["net_monthly_income_cents"] = net_disposable_income(disc)
    disc["status"] = "SUBMITTED"
    db.bump(disc)
    return ok_object(serialize(disc), 200)


@bp.post("/api/financial-disclosures/<rid>/verify")
def verify_disclosure(rid):
    require_auth(["Clerk"])()
    disc = require(db.financial_disclosures, rid, "FinancialDisclosure")
    case = get_case(disc["case_id"])

    if disc["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Verify requires SUBMITTED")
    # Owning case must be in one of these statuses.
    if case["status"] not in ("DISCOVERY", "MEDIATION", "DEFAULT_PENDING", "AWAITING_JUDGMENT"):
        raise APIError(ERR_INVALID_STATE, 409, "Case not in a verifiable status")

    disc["status"] = "VERIFIED"
    db.bump(disc)
    recompute_disclosure_flags(case)
    db.bump(case)
    return ok_object(serialize(disc), 200)


@bp.post("/api/financial-disclosures/<rid>/return")
def return_disclosure(rid):
    require_auth(["Clerk"])()
    disc = require(db.financial_disclosures, rid, "FinancialDisclosure")
    if disc["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Return requires SUBMITTED")
    disc["status"] = "RETURNED"
    db.bump(disc)
    return ok_object(serialize(disc), 200)
