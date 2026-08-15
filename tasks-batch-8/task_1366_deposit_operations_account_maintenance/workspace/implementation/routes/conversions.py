"""ProductConversion endpoints (PRD §3.7): schedule with a strictly-future
effective date; execute settles old-product interest then applies the new
product and rate.
"""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ACCOUNT_RESTRICTED,
    ERR_ACTIVE_REQUEST_EXISTS,
    ERR_CONVERSION_NOT_DUE,
    ERR_EFFECTIVE_DATE_NOT_FUTURE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import conversion_view
from services.account import (
    PRODUCT_CODES,
    get_account_or_404,
    post_transaction,
    touch_account,
    touch_resource,
)
from services.interest import accrued_interest, rounding_variant_for_product

bp = Blueprint("conversions", __name__)


@bp.post("/bank/accounts/<account_id>/conversions")
def schedule_conversion(account_id):
    require_roles(["OpsOfficer"])
    acct = get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    to_product = body.get("to_product_code")
    if to_product not in PRODUCT_CODES:
        raise ApiError(ERR_INVALID_REQUEST, "to_product_code must be a declared member")
    if to_product == acct["product_code"]:
        raise ApiError(ERR_INVALID_REQUEST, "to_product_code must differ from the current product")
    new_rate = body.get("new_rate_bps")
    if not isinstance(new_rate, int) or isinstance(new_rate, bool) or new_rate < 0 or new_rate > 2000:
        raise ApiError(ERR_INVALID_REQUEST, "new_rate_bps must be an integer between 0 and 2000 inclusive")
    eff_raw = body.get("effective_date")
    if not isinstance(eff_raw, str):
        raise ApiError(ERR_INVALID_REQUEST, "effective_date is required")
    try:
        effective = date.fromisoformat(eff_raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "effective_date must be a YYYY-MM-DD date")

    if any(
        c["account_id"] == account_id and c["status"] == "SCHEDULED"
        for c in db.conversions.values()
    ):
        raise ApiError(ERR_ACTIVE_REQUEST_EXISTS, "A SCHEDULED conversion already exists")

    # Clock-relative: the effective date must lie strictly after today.
    if effective <= db.clock_instant().date():
        raise ApiError(ERR_EFFECTIVE_DATE_NOT_FUTURE, "effective_date must be strictly after today")

    conv = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "from_product_code": acct["product_code"],
        "to_product_code": to_product,
        "new_rate_bps": new_rate,
        "effective_date": effective.isoformat(),
        "accrued_interest_settled_cents": None,
        "status": "SCHEDULED",
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.conversions[conv["id"]] = conv
    return success_object(conversion_view(conv), status=201)


@bp.post("/bank/conversions/<conversion_id>/execute")
def execute_conversion(conversion_id):
    require_roles(["OpsOfficer", "System"])
    conv = db.conversions.get(conversion_id)
    if conv is None:
        raise ApiError(ERR_NOT_FOUND, f"Conversion {conversion_id} does not exist")
    acct = get_account_or_404(conv["account_id"])

    if conv["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Only a SCHEDULED conversion can be executed")
    if acct["lifecycle_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "Account is CLOSED")
    if acct["restriction_status"] == "DECEASED_HOLD":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, "A deceased hold blocks conversion execution")
    if db.clock_instant().date() < date.fromisoformat(conv["effective_date"]):
        raise ApiError(ERR_CONVERSION_NOT_DUE, "The conversion is not yet due")

    # Settle the old regime under the OLD product's rounding variant (PRD §3.7).
    settled = accrued_interest(
        acct["id"], acct["accrual_start_date"], conv["effective_date"],
        acct["rate_bps"], rounding_variant_for_product(acct["product_code"]),
    )
    conv["accrued_interest_settled_cents"] = settled
    if settled > 0:
        post_transaction(acct, "INTEREST_CREDIT", settled, False, conv["effective_date"])

    acct["product_code"] = conv["to_product_code"]
    acct["rate_bps"] = conv["new_rate_bps"]
    acct["accrual_start_date"] = conv["effective_date"]
    acct["accrued_interest_cents"] = 0
    touch_account(acct)

    conv["status"] = "COMPLETED"
    touch_resource(conv)
    return success_object(conversion_view(conv))


@bp.get("/bank/accounts/<account_id>/conversions")
def list_conversions(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [c for c in db.conversions.values() if c["account_id"] == account_id]
    items.sort(key=lambda c: c["_seq"])
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([conversion_view(c) for c in page], total, limit, offset)
