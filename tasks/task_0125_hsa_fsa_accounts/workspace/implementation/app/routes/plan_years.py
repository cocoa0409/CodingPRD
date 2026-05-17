"""PlanYear endpoints (incl. tax-form recapture)."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import to_date
from ..errors import ApiError
from ..helpers import (
    get_json_body, require_fields, require_positive_int,
    serialize_plan_year, sort_key_created_then_id,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..services.audit import emit_audit_event
from ..services.caps import compute_caps
from ..services.tax_form import compute_chronological, compute_forward_looking
from ..services.year_end import apply_pending_carryover_to_successor
from ..store import store


bp = Blueprint("plan_years", __name__)


def _get_account_or_404_scoped(account_id: str) -> dict:
    a = store.accounts.get(account_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")
    if g.role == "AccountHolder" and a["account_holder_id"] != g.user_id:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")
    return a


def _get_plan_year_in_account(account_id: str, plan_year_id: str) -> dict:
    py = store.plan_years.get(plan_year_id)
    if py is None or py["account_id"] != account_id:
        raise ApiError("ERR_NOT_FOUND", "Plan year not found.")
    return py


@bp.route("/accounts/<account_id>/plan-years", methods=["POST"])
@require_auth(["PlanAdministrator"])
def create_plan_year(account_id: str):
    a = _get_account_or_404_scoped(account_id)
    body = get_json_body(allow_empty=False)
    require_fields(body, ["calendar_year"])
    cy = body["calendar_year"]
    if isinstance(cy, bool) or not isinstance(cy, int):
        raise ApiError("ERR_BAD_REQUEST", "calendar_year must be an integer.")
    if cy < 1000 or cy > 9999:
        raise ApiError("ERR_BAD_REQUEST", "calendar_year must be a 4-digit year.")

    with store.lock:
        if a["status"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")
        # calendar_year must be >= account's creation year (per PRD).
        account_creation_year = to_date(a["created_at"]).year
        if cy < account_creation_year:
            raise ApiError("ERR_BAD_REQUEST", "calendar_year must be >= the account's creation year.")
        # Uniqueness across (account_id, calendar_year)
        for existing in store.plan_years.values():
            if existing["account_id"] == a["id"] and existing["calendar_year"] == cy:
                raise ApiError("ERR_DUPLICATE_PLAN_YEAR", "Plan year already exists for this account.")

        holder = store.account_holders.get(a["account_holder_id"])
        if holder is None:
            raise ApiError("ERR_NOT_FOUND", "Owning account holder not found.")
        cap, catch_up = compute_caps(
            account_type=a["account_type"],
            coverage_tier=a.get("coverage_tier"),
            tax_filing_status=holder["tax_filing_status"],
            birth_date=a["account_holder_birth_date"],
            calendar_year=cy,
        )

        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "account_id": a["id"],
            "calendar_year": cy,
            "status": "ACTIVE",
            "contribution_cap_cents": cap,
            "catch_up_cap_cents": catch_up,
            "contributions_ytd_cents": 0,
            "claims_paid_ytd_cents": 0,
            "provisional_balance_cents": 0,
            "carryover_in_cents": 0,
            "carryover_consumed_cents": 0,
            "forfeited_cents": 0,
            "grace_period_end_date": None,
        }
        store.plan_years[row["id"]] = row

        # If predecessor (cy - 1) is CARRYOVER_PENDING, apply carryover and close it.
        predecessor = None
        for existing in store.plan_years.values():
            if (existing["account_id"] == a["id"]
                    and existing["calendar_year"] == cy - 1
                    and existing["status"] == "CARRYOVER_PENDING"):
                predecessor = existing
                break
        if predecessor is not None:
            apply_pending_carryover_to_successor(predecessor=predecessor, successor=row)

        emit_audit_event(
            event_type="PLAN_YEAR_OPENED",
            subject_entity="PLAN_YEAR", subject_id=row["id"],
            account_id=a["id"], plan_year_id=row["id"], cents_delta=0,
        )

    return jsonify(build_success_envelope(serialize_plan_year(row))), 201


@bp.route("/accounts/<account_id>/plan-years/<plan_year_id>", methods=["GET"])
@require_auth(["PlanAdministrator", "AccountHolder", "ClaimAdjudicator", "Auditor"])
def get_plan_year(account_id: str, plan_year_id: str):
    a = _get_account_or_404_scoped(account_id)
    py = _get_plan_year_in_account(a["id"], plan_year_id)
    return jsonify(build_success_envelope(serialize_plan_year(py))), 200


@bp.route("/accounts/<account_id>/plan-years", methods=["GET"])
@require_auth(["PlanAdministrator", "AccountHolder", "ClaimAdjudicator", "Auditor"])
def list_plan_years(account_id: str):
    a = _get_account_or_404_scoped(account_id)
    limit, offset = parse_pagination()
    f_status = request.args.get("status")
    f_cy = request.args.get("calendar_year")
    rows = [py for py in store.plan_years.values() if py["account_id"] == a["id"]]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_cy is not None:
        try:
            cy_int = int(f_cy)
        except ValueError:
            raise ApiError("ERR_BAD_REQUEST", "calendar_year filter must be an integer.")
        rows = [r for r in rows if r["calendar_year"] == cy_int]
    rows.sort(key=sort_key_created_then_id)
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_plan_year(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


@bp.route("/accounts/<account_id>/plan-years/<plan_year_id>/tax-form", methods=["GET"])
@require_auth(["AccountHolder", "PlanAdministrator", "Auditor"])
def get_tax_form(account_id: str, plan_year_id: str):
    a = _get_account_or_404_scoped(account_id)
    py = _get_plan_year_in_account(a["id"], plan_year_id)
    basis = request.args.get("basis", "chronological")
    if basis not in ("chronological", "forward_looking"):
        raise ApiError("ERR_BAD_REQUEST", "basis must be 'chronological' or 'forward_looking'.")
    if basis == "chronological":
        result = compute_chronological(py["id"], py)
    else:
        result = compute_forward_looking(py["id"], py)
    return jsonify(build_success_envelope(result)), 200
