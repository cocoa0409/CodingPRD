"""ShareholderAccount endpoints (PRD §3.2/§3.3)."""

from __future__ import annotations

import secrets

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_DUPLICATE_ACCOUNT_NUMBER,
    ERR_FORBIDDEN,
    ERR_INVALID_MEETING_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_bool,
    optional_enum,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("accounts", __name__)

SHARE_CLASSES = {"COMMON", "PREFERRED"}
DELIVERY_PREFERENCES = {"NOTICE_AND_ACCESS", "FULL_MAIL", "E_DELIVERY"}

# States from MEETING_HELD onward (plus CANCELLED) reject delivery-preference
# updates (PRD §3.3: "at any time before the meeting reaches MEETING_HELD").
_PREFERENCE_UPDATE_BLOCKED = {"MEETING_HELD", "RESULTS_CERTIFIED", "FILED_8K", "CANCELLED"}


def get_account_or_404(account_id: str) -> dict:
    account = db.accounts.get(account_id)
    if account is None:
        raise_err(ERR_ACCOUNT_NOT_FOUND, "ShareholderAccount id does not exist")
    return account


def _mint_control_number() -> str:
    # System-minted 12-digit control number (leading digit non-zero).
    return f"{100_000_000_000 + secrets.randbelow(900_000_000_000):012d}"


@bp.route("/proxy/shareholder-accounts", methods=["POST"])
@require_roles("TransferAgent")
def create_account(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    if meeting["status"] != "DRAFT":
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Shareholder accounts may only be added while the meeting is DRAFT",
        )

    account_number = require_string(body, "account_number")
    if any(
        a["meeting_id"] == meeting_id and a["account_number"] == account_number
        for a in db.accounts.values()
    ):
        raise_err(
            ERR_DUPLICATE_ACCOUNT_NUMBER,
            "account_number already exists within the meeting",
        )

    holder_name = require_string(body, "holder_name")
    share_class = require_enum(body, "share_class", SHARE_CLASSES)
    shares_held = require_int(body, "shares_held")
    if shares_held <= 0:
        raise_err(ERR_INVALID_REQUEST, "shares_held must be > 0")
    address_key = optional_string(body, "address_key")
    email = optional_string(body, "email")
    delivery_preference = optional_enum(
        body, "delivery_preference", DELIVERY_PREFERENCES, "NOTICE_AND_ACCESS"
    )
    householding_opt_out = optional_bool(body, "householding_opt_out", False)

    account = {
        "meeting_id": meeting_id,
        "holder_name": holder_name,
        "account_number": account_number,
        "share_class": share_class,
        "shares_held": shares_held,
        "address_key": address_key,
        "email": email,
        "delivery_preference": delivery_preference,
        "householding_opt_out": householding_opt_out,
        "control_number": _mint_control_number(),
        "status": "PENDING",
    }
    db.stamp_new(account)
    db.accounts[account["id"]] = account
    return success_object(serialize(account), 201)


@bp.route("/proxy/shareholder-accounts", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_accounts(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.accounts.values()))
    items = apply_filters(items, ["meeting_id", "status", "delivery_preference"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/shareholder-accounts/<account_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Shareholder")
def get_account(account_id: str, _user_id: str, _role: str):
    account = get_account_or_404(account_id)
    if _role == "Shareholder" and account["id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may read only its own account record")
    return success_object(serialize(account))


@bp.route("/proxy/shareholder-accounts/<account_id>", methods=["PATCH"])
@require_roles("Shareholder", "TransferAgent")
def update_account(account_id: str, _user_id: str, _role: str):
    account = get_account_or_404(account_id)
    if _role == "Shareholder" and account["id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may update only its own account record")
    meeting = db.meetings.get(account["meeting_id"])
    if meeting is not None and meeting["status"] in _PREFERENCE_UPDATE_BLOCKED:
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Delivery preferences cannot change once the meeting has reached MEETING_HELD",
        )
    body = get_json_body()
    delivery_preference = optional_enum(body, "delivery_preference", DELIVERY_PREFERENCES)
    householding_opt_out = optional_bool(body, "householding_opt_out")
    if delivery_preference is not None:
        account["delivery_preference"] = delivery_preference
    if householding_opt_out is not None:
        account["householding_opt_out"] = householding_opt_out
    db.touch(account)
    return success_object(serialize(account))
