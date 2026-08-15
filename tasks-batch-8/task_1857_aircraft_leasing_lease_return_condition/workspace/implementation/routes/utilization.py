"""Utilization reports: submit, list, review (accept/dispute), revise, void."""
from flask import Blueprint

from db import STORE, base_entity, touch
from errors import ERR_DUPLICATE_REPORT_PERIOD, ApiError, invalid_state, not_found
from middleware import require_lease_ownership, require_roles
from response import paginated, success
from services.calculations import compute_accrual, recompute_aircraft_totals, recompute_balance
from validators import get_body, opt_str, req_enum, req_int, req_month, req_number

bp = Blueprint("utilization", __name__)

REVIEWABLE_LEASE_STATUSES = ("ACTIVE", "DEFAULTED", "RETURN_INITIATED")
REPORT_READ_ROLES = (
    "LessorAdmin",
    "CreditOfficer",
    "LegalApprover",
    "FinanceManager",
    "LesseeRep",
)


def get_report_or_404(report_id):
    r = STORE["utilization_reports"].get(report_id)
    if r is None:
        raise not_found("Utilization report not found")
    return r


@bp.post("/leasing/leases/<lease_id>/utilization-reports")
@require_roles("LesseeRep")
def submit_report(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    b = get_body()
    period_month = req_month(b, "period_month")
    flight_hours = req_number(b, "flight_hours", min_v=0)
    flight_cycles = req_int(b, "flight_cycles", min_v=0)

    for r in STORE["utilization_reports"].values():
        if (
            r["lease_id"] == lease["id"]
            and r["period_month"] == period_month
            and r["status"] != "VOIDED"
        ):
            raise ApiError(
                ERR_DUPLICATE_REPORT_PERIOD,
                "A non-VOIDED report already exists for this lease and period_month",
                409,
            )

    r = base_entity()
    r.update(
        {
            "lease_id": lease["id"],
            "period_month": period_month,
            "flight_hours": flight_hours,
            "flight_cycles": flight_cycles,
            "status": "SUBMITTED",
            "dispute_reason": None,
            "posted_accrual_cents": 0,
        }
    )
    STORE["utilization_reports"][r["id"]] = r
    return success(r, status=201)


@bp.get("/leasing/leases/<lease_id>/utilization-reports")
@require_roles(*REPORT_READ_ROLES)
def list_reports(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    items = [r for r in STORE["utilization_reports"].values() if r["lease_id"] == lease["id"]]
    items.sort(key=lambda r: (r["period_month"], r["created_at"]))
    return paginated(items)


@bp.post("/leasing/utilization-reports/<report_id>/review")
@require_roles("LessorAdmin")
def review_report(report_id):
    r = get_report_or_404(report_id)
    b = get_body()
    decision = req_enum(b, "decision", {"ACCEPT", "DISPUTE"})
    if r["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED report can be reviewed")
    lease = STORE["leases"][r["lease_id"]]

    if decision == "DISPUTE":
        r["dispute_reason"] = opt_str(b, "reason", None)
        r["status"] = "DISPUTED"
        touch(r)
        return success(r)

    # ACCEPT
    if lease["status"] not in REVIEWABLE_LEASE_STATUSES:
        raise invalid_state(
            "Reports can be accepted only while the lease is ACTIVE, DEFAULTED, or RETURN_INITIATED"
        )
    accrual = compute_accrual(lease, r)
    r["posted_accrual_cents"] = accrual
    r["status"] = "ACCEPTED"
    touch(r)

    lease["reserve_accrued_cents"] += accrual
    recompute_balance(lease)
    touch(lease)

    recompute_aircraft_totals(lease["aircraft_id"])
    aircraft = STORE["aircraft"][lease["aircraft_id"]]
    touch(aircraft)
    return success(r)


@bp.post("/leasing/utilization-reports/<report_id>/revise")
@require_roles("LesseeRep")
def revise_report(report_id):
    r = get_report_or_404(report_id)
    lease = STORE["leases"][r["lease_id"]]
    require_lease_ownership(lease)
    b = get_body()
    flight_hours = req_number(b, "flight_hours", min_v=0)
    flight_cycles = req_int(b, "flight_cycles", min_v=0)
    if r["status"] != "DISPUTED":
        raise invalid_state("Only a DISPUTED report can be revised")
    r["flight_hours"] = flight_hours
    r["flight_cycles"] = flight_cycles
    r["dispute_reason"] = None
    r["status"] = "SUBMITTED"
    touch(r)
    return success(r)


@bp.post("/leasing/utilization-reports/<report_id>/void")
@require_roles("LessorAdmin")
def void_report(report_id):
    r = get_report_or_404(report_id)
    if r["status"] != "ACCEPTED":
        raise invalid_state("Only an ACCEPTED report can be voided")
    lease = STORE["leases"][r["lease_id"]]
    if lease["status"] not in REVIEWABLE_LEASE_STATUSES:
        raise invalid_state(
            "Reports can be voided only while the lease is ACTIVE, DEFAULTED, or RETURN_INITIATED"
        )
    lease["reserve_accrued_cents"] -= r["posted_accrual_cents"]
    recompute_balance(lease)
    touch(lease)

    r["status"] = "VOIDED"
    touch(r)

    recompute_aircraft_totals(lease["aircraft_id"])
    aircraft = STORE["aircraft"][lease["aircraft_id"]]
    touch(aircraft)
    return success(r)
