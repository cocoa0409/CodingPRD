"""SettlementRun endpoints: sweep APPROVED claims into PAID; read; list."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import ApiError, ERR_STALE_VERSION
from logical_clock import _parse_iso
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    get_body,
    idempotency_guard,
    paginate,
    req_datetime,
    req_int,
    req_str,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    iso,
    program_id_of_submission,
    serialize_settlement_run,
)

bp = Blueprint("settlement_runs", __name__)

RUN_READ_ROLES = ["ProgramAdmin", "Auditor"]


@bp.route("/settlement-runs", methods=["POST"])
def create_settlement_run():
    authenticate(["ProgramAdmin"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)

    # Priority 6: body FK existence.
    ref_exists("programs", body.get("program_id"))
    # Priority 8: shape.
    ensure_valid_json(body)
    program_id = req_str(body, "program_id")
    cutoff_at = req_datetime(body, "cutoff_at")
    expected_version = req_int(body, "expected_program_version")

    program = STORE["programs"][program_id]

    # Priority 10: OCC on the program's version.
    if expected_version != program["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_program_version does not match the program's "
                       "current version")

    # Eligible set (SCAFFOLD settlement_sweep): APPROVED, approved_at <= cutoff
    # (inclusive). Pinned order: approved_at ASC, tie created_at ASC, never id
    # (insertion sequence is the final deterministic tie-break).
    eligible = []
    for sub in STORE["submissions"].values():
        if sub["status"] != "APPROVED":
            continue
        if program_id_of_submission(sub) != program["id"]:
            continue
        if _parse_iso(sub["approved_at"]) <= cutoff_at:
            eligible.append(sub)
    eligible.sort(key=lambda s: (s["approved_at"], s["created_at"], s["_seq"]))

    swept_ids = []
    total_paid = 0
    vendors_paid = set()
    for sub in eligible:
        sub["status"] = "PAID"
        sub["paid_amount_cents"] = sub["approved_amount_cents"]
        touch(sub)
        vendor = STORE["vendors"].get(sub["vendor_id"])
        if vendor is not None:
            touch(vendor)
            vendors_paid.add(vendor["id"])
        total_paid += sub["paid_amount_cents"] or 0
        # Program version advances for each swept claim.
        touch(program)
        swept_ids.append(sub["id"])

    # ...and once more for the creation of the run itself (PRD §3.8).
    touch(program)

    run = stamp_new({
        "program_id": program["id"],
        "cutoff_at": iso(cutoff_at),
        "swept_submission_ids": swept_ids,
        "total_paid_cents": total_paid,
        "vendor_payment_count": len(vendors_paid),
    })
    STORE["settlement_runs"][run["id"]] = run

    env, status = success_object(serialize_settlement_run(run), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/settlement-runs/<rid>", methods=["GET"])
def get_settlement_run(rid):
    authenticate(RUN_READ_ROLES)
    run = get_path_entity("settlement_runs", rid)
    return success_object(serialize_settlement_run(run))


@bp.route("/settlement-runs", methods=["GET"])
def list_settlement_runs():
    authenticate(RUN_READ_ROLES)
    program_id = request.args.get("program_id")
    items = list(STORE["settlement_runs"].values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_settlement_run(r) for r in page], limit, offset, total)
