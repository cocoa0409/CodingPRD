"""TradelineItem routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import current_principal, require_auth
from ..calculations import PAYMENT_SCORES, recompute_fico_on_report
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, store
from ..utils import parse_json_body, require_field


bp_tradeline_items = Blueprint("tradeline_items", __name__)

VALID_PAYMENT_STATUSES = set(PAYMENT_SCORES.keys()) | {"DELETED"}


def _ensure_credit_report(credit_report_id: str) -> dict:
    report = store.credit_reports.get(credit_report_id)
    if report is None:
        raise ApiError("ERR_NOT_FOUND", "CreditReport not found.", 404)
    return report


def _ensure_furnisher(furnisher_id: str) -> dict:
    furnisher = store.furnishers.get(furnisher_id)
    if furnisher is None:
        raise ApiError("ERR_NOT_FOUND", "Furnisher not found.", 404)
    return furnisher


@bp_tradeline_items.route(
    "/credit_reports/<credit_report_id>/tradeline_items", methods=["POST"]
)
@require_auth(["PlatformAdmin", "Furnisher"])
def create_tradeline(credit_report_id: str):
    report = _ensure_credit_report(credit_report_id)
    body = parse_json_body()
    furnisher_id = require_field(body, "furnisher_id", types=[str])
    account_ref = require_field(body, "account_ref", types=[str])
    original_dofd_day = require_field(body, "original_dofd_day", types=[int])
    balance_cents = require_field(body, "balance_cents", types=[int])
    payment_status = require_field(body, "payment_status", types=[str])

    if isinstance(original_dofd_day, bool) or original_dofd_day < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "original_dofd_day must be a non-negative integer.", 400
        )
    if isinstance(balance_cents, bool) or balance_cents < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "balance_cents must be a non-negative integer.", 400
        )
    if payment_status not in VALID_PAYMENT_STATUSES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"payment_status must be one of {sorted(VALID_PAYMENT_STATUSES)}.",
            400,
        )

    _ensure_furnisher(furnisher_id)

    # Furnisher ownership: a Furnisher caller can only seed tradelines for themselves.
    user_id, user_role = current_principal()
    if user_role == "Furnisher" and user_id != furnisher_id:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Furnisher may only seed tradelines for themselves.",
            403,
        )

    with store.lock:
        # Uniqueness: (credit_report_id, furnisher_id, account_ref).
        for existing in store.tradeline_items.values():
            if (
                existing["credit_report_id"] == credit_report_id
                and existing["furnisher_id"] == furnisher_id
                and existing["account_ref"] == account_ref
            ):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "account_ref must be unique per (credit_report_id, furnisher_id).",
                    400,
                )
        item = stamp_create(
            {
                "credit_report_id": credit_report_id,
                "furnisher_id": furnisher_id,
                "account_ref": account_ref,
                "original_dofd_day": original_dofd_day,
                "reported_dofd_day": original_dofd_day,
                "balance_cents": balance_cents,
                "payment_status": payment_status,
                "verification_status": "UNVERIFIED",
            }
        )
        store.tradeline_items[item["id"]] = item
        recompute_fico_on_report(credit_report_id)

    # Re-read the report's possibly bumped data not needed in response.
    return json_object(item, 201)


@bp_tradeline_items.route(
    "/credit_reports/<credit_report_id>/tradeline_items/<tradeline_item_id>",
    methods=["GET"],
)
@require_auth(["Consumer", "PlatformAdmin", "BureauOperator", "Furnisher"])
def get_tradeline(credit_report_id: str, tradeline_item_id: str):
    report = _ensure_credit_report(credit_report_id)
    item = store.tradeline_items.get(tradeline_item_id)
    if item is None or item["credit_report_id"] != credit_report_id:
        raise ApiError("ERR_NOT_FOUND", "TradelineItem not found.", 404)
    user_id, user_role = current_principal()
    if user_role == "Consumer" and user_id != report["consumer_id"]:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Consumer may only view tradelines on their own reports.",
            403,
        )
    if user_role == "Furnisher" and user_id != item["furnisher_id"]:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Furnisher may only view their own tradeline rows.",
            403,
        )
    return json_object(item, 200)
