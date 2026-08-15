"""Originator registration, underwriting decisions, rate snapshots, risk cases."""

from __future__ import annotations

from flask import Blueprint

import db
from db import stamp_new, stamp_new_light, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_ORIGINATOR_STATUS_TERMINAL,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    SEC_CODES,
    compute_rates,
    maybe_auto_open_rate_breach_case,
)
from util import (
    get_json_body,
    optional_int,
    parse_pagination,
    paginate,
    require_enum,
    require_field,
    require_int,
    require_list,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("originators", __name__)

DECISIONS = {"APPROVE", "DECLINE"}


def get_originator_or_404(originator_id: str) -> dict:
    o = db.originators.get(originator_id)
    if o is None:
        raise_err(ERR_NOT_FOUND, "Originator not found")
    return o


@bp.route("/ach/originators", methods=["POST"])
@require_roles("OdfiUnderwriter")
def create_originator(_user_id: str, _role: str):
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    sec_codes = require_list(body, "sec_codes_allowed")
    for code in sec_codes:
        if not isinstance(code, str) or code not in SEC_CODES:
            raise_err(
                ERR_INVALID_REQUEST,
                f"sec_codes_allowed entries must be a subset of {sorted(SEC_CODES)}",
            )
    originator = {
        "legal_name": legal_name,
        "sec_codes_allowed": list(sec_codes),
        "exposure_limit_cents": 0,
        "fee_discount_bps": 0,
        "status": "PENDING_UNDERWRITING",
        "unauth_rate_bps_trailing": 0,
        "unauth_rate_bps_mtd": 0,
        "outstanding_exposure_gross_cents": 0,
        "outstanding_exposure_debit_cents": 0,
    }
    stamp_new(originator)
    db.originators[originator["id"]] = originator
    return success_object(originator, 201)


@bp.route("/ach/originators/<originator_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_originator(originator_id: str, _user_id: str, _role: str):
    return success_object(get_originator_or_404(originator_id))


@bp.route("/ach/originators/<originator_id>", methods=["PATCH"])
@require_roles("OdfiUnderwriter")
def patch_originator(originator_id: str, _user_id: str, _role: str):
    # Existence (p4)
    originator = get_originator_or_404(originator_id)
    body = get_json_body()

    # Schema (p5): OCC field required; decision enum; numeric bands; the
    # APPROVE-conditional exposure requirement is a body-schema concern.
    expected_version = require_int(body, "expected_originator_version")
    decision = body.get("decision")
    if decision is not None and decision not in DECISIONS:
        raise_err(ERR_INVALID_REQUEST, f"decision must be one of {sorted(DECISIONS)}")
    exposure = optional_int(body, "exposure_limit_cents", minimum=0)
    discount = optional_int(body, "fee_discount_bps", minimum=0, maximum=10000)
    if decision == "APPROVE" and (exposure is None or exposure <= 0):
        raise_err(
            ERR_INVALID_REQUEST,
            "decision=APPROVE requires exposure_limit_cents provided and > 0",
        )

    # State (p6): decision only from PENDING_UNDERWRITING; nothing on TERMINATED.
    if originator["status"] == "TERMINATED":
        raise_err(ERR_ORIGINATOR_STATUS_TERMINAL, "Originator is TERMINATED")
    if decision is not None and originator["status"] != "PENDING_UNDERWRITING":
        raise_err(
            ERR_ORIGINATOR_STATUS_TERMINAL,
            "decision is only valid from PENDING_UNDERWRITING",
        )

    # OCC (p7)
    if expected_version != originator["version"]:
        raise_err(ERR_STALE_VERSION, "expected_originator_version is stale")

    # Apply
    if decision == "APPROVE":
        originator["exposure_limit_cents"] = exposure
        if discount is not None:
            originator["fee_discount_bps"] = discount
        originator["status"] = "ACTIVE"
    elif decision == "DECLINE":
        originator["status"] = "TERMINATED"
    else:
        # Limit/discount maintenance (no status change).
        if exposure is not None:
            originator["exposure_limit_cents"] = exposure
        if discount is not None:
            originator["fee_discount_bps"] = discount
    touch(originator)
    return success_object(originator)


@bp.route("/ach/originators/<originator_id>/return-rate-snapshots", methods=["POST"])
@require_roles("OdfiRiskOfficer")
def create_return_rate_snapshot(originator_id: str, _user_id: str, _role: str):
    originator = get_originator_or_404(originator_id)
    computed_at = db.clock()
    rates = compute_rates(originator["id"], computed_at)
    snapshot = {
        "originator_id": originator["id"],
        "computed_at": db.format_iso(computed_at),
        "unauth_returns_60d": rates["unauth_returns_60d"],
        "debits_60d": rates["debits_60d"],
        "unauth_returns_mtd": rates["unauth_returns_mtd"],
        "debits_mtd": rates["debits_mtd"],
        "rate_bps_trailing_60d": rates["rate_bps_trailing_60d"],
        "rate_bps_mtd": rates["rate_bps_mtd"],
        "breach": rates["breach"],
    }
    stamp_new_light(snapshot)
    db.return_rate_snapshots[snapshot["id"]] = snapshot

    # Refresh the originator's rate fields (touch only on real change).
    if (
        originator["unauth_rate_bps_trailing"] != rates["rate_bps_trailing_60d"]
        or originator["unauth_rate_bps_mtd"] != rates["rate_bps_mtd"]
    ):
        originator["unauth_rate_bps_trailing"] = rates["rate_bps_trailing_60d"]
        originator["unauth_rate_bps_mtd"] = rates["rate_bps_mtd"]
        touch(originator)
    if rates["breach"]:
        maybe_auto_open_rate_breach_case(originator["id"])
    return success_object(snapshot, 201)


@bp.route("/ach/originators/<originator_id>/return-rate-snapshots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_return_rate_snapshots(originator_id: str, _user_id: str, _role: str):
    get_originator_or_404(originator_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [
            s
            for s in db.return_rate_snapshots.values()
            if s["originator_id"] == originator_id
        ]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/ach/originators/<originator_id>/risk-cases", methods=["POST"])
@require_roles("OdfiRiskOfficer")
def create_risk_case(originator_id: str, _user_id: str, _role: str):
    get_originator_or_404(originator_id)
    case = {
        "originator_id": originator_id,
        "source": "MANUAL",
        "status": "OPEN",
        "resolution_action": None,
        "resolved_by_user_id": None,
    }
    stamp_new(case)
    db.risk_cases[case["id"]] = case
    return success_object(case, 201)


@bp.route("/ach/originators/<originator_id>/risk-cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_risk_cases(originator_id: str, _user_id: str, _role: str):
    get_originator_or_404(originator_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [c for c in db.risk_cases.values() if c["originator_id"] == originator_id]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
