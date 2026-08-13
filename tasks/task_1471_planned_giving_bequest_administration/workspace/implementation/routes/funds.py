"""Donor-intent funds: create, list, read, lifecycle transitions (PRD 3.8)."""
from flask import Blueprint

import store
from calc import DEFAULT_MIN_ENDOWMENT_CENTS
from domain import RESTRICTIONS, lookup, matches, paginate, sort_created, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import get_body, validate_body

bp = Blueprint("funds", __name__)

ACTIONS = ("ACTIVATE", "FREEZE", "UNFREEZE", "CLOSE")


@bp.post("/giving/funds")
@require_roles("FinanceSteward")
def create_fund():
    body = get_body()
    validate_body(
        body,
        {
            "name": ("str", True, None),
            "restriction_type": ("str", True, RESTRICTIONS),
            "gift_agreement_id": ("str", True, None),
            "minimum_endowment_cents": ("int", False, None),
        },
    )
    agreement = lookup(store.agreements, body["gift_agreement_id"], "GiftAgreement")
    # at most one non-CLOSED fund per agreement
    if any(
        f["gift_agreement_id"] == agreement["id"] and f["status"] != "CLOSED"
        for f in store.funds.values()
    ):
        raise ApiError(
            "ERR_FUND_ALREADY_EXISTS",
            409,
            "A non-CLOSED fund already exists for this agreement",
        )
    fund = base_fields()
    fund.update(
        {
            "name": body["name"],
            "restriction_type": body["restriction_type"],
            "minimum_endowment_cents": body.get(
                "minimum_endowment_cents", DEFAULT_MIN_ENDOWMENT_CENTS
            ),
            "gift_agreement_id": agreement["id"],
            "balance_cents": 0,
            "status": "PROPOSED",
        }
    )
    store.funds[fund["id"]] = fund
    return success(view(fund), 201)


@bp.get("/giving/funds")
@require_roles(*ALL_ROLES)
def list_funds():
    items = [
        f
        for f in sort_created(store.funds.values())
        if matches(
            f, {"gift_agreement_id": None, "restriction_type": None, "status": None}
        )
    ]
    page, meta = paginate(items)
    return success([view(f) for f in page], 200, meta)


@bp.get("/giving/funds/<fund_id>")
@require_roles(*ALL_ROLES)
def get_fund(fund_id):
    return success(view(lookup(store.funds, fund_id, "Fund")), 200)


@bp.post("/giving/funds/<fund_id>/transition")
@require_roles("FinanceSteward")
def fund_transition(fund_id):
    fund = lookup(store.funds, fund_id, "Fund")
    body = get_body()
    validate_body(body, {"action": ("str", True, ACTIONS)})
    action = body["action"]
    status = fund["status"]

    if action == "ACTIVATE":
        if status not in ("PROPOSED", "ENDOWED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot ACTIVATE from %s" % status
            )
        if fund["balance_cents"] < fund["minimum_endowment_cents"]:
            raise ApiError(
                "ERR_FUND_MINIMUM_NOT_MET",
                409,
                "Balance is below the endowment minimum",
            )
        fund["status"] = "ACTIVE"
    elif action == "FREEZE":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot FREEZE from %s" % status)
        fund["status"] = "FROZEN"
    elif action == "UNFREEZE":
        if status != "FROZEN":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Cannot UNFREEZE from %s" % status
            )
        fund["status"] = "ACTIVE"
    else:  # CLOSE
        if status != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot CLOSE from %s" % status)
        fund["status"] = "CLOSED"

    touch(fund)
    return success(view(fund), 200)
