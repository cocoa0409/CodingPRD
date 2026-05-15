"""Subsidy policy and declaration endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, current_app, g, request

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_DOCUMENTS_INCOMPLETE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SETTLEMENT_NOT_CONFIRMED,
    ERR_SUBSIDY_BELOW_THRESHOLD,
    ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE,
    ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
)
from pv_ops.responses import created, listed, success
from pv_ops.services import serializers
from pv_ops.store import paginate
from pv_ops.utils import (
    D,
    fmt_dt,
    get_body,
    parse_dt,
    parse_dt_opt,
    parse_pagination,
    require_enum,
    require_list,
    require_number,
    require_str,
    round_half_up,
)


bp = Blueprint("subsidy", __name__)


SUBSIDY_MIN_PAYOUT_CNY = D("100")
APPROVAL_DUE_DAYS = 90


@bp.route("/pv-ops/subsidy-policies", methods=["POST"])
@require_roles("PlatformAdmin")
def create_policy():
    body = get_body()
    code = require_str(body, "code")
    scope = require_enum(body, "scope", {"NATIONAL", "LOCAL"})
    rate = require_number(body, "rate_cny_per_kwh", ge=0.0)
    eligible_from = parse_dt(body.get("eligible_from"), "eligible_from")
    eligible_to = parse_dt(body.get("eligible_to"), "eligible_to")
    if eligible_to <= eligible_from:
        raise APIError(ERR_VALIDATION, 422, "eligible_to must be after eligible_from")
    min_comm = parse_dt_opt(body.get("min_commissioning_date"), "min_commissioning_date")
    max_comm = parse_dt_opt(body.get("max_commissioning_date"), "max_commissioning_date")
    required_documents = require_list(body, "required_documents")
    for r in required_documents:
        if not isinstance(r, str):
            raise APIError(ERR_VALIDATION, 422, "required_documents entries must be strings")
    store = current_app.extensions["store"]
    with store.lock:
        for p in store.subsidy_policies.values():
            if p.get("code") == code:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Subsidy policy code already exists")
        row = {
            "code": code,
            "scope": scope,
            "rate_cny_per_kwh": float(round_half_up(rate, 4)),
            "eligible_from": fmt_dt(eligible_from),
            "eligible_to": fmt_dt(eligible_to),
            "min_commissioning_date": fmt_dt(min_comm) if min_comm else None,
            "max_commissioning_date": fmt_dt(max_comm) if max_comm else None,
            "required_documents": list(required_documents),
            "lifecycle_state": "ACTIVE",
        }
        store.insert_common(row)
        store.subsidy_policies[row["id"]] = row
        return created(serializers.subsidy_policy_view(row))


@bp.route("/pv-ops/stations/<station_id>/subsidy-declarations", methods=["POST"])
@require_roles("FinanceOfficer")
def create_declaration(station_id: str):
    body = get_body()
    subsidy_policy_id = require_str(body, "subsidy_policy_id")
    settlement_period_id = require_str(body, "settlement_period_id")
    documents = require_list(body, "documents")
    for d in documents:
        if not isinstance(d, dict) or "key" not in d or "ref_url" not in d:
            raise APIError(ERR_VALIDATION, 422, "documents entries need key and ref_url")
    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        if subsidy_policy_id not in store.subsidy_policies:
            raise APIError(ERR_NOT_FOUND, 404, "Subsidy policy not found")
        if settlement_period_id not in store.settlement_periods:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        period = store.settlement_periods[settlement_period_id]
        if period.get("station_id") != station_id:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period does not belong to station")
        row = {
            "station_id": station_id,
            "subsidy_policy_id": subsidy_policy_id,
            "settlement_period_id": settlement_period_id,
            "documents": [dict(d) for d in documents],
            "claimed_kwh": None,
            "subsidy_amount_cny": None,
            "state": "DRAFT",
            "approval_due_date": None,
            "received_at": None,
            "rejection_reason": None,
        }
        store.insert_common(row)
        store.subsidy_declarations[row["id"]] = row
        return created(serializers.subsidy_declaration_view(row))


@bp.route("/pv-ops/subsidy-declarations/<decl_id>/submit", methods=["POST"])
@require_roles("FinanceOfficer")
def submit_declaration(decl_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        decl = store.subsidy_declarations.get(decl_id)
        if not decl:
            raise APIError(ERR_NOT_FOUND, 404, "Declaration not found")
        if decl.get("state") != "DRAFT":
            raise APIError(ERR_INVALID_STATE, 409, "Declaration must be DRAFT")
        period = store.settlement_periods.get(decl["settlement_period_id"])
        policy = store.subsidy_policies.get(decl["subsidy_policy_id"])
        station = store.stations.get(decl["station_id"])
        if not (period and policy and station):
            raise APIError(ERR_NOT_FOUND, 404, "Linked resource missing")

        # 1) settlement state in {CONFIRMED, INVOICED}
        if period.get("state") not in ("CONFIRMED", "INVOICED"):
            raise APIError(ERR_SETTLEMENT_NOT_CONFIRMED, 422, "Settlement not confirmed or invoiced")

        # 2) commissioning date eligibility
        if policy.get("min_commissioning_date") or policy.get("max_commissioning_date"):
            comm = parse_dt(station["commissioning_date"], "commissioning_date")
            if policy.get("min_commissioning_date"):
                min_c = parse_dt(policy["min_commissioning_date"], "min_commissioning_date")
                if comm < min_c:
                    raise APIError(
                        ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE,
                        422,
                        "Station commissioning_date earlier than policy minimum",
                    )
            if policy.get("max_commissioning_date"):
                max_c = parse_dt(policy["max_commissioning_date"], "max_commissioning_date")
                if comm >= max_c:
                    raise APIError(
                        ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE,
                        422,
                        "Station commissioning_date at or after policy maximum",
                    )

        # 3) eligibility window: period_end within [eligible_from, eligible_to)
        period_end = parse_dt(period["period_end"], "period_end")
        elig_from = parse_dt(policy["eligible_from"], "eligible_from")
        elig_to = parse_dt(policy["eligible_to"], "eligible_to")
        if not (elig_from <= period_end < elig_to):
            raise APIError(
                ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW,
                422,
                "period_end outside policy eligibility window",
            )

        # 4) documents
        required = set(policy.get("required_documents", []))
        present = {d.get("key") for d in decl.get("documents", [])}
        if not required.issubset(present):
            raise APIError(ERR_DOCUMENTS_INCOMPLETE, 422, "Required documents missing")

        # 5) compute amount and threshold
        claimed_kwh = D(period["grid_company_confirmed_kwh"] or 0)
        amount = round_half_up(claimed_kwh * D(policy["rate_cny_per_kwh"]), 2)
        if amount < D("0"):
            amount = D("0")
        if amount < SUBSIDY_MIN_PAYOUT_CNY:
            raise APIError(ERR_SUBSIDY_BELOW_THRESHOLD, 422, "Subsidy below minimum payout")

        decl["claimed_kwh"] = float(claimed_kwh)
        decl["subsidy_amount_cny"] = float(amount)
        decl["state"] = "SUBMITTED"
        decl["approval_due_date"] = fmt_dt(store.clock.now() + timedelta(days=APPROVAL_DUE_DAYS))
        store.bump(decl)
        return success(serializers.subsidy_declaration_view(decl))


@bp.route("/pv-ops/subsidy-declarations/<decl_id>/approve", methods=["POST"])
@require_roles("PlatformAdmin")
def approve_declaration(decl_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        decl = store.subsidy_declarations.get(decl_id)
        if not decl:
            raise APIError(ERR_NOT_FOUND, 404, "Declaration not found")
        if decl.get("state") != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Declaration must be SUBMITTED")
        decl["state"] = "APPROVED"
        store.bump(decl)
        return success(serializers.subsidy_declaration_view(decl))


@bp.route("/pv-ops/subsidy-declarations/<decl_id>/reject", methods=["POST"])
@require_roles("PlatformAdmin")
def reject_declaration(decl_id: str):
    body = get_body()
    reason = require_str(body, "reason")
    store = current_app.extensions["store"]
    with store.lock:
        decl = store.subsidy_declarations.get(decl_id)
        if not decl:
            raise APIError(ERR_NOT_FOUND, 404, "Declaration not found")
        if decl.get("state") != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Declaration must be SUBMITTED")
        decl["state"] = "REJECTED"
        decl["rejection_reason"] = reason
        store.bump(decl)
        return success(serializers.subsidy_declaration_view(decl))


@bp.route("/pv-ops/subsidy-declarations/<decl_id>/receive", methods=["POST"])
@require_roles("FinanceOfficer")
def receive_declaration(decl_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        decl = store.subsidy_declarations.get(decl_id)
        if not decl:
            raise APIError(ERR_NOT_FOUND, 404, "Declaration not found")
        if decl.get("state") not in ("APPROVED", "ARREARS"):
            raise APIError(ERR_INVALID_STATE, 409, "Declaration must be APPROVED or ARREARS")
        decl["state"] = "RECEIVED"
        decl["received_at"] = store.clock.now_iso()
        store.bump(decl)
        return success(serializers.subsidy_declaration_view(decl))


@bp.route("/pv-ops/subsidy-declarations", methods=["GET"])
@require_roles("PlatformAdmin", "FinanceOfficer")
def list_declarations():
    store = current_app.extensions["store"]
    limit, offset = parse_pagination(request.args)
    station_id = request.args.get("station_id")
    state = request.args.get("state")
    with store.lock:
        rows = list(store.subsidy_declarations.values())
        if station_id:
            rows = [r for r in rows if r.get("station_id") == station_id]
        if state:
            rows = [r for r in rows if r.get("state") == state]
        rows.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(rows, limit, offset)
        return listed(
            [serializers.subsidy_declaration_view(r) for r in page],
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=has_more,
        )
