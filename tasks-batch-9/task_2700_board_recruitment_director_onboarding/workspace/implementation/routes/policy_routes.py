"""Governance policy, skills-matrix reference data, search firms, external
companies, the gap-analysis read and the logical clock."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEARCH_FIRM_PARTNER,
    SEATED_DIRECTOR,
    require,
    require_firm_owner,
)
from calc import gap_analysis, governing_policy, require_policy
from envelope import ok
from errors import fail
from payload import (
    body,
    check_enum,
    check_fee_pct,
    check_min,
    check_pct,
    check_range,
    check_weight,
    optional,
    parse_dt,
    required,
)
from store import clock_instant, db, iso_ms, new_row, public, touch
from vocab import CRITICALITY, FEE_MODEL, GAP_VARIANT, INDEPENDENCE_STANDARD, POLICY_STATUS

from routes.common import apply_filters, by_field, emit, emit_list, need

bp = Blueprint("policy", __name__)

READ_ALL = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
            SEATED_DIRECTOR)

# name -> (json kind, default)
POLICY_THRESHOLDS = (
    ("authorized_seats", "integer", 9),
    ("independence_min_pct", "number", 66.67),
    ("bright_line_payment_floor_cents", "integer", 100000000),
    ("bright_line_revenue_pct", "number", 2.0),
    ("bright_line_lookback_years", "integer", 3),
    ("enhanced_lookback_years", "integer", 5),
    ("enhanced_charitable_pct", "number", 2.0),
    ("max_public_boards_default", "integer", 4),
    ("max_public_boards_sitting_ceo", "integer", 2),
    ("interlock_max_shared_boards", "integer", 2),
    ("mandatory_retirement_age", "integer", 75),
    ("max_tenure_years", "integer", 15),
    ("min_completed_interviews", "integer", 3),
    ("quorum_size", "integer", 3),
    ("approval_threshold_pct", "number", 66.67),
    ("annual_cash_retainer_cents", "integer", 12000000),
    ("committee_member_fee_cents", "integer", 1500000),
    ("committee_chair_premium_cents", "integer", 2500000),
    ("equity_grant_value_cents", "integer", 20000000),
    ("ownership_multiple", "number", 5.0),
    ("ownership_grace_years", "integer", 5),
    ("education_hours_required", "number", 8.0),
    ("readiness_min_score", "number", 60.0),
)

PCT_FIELDS = ("independence_min_pct", "bright_line_revenue_pct", "enhanced_charitable_pct",
              "approval_threshold_pct")
AT_LEAST_ONE = ("authorized_seats",)


@bp.post("/policies")
def adopt_policy():
    require(CORPORATE_SECRETARY)
    b = body()
    cycle_year = required(b, "cycle_year", "integer")
    effective_from = required(b, "effective_from", "string")
    values = {}
    for name, kind, default in POLICY_THRESHOLDS:
        values[name] = optional(b, name, kind, default)
    standard = check_enum("independence_standard", optional(b, "independence_standard", "string",
                                                            "BRIGHT_LINE"), INDEPENDENCE_STANDARD)
    check_min("cycle_year", cycle_year, 2000)
    for name in PCT_FIELDS:
        check_pct(name, values[name])
    for name in AT_LEAST_ONE:
        check_min(name, values[name], 1)
    for name, kind, default in POLICY_THRESHOLDS:
        if name in PCT_FIELDS or name in AT_LEAST_ONE:
            continue
        check_min(name, values[name], 0)
    parsed = parse_dt(effective_from, "effective_from")

    # Adoption is a two-part act: every prior ACTIVE row becomes SUPERSEDED and the
    # new row is created ACTIVE, so the "only one ACTIVE policy per cycle_year"
    # invariant is maintained by the supersede step rather than by a rejection.
    # ERR_DUPLICATE_RESOURCE covers the ten rules enumerated in PRD 2.10, none of
    # which is policy adoption.
    current = governing_policy()
    if current is not None:
        incumbent = parse_dt(current["effective_from"], "effective_from")
        if parsed is not None and incumbent is not None and not parsed > incumbent:
            fail("ERR_CYCLE_YEAR_NOT_ADVANCED",
                 "effective_from must be strictly after the policy currently in force.")

    for row in db.policies.values():
        if row["status"] == "ACTIVE":
            row["status"] = "SUPERSEDED"
            touch(row)

    fields = {"cycle_year": cycle_year, "effective_from": effective_from,
              "independence_standard": standard}
    fields.update(values)
    fields["status"] = "ACTIVE"
    row = new_row(fields)
    row["_effective_sort"] = iso_ms(parsed)
    db.policies[row["id"]] = row
    return emit(row, 201)


@bp.get("/policies/<policy_id>")
def read_policy(policy_id):
    require(*READ_ALL)
    return emit(need("policy", policy_id))


@bp.get("/policies")
def list_policies():
    require(*READ_ALL)
    rows = apply_filters(list(db.policies.values()),
                         {"status": ("status", "str"), "cycle_year": ("cycle_year", "int")})
    rows = by_field(rows, "_effective_sort", reverse=True)
    return emit_list(rows)


# ---------------------------------------------------------------- skill matrix
@bp.post("/skill-categories")
def register_skill_category():
    require(GOVERNANCE_STAFF, CORPORATE_SECRETARY)
    b = body()
    code = required(b, "code", "string")
    name = required(b, "name", "string")
    weight = required(b, "strategic_weight", "number")
    minimum = required(b, "required_min_directors", "integer")
    risk = optional(b, "risk_oversight", "boolean", False)
    criticality = check_enum("criticality", optional(b, "criticality", "string", "STRATEGIC"),
                             CRITICALITY)
    check_weight("strategic_weight", weight)
    check_min("required_min_directors", minimum, 1)
    for row in db.skill_categories.values():
        if row["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE", "Skill category %s already exists." % code)
    row = new_row({
        "code": code,
        "name": name,
        "strategic_weight": weight,
        "risk_oversight": risk,
        "required_min_directors": minimum,
        "criticality": criticality,
    }, common=False)
    db.skill_categories[row["id"]] = row
    return emit(row, 201)


@bp.get("/skill-categories")
def list_skill_categories():
    require(*READ_ALL)
    rows = apply_filters(list(db.skill_categories.values()),
                         {"criticality": ("criticality", "str"),
                          "risk_oversight": ("risk_oversight", "bool")})
    rows = by_field(rows, "code")
    return emit_list(rows)


@bp.get("/skills-matrix/gap-analysis")
def read_gap_analysis():
    from flask import request
    require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "SELF_REPORTED"
    check_enum("variant", variant, GAP_VARIANT)
    require_policy()
    return ok(gap_analysis(variant))


# ---------------------------------------------------- search firms, companies
@bp.post("/search-firms")
def onboard_search_firm():
    require(CORPORATE_SECRETARY)
    b = body()
    name = required(b, "name", "string")
    contact_email = required(b, "contact_email", "string")
    tier1 = required(b, "placement_fee_pct", "number")
    tier2 = required(b, "placement_fee_tier2_pct", "number")
    fee_model = check_enum("fee_model", optional(b, "fee_model", "string", "RETAINER"), FEE_MODEL)
    retainer = optional(b, "retainer_fee_cents", "integer", 0)
    check_fee_pct("placement_fee_pct", tier1)
    check_fee_pct("placement_fee_tier2_pct", tier2)
    check_min("retainer_fee_cents", retainer, 0)
    for row in db.search_firms.values():
        if row["name"] == name:
            fail("ERR_DUPLICATE_RESOURCE", "Search firm %s already exists." % name)
    row = new_row({
        "name": name,
        "contact_email": contact_email,
        "fee_model": fee_model,
        "retainer_fee_cents": retainer,
        "placement_fee_pct": tier1,
        "placement_fee_tier2_pct": tier2,
        "placed_nominee_count": 0,
        "committed_fee_cents": 0,
        "retainer_credit_applied_cents": 0,
        "net_payable_cents": 0,
    })
    db.search_firms[row["id"]] = row
    return emit(row, 201)


@bp.get("/search-firms/<firm_id>")
def read_search_firm(firm_id):
    actor = require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, SEARCH_FIRM_PARTNER)
    require_firm_owner(actor, firm_id)
    return emit(need("search_firm", firm_id))


@bp.post("/external-companies")
def register_external_company():
    require(GOVERNANCE_STAFF, CORPORATE_SECRETARY)
    b = body()
    name = required(b, "name", "string")
    ticker = required(b, "ticker", "string")
    is_public = optional(b, "is_public", "boolean", True)
    is_competitor = optional(b, "is_competitor", "boolean", False)
    revenue = optional(b, "gross_revenue_cents", "integer", 0)
    check_min("gross_revenue_cents", revenue, 0)
    for row in db.external_companies.values():
        if row["name"] == name:
            fail("ERR_DUPLICATE_RESOURCE", "External company %s already exists." % name)
    row = new_row({
        "name": name,
        "ticker": ticker,
        "is_public": is_public,
        "is_competitor": is_competitor,
        "gross_revenue_cents": revenue,
    }, common=False)
    db.external_companies[row["id"]] = row
    return emit(row, 201)


# ----------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    from derive import recompute_compliance, refresh_director_clock_fields
    require(CORPORATE_SECRETARY)
    b = body()
    current_utc = required(b, "current_utc", "string")
    parsed = parse_dt(current_utc, "current_utc")
    policy = require_policy()
    if parsed is None or not parsed > db.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "current_utc must be strictly after the current logical clock instant.")
    db.clock = parsed
    db.clock_text = current_utc
    stale = ("RETIRED", "RESIGNED", "NOT_RENOMINATED")
    for director in list(db.directors.values()):
        refresh_director_clock_fields(director)
        if director["service_status"] not in stale:
            recompute_compliance(director, policy)
    return ok({"current_utc": current_utc, "recomputed_director_count": len(db.directors)})
