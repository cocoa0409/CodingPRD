"""Acquisition underwriting and the committee cycle."""
from flask import Blueprint

import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, validate

bp = Blueprint("underwriting", __name__)

CASE_READ = ["AcquisitionAnalyst", "InvestmentCommittee", "PortfolioAdmin",
             "RegionalDirector", "OperationsManager"]

LINE_FIELDS = [F("scope_template_id", "string"), F("quantity", "count", minimum=1)]

CREATE_FIELDS = [
    F("home_id", "string"),
    F("expected_home_version", "count"),
    F("purchase_price_cents", "money", minimum=1),
    F("acquisition_closing_costs_cents", "money", minimum=0),
    F("estimated_monthly_rent_cents", "money", minimum=1),
    F("turn_reserve_annual_cents", "money", minimum=0),
    F("planned_scope_lines", "array", item_fields=LINE_FIELDS, min_items=1),
]

REVISE_FIELDS = [
    F("purchase_price_cents", "money", required=False, default=None, minimum=1),
    F("acquisition_closing_costs_cents", "money", required=False, default=None, minimum=0),
    F("estimated_monthly_rent_cents", "money", required=False, default=None, minimum=1),
    F("turn_reserve_annual_cents", "money", required=False, default=None, minimum=0),
    F("planned_scope_lines", "array", required=False, default=None,
      item_fields=LINE_FIELDS, min_items=1),
]

LIVE_CASE_STATUSES = {"DRAFT", "SUBMITTED", "REVISION_REQUESTED"}


def _check_templates(lines):
    for line in lines:
        must_find("scope_templates", line["scope_template_id"], "ERR_SCOPE_TEMPLATE_NOT_FOUND")


@bp.post("/underwriting-cases")
def create_case():
    data = validate(body_json(), CREATE_FIELDS)
    authorize(["AcquisitionAnalyst"])
    _check_templates(data["planned_scope_lines"])
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    if int(data["expected_home_version"]) != int(home["version"]):
        fail("ERR_STALE_HOME_VERSION")

    for case in store.all_rows("underwriting_cases"):
        if case["home_id"] == home["id"] and case["status"] in LIVE_CASE_STATUSES:
            case["status"] = "SUPERSEDED"
            store.touch(case)

    row = store.base_row()
    row.update({
        "home_id": home["id"],
        "purchase_price_cents": data["purchase_price_cents"],
        "acquisition_closing_costs_cents": data["acquisition_closing_costs_cents"],
        "estimated_monthly_rent_cents": data["estimated_monthly_rent_cents"],
        "turn_reserve_annual_cents": data["turn_reserve_annual_cents"],
        "planned_scope_lines": data["planned_scope_lines"],
        "planned_renovation_budget_cents": 0,
        "underwritten_effective_gross_income_cents": 0,
        "underwritten_noi_cents": 0,
        "underwritten_all_in_basis_cents": 0,
        "underwritten_yield_on_cost_bps": 0,
        "realized_renovation_cost_cents": None,
        "realized_noi_cents": None,
        "realized_all_in_basis_cents": None,
        "realized_yield_on_cost_bps": None,
        "status": "DRAFT",
        "revision_round": 0,
        "submitted_by_user_id": "",
        "decided_by_user_id": "",
        "decision_note": "",
    })
    cascades.recompute_underwritten(row)
    store.insert("underwriting_cases", row)
    return created(views.public(row))


@bp.get("/underwriting-cases/<case_id>")
def read_case(case_id):
    authorize(CASE_READ)
    row = must_find("underwriting_cases", case_id, "ERR_UNDERWRITING_CASE_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/underwriting-cases")
def list_cases():
    authorize(CASE_READ)
    rows = views.filtered("underwriting_cases", [
        ("home_id", "home_id", "string"),
        ("status", "status", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/underwriting-cases/<case_id>/submit")
def submit_case(case_id):
    role, user_id = authorize(["AcquisitionAnalyst"])
    case = must_find("underwriting_cases", case_id, "ERR_UNDERWRITING_CASE_NOT_FOUND")
    if case["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if not case["planned_scope_lines"]:
        fail("ERR_PROJECT_SCOPE_EMPTY")
    home = store.get("homes", case["home_id"])
    market = cascades.market_of(home)
    # Recompute the whole underwritten group before the floor check, but write
    # nothing until the guard has passed.
    trial = dict(case)
    cascades.recompute_underwritten(trial)
    if int(trial["underwritten_yield_on_cost_bps"]) < int(market["underwriting_yield_floor_bps"]):
        fail("ERR_YIELD_BELOW_FLOOR")
    for key in ("planned_renovation_budget_cents", "underwritten_all_in_basis_cents",
                "underwritten_effective_gross_income_cents", "underwritten_noi_cents",
                "underwritten_yield_on_cost_bps"):
        case[key] = trial[key]
    case["status"] = "SUBMITTED"
    case["submitted_by_user_id"] = user_id
    store.touch(case)
    return ok(views.public(case))


@bp.post("/underwriting-cases/<case_id>/decision")
def decide_case(case_id):
    data = validate(body_json(), [
        F("decision", "string", enum=["APPROVE", "REJECT", "REQUEST_REVISION"]),
        F("decision_note", "string", required=False, default=None),
    ])
    role, user_id = authorize(["InvestmentCommittee"])
    case = must_find("underwriting_cases", case_id, "ERR_UNDERWRITING_CASE_NOT_FOUND")
    if case["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if user_id == case["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    decision = data["decision"]
    if decision == "REQUEST_REVISION" and int(case["revision_round"]) > 1:
        fail("ERR_REVISION_LIMIT_EXCEEDED")
    home = store.get("homes", case["home_id"])
    market = cascades.market_of(home)
    if decision == "APPROVE":
        if int(case["underwritten_yield_on_cost_bps"]) < int(market["underwriting_yield_floor_bps"]):
            fail("ERR_YIELD_BELOW_FLOOR")

    if data["decision_note"] is not None:
        case["decision_note"] = data["decision_note"]

    if decision == "REQUEST_REVISION":
        case["status"] = "REVISION_REQUESTED"
        store.touch(case)
        return ok(views.public(case))

    case["decided_by_user_id"] = user_id
    if decision == "APPROVE":
        case["status"] = "APPROVED"
        store.touch(case)
        if home["asset_status"] == "PIPELINE":
            home["asset_status"] = "ACQUIRED"
            store.touch(home)
        cascades.recompute_posture(home)
        return ok(views.public(case))

    case["status"] = "REJECTED"
    store.touch(case)
    if home["asset_status"] == "PIPELINE":
        home["asset_status"] = "PASSED"
        store.touch(home)
    cascades.recompute_posture(home)
    return ok(views.public(case))


@bp.post("/underwriting-cases/<case_id>/revise")
def revise_case(case_id):
    data = validate(body_json(), REVISE_FIELDS)
    authorize(["AcquisitionAnalyst"])
    if data["planned_scope_lines"] is not None:
        _check_templates(data["planned_scope_lines"])
    case = must_find("underwriting_cases", case_id, "ERR_UNDERWRITING_CASE_NOT_FOUND")
    if case["status"] != "REVISION_REQUESTED":
        fail("ERR_INVALID_STATE")
    for name in ("purchase_price_cents", "acquisition_closing_costs_cents",
                 "estimated_monthly_rent_cents", "turn_reserve_annual_cents",
                 "planned_scope_lines"):
        if data[name] is not None:
            case[name] = data[name]
    case["status"] = "DRAFT"
    case["revision_round"] = int(case["revision_round"]) + 1
    case["submitted_by_user_id"] = ""
    cascades.recompute_underwritten(case)
    store.touch(case)
    return ok(views.public(case))
