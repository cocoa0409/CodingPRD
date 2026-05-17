"""OpsRun endpoints — year-end / grace-period checkpoint sweeps."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import (
    get_json_body, parse_iso_field, require_enum, require_fields,
    serialize_ops_run,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..services.audit import emit_audit_event
from ..services.year_end import execute_grace_period_expiry, execute_year_end_close
from ..store import store


bp = Blueprint("ops_runs", __name__)


OPS_KINDS = {"YEAR_END_CLOSE", "GRACE_PERIOD_EXPIRY"}


@bp.route("/ops-runs", methods=["POST"])
@require_auth(["PlanAdministrator"])
def create_ops_run():
    body = get_json_body(allow_empty=False)
    require_fields(body, ["kind", "as_of_date"])
    kind = require_enum(body["kind"], OPS_KINDS, "kind")
    as_of_date = parse_iso_field(body["as_of_date"], "as_of_date")

    with store.lock:
        # PRD §2.10 validation priority for ops-runs: duplicate check
        # precedes the strict-monotonic check.
        # Uniqueness on (kind, as_of_date)
        for r in store.ops_runs:
            if r["kind"] == kind and r["as_of_date"] == as_of_date:
                raise ApiError(
                    "ERR_DUPLICATE_OPS_RUN",
                    "OpsRun with this (kind, as_of_date) already exists.",
                )

        # Monotonic: must be > previous OpsRun.as_of_date
        if store.ops_runs:
            latest = max(store.ops_runs, key=lambda r: r["as_of_date"])
            if as_of_date <= latest["as_of_date"]:
                raise ApiError(
                    "ERR_OPS_RUN_NOT_MONOTONIC",
                    "as_of_date must be strictly greater than the latest OpsRun.as_of_date.",
                )

        index = store.next_ops_index()
        now = store.clock.now()
        ops_row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "index": index,
            "as_of_date": as_of_date,
            "kind": kind,
            "plan_years_affected": [],
            "total_forfeited_cents": 0,
        }
        store.ops_runs.append(ops_row)

        # Initial OPS_RUN_EXECUTED event
        emit_audit_event(
            event_type="OPS_RUN_EXECUTED",
            subject_entity="PLAN_YEAR", subject_id=ops_row["id"],
            account_id=None, plan_year_id=None,
            cents_delta=0, ops_run_index=index,
        )

        if kind == "YEAR_END_CLOSE":
            affected, total_forfeit = execute_year_end_close(
                as_of_date=as_of_date, ops_run_index=index,
            )
        else:
            affected, total_forfeit = execute_grace_period_expiry(
                as_of_date=as_of_date, ops_run_index=index,
            )
        ops_row["plan_years_affected"] = sorted(affected)
        ops_row["total_forfeited_cents"] = total_forfeit

    return jsonify(build_success_envelope(serialize_ops_run(ops_row))), 201


@bp.route("/ops-runs", methods=["GET"])
@require_auth(["PlanAdministrator", "Auditor"])
def list_ops_runs():
    limit, offset = parse_pagination()
    f_kind = request.args.get("kind")
    rows = list(store.ops_runs)
    if f_kind is not None:
        rows = [r for r in rows if r["kind"] == f_kind]
    rows.sort(key=lambda r: r["index"])
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_ops_run(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
