"""Retouch tasks: queueing, the claim-next selector, submission and QC."""
from datetime import timedelta

from flask import Blueprint

from core import (
    MAX_REWORK, SLA_STATES, TASK_STATES, actor_id, authorize, by_created,
    created, db, dec, fail, get_body, hours_between, new_row, now, ok, ok_list,
    page_params, paginate, qenum, qstr, round_half_up, touch, venum, vstr,
)
from cascade import cascade_asset_rejected
from logic import apply_turnaround, claim_candidates, find, pinned_sla_hours, task_style
from serialize import task_out

bp = Blueprint("retouch", __name__)

LIVE_TASK_STATES = ("QUEUED", "IN_PROGRESS", "SUBMITTED", "REWORK", "APPROVED")


@bp.post("/retouch-tasks")
def create_task():
    authorize("ContentOps")
    body = get_body()
    asset_id = vstr(body, "asset_id", minlen=1)
    provider_id = vstr(body, "provider_id", minlen=1)

    asset = find(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
    provider = find(db.providers, provider_id, "ERR_REFERENCE_NOT_FOUND")

    if asset["asset_state"] != "INGESTED":
        fail("ERR_ASSET_NOT_APPROVED",
             "Only an INGESTED asset may be queued for retouching.")

    for task in db.tasks.values():
        if task["asset_id"] == asset["id"] and task["task_state"] in LIVE_TASK_STATES:
            fail("ERR_RETOUCH_TASK_EXISTS")

    style = None
    item = db.items.get(asset["shot_list_item_id"])
    if item is not None:
        style = db.styles.get(item["style_id"])
    sla_hours = pinned_sla_hours(provider, style)

    row = new_row({
        "asset_id": asset["id"],
        "provider_id": provider["id"],
        "assigned_retoucher_id": None,
        "task_state": "QUEUED",
        "sla_hours": sla_hours,
        "due_at": asset["created_at"] + timedelta(hours=sla_hours),
        "rework_count": 0,
        "rework_started_at": None,
        "rework_hours_total": dec(0),
        "claimed_at": None,
        "submitted_at": None,
        "approved_at": None,
        "turnaround_hours_gross": None,
        "turnaround_hours_net": None,
        "sla_state": "IN_SLA",
    })
    db.tasks[row["id"]] = row

    asset["asset_state"] = "IN_RETOUCH"
    touch(asset)
    touch(provider)
    return created(task_out(row))


@bp.post("/retouch-tasks/claim-next")
def claim_next():
    authorize("Retoucher")
    retoucher = db.talents.get(actor_id())
    if retoucher is None or retoucher["talent_type"] != "RETOUCHER":
        fail("ERR_TALENT_TYPE_MISMATCH",
             "X-User-ID must identify a RETOUCHER talent profile.")

    candidates = claim_candidates()
    if not candidates:
        fail("ERR_NO_CLAIMABLE_TASK")
    task = candidates[0]

    task["task_state"] = "IN_PROGRESS"
    task["assigned_retoucher_id"] = actor_id()
    task["claimed_at"] = now()
    touch(task)

    style = task_style(task)
    if style is not None and style["content_state"] == "SHOT":
        style["content_state"] = "IN_POST"
        touch(style)
    return ok(task_out(task))


@bp.post("/retouch-tasks/<task_id>/submit")
def submit_task(task_id):
    authorize("Retoucher")
    body = get_body()
    vstr(body, "note", required=False, default=None, maxlen=1000)

    task = find(db.tasks, task_id, "ERR_RETOUCH_TASK_NOT_FOUND")
    if task["assigned_retoucher_id"] != actor_id():
        fail("ERR_TASK_NOT_ASSIGNED_TO_ACTOR")
    if task["task_state"] not in ("IN_PROGRESS", "REWORK"):
        fail("ERR_RETOUCH_TASK_INVALID_STATE")

    if task["task_state"] == "REWORK" and task["rework_started_at"] is not None:
        banked = round_half_up(hours_between(task["rework_started_at"], now()), 2)
        task["rework_hours_total"] = round_half_up(
            dec(task["rework_hours_total"]) + banked, 2)
        task["rework_started_at"] = None

    task["task_state"] = "SUBMITTED"
    task["submitted_at"] = now()
    touch(task)

    asset = db.assets.get(task["asset_id"])
    if asset is not None and asset["asset_state"] == "IN_RETOUCH":
        asset["asset_state"] = "QC_PENDING"
        touch(asset)
    return ok(task_out(task))


@bp.post("/retouch-tasks/<task_id>/qc-decision")
def qc_decision(task_id):
    authorize("QCReviewer")
    body = get_body()
    decision = venum(body, "decision", ["APPROVE", "REJECT"])
    vstr(body, "note", required=False, default=None, maxlen=1000)

    task = find(db.tasks, task_id, "ERR_RETOUCH_TASK_NOT_FOUND")
    if task["assigned_retoucher_id"] is not None \
            and task["assigned_retoucher_id"] == actor_id():
        fail("ERR_SEGREGATION_OF_DUTIES")
    if task["task_state"] != "SUBMITTED":
        fail("ERR_RETOUCH_TASK_INVALID_STATE")

    asset = db.assets.get(task["asset_id"])
    provider = db.providers.get(task["provider_id"])

    if decision == "APPROVE":
        task["task_state"] = "APPROVED"
        task["approved_at"] = now()
        if asset is not None:
            apply_turnaround(task, asset)
        touch(task)
        if asset is not None:
            asset["asset_state"] = "APPROVED"
            touch(asset)
        if provider is not None:
            touch(provider)
        return ok(task_out(task))

    if task["rework_count"] < MAX_REWORK:
        task["task_state"] = "REWORK"
        task["rework_count"] += 1
        task["rework_started_at"] = now()
        touch(task)
        if asset is not None:
            asset["asset_state"] = "IN_RETOUCH"
            touch(asset)
        return ok(task_out(task))

    task["task_state"] = "ABANDONED"
    touch(task)
    if asset is not None:
        asset["asset_state"] = "REJECTED"
        touch(asset)
        item = db.items.get(asset["shot_list_item_id"])
        if item is not None:
            cascade_asset_rejected(item)
    if provider is not None:
        touch(provider)
    return ok(task_out(task))


@bp.get("/retouch-tasks/<task_id>")
def read_task(task_id):
    authorize("StudioAdmin", "ContentOps", "Retoucher", "QCReviewer")
    row = find(db.tasks, task_id, "ERR_RETOUCH_TASK_NOT_FOUND")
    return ok(task_out(row))


@bp.get("/retouch-tasks")
def list_tasks():
    authorize("StudioAdmin", "ContentOps", "Retoucher", "QCReviewer")
    limit, offset = page_params()
    asset_id = qstr("asset_id")
    provider_id = qstr("provider_id")
    assigned_retoucher_id = qstr("assigned_retoucher_id")
    task_state = qenum("task_state", TASK_STATES)
    sla_state = qenum("sla_state", SLA_STATES)

    rows = list(db.tasks.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if assigned_retoucher_id is not None:
        rows = [r for r in rows if r.get("assigned_retoucher_id") == assigned_retoucher_id]
    if task_state is not None:
        rows = [r for r in rows if r["task_state"] == task_state]
    if sla_state is not None:
        rows = [r for r in rows if r["sla_state"] == sla_state]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([task_out(r) for r in page], limit, offset, total)
