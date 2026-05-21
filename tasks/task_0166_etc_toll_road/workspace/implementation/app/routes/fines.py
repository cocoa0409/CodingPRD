"""Fine retrieval, payment, and dispute endpoints."""
from flask import Blueprint, request

from ..auth import require_roles
from ..errors import raise_api_error
from ..responses import paginate, parse_pagination, success_array, success_object
from ..serializers import serialize_fine
from ..services.accounts_svc import recompute_outstanding_and_cascade, restore_vehicle_if_escalated
from ..store import store
from ..validators import optional_str, require_json, require_str


fines_bp = Blueprint("fines", __name__)


def _violation_of(fine: dict):
    return store.violations.get(fine.get("violation_id"))


def _account_of(fine: dict):
    v = _violation_of(fine)
    if v is None or not v.get("account_id"):
        return None
    return store.accounts.get(v["account_id"])


def _enforce_ownership(fine: dict) -> None:
    role = getattr(request, "caller_role", None)
    caller_id = getattr(request, "caller_id", None)
    if role == "AccountHolder":
        violation = _violation_of(fine)
        if violation is None or violation.get("account_id") != caller_id:
            raise_api_error("ERR_FORBIDDEN")


@fines_bp.route("/fines/<fine_id>", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def get_fine(fine_id: str):
    fine = store.fines.get(fine_id)
    if fine is None:
        raise_api_error("ERR_NOT_FOUND")
    _enforce_ownership(fine)
    return success_object(serialize_fine(fine))


@fines_bp.route("/fines", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def list_fines():
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    settlement_status = request.args.get("settlement_status")

    role = getattr(request, "caller_role", None)
    caller_id = getattr(request, "caller_id", None)
    if role == "AccountHolder":
        if account_id is None:
            account_id = caller_id
        elif account_id != caller_id:
            raise_api_error("ERR_FORBIDDEN")

    rows = []
    for f in store.fines.values():
        v = _violation_of(f)
        if v is None:
            continue
        if account_id and v.get("account_id") != account_id:
            continue
        if settlement_status and f["settlement_status"] != settlement_status:
            continue
        rows.append(f)
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_fine(r) for r in page], limit, offset, total)


@fines_bp.route("/fines/<fine_id>/pay", methods=["POST"])
@require_roles("AccountHolder")
def pay_fine(fine_id: str):
    fine = store.fines.get(fine_id)
    if fine is None:
        raise_api_error("ERR_NOT_FOUND")
    _enforce_ownership(fine)
    payload = require_json(request.get_json(silent=True))
    _ = require_str(payload, "payment_method_token", min_len=1, max_len=256)

    with store.lock:
        # account must be ACTIVE per validation priority #6
        violation = _violation_of(fine)
        account = _account_of(fine)
        if account is not None and account["status"] != "ACTIVE":
            raise_api_error("ERR_ACCOUNT_NOT_ACTIVE")
        if fine["settlement_status"] not in ("PENDING", "OVERDUE"):
            raise_api_error("ERR_INVALID_STATE")

        fine["settlement_status"] = "SETTLED"
        store.bump(fine)
        if violation:
            was_escalated = violation["status"] == "ESCALATED"
            violation["status"] = "CLEARED"
            store.bump(violation)
            if was_escalated and violation.get("vehicle_id"):
                restore_vehicle_if_escalated(violation["vehicle_id"])
        if account:
            recompute_outstanding_and_cascade(account["id"])
        return success_object(serialize_fine(fine))


@fines_bp.route("/fines/<fine_id>/dispute", methods=["POST"])
@require_roles("AccountHolder")
def dispute_fine(fine_id: str):
    fine = store.fines.get(fine_id)
    if fine is None:
        raise_api_error("ERR_NOT_FOUND")
    _enforce_ownership(fine)
    payload = require_json(request.get_json(silent=True))
    _ = require_str(payload, "reason", min_len=1, max_len=1024)

    with store.lock:
        if fine["settlement_status"] != "PENDING":
            raise_api_error("ERR_INVALID_STATE")
        if fine["dispute_count"] >= 2:
            raise_api_error("ERR_DISPUTE_LIMIT_REACHED")
        fine["settlement_status"] = "DISPUTED"
        fine["dispute_count"] = int(fine["dispute_count"]) + 1
        store.bump(fine)
        account = _account_of(fine)
        if account:
            recompute_outstanding_and_cascade(account["id"])
        return success_object(serialize_fine(fine))


@fines_bp.route("/fines/<fine_id>/dispute/uphold", methods=["POST"])
@require_roles("AgencyAdmin")
def uphold_dispute(fine_id: str):
    fine = store.fines.get(fine_id)
    if fine is None:
        raise_api_error("ERR_NOT_FOUND")
    with store.lock:
        if fine["settlement_status"] != "DISPUTED":
            raise_api_error("ERR_INVALID_STATE")
        fine["settlement_status"] = "DISMISSED"
        store.bump(fine)
        violation = _violation_of(fine)
        if violation:
            was_escalated = violation["status"] == "ESCALATED"
            violation["status"] = "CLEARED"
            store.bump(violation)
            if was_escalated and violation.get("vehicle_id"):
                restore_vehicle_if_escalated(violation["vehicle_id"])
        account = _account_of(fine)
        if account:
            recompute_outstanding_and_cascade(account["id"])
        return success_object(serialize_fine(fine))


@fines_bp.route("/fines/<fine_id>/dispute/reject", methods=["POST"])
@require_roles("AgencyAdmin")
def reject_dispute(fine_id: str):
    fine = store.fines.get(fine_id)
    if fine is None:
        raise_api_error("ERR_NOT_FOUND")
    with store.lock:
        if fine["settlement_status"] != "DISPUTED":
            raise_api_error("ERR_INVALID_STATE")
        fine["settlement_status"] = "PENDING"
        store.bump(fine)
        account = _account_of(fine)
        if account:
            recompute_outstanding_and_cascade(account["id"])
        return success_object(serialize_fine(fine))
