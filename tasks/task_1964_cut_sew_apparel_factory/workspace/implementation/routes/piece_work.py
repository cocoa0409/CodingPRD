"""PieceWorkEntry endpoints (PRD §3.6) — logging guard chain and review."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, ROLE_SEWING_OPERATOR, ROLE_LINE_SUPERVISOR,
)
from response import success_object
from util import get_body, req_str, req_int, req_enum, req_date, fk_exists
from errors import (
    invalid_state, bundle_not_loggable, operation_not_in_tech_pack,
    no_line_assignment, operation_sequence_violation, qty_exceeds_remaining,
)
from services.calc import straight_piece
from services.core import (
    base_record, touch, public, get_piece_work_entry, get_bundle,
    get_production_order, pack_operations,
)
from routes.common import list_response, active_filters

bp = Blueprint("piece_work", __name__)

REVIEW_DECISIONS = {"VERIFY", "REJECT"}


def _non_rejected_qty(bundle_id, operation_spec_id):
    return sum(
        e["qty"] for e in store.piece_work_entries.values()
        if e["bundle_id"] == bundle_id
        and e["operation_spec_id"] == operation_spec_id
        and e["status"] != "REJECTED"
    )


def _verified_qty(bundle_id, operation_spec_id):
    return sum(
        e["qty"] for e in store.piece_work_entries.values()
        if e["bundle_id"] == bundle_id
        and e["operation_spec_id"] == operation_spec_id
        and e["status"] in ("VERIFIED", "PAID")
    )


def _reevaluate_bundle(bundle):
    """Recompute completed_through_seq; auto-complete when every operation of
    the pinned pack is fully verified (PRD §3.6)."""
    order = get_production_order(bundle["production_order_id"])
    ops = pack_operations(order["tech_pack_id"])
    if not ops:
        return
    completed = 0
    all_done = True
    for op in ops:
        if _verified_qty(bundle["id"], op["id"]) == bundle["qty"]:
            completed = op["sequence_no"]
        else:
            all_done = False
    if all_done:
        if bundle["status"] == "IN_PROGRESS":
            bundle["status"] = "COMPLETED"
            bundle["completed_through_seq"] = ops[-1]["sequence_no"]
            touch(bundle)
    elif completed != bundle["completed_through_seq"]:
        bundle["completed_through_seq"] = completed
        touch(bundle)


@bp.route("/piece-work-entries", methods=["POST"])
def create_piece_work_entry():
    _, user_id = require_roles([ROLE_SEWING_OPERATOR])
    body = get_body()
    fk_exists(body, "bundle_id", store.bundles, "Bundle")
    fk_exists(body, "operation_spec_id", store.operation_specs, "OperationSpec")
    bundle_id = req_str(body, "bundle_id")
    operation_spec_id = req_str(body, "operation_spec_id")
    work_date = req_date(body, "work_date")
    qty = req_int(body, "qty", min_v=1)
    # operator_id is always the caller's X-User-ID (entity-backed identity);
    # a body-supplied operator id is ignored (PRD §2.1, §3.6).
    bundle = get_bundle(bundle_id)
    operation = store.operation_specs[operation_spec_id]
    order = get_production_order(bundle["production_order_id"])

    # Guard chain in pipeline order (PRD §3.6).
    if bundle["status"] not in ("RELEASED", "IN_PROGRESS"):
        raise bundle_not_loggable(
            "bundle must be RELEASED or IN_PROGRESS to log piece work")
    if operation["tech_pack_id"] != order["tech_pack_id"]:
        raise operation_not_in_tech_pack(
            "operation spec does not belong to the order's pinned tech pack")
    has_assignment = any(
        a["operator_id"] == user_id
        and a["operation_spec_id"] == operation_spec_id
        and a["production_order_id"] == order["id"]
        and a["shift_date"] == work_date
        for a in store.line_assignments.values())
    if not has_assignment:
        raise no_line_assignment(
            "no LineAssignment matches this operator, operation, order, and "
            "work_date")
    ops = pack_operations(order["tech_pack_id"])
    positions = {op["id"]: i for i, op in enumerate(ops)}
    pos = positions[operation["id"]]
    if pos > 0:
        prev = ops[pos - 1]
        if _non_rejected_qty(bundle["id"], prev["id"]) != bundle["qty"]:
            raise operation_sequence_violation(
                "the preceding operation must be fully logged on this bundle "
                "first")
    remaining = bundle["qty"] - _non_rejected_qty(bundle["id"], operation_spec_id)
    if qty > remaining:
        raise qty_exceeds_remaining(
            "qty exceeds the remaining loggable quantity for this operation on "
            "this bundle")

    piece_earnings, earned_minutes = straight_piece(qty, operation)
    rec = base_record()
    rec.update({
        "bundle_id": bundle_id,
        "operation_spec_id": operation_spec_id,
        "operator_id": user_id,
        "work_date": work_date,
        "qty": qty,
        "piece_earnings_cents": piece_earnings,
        "earned_minutes": earned_minutes,
        "payable_cents": None,
        "payroll_run_id": None,
        "reviewed_by_user_id": None,
        "status": "LOGGED",
    })
    store.piece_work_entries[rec["id"]] = rec
    # First entry on a RELEASED bundle moves it to IN_PROGRESS.
    if bundle["status"] == "RELEASED":
        bundle["status"] = "IN_PROGRESS"
        touch(bundle)
    return success_object(public(rec), status=201)


@bp.route("/piece-work-entries", methods=["GET"])
def list_piece_work_entries():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("bundle_id", request.args.get("bundle_id")),
        ("operation_spec_id", request.args.get("operation_spec_id")),
        ("operator_id", request.args.get("operator_id")),
        ("payroll_run_id", request.args.get("payroll_run_id")),
    ])
    return list_response(store.piece_work_entries.values(), filters)


@bp.route("/piece-work-entries/<entry_id>", methods=["GET"])
def get_piece_work_entry_endpoint(entry_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_piece_work_entry(entry_id)))


@bp.route("/piece-work-entries/<entry_id>/review", methods=["POST"])
def review_piece_work_entry(entry_id):
    _, user_id = require_roles([ROLE_LINE_SUPERVISOR])
    entry = get_piece_work_entry(entry_id)
    body = get_body()
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    if entry["status"] != "LOGGED":
        raise invalid_state("piece work entry must be LOGGED to review")
    entry["reviewed_by_user_id"] = user_id
    if decision == "VERIFY":
        entry["status"] = "VERIFIED"
        touch(entry)
        _reevaluate_bundle(get_bundle(entry["bundle_id"]))
    else:
        entry["status"] = "REJECTED"
        touch(entry)
    return success_object(public(entry))
