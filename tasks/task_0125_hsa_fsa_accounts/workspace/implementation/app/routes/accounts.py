"""Account endpoints."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import to_date
from ..errors import ApiError
from ..helpers import (
    get_json_body, parse_iso_field, require_enum, require_fields,
    serialize_account, sort_key_created_then_id,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..services.audit import emit_audit_event
from ..services.occ import check_version
from ..store import store


bp = Blueprint("accounts", __name__)


ACCOUNT_TYPES = {"HSA", "HEALTH_FSA", "DEPENDENT_CARE_FSA"}
COVERAGE_TIERS = {"SELF_ONLY", "FAMILY"}
YEAR_END_POLICIES = {"GRACE_PERIOD", "CARRYOVER", "NONE"}


def _validate_policy(account_type: str, year_end_policy: str) -> None:
    if account_type == "HSA":
        if year_end_policy != "NONE":
            raise ApiError("ERR_BAD_REQUEST", "HSA accounts must have year_end_policy=NONE.")
    elif account_type == "HEALTH_FSA":
        if year_end_policy not in {"GRACE_PERIOD", "CARRYOVER", "NONE"}:
            raise ApiError("ERR_BAD_REQUEST", "HEALTH_FSA year_end_policy must be one of GRACE_PERIOD, CARRYOVER, NONE.")
    elif account_type == "DEPENDENT_CARE_FSA":
        if year_end_policy not in {"GRACE_PERIOD", "NONE"}:
            raise ApiError("ERR_BAD_REQUEST", "DEPENDENT_CARE_FSA year_end_policy must be GRACE_PERIOD or NONE.")


def _validate_coverage_tier(account_type: str, coverage_tier: str | None) -> None:
    if account_type == "HSA":
        if coverage_tier not in COVERAGE_TIERS:
            raise ApiError("ERR_BAD_REQUEST", "HSA requires coverage_tier in {SELF_ONLY, FAMILY}.")
    else:
        if coverage_tier is not None:
            raise ApiError("ERR_BAD_REQUEST", "Non-HSA accounts must have coverage_tier=null.")


def _account_scope_check(account: dict) -> None:
    if g.role == "AccountHolder" and account["account_holder_id"] != g.user_id:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")


def _get_account_or_404(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")
    return a


@bp.route("/accounts", methods=["POST"])
@require_auth(["PlanAdministrator"])
def create_account():
    body = get_json_body(allow_empty=False)
    require_fields(body, ["account_holder_id", "account_type", "year_end_policy", "account_holder_birth_date"])
    account_holder_id = body["account_holder_id"]
    if not isinstance(account_holder_id, str):
        raise ApiError("ERR_BAD_REQUEST", "account_holder_id must be a string.")
    if account_holder_id not in store.account_holders:
        raise ApiError("ERR_NOT_FOUND", "Account holder not found.")

    account_type = require_enum(body["account_type"], ACCOUNT_TYPES, "account_type")
    year_end_policy = require_enum(body["year_end_policy"], YEAR_END_POLICIES, "year_end_policy")
    coverage_tier = body.get("coverage_tier")
    if coverage_tier is not None and not isinstance(coverage_tier, str):
        raise ApiError("ERR_BAD_REQUEST", "coverage_tier must be a string or null.")
    _validate_coverage_tier(account_type, coverage_tier)
    _validate_policy(account_type, year_end_policy)
    birth_date = parse_iso_field(body["account_holder_birth_date"], "account_holder_birth_date")

    with store.lock:
        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "account_holder_id": account_holder_id,
            "account_type": account_type,
            "coverage_tier": coverage_tier if account_type == "HSA" else None,
            "account_holder_birth_date": birth_date,
            "year_end_policy": year_end_policy,
            "status": "OPEN",
            "closed_at": None,
        }
        store.accounts[row["id"]] = row
        emit_audit_event(
            event_type="ACCOUNT_OPENED",
            subject_entity="ACCOUNT", subject_id=row["id"],
            account_id=row["id"], plan_year_id=None, cents_delta=0,
        )

    return jsonify(build_success_envelope(serialize_account(row))), 201


@bp.route("/accounts/<account_id>", methods=["GET"])
@require_auth(["PlanAdministrator", "AccountHolder", "ClaimAdjudicator", "Auditor"])
def get_account(account_id: str):
    a = _get_account_or_404(account_id)
    _account_scope_check(a)
    return jsonify(build_success_envelope(serialize_account(a))), 200


@bp.route("/accounts", methods=["GET"])
@require_auth(["PlanAdministrator", "Auditor"])
def list_accounts():
    limit, offset = parse_pagination()
    f_holder = request.args.get("account_holder_id")
    f_status = request.args.get("status")
    f_type = request.args.get("account_type")

    rows = list(store.accounts.values())
    if f_holder is not None:
        rows = [r for r in rows if r["account_holder_id"] == f_holder]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_type is not None:
        rows = [r for r in rows if r["account_type"] == f_type]

    rows.sort(key=sort_key_created_then_id)
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_account(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


@bp.route("/accounts/<account_id>/freeze", methods=["POST"])
@require_auth(["PlanAdministrator"])
def freeze_account(account_id: str):
    a = _get_account_or_404(account_id)
    body = get_json_body()
    with store.lock:
        check_version(body, a["version"])
        if a["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Account is not OPEN.")
        a["status"] = "FROZEN"
        a["version"] += 1
        a["updated_at"] = store.clock.now()
        emit_audit_event(
            event_type="ACCOUNT_FROZEN",
            subject_entity="ACCOUNT", subject_id=a["id"],
            account_id=a["id"], cents_delta=0,
        )
    return jsonify(build_success_envelope(serialize_account(a))), 200


@bp.route("/accounts/<account_id>/unfreeze", methods=["POST"])
@require_auth(["PlanAdministrator"])
def unfreeze_account(account_id: str):
    a = _get_account_or_404(account_id)
    body = get_json_body()
    with store.lock:
        check_version(body, a["version"])
        if a["status"] != "FROZEN":
            raise ApiError("ERR_INVALID_STATE", "Account is not FROZEN.")
        a["status"] = "OPEN"
        a["version"] += 1
        a["updated_at"] = store.clock.now()
        emit_audit_event(
            event_type="ACCOUNT_FROZEN",
            subject_entity="ACCOUNT", subject_id=a["id"],
            account_id=a["id"], cents_delta=0, note="unfreeze",
        )
    return jsonify(build_success_envelope(serialize_account(a))), 200


@bp.route("/accounts/<account_id>/close", methods=["POST"])
@require_auth(["PlanAdministrator"])
def close_account(account_id: str):
    a = _get_account_or_404(account_id)
    body = get_json_body()
    with store.lock:
        check_version(body, a["version"])
        if a["status"] not in ("OPEN", "FROZEN"):
            raise ApiError("ERR_INVALID_STATE", "Account is already CLOSED.")
        # Preconditions
        for py in store.plan_years.values():
            if py["account_id"] != a["id"]:
                continue
            if py["status"] in ("ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING"):
                raise ApiError(
                    "ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR",
                    "Cannot close account with non-CLOSED plan years.",
                )
        for cl in store.claims.values():
            if cl["account_id"] != a["id"]:
                continue
            if cl["status"] in ("SUBMITTED", "APPROVED"):
                raise ApiError(
                    "ERR_ACCOUNT_HAS_PENDING_CLAIMS",
                    "Cannot close account with pending claims.",
                )
        now = store.clock.now()
        a["status"] = "CLOSED"
        a["closed_at"] = now
        a["version"] += 1
        a["updated_at"] = now
        emit_audit_event(
            event_type="ACCOUNT_CLOSED",
            subject_entity="ACCOUNT", subject_id=a["id"],
            account_id=a["id"], cents_delta=0,
        )
    return jsonify(build_success_envelope(serialize_account(a))), 200
