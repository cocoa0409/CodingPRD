"""Distribution and allocation endpoints (PRD 3.8)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError, bad_request
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("distributions", __name__)


def _loan_for_accrual(trust):
    return domain.funded_loan(trust) or domain.live_loan(trust) or domain.any_loan(trust)


@bp.post("/distributions")
def declare_distribution():
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    kind = middleware.req_enum(payload, "kind", C.DISTRIBUTION_KINDS)
    period_start = middleware.req_dt(payload, "period_start")
    period_end = middleware.req_dt(payload, "period_end")
    expected_trust_version = middleware.req_int(payload, "expected_trust_version")
    if period_start >= period_end:
        raise bad_request("Field 'period_start' must be strictly before 'period_end'.")

    trust = domain.require("trust", trust_id)

    # rung 9 — optimistic concurrency on the cash-bearing parent
    if expected_trust_version != trust["version"]:
        raise ApiError("ERR_STALE_TRUST_VERSION")

    if kind != "LIQUIDATING":
        domain.check_frozen(trust)
    if kind == "OPERATING":
        domain.check_restricted(trust)
    domain.check_trust_status(trust, ("OPERATING",))
    if domain.executed_lease(trust) is None:
        raise ApiError("ERR_MASTER_LEASE_NOT_EXECUTED")

    for other in db.sorted_rows(db.distributions):
        if other["trust_id"] != trust["id"] or other["status"] not in ("DECLARED", "PAID"):
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError("ERR_DISTRIBUTION_PERIOD_OVERLAP")

    window = {"period_start": period_start, "period_end": period_end}
    replenishment, days, lease = domain.distribution_replenishment(trust, window)
    loan = _loan_for_accrual(trust)
    gross = calc.provisional_gross(
        lease["base_rent_annual_cents"] if lease else 0,
        lease["supplemental_rent_annual_cents"] if lease else 0,
        loan["principal_cents"] if loan else 0,
        loan["rate_bps"] if loan else 0,
        days,
    )

    row = db.new_row(db.distributions, {
        "trust_id": trust["id"],
        "kind": kind,
        "period_start": period_start,
        "period_end": period_end,
        "provisional_amount_cents": gross - replenishment,
        "final_amount_cents": None,
        "reconciliation_delta_cents": None,
        "declared_at": clock.now(),
        "paid_at": None,
        "status": "DECLARED",
    })
    db.touch(trust)
    return created_response(db.serialize(row))


@bp.get("/distributions/<distribution_id>")
def get_distribution(distribution_id):
    return read_one("distribution", C.READ_TRUST_SIDE, distribution_id)


@bp.get("/distributions")
def list_distributions():
    return listing(db.distributions, C.READ_TRUST_SIDE,
                   str_filters=("trust_id", "status", "kind"))


@bp.post("/distributions/<distribution_id>/pay")
def pay_distribution(distribution_id):
    middleware.actor([C.TRUSTEE])
    dist = domain.require("distribution", distribution_id)
    trust = db.trusts[dist["trust_id"]]

    if dist["kind"] != "LIQUIDATING":
        domain.check_frozen(trust)
    if dist["kind"] == "OPERATING":
        domain.check_restricted(trust)
    domain.check_trust_status(trust, ("OPERATING", "WINDING_DOWN"))
    if dist["status"] != "DECLARED":
        raise ApiError("ERR_DISTRIBUTION_INVALID_STATE")
    now = clock.now()
    if now < dist["period_end"]:
        raise ApiError("ERR_DISTRIBUTION_PERIOD_NOT_ENDED")

    replenishment, _days, _lease = domain.distribution_replenishment(trust, dist)
    final_amount = domain.final_cash_gross(trust, dist) - replenishment
    if trust["operating_balance_cents"] < final_amount + replenishment:
        raise ApiError("ERR_OPERATING_CASH_INSUFFICIENT")

    dist["final_amount_cents"] = final_amount
    dist["reconciliation_delta_cents"] = final_amount - (
        dist["provisional_amount_cents"] or 0)
    dist["paid_at"] = now
    dist["status"] = "PAID"
    db.touch(dist)

    closed = domain.closed_subscriptions_of_trust(trust)
    rows = [(sub["id"], sub["units_requested"]) for sub in closed]
    for allocation in calc.allocate(final_amount, rows, trust["units_issued"]):
        db.new_row(db.allocations, {
            "distribution_id": dist["id"],
            "subscription_id": allocation["subscription_id"],
            "units": allocation["units"],
            "raw_share_cents": allocation["raw_share_cents"],
            "allocated_cents": allocation["allocated_cents"],
            "residual_adjustment_cents": allocation["residual_adjustment_cents"],
        }, journal=True)

    domain.book(trust, "DISTRIBUTION_PAYMENT", "OPERATING", -final_amount,
                "DISTRIBUTION", memo="distribution payment", occurred_at=now)
    domain.book(trust, "RESERVE_FUNDING", "OPERATING", -replenishment, "DISTRIBUTION",
                memo="reserve replenishment", occurred_at=now)
    domain.book(trust, "RESERVE_FUNDING", "RESERVE", replenishment, "DISTRIBUTION",
                memo="reserve replenishment", occurred_at=now)
    domain.recompute_trust(trust, force=True)
    return object_response(db.serialize(dist))


@bp.post("/distributions/<distribution_id>/void")
def void_distribution(distribution_id):
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    dist = domain.require("distribution", distribution_id)
    trust = db.trusts[dist["trust_id"]]
    domain.check_frozen(trust)
    if dist["status"] != "DECLARED":
        raise ApiError("ERR_DISTRIBUTION_INVALID_STATE")

    dist["status"] = "VOIDED"
    db.touch(dist)
    return object_response(db.serialize(dist))


@bp.get("/distribution-allocations/<allocation_id>")
def get_allocation(allocation_id):
    return read_one("allocation", C.READ_TRUST_SIDE, allocation_id)


@bp.get("/distribution-allocations")
def list_allocations():
    return listing(db.allocations, C.READ_TRUST_SIDE,
                   str_filters=("distribution_id", "subscription_id"))
