"""Token endpoints: read, list (serial_number ASC), redeem, reverse-redemption."""

from flask import Blueprint, request

from db import STORE, idem_marker
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MARKET_DAY_NOT_OPEN,
    ERR_TOKEN_ALREADY_REDEEMED,
    ERR_TOKEN_ALREADY_SUBMITTED,
    ERR_TOKEN_FLAGGED,
    ERR_TOKEN_NOT_MINTED,
    ERR_TOKEN_UNKNOWN_SERIAL,
    ERR_TOKEN_VENDOR_MISMATCH,
    ERR_TOKEN_VOID,
    ERR_VENDOR_NOT_ACTIVE,
)
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    get_body,
    idempotency_guard,
    paginate,
    req_int,
)
from response import success_list, success_object
from routes.common import get_path_entity, replay_response
from services.domain import (
    change_token_status,
    flag_token,
    market_day_of_issuance,
    open_auto_double_spend_case,
    serialize_token,
)

bp = Blueprint("tokens", __name__)

TOKEN_READ_ROLES = ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor", "Vendor"]


@bp.route("/tokens/<tid>", methods=["GET"])
def get_token(tid):
    authenticate(TOKEN_READ_ROLES)
    token = get_path_entity("tokens", tid)
    return success_object(serialize_token(token))


@bp.route("/tokens", methods=["GET"])
def list_tokens():
    authenticate(TOKEN_READ_ROLES)
    issuance_id = request.args.get("issuance_id")
    token_batch_id = request.args.get("token_batch_id")
    submission_id = request.args.get("submission_id")
    redeemed_vendor_id = request.args.get("redeemed_vendor_id")
    serial_number = request.args.get("serial_number")
    status_filter = request.args.get("status")
    items = list(STORE["tokens"].values())
    if issuance_id is not None:
        items = [t for t in items if t["issuance_id"] == issuance_id]
    if token_batch_id is not None:
        items = [t for t in items if t["token_batch_id"] == token_batch_id]
    if submission_id is not None:
        items = [t for t in items if t.get("submission_id") == submission_id]
    if redeemed_vendor_id is not None:
        items = [t for t in items if t.get("redeemed_vendor_id") == redeemed_vendor_id]
    if serial_number is not None:
        try:
            sn = int(serial_number)
            items = [t for t in items if t["serial_number"] == sn]
        except (TypeError, ValueError):
            items = []
    if status_filter is not None:
        items = [t for t in items if t["status"] == status_filter]
    # Standing exception (PRD §2.3): tokens ordered by serial_number ASC.
    page, limit, offset, total = paginate(
        items, sort_key=lambda t: (t["serial_number"], t["_seq"]))
    return success_list([serialize_token(t) for t in page], limit, offset, total)


def _serial_in_any_batch_range(serial):
    for batch in STORE["token_batches"].values():
        if batch["serial_start"] <= serial <= batch["serial_end"]:
            return True
    return False


@bp.route("/tokens/redeem", methods=["POST"])
def redeem_token():
    _role, vendor_id = authenticate(["Vendor"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)

    # Priority 7: serial mapping precedes general request-shape validation.
    serial = body.get("serial_number")
    token = None
    if isinstance(serial, int) and not isinstance(serial, bool):
        candidates = [t for t in STORE["tokens"].values()
                      if t["serial_number"] == serial]
        if candidates:
            candidates.sort(key=lambda t: t["_seq"])
            token = candidates[0]
        elif _serial_in_any_batch_range(serial):
            raise ApiError(ERR_TOKEN_NOT_MINTED, 409,
                           "Serial lies inside a batch range but was never minted")
        else:
            raise ApiError(ERR_TOKEN_UNKNOWN_SERIAL, 404,
                           "Serial lies outside every batch range of the program")

    # Priority 8: shape.
    ensure_valid_json(body)
    req_int(body, "serial_number")

    vendor = STORE["vendors"][vendor_id]
    issuance = STORE["issuances"].get(token["issuance_id"])
    day = market_day_of_issuance(issuance) if issuance else None

    # Priority 13: acting vendor must be ACTIVE.
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409,
                       "Vendor must be ACTIVE to redeem tokens")
    # Priority 14: tokens are same-day scrip — issuing day must be OPEN.
    if day is None or day["status"] != "OPEN":
        raise ApiError(ERR_MARKET_DAY_NOT_OPEN, 409,
                       "The token's issuing market day is not OPEN")
    # Priority 16: quarantine first.
    if token["status"] == "FLAGGED":
        raise ApiError(ERR_TOKEN_FLAGGED, 409, "Token is under fraud quarantine")
    # Priority 17: double-spend defense (auto-flag + AUTO_DOUBLE_SPEND case).
    if token["status"] in ("REDEEMED", "SETTLED"):
        if token["status"] == "REDEEMED":
            flag_token(token)
        open_auto_double_spend_case(token, vendor_id)
        raise ApiError(ERR_TOKEN_ALREADY_REDEEMED, 409,
                       "Token was already redeemed")
    # Priority 18: voided-token refusal.
    if token["status"] in ("VOIDED", "CONFISCATED"):
        raise ApiError(ERR_TOKEN_VOID, 409, "Token is void")
    # Priority 19: acting vendor's market must equal the issuing market.
    if day is not None and vendor["market_id"] != day["market_id"]:
        raise ApiError(ERR_TOKEN_VENDOR_MISMATCH, 409,
                       "Vendor's market does not match the token's issuing market")

    # Success: ISSUED -> REDEEMED.
    token["redeemed_vendor_id"] = vendor_id
    change_token_status(token, "REDEEMED")

    env, status = success_object(serialize_token(token), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/tokens/<tid>/reverse-redemption", methods=["POST"])
def reverse_redemption(tid):
    _role, vendor_id = authenticate(["Vendor"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    token = get_path_entity("tokens", tid)

    # Priority 2 (ownership, resource-dependent): only the redeeming vendor.
    if token.get("redeemed_vendor_id") != vendor_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Only the vendor that redeemed the token may reverse it")
    # Priority 11: generic invalid-from rejection.
    if token["status"] != "REDEEMED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Token in status {token['status']} cannot be reversed")
    # Priority 14: same-day correction only.
    issuance = STORE["issuances"].get(token["issuance_id"])
    day = market_day_of_issuance(issuance) if issuance else None
    if day is None or day["status"] != "OPEN":
        raise ApiError(ERR_MARKET_DAY_NOT_OPEN, 409,
                       "The token's issuing market day is not OPEN")
    # Priority 20: attached tokens cannot be reversed.
    if token.get("submission_id") is not None:
        raise ApiError(ERR_TOKEN_ALREADY_SUBMITTED, 409,
                       "Token is attached to a submission")

    token["redeemed_vendor_id"] = None
    change_token_status(token, "ISSUED")

    env, status = success_object(serialize_token(token), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
