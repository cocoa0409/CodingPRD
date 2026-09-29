"""Monthly reporting packages: benchmarks, chargebacks, the freeze, owner
review, the fee ledger and the cash waterfall."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import new_row, serialize, store, touch
from errors import ApiError
from money import as_json_number
from response import ok
from routes.common import paged
from services import calc, core
from timeutil import cmp_iso

bp = Blueprint("packages", __name__)

BENCHMARK_SOURCES = ("STR_REPORT", "MANAGER_ESTIMATE")
SERVICE_CODES = ("RESERVATIONS", "REVENUE_MANAGEMENT", "IT_HOSTING", "PROCUREMENT", "TALENT")
ALLOCATION_BASES = ("ROOMS_AVAILABLE", "GROSS_REVENUE", "HEADCOUNT", "FLAT")
REVIEW_ACTIONS = ("CONTEST", "REAFFIRM", "ADJUST")
REVIEW_ACTION_ROLES = {
    "CONTEST": ("AssetManager",),
    "REAFFIRM": ("HotelManagerOps",),
    "ADJUST": ("HotelManagerOps",),
}
DIMENSIONS = ("FINANCIAL", "BENCHMARK")
REVIEW_DECISIONS = ("ACCEPT", "DISPUTE")


# ---------------------------------------------------------------------------
# Report packages
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/report-packages")
def create_package(agreement_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    fiscal_year = v.req_int(body, "fiscal_year", ge=2000, le=2100)
    period_month = v.req_int(body, "period_month", ge=1, le=12)
    rooms = v.req_int(body, "rooms_revenue_cents", ge=0)
    fnb = v.req_int(body, "fnb_revenue_cents", ge=0)
    other = v.req_int(body, "other_revenue_cents", ge=0)
    opex = v.req_int(body, "operating_expenses_cents", ge=0)
    cash = v.req_int(body, "closing_cash_available_cents", ge=0)

    agreement = core.find_agreement(agreement_id)
    core.require_active(agreement)

    for existing in core.packages_of(agreement["id"]):
        if existing["fiscal_year"] == fiscal_year and existing["period_month"] == period_month:
            raise ApiError("ERR_PERIOD_ALREADY_REPORTED")

    package = new_row(
        {
            "agreement_id": agreement["id"],
            "fiscal_year": fiscal_year,
            "period_month": period_month,
            "rooms_revenue_cents": rooms,
            "fnb_revenue_cents": fnb,
            "other_revenue_cents": other,
            "operating_expenses_cents": opex,
            "closing_cash_available_cents": cash,
            "gross_revenue_cents": calc.gross_revenue(rooms, fnb, other),
            "allocated_centralized_cents": 0,
            "base_fee_cents": 0,
            "agop_cents": 0,
            "incentive_fee_provisional_cents": 0,
            "reported_rpi": None,
            "financial_status": "PENDING",
            "benchmark_status": "PENDING",
            "package_status": "INCOMPLETE",
            "due_date_utc": core.package_due_date(fiscal_year, period_month),
            "submitted_at": None,
            "submitted_late": False,
            "resubmission_count": 0,
        }
    )
    store.report_packages[package["id"]] = package
    return ok(serialize(package), 201)


@bp.get("/hotel-management/agreements/<agreement_id>/report-packages")
def list_packages(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = core.packages_of(agreement["id"])
    fiscal_year = v.query_int("fiscal_year")
    period_month = v.query_int("period_month")
    financial_status = v.query_str("financial_status")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    if financial_status is not None:
        rows = [r for r in rows if r["financial_status"] == financial_status]
    return paged(rows)


@bp.get("/hotel-management/report-packages/<package_id>")
def read_package(package_id):
    authenticate(READ_ROLES)
    return ok(serialize(core.find_package(package_id)))


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/report-packages/<package_id>/benchmarks")
def create_benchmark(package_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    hotel_revpar = v.req_int(body, "hotel_revpar_cents", gt=0)
    comp_revpar = v.req_int(body, "comp_set_revpar_cents", gt=0)
    rooms_available = v.req_int(body, "rooms_available", gt=0)
    source = v.req_str(body, "source")
    v.check_enum(source, BENCHMARK_SOURCES, "source")

    package = core.find_package(package_id)
    agreement = core.agreement_of_package(package)
    core.require_active(agreement)
    if package["benchmark_status"] not in ("PENDING", "CHALLENGED"):
        raise ApiError("ERR_INVALID_BENCHMARK_STATE")

    if package["benchmark_status"] == "CHALLENGED":
        for prior in core.benchmarks_of(package["id"]):
            if not prior["superseded"]:
                prior["superseded"] = True
                touch(prior)

    rpi = calc.benchmark_rpi(hotel_revpar, comp_revpar)
    row = new_row(
        {
            "report_package_id": package["id"],
            "hotel_revpar_cents": hotel_revpar,
            "comp_set_revpar_cents": comp_revpar,
            "rooms_available": rooms_available,
            "source": source,
            "rpi": as_json_number(rpi),
            "superseded": False,
        }
    )
    store.benchmarks[row["id"]] = row

    package["reported_rpi"] = row["rpi"]
    package["benchmark_status"] = "SUBMITTED"
    core.refresh_package_status(package)
    touch(package)
    return ok(serialize(row), 201)


@bp.get("/hotel-management/report-packages/<package_id>/benchmarks")
def list_benchmarks(package_id):
    authenticate(READ_ROLES)
    package = core.find_package(package_id)
    rows = core.benchmarks_of(package["id"])
    source = v.query_str("source")
    superseded = v.query_bool("superseded")
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if superseded is not None:
        rows = [r for r in rows if r["superseded"] is superseded]
    return paged(rows)


# ---------------------------------------------------------------------------
# Centralized service charges
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/report-packages/<package_id>/centralized-charges")
def create_charge(package_id):
    authenticate(["HotelManagerOps"])
    body = v.body()
    service_code = v.req_str(body, "service_code")
    allocation_basis = v.req_str(body, "allocation_basis")
    pool_amount_cents = v.req_int(body, "pool_amount_cents", gt=0)
    hotel_basis_share = v.req_number(body, "hotel_basis_share", gt=0, le=1, max_dp=6)
    allow_deferral = v.opt_bool(body, "allow_deferral", default=False)
    supporting_detail_provided = v.opt_bool(body, "supporting_detail_provided", default=False)
    v.check_enum(service_code, SERVICE_CODES, "service_code")
    v.check_enum(allocation_basis, ALLOCATION_BASES, "allocation_basis")

    package = core.find_package(package_id)
    agreement = core.agreement_of_package(package)
    core.require_active(agreement)

    existing = core.charges_of(package["id"])
    for charge in existing:
        if charge["service_code"] == service_code:
            raise ApiError("ERR_SERVICE_CODE_ALREADY_CHARGED")

    if allow_deferral and not supporting_detail_provided:
        raise ApiError("ERR_CHARGEBACK_DETAIL_REQUIRED")

    requested = calc.charge_requested_amount(pool_amount_cents, hotel_basis_share)
    if not allow_deferral:
        cap = calc.centralized_cap_cents(
            package["gross_revenue_cents"], agreement["centralized_services_cap_pct"]
        )
        cumulative = sum(c["requested_amount_cents"] for c in existing) + requested
        if cumulative > cap:
            raise ApiError("ERR_CENTRALIZED_CAP_EXCEEDED")

    charge = new_row(
        {
            "report_package_id": package["id"],
            "service_code": service_code,
            "allocation_basis": allocation_basis,
            "pool_amount_cents": pool_amount_cents,
            "hotel_basis_share": hotel_basis_share,
            "allow_deferral": allow_deferral,
            "supporting_detail_provided": supporting_detail_provided,
            "requested_amount_cents": requested,
            "allocated_amount_cents": 0,
            "deferred_amount_cents": 0,
            "disclosure_status": "DISCLOSED",
            "adjusted_amount_cents": None,
        }
    )
    store.charges[charge["id"]] = charge

    core.recompute_centralized_allocation(package, agreement)
    touch(package)
    return ok(serialize(charge), 201)


@bp.get("/hotel-management/report-packages/<package_id>/centralized-charges")
def list_charges(package_id):
    authenticate(READ_ROLES)
    package = core.find_package(package_id)
    rows = core.charges_of(package["id"])
    service_code = v.query_str("service_code")
    disclosure_status = v.query_str("disclosure_status")
    if service_code is not None:
        rows = [r for r in rows if r["service_code"] == service_code]
    if disclosure_status is not None:
        rows = [r for r in rows if r["disclosure_status"] == disclosure_status]
    return paged(rows)


def _centralized_accrual(package_id, statuses):
    rows = [
        a
        for a in core.accruals_of(package_id)
        if a["fee_type"] == "CENTRALIZED_SERVICES" and a["status"] in statuses
    ]
    return rows[-1] if rows else None


def _incentive_accrual(package_id):
    rows = [
        a
        for a in core.accruals_of(package_id)
        if a["fee_type"] == "INCENTIVE"
        and a["variant"] == "PROVISIONAL"
        and a["status"] != "REVERSED"
    ]
    return rows[-1] if rows else None


def _release_status(package):
    if package["financial_status"] == "ACCEPTED":
        return "INVOICED"
    return "ACCRUED"


@bp.post("/hotel-management/centralized-charges/<charge_id>/review")
def review_charge(charge_id):
    _user_id, role = authenticate(["AssetManager", "HotelManagerOps"])
    body = v.body()
    action = v.req_str(body, "action")
    v.opt_str(body, "note")
    if action == "ADJUST":
        v.opt_int(body, "adjusted_amount_cents")
    v.check_enum(action, REVIEW_ACTIONS, "action")

    charge = core.find_charge(charge_id)
    package = core.find_package(charge["report_package_id"])
    agreement = core.agreement_of_package(package)

    origins = {"CONTEST": ("DISCLOSED",), "REAFFIRM": ("CONTESTED",), "ADJUST": ("CONTESTED",)}
    if charge["disclosure_status"] not in origins[action]:
        raise ApiError("ERR_INVALID_CHARGE_STATE")

    if role not in REVIEW_ACTION_ROLES[action]:
        raise ApiError("ERR_ACTION_ROLE_MISMATCH")

    if action == "CONTEST":
        if package["financial_status"] not in ("SUBMITTED", "ACCEPTED"):
            raise ApiError(
                "ERR_INVALID_PACKAGE_STATE",
                "A chargeback may only be contested while the package profit-and-loss is "
                "SUBMITTED or ACCEPTED.",
            )
        charge["disclosure_status"] = "CONTESTED"
        touch(charge)
        held = _centralized_accrual(package["id"], ("ACCRUED", "INVOICED"))
        if held is not None:
            held["status"] = "DISPUTED_HELD"
            touch(held)
        return ok(serialize(charge))

    if action == "REAFFIRM":
        charge["disclosure_status"] = "DISCLOSED"
        touch(charge)
        held = _centralized_accrual(package["id"], ("DISPUTED_HELD",))
        if held is not None:
            held["status"] = _release_status(package)
            held["amount_cents"] = package["allocated_centralized_cents"]
            touch(held)
        return ok(serialize(charge))

    # ADJUST -- rule 48
    adjusted = body.get("adjusted_amount_cents")
    if (
        adjusted is None
        or isinstance(adjusted, bool)
        or not isinstance(adjusted, int)
        or adjusted < 0
        or adjusted > charge["allocated_amount_cents"]
    ):
        raise ApiError("ERR_ADJUSTMENT_OUT_OF_RANGE")

    # hop 1
    charge["disclosure_status"] = "ADJUSTED"
    charge["adjusted_amount_cents"] = adjusted
    charge["allocated_amount_cents"] = adjusted
    charge["deferred_amount_cents"] = charge["requested_amount_cents"] - adjusted
    touch(charge)

    # hop 2 -- the same pinned five-step order the freeze uses
    core.freeze_package_financials(package, agreement)
    touch(package)

    # hop 3
    incentive = _incentive_accrual(package["id"])
    if incentive is not None:
        incentive["amount_cents"] = package["incentive_fee_provisional_cents"]
        touch(incentive)
    held = _centralized_accrual(package["id"], ("DISPUTED_HELD",))
    if held is not None:
        held["status"] = _release_status(package)
        held["amount_cents"] = package["allocated_centralized_cents"]
        touch(held)
    return ok(serialize(charge))


# ---------------------------------------------------------------------------
# POST /hotel-management/report-packages/{id}/submit
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/report-packages/<package_id>/submit")
def submit_package(package_id):
    authenticate(["HotelManagerOps"])
    v.body()

    package = core.find_package(package_id)
    agreement = core.agreement_of_package(package)
    core.require_active(agreement)
    if package["financial_status"] not in ("PENDING", "DISPUTED"):
        raise ApiError("ERR_INVALID_PACKAGE_STATE")
    if not core.approved_equivalent_budget_exists(agreement["id"], package["fiscal_year"]):
        raise ApiError("ERR_BUDGET_NOT_APPROVED")

    if package["financial_status"] == "DISPUTED":
        package["resubmission_count"] = package["resubmission_count"] + 1

    package["submitted_at"] = store.now_iso
    package["submitted_late"] = cmp_iso(package["submitted_at"], package["due_date_utc"]) > 0
    core.freeze_package_financials(package, agreement)
    package["financial_status"] = "SUBMITTED"
    core.refresh_package_status(package)
    touch(package)

    core.create_accrual_set(package)
    return ok(serialize(package))


# ---------------------------------------------------------------------------
# POST /hotel-management/report-packages/{id}/owner-review
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/report-packages/<package_id>/owner-review")
def owner_review(package_id):
    authenticate(["OwnerRep"])
    body = v.body()
    dimension = v.req_str(body, "dimension")
    decision = v.req_str(body, "decision")
    v.opt_str(body, "note")
    v.check_enum(dimension, DIMENSIONS, "dimension")
    v.check_enum(decision, REVIEW_DECISIONS, "decision")

    package = core.find_package(package_id)
    agreement = core.agreement_of_package(package)

    if dimension == "BENCHMARK":
        if package["benchmark_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_BENCHMARK_STATE")
        package["benchmark_status"] = "ACCEPTED" if decision == "ACCEPT" else "CHALLENGED"
        core.refresh_package_status(package)
        touch(package)
        return ok(serialize(package))

    # FINANCIAL -- tolerated while the agreement is ACTIVE or in CURE_PERIOD
    core.require_active_or_cure(agreement)
    if package["financial_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PACKAGE_STATE")

    if decision == "DISPUTE":
        for accrual in core.accruals_of(package["id"]):
            if accrual["status"] == "ACCRUED":
                accrual["status"] = "REVERSED"
                touch(accrual)
        package["financial_status"] = "DISPUTED"
        core.refresh_package_status(package)
        touch(package)
        return ok(serialize(package))

    # ACCEPT -- four hops
    package["financial_status"] = "ACCEPTED"
    core.refresh_package_status(package)
    touch(package)

    for accrual in core.accruals_of(package["id"]):
        if accrual["status"] == "ACCRUED":
            accrual["status"] = "INVOICED"
            touch(accrual)

    distribution = core.create_distribution(package, agreement)

    if distribution["shortfall_cents"] > 0:
        core.create_working_capital_call(
            agreement, distribution["shortfall_cents"], "DISTRIBUTION_SHORTFALL", True
        )
    return ok(serialize(package))


# ---------------------------------------------------------------------------
# Fee accruals and distributions
# ---------------------------------------------------------------------------

@bp.get("/hotel-management/report-packages/<package_id>/fee-accruals")
def list_accruals(package_id):
    authenticate(READ_ROLES)
    package = core.find_package(package_id)
    rows = core.accruals_of(package["id"])
    fee_type = v.query_str("fee_type")
    variant = v.query_str("variant")
    status = v.query_str("status")
    if fee_type is not None:
        rows = [r for r in rows if r["fee_type"] == fee_type]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows)


@bp.get("/hotel-management/report-packages/<package_id>/distributions")
def list_distributions(package_id):
    authenticate(READ_ROLES)
    package = core.find_package(package_id)
    rows = core.distributions_of(package["id"])
    status = v.query_str("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows)


@bp.post("/hotel-management/distributions/<distribution_id>/execute")
def execute_distribution(distribution_id):
    authenticate(["HotelManagerOps"])
    v.body()

    distribution = core.find_distribution(distribution_id)
    package = core.find_package(distribution["report_package_id"])
    agreement = core.agreement_of_package(package)

    if agreement["distribution_hold"]:
        raise ApiError("ERR_DISTRIBUTION_ON_HOLD")
    if distribution["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE")
    for accrual in core.accruals_of(package["id"]):
        if accrual["status"] == "DISPUTED_HELD":
            raise ApiError("ERR_ACCRUALS_ON_HOLD")

    distribution["status"] = "EXECUTED"
    touch(distribution)

    restoration = distribution["wc_restoration_cents"]
    agreement["working_capital_balance_cents"] = (
        agreement["working_capital_balance_cents"] + restoration
    )
    touch(agreement)

    if agreement["working_capital_balance_cents"] >= agreement["working_capital_floor_cents"]:
        for call in core.calls_of(agreement["id"]):
            if call["reason"] == "FLOOR_RESTORATION" and call["status"] == "REQUESTED":
                call["status"] = "WAIVED_OFFSET"
                touch(call)

    _settle(package, "BASE", distribution["base_fee_paid_cents"])
    _settle(package, "INCENTIVE", distribution["incentive_fee_paid_cents"])

    if distribution["reserve_contribution_cents"] != 0:
        core.append_reserve_entry(
            agreement,
            "CONTRIBUTION",
            distribution["reserve_contribution_cents"],
            "DISTRIBUTION_EXECUTION",
            "reserve contribution from cash distribution %s" % distribution["id"],
        )
    return ok(serialize(distribution))


def _settle(package, fee_type, allocated):
    """Pay the INVOICED accruals of one bucket in created_at ASC order."""
    remaining = allocated
    for accrual in core.accruals_of(package["id"]):
        if accrual["fee_type"] != fee_type or accrual["status"] != "INVOICED":
            continue
        if fee_type == "INCENTIVE" and accrual["variant"] != "PROVISIONAL":
            continue
        if remaining <= 0:
            break
        paid = min(remaining, accrual["amount_cents"])
        if paid <= 0:
            continue
        accrual["status"] = "PAID"
        accrual["paid_amount_cents"] = paid
        touch(accrual)
        remaining -= paid
