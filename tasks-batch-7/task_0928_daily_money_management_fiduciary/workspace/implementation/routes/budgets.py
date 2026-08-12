"""Monthly budget lines and allocation overrides."""

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import recompute_budget
from core.audit import set_client, set_subject
from core.envelope import object_response
from core.errors import fail
from core.pipeline import audited, authorize, resolve, resolve_body_client
from core.store import all_of, bump, new_row

bp = Blueprint("budgets", __name__)


@bp.post("/dmm/budget-categories")
@audited("BudgetCategory")
def create_budget_category():
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("category_name", str, True),
        ("budget_month", str, True),
        ("allocation_cents", int, True),
    ])

    allocation = ctx.body["allocation_cents"]
    if allocation <= 0:                                        # rung 15
        fail("ERR_VALIDATION", "allocation_cents must be greater than zero.")

    for line in all_of("budget_categories"):                   # rung 16
        if (line["client_id"] == client_row["id"]
                and line["category_name"] == ctx.body["category_name"]
                and line["budget_month"] == ctx.body["budget_month"]):
            fail("ERR_VALIDATION", "That budget line already exists for the month.")

    row = new_row("budget_categories", {
        "client_id": client_row["id"],
        "category_name": ctx.body["category_name"],
        "budget_month": ctx.body["budget_month"],
        "allocation_cents": allocation,
        "override_granted_cents": 0,
        "override_count": 0,
        "last_override_reason": None,
        "committed_cents": 0,
        "settled_cents": 0,
        "remaining_cents": allocation,
        "variance_full_cents": allocation,
        "variance_ptd_cents": 0,
        "variance_direction": "EXACT",
    })
    recompute_budget(row)
    set_subject(row["id"])
    return object_response(serialize.budget_category(row), 201)


@bp.post("/dmm/budget-categories/<bid>/overrides")
@audited("BudgetCategory", path_param="bid")
def grant_override(bid):
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    line = resolve("budget_categories", bid)                   # rung 3
    set_client(line["client_id"])
    ctx.check_shape([                                          # rung 4
        ("added_cents", int, True),
        ("reason", str, True),
    ])

    added = ctx.body["added_cents"]
    reason = ctx.body["reason"]
    if added <= 0:                                             # rung 15
        fail("ERR_VALIDATION", "added_cents must be greater than zero.")
    if len(reason) < K.BUDGET_OVERRIDE_REASON_MIN_CHARS:
        fail("ERR_VALIDATION", "The override reason is too short.")

    line["override_granted_cents"] += added
    line["override_count"] += 1
    line["last_override_reason"] = reason
    recompute_budget(line)
    bump(line)
    return object_response(serialize.budget_category(line), 200)


@bp.get("/dmm/budget-categories/<bid>")
def read_budget_category(bid):
    authorize("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer",
              "PlatformAdmin")
    return object_response(serialize.budget_category(resolve("budget_categories", bid)), 200)
