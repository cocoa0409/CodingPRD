"""Leases: creation, amendment, activation, return initiation/abort, monthly charge."""
from flask import Blueprint, request

from db import STORE, base_entity, touch
from errors import (
    ERR_AIRCRAFT_NOT_AVAILABLE,
    ERR_LEASE_PERIOD_OVERLAP,
    ERR_LESSEE_NOT_ACTIVE,
    ERR_RECORDS_INCOMPLETE,
    ERR_STALE_VERSION,
    ApiError,
    bad_request,
    invalid_state,
    not_found,
)
from middleware import require_lease_ownership, require_roles
from response import paginated, success
from services.calculations import CHECKLIST_TEMPLATE, monthly_charge
from services.cascades import open_return_case
from validators import (
    get_body,
    month_param,
    opt_number,
    req_date,
    req_int,
    req_str,
)

bp = Blueprint("leases", __name__)

LEASE_STATUSES = {
    "DRAFT",
    "ACTIVE",
    "RETURN_INITIATED",
    "RETURNED",
    "CLOSED",
    "DEFAULTED",
    "TERMINATED",
}
ACCRUAL_BASIS = {"ACTUAL", "MINIMUM_GUARANTEE"}
OVERLAP_BLOCKING_STATUSES = ("DRAFT", "ACTIVE", "RETURN_INITIATED", "DEFAULTED")

ADMIN_READ = ("LessorAdmin", "CreditOfficer", "LegalApprover", "FinanceManager")


def get_lease_or_404(lease_id):
    l = STORE["leases"].get(lease_id)
    if l is None:
        raise not_found("Lease not found")
    return l


@bp.post("/leasing/leases")
@require_roles("LessorAdmin")
def create_lease():
    b = get_body()
    aircraft_id = req_str(b, "aircraft_id")
    lessee_id = req_str(b, "lessee_id")
    if aircraft_id not in STORE["aircraft"]:
        raise bad_request("aircraft_id does not reference an existing aircraft")
    if lessee_id not in STORE["lessees"]:
        raise bad_request("lessee_id does not reference an existing lessee")
    start_date = req_date(b, "start_date")
    end_date = req_date(b, "end_date")
    if end_date <= start_date:
        raise bad_request("end_date must be strictly after start_date")
    monthly_rent_cents = req_int(b, "monthly_rent_cents", min_v=1)
    reserve_rate_per_fh_cents = req_int(b, "reserve_rate_per_fh_cents", min_v=0)
    reserve_rate_per_fc_cents = req_int(b, "reserve_rate_per_fc_cents", min_v=0)
    monthly_hour_cap = req_int(b, "monthly_hour_cap", min_v=1)
    accrual_basis = b.get("accrual_basis", "ACTUAL")
    if accrual_basis is None:
        accrual_basis = "ACTUAL"
    if accrual_basis not in ACCRUAL_BASIS:
        raise bad_request("accrual_basis must be one of ['ACTUAL', 'MINIMUM_GUARANTEE']")
    minimum_monthly_hours = opt_number(b, "minimum_monthly_hours", min_v=0, default=0)

    l = base_entity()
    l.update(
        {
            "aircraft_id": aircraft_id,
            "lessee_id": lessee_id,
            "start_date": start_date,
            "end_date": end_date,
            "monthly_rent_cents": monthly_rent_cents,
            "reserve_rate_per_fh_cents": reserve_rate_per_fh_cents,
            "reserve_rate_per_fc_cents": reserve_rate_per_fc_cents,
            "monthly_hour_cap": monthly_hour_cap,
            "accrual_basis": accrual_basis,
            "minimum_monthly_hours": minimum_monthly_hours,
            "status": "DRAFT",
            "reserve_accrued_cents": 0,
            "reserve_reimbursed_cents": 0,
            "reserve_forfeited_cents": 0,
            "reserve_balance_cents": 0,
            "approved_sublessee_id": None,
        }
    )
    STORE["leases"][l["id"]] = l
    return success(l, status=201)


@bp.get("/leasing/leases")
@require_roles(*ADMIN_READ)
def list_leases():
    status_f = request.args.get("status")
    if status_f is not None and status_f not in LEASE_STATUSES:
        raise bad_request("status filter is not a declared lease status")
    aircraft_f = request.args.get("aircraft_id")
    lessee_f = request.args.get("lessee_id")
    sublessee_f = request.args.get("approved_sublessee_id")
    items = list(STORE["leases"].values())
    if aircraft_f is not None:
        items = [l for l in items if l["aircraft_id"] == aircraft_f]
    if lessee_f is not None:
        items = [l for l in items if l["lessee_id"] == lessee_f]
    if sublessee_f is not None:
        items = [l for l in items if l["approved_sublessee_id"] == sublessee_f]
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    items.sort(key=lambda l: l["created_at"])
    return paginated(items)


@bp.get("/leasing/leases/<lease_id>")
@require_roles(*ADMIN_READ, "LesseeRep")
def get_lease(lease_id):
    l = get_lease_or_404(lease_id)
    require_lease_ownership(l)
    return success(l)


@bp.patch("/leasing/leases/<lease_id>")
@require_roles("LessorAdmin")
def amend_lease(lease_id):
    l = get_lease_or_404(lease_id)
    b = get_body()
    expected = b.get("expected_lease_version")
    if expected is None:
        raise bad_request("Missing required field: expected_lease_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_lease_version must be an integer")

    updates = {}
    if "monthly_rent_cents" in b and b["monthly_rent_cents"] is not None:
        updates["monthly_rent_cents"] = req_int(b, "monthly_rent_cents", min_v=1)
    if "reserve_rate_per_fh_cents" in b and b["reserve_rate_per_fh_cents"] is not None:
        updates["reserve_rate_per_fh_cents"] = req_int(
            b, "reserve_rate_per_fh_cents", min_v=0
        )
    if "reserve_rate_per_fc_cents" in b and b["reserve_rate_per_fc_cents"] is not None:
        updates["reserve_rate_per_fc_cents"] = req_int(
            b, "reserve_rate_per_fc_cents", min_v=0
        )
    if "monthly_hour_cap" in b and b["monthly_hour_cap"] is not None:
        updates["monthly_hour_cap"] = req_int(b, "monthly_hour_cap", min_v=1)
    if "minimum_monthly_hours" in b and b["minimum_monthly_hours"] is not None:
        updates["minimum_monthly_hours"] = opt_number(
            b, "minimum_monthly_hours", min_v=0
        )
    if "end_date" in b and b["end_date"] is not None:
        end_date = req_date(b, "end_date")
        if end_date <= l["start_date"]:
            raise bad_request("end_date must be strictly after start_date")
        updates["end_date"] = end_date

    if l["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state("Only a DRAFT or ACTIVE lease can be amended")
    if expected != l["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_lease_version does not match the lease's current version",
            412,
        )
    l.update(updates)
    touch(l)
    return success(l)


@bp.post("/leasing/leases/<lease_id>/activate")
@require_roles("LessorAdmin")
def activate_lease(lease_id):
    l = get_lease_or_404(lease_id)
    if l["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT lease can be activated")
    aircraft = STORE["aircraft"][l["aircraft_id"]]
    lessee = STORE["lessees"][l["lessee_id"]]

    # Records safety gate (priority 6): VERIFIED BIRTH_RECORD required.
    has_birth = any(
        d["aircraft_id"] == aircraft["id"]
        and d["doc_type"] == "BIRTH_RECORD"
        and d["status"] == "VERIFIED"
        for d in STORE["aircraft_documents"].values()
    )
    if not has_birth:
        raise ApiError(
            ERR_RECORDS_INCOMPLETE,
            "Aircraft holds no VERIFIED BIRTH_RECORD (back-to-birth anchor)",
            409,
        )

    # Overlap rule (priority 7): half-open [start, end) intersection; adjacency allowed.
    for other in STORE["leases"].values():
        if other["id"] == l["id"]:
            continue
        if other["aircraft_id"] != l["aircraft_id"]:
            continue
        if other["status"] not in OVERLAP_BLOCKING_STATUSES:
            continue
        if l["start_date"] < other["end_date"] and other["start_date"] < l["end_date"]:
            raise ApiError(
                ERR_LEASE_PERIOD_OVERLAP,
                "Lease period overlaps another non-terminal lease on this aircraft",
                409,
            )

    # Cross-entity referential checks (priority 9).
    if aircraft["status"] != "AVAILABLE":
        raise ApiError(ERR_AIRCRAFT_NOT_AVAILABLE, "Aircraft is not AVAILABLE", 409)
    if lessee["status"] != "ACTIVE":
        raise ApiError(ERR_LESSEE_NOT_ACTIVE, "Lessee is not ACTIVE", 409)

    l["status"] = "ACTIVE"
    touch(l)
    aircraft["status"] = "ON_LEASE"
    touch(aircraft)
    return success(l)


@bp.post("/leasing/leases/<lease_id>/initiate-return")
@require_roles("LessorAdmin")
def initiate_return(lease_id):
    l = get_lease_or_404(lease_id)
    if l["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE lease can initiate a return")
    if open_return_case(l["id"]) is not None:
        raise invalid_state("A non-terminal return case already exists for this lease")

    l["status"] = "RETURN_INITIATED"
    touch(l)

    case = base_entity()
    case.update(
        {
            "lease_id": l["id"],
            "status": "OPEN",
            "round_count": 0,
            "current_proposal_cents": None,
            "current_proposer_side": None,
            "reinspection_count": 0,
            "provisional_estimate_cents": 0,
            "agreed_total_cents": None,
            "reserve_applied_cents": None,
            "settlement_cash_due_cents": None,
        }
    )
    STORE["return_cases"][case["id"]] = case

    for item_code, severity in CHECKLIST_TEMPLATE:
        item = base_entity()
        item.update(
            {
                "return_case_id": case["id"],
                "item_code": item_code,
                "severity": severity,
                "status": "PENDING",
                "rectification_cost_estimate_cents": None,
                "inspected_by_id": None,
            }
        )
        STORE["checklist_items"][item["id"]] = item

    return success(l)


@bp.post("/leasing/leases/<lease_id>/abort-return")
@require_roles("LessorAdmin")
def abort_return(lease_id):
    l = get_lease_or_404(lease_id)
    if l["status"] != "RETURN_INITIATED":
        raise invalid_state("Only a RETURN_INITIATED lease can abort its return")
    case = open_return_case(l["id"])
    if case is None or case["status"] not in ("OPEN", "RECORDS_VERIFIED"):
        raise invalid_state(
            "The return can no longer be aborted once inspection has begun"
        )
    case["status"] = "CANCELLED"
    touch(case)
    l["status"] = "ACTIVE"
    touch(l)
    return success(l)


@bp.get("/leasing/leases/<lease_id>/monthly-charge")
@require_roles("LessorAdmin", "FinanceManager", "LesseeRep")
def get_monthly_charge(lease_id):
    l = get_lease_or_404(lease_id)
    require_lease_ownership(l)
    month = month_param("month")
    report = None
    for r in STORE["utilization_reports"].values():
        if (
            r["lease_id"] == l["id"]
            and r["period_month"] == month
            and r["status"] == "ACCEPTED"
        ):
            report = r
            break
    return success(monthly_charge(l, month, report))
