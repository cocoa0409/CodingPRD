"""Routes: AccessRevocationTask, AssetReturnItem, FinalPayStatement."""
from datetime import timedelta

from flask import g

from core import (
    ASSET_DEFAULT_GRACE_DAYS,
    ASSET_KINDS,
    DB,
    LATE_FEE_CENTS,
    MAX_REVOKE_RETRIES,
    RETRY_BACKOFF_MINUTES,
    RETURN_CONDITIONS,
    SYSTEM_NAMES,
    app,
    authenticate,
    bump,
    err_bad_request,
    err_case_terminal,
    err_fiscal,
    err_invalid_state,
    err_not_found,
    err_referential,
    err_retry_cap,
    err_sequence_gate,
    err_sod,
    get_body,
    is_int,
    new_record,
    now_dt,
    ok_object,
    paginate,
    parse_dt,
    req_str,
    ser,
    ApiError,
)
from domain import (
    after_asset_mutation,
    after_task_mutation,
    apply_deduction_cascade,
    assets_of,
    calc_asset_deduction_damage,
    calc_asset_deduction_default,
    calc_final_net_pay,
    calc_late_penalty,
    calc_pto_payout,
    calc_revocation_schedule,
    reconcile_case,
    statement_of,
    tasks_of,
)
from routes_cases import _q, get_case_or_404

TASK_ROLES = {"ITOperator", "ITVerifier", "ITManager", "HRPartner"}
ASSET_ROLES = {"AssetClerk", "PayrollSpecialist", "HRPartner", "Manager"}
STATEMENT_ROLES = {"PayrollSpecialist", "HRPartner", "HRDirector"}

CASE_STATES_FOR_EXECUTE = {"APPROVED", "REVOCATION_IN_PROGRESS"}
CASE_STATES_FOR_RETURN = {
    "APPROVED", "REVOCATION_IN_PROGRESS", "PAYROLL_PENDING",
    "CLEARANCE_IN_PROGRESS", "READY_TO_CLOSE",
}
CASE_STATES_FOR_PAYROLL = {"APPROVED", "REVOCATION_IN_PROGRESS", "PAYROLL_PENDING"}


def get_task_or_404(task_id):
    task = DB["tasks"].get(task_id)
    if task is None:
        raise err_not_found("AccessRevocationTask %s not found" % task_id)
    return task


def get_asset_or_404(item_id):
    item = DB["assets"].get(item_id)
    if item is None:
        raise err_not_found("AssetReturnItem %s not found" % item_id)
    return item


def get_statement_or_404(statement_id):
    st = DB["statements"].get(statement_id)
    if st is None:
        raise err_not_found("FinalPayStatement %s not found" % statement_id)
    return st


def _parent_case_of_task(task):
    return get_case_or_404(task["offboarding_case_id"])


def _reject_if_case_terminal(case):
    if case["status"] in ("CLOSED", "VOIDED"):
        raise err_case_terminal()


# --------------------------------------------------------------------------
# AccessRevocationTask
# --------------------------------------------------------------------------
@app.post("/offboarding/access-revocation-tasks")
def create_revocation_task():
    authenticate({"ITManager"})
    body = get_body()
    case_id = body.get("offboarding_case_id")
    case = DB["cases"].get(case_id) if isinstance(case_id, str) else None
    if case is None:
        if not isinstance(case_id, str) or not case_id:
            raise err_bad_request("offboarding_case_id is required")
        raise err_referential("offboarding_case_id does not reference an existing case")
    _reject_if_case_terminal(case)
    rank = body.get("sequence_rank")
    if not is_int(rank) or rank < 1:
        raise err_bad_request("sequence_rank must be an integer >= 1")
    if any(t["sequence_rank"] == rank for t in tasks_of(case["id"])):
        raise err_referential("sequence_rank must be unique within the case")
    if body.get("system_name") not in SYSTEM_NAMES:
        raise err_bad_request("system_name must be one of %s" % sorted(SYSTEM_NAMES))

    task = new_record()
    scheduled = None
    if case["determined_last_day"] is not None:
        scheduled = calc_revocation_schedule(body["system_name"], case["determined_last_day"])
    task.update({
        "offboarding_case_id": case["id"],
        "system_name": body["system_name"],
        "sequence_rank": rank,
        "status": "PENDING",
        "scheduled_at": scheduled,
        "executed_at": None,
        "verified_by": None,
        "retry_count": 0,
        "failure_reason": None,
        "_executed_by": None,
        "_waive_reason": None,
    })
    DB["tasks"][task["id"]] = task
    after_task_mutation(case)
    return ok_object(ser(task), status=201)


@app.get("/offboarding/access-revocation-tasks")
def list_revocation_tasks():
    authenticate(TASK_ROLES)
    records = list(DB["tasks"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [t for t in records if t["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [t for t in records if t["status"] == status]
    system_name = _q("system_name")
    if system_name is not None:
        records = [t for t in records if t["system_name"] == system_name]
    return paginate(records)


@app.get("/offboarding/access-revocation-tasks/<task_id>")
def get_revocation_task(task_id):
    authenticate(TASK_ROLES)
    return ok_object(ser(get_task_or_404(task_id)))


@app.get("/offboarding/offboarding-cases/<case_id>/access-revocation-tasks")
def list_case_revocation_tasks(case_id):
    authenticate(TASK_ROLES)
    get_case_or_404(case_id)
    records = tasks_of(case_id)
    status = _q("status")
    if status is not None:
        records = [t for t in records if t["status"] == status]
    return paginate(records)


def _sequence_gate_ok(task):
    for t in tasks_of(task["offboarding_case_id"]):
        if t["id"] == task["id"]:
            continue
        if t["sequence_rank"] < task["sequence_rank"] and t["status"] not in ("VERIFIED", "WAIVED"):
            return False
    return True


@app.post("/offboarding/access-revocation-tasks/<task_id>/execute")
def execute_revocation_task(task_id):
    authenticate({"ITOperator"})
    task = get_task_or_404(task_id)
    if task["status"] != "READY":
        raise err_invalid_state("Only a READY task can be executed")
    case = _parent_case_of_task(task)
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_EXECUTE:
        raise err_invalid_state("Parent case must be APPROVED or REVOCATION_IN_PROGRESS")
    if not _sequence_gate_ok(task):
        raise err_sequence_gate("Lower sequence_rank sibling tasks are not yet terminal")
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("SUCCESS", "FAILED"):
        raise err_bad_request("outcome must be SUCCESS or FAILED")
    if outcome == "FAILED":
        reason = req_str(body, "failure_reason")
        task["status"] = "FAILED"
        task["failure_reason"] = reason
    else:
        task["status"] = "EXECUTED"
        task["executed_at"] = now_dt()
        task["_executed_by"] = g.user_id
    bump(task)
    after_task_mutation(case)
    return ok_object(ser(task))


@app.post("/offboarding/access-revocation-tasks/<task_id>/verify")
def verify_revocation_task(task_id):
    authenticate({"ITVerifier"})
    task = get_task_or_404(task_id)
    if task["status"] != "EXECUTED":
        raise err_invalid_state("Only an EXECUTED task can be verified")
    case = _parent_case_of_task(task)
    _reject_if_case_terminal(case)
    # SoD-3: verifier must differ from the executor
    if g.user_id == task.get("_executed_by"):
        raise err_sod("Verifier must differ from the executing operator (SoD-3)")
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("VERIFIED", "REJECTED"):
        raise err_bad_request("outcome must be VERIFIED or REJECTED")
    if outcome == "VERIFIED":
        task["status"] = "VERIFIED"
        task["verified_by"] = g.user_id
    else:
        task["status"] = "FAILED"
    bump(task)
    after_task_mutation(case)
    return ok_object(ser(task))


@app.post("/offboarding/access-revocation-tasks/<task_id>/retry")
def retry_revocation_task(task_id):
    authenticate({"ITOperator"})
    task = get_task_or_404(task_id)
    if task["status"] != "FAILED":
        raise err_invalid_state("Only a FAILED task can be retried")
    case = _parent_case_of_task(task)
    _reject_if_case_terminal(case)
    if task["retry_count"] >= MAX_REVOKE_RETRIES:
        raise err_retry_cap("Revocation retry cap reached")
    task["retry_count"] += 1
    task["scheduled_at"] = now_dt() + timedelta(minutes=RETRY_BACKOFF_MINUTES * task["retry_count"])
    task["status"] = "RETRY_SCHEDULED"
    bump(task)
    after_task_mutation(case)
    return ok_object(ser(task))


@app.post("/offboarding/access-revocation-tasks/<task_id>/waive")
def waive_revocation_task(task_id):
    authenticate({"ITManager"})
    task = get_task_or_404(task_id)
    if task["status"] not in ("FAILED", "RETRY_SCHEDULED"):
        raise err_invalid_state("Only a FAILED or RETRY_SCHEDULED task can be waived")
    case = _parent_case_of_task(task)
    _reject_if_case_terminal(case)
    if task["retry_count"] < MAX_REVOKE_RETRIES:
        raise err_sequence_gate("A task may be waived only after the retry cap is reached")
    body = get_body()
    task["_waive_reason"] = req_str(body, "waive_reason")
    task["status"] = "WAIVED"
    bump(task)
    after_task_mutation(case)
    return ok_object(ser(task))


# --------------------------------------------------------------------------
# AssetReturnItem
# --------------------------------------------------------------------------
@app.post("/offboarding/asset-return-items")
def create_asset_item():
    authenticate({"AssetClerk"})
    body = get_body()
    case_id = body.get("offboarding_case_id")
    case = DB["cases"].get(case_id) if isinstance(case_id, str) else None
    if case is None:
        if not isinstance(case_id, str) or not case_id:
            raise err_bad_request("offboarding_case_id is required")
        raise err_referential("offboarding_case_id does not reference an existing case")
    _reject_if_case_terminal(case)
    tag = body.get("asset_tag")
    if not isinstance(tag, str) or not tag:
        raise err_bad_request("asset_tag is required")
    if any(a["asset_tag"] == tag for a in assets_of(case["id"])):
        raise err_referential("asset_tag must be unique within the case")
    cost = body.get("replacement_cost_cents")
    if not is_int(cost):
        raise err_bad_request("replacement_cost_cents must be an integer")
    if cost < 0:
        raise err_fiscal("replacement_cost_cents must be >= 0")
    if body.get("asset_kind") not in ASSET_KINDS:
        raise err_bad_request("asset_kind must be one of %s" % sorted(ASSET_KINDS))
    issued = parse_dt(body.get("issued_date"))
    if issued is None:
        raise err_bad_request("issued_date must be an ISO 8601 UTC instant")

    item = new_record()
    return_due = None
    if case["determined_last_day"] is not None:
        return_due = case["determined_last_day"] + timedelta(days=3)
    item.update({
        "offboarding_case_id": case["id"],
        "asset_tag": tag,
        "asset_kind": body["asset_kind"],
        "replacement_cost_cents": cost,
        "issued_date": issued,
        "return_due_at": return_due,
        "returned_at": None,
        "condition_on_return": None,
        "status": "TRACKED",
        "deduction_status": "NONE",
        "deduction_amount_cents": 0,
        "_waive_reason": None,
    })
    DB["assets"][item["id"]] = item
    after_asset_mutation(case)
    return ok_object(ser(item), status=201)


@app.get("/offboarding/asset-return-items")
def list_asset_items():
    authenticate(ASSET_ROLES)
    records = list(DB["assets"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [a for a in records if a["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    ded = _q("deduction_status")
    if ded is not None:
        records = [a for a in records if a["deduction_status"] == ded]
    return paginate(records)


@app.get("/offboarding/asset-return-items/<item_id>")
def get_asset_item(item_id):
    authenticate(ASSET_ROLES)
    return ok_object(ser(get_asset_or_404(item_id)))


@app.get("/offboarding/offboarding-cases/<case_id>/asset-return-items")
def list_case_asset_items(case_id):
    authenticate(ASSET_ROLES)
    get_case_or_404(case_id)
    records = assets_of(case_id)
    status = _q("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return paginate(records)


@app.post("/offboarding/asset-return-items/<item_id>/record-return")
def record_asset_return(item_id):
    authenticate({"AssetClerk"})
    item = get_asset_or_404(item_id)
    if item["status"] not in ("TRACKED", "OVERDUE"):
        raise err_invalid_state("Only a TRACKED or OVERDUE item can be recorded returned")
    case = get_case_or_404(item["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_RETURN:
        raise err_invalid_state("Parent case state does not allow recording returns")
    body = get_body()
    condition = body.get("condition_on_return")
    if condition not in RETURN_CONDITIONS:
        raise err_bad_request("condition_on_return must be one of %s" % sorted(RETURN_CONDITIONS))
    expected = body.get("expected_asset_return_item_version")
    if not is_int(expected):
        raise err_bad_request("expected_asset_return_item_version is required")
    if expected != item["version"]:
        raise ApiError("ERR_STALE_ASSET_VERSION", 412,
                       "AssetReturnItem version has advanced since the caller's read")

    now = now_dt()
    item["returned_at"] = now
    item["condition_on_return"] = condition
    item["status"] = "RETURNED"
    deduction = 0
    if condition in ("DAMAGED", "DESTROYED"):
        deduction = calc_asset_deduction_damage(item, condition)
    if item["return_due_at"] is not None and now > item["return_due_at"]:
        deduction += LATE_FEE_CENTS
    if deduction > 0:
        item["deduction_status"] = "COMPUTED"
        item["deduction_amount_cents"] = deduction
    bump(item)
    after_asset_mutation(case)
    return ok_object(ser(item))


@app.post("/offboarding/asset-return-items/<item_id>/mark-defaulted")
def mark_asset_defaulted(item_id):
    authenticate({"PayrollSpecialist"})
    item = get_asset_or_404(item_id)
    if item["status"] != "OVERDUE":
        raise err_invalid_state("Only an OVERDUE item can be marked defaulted")
    case = get_case_or_404(item["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in ("PAYROLL_PENDING", "CLEARANCE_IN_PROGRESS"):
        raise err_invalid_state(
            "Parent case must be PAYROLL_PENDING or CLEARANCE_IN_PROGRESS to default an asset")
    if not (now_dt() > item["return_due_at"] + timedelta(days=ASSET_DEFAULT_GRACE_DAYS)):
        raise err_invalid_state("Asset default grace period has not yet elapsed")

    item["status"] = "DEFAULTED"
    item["deduction_status"] = "APPLIED"
    item["deduction_amount_cents"] = calc_asset_deduction_default(item)
    bump(item)
    total_changed = apply_deduction_cascade(case)
    posture_changed = False
    from domain import compute_asset_posture
    posture = compute_asset_posture(assets_of(case["id"]))
    if posture != case["asset_posture"]:
        case["asset_posture"] = posture
        posture_changed = True
    transitioned = reconcile_case(case)
    if (total_changed or posture_changed) and not transitioned:
        bump(case)
    return ok_object(ser(item))


@app.post("/offboarding/asset-return-items/<item_id>/waive")
def waive_asset_item(item_id):
    authenticate({"AssetClerk"})
    item = get_asset_or_404(item_id)
    if item["status"] not in ("TRACKED", "OVERDUE"):
        raise err_invalid_state("Only a TRACKED or OVERDUE item can be waived")
    case = get_case_or_404(item["offboarding_case_id"])
    _reject_if_case_terminal(case)
    body = get_body()
    item["_waive_reason"] = req_str(body, "waive_reason")
    item["status"] = "WAIVED"
    total_changed = False
    if item["deduction_status"] in ("COMPUTED", "APPLIED"):
        item["deduction_status"] = "WAIVED"
        item["deduction_amount_cents"] = 0
        total_changed = apply_deduction_cascade(case)
    bump(item)
    from domain import compute_asset_posture
    posture = compute_asset_posture(assets_of(case["id"]))
    posture_changed = posture != case["asset_posture"]
    if posture_changed:
        case["asset_posture"] = posture
    transitioned = reconcile_case(case)
    if (total_changed or posture_changed) and not transitioned:
        bump(case)
    return ok_object(ser(item))


# --------------------------------------------------------------------------
# FinalPayStatement
# --------------------------------------------------------------------------
@app.get("/offboarding/final-pay-statements")
def list_statements():
    authenticate(STATEMENT_ROLES)
    records = list(DB["statements"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [s for s in records if s["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records)


@app.get("/offboarding/final-pay-statements/<statement_id>")
def get_statement(statement_id):
    authenticate(STATEMENT_ROLES)
    return ok_object(ser(get_statement_or_404(statement_id)))


@app.get("/offboarding/offboarding-cases/<case_id>/final-pay-statements")
def list_case_statements(case_id):
    authenticate(STATEMENT_ROLES)
    get_case_or_404(case_id)
    records = [s for s in DB["statements"].values() if s["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records)


def _compute_statement_amounts(st, case):
    pto = calc_pto_payout(case)
    ded, net = calc_final_net_pay(
        st["regular_wages_cents"], pto, case["deduction_total_cents"]
    )
    st["pto_payout_cents"] = pto
    st["deduction_total_cents"] = ded
    st["net_pay_cents"] = net


@app.post("/offboarding/final-pay-statements/<statement_id>/calculate")
def calculate_statement(statement_id):
    authenticate({"PayrollSpecialist"})
    st = get_statement_or_404(statement_id)
    if st["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT statement can be calculated")
    case = get_case_or_404(st["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_PAYROLL:
        raise err_invalid_state("Parent case state does not allow calculation")
    body = get_body()
    wages = body.get("regular_wages_cents")
    if not is_int(wages):
        raise err_bad_request("regular_wages_cents must be an integer")
    if wages < 0:
        raise err_fiscal("regular_wages_cents must be >= 0")
    expected = body.get("expected_final_pay_statement_version")
    if not is_int(expected):
        raise err_bad_request("expected_final_pay_statement_version is required")
    if expected != st["version"]:
        raise ApiError("ERR_STALE_STATEMENT_VERSION", 412,
                       "FinalPayStatement version has advanced since the caller's read")

    st["regular_wages_cents"] = wages
    _compute_statement_amounts(st, case)
    st["_calc_by_ref"] = g.user_id
    st["status"] = "CALCULATED"
    bump(st)
    return ok_object(ser(st))


@app.post("/offboarding/final-pay-statements/<statement_id>/recalculate")
def recalculate_statement(statement_id):
    authenticate({"PayrollSpecialist"})
    st = get_statement_or_404(statement_id)
    if st["status"] != "CALCULATED":
        raise err_invalid_state("Only a CALCULATED statement can be recalculated")
    case = get_case_or_404(st["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_PAYROLL:
        raise err_invalid_state("Parent case state does not allow recalculation")
    body = get_body()
    if "regular_wages_cents" in body and body["regular_wages_cents"] is not None:
        wages = body["regular_wages_cents"]
        if not is_int(wages):
            raise err_bad_request("regular_wages_cents must be an integer")
        if wages < 0:
            raise err_fiscal("regular_wages_cents must be >= 0")
        st["regular_wages_cents"] = wages
    _compute_statement_amounts(st, case)
    st["_calc_by_ref"] = g.user_id
    st["status"] = "CALCULATED"
    bump(st)
    return ok_object(ser(st))


@app.post("/offboarding/final-pay-statements/<statement_id>/approve")
def approve_statement(statement_id):
    authenticate({"PayrollSpecialist"})
    st = get_statement_or_404(statement_id)
    if st["status"] != "CALCULATED":
        raise err_invalid_state("Only a CALCULATED statement can be approved")
    case = get_case_or_404(st["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_PAYROLL:
        raise err_invalid_state("Parent case state does not allow statement approval")
    # SoD-2: approver must differ from the calculator
    if g.user_id == st.get("_calc_by_ref"):
        raise err_sod("Approver must differ from the calculator (SoD-2)")

    st["status"] = "APPROVED"
    bump(st)
    if case["status"] == "PAYROLL_PENDING":
        case["status"] = "CLEARANCE_IN_PROGRESS"
        transitioned = reconcile_case(case)
        if not transitioned:
            bump(case)
    else:
        reconcile_case(case)
    return ok_object(ser(st))


@app.post("/offboarding/final-pay-statements/<statement_id>/disburse")
def disburse_statement(statement_id):
    authenticate({"PayrollSpecialist"})
    st = get_statement_or_404(statement_id)
    if st["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED statement can be disbursed")
    case = get_case_or_404(st["offboarding_case_id"])
    _reject_if_case_terminal(case)
    now = now_dt()
    st["disbursed_at"] = now
    if now <= st["due_at"]:
        st["status"] = "DISBURSED"
    else:
        st["status"] = "LATE"
        st["late_penalty_cents"] = calc_late_penalty(st["due_at"], now, case["hourly_wage_cents"])
    bump(st)
    reconcile_case(case)
    return ok_object(ser(st))
