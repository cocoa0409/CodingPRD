"""NamedInsuredInterest endpoints (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint

import lookup
from db import by_policy, new_row, store, touch
from enums import PARTY_ROLES
from errors import ApiError
from middleware import authenticate, body, get_int, get_number, get_str, get_enum, present
from response import created, ok
from util import dec

bp = Blueprint("interests", __name__)

EDITABLE_POLICY_STATUSES = ("DRAFT", "REFERRED")
ACKNOWLEDGEABLE_POLICY_STATUSES = ("DRAFT", "REFERRED", "QUOTED")


def owned_interest(interest, user_id, role):
    """LossPayee identity is entity-backed: X-User-ID is the interest's own id."""
    if role == "LossPayee" and interest["id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This interest does not belong to the caller.")


@bp.post("/named-insured-interests")
def add_interest():
    authenticate("Underwriter")
    payload = body()
    policy = lookup.fk_policy(payload)
    party_name = get_str(payload, "party_name")
    party_role = get_enum(payload, "party_role", PARTY_ROLES)
    pct = get_number(
        payload, "insurable_interest_pct", minimum=0, maximum=100, max_decimals=2
    )
    priority = get_int(payload, "loss_payee_priority", required=False, minimum=1)
    if party_role == "LENDER":
        if pct != Decimal("0"):
            raise ApiError(
                "ERR_INVALID_REQUEST", "insurable_interest_pct must be 0 for a LENDER interest."
            )
        if priority is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "loss_payee_priority is required for a LENDER interest."
            )
    if policy["status"] not in EDITABLE_POLICY_STATUSES:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "The insured schedule is editable only while the policy is DRAFT or REFERRED.",
        )
    existing = by_policy(store.interests, policy["id"])
    pct_total = sum((dec(row["insurable_interest_pct"]) for row in existing), Decimal("0")) + pct
    if pct_total > Decimal("100"):
        raise ApiError(
            "ERR_INTEREST_PCT_EXCEEDED",
            "The insurable interest schedule may not exceed 100 percent in total.",
        )
    if priority is not None and any(row["loss_payee_priority"] == priority for row in existing):
        raise ApiError(
            "ERR_DUPLICATE_PAYEE_PRIORITY",
            "This loss_payee_priority is already taken on the policy.",
        )
    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "party_name": party_name,
        "party_role": party_role,
        "insurable_interest_pct": pct,
        "loss_payee_priority": priority,
        "acknowledgment_status": "PENDING",
        "acknowledged_at": None,
    })
    store.interests[row["id"]] = row
    touch(policy)
    return created(row)


@bp.post("/named-insured-interests/<interest_id>/acknowledge")
def acknowledge_interest(interest_id):
    user_id, role = authenticate("LossPayee")
    interest = lookup.interest(interest_id)
    owned_interest(interest, user_id, role)
    if interest["acknowledgment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_INTEREST_STATE", "This interest is already ACKNOWLEDGED.")
    policy = store.policies[interest["policy_id"]]
    if policy["status"] not in ACKNOWLEDGEABLE_POLICY_STATUSES:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "Acknowledgement happens before the risk attaches to the policy.",
        )
    interest["acknowledgment_status"] = "ACKNOWLEDGED"
    interest["acknowledged_at"] = store.now()
    touch(interest)
    return ok(interest)


@bp.get("/named-insured-interests/<interest_id>")
def read_interest(interest_id):
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "ClaimAdjuster", "LossPayee"
    )
    interest = lookup.interest(interest_id)
    owned_interest(interest, user_id, role)
    return ok(interest)
