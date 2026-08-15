"""Service credits: list/get + apply/expire with contract counter identity."""

from datetime import datetime, timezone

from flask import Blueprint, request

from auth import require_roles, check_ownership, owning_facility_id
from envelope import ok_object, ok_list
from errors import conflict, invalid_state, not_found, ERR_CREDIT_NOT_EXPIRED
import store
from store import touch
from util import parse_pagination, public, sort_and_page

bp = Blueprint("credits", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(credit_id):
    credit = store.service_credits.get(credit_id)
    if credit is None:
        raise not_found("ServiceCredit not found")
    return credit


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


@bp.route("/service-credits", methods=["GET"])
def list_credits():
    require_roles(ALL_ROLES)
    items = list(store.service_credits.values())
    for param in ("contract_id", "ticket_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(c) for c in page], limit, offset, total)


@bp.route("/service-credits/<serviceCreditId>", methods=["GET"])
def get_credit(serviceCreditId):
    user_id, role = require_roles(ALL_ROLES)
    credit = _get_or_404(serviceCreditId)
    check_ownership(user_id, role, owning_facility_id("service_credit", credit))
    return ok_object(public(credit), 200)


@bp.route("/service-credits/<serviceCreditId>/apply", methods=["POST"])
def apply_credit(serviceCreditId):
    require_roles(["ContractManager"])
    credit = _get_or_404(serviceCreditId)
    if credit["status"] != "ACCRUED":
        raise invalid_state("ServiceCredit must be ACCRUED to apply")
    credit["status"] = "APPLIED"
    touch(credit)
    contract = store.service_contracts.get(credit["contract_id"])
    if contract is not None:
        contract["credits_outstanding_cents"] -= credit["amount_cents"]
        contract["credits_applied_total_cents"] += credit["amount_cents"]
        touch(contract)
    return ok_object(public(credit), 200)


@bp.route("/service-credits/<serviceCreditId>/expire", methods=["POST"])
def expire_credit(serviceCreditId):
    require_roles(["ContractManager"])
    credit = _get_or_404(serviceCreditId)
    if credit["status"] != "ACCRUED":
        raise invalid_state("ServiceCredit must be ACCRUED to expire")
    # inclusive: exactly at expires_at counts
    if store.get_clock() < _parse_iso(credit["expires_at"]):
        raise conflict(ERR_CREDIT_NOT_EXPIRED, "Logical clock has not reached expires_at")
    credit["status"] = "EXPIRED"
    touch(credit)
    contract = store.service_contracts.get(credit["contract_id"])
    if contract is not None:
        contract["credits_outstanding_cents"] -= credit["amount_cents"]
        contract["credits_expired_total_cents"] += credit["amount_cents"]
        touch(contract)
    return ok_object(public(credit), 200)
