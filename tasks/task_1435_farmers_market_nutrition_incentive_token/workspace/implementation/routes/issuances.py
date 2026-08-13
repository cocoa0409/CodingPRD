"""Issuance endpoints: create (match computation + minting), read, list, void."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import (
    ApiError,
    ERR_BATCH_SERIALS_INSUFFICIENT,
    ERR_CHARGE_TOO_SMALL,
    ERR_FRACTIONAL_CHARGE,
    ERR_INVALID_STATE,
    ERR_ISSUANCE_NOT_VOIDABLE,
    ERR_MARKET_DAY_NOT_OPEN,
    ERR_NO_ACTIVE_TOKEN_BATCH,
    ERR_SHOPPER_NOT_ELIGIBLE,
    ERR_STALE_VERSION,
)
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    get_body,
    idempotency_guard,
    paginate,
    req_int,
    req_str,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    batch_next_serial,
    batch_pool,
    batch_remaining_serials,
    bulk_change_tokens,
    compute_match_cents,
    denomination_plan,
    market_day_of_issuance,
    program_id_of_market_day,
    serialize_issuance,
    tokens_of_issuance,
)

bp = Blueprint("issuances", __name__)

ISSUANCE_READ_ROLES = ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor"]


@bp.route("/issuances", methods=["POST"])
def create_issuance():
    authenticate(["BoothOperator"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)

    # Priority 6: body FK existence (before shape).
    ref_exists("shoppers", body.get("shopper_id"))
    ref_exists("market_days", body.get("market_day_id"))

    # Priority 8: shape.
    ensure_valid_json(body)
    shopper_id = req_str(body, "shopper_id")
    market_day_id = req_str(body, "market_day_id")
    charge = req_int(body, "benefit_charged_cents")
    expected_version = req_int(body, "expected_shopper_version")

    shopper = STORE["shoppers"][shopper_id]
    day = STORE["market_days"][market_day_id]

    # Priority 10: OCC on the parent shopper's version.
    if expected_version != shopper["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_shopper_version does not match the shopper's "
                       "current version")

    # Priorities 12/14: shopper eligibility, market-day openness.
    if shopper["status"] != "ACTIVE":
        raise ApiError(ERR_SHOPPER_NOT_ELIGIBLE, 409,
                       "Shopper must be ACTIVE to receive an issuance")
    if day["status"] != "OPEN":
        raise ApiError(ERR_MARKET_DAY_NOT_OPEN, 409,
                       "Issuance requires an OPEN market day")

    market = STORE["markets"][day["market_id"]]
    program = STORE["programs"][market["program_id"]]

    # Mint plan computed from the raw request values (needed for the pinned
    # fiscal ladder order: batch-serial sufficiency precedes charge checks).
    match_cents = compute_match_cents(shopper, program, day, charge)
    plan = denomination_plan(charge, match_cents)

    # Priority 27: eligible ACTIVE batches exist but none has enough serials.
    chosen = {}
    for (kind, denom), count in plan.items():
        pool = batch_pool(market["id"], kind, denom)
        sufficient = [b for b in pool if batch_remaining_serials(b) >= count]
        if pool and not sufficient:
            raise ApiError(ERR_BATCH_SERIALS_INSUFFICIENT, 409,
                           "No ACTIVE batch has enough remaining serials for "
                           f"({kind}, {denom})")
        if sufficient:
            chosen[(kind, denom)] = sufficient[0]

    # Priority 28/29: whole-dollar scrip gates.
    if charge < 100:
        raise ApiError(ERR_CHARGE_TOO_SMALL, 422,
                       "benefit_charged_cents must be at least 100")
    if charge % 100 != 0:
        raise ApiError(ERR_FRACTIONAL_CHARGE, 422,
                       "benefit_charged_cents must be a multiple of 100")

    # Priority 30: no ACTIVE batch at all for a needed (kind, denomination).
    for (kind, denom), count in plan.items():
        if (kind, denom) not in chosen:
            raise ApiError(ERR_NO_ACTIVE_TOKEN_BATCH, 409,
                           f"No ACTIVE token batch for ({kind}, {denom})")

    # All checks passed: record the issuance, then mint (atomic — selection
    # was fully validated above, so no partial mint is possible).
    issuance = stamp_new({
        "shopper_id": shopper_id,
        "market_day_id": market_day_id,
        "benefit_charged_cents": charge,
        "base_value_cents": charge,
        "match_cents": match_cents,
        "status": "ACTIVE",
    })
    STORE["issuances"][issuance["id"]] = issuance

    for (kind, denom), count in plan.items():
        batch = chosen[(kind, denom)]
        start = batch_next_serial(batch)
        for n in range(count):
            token = stamp_new({
                "serial_number": start + n,
                "kind": kind,
                "denomination_cents": denom,
                "issuance_id": issuance["id"],
                "token_batch_id": batch["id"],
                "status": "ISSUED",
                "redeemed_vendor_id": None,
                "submission_id": None,
            })
            STORE["tokens"][token["id"]] = token

    # Side effects (SCAFFOLD §1.5): shopper, program, and market day each
    # increment their version.
    touch(shopper)
    touch(program)
    touch(day)

    env, status = success_object(serialize_issuance(issuance), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/issuances/<iid>", methods=["GET"])
def get_issuance(iid):
    role, user_id = authenticate(ISSUANCE_READ_ROLES + ["Shopper"])
    issuance = get_path_entity("issuances", iid)
    if role == "Shopper" and issuance["shopper_id"] != user_id:
        from errors import ERR_FORBIDDEN
        raise ApiError(ERR_FORBIDDEN, 403,
                       "A shopper may only read its own issuances")
    return success_object(serialize_issuance(issuance))


@bp.route("/issuances", methods=["GET"])
def list_issuances():
    authenticate(ISSUANCE_READ_ROLES)
    shopper_id = request.args.get("shopper_id")
    market_day_id = request.args.get("market_day_id")
    status_filter = request.args.get("status")
    items = list(STORE["issuances"].values())
    if shopper_id is not None:
        items = [i for i in items if i["shopper_id"] == shopper_id]
    if market_day_id is not None:
        items = [i for i in items if i["market_day_id"] == market_day_id]
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_issuance(i) for i in page], limit, offset, total)


@bp.route("/issuances/<iid>/void", methods=["POST"])
def void_issuance(iid):
    authenticate(["BoothOperator"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    issuance = get_path_entity("issuances", iid)

    # Priority 11: generic invalid-from rejection.
    if issuance["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Issuance in status {issuance['status']} cannot be voided")
    # Priority 14: same-day reversal only (day must still be OPEN).
    day = market_day_of_issuance(issuance)
    if day is None or day["status"] != "OPEN":
        raise ApiError(ERR_MARKET_DAY_NOT_OPEN, 409,
                       "Issuance void requires the market day to still be OPEN")
    # Priority 31: every token must still be ISSUED.
    tokens = tokens_of_issuance(issuance["id"])
    if any(t["status"] != "ISSUED" for t in tokens):
        raise ApiError(ERR_ISSUANCE_NOT_VOIDABLE, 409,
                       "Issuance has tokens that already left ISSUED status")

    # Side effects: issuance -> VOIDED; tokens -> VOIDED; shopper season usage
    # and program pool compensated (computed fields); versions increment.
    issuance["status"] = "VOIDED"
    touch(issuance)
    bulk_change_tokens(tokens, lambda t: "VOIDED")
    shopper = STORE["shoppers"].get(issuance["shopper_id"])
    if shopper is not None:
        touch(shopper)
    market = STORE["markets"].get(day["market_id"]) if day else None
    program = STORE["programs"].get(market["program_id"]) if market else None
    if program is not None:
        touch(program)
    if not tokens:
        # No tokens to cascade over; the day's issued total still drops.
        touch(day)

    env, status = success_object(serialize_issuance(issuance), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
