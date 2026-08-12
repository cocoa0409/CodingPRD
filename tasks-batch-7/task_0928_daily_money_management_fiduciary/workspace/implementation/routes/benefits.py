"""Benefit applications, programme limits and the retroactive award posting."""

from flask import Blueprint

from core import calc
from core import constants as K
from core import serialize
from core.aggregates import append_ledger_entry, period_for_month, recompute_account
from core.audit import set_client, set_subject
from core.clock import month_of_date_string, parse_date
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.gates import gate_authorization, gate_client_active, gate_scope_benefit_application
from core.pipeline import (
    audited,
    authorize,
    resolve,
    resolve_body_client,
    resolve_body_ref,
)
from core.store import bump, db, new_row

bp = Blueprint("benefits", __name__)

READ_ROLES = ("FiduciaryManager", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/dmm/benefit-applications")
@audited("BenefitApplication")
def draft_application():
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    auth = resolve_body_ref(ctx, "authorization_id", "authorizations")
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("authorization_id", str, True),
        ("program", str, True),
        ("asserted_monthly_income_cents", int, True),
        ("resource_items", list, True),
    ])
    items = ctx.body["resource_items"]
    for item in items:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "Each resource item must be an object.")
        if not isinstance(item.get("item_type"), str):
            fail("ERR_VALIDATION", "Each resource item needs a string item_type.")
        value = item.get("value_cents")
        if not isinstance(value, int) or isinstance(value, bool):
            fail("ERR_VALIDATION", "Each resource item needs an integer value_cents.")

    ctx.check_enum("program", K.BENEFIT_PROGRAM)               # rung 5
    for item in items:
        if item["item_type"] not in K.RESOURCE_ITEM_TYPE:
            fail("ERR_INVALID_ENUM", "resource_items[].item_type is not a member.")

    gate_authorization(auth)                                   # rung 7
    gate_scope_benefit_application(auth)                       # rung 8
    gate_client_active(client_row)                             # rung 11

    income = ctx.body["asserted_monthly_income_cents"]
    if income < 0:                                             # rung 15
        fail("ERR_VALIDATION", "asserted_monthly_income_cents must be zero or greater.")
    for item in items:
        if item["value_cents"] < 0:
            fail("ERR_VALIDATION", "resource_items[].value_cents must be zero or greater.")

    gross, net = calc.countable_resources(items)
    row = new_row("benefit_applications", {
        "client_id": client_row["id"],
        "authorization_id": auth["id"],
        "program": ctx.body["program"],
        "asserted_monthly_income_cents": income,
        "resource_items": [
            {"item_type": i["item_type"], "value_cents": i["value_cents"]} for i in items
        ],
        "countable_resources_gross_cents": gross,
        "countable_resources_net_cents": net,
        "status": "DRAFT",
        "appeal_count": 0,
        "submitted_on": None,
        "decision_date": None,
        "award_effective_date": None,
        "award_monthly_amount_cents": None,
        "retro_months": 0,
        "retro_award_cents": 0,
        "denial_reason": None,
    })
    set_subject(row["id"])
    return object_response(serialize.benefit_application(row), 201)


@bp.post("/dmm/benefit-applications/<bid>/status")
@audited("BenefitApplication", path_param="bid")
def drive_application_status(bid):
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    app_row = resolve("benefit_applications", bid)             # rung 3
    set_client(app_row["client_id"])
    ctx.check_shape([("action", str, True)])                   # rung 4
    ctx.check_enum("action", K.BENEFIT_STATUS_ACTION)          # rung 5

    auth = db.authorizations.get(app_row["authorization_id"])
    gate_authorization(auth)                                   # rung 7
    gate_client_active(db.clients.get(app_row["client_id"]))   # rung 11

    action = ctx.body["action"]
    if action == "SUBMIT":                                     # rung 12
        if app_row["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT application may be submitted.")
    else:
        if app_row["status"] != "DENIED":
            fail("ERR_INVALID_STATE", "Only a DENIED application may be appealed.")
        if app_row["appeal_count"] >= K.BENEFIT_APPEAL_MAX_COUNT:   # rung 26
            fail("ERR_APPEAL_LIMIT_REACHED", "The appeal cap is reached.")

    if action == "SUBMIT":                                     # rung 38
        program = app_row["program"]
        if (app_row["countable_resources_net_cents"] > K.PROGRAM_RESOURCE_LIMIT_CENTS[program]
                or app_row["asserted_monthly_income_cents"]
                > K.PROGRAM_INCOME_LIMIT_CENTS[program]):
            fail("ERR_RESOURCE_LIMIT_EXCEEDED", "A programme limit is exceeded.")
        app_row["status"] = "SUBMITTED"
        app_row["submitted_on"] = db.today_str()
    else:
        app_row["status"] = "APPEALED"
        app_row["appeal_count"] += 1

    bump(app_row)
    return object_response(serialize.benefit_application(app_row), 200)


@bp.post("/dmm/benefit-applications/<bid>/record-decision")
@audited("BenefitApplication", path_param="bid")
def record_decision(bid):
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    app_row = resolve("benefit_applications", bid)             # rung 3 - path
    set_client(app_row["client_id"])
    account = resolve_body_ref(ctx, "account_id", "accounts")  # rung 3 - body
    ctx.check_shape([                                          # rung 4
        ("outcome", str, True),
        ("decision_date", str, True),
        ("account_id", str, True),
        ("award_effective_date", str, False),
        ("award_monthly_amount_cents", int, False),
        ("denial_reason", str, False),
    ])
    outcome = ctx.body.get("outcome")
    if outcome == "DENIED":
        ctx.require_conditional("denial_reason")
    elif outcome == "APPROVED":
        ctx.require_conditional("award_effective_date")
        ctx.require_conditional("award_monthly_amount_cents", int)
    ctx.check_enum("outcome", K.BENEFIT_DECISION_OUTCOME)      # rung 5

    if app_row["status"] not in ("SUBMITTED", "APPEALED"):     # rung 12
        fail("ERR_INVALID_STATE", "No decision may be recorded from this state.")

    if outcome == "DENIED" and ctx.body["denial_reason"].strip() == "":   # rung 15
        fail("ERR_VALIDATION", "denial_reason must not be empty.")

    decision_date = ctx.body["decision_date"]
    if outcome == "APPROVED":                                  # rung 24
        award_effective_date = ctx.body["award_effective_date"]
        span = calc.days_between(award_effective_date, decision_date)
        if span is None or span < 0 or span > K.RETRO_AWARD_MAX_LOOKBACK_DAYS:
            fail("ERR_RETRO_LOOKBACK_EXCEEDED", "The retroactive lookback is out of range.")

    if outcome == "DENIED":
        app_row["status"] = "DENIED"
        app_row["decision_date"] = decision_date
        app_row["denial_reason"] = ctx.body["denial_reason"]
        bump(app_row)
        return object_response(serialize.benefit_application(app_row), 200)

    award_effective_date = ctx.body["award_effective_date"]
    monthly = ctx.body["award_monthly_amount_cents"]
    months = calc.retro_months(decision_date, award_effective_date)
    app_row["status"] = "APPROVED"
    app_row["decision_date"] = decision_date
    app_row["award_effective_date"] = award_effective_date
    app_row["award_monthly_amount_cents"] = monthly
    app_row["retro_months"] = months
    app_row["retro_award_cents"] = monthly * months

    _post_award(app_row, account, award_effective_date)
    bump(app_row)
    return object_response(serialize.benefit_application(app_row), 200)


def _post_award(app_row, account, award_effective_date):
    """The two-branch posting rule that never writes into frozen books."""
    award_month = month_of_date_string(award_effective_date)
    award_period = period_for_month(account["id"], award_month)
    if award_period is not None and award_period["status"] in ("CLOSED", "LOCKED"):
        append_ledger_entry(
            account, "BENEFIT_AWARD", app_row["retro_award_cents"], db.today_str(),
            memo="Retroactive benefit award", retro_period_month=award_month,
        )
        # The single field the reconciliation freeze permits writing; it is
        # explicitly not a mutation of the period's own lifecycle.
        award_period["has_retro_adjustment"] = True
    else:
        append_ledger_entry(
            account, "BENEFIT_AWARD", app_row["retro_award_cents"], award_effective_date,
            memo="Benefit award",
        )
    recompute_account(account)


@bp.get("/dmm/benefit-applications")
def list_applications():
    authorize(*READ_ROLES)
    rows = db.ordered("benefit_applications")
    for field in ("client_id", "authorization_id", "status"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.benefit_application)


@bp.get("/dmm/benefit-applications/<bid>")
def read_application(bid):
    authorize(*READ_ROLES)
    return object_response(
        serialize.benefit_application(resolve("benefit_applications", bid)), 200
    )
