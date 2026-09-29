"""Logical clock, markets and the scope-template catalogue."""
from flask import Blueprint

import calc
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, ALL_ROLES, authorize, body_json, must_find, validate

bp = Blueprint("core", __name__)

STAFF_READ = ["PortfolioAdmin", "OperationsManager", "LeasingAgent", "ComplianceOfficer",
              "VendorManager", "AcquisitionAnalyst", "InvestmentCommittee", "RegionalDirector"]
CATALOGUE_READ = ["PortfolioAdmin", "OperationsManager", "AcquisitionAnalyst", "VendorManager",
                  "InvestmentCommittee", "RegionalDirector", "Vendor"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    data = validate(body_json(), [F("current_utc", "datetime")])
    authorize(["System"], require_user=False)
    from validation import parse_instant_value

    store.clock_set(parse_instant_value(data["current_utc"]), data["current_utc"])
    return ok({"current_utc": store.clock_text()})


@bp.get("/_clock")
def read_clock():
    authorize(ALL_ROLES)
    return ok({"current_utc": store.clock_text()})


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

MARKET_FIELDS = [
    F("code", "string", pattern=r"^[A-Z]{2,6}$"),
    F("name", "string"),
    F("tax_jurisdiction_code", "string"),
    F("millage_bps", "bps", minimum=1, maximum=3000),
    F("rent_index_cents", "money", minimum=1),
    F("cost_index_bps", "bps", minimum=5000, maximum=20000),
    F("cost_variance_tolerance_bps", "bps", minimum=0, maximum=10000),
    F("make_ready_target_days", "count", minimum=1),
    F("turn_holdback_cap_bps", "bps", minimum=0, maximum=10000),
    F("showing_buffer_minutes", "count", minimum=0, maximum=240),
    F("min_showing_duration_minutes", "count", minimum=5),
    F("pet_deposit_per_pet_cents", "money"),
    F("pet_deposit_cap_cents", "money"),
    F("max_pets", "count", minimum=0),
    F("restricted_breeds", "array", item_kind="string"),
    F("standard_lease_term_months", "count", minimum=1),
    F("fraud_block_threshold_bps", "bps", minimum=0, maximum=10000),
    F("rent_to_income_max_bps", "bps", minimum=0, maximum=10000),
    F("vacancy_loss_bps", "bps", minimum=0, maximum=10000),
    F("bad_debt_bps", "bps", minimum=0, maximum=10000),
    F("mgmt_fee_bps", "bps", minimum=0, maximum=10000),
    F("underwriting_yield_floor_bps", "bps", minimum=0, maximum=10000),
    F("disposition_yield_floor_bps", "bps", minimum=0, maximum=10000),
    F("max_rent_concession_bps", "bps", minimum=0, maximum=10000),
]


@bp.post("/markets")
def create_market():
    data = validate(body_json(), MARKET_FIELDS)
    authorize(["PortfolioAdmin"])
    for existing in store.all_rows("markets"):
        if existing["code"] == data["code"]:
            fail("ERR_DUPLICATE_MARKET_CODE")
    row = store.base_row()
    row.update(data)
    store.insert("markets", row)
    return created(views.public(row))


@bp.get("/markets/<market_id>")
def read_market(market_id):
    authorize(STAFF_READ)
    row = must_find("markets", market_id, "ERR_MARKET_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/markets")
def list_markets():
    authorize(STAFF_READ)
    rows = views.filtered("markets", [("code", "code", "string")])
    return paginate(rows, views.public)


# ---------------------------------------------------------------------------
# Scope templates
# ---------------------------------------------------------------------------

SCOPE_FIELDS = [
    F("code", "string"),
    F("name", "string"),
    F("certification_code", "string"),
    F("unit", "string", enum=["HOME", "SYSTEM", "SQFT", "EACH"]),
    F("benchmark_unit_cost_cents", "money", minimum=1),
    F("default_crew_size", "count", minimum=1),
    F("default_crew_days", "count", minimum=1),
    F("safety_critical", "bool", required=False, default=False),
]


@bp.post("/scope-templates")
def create_scope_template():
    data = validate(body_json(), SCOPE_FIELDS)
    authorize(["PortfolioAdmin"])
    for existing in store.all_rows("scope_templates"):
        if existing["code"] == data["code"]:
            fail("ERR_DUPLICATE_SCOPE_TEMPLATE_CODE")
    row = store.base_row()
    row.update(data)
    store.insert("scope_templates", row)
    return created(views.public(row))


@bp.get("/scope-templates/<template_id>")
def read_scope_template(template_id):
    authorize(CATALOGUE_READ)
    row = must_find("scope_templates", template_id, "ERR_SCOPE_TEMPLATE_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/scope-templates")
def list_scope_templates():
    authorize(CATALOGUE_READ)
    rows = views.filtered("scope_templates", [
        ("code", "code", "string"),
        ("certification_code", "certification_code", "string"),
        ("safety_critical", "safety_critical", "bool"),
    ])
    return paginate(rows, views.public)
