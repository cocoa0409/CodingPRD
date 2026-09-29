"""Pour-cost variance, investigations, par levels, corkage and the logical clock (PRD 3.10)."""
from decimal import Decimal

from flask import Blueprint, request

from core import (
    API_PREFIX,
    D,
    WINE_CATEGORIES,
    authorize,
    bool_param,
    check_venue_scope,
    fail,
    get_body,
    get_investigation,
    get_venue,
    iso_ms,
    new_record,
    now,
    paginate,
    parse_iso,
    q,
    respond_list,
    respond_object,
    serialize,
    sort_default,
    store,
    touch,
    validate_body,
)
from calc import corkage_quote, par_lines, pour_cost_figures
from cascade import entries_of_version, live_version_of_venue, recompute_posture

bp = Blueprint("reports", __name__)

PERIOD_SPEC = [
    {"name": "period_start", "type": "datetime", "required": True},
    {"name": "period_end", "type": "datetime", "required": True},
]


def _open_investigation_exists(venue_id):
    return any(
        inv["venue_id"] == venue_id and inv["state"] in ("OPEN", "ESCALATED")
        for inv in store.variance_investigations.values()
    )


@bp.post(API_PREFIX + "/venues/<venue_id>/pour-cost-runs")
def create_pour_cost_run(venue_id):
    authorize("BeverageDirector")
    venue = get_venue(venue_id)
    body = get_body()
    validate_body(body, PERIOD_SPEC)
    period_start = parse_iso(body["period_start"])
    period_end = parse_iso(body["period_end"])
    if not period_start < period_end:
        fail("ERR_INVALID_PERIOD", "A reporting period must start strictly before it ends.")

    figures = pour_cost_figures(venue_id, period_start, period_end)
    venue["last_variance_pct"] = figures["variance_pct"]
    venue["last_pour_cost_run_at"] = now()
    posture = recompute_posture(venue, force_touch=True)

    if posture in ("RESTRICTED", "FROZEN") and not _open_investigation_exists(venue_id):
        investigation = new_record(
            {
                "venue_id": venue_id,
                "triggered_variance_pct": figures["variance_pct"],
                "period_start": period_start,
                "period_end": period_end,
                "state": "OPEN",
                "escalation_note": None,
                "resolution_note": None,
                "resolved_at": None,
            }
        )
        store.variance_investigations[investigation["id"]] = investigation
    return respond_object(serialize(venue))


@bp.get(API_PREFIX + "/venues/<venue_id>/pour-cost-report")
def read_pour_cost_report(venue_id):
    authorize("BeverageDirector", "Controller")
    get_venue(venue_id)
    raw_start = request.args.get("period_start")
    raw_end = request.args.get("period_end")
    if raw_start is None or raw_end is None:
        fail("ERR_INVALID_REQUEST", "period_start and period_end are required.")
    period_start = parse_iso(raw_start)
    period_end = parse_iso(raw_end)
    if period_start is None or period_end is None:
        fail("ERR_INVALID_REQUEST", "period_start and period_end must be ISO 8601 instants.")
    if not period_start < period_end:
        fail("ERR_INVALID_PERIOD", "A reporting period must start strictly before it ends.")

    figures = pour_cost_figures(venue_id, period_start, period_end)
    data = {"period_start": iso_ms(period_start), "period_end": iso_ms(period_end)}
    for key in (
        "actual_pour_cost_pct",
        "theoretical_pour_cost_pct",
        "variance_pct",
        "actual_cogs_cents",
        "actual_revenue_cents",
        "theoretical_cogs_cents",
        "theoretical_revenue_cents",
        "entry_count",
    ):
        value = figures[key]
        data[key] = float(value) if isinstance(value, Decimal) else value
    return respond_object(data)


@bp.get(API_PREFIX + "/venues/<venue_id>/par-report")
def read_par_report(venue_id):
    user_id, role = authorize("BeverageDirector", "VenueSommelier")
    check_venue_scope(role, user_id, venue_id)
    get_venue(venue_id)
    version = live_version_of_venue(venue_id)
    entries = entries_of_version(version["id"]) if version is not None else []
    lines = par_lines(venue_id, entries)
    if bool_param("urgent_only"):
        lines = [line for line in lines if line["is_urgent"]]
    page, meta = paginate(lines)
    data = {
        "venue_id": venue_id,
        "generated_at": iso_ms(now()),
        "line_count": len(lines),
        "urgent_line_count": sum(1 for line in lines if line["is_urgent"]),
        "lines": page,
    }
    return respond_object(data, 200, meta)


# ---------------------------------------------------------------------------
# Variance investigations
# ---------------------------------------------------------------------------
INVESTIGATION_ROLES = ["BeverageDirector", "Controller"]


@bp.get(API_PREFIX + "/variance-investigations/<investigation_id>")
def read_investigation(investigation_id):
    authorize(INVESTIGATION_ROLES)
    return respond_object(serialize(get_investigation(investigation_id)))


@bp.get(API_PREFIX + "/variance-investigations")
def list_investigations():
    authorize(INVESTIGATION_ROLES)
    rows = list(store.variance_investigations.values())
    for field in ("venue_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


ESCALATE_SPEC = [
    {"name": "note", "type": "string", "required": True, "min_len": 1, "max_len": 500}
]
RESOLVE_SPEC = [
    {
        "name": "resolution",
        "type": "string",
        "required": True,
        "enum": ["EXPLAINED", "ADJUSTED"],
    },
    {"name": "resolution_note", "type": "string", "required": True, "min_len": 1, "max_len": 500},
]


@bp.post(API_PREFIX + "/variance-investigations/<investigation_id>/escalate")
def escalate_investigation(investigation_id):
    authorize("Controller")
    investigation = get_investigation(investigation_id)
    body = get_body()
    validate_body(body, ESCALATE_SPEC)
    if investigation["state"] != "OPEN":
        fail("ERR_INVESTIGATION_NOT_ACTIONABLE", "Only an open investigation may be escalated.")
    investigation["state"] = "ESCALATED"
    investigation["escalation_note"] = body["note"]
    touch(investigation)
    venue = store.venues.get(investigation["venue_id"])
    if venue is not None:
        recompute_posture(venue)
    return respond_object(serialize(investigation))


@bp.post(API_PREFIX + "/variance-investigations/<investigation_id>/resolve")
def resolve_investigation(investigation_id):
    authorize("Controller")
    investigation = get_investigation(investigation_id)
    body = get_body()
    validate_body(body, RESOLVE_SPEC)
    if investigation["state"] not in ("OPEN", "ESCALATED"):
        fail("ERR_INVESTIGATION_NOT_ACTIONABLE", "This investigation is already resolved.")
    adjusted = body["resolution"] == "ADJUSTED"
    investigation["state"] = "RESOLVED_ADJUSTED" if adjusted else "RESOLVED_EXPLAINED"
    investigation["resolution_note"] = body["resolution_note"]
    investigation["resolved_at"] = now()
    touch(investigation)
    venue = store.venues.get(investigation["venue_id"])
    if venue is not None:
        if adjusted:
            venue["last_variance_pct"] = D("0.00")
            recompute_posture(venue, force_touch=True)
        else:
            recompute_posture(venue)
    return respond_object(serialize(investigation))


# ---------------------------------------------------------------------------
# Corkage quote: persists nothing at all
# ---------------------------------------------------------------------------
CORKAGE_SPEC = [
    {"name": "byo_bottle_count", "type": "int", "required": True, "min": 0},
    {"name": "bottles_purchased_from_list", "type": "int", "required": True, "min": 0},
    {"name": "party_size", "type": "int", "required": True, "min": 1},
    {"name": "byo_categories", "type": "array", "required": True},
]


@bp.post(API_PREFIX + "/venues/<venue_id>/corkage-charges")
def quote_corkage(venue_id):
    user_id, role = authorize("VenueSommelier")
    check_venue_scope(role, user_id, venue_id)
    venue = get_venue(venue_id)
    body = get_body()
    validate_body(body, CORKAGE_SPEC)
    for category in body["byo_categories"]:
        if category not in WINE_CATEGORIES:
            fail("ERR_INVALID_ENUM_VALUE", "byo_categories carries an undeclared wine category.")

    prohibited = venue["byo_prohibited_categories"] or []
    for category in body["byo_categories"]:
        if category in prohibited:
            fail("ERR_BYO_CATEGORY_PROHIBITED", "This venue refuses that outside category.")
    if int(body["byo_bottle_count"]) > int(venue["byo_bottle_limit_per_party"]):
        fail("ERR_BYO_LIMIT_EXCEEDED", "That party exceeds the venue's outside-bottle limit.")

    quote = corkage_quote(
        venue,
        body["byo_bottle_count"],
        body["bottles_purchased_from_list"],
        body["party_size"],
    )
    return respond_object(quote)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
CLOCK_SPEC = [{"name": "to_iso8601", "type": "datetime", "required": True}]


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(
        "BeverageDirector", "VenueSommelier", "DistributorRep", "Controller", "ComplianceOfficer"
    )
    body = get_body()
    validate_body(body, CLOCK_SPEC)
    store.clock = parse_iso(body["to_iso8601"])
    return respond_object({}, 204)
