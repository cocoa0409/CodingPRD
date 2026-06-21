"""Account lifecycle endpoints (PRD §3.2, §3.3, §3.10, §4)."""

from flask import Blueprint, request

import db
from middleware import get_identity, require_role
from response import object_response
from services import common
from services import accounts as acc_svc

bp = Blueprint("accounts", __name__)


@bp.route("/accounts", methods=["POST"])
def create_account():
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    body = common.get_json_body()
    customer_name = common.require_str(body, "customer_name")
    service_state_code = common.require_str(body, "service_state_code")
    contract_term_months = common.optional_int(body, "contract_term_months", 0, minimum=0)
    created_at, updated_at, version = db.stamp_new()
    rec = {
        "id": db.new_id(),
        "customer_name": customer_name,
        "service_state_code": service_state_code,
        "tenure_months": 0,
        "lifecycle_status": "PROSPECT",
        "promo_status": "NONE",
        "active_package_id": None,
        "contract_term_months": contract_term_months,
        "regional_sports_fee_cents": 0,
        "monthly_recurring_cents": 0,
        "cancellation_effective_cycle": None,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }
    db.accounts[rec["id"]] = rec
    return object_response(_view(rec), 201)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent"})
    items = list(db.accounts.values())
    lifecycle_status = request.args.get("lifecycle_status")
    if lifecycle_status is not None:
        items = [a for a in items if a["lifecycle_status"] == lifecycle_status]
    active_package_id = request.args.get("active_package_id")
    if active_package_id is not None:
        items = [a for a in items if a["active_package_id"] == active_package_id]
    return common.paginate_and_respond([_view(a) for a in items])


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = get_identity()
    require_role(role, {"BillingAdmin", "CustomerServiceAgent", "Subscriber"})
    acc = common.resolve_account(role, user_id, account_id)
    return object_response(_view(acc), 200)


@bp.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    acc = common.get_account_or_404(account_id)
    acc_svc.suspend(acc)
    return object_response(_view(acc), 200)


@bp.route("/accounts/<account_id>/reactivate", methods=["POST"])
def reactivate_account(account_id):
    _, role = get_identity()
    require_role(role, {"CustomerServiceAgent"})
    acc = common.get_account_or_404(account_id)
    acc_svc.reactivate(acc)
    return object_response(_view(acc), 200)


@bp.route("/accounts/<account_id>/cancel", methods=["POST"])
def cancel_account(account_id):
    user_id, role = get_identity()
    require_role(role, {"CustomerServiceAgent", "Subscriber"})
    acc = common.resolve_account(role, user_id, account_id)
    acc_svc.cancel(acc)
    return object_response(_view(acc), 200)


@bp.route("/accounts/<account_id>/advance-cycle", methods=["POST"])
def advance_cycle(account_id):
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    acc = common.get_account_or_404(account_id)
    acc_svc.advance_cycle(acc)
    return object_response(_view(acc), 200)


def _view(account):
    """Serialize an account, excluding internal-only bookkeeping fields."""
    out = {k: v for k, v in account.items() if k != "etf_tenure_at_cancel"}
    return out
