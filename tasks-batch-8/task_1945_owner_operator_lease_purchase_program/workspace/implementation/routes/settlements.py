"""SettlementStatement routes."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import errors
import middleware
from db import db
from response import success
from services.core import base_entity, touch, run_waterfall
from services.serialize import serialize_settlement
from routes.leases import escrow_for_lease
from util import (
    get_body, req_str, req_int, req_number, req_dt, opt_bool, opt_int,
    parse_pagination, paginate,
)

bp = Blueprint("settlements", __name__)


def _get_settlement_or_404(sid):
    s = db.settlement_statements.get(sid)
    if s is None:
        raise errors.err(errors.ERR_SETTLEMENT_NOT_FOUND, "SettlementStatement not found", 404)
    return s


@bp.post("/settlement-statements")
def create_settlement():
    middleware.require_roles({"SettlementClerk"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    week_start = req_dt(body, "week_start_date")
    gross_revenue_cents = req_int(body, "gross_revenue_cents")
    fuel_gallons = req_number(body, "fuel_gallons")
    fuel_price_cents_per_gallon = req_int(body, "fuel_price_cents_per_gallon")
    insurance_weekly_cents = req_int(body, "insurance_weekly_cents")
    miles_driven = req_int(body, "miles_driven")
    load_declined_flag = opt_bool(body, "load_declined_flag", False)

    lease = db.lease_agreements.get(lease_id)
    if lease is None:
        raise errors.err(errors.ERR_LEASE_NOT_FOUND, "LeaseAgreement not found", 404)

    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)

    term_end = lease["_start_date"] + timedelta(weeks=lease["term_weeks"])
    if not (lease["_start_date"] <= week_start < term_end):
        raise errors.err(errors.ERR_WEEK_OUT_OF_TERM, "week_start_date outside the lease term", 422)

    if clock.now() < week_start + timedelta(days=7):
        raise errors.err(errors.ERR_SETTLEMENT_WEEK_NOT_CLOSED, "Settlement week is not closed", 422)

    for s in db.settlement_statements.values():
        if s["lease_id"] == lease_id and s["_week_start_date"] == week_start:
            raise errors.err(
                errors.ERR_DUPLICATE_WEEK_SETTLEMENT,
                "A settlement already exists for this (lease_id, week_start_date)",
                409,
            )

    st = base_entity()
    st.update({
        "lease_id": lease_id,
        "_week_start_date": week_start,
        "gross_revenue_cents": gross_revenue_cents,
        "fuel_gallons": fuel_gallons,
        "fuel_price_cents_per_gallon": fuel_price_cents_per_gallon,
        "insurance_weekly_cents": insurance_weekly_cents,
        "miles_driven": miles_driven,
        "load_declined_flag": load_declined_flag,
        "fuel_deduction_cents": 0,
        "maintenance_deduction_cents": 0,
        "guarantee_top_up_cents": 0,
        "escrow_contribution_cents": 0,
        "lease_payment_applied_cents": 0,
        "payment_short_flag": False,
        "net_pay_cents": 0,
        "status": "DRAFT",
    })
    escrow = escrow_for_lease(lease_id)
    run_waterfall(st, lease, escrow, maintenance_basis="provisional")
    db.settlement_statements[st["id"]] = st
    return success(serialize_settlement(st), "object", 201)


@bp.get("/settlement-statements")
def list_settlements():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.settlement_statements.values())
    lease_filter = request.args.get("lease_id")
    status_filter = request.args.get("status")
    if lease_filter is not None:
        items = [s for s in items if s["lease_id"] == lease_filter]
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_settlement(s) for s in page], "array", 200, pagination=pg)


@bp.get("/settlement-statements/<sid>")
def get_settlement(sid):
    middleware.require_roles(middleware.ALL_ROLES)
    return success(serialize_settlement(_get_settlement_or_404(sid)), "object", 200)


@bp.post("/settlement-statements/<sid>/issue")
def issue_settlement(sid):
    middleware.require_roles({"SettlementClerk"})
    st = _get_settlement_or_404(sid)
    if st["status"] != "DRAFT":
        raise errors.err(errors.ERR_SETTLEMENT_NOT_DRAFT, "Settlement is not DRAFT", 409)
    lease = db.lease_agreements[st["lease_id"]]
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)
    st["status"] = "ISSUED"
    touch(st)
    return success(serialize_settlement(st), "object", 200)


@bp.post("/settlement-statements/<sid>/dispute")
def dispute_settlement(sid):
    user_id, _ = middleware.require_roles({"Driver"})
    st = _get_settlement_or_404(sid)
    if st["status"] != "ISSUED":
        raise errors.err(errors.ERR_SETTLEMENT_NOT_ISSUED, "Settlement is not ISSUED", 409)
    lease = db.lease_agreements[st["lease_id"]]
    middleware.check_ownership(user_id, lease["owner_operator_id"])
    st["status"] = "DISPUTED"
    touch(st)
    return success(serialize_settlement(st), "object", 200)


@bp.post("/settlement-statements/<sid>/reissue")
def reissue_settlement(sid):
    middleware.require_roles({"SettlementClerk"})
    st = _get_settlement_or_404(sid)
    body = get_body()
    override = opt_int(body, "maintenance_deduction_override_cents")
    if override is None:
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            "maintenance_deduction_override_cents is required",
            400,
        )
    if st["status"] != "DISPUTED":
        raise errors.err(errors.ERR_SETTLEMENT_NOT_DISPUTED, "Settlement is not DISPUTED", 409)
    lease = db.lease_agreements[st["lease_id"]]
    escrow = escrow_for_lease(st["lease_id"])
    run_waterfall(st, lease, escrow, maintenance_basis="provisional",
                  maintenance_override_cents=override,
                  guarantee_forced_zero=(lease["status"] == "DEFAULTED"))
    st["status"] = "ISSUED"
    touch(st)
    return success(serialize_settlement(st), "object", 200)


@bp.post("/settlement-statements/<sid>/finalize")
def finalize_settlement(sid):
    middleware.require_roles({"SettlementClerk"})
    st = _get_settlement_or_404(sid)
    if st["status"] != "ISSUED":
        raise errors.err(errors.ERR_SETTLEMENT_NOT_FINALIZABLE, "Settlement is not ISSUED", 409)
    lease = db.lease_agreements[st["lease_id"]]
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)
    escrow = escrow_for_lease(st["lease_id"])

    # Final basis: actual OPERATOR-billed COMPLETED work orders in the week
    run_waterfall(st, lease, escrow, maintenance_basis="final",
                  guarantee_forced_zero=(lease["status"] == "DEFAULTED"))
    st["status"] = "FINALIZED"
    touch(st)

    # Missed-payment tracking on the lease
    if st["payment_short_flag"]:
        lease["missed_payment_count"] += 1
        lease["arrears_cents"] += lease["weekly_payment_cents"] - st["lease_payment_applied_cents"]
    lease["total_payments_applied_cents"] += st["lease_payment_applied_cents"]
    touch(lease)

    # Escrow credit cascade
    credit = st["escrow_contribution_cents"]
    if credit > 0:
        escrow["balance_cents"] += credit
        escrow["total_credited_cents"] += credit
    if escrow["status"] == "ACCUMULATING" and escrow["balance_cents"] >= lease["escrow_cap_cents"]:
        escrow["status"] = "FULL"
        lease["escrow_satisfied"] = True
    touch(escrow)

    return success(serialize_settlement(st), "object", 200)
