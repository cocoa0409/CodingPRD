"""TokenBatch endpoints: register, read, list, activate, recall (cascade)."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_SERIAL_RANGE_OVERLAP,
)
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    fail_shape,
    get_body,
    idempotency_guard,
    paginate,
    req_enum,
    req_int,
    req_str,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    bulk_change_tokens,
    serialize_token_batch,
    tokens_of_batch,
)

bp = Blueprint("token_batches", __name__)

BATCH_READ_ROLES = ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor"]


@bp.route("/token-batches", methods=["POST"])
def create_token_batch():
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    ref_exists("markets", body.get("market_id"))
    ensure_valid_json(body)
    market_id = req_str(body, "market_id")
    kind = req_enum(body, "kind", {"BASE", "MATCH"})
    denomination = req_int(body, "denomination_cents")
    serial_start = req_int(body, "serial_start")
    serial_end = req_int(body, "serial_end")
    if kind == "MATCH" and denomination != 100:
        fail_shape("MATCH batches must have denomination_cents 100")
    if kind == "BASE" and denomination not in (500, 100):
        fail_shape("BASE batches must have denomination_cents 500 or 100")
    if serial_end < serial_start:
        fail_shape("serial_end must be >= serial_start")

    # Priority 24: closed serial range must not intersect any non-RECALLED
    # batch range in the same program (any kind/denomination).
    market = STORE["markets"][market_id]
    program_id = market["program_id"]
    for other in STORE["token_batches"].values():
        if other["status"] == "RECALLED":
            continue
        other_market = STORE["markets"].get(other["market_id"])
        if not other_market or other_market["program_id"] != program_id:
            continue
        if serial_start <= other["serial_end"] and other["serial_start"] <= serial_end:
            raise ApiError(ERR_SERIAL_RANGE_OVERLAP, 409,
                           "Serial range intersects an existing batch range")

    batch = stamp_new({
        "market_id": market_id,
        "kind": kind,
        "denomination_cents": denomination,
        "serial_start": serial_start,
        "serial_end": serial_end,
        "status": "SEALED",
    })
    STORE["token_batches"][batch["id"]] = batch
    env, status = success_object(serialize_token_batch(batch), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/token-batches/<bid>", methods=["GET"])
def get_token_batch(bid):
    authenticate(BATCH_READ_ROLES)
    batch = get_path_entity("token_batches", bid)
    return success_object(serialize_token_batch(batch))


@bp.route("/token-batches", methods=["GET"])
def list_token_batches():
    authenticate(BATCH_READ_ROLES)
    market_id = request.args.get("market_id")
    status_filter = request.args.get("status")
    kind = request.args.get("kind")
    items = list(STORE["token_batches"].values())
    if market_id is not None:
        items = [b for b in items if b["market_id"] == market_id]
    if status_filter is not None:
        items = [b for b in items if b["status"] == status_filter]
    if kind is not None:
        items = [b for b in items if b["kind"] == kind]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_token_batch(b) for b in page], limit, offset, total)


@bp.route("/token-batches/<bid>/activate", methods=["POST"])
def activate_token_batch(bid):
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    batch = get_path_entity("token_batches", bid)
    if batch["status"] != "SEALED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"TokenBatch in status {batch['status']} cannot be activated")
    batch["status"] = "ACTIVE"
    touch(batch)
    env, status = success_object(serialize_token_batch(batch), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/token-batches/<bid>/recall", methods=["POST"])
def recall_token_batch(bid):
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    batch = get_path_entity("token_batches", bid)
    if batch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"TokenBatch in status {batch['status']} cannot be recalled")
    batch["status"] = "RECALLED"
    touch(batch)
    # HOP-1: every token of this batch still ISSUED transitions to VOIDED.
    # HOP-2: each affected MarketDay recomputes voided/variance (crossing
    # auto-flip between CLOSED and VARIANCE_FLAGGED per PRD §3.1); each
    # affected day bumps its version once per cascade.
    issued_tokens = [t for t in tokens_of_batch(batch["id"]) if t["status"] == "ISSUED"]
    bulk_change_tokens(issued_tokens, lambda t: "VOIDED")
    env, status = success_object(serialize_token_batch(batch), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
