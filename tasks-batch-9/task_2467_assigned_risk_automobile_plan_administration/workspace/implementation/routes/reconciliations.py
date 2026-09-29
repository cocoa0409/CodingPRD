"""Quota reconciliation filings on the plan's two approved measurement bases."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, new_row, touch

bp = Blueprint("reconciliations", __name__)

READ_ROLES = ("PlanAdministrator", "ComplianceExaminer", "ServicingCarrier")
BASES = ("POLICY_COUNT", "CAR_YEAR_EXPOSURE")


def _measure(carrier, period, basis):
    credit = carrier["voluntary_credit_units"]
    if basis == "POLICY_COUNT":
        obligation = Decimal(domain.carrier_quota_target(carrier))
        credited = calc.dec1(Decimal(domain.carrier_assigned_risk_count(carrier)) + credit)
        variance = calc.dec1(credited - obligation)
        return obligation, credited, variance
    total_bps = sum(
        c["voluntary_market_share_bps"]
        for c in db.carriers.values()
        if c["status"] == "ACTIVE"
    )
    total_car_years = domain.period_total_car_years(period)
    if total_bps <= 0:
        obligation = Decimal("0.0000")
    else:
        obligation = calc.rhu(
            total_car_years * Decimal(carrier["voluntary_market_share_bps"]) / Decimal(total_bps),
            4,
        )
    credited = calc.dec4(domain.carrier_car_years(carrier, period) + credit)
    variance = calc.dec4(credited - obligation)
    return obligation, credited, variance


@bp.post("/plan/quota-reconciliations")
def file_reconciliation():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    carrier_id = guards.req_str(data, "carrier_id")
    plan_period_id = guards.req_str(data, "plan_period_id")
    basis = guards.req_enum(data, "basis", BASES)
    expected_carrier_version = guards.req_int(data, "expected_carrier_version", minimum=0)

    carrier = guards.need_carrier(carrier_id)
    period = guards.need_plan_period(plan_period_id)

    if carrier["status"] != "ACTIVE":
        fail("ERR_CARRIER_NOT_ACTIVE")
    if expected_carrier_version != carrier["version"]:
        fail("ERR_STALE_CARRIER_VERSION")
    if period["status"] != "RECONCILING":
        fail("ERR_PERIOD_NOT_RECONCILING")

    obligation, credited, variance = _measure(carrier, period, basis)

    row = new_row()
    row.update(
        {
            "carrier_id": carrier["id"],
            "plan_period_id": period["id"],
            "basis": basis,
            "obligation_units": obligation,
            "credited_units": credited,
            "variance_units": variance,
            "voluntary_credit_units_applied": calc.dec1(carrier["voluntary_credit_units"]),
            "penalty_cents": calc.deficiency_penalty(variance),
            "status": "FINAL",
        }
    )

    # A later filing lawfully supersedes the prior FINAL row.
    for existing in db.reconciliations.values():
        if (
            existing["carrier_id"] == carrier["id"]
            and existing["plan_period_id"] == period["id"]
            and existing["status"] == "FINAL"
        ):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    db.reconciliations[row["id"]] = row
    touch(carrier)
    domain.bubble_period_closed(period)
    return created(domain.reconciliation_out(row))


@bp.get("/plan/quota-reconciliations")
def list_reconciliations():
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    carrier_id = request.args.get("carrier_id")
    plan_period_id = request.args.get("plan_period_id")
    basis = request.args.get("basis")
    status = request.args.get("status")

    rows = list(db.reconciliations.values())
    if carrier_id is not None:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    if plan_period_id is not None:
        rows = [r for r in rows if r["plan_period_id"] == plan_period_id]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.reconciliation_out(r) for r in page], limit, offset, total)


@bp.get("/plan/quota-reconciliations/<reconciliation_id>")
def read_reconciliation(reconciliation_id):
    guards.authenticate(READ_ROLES)
    reconciliation = guards.need_reconciliation(reconciliation_id)
    return ok(domain.reconciliation_out(reconciliation))
