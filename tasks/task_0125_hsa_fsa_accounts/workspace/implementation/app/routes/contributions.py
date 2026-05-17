"""Contribution endpoints."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import (
    get_json_body, require_enum, require_fields, require_positive_int,
    serialize_contribution, sort_key_created_then_id,
)
from ..responses import build_list_envelope, build_success_envelope, paginate, parse_pagination
from ..services.audit import emit_audit_event
from ..services.occ import check_version
from ..store import store


bp = Blueprint("contributions", __name__)


SOURCES = {"PAYROLL", "DIRECT", "EMPLOYER_MATCH"}


def _recompute_provisional(py: dict) -> None:
    py["provisional_balance_cents"] = (
        py["contributions_ytd_cents"] + py["carryover_in_cents"]
        - py["claims_paid_ytd_cents"]
    )


@bp.route("/plan-years/<plan_year_id>/contributions", methods=["POST"])
@require_auth(["AccountHolder", "PlanAdministrator"])
def post_contribution(plan_year_id: str):
    py = store.plan_years.get(plan_year_id)
    if py is None:
        raise ApiError("ERR_NOT_FOUND", "Plan year not found.")
    a = store.accounts.get(py["account_id"])
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Owning account not found.")
    if g.role == "AccountHolder" and a["account_holder_id"] != g.user_id:
        raise ApiError("ERR_NOT_FOUND", "Plan year not found.")

    body = get_json_body(allow_empty=False)
    require_fields(body, ["amount_cents", "source"])
    amount = require_positive_int(body["amount_cents"], "amount_cents", min_value=1)
    source = require_enum(body["source"], SOURCES, "source")

    with store.lock:
        if a["status"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_NOT_OPEN", "Account is not OPEN.")
        if py["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is not ACTIVE.")
        # Cap check on post-write state
        cap_total = py["contribution_cap_cents"] + py["catch_up_cap_cents"]
        if py["contributions_ytd_cents"] + amount > cap_total:
            raise ApiError("ERR_CONTRIBUTION_CAP_EXCEEDED", "Contribution would exceed the cap.")

        now = store.clock.now()
        row = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "plan_year_id": py["id"],
            "amount_cents": amount,
            "source": source,
            "posted_at": now,
            "status": "POSTED",
            "reversal_of_id": None,
        }
        store.contributions[row["id"]] = row

        py["contributions_ytd_cents"] += amount
        _recompute_provisional(py)
        py["version"] += 1
        py["updated_at"] = now

        emit_audit_event(
            event_type="CONTRIBUTION_POSTED",
            subject_entity="CONTRIBUTION", subject_id=row["id"],
            account_id=a["id"], plan_year_id=py["id"],
            cents_delta=amount,
        )

    return jsonify(build_success_envelope(serialize_contribution(row))), 201


@bp.route("/contributions/<contribution_id>/reverse", methods=["POST"])
@require_auth(["PlanAdministrator"])
def reverse_contribution(contribution_id: str):
    original = store.contributions.get(contribution_id)
    if original is None:
        raise ApiError("ERR_NOT_FOUND", "Contribution not found.")
    body = get_json_body()
    py = store.plan_years.get(original["plan_year_id"])
    if py is None:
        raise ApiError("ERR_NOT_FOUND", "Owning plan year not found.")
    a = store.accounts.get(py["account_id"])
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Owning account not found.")

    with store.lock:
        if original["status"] != "POSTED":
            raise ApiError("ERR_INVALID_STATE", "Original contribution is not POSTED.")
        # Reversal of a reversing row (negative amount) is not meaningful in this API.
        if original["amount_cents"] < 0:
            raise ApiError("ERR_INVALID_STATE", "Cannot reverse a reversing contribution row.")
        if py["status"] not in ("ACTIVE", "GRACE_PERIOD", "CARRYOVER_PENDING"):
            raise ApiError("ERR_PLAN_YEAR_NOT_CLAIMABLE", "Plan year is not in a reversable state.")
        # Overdraw check: after subtracting, contributions_ytd_cents must remain >= claims_paid_ytd_cents
        amt = original["amount_cents"]
        if py["contributions_ytd_cents"] - amt < py["claims_paid_ytd_cents"]:
            raise ApiError(
                "ERR_REVERSAL_WOULD_OVERDRAW",
                "Reversal would drive contributions below claims paid.",
            )

        now = store.clock.now()
        original["status"] = "REVERSED"

        twin = {
            "id": store.new_id(),
            "_seq": store.next_seq(),
            "created_at": now,
            "plan_year_id": py["id"],
            "amount_cents": -amt,
            "source": original["source"],
            "posted_at": now,
            "status": "POSTED",
            "reversal_of_id": original["id"],
        }
        store.contributions[twin["id"]] = twin

        py["contributions_ytd_cents"] -= amt
        _recompute_provisional(py)
        py["version"] += 1
        py["updated_at"] = now

        emit_audit_event(
            event_type="CONTRIBUTION_REVERSED",
            subject_entity="CONTRIBUTION", subject_id=original["id"],
            account_id=a["id"], plan_year_id=py["id"],
            cents_delta=-amt,
        )

    # PRD §3.3: the reverse response returns the newly appended
    # twin row (whose amount_cents is the negative of the original).
    return jsonify(build_success_envelope(serialize_contribution(twin))), 200


@bp.route("/plan-years/<plan_year_id>/contributions", methods=["GET"])
@require_auth(["PlanAdministrator", "AccountHolder", "ClaimAdjudicator", "Auditor"])
def list_contributions(plan_year_id: str):
    py = store.plan_years.get(plan_year_id)
    if py is None:
        raise ApiError("ERR_NOT_FOUND", "Plan year not found.")
    a = store.accounts.get(py["account_id"])
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Owning account not found.")
    if g.role == "AccountHolder" and a["account_holder_id"] != g.user_id:
        raise ApiError("ERR_NOT_FOUND", "Plan year not found.")

    limit, offset = parse_pagination()
    f_status = request.args.get("status")
    f_source = request.args.get("source")

    rows = [c for c in store.contributions.values() if c["plan_year_id"] == py["id"]]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_source is not None:
        rows = [r for r in rows if r["source"] == f_source]
    rows.sort(key=sort_key_created_then_id)
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_contribution(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
