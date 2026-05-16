"""ParentAccount endpoints. PRD §3.1, §3.6."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock, touch
from core.validation import (
    require_body, require_field, optional_field, check_version,
)

from services.relationships import (
    get_district_or_404, get_parent_account_in_district,
)
from services.ledger import (
    append_ledger_entry, find_charge_for_serving, find_refund_for_serving,
)
from services.views import parent_account_view


bp = Blueprint("parent_accounts", __name__)


@bp.post("/districts/<district_id>/parent-accounts")
@require_roles("AuditOfficer")
def create_parent_account(district_id):
    with lock():
        district = get_district_or_404(district_id)
        body = require_body(request)
        parent_email = require_field(body, "parent_email", kind="string")
        # Uniqueness on (district_id, parent_email)
        for pa in STORE.parent_accounts.values():
            if pa["district_id"] == district_id and pa["parent_email"] == parent_email:
                raise_error("ERR_PARENT_EMAIL_TAKEN",
                            f"parent_email '{parent_email}' is already used in this district")
        pa = {
            "district_id": district_id,
            "parent_email": parent_email,
        }
        stamp_common(pa)
        STORE.parent_accounts[pa["id"]] = pa
        return success_object(parent_account_view(pa), status=201)


@bp.get("/districts/<district_id>/parent-accounts/<account_id>")
@require_roles("Parent", "AuditOfficer")
def get_parent_account(district_id, account_id):
    with lock():
        get_district_or_404(district_id)
        pa = get_parent_account_in_district(district_id, account_id)
        # Parent ownership: parents may only read their own account.
        if g.user_role == "Parent" and g.user_id != account_id:
            raise_error("ERR_FORBIDDEN", "Parent may only read their own account")
        return success_object(parent_account_view(pa))


@bp.post("/districts/<district_id>/parent-accounts/<account_id>/top-up")
@require_roles("Parent")
def top_up(district_id, account_id):
    with lock():
        get_district_or_404(district_id)
        pa = get_parent_account_in_district(district_id, account_id)
        if g.user_id != account_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only top up their own account")
        body = require_body(request)
        check_version(body, pa)
        amount = require_field(body, "amount_cents", kind="positive_int")
        append_ledger_entry(account_id, "TOP_UP", amount, None)
        touch(pa)
        return success_object(parent_account_view(pa))


@bp.post("/districts/<district_id>/parent-accounts/<account_id>/refund")
@require_roles("AuditOfficer")
def refund(district_id, account_id):
    with lock():
        get_district_or_404(district_id)
        pa = get_parent_account_in_district(district_id, account_id)
        body = require_body(request)
        check_version(body, pa)
        serving_record_id = require_field(body, "serving_record_id", kind="string")
        charge = find_charge_for_serving(account_id, serving_record_id)
        if charge is None:
            # No linked CHARGE → cannot refund.
            raise_error("ERR_REFUND_MISMATCH",
                        "No CHARGE entry on this ParentAccount for the named serving_record_id")
        # Partial refunds rejected — also disallow double-refund.
        existing_refund = find_refund_for_serving(account_id, serving_record_id)
        if existing_refund is not None:
            raise_error("ERR_REFUND_MISMATCH",
                        "A REFUND for this serving_record_id has already been issued")
        append_ledger_entry(account_id, "REFUND", charge["amount_cents"], serving_record_id)
        touch(pa)
        return success_object(parent_account_view(pa))
