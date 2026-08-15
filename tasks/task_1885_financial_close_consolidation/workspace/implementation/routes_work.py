"""Routes: entity-periods, close tasks, subledger cutoffs, accrual estimates."""
from datetime import timedelta

from flask import request

from core import (
    STORE, ApiError, ALL_ROLES, base_record, body, bp, bump, logical_now,
    ok, paged_response, req_enum, req_int, req_str, req_ts, require_roles,
)
from domain import (
    ELIM_TOLERANCE, add_event, compute_nci, compute_provisional, create_je,
    entity_of_ep, eps_of_period, get_accrual, get_cutoff, get_ep, get_period,
    get_task, json_detail, lock_gate_ep, period_of_ep,
    recompute_open_task_count, recompute_unreconciled_count, run_translation,
    ser_accrual, ser_cutoff, ser_ep, ser_event, ser_task,
    recompute_task_is_late, touch_ep, unblock_dependents,
)

READERS = ALL_ROLES


# ---------------------------------------------------------------------------
# EntityPeriod
# ---------------------------------------------------------------------------
@bp.get("/close/entity-periods/<eid>")
def get_one_ep(eid):
    require_roles(*READERS)
    return ok(ser_ep(get_ep(eid)))


@bp.get("/close/entity-periods")
def list_eps():
    require_roles(*READERS)
    records = list(STORE["entity_periods"].values())
    for param in ("close_period_id", "entity_id", "status"):
        value = request.args.get(param)
        if value is not None:
            records = [e for e in records if e[param] == value]
    return paged_response(records, ser_ep)


@bp.post("/close/entity-periods/<eid>/translate")
def translate_ep(eid):
    uid = require_roles("Controller")
    ep = get_ep(eid)
    period = period_of_ep(ep)
    if period["status"] == "FINALIZED":
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Period is FINALIZED; translation no longer allowed")
    entity = entity_of_ep(ep)
    run_translation(ep, period, entity)
    touch_ep(ep)
    add_event(period["id"], ep["id"], "TRANSLATION_RUN", uid,
              json_detail({
                  "entity_period_id": ep["id"],
                  "translated_balance_minor": ep["translated_balance_minor"],
                  "cta_minor": ep["cta_minor"],
              }))
    return ok(ser_ep(ep))


@bp.post("/close/entity-periods/<eid>/mark-reconciled")
def mark_reconciled(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    period = period_of_ep(ep)
    if ep["status"] == "PREPARING":
        cutoffs = [c for c in STORE["cutoffs"].values()
                   if c["entity_period_id"] == ep["id"]]
        if not cutoffs:
            raise ApiError("ERR_NO_SUBLEDGER_CUTOFF", 409,
                           "Entity-period has no subledger cutoff rows")
    if ep["status"] not in ("SUBLEDGER_CUT", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark-reconciled requires SUBLEDGER_CUT or REOPENED")
    if ep["status"] == "REOPENED" and ep["_translation_stale"]:
        raise ApiError("ERR_TRANSLATION_STALE", 409,
                       "A fresh translation run is required after a reopen")
    for recon in STORE["reconciliations"].values():
        if recon["entity_period_id"] != ep["id"]:
            continue
        if recon["status"] == "CLEARED":
            continue
        if recon["status"] in ("OPEN", "IN_REVIEW") \
                and recon["is_within_tolerance"]:
            continue
        raise ApiError(
            "ERR_RECON_OUTSTANDING", 409,
            "Reconciliation %s is neither cleared nor within tolerance"
            % recon["id"])
    materiality = period["materiality_threshold_minor"]
    for accr in STORE["accruals"].values():
        if accr["entity_period_id"] != ep["id"]:
            continue
        if accr["status"] == "POSTED":
            continue
        if accr["status"] == "TRUED_UP" \
                and abs(accr["true_up_delta_minor"]) < materiality:
            continue
        raise ApiError(
            "ERR_ACCRUAL_MATERIAL_TRUEUP", 409,
            "Accrual %s has an unposted true-up at or above materiality, "
            "or was never trued up/posted" % accr["id"])
    ep["status"] = "RECONCILED"
    recompute_unreconciled_count(ep, period_too=False)
    touch_ep(ep)
    return ok(ser_ep(ep))


@bp.post("/close/entity-periods/<eid>/ready")
def ready_ep(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    if ep["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "ready requires RECONCILED status")
    if not ep["_translation_run"]:
        raise ApiError("ERR_TRANSLATION_NOT_RUN", 409,
                       "No translation run exists for this entity-period")
    if ep["_translation_stale"]:
        raise ApiError("ERR_TRANSLATION_STALE", 409,
                       "Translation is stale; re-run translation first")
    for pair in STORE["elim_pairs"].values():
        if ep["id"] not in (pair["entity_period_id_a"],
                            pair["entity_period_id_b"]):
            continue
        if pair["status"] == "ELIMINATED":
            continue
        if pair["status"] in ("MATCHED", "DISPUTED") \
                and abs(pair["residual_minor"]) <= ELIM_TOLERANCE:
            continue
        raise ApiError("ERR_ELIM_RESIDUAL_EXCEEDED", 409,
                       "Elimination pair %s unresolved or residual above "
                       "tolerance" % pair["id"])
    for task in STORE["tasks"].values():
        if task["entity_period_id"] == ep["id"] \
                and task["status"] not in ("DONE", "WAIVED"):
            raise ApiError("ERR_OPEN_CLOSE_TASKS", 409,
                           "Close task %s is not DONE or WAIVED"
                           % task["id"])
    ep["status"] = "READY_FOR_CONSOL"
    ep["nci_share_minor"] = compute_nci(ep, entity_of_ep(ep))
    touch_ep(ep)
    return ok(ser_ep(ep))


@bp.get("/close/entity-periods/<eid>/events")
def list_ep_events(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    events = [e for e in STORE["events"].values()
              if e["entity_period_id"] == ep["id"]]
    return paged_response(events, ser_event)


@bp.get("/close/entity-periods/<eid>/tasks")
def list_ep_tasks(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    tasks = [t for t in STORE["tasks"].values()
             if t["entity_period_id"] == ep["id"]]
    return paged_response(tasks, ser_task)


# ---------------------------------------------------------------------------
# CloseTask
# ---------------------------------------------------------------------------
def _creates_cycle(period_id, deps):
    graph = {t["id"]: list(t["depends_on_task_ids"])
             for t in STORE["tasks"].values()
             if t["close_period_id"] == period_id}
    graph["__new__"] = list(deps)
    color = {}

    def visit(node):
        color[node] = 1
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if color.get(nxt) == 1:
                return True
            if color.get(nxt, 0) == 0 and visit(nxt):
                return True
        color[node] = 2
        return False

    return any(color.get(n, 0) == 0 and visit(n) for n in list(graph))


@bp.post("/close/periods/<pid>/tasks")
def create_task(pid):
    require_roles("Controller")
    period = get_period(pid)
    b = body()
    entity_period_id = b.get("entity_period_id")
    ep = None
    if entity_period_id is not None:
        ep = get_ep(entity_period_id)
        if ep["close_period_id"] != period["id"]:
            raise ApiError("ERR_NOT_FOUND", 404,
                           "entity_period_id does not belong to this period")
    task_key = req_str(b, "task_key")
    title = req_str(b, "title")
    deps = b.get("depends_on_task_ids")
    if deps is None:
        deps = []
    if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
        raise ApiError("ERR_VALIDATION", 400,
                       "depends_on_task_ids must be an array of task ids")
    for dep_id in deps:
        dep = STORE["tasks"].get(dep_id)
        if dep is None or dep["close_period_id"] != period["id"]:
            raise ApiError("ERR_NOT_FOUND", 404,
                           "Dependency task %s not found in this period"
                           % dep_id)
    if _creates_cycle(period["id"], deps):
        raise ApiError("ERR_TASK_DEPENDENCY_CYCLE", 409,
                       "depends_on_task_ids introduces a cycle")
    assignee = req_str(b, "assignee_user_id")
    due_offset_hours = req_int(b, "due_offset_hours")
    due_instant = period["period_start"] + timedelta(hours=due_offset_hours)
    rec = base_record()
    rec.update({
        "close_period_id": period["id"],
        "entity_period_id": ep["id"] if ep is not None else None,
        "task_key": task_key,
        "title": title,
        "depends_on_task_ids": list(deps),
        "assignee_user_id": assignee,
        "due_offset_hours": due_offset_hours,
        "status": "READY" if not deps else "BLOCKED",
        "is_late": logical_now() > due_instant,
        "completed_at": None,
    })
    STORE["tasks"][rec["id"]] = rec
    bump(period)
    if ep is not None:
        recompute_open_task_count(ep)
    return ok(ser_task(rec), 201)


@bp.get("/close/tasks/<tid>")
def get_one_task(tid):
    require_roles(*READERS)
    return ok(ser_task(get_task(tid)))


@bp.get("/close/periods/<pid>/tasks")
def list_period_tasks(pid):
    require_roles(*READERS)
    period = get_period(pid)
    tasks = [t for t in STORE["tasks"].values()
             if t["close_period_id"] == period["id"]]
    status = request.args.get("status")
    if status is not None:
        tasks = [t for t in tasks if t["status"] == status]
    return paged_response(tasks, ser_task)


@bp.post("/close/tasks/<tid>/start")
def start_task(tid):
    uid = require_roles("Preparer")
    task = get_task(tid)
    if task["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a READY task can be started")
    period = get_period(task["close_period_id"])
    if period["close_posture"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_POSTURE_NOT_OPEN", 409,
                       "Close posture is not OPEN or REOPENED")
    if uid != task["assignee_user_id"]:
        raise ApiError("ERR_NOT_TASK_ASSIGNEE", 409,
                       "Only the task assignee may start the task")
    task["status"] = "IN_PROGRESS"
    bump(task)
    return ok(ser_task(task))


@bp.post("/close/tasks/<tid>/complete")
def complete_task(tid):
    uid = require_roles("Preparer")
    task = get_task(tid)
    if task["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_PROGRESS task can be completed")
    if uid != task["assignee_user_id"]:
        raise ApiError("ERR_NOT_TASK_ASSIGNEE", 409,
                       "Only the task assignee may complete the task")
    period = get_period(task["close_period_id"])
    key = task["task_key"]
    if key.startswith("RECON_"):
        if task["entity_period_id"] is not None:
            recons = [r for r in STORE["reconciliations"].values()
                      if r["entity_period_id"] == task["entity_period_id"]]
        else:
            ep_ids = {e["id"] for e in eps_of_period(period["id"])}
            recons = [r for r in STORE["reconciliations"].values()
                      if r["entity_period_id"] in ep_ids]
        if any(r["status"] != "CLEARED" for r in recons):
            raise ApiError("ERR_RECON_OUTSTANDING", 409,
                           "Linked reconciliation is not CLEARED")
    elif key == "TRANSLATE":
        if task["entity_period_id"] is not None:
            eps = [get_ep(task["entity_period_id"])]
        else:
            eps = eps_of_period(period["id"])
        if any(not e["_translation_run"] for e in eps):
            raise ApiError("ERR_TRANSLATION_NOT_RUN", 409,
                           "A translation run must occur this period before "
                           "completing a TRANSLATE task")
    elif key == "ELIMINATE":
        pairs = [p for p in STORE["elim_pairs"].values()
                 if p["close_period_id"] == period["id"]]
        if any(p["status"] not in ("ELIMINATED", "DISPUTED") for p in pairs):
            raise ApiError("ERR_ELIM_RESIDUAL_EXCEEDED", 409,
                           "All elimination pairs must be resolved before "
                           "completing an ELIMINATE task")
    task["status"] = "DONE"
    task["completed_at"] = logical_now()
    recompute_task_is_late(task, logical_now())
    bump(task)
    bump(period)
    add_event(period["id"], task["entity_period_id"], "TASK_DONE", uid,
              json_detail({"task_id": task["id"], "task_key": key}))
    unblock_dependents(task)
    if task["entity_period_id"] is not None:
        recompute_open_task_count(get_ep(task["entity_period_id"]))
    return ok(ser_task(task))


@bp.post("/close/tasks/<tid>/waive")
def waive_task(tid):
    require_roles("Controller")
    task = get_task(tid)
    if task["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a READY task can be waived")
    period = get_period(task["close_period_id"])
    if period["close_posture"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_POSTURE_NOT_OPEN", 409,
                       "Close posture is not OPEN or REOPENED")
    if task["task_key"] in ("TRANSLATE", "ELIMINATE", "CONSOLIDATE"):
        raise ApiError("ERR_TASK_NOT_WAIVABLE", 409,
                       "Critical-path tasks cannot be waived")
    task["status"] = "WAIVED"
    bump(task)
    bump(period)
    unblock_dependents(task)
    if task["entity_period_id"] is not None:
        recompute_open_task_count(get_ep(task["entity_period_id"]))
    return ok(ser_task(task))


@bp.post("/close/tasks/<tid>/unstart")
def unstart_task(tid):
    uid = require_roles("Preparer")
    task = get_task(tid)
    if task["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_PROGRESS task can be returned to READY")
    if uid != task["assignee_user_id"]:
        raise ApiError("ERR_NOT_TASK_ASSIGNEE", 409,
                       "Only the task assignee may unstart the task")
    task["status"] = "READY"
    bump(task)
    return ok(ser_task(task))


# ---------------------------------------------------------------------------
# SubledgerCutoff
# ---------------------------------------------------------------------------
@bp.post("/close/entity-periods/<eid>/subledger-cutoffs")
def create_cutoff(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    lock_gate_ep(ep, child_creation=True)
    b = body()
    subledger = req_enum(b, "subledger",
                         ("AR", "AP", "INVENTORY", "FIXED_ASSETS", "PAYROLL"))
    cutoff_at = req_ts(b, "cutoff_at")
    cutoff_rule = req_enum(b, "cutoff_rule", ("INCLUSIVE",
                                              "EXCLUSIVE_AT_END"))
    rec = base_record()
    rec.update({
        "entity_period_id": ep["id"],
        "subledger": subledger,
        "cutoff_at": cutoff_at,
        "cutoff_rule": cutoff_rule,
        "status": "OPEN",
        "pre_cutoff_total_minor": 0,
        "boundary_transaction_count": 0,
        "_cut_by_user_id": None,
    })
    STORE["cutoffs"][rec["id"]] = rec
    return ok(ser_cutoff(rec), 201)


@bp.get("/close/entity-periods/<eid>/subledger-cutoffs")
def list_ep_cutoffs(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [c for c in STORE["cutoffs"].values()
               if c["entity_period_id"] == ep["id"]]
    return paged_response(records, ser_cutoff)


@bp.get("/close/subledger-cutoffs/<cid>")
def get_one_cutoff(cid):
    require_roles(*READERS)
    return ok(ser_cutoff(get_cutoff(cid)))


@bp.post("/close/subledger-cutoffs/<cid>/cut")
def cut_cutoff(cid):
    uid = require_roles("Preparer")
    cutoff = get_cutoff(cid)
    if cutoff["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN cutoff can be cut")
    ep = get_ep(cutoff["entity_period_id"])
    period = period_of_ep(ep)
    if ep["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cut is allowed only while the entity-period is "
                       "PREPARING")
    t_cut = cutoff["cutoff_at"]
    if not (t_cut > period["period_start"] and t_cut <= period["period_end"]):
        raise ApiError("ERR_CUTOFF_OUT_OF_PERIOD", 409,
                       "cutoff_at must fall within (period_start, "
                       "period_end]")
    txns = [t for t in STORE["subledger_txns"].values()
            if t["entity_id"] == ep["entity_id"]
            and t["subledger"] == cutoff["subledger"]
            and t["ts"] >= period["period_start"]]
    boundary = [t for t in txns if t["ts"] == t_cut]
    if cutoff["cutoff_rule"] == "INCLUSIVE":
        included = [t for t in txns if t["ts"] < t_cut]
    else:  # EXCLUSIVE_AT_END
        included = [t for t in txns if t["ts"] <= t_cut]
    cutoff["pre_cutoff_total_minor"] = sum(t["amount_minor"]
                                           for t in included)
    cutoff["boundary_transaction_count"] = len(boundary)
    cutoff["_cut_by_user_id"] = uid
    cutoff["status"] = "CUT"
    bump(cutoff)
    return ok(ser_cutoff(cutoff))


@bp.post("/close/subledger-cutoffs/<cid>/confirm")
def confirm_cutoff(cid):
    uid = require_roles("Approver")
    cutoff = get_cutoff(cid)
    if cutoff["status"] != "CUT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CUT cutoff can be confirmed")
    if uid == cutoff["_cut_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "The approver confirming a cutoff must differ from "
                       "the preparer who executed the cut")
    cutoff["status"] = "CONFIRMED"
    bump(cutoff)
    ep = get_ep(cutoff["entity_period_id"])
    siblings = [c for c in STORE["cutoffs"].values()
                if c["entity_period_id"] == ep["id"]]
    if ep["status"] == "PREPARING" and siblings \
            and all(c["status"] == "CONFIRMED" for c in siblings):
        ep["status"] = "SUBLEDGER_CUT"
        period = period_of_ep(ep)
        for accr in STORE["accruals"].values():
            if accr["entity_period_id"] == ep["id"]:
                accr["provisional_amount_minor"] = compute_provisional(accr)
                bump(accr)
        add_event(period["id"], ep["id"], "SUBLEDGER_CUT", "system",
                  json_detail({"entity_period_status_before": "PREPARING",
                               "entity_period_status_after": "SUBLEDGER_CUT"}))
        touch_ep(ep)
    return ok(ser_cutoff(cutoff))


# ---------------------------------------------------------------------------
# AccrualEstimate
# ---------------------------------------------------------------------------
@bp.post("/close/entity-periods/<eid>/accruals")
def create_accrual(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    lock_gate_ep(ep, child_creation=True)
    b = body()
    cutoff = get_cutoff(req_str(b, "subledger_cutoff_id"))
    if cutoff["entity_period_id"] != ep["id"]:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "subledger_cutoff_id does not belong to this "
                       "entity-period")
    account_code = req_str(b, "account_code")
    basis = req_enum(b, "basis",
                     ("PRIOR_3M_AVG", "PRIOR_PERIOD", "DAYS_OUTSTANDING"))
    rec = base_record()
    rec.update({
        "entity_period_id": ep["id"],
        "subledger_cutoff_id": cutoff["id"],
        "account_code": account_code,
        "basis": basis,
        "provisional_amount_minor": 0,
        "final_amount_minor": None,
        "true_up_delta_minor": 0,
        "status": "PROVISIONAL",
    })
    STORE["accruals"][rec["id"]] = rec
    return ok(ser_accrual(rec), 201)


@bp.get("/close/entity-periods/<eid>/accruals")
def list_ep_accruals(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [a for a in STORE["accruals"].values()
               if a["entity_period_id"] == ep["id"]]
    return paged_response(records, ser_accrual)


@bp.get("/close/subledger-cutoffs/<cid>/accruals")
def list_cutoff_accruals(cid):
    require_roles(*READERS)
    cutoff = get_cutoff(cid)
    records = [a for a in STORE["accruals"].values()
               if a["subledger_cutoff_id"] == cutoff["id"]]
    return paged_response(records, ser_accrual)


@bp.post("/close/accruals/<aid>/true-up")
def true_up_accrual(aid):
    require_roles("Preparer")
    accr = get_accrual(aid)
    if accr["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROVISIONAL accrual can be trued up")
    ep = get_ep(accr["entity_period_id"])
    lock_gate_ep(ep)
    if ep["status"] not in ("SUBLEDGER_CUT", "RECONCILED", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "True-up requires the entity-period in SUBLEDGER_CUT, "
                       "RECONCILED, or REOPENED")
    final_amount = req_int(body(), "final_amount_minor")
    accr["final_amount_minor"] = final_amount
    accr["true_up_delta_minor"] = final_amount - accr["provisional_amount_minor"]
    accr["status"] = "TRUED_UP"
    bump(accr)
    return ok(ser_accrual(accr))


@bp.post("/close/accruals/<aid>/recompute")
def recompute_accrual(aid):
    require_roles("Preparer")
    accr = get_accrual(aid)
    if accr["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROVISIONAL accrual can be recomputed")
    ep = get_ep(accr["entity_period_id"])
    lock_gate_ep(ep)
    accr["provisional_amount_minor"] = compute_provisional(accr)
    bump(accr)
    return ok(ser_accrual(accr))


@bp.post("/close/accruals/<aid>/post")
def post_accrual(aid):
    uid = require_roles("Preparer")
    accr = get_accrual(aid)
    if accr["status"] not in ("PROVISIONAL", "TRUED_UP"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROVISIONAL or TRUED_UP accrual can post")
    ep = get_ep(accr["entity_period_id"])
    lock_gate_ep(ep)
    if accr["status"] == "TRUED_UP":
        delta = accr["true_up_delta_minor"]
        if delta == 0:
            raise ApiError("ERR_ACCRUAL_ZERO_DELTA", 409,
                           "A zero-delta accrual is closed directly from "
                           "PROVISIONAL")
        amount = abs(delta)
        contra = accr["account_code"] + "-CONTRA"
        if delta > 0:
            lines = [
                {"account_code": accr["account_code"], "direction": "DEBIT",
                 "amount_minor": amount},
                {"account_code": contra, "direction": "CREDIT",
                 "amount_minor": amount},
            ]
        else:
            lines = [
                {"account_code": contra, "direction": "DEBIT",
                 "amount_minor": amount},
                {"account_code": accr["account_code"], "direction": "CREDIT",
                 "amount_minor": amount},
            ]
        je = create_je(ep, "ACCRUAL", logical_now(), lines, uid)
        period = period_of_ep(ep)
        add_event(period["id"], ep["id"], "ACCRUAL_POSTED", uid,
                  json_detail({"accrual_id": accr["id"],
                               "journal_entry_id": je["id"]}))
    accr["status"] = "POSTED"
    bump(accr)
    return ok(ser_accrual(accr))
