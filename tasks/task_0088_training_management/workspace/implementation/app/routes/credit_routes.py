"""CreditPool and CreditAdjustment endpoints."""
from __future__ import annotations

from flask import Flask, g, request

from ..audit import write_audit
from ..auth import require_auth
from ..clock import format_iso, parse_iso, add_years
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store
from ..services.calculations import recompute_credit_pool_accumulated
from ..services.lookups import get_credit_pool, ref_credit_pool, ref_trainee
from ..services.serializers import serialize_credit_adjustment, serialize_credit_pool
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


def register(app: Flask) -> None:
    @app.post("/training/credit-pools")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_credit_pool():
        body = get_json_body()
        trainee_id = body.get("trainee_id")
        cycle_kind = body.get("cycle_kind")
        cycle_start = body.get("cycle_start")
        required_credits = body.get("required_credits")
        if not trainee_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "trainee_id required.", http_status=422)
        ref_trainee(trainee_id)
        if cycle_kind not in ("ANNUAL", "BIENNIAL"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "cycle_kind must be ANNUAL or BIENNIAL.", http_status=422)
        try:
            cs = parse_iso(cycle_start)
        except (ValueError, TypeError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "cycle_start invalid.", http_status=422)
        try:
            rc = float(required_credits)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "required_credits invalid.", http_status=422)
        ce = add_years(cs, 1 if cycle_kind == "ANNUAL" else 2)

        base = common_fields_create()
        row = {
            **base,
            "trainee_id": trainee_id,
            "cycle_kind": cycle_kind,
            "cycle_start": format_iso(cs),
            "cycle_end": format_iso(ce),
            "required_credits": rc,
            "accumulated_credits": 0,
            "shortfall_warning_emitted": False,
        }
        get_store().credit_pools[base["id"]] = row
        return created(serialize_credit_pool(row))

    @app.get("/training/credit-pools")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def list_credit_pools():
        limit, offset = parse_limit_offset()
        trainee_id = request.args.get("trainee_id")
        cycle_kind = request.args.get("cycle_kind")
        items = list(get_store().credit_pools.values())
        if g.user_role == "Trainee":
            items = [p for p in items if p["trainee_id"] == g.user_id]
        if trainee_id:
            items = [p for p in items if p["trainee_id"] == trainee_id]
        if cycle_kind:
            items = [p for p in items if p["cycle_kind"] == cycle_kind]
        items = sort_by_created(items)
        return ok_list([serialize_credit_pool(p) for p in items], limit, offset)

    @app.get("/training/credit-pools/<cid>")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def fetch_credit_pool(cid):
        p = get_credit_pool(cid)
        if g.user_role == "Trainee" and p["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Cannot view another trainee's pool.")
        return ok(serialize_credit_pool(p))

    @app.post("/training/credit-adjustments")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_credit_adjustment():
        body = get_json_body()
        pool_id = body.get("credit_pool_id")
        delta = body.get("delta")
        reason = body.get("reason")
        if not pool_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "credit_pool_id required.", http_status=422)
        pool = ref_credit_pool(pool_id)
        try:
            d = float(delta)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "delta must be number.", http_status=422)
        if not isinstance(reason, str) or not reason:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "reason required.", http_status=422)

        # Tentative new accumulated_credits
        cur_acc = float(pool.get("accumulated_credits", 0))
        if cur_acc + d < 0:
            raise ApiError("ERR_CREDIT_NEGATIVE", "Adjustment would drive accumulated_credits below zero.")

        actor_id, actor_role = g.user_id, g.user_role
        base = common_fields_append_only()
        adj = {
            **base,
            "credit_pool_id": pool_id,
            "delta": d,
            "reason": reason,
            "actor_role": actor_role,
        }
        get_store().credit_adjustments[base["id"]] = adj

        before = {"accumulated_credits": pool.get("accumulated_credits")}
        recompute_credit_pool_accumulated(pool)
        bump_version(pool)
        # Defensive: if floating arithmetic produces a tiny negative, snap to 0 (would have already been rejected above)
        write_audit(
            "CREDIT_POOL",
            pool["id"],
            "credit.adjusted",
            before=before,
            after={"accumulated_credits": pool["accumulated_credits"], "delta": d},
        )
        return created(serialize_credit_adjustment(adj))
