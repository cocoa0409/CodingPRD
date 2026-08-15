"""DepositAccount endpoints (PRD §3.1, §3.9; SCAFFOLD §1.5)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CLOSURE_BLOCKED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import (
    paginate,
    parse_pagination,
    success_list,
    success_object,
)
from serialization import account_view
from services import account as acct_svc
from services.account import (
    DEST_OWNER,
    OWNERSHIP_TYPES,
    PRODUCT_CODES,
    closure_cascade,
    get_account_or_404,
    post_transaction,
    settle_interest_txn,
    touch_account,
)
from services.interest import rounding_variant_for_product

bp = Blueprint("accounts", __name__)


def _require_string(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required")
    return value


def _require_rate(value, field="rate_bps"):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if value < 0 or value > 2000:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be between 0 and 2000 inclusive")
    return value


def _check_pod_beneficiary(body, ownership_type):
    """pod_beneficiary_name is present exactly when the type in play is POD (PRD §2.10.4)."""
    beneficiary = body.get("pod_beneficiary_name")
    if ownership_type == "POD":
        if not isinstance(beneficiary, str) or not beneficiary.strip():
            raise ApiError(
                ERR_INVALID_REQUEST,
                "pod_beneficiary_name is required when ownership_type is POD",
            )
        return beneficiary.strip()
    if beneficiary is not None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "pod_beneficiary_name is only allowed when ownership_type is POD",
        )
    return None


@bp.post("/bank/accounts")
def open_account():
    require_roles(["OpsOfficer", "OpsManager"])
    body = request.get_json(silent=True) or {}

    primary_owner_name = _require_string(body, "primary_owner_name")
    owner_tax_id = _require_string(body, "owner_tax_id")
    ownership_type = body.get("ownership_type")
    if ownership_type not in OWNERSHIP_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "ownership_type must be a declared member")
    product_code = body.get("product_code")
    if product_code not in PRODUCT_CODES:
        raise ApiError(ERR_INVALID_REQUEST, "product_code must be a declared member")
    rate_bps = _require_rate(body.get("rate_bps"))
    opening = body.get("opening_deposit_cents")
    if not isinstance(opening, int) or isinstance(opening, bool) or opening <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "opening_deposit_cents must be a positive integer")
    pod_beneficiary_name = _check_pod_beneficiary(body, ownership_type)

    clock_date = db.clock_date_str()
    acct = {
        "id": db.new_uuid(),
        "account_number": db.mint_account_number(),
        "primary_owner_name": primary_owner_name,
        "owner_tax_id": owner_tax_id,
        "ownership_type": ownership_type,
        "pod_beneficiary_name": pod_beneficiary_name,
        "product_code": product_code,
        "rate_bps": rate_bps,
        "lifecycle_status": "OPEN",
        "restriction_status": "NONE",
        "balance_cents": 0,
        "accrual_start_date": clock_date,
        "accrued_interest_cents": 0,
        "last_customer_activity_date": clock_date,
        "dormant_since_date": None,
        "fees_assessed_count": 0,
        "statement_suppression": "NONE",
        "closure_payout_cents": None,
        "closure_payout_destination": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.accounts[acct["id"]] = acct
    # Opening deposit posts as a customer-initiated DEPOSIT (PRD §3.1).
    post_transaction(acct, "DEPOSIT", opening, True, clock_date)
    return success_object(account_view(acct), status=201)


@bp.get("/bank/accounts")
def list_accounts():
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    ownership_type = request.args.get("ownership_type")

    items = sorted(db.accounts.values(), key=lambda a: a["_seq"])
    if status is not None:
        items = [
            a for a in items
            if a["lifecycle_status"] == status or a["restriction_status"] == status
        ]
    if ownership_type is not None:
        items = [a for a in items if a["ownership_type"] == ownership_type]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([account_view(a) for a in page], total, limit, offset)


@bp.get("/bank/accounts/<account_id>")
def get_account(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    acct = get_account_or_404(account_id)
    return success_object(account_view(acct))


@bp.post("/bank/accounts/<account_id>/close")
def close_account(account_id):
    require_roles(["OpsOfficer", "OpsManager"])
    acct = get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    expected = body.get("expected_account_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_account_version is required")

    # Tier 5: state, then OCC (PRD §2.10).
    if acct["lifecycle_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "Account is already CLOSED")
    if expected != acct["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_account_version does not match the current version")

    # Tier 6: closure gates (PRD §3.9).
    blocked = acct["restriction_status"] != "NONE"
    blocked = blocked or any(
        g["account_id"] == account_id and g["status"] == "FUNDS_HELD"
        for g in db.garnishments.values()
    )
    blocked = blocked or any(
        c["account_id"] == account_id and c["status"] in ("REPORTED", "VERIFIED", "RELEASE_PENDING")
        for c in db.deceased_cases.values()
    )
    blocked = blocked or any(
        r["account_id"] == account_id and r["status"] == "SUBMITTED"
        for r in db.title_changes.values()
    )
    if blocked:
        raise ApiError(ERR_CLOSURE_BLOCKED, "Closure is blocked by in-flight legal or transitional work")

    close_date = db.clock_date_str()
    settled = settle_interest_txn(
        acct, close_date, rounding_variant_for_product(acct["product_code"])
    )
    payout = acct["balance_cents"]  # pre-close balance + settled interest
    if payout > 0:
        post_transaction(acct, "CLOSURE_PAYOUT", payout, False, close_date)
    acct["lifecycle_status"] = "CLOSED"
    acct["closure_payout_cents"] = payout
    acct["closure_payout_destination"] = DEST_OWNER
    closure_cascade(acct, close_date, "ACCOUNT_CLOSED")
    touch_account(acct)
    return success_object(account_view(acct))
