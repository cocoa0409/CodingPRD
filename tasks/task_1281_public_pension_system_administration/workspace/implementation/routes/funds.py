"""PensionFund endpoints: create / get / OCC-guarded patch / COLA runs."""

from flask import Blueprint

from db import store, make_entity, touch, public, now
from errors import err_not_found, err_stale_version
from middleware import auth, require_roles, body, req_field, as_int, as_number, as_str
from response import ok
from services import calcs

bp = Blueprint("funds", __name__)

ALL_ROLES = {
    "FundAdmin",
    "MemberServicesAnalyst",
    "BenefitApprover",
    "MedicalReviewer",
    "EmployerClerk",
    "Member",
    "SurvivorClaimant",
}


def serialize(fund):
    return public(fund)


def get_fund(fund_id):
    fund = store.funds.get(fund_id)
    if fund is None:
        raise err_not_found("Pension fund not found")
    return fund


@bp.post("/pension-funds")
def create_fund():
    ctx = auth()
    require_roles(ctx, {"FundAdmin"})
    data = body()
    fund_name = as_str(req_field(data, "fund_name"), "fund_name")
    cola_rate_pct = as_number(req_field(data, "cola_rate_pct"), "cola_rate_pct")
    earnings_limit = as_int(
        req_field(data, "earnings_limit_annual_cents"), "earnings_limit_annual_cents"
    )
    fund = make_entity(
        {
            "fund_name": fund_name,
            "cola_rate_pct": cola_rate_pct,
            "earnings_limit_annual_cents": earnings_limit,
        }
    )
    store.funds[fund["id"]] = fund
    return ok(serialize(fund), 201)


@bp.get("/pension-funds/<fund_id>")
def read_fund(fund_id):
    ctx = auth()
    require_roles(ctx, ALL_ROLES)
    return ok(serialize(get_fund(fund_id)))


@bp.patch("/pension-funds/<fund_id>")
def update_fund(fund_id):
    ctx = auth()
    require_roles(ctx, {"FundAdmin"})
    fund = get_fund(fund_id)
    data = body()
    # OCC: expected_fund_version, when supplied, must match the stored version
    expected = data.get("expected_fund_version")
    if expected is not None and as_int(expected, "expected_fund_version") != fund["version"]:
        raise err_stale_version("Fund version has advanced; re-read before writing")
    if "cola_rate_pct" in data and data["cola_rate_pct"] is not None:
        fund["cola_rate_pct"] = as_number(data["cola_rate_pct"], "cola_rate_pct")
    if "earnings_limit_annual_cents" in data and data["earnings_limit_annual_cents"] is not None:
        fund["earnings_limit_annual_cents"] = as_int(
            data["earnings_limit_annual_cents"], "earnings_limit_annual_cents"
        )
    touch(fund)
    return ok(serialize(fund))


@bp.post("/pension-funds/<fund_id>/cola-runs")
def cola_run(fund_id):
    ctx = auth()
    require_roles(ctx, {"FundAdmin"})
    fund = get_fund(fund_id)
    applied = 0
    skipped = 0
    today = now().date()
    for benefit in sorted(store.benefits.values(), key=lambda b: b["_seq"]):
        if benefit["status"] != "ACTIVE":
            continue  # SUSPENDED and TERMINATED are excluded entirely
        if calcs.cola_months_active(benefit, today) >= calcs.COLA_MIN_MONTHS_ACTIVE:
            benefit["monthly_amount_cents"] = calcs.cola_adjusted_amount(
                benefit["monthly_amount_cents"], fund["cola_rate_pct"]
            )
            benefit["cola_applied_count"] += 1
            touch(benefit)
            applied += 1
        else:
            skipped += 1
    return ok({"applied_count": applied, "skipped_count": skipped})
