"""Project lifecycle, commercial ledger and milestone administration."""

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from clock import dec, money
from errors import fail
from routes.common import paginate, filter_eq, project_substation_energized
from validate import ALL_ROLES, authorize, body, dy, e, i, n, s

bp = Blueprint("projects", __name__)

MILESTONE_KINDS = ("MECHANICAL_COMPLETION", "SUBSTANTIAL_COMPLETION", "FINAL_ACCEPTANCE")
MILESTONE_STATES = (
    "PRECONSTRUCTION",
    "MC_CLAIMED",
    "MC_CERTIFIED",
    "SC_CLAIMED",
    "SC_CERTIFIED",
    "FA_CLAIMED",
    "FINAL_ACCEPTED",
)


@bp.post("/solar/projects")
def create_project():
    authorize("EpcProjectManager")
    data = body(
        s("name"),
        s("utility_name"),
        n("ac_capacity_kw", gt=0),
        n("dc_capacity_kw", gt=0),
        i("contract_value_cents", gt=0),
        n("retainage_pct", ge=0, le=0.10),
        i("ld_per_day_cents", ge=0),
        n("ld_cap_pct", ge=0, le=0.20),
        dy("sc_deadline_date"),
        n("guaranteed_capacity_kw_ac", gt=0),
        n("guaranteed_performance_ratio", gt=0, lt=1),
        e("prevailing_wage_election", ("STRICT", "REMEDIABLE"), required=False, default="REMEDIABLE"),
        e(
            "apprenticeship_basis",
            ("PROJECT_AGGREGATE", "WEEKLY_WORST_CASE"),
            required=False,
            default="PROJECT_AGGREGATE",
        ),
        n("apprenticeship_min_pct", required=False, default=15.00, ge=0, le=100),
    )
    row = store.base()
    row.update(
        {
            "name": data["name"],
            "utility_name": data["utility_name"],
            "ac_capacity_kw": data["ac_capacity_kw"],
            "dc_capacity_kw": data["dc_capacity_kw"],
            "contract_value_cents": data["contract_value_cents"],
            "approved_change_order_cents": 0,
            "retainage_pct": data["retainage_pct"],
            "ld_per_day_cents": data["ld_per_day_cents"],
            "ld_cap_pct": data["ld_cap_pct"],
            "sc_deadline_date": data["sc_deadline_date"],
            "guaranteed_capacity_kw_ac": data["guaranteed_capacity_kw_ac"],
            "guaranteed_performance_ratio": data["guaranteed_performance_ratio"],
            "prevailing_wage_election": data["prevailing_wage_election"],
            "apprenticeship_basis": data["apprenticeship_basis"],
            "apprenticeship_min_pct": data["apprenticeship_min_pct"],
            "milestone_state": "PRECONSTRUCTION",
            "mc_readiness": "BLOCKED",
            "blocks_total": 0,
            "blocks_mc_ready_count": 0,
            "total_labor_hours": 0,
            "apprentice_labor_hours": 0,
            "apprentice_hours_pct": 0,
            "apprenticeship_basis_applied": None,
            "wage_restitution_owed_cents": 0,
            "wage_liquidated_damages_cents": 0,
            "tax_credit_status": "UNDETERMINED",
            "open_punch_item_count": 0,
            "open_critical_punch_count": 0,
            "delay_days": 0,
            "ld_assessed_cents": 0,
            "retainage_held_cents": 0,
            "punchlist_holdback_cents": 0,
            "sc_payment_due_cents": 0,
            "final_payment_cents": 0,
            "mc_claimed_by_user_id": None,
            "last_milestone_rejection_reason": None,
            "_sc_settled": False,
            "_ld_cap_cents": 0,
        }
    )
    store.projects[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/projects/<project_id>")
def get_project(project_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_project(project_id))


@bp.get("/solar/projects")
def list_projects():
    authorize(*ALL_ROLES)
    rows = store.ordered(list(store.projects.values()))
    rows = filter_eq(rows, "milestone_state", validate.q("milestone_state"))
    rows = filter_eq(rows, "mc_readiness", validate.q("mc_readiness"))
    return paginate(rows)


@bp.get("/solar/projects/<project_id>/settlement-summary")
def settlement_summary(project_id):
    authorize(*ALL_ROLES)
    project = store.require_project(project_id)
    return envelope.ok(
        {
            "adjusted_contract_cents": calc.adjusted_contract(project),
            "delay_days": project["delay_days"],
            "ld_cap_cents": project["_ld_cap_cents"],
            "ld_assessed_cents": project["ld_assessed_cents"],
            "retainage_held_cents": project["retainage_held_cents"],
            "punchlist_holdback_cents": project["punchlist_holdback_cents"],
            "sc_payment_due_cents": project["sc_payment_due_cents"],
            "final_payment_cents": project["final_payment_cents"],
            "open_punch_item_count": project["open_punch_item_count"],
            "open_critical_punch_count": project["open_critical_punch_count"],
            "tax_credit_status": project["tax_credit_status"],
        }
    )


@bp.post("/solar/projects/<project_id>/change-orders")
def create_change_order(project_id):
    authorize("EpcProjectManager")
    data = body(i("amount_cents"), s("reason"))
    project = store.require_project(project_id)
    if project["milestone_state"] == "FINAL_ACCEPTED":
        fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
    candidate = project["approved_change_order_cents"] + data["amount_cents"]
    if candidate > calc.change_order_cap(project):
        fail("ERR_CHANGE_ORDER_CAP_EXCEEDED")
    project["approved_change_order_cents"] = candidate
    store.touch(project)
    return envelope.ok(project)


@bp.post("/solar/projects/<project_id>/labor-compliance-runs")
def labor_compliance_run(project_id):
    authorize("LaborComplianceOfficer")
    data = body(
        e(
            "basis_override",
            ("PROJECT_AGGREGATE", "WEEKLY_WORST_CASE"),
            required=False,
        )
    )
    project = store.require_project(project_id)
    basis = data["basis_override"] or project["apprenticeship_basis"]
    pct = calc.apprenticeship_pct(project, basis)
    owed, penalty = calc.wage_restitution(project)
    qualified = dec(pct) >= dec(project["apprenticeship_min_pct"])
    project["apprentice_hours_pct"] = pct
    project["apprenticeship_basis_applied"] = basis
    project["wage_restitution_owed_cents"] = owed
    project["wage_liquidated_damages_cents"] = penalty
    project["tax_credit_status"] = "QUALIFIED" if (qualified and owed == 0) else "DISQUALIFIED"
    store.touch(project)
    return envelope.ok(project)


@bp.post("/solar/projects/<project_id>/milestone-claims")
def milestone_claim(project_id):
    authorize("EpcProjectManager")
    data = body(e("milestone_kind", MILESTONE_KINDS))
    project = store.require_project(project_id)
    kind = data["milestone_kind"]
    user_id = validate.actor()[0]

    if kind == "MECHANICAL_COMPLETION":
        if project["milestone_state"] != "PRECONSTRUCTION":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if project["mc_readiness"] != "READY":
            fail("ERR_BLOCKS_NOT_MC_READY")
        project["milestone_state"] = "MC_CLAIMED"
        project["mc_claimed_by_user_id"] = user_id
    elif kind == "SUBSTANTIAL_COMPLETION":
        if project["milestone_state"] != "MC_CERTIFIED":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if not project_substation_energized(project_id):
            fail("ERR_SUBSTATION_NOT_ENERGIZED")
        if not calc.passed_test_exists(project_id, "CAPACITY"):
            fail("ERR_REQUIRED_TEST_NOT_PASSED")
        if project["open_critical_punch_count"] != 0:
            fail("ERR_OPEN_CRITICAL_PUNCH_ITEMS")
        project["milestone_state"] = "SC_CLAIMED"
    else:
        if project["milestone_state"] != "SC_CERTIFIED":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if not calc.passed_test_exists(project_id, "PERFORMANCE_RATIO"):
            fail("ERR_REQUIRED_TEST_NOT_PASSED")
        if project["open_punch_item_count"] != 0:
            fail("ERR_OPEN_PUNCH_ITEMS")
        if project["tax_credit_status"] != "QUALIFIED":
            fail("ERR_TAX_CREDIT_NOT_QUALIFIED")
        project["milestone_state"] = "FA_CLAIMED"

    store.touch(project)
    return envelope.ok(project)


@bp.post("/solar/projects/<project_id>/milestone-decisions")
def milestone_decision(project_id):
    authorize("OwnerEngineer")
    data = body(
        e("milestone_kind", MILESTONE_KINDS),
        e("decision", ("CERTIFY", "REJECT")),
        s("reason", required=False),
    )
    project = store.require_project(project_id)
    kind = data["milestone_kind"]
    decision = data["decision"]
    user_id = validate.actor()[0]

    if kind == "MECHANICAL_COMPLETION":
        if project["milestone_state"] != "MC_CLAIMED":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if project["mc_claimed_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")
        if decision == "CERTIFY":
            if project["mc_readiness"] != "READY":
                fail("ERR_BLOCKS_NOT_MC_READY")
            project["milestone_state"] = "MC_CERTIFIED"
        else:
            project["milestone_state"] = "PRECONSTRUCTION"
            project["last_milestone_rejection_reason"] = data["reason"]
        project["mc_claimed_by_user_id"] = None
    elif kind == "SUBSTANTIAL_COMPLETION":
        if project["milestone_state"] != "SC_CLAIMED":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if decision == "CERTIFY":
            if project["open_critical_punch_count"] != 0:
                fail("ERR_OPEN_CRITICAL_PUNCH_ITEMS")
            result = calc.substantial_completion_settlement(project)
            project["delay_days"] = result["ld_delay_days"]
            project["ld_assessed_cents"] = result["ld_assessed_cents"]
            project["retainage_held_cents"] = result["retainage_held_cents"]
            project["punchlist_holdback_cents"] = result["punchlist_holdback_cents"]
            project["sc_payment_due_cents"] = result["sc_payment_due_cents"]
            project["_ld_cap_cents"] = result["ld_cap_cents"]
            project["_sc_settled"] = True
            project["milestone_state"] = "SC_CERTIFIED"
        else:
            project["milestone_state"] = "MC_CERTIFIED"
            project["last_milestone_rejection_reason"] = data["reason"]
    else:
        if project["milestone_state"] != "FA_CLAIMED":
            fail("ERR_MILESTONE_OUT_OF_SEQUENCE")
        if decision == "CERTIFY":
            if project["open_punch_item_count"] != 0:
                fail("ERR_OPEN_PUNCH_ITEMS")
            if project["tax_credit_status"] != "QUALIFIED":
                fail("ERR_TAX_CREDIT_NOT_QUALIFIED")
            project["final_payment_cents"] = (
                project["retainage_held_cents"] + project["punchlist_holdback_cents"]
            )
            project["milestone_state"] = "FINAL_ACCEPTED"
        else:
            project["milestone_state"] = "SC_CERTIFIED"
            project["last_milestone_rejection_reason"] = data["reason"]

    store.touch(project)
    return envelope.ok(project)
