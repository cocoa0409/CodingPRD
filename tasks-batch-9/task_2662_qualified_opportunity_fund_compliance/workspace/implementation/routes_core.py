"""Logical clock, the deadline sweep, investors and funds."""

from flask import Blueprint

import calc
import derive
from core import (
    ALL_ROLES, API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_FUND_MANAGER,
    ROLE_INVESTOR, ROLE_PLATFORM_ADMIN, ZERO2, ZERO4, authenticate, fail, insert,
    iso, must_get, now_logical, num, object_response, pagination, rows,
    set_clock, touch,
)
from schema import F, parse_body
from serialize import dump
from support import investor_scope, listing, manager_scope, one

bp = Blueprint("core_routes", __name__, url_prefix=API_PREFIX)

TAXPAYER_TYPES = ("INDIVIDUAL", "PARTNERSHIP", "C_CORPORATION", "TRUST")
ATTESTATION_STATES = ("PENDING", "ATTESTED", "BLOCKED")
ENTITY_TYPES = ("CORPORATION", "PARTNERSHIP")
VALUATION_METHODS = ("APPLICABLE_FINANCIAL_STATEMENT", "UNADJUSTED_COST_BASIS")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def clock_set():
    authenticate((ROLE_PLATFORM_ADMIN,))
    body = parse_body([F("current_utc", "datetime")])
    previous = set_clock(body["current_utc"])
    return object_response({
        "current_utc": iso(now_logical()),
        "previous_utc": iso(previous),
    })


@bp.get("/_clock")
def clock_read():
    authenticate(ALL_ROLES)
    return object_response({"current_utc": iso(now_logical())})


# ---------------------------------------------------------------------------
# Deadline sweep
# ---------------------------------------------------------------------------

@bp.post("/ops-runs/deadline-sweep")
def deadline_sweep():
    authenticate((ROLE_PLATFORM_ADMIN,))
    parse_body([])
    clock = now_logical()

    expired = 0
    for gain in rows("eligible_gains", lambda r: (
            r["status"] in ("ELIGIBLE", "PARTIALLY_INVESTED"))):
        if clock > gain["investment_deadline"]:
            gain["status"] = "EXPIRED"
            gain["expired_at"] = clock
            touch(gain)
            expired += 1

    lapsed = 0
    for project in rows("improvement_projects", lambda r: r["status"] == "OPEN"):
        if (clock >= project["window_end"]
                and project["improvement_ratio_pct"] < calc.SI_REQUIRED_PCT):
            derive.project_lapse(project)
            lapsed += 1

    blown = 0
    from core import get
    for plan in rows("wcsh_plans", lambda r: r["status"] == "ACTIVE"):
        if clock >= plan["window_end"] and plan["unspent_amount"] > ZERO2:
            business = get("qoz_businesses", plan["qoz_business_id"])
            fund = get("funds", business["fund_id"]) if business else None
            derive.plan_blown_cascade(plan, business, fund)
            blown += 1

    return object_response({
        "expired_gain_count": expired,
        "lapsed_project_count": lapsed,
        "blown_plan_count": blown,
        "swept_at": iso(clock),
    })


# ---------------------------------------------------------------------------
# Investors
# ---------------------------------------------------------------------------

@bp.post("/investors")
def create_investor():
    authenticate((ROLE_PLATFORM_ADMIN,))
    body = parse_body([
        F("legal_name", "string", min_len=1, max_len=200, non_blank=True),
        F("taxpayer_type", "enum", enum=TAXPAYER_TYPES),
        F("tax_year_end_month", "integer", required=False, default=12,
          gte=1, lte=12),
        F("compliance_attestation_status", "enum", required=False,
          default="PENDING", enum=ATTESTATION_STATES),
    ])
    investor = insert("investors", {
        "legal_name": body["legal_name"],
        "taxpayer_type": body["taxpayer_type"],
        "tax_year_end_month": body["tax_year_end_month"],
        "compliance_attestation_status": body["compliance_attestation_status"],
        "eligible_gain_total": ZERO2,
        "deferred_gain_outstanding": ZERO2,
        "included_gain_total": ZERO2,
    })
    return one(investor, 201)


@bp.get("/investors/<investor_id>")
def read_investor(investor_id):
    authenticate((ROLE_PLATFORM_ADMIN, ROLE_COMPLIANCE_OFFICER, ROLE_INVESTOR))
    investor = must_get("investors", investor_id)
    investor_scope(investor_id)
    return one(investor)


@bp.get("/investors")
def list_investors():
    authenticate((ROLE_PLATFORM_ADMIN, ROLE_COMPLIANCE_OFFICER))
    page = pagination()
    return listing("investors",
                   [("compliance_attestation_status",
                     "compliance_attestation_status")], page)


@bp.patch("/investors/<investor_id>/attestation")
def patch_attestation(investor_id):
    authenticate((ROLE_PLATFORM_ADMIN,))
    body = parse_body([
        F("compliance_attestation_status", "enum", enum=ATTESTATION_STATES),
    ])
    investor = must_get("investors", investor_id)
    investor["compliance_attestation_status"] = body["compliance_attestation_status"]
    touch(investor)
    return one(investor)


@bp.get("/investors/<investor_id>/statement")
def investor_statement(investor_id):
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    investor = must_get("investors", investor_id)
    investor_scope(investor_id)
    elections = rows("deferral_elections",
                     lambda e: e["investor_id"] == investor_id)
    election_ids = set(e["id"] for e in elections)
    events = rows("inclusion_events",
                  lambda v: v["deferral_election_id"] in election_ids)
    return object_response({
        "investor_id": investor["id"],
        "eligible_gain_total": num(investor["eligible_gain_total"]),
        "deferred_gain_outstanding": num(investor["deferred_gain_outstanding"]),
        "included_gain_total": num(investor["included_gain_total"]),
        "election_count": len(elections),
        "inclusion_event_count": len(events),
    })


@bp.get("/investors/<investor_id>/eligible-gains")
def investor_gains(investor_id):
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("investors", investor_id)
    return listing("eligible_gains", [("status", "status")], page,
                   extra=lambda r: r["investor_id"] == investor_id)


@bp.get("/investors/<investor_id>/deferral-elections")
def investor_elections(investor_id):
    authenticate((ROLE_INVESTOR, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("investors", investor_id)
    return listing("deferral_elections", [("status", "status")], page,
                   extra=lambda r: r["investor_id"] == investor_id)


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------

@bp.post("/funds")
def create_fund():
    authenticate((ROLE_PLATFORM_ADMIN, ROLE_FUND_MANAGER))
    body = parse_body([
        F("name", "string", min_len=1, max_len=200, non_blank=True),
        F("entity_type", "enum", enum=ENTITY_TYPES),
        F("manager_user_id", "string", min_len=1, max_len=64, non_blank=True),
        F("asset_test_valuation_method", "enum", required=False,
          default="UNADJUSTED_COST_BASIS", enum=VALUATION_METHODS),
    ])
    fund = insert("funds", {
        "name": body["name"],
        "entity_type": body["entity_type"],
        "manager_user_id": body["manager_user_id"],
        "asset_test_valuation_method": body["asset_test_valuation_method"],
        "certification_status": "DRAFT",
        "compliance_posture": "UNTESTED",
        "first_taxable_month_iso8601": None,
        "self_certification_date": None,
        "aggregate_asset_basis": ZERO2,
        "aggregate_qualified_basis": ZERO2,
        "aggregate_afs_value": ZERO2,
        "aggregate_qualified_afs_value": ZERO2,
        "deferred_gain_committed": ZERO2,
        "cumulative_penalty_months": 0,
        "consecutive_failed_tests": 0,
        "last_test_measurement_date": None,
    })
    return one(fund, 201)


@bp.get("/funds/<fund_id>")
def read_fund(fund_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN, ROLE_INVESTOR))
    return one(must_get("funds", fund_id))


@bp.get("/funds")
def list_funds():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("funds", [("certification_status", "certification_status"),
                             ("compliance_posture", "compliance_posture"),
                             ("manager_user_id", "manager_user_id")], page)


@bp.post("/funds/<fund_id>/self-certify")
def self_certify(fund_id):
    authenticate((ROLE_FUND_MANAGER,))
    body = parse_body([
        F("first_taxable_month_iso8601", "datetime", month_boundary=True),
    ])
    fund = must_get("funds", fund_id)
    manager_scope(fund)
    if fund["certification_status"] == "DECERTIFIED":
        fail("ERR_FUND_DECERTIFIED", "Fund is decertified")
    if fund["certification_status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Self-certification is available only from DRAFT")
    fund["certification_status"] = "SELF_CERTIFIED"
    fund["self_certification_date"] = now_logical()
    fund["first_taxable_month_iso8601"] = body["first_taxable_month_iso8601"]
    touch(fund)
    return one(fund)


@bp.post("/funds/<fund_id>/decertify")
def decertify(fund_id):
    authenticate((ROLE_COMPLIANCE_OFFICER,))
    parse_body([F("reason_note", "string", required=False, max_len=500)])
    fund = must_get("funds", fund_id)
    if fund["certification_status"] == "DECERTIFIED":
        fail("ERR_FUND_DECERTIFIED", "Fund is already decertified")
    derive.decertify_fund(fund)
    return one(fund)


@bp.post("/funds/<fund_id>/asset-tests")
def create_asset_test(fund_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    body = parse_body([
        F("measurement_date", "datetime"),
        F("period_start", "datetime"),
        F("period_end", "datetime"),
        F("valuation_method_override", "enum", required=False,
          enum=VALUATION_METHODS),
    ])
    fund = must_get("funds", fund_id)
    manager_scope(fund)
    if fund["certification_status"] == "DECERTIFIED":
        fail("ERR_FUND_DECERTIFIED", "Fund is decertified")
    start = body["period_start"]
    end = body["period_end"]
    if not start < end:
        fail("ERR_TESTING_PERIOD_OVERLAP",
             "period_start must be strictly before period_end")
    for existing in rows("asset_tests", lambda t: t["fund_id"] == fund_id):
        if start < existing["period_end"] and existing["period_start"] < end:
            fail("ERR_TESTING_PERIOD_OVERLAP",
                 "Testing period intersects an existing period for this fund")
    test = insert("asset_tests", {
        "fund_id": fund_id,
        "measurement_date": body["measurement_date"],
        "period_start": start,
        "period_end": end,
        "valuation_method": (body["valuation_method_override"]
                             or fund["asset_test_valuation_method"]),
        "qualified_numerator": ZERO2,
        "total_denominator": ZERO2,
        "ratio_pct": ZERO4,
        "included_asset_count": 0,
        "result": "PENDING",
        "shortfall_amount": ZERO2,
        "failed_month_count": 0,
        "status": "DRAFT",
        "measured_by_user_id": None,
        "certified_by_user_id": None,
    })
    return one(test, 201)


@bp.get("/funds/<fund_id>/asset-tests")
def fund_asset_tests(fund_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("funds", fund_id)
    return listing("asset_tests", [("status", "status")], page,
                   extra=lambda r: r["fund_id"] == fund_id)
