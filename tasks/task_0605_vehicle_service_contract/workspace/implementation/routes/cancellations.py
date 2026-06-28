"""Cancellations, pro-rata refund, logical clock."""
from flask import Blueprint, request, g

from db import db, fmt_iso
from errors import err
from middleware import require_roles
from response import ok, created, listing
import common as c

bp = Blueprint("cancellations", __name__)

FREE_LOOK_DAYS = 30
CANCELLATION_FEE_CENTS = 5000
DAYS_PER_MONTH = 30


@bp.route("/cancellations", methods=["POST"])
@require_roles("ContractAdmin")
def create_cancellation():
    body = c.require_body(request.get_json(silent=True))
    contract_id = c.req_field(body, "contract_id", "str")
    reason = c.req_field(body, "reason", "str")
    request_date = c.req_field(body, "request_date", "str")

    contract = c.fk_or_404(db.contracts, contract_id)

    rec = c.make_common()
    rec.update({
        "contract_id": contract_id, "reason": reason, "request_date": request_date,
        "refund_basis": None, "gross_refund_cents": 0, "cancellation_fee_cents": 0,
        "claims_offset_cents": 0, "net_refund_cents": 0, "status": "REQUESTED",
    })
    db.cancellations[rec["id"]] = rec
    contract["cancellation_id"] = rec["id"]
    c.touch(contract)
    return created(c.public(rec))


@bp.route("/cancellations/<id>", methods=["GET"])
@require_roles("ContractAdmin", "AdminUnderwriter", "Auditor")
def get_cancellation(id):
    rec = c.get_or_404(db.cancellations, id)
    return ok(c.public(rec))


def _current_odometer(contract):
    """Latest claim by claim_date, tie-break created_at ASC; else odometer_at_sale."""
    claims = [cl for cl in db.claims.values() if cl["contract_id"] == contract["id"]]
    if not claims:
        return contract["odometer_at_sale"]
    def key(cl):
        cd = c.parse_iso(cl.get("claim_date"))
        return (cd if cd is not None else c.parse_iso("1970-01-01T00:00:00Z"),
                cl["created_at"], cl.get("_seq", 0))
    latest = max(claims, key=key)
    return latest["odometer_at_claim"]


def _run_refund(cancellation, contract):
    plan = db.coverage_plans.get(contract["coverage_plan_id"])
    sale_dt = c.parse_iso(contract["sale_date"])
    now_dt = db.clock_utc
    days_in_force = c.floor_days(now_dt, sale_dt)

    if days_in_force <= FREE_LOOK_DAYS and contract["paid_claim_total_cents"] == 0:
        refund_basis = "FULL"
        gross_refund = contract["sale_price_cents"]
    else:
        term_days = plan["term_months"] * DAYS_PER_MONTH
        time_frac = min(1.0, days_in_force / term_days) if term_days > 0 else 1.0
        miles_used = max(0, _current_odometer(contract) - contract["odometer_at_sale"])
        mileage_frac = min(1.0, miles_used / plan["term_miles"]) if plan["term_miles"] > 0 else 1.0
        earned_frac = max(time_frac, mileage_frac)
        refund_basis = "PRO_RATA_MILEAGE" if mileage_frac >= time_frac else "PRO_RATA_TIME"
        gross_refund = c.round_half_up(contract["sale_price_cents"] * (1.0 - earned_frac))

    cancellation_fee = 0 if refund_basis == "FULL" else CANCELLATION_FEE_CENTS
    claims_offset = contract["paid_claim_total_cents"] if cancellation["reason"] == "DEALER_UNWIND" else 0
    net_refund = max(0, gross_refund - cancellation_fee - claims_offset)

    cancellation["refund_basis"] = refund_basis
    cancellation["gross_refund_cents"] = gross_refund
    cancellation["cancellation_fee_cents"] = cancellation_fee
    cancellation["claims_offset_cents"] = claims_offset
    cancellation["net_refund_cents"] = net_refund


@bp.route("/cancellations/<id>/approve", methods=["POST"])
@require_roles("ContractAdmin")
def approve_cancellation(id):
    cancellation = c.get_or_404(db.cancellations, id)
    if cancellation["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Cancellation not REQUESTED")
    contract = db.contracts.get(cancellation["contract_id"])
    if contract["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_CONTRACT_NOT_CANCELLABLE", "Contract not cancellable")
    for cl in db.claims.values():
        if cl["contract_id"] == contract["id"] and cl["payment_status"] == "AUTHORIZED":
            raise err("ERR_CLAIM_IN_FLIGHT", "A claim payout is in flight")
    _run_refund(cancellation, contract)
    cancellation["status"] = "APPROVED"
    c.touch(cancellation)
    c.audit(g.user_role, "Cancellation", cancellation["id"], "CANCELLATION_APPROVED")
    return ok(c.public(cancellation))


@bp.route("/cancellations/<id>/reject", methods=["POST"])
@require_roles("ContractAdmin")
def reject_cancellation(id):
    cancellation = c.get_or_404(db.cancellations, id)
    if cancellation["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Cancellation not REQUESTED")
    cancellation["status"] = "REJECTED"
    c.touch(cancellation)
    contract = db.contracts.get(cancellation["contract_id"])
    if contract is not None and contract.get("cancellation_id") == cancellation["id"]:
        contract["cancellation_id"] = None
        c.touch(contract)
    c.audit(g.user_role, "Cancellation", cancellation["id"], "CANCELLATION_REJECTED")
    return ok(c.public(cancellation))


@bp.route("/cancellations/<id>/refund", methods=["POST"])
@require_roles("ContractAdmin")
def refund_cancellation(id):
    cancellation = c.get_or_404(db.cancellations, id)
    # Structural state-transition guard (PRD §2.8 / §3 priority order): the refund
    # transition is defined only from APPROVED. From a terminal status (REFUNDED,
    # REJECTED) the transition is undefined and must surface ERR_INVALID_STATE
    # ahead of the business ERR_CANCELLATION_NOT_APPROVED check.
    if cancellation["status"] in ("REFUNDED", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Cancellation in terminal status")
    if cancellation["status"] != "APPROVED":
        raise err("ERR_CANCELLATION_NOT_APPROVED", "Cancellation not APPROVED")
    contract = db.contracts.get(cancellation["contract_id"])
    if contract["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_CONTRACT_NOT_CANCELLABLE", "Contract not cancellable")

    net_refund = cancellation["net_refund_cents"]
    cancellation["status"] = "REFUNDED"
    c.touch(cancellation)

    # cross-entity cascade
    contract["status"] = "CANCELLED"
    if net_refund != 0:
        c.post_ledger(contract["reinsurance_pool_id"], "REFUND_CLAWBACK", -net_refund,
                      "Refund clawback on cancellation", contract_id=contract["id"])
    c.touch(contract)

    for anc in db.ancillary_products.values():
        if anc["contract_id"] == contract["id"] and anc["status"] == "BUNDLED" and anc["refundable"]:
            anc["status"] = "REFUNDED"
            c.touch(anc)

    c.audit(g.user_role, "Cancellation", cancellation["id"], "CANCELLATION_REFUNDED")
    return ok(c.public(cancellation))


# ===========================================================================
# Logical Clock
# ===========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("AdminUnderwriter", "ContractAdmin", "ClaimsAdjuster")
def set_clock():
    body = c.require_body(request.get_json(silent=True))
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing to_iso8601")
    dt = c.parse_iso(body["to_iso8601"])
    if dt is None:
        raise err("ERR_CLOCK_INVALID", "Invalid ISO 8601 UTC timestamp")
    db.clock_utc = dt
    return ok({"current_utc": fmt_iso(db.clock_utc)})
