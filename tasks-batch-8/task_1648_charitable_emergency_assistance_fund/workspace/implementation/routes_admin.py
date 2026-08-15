"""Routes: households, policies, vendors, funding sources, and the clock."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ApiError, raise_err,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_POLICY_STATE,
    ERR_INVALID_STATE, ERR_INVALID_SOURCE_STATE,
    ERR_RESERVED_FUNDS_OUTSTANDING, ERR_SOURCE_PERIOD_OVERLAP,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, reject_unknown_fields, require_fields, req_string, req_int,
    req_positive_cents, req_bool, req_enum, req_datetime, opt_string,
)

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------

@bp.post("/assistance/households")
def create_household():
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["head_of_household_name", "address", "phone",
                          "household_size", "annual_income_cents"])
    reject_unknown_fields(data, ["head_of_household_name", "address", "phone",
                                 "household_size", "annual_income_cents"])
    rec = svc.stamp_new({
        "head_of_household_name": req_string(data, "head_of_household_name"),
        "address": req_string(data, "address"),
        "phone": req_string(data, "phone"),
        "household_size": req_int(data, "household_size", minimum=1),
        "annual_income_cents": req_int(data, "annual_income_cents", minimum=0),
    })
    db.households[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/households/<hid>")
def get_household(hid):
    require_role(ALL_ROLES)
    rec = db.households.get(hid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Household not found")
    return success_object(rec)


@bp.get("/assistance/households/<hid>/benefit-summary")
def household_benefit_summary(hid):
    require_role(ALL_ROLES)
    rec = db.households.get(hid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Household not found")
    policy = svc.active_policy()
    year = db.clock.now().year
    if policy is None:
        # No active policy: report raw usage with no cap-relative fields.
        usage = svc.household_usage(hid, year, {
            "max_annual_benefit_cents": 0,
            "rent_cap_cents": 0,
            "utility_cap_cents": 0,
        })
    else:
        usage = svc.household_usage(hid, year, policy)
    return success_object(usage)


# ---------------------------------------------------------------------------
# Eligibility policies
# ---------------------------------------------------------------------------

@bp.post("/assistance/policies")
def create_policy():
    user_id = require_role(["ProgramManager"])
    data = body()
    require_fields(data, ["name", "max_annual_benefit_cents", "rent_cap_cents",
                          "utility_cap_cents", "income_limit_cents"])
    allowed = ["name", "max_annual_benefit_cents", "rent_cap_cents",
               "utility_cap_cents", "income_limit_cents", "appeal_window_days",
               "require_eviction_notice", "require_lease_ledger",
               "require_utility_bill"]
    reject_unknown_fields(data, allowed)
    rec = svc.stamp_new({
        "name": req_string(data, "name"),
        "max_annual_benefit_cents": req_positive_cents(
            data, "max_annual_benefit_cents"),
        "rent_cap_cents": req_positive_cents(data, "rent_cap_cents"),
        "utility_cap_cents": req_positive_cents(data, "utility_cap_cents"),
        "income_limit_cents": req_int(data, "income_limit_cents", minimum=0),
        "appeal_window_days": req_int(data, "appeal_window_days",
                                      required=False, minimum=1, default=30),
        "require_eviction_notice": req_bool(data, "require_eviction_notice",
                                            True),
        "require_lease_ledger": req_bool(data, "require_lease_ledger", False),
        "require_utility_bill": req_bool(data, "require_utility_bill", True),
        "status": "DRAFT",
    })
    db.policies[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/policies/<pid>")
def get_policy(pid):
    require_role(ALL_ROLES)
    rec = db.policies.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "EligibilityPolicy not found")
    return success_object(rec)


@bp.get("/assistance/policies")
def list_policies():
    require_role(ALL_ROLES)
    status = request.args.get("status")
    records = list(db.policies.values())
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/assistance/policies/<pid>/activate")
def activate_policy(pid):
    user_id = require_role(["ProgramManager"])
    rec = db.policies.get(pid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "EligibilityPolicy not found")
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_POLICY_STATE,
                  "Activate attempted on a policy not in DRAFT status")
    # Retire whichever policy is currently ACTIVE (at most one).
    for p in db.policies.values():
        if p["status"] == "ACTIVE":
            p["status"] = "RETIRED"
            svc.touch(p)
    rec["status"] = "ACTIVE"
    svc.touch(rec)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@bp.post("/assistance/vendors")
def create_vendor():
    user_id = require_role(["Caseworker", "ProgramManager"])
    data = body()
    require_fields(data, ["name", "vendor_type"])
    reject_unknown_fields(data, ["name", "vendor_type", "contact_name",
                                 "phone"])
    rec = svc.stamp_new({
        "name": req_string(data, "name"),
        "vendor_type": req_enum(data, "vendor_type", {"LANDLORD", "UTILITY"}),
        "contact_name": opt_string(data, "contact_name", ""),
        "phone": opt_string(data, "phone", ""),
        "status": "ACTIVE",
    })
    db.vendors[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/vendors/<vid>")
def get_vendor(vid):
    require_role(ALL_ROLES)
    rec = db.vendors.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Vendor not found")
    return success_object(rec)


@bp.post("/assistance/vendors/<vid>/suspend")
def suspend_vendor(vid):
    user_id = require_role(["ProgramManager"])
    rec = db.vendors.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Vendor not found")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE,
                  "Suspend attempted from a state where it does not exist")
    rec["status"] = "SUSPENDED"
    svc.touch(rec)
    return success_object(rec)


@bp.post("/assistance/vendors/<vid>/reactivate")
def reactivate_vendor(vid):
    user_id = require_role(["ProgramManager"])
    rec = db.vendors.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Vendor not found")
    if rec["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE,
                  "Reactivate attempted from a state where it does not exist")
    rec["status"] = "ACTIVE"
    svc.touch(rec)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Funding sources
# ---------------------------------------------------------------------------

def _periods_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; adjacency (end == start) is allowed."""
    return a_start < b_end and b_start < a_end


@bp.post("/assistance/funding-sources")
def create_funding_source():
    user_id = require_role(["ProgramManager"])
    data = body()
    fields = ["name", "funder_name", "source_type", "allowed_categories",
              "period_start", "period_end", "total_budget_cents",
              "max_per_household_cents"]
    require_fields(data, fields)
    reject_unknown_fields(data, fields)
    name = req_string(data, "name")
    funder_name = req_string(data, "funder_name")
    source_type = req_enum(data, "source_type",
                           {"DONOR_UNRESTRICTED", "GRANT_RESTRICTED",
                            "GOVERNMENT"})
    cats = data["allowed_categories"]
    if not isinstance(cats, list) or len(cats) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "allowed_categories must be a non-empty list")
    for c in cats:
        if c not in ("RENT", "UTILITY"):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "allowed_categories entries must be RENT or UTILITY")
    period_start = req_datetime(data, "period_start")
    period_end = req_datetime(data, "period_end")
    total_budget = req_positive_cents(data, "total_budget_cents")
    max_per_household = req_positive_cents(data, "max_per_household_cents")

    # ERR_SOURCE_PERIOD_OVERLAP: no overlap with a non-CLOSED same-funder
    # source (half-open intervals; adjacency allowed).
    new_start = db.parse_iso(period_start)
    new_end = db.parse_iso(period_end)
    for s in db.funding_sources.values():
        if s["funder_name"] != funder_name or s["status"] == "CLOSED":
            continue
        if _periods_overlap(new_start, new_end,
                            db.parse_iso(s["period_start"]),
                            db.parse_iso(s["period_end"])):
            raise_err(ERR_SOURCE_PERIOD_OVERLAP,
                      "New funding source period overlaps another non-CLOSED "
                      "source from the same funder")

    rec = svc.stamp_new({
        "name": name,
        "funder_name": funder_name,
        "source_type": source_type,
        "allowed_categories": list(cats),
        "period_start": period_start,
        "period_end": period_end,
        "total_budget_cents": total_budget,
        "max_per_household_cents": max_per_household,
        "reserved_cents": 0,
        "committed_cents": 0,
        "available_cents": total_budget,
        "status": "ACTIVE",
    })
    db.funding_sources[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/funding-sources/<sid>")
def get_funding_source(sid):
    require_role(ALL_ROLES)
    rec = db.funding_sources.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FundingSource not found")
    return success_object(rec)


@bp.get("/assistance/funding-sources")
def list_funding_sources():
    require_role(ALL_ROLES)
    status = request.args.get("status")
    records = list(db.funding_sources.values())
    if status is not None:
        records = [s for s in records if s["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/assistance/funding-sources/<sid>/deposits")
def deposit_funding_source(sid):
    user_id = require_role(["ProgramManager"])
    rec = db.funding_sources.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FundingSource not found")
    data = body()
    require_fields(data, ["amount_cents"])
    reject_unknown_fields(data, ["amount_cents"])
    amount = req_positive_cents(data, "amount_cents")
    if rec["status"] == "CLOSED":
        raise_err(ERR_INVALID_SOURCE_STATE,
                  "Deposit attempted on a CLOSED funding source")
    rec["total_budget_cents"] += amount
    svc.recompute_source(rec)
    svc.touch(rec)
    svc.refresh_source_status(rec)
    return success_object(rec)


@bp.post("/assistance/funding-sources/<sid>/close")
def close_funding_source(sid):
    user_id = require_role(["ProgramManager"])
    rec = db.funding_sources.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FundingSource not found")
    if rec["status"] == "CLOSED":
        raise_err(ERR_INVALID_SOURCE_STATE,
                  "Close attempted on a CLOSED funding source")
    svc.recompute_source(rec)
    if rec["reserved_cents"] != 0:
        raise_err(ERR_RESERVED_FUNDS_OUTSTANDING,
                  "Funding-source close attempted while reserved_cents > 0")
    rec["status"] = "CLOSED"
    svc.touch(rec)
    return success_object(rec)


@bp.get("/assistance/funding-sources/<sid>/report")
def funding_source_report(sid):
    require_role(["ProgramManager", "Auditor"])
    rec = db.funding_sources.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "FundingSource not found")
    svc.recompute_source(rec)
    budget = rec["total_budget_cents"]

    def pct(numerator):
        return float((Decimal(numerator) * Decimal(100)
                      / Decimal(budget)).quantize(
                          Decimal("0.1"), rounding=ROUND_HALF_UP))

    rent_committed = 0
    utility_committed = 0
    for a in db.allocations.values():
        if a["funding_source_id"] != sid or a["consumed_cents"] == 0:
            continue
        award = db.awards[a["award_id"]]
        app = db.applications[award["application_id"]]
        if app["category"] == "RENT":
            rent_committed += a["consumed_cents"]
        else:
            utility_committed += a["consumed_cents"]

    period_start = db.parse_iso(rec["period_start"])
    period_end = db.parse_iso(rec["period_end"])
    households_served = set()
    for p in db.payments.values():
        if p["funding_source_id"] != sid or p["status"] != "CLEARED":
            continue
        cleared = db.parse_iso(p["cleared_at"])
        if period_start <= cleared < period_end:
            award = db.awards[p["award_id"]]
            app = db.applications[award["application_id"]]
            households_served.add(app["household_id"])

    return success_object({
        "funding_source_id": sid,
        "committed_cents": rec["committed_cents"],
        "reserved_cents": rec["reserved_cents"],
        "available_cents": rec["available_cents"],
        "cash_utilization_pct": pct(rec["committed_cents"]),
        "encumbrance_utilization_pct": pct(rec["committed_cents"]
                                           + rec["reserved_cents"]),
        "rent_committed_cents": rent_committed,
        "utility_committed_cents": utility_committed,
        "households_served": len(households_served),
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
    })


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id = require_role(["ProgramManager"])
    data = body()
    require_fields(data, ["to_iso8601"])
    reject_unknown_fields(data, ["to_iso8601"])
    to_iso = req_datetime(data, "to_iso8601")
    db.clock.set(db.parse_iso(to_iso))
    return success_object({"current_utc": db.now_iso()})
