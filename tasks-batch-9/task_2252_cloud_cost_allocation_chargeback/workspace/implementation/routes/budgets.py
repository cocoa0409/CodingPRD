"""Budget discipline (PRD 3.9)."""
from flask import Blueprint

from db import base_fields, db, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, optional_ref, require_bu_owner, serve, serve_list
from services import derived
from validation import body, opt_enum, req_int, req_interval, req_str

bp = Blueprint("budgets", __name__)

BASES = ("MAPE_BASIS", "PERIOD_END_BASIS")
READERS = ("FinOpsController", "FinOpsAnalyst", "PlatformAdmin", "BusinessUnitOwner")


@bp.route("/finops/budgets", methods=["POST"])
@authorize("FinOpsController", "FinOpsAnalyst")
def create_budget():
    data = body()
    bu = optional_ref("business_units", req_str(data, "business_unit_id"))
    (start_raw, start), (end_raw, end) = req_interval(data, "period_start", "period_end")
    amount = req_int(data, "amount_cents", exclusive_minimum=0)
    forecast = req_int(data, "forecast_cents", minimum=0)
    basis = opt_enum(data, "accuracy_basis", BASES, "MAPE_BASIS")

    for other in db.budgets.values():
        if other["business_unit_id"] != bu["id"] or other["status"] == "CLOSED":
            continue
        if start < other["_period_end_dt"] and other["_period_start_dt"] < end:
            fail(
                "ERR_BUDGET_PERIOD_DUPLICATE",
                "The business unit already holds an overlapping non-closed budget.",
            )

    budget = base_fields()
    budget.update(
        {
            "business_unit_id": bu["id"],
            "period_start": start_raw,
            "period_end": end_raw,
            "amount_cents": amount,
            "forecast_cents": forecast,
            "accuracy_basis": basis,
            "forecast_history": [],
            "status": "DRAFT",
            "actual_spend_cents": 0,
            "variance_cents": 0,
            "variance_pct": 0.00,
            "forecast_accuracy_pct": 0.00,
            "accuracy_basis_applied": None,
            "warning_flag": False,
            "variance_explanation_text": None,
            "revision_count": 0,
            "_period_start_dt": start,
            "_period_end_dt": end,
        }
    )
    db.budgets[budget["id"]] = budget
    return serve(budget, 201)


@bp.route("/finops/budgets", methods=["GET"])
@authorize(*READERS)
def list_budgets():
    return serve_list(
        db.budgets.values(),
        {"business_unit_id": "business_unit_id", "status": "status"},
    )


@bp.route("/finops/budgets/<budget_id>", methods=["GET"])
@authorize(*READERS)
def get_budget(budget_id):
    return serve(lookup("budgets", budget_id))


@bp.route("/finops/budgets/<budget_id>/activate", methods=["POST"])
@authorize("FinOpsController")
def activate_budget(budget_id):
    budget = lookup("budgets", budget_id)
    if budget["status"] != "DRAFT":
        fail("ERR_BUDGET_STATE_INVALID", "Only a DRAFT budget may be activated.")
    bu = db.business_units.get(budget["business_unit_id"])
    if bu is None or bu["status"] != "ACTIVE":
        fail("ERR_BU_SUSPENDED", "The governed business unit is not ACTIVE.")
    budget["status"] = "ACTIVE"
    touch(budget)
    return serve(budget)


@bp.route("/finops/budgets/<budget_id>/revise", methods=["POST"])
@authorize("FinOpsController", "FinOpsAnalyst")
def revise_budget(budget_id):
    budget = lookup("budgets", budget_id)
    data = body()
    expected = req_int(data, "expected_budget_version")
    forecast = req_int(data, "forecast_cents", minimum=0)

    if expected != budget["version"]:
        fail(
            "ERR_STALE_VERSION",
            "expected_budget_version %s does not match the budget version %s."
            % (expected, budget["version"]),
        )
    if budget["status"] not in ("DRAFT", "ACTIVE", "BREACHED"):
        fail("ERR_BUDGET_STATE_INVALID", "A CLOSED budget may not be revised.")

    budget["forecast_history"] = list(budget["forecast_history"]) + [budget["forecast_cents"]]
    budget["forecast_cents"] = forecast
    budget["revision_count"] = budget["revision_count"] + 1
    touch(budget)
    return serve(budget)


@bp.route("/finops/budgets/<budget_id>/evaluate", methods=["POST"])
@authorize("FinOpsController", "FinOpsAnalyst")
def evaluate_budget(budget_id):
    budget = lookup("budgets", budget_id)
    if budget["status"] not in ("ACTIVE", "BREACHED"):
        fail(
            "ERR_BUDGET_STATE_INVALID",
            "Only an ACTIVE or BREACHED budget may be evaluated.",
        )
    before = budget["version"]
    derived.budget_evaluate(budget, bump=True)
    if budget["version"] == before:
        touch(budget)
    return serve(budget)


@bp.route("/finops/budgets/<budget_id>/variance-explanation", methods=["POST"])
@authorize("BusinessUnitOwner", "FinOpsController")
def explain_variance(budget_id):
    budget = lookup("budgets", budget_id)
    require_bu_owner(budget["business_unit_id"])
    data = body()
    text = req_str(data, "variance_explanation_text")
    if budget["status"] != "BREACHED":
        fail(
            "ERR_BUDGET_STATE_INVALID",
            "Only a BREACHED budget may record a variance explanation.",
        )
    budget["variance_explanation_text"] = text
    touch(budget)
    return serve(budget)


@bp.route("/finops/budgets/<budget_id>/close", methods=["POST"])
@authorize("FinOpsController")
def close_budget(budget_id):
    budget = lookup("budgets", budget_id)
    if budget["status"] not in ("ACTIVE", "BREACHED"):
        fail("ERR_BUDGET_STATE_INVALID", "Only an ACTIVE or BREACHED budget may be closed.")
    budget["status"] = "CLOSED"
    touch(budget)
    return serve(budget)
