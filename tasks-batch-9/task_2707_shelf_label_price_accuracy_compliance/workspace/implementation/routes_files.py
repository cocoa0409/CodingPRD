"""Price change files, lines, and the label-task execution axes."""
from datetime import timedelta

from flask import Blueprint

import calc
import services
import views
from auth import actor, actor_id, roles
from core import (
    ASSOCIATE_DAILY_MINUTES_CAP,
    DB,
    FILE_PRIORITIES,
    FILE_STATUSES,
    LINE_STATUSES,
    NET_CONTENT_UOMS,
    PLACEMENT_STATUSES,
    PRINT_STATUSES,
    R_COMPLIANCE_OFFICER,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
    R_PRICING_ADMIN,
    R_STORE_MANAGER,
    VERIFICATION_GRACE_HOURS,
    VERIFY_OUTCOMES,
    apply_changes,
    arg_bool,
    arg_enum,
    arg_str,
    body,
    fail,
    insert,
    must,
    now,
    ok,
    opt_bool,
    opt_enum,
    opt_str,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    req_str_array,
    rows,
    touch,
)

bp = Blueprint("files", __name__)

FILE_READ = [
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
]
ADMIN_READ = [R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER]


# ---------------------------------------------------------------- files
@bp.post("/price-integrity/price-change-files")
@roles(R_PRICING_ADMIN)
def create_file():
    data = body()
    file_number = req_str(data, "file_number", 1, 24)
    jurisdiction_id = req_str(data, "jurisdiction_id")
    effective_date = req_dt(data, "effective_date")
    scope_store_ids = req_str_array(data, "scope_store_ids", 1, 20)
    priority = opt_enum(data, "priority", FILE_PRIORITIES, "ROUTINE")
    must("jurisdictions", jurisdiction_id)
    for store_id in scope_store_ids:
        must("stores", store_id)
    if any(r["file_number"] == file_number for r in DB["price_change_files"].values()):
        fail("ERR_DUPLICATE_RESOURCE", "file_number already drafted")
    price_file = insert(
        "price_change_files",
        {
            "file_number": file_number,
            "jurisdiction_id": jurisdiction_id,
            "effective_date": effective_date,
            "priority": priority,
            "scope_store_ids": list(scope_store_ids),
            "status": "DRAFT",
            "distributed_at": None,
            "superseded_by_file_id": None,
        },
    )
    return ok(views.price_change_file(price_file), 201)


@bp.get("/price-integrity/price-change-files/<fid>")
@roles(*FILE_READ)
def get_file(fid):
    return ok(views.price_change_file(must("price_change_files", fid)))


@bp.get("/price-integrity/price-change-files")
@roles(*ADMIN_READ)
def list_files():
    jurisdiction_id = arg_str("jurisdiction_id")
    status = arg_enum("status", FILE_STATUSES)
    superseded_by = arg_str("superseded_by_file_id")
    priority = arg_enum("priority", FILE_PRIORITIES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("price_change_files")
        if (jurisdiction_id is None or r["jurisdiction_id"] == jurisdiction_id)
        and (status is None or r["status"] == status)
        and (superseded_by is None or r["superseded_by_file_id"] == superseded_by)
        and (priority is None or r["priority"] == priority)
    ]
    return views.paged(items, views.price_change_file, limit, offset)


# ---------------------------------------------------------------- lines
@bp.post("/price-integrity/price-change-files/<fid>/lines")
@roles(R_PRICING_ADMIN)
def create_line(fid):
    data = body()
    item_upc = req_str(data, "item_upc", 8, 14, r"\d{8,14}")
    item_description = req_str(data, "item_description", 1, 255)
    category_code = req_str(data, "category_code", 1, 24, upper=True)
    old_retail_cents = req_int(data, "old_retail_cents", 0)
    new_retail_cents = req_int(data, "new_retail_cents", 1)
    net_content_qty = req_num(data, "net_content_qty", 0, None, 3)
    net_content_uom = req_enum(data, "net_content_uom", NET_CONTENT_UOMS)
    promo_flag = opt_bool(data, "promo_flag", False)
    price_file = must("price_change_files", fid)
    if price_file["status"] != "DRAFT":
        fail("ERR_FILE_INVALID_STATE", "lines may only be added to a draft file")
    if any(
        r["price_change_file_id"] == fid and r["item_upc"] == item_upc
        for r in DB["price_change_lines"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "item_upc already present in this file")
    juris = services.jurisdiction_of_file(price_file)
    fields = {
        "price_change_file_id": price_file["id"],
        "item_upc": item_upc,
        "item_description": item_description,
        "category_code": category_code,
        "old_retail_cents": old_retail_cents,
        "new_retail_cents": new_retail_cents,
        "net_content_qty": net_content_qty,
        "net_content_uom": net_content_uom,
        "promo_flag": promo_flag,
        "line_status": "PENDING",
    }
    fields.update(calc.apply_unit_price(fields, juris))
    return ok(views.price_change_line(insert("price_change_lines", fields)), 201)


@bp.get("/price-integrity/price-change-lines/<lid>")
@roles(*FILE_READ)
def get_line(lid):
    return ok(views.price_change_line(must("price_change_lines", lid)))


@bp.get("/price-integrity/price-change-files/<fid>/lines")
@roles(*FILE_READ)
def list_file_lines(fid):
    line_status = arg_enum("line_status", LINE_STATUSES)
    category_code = arg_str("category_code")
    limit, offset = pagination()
    must("price_change_files", fid)
    items = [
        r
        for r in rows("price_change_lines")
        if r["price_change_file_id"] == fid
        and (line_status is None or r["line_status"] == line_status)
        and (category_code is None or r["category_code"] == category_code)
    ]
    return views.paged(items, views.price_change_line, limit, offset)


@bp.post("/price-integrity/price-change-files/<fid>/distribute")
@roles(R_PRICING_ADMIN)
def distribute_file(fid):
    price_file = must("price_change_files", fid)
    if price_file["status"] != "DRAFT":
        fail("ERR_FILE_INVALID_STATE", "only a draft file may be distributed")
    lines = services.file_lines(fid)
    live = [line for line in lines if line["line_status"] != "WITHDRAWN"]
    if len(live) < 1:
        fail("ERR_FILE_HAS_NO_LINES", "the file carries no lines")
    juris = services.jurisdiction_of_file(price_file)
    if juris["unit_price_required"]:
        for line in live:
            if not calc.basis_resolves(line, juris):
                fail("ERR_UNIT_PRICE_UNAVAILABLE", "a line cannot resolve a unit price")
    deadline = price_file["effective_date"] + timedelta(hours=juris["grace_period_hours"])
    if not now() < deadline:
        fail("ERR_EFFECTIVE_DATE_PASSED", "the distribution deadline has passed")
    for line in live:
        apply_changes(line, calc.apply_unit_price(line, juris))
    apply_changes(price_file, {"status": "DISTRIBUTED", "distributed_at": now()})
    touch(price_file)
    return ok(views.price_change_file(price_file))


@bp.post("/price-integrity/price-change-files/<fid>/supersede")
@roles(R_PRICING_ADMIN)
def supersede(fid):
    data = body()
    replacement_id = req_str(data, "superseded_by_file_id")
    price_file = must("price_change_files", fid)
    replacement = must("price_change_files", replacement_id)
    if price_file["status"] not in ("DISTRIBUTED", "PARTIALLY_EXECUTED"):
        fail("ERR_FILE_INVALID_STATE", "this file cannot be superseded")
    if (
        replacement["id"] == price_file["id"]
        or replacement["jurisdiction_id"] != price_file["jurisdiction_id"]
        or replacement["status"] not in ("DRAFT", "DISTRIBUTED")
        or replacement["effective_date"] < price_file["effective_date"]
    ):
        fail("ERR_SUPERSEDING_FILE_INVALID", "the named replacement is not eligible")
    services.supersede_file(price_file, replacement)
    touch(price_file)
    return ok(views.price_change_file(price_file))


# ---------------------------------------------------------------- label tasks
def interval_minutes(start, end):
    return (end - start).total_seconds() / 60.0


def day_minutes(start, end, day_start):
    """Overlap in minutes between [start, end] and one UTC calendar day."""
    day_end = day_start + timedelta(days=1)
    lo = max(start, day_start)
    hi = min(end, day_end)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds() / 60.0


def utc_days(start, end):
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    while day <= end:
        days.append(day)
        day = day + timedelta(days=1)
    return days


@bp.post("/price-integrity/price-change-files/<fid>/label-tasks")
@roles(R_STORE_MANAGER, R_PRICING_ADMIN)
def create_label_task(fid):
    data = body()
    store_id = req_str(data, "store_id")
    line_id = req_str(data, "price_change_line_id")
    aisle_id = req_str(data, "aisle_id")
    assigned_id = req_str(data, "assigned_associate_id")
    scheduled_start_at = req_dt(data, "scheduled_start_at")
    scheduled_end_at = req_dt(data, "scheduled_end_at")
    expected_version = req_int(data, "expected_price_change_file_version")
    # priority 30 then 32 — path first, then body refs in declared order
    price_file = must("price_change_files", fid)
    store = must("stores", store_id)
    line = must("price_change_lines", line_id)
    if line["price_change_file_id"] != price_file["id"]:
        fail("ERR_PRICE_CHANGE_LINE_NOT_FOUND", "the line does not belong to this file")
    aisle = must("aisles", aisle_id)
    assigned = must("associates", assigned_id)
    # priority 40 — the file's own state
    if price_file["status"] not in ("DISTRIBUTED", "PARTIALLY_EXECUTED"):
        fail("ERR_FILE_INVALID_STATE", "the file is not distributed")
    # priority 45 — version pin
    if expected_version != price_file["version"]:
        fail("ERR_STALE_PRICE_CHANGE_FILE_VERSION", "the pinned file version is stale")
    # priority 52 — posture gate (REGULATORY files bypass the frozen gate)
    if store["compliance_posture"] == "FROZEN" and price_file["priority"] != "REGULATORY":
        fail("ERR_STORE_POSTURE_BLOCKED", "the store is frozen")
    # priority 54 — undisplayable unit price
    juris = services.jurisdiction_of_file(price_file)
    if juris["unit_price_uom_rule"] != "PER_SINGLE_ITEM" and not (
        line["net_content_qty"] > 0
    ):
        fail("ERR_UNIT_PRICE_UNAVAILABLE", "the line has no displayable unit price")
    # priority 58 — well-formed interval
    if not scheduled_start_at < scheduled_end_at:
        fail("ERR_INVALID_WINDOW", "scheduled_start_at must precede scheduled_end_at")
    # priority 61 — associate labour exclusion (closed-closed)
    for task in rows("label_tasks"):
        if task["assigned_associate_id"] != assigned_id:
            continue
        if task["placement_status"] == "VERIFIED":
            continue
        if (
            scheduled_start_at <= task["scheduled_end_at"]
            and task["scheduled_start_at"] <= scheduled_end_at
        ):
            fail("ERR_ASSOCIATE_SCHEDULE_CONFLICT", "the assignee is already scheduled")
    # priority 63 — uniqueness
    if any(
        t["price_change_line_id"] == line_id and t["store_id"] == store_id
        for t in DB["label_tasks"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "this line is already tasked for this store")
    # priority 66 / 67 / 68
    if aisle["store_id"] != store_id:
        fail("ERR_AISLE_STORE_MISMATCH", "the aisle belongs to another store")
    if assigned["store_id"] != store_id:
        fail("ERR_ASSOCIATE_STORE_MISMATCH", "the associate belongs to another store")
    if store_id not in (price_file["scope_store_ids"] or []) or (
        store["jurisdiction_id"] != price_file["jurisdiction_id"]
    ):
        fail("ERR_STORE_OUT_OF_FILE_SCOPE", "the store is outside the file scope")
    # priority 70 — daily labour cap
    for day_start in utc_days(scheduled_start_at, scheduled_end_at):
        total = day_minutes(scheduled_start_at, scheduled_end_at, day_start)
        for task in DB["label_tasks"].values():
            if task["assigned_associate_id"] != assigned_id:
                continue
            if task["placement_status"] == "VERIFIED":
                continue
            total += day_minutes(
                task["scheduled_start_at"], task["scheduled_end_at"], day_start
            )
        if total > ASSOCIATE_DAILY_MINUTES_CAP:
            fail("ERR_ASSOCIATE_DAILY_CAP_EXCEEDED", "the assignee is over the daily cap")

    task = insert(
        "label_tasks",
        {
            "store_id": store_id,
            "price_change_line_id": line_id,
            "aisle_id": aisle_id,
            "assigned_associate_id": assigned_id,
            "placed_by_associate_id": None,
            "verified_by_associate_id": None,
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
            "print_status": "NOT_PRINTED",
            "placement_status": "UNPLACED",
            "printed_label_serial": None,
            "due_at": calc.label_task_due_at(price_file, juris),
            "placed_at": None,
            "verified_at": None,
            "rejection_count": 0,
            "observed_shelf_price_cents": None,
        },
    )
    services.on_task_created(line)
    services.recompute_store(store)
    return ok(views.label_task(task), 201)


@bp.get("/price-integrity/label-tasks/<tid>")
@roles(*FILE_READ)
def get_label_task(tid):
    return ok(views.label_task(must("label_tasks", tid)))


@bp.get("/price-integrity/label-tasks")
@roles(*FILE_READ)
def list_label_tasks():
    store_id = arg_str("store_id")
    line_id = arg_str("price_change_line_id")
    aisle_id = arg_str("aisle_id")
    assigned_id = arg_str("assigned_associate_id")
    placed_by = arg_str("placed_by_associate_id")
    verified_by = arg_str("verified_by_associate_id")
    print_status = arg_enum("print_status", PRINT_STATUSES)
    placement_status = arg_enum("placement_status", PLACEMENT_STATUSES)
    overdue = arg_bool("overdue")
    limit, offset = pagination()
    clock = now()
    items = [
        r
        for r in rows("label_tasks")
        if (store_id is None or r["store_id"] == store_id)
        and (line_id is None or r["price_change_line_id"] == line_id)
        and (aisle_id is None or r["aisle_id"] == aisle_id)
        and (assigned_id is None or r["assigned_associate_id"] == assigned_id)
        and (placed_by is None or r["placed_by_associate_id"] == placed_by)
        and (verified_by is None or r["verified_by_associate_id"] == verified_by)
        and (print_status is None or r["print_status"] == print_status)
        and (placement_status is None or r["placement_status"] == placement_status)
        and (overdue is None or calc.is_overdue(r, clock) == overdue)
    ]
    return views.paged(items, views.label_task, limit, offset)


@bp.post("/price-integrity/label-tasks/<tid>/print")
@roles(R_LABEL_ASSOCIATE, R_STORE_MANAGER)
def print_label(tid):
    task = must("label_tasks", tid)
    if task["print_status"] not in ("NOT_PRINTED", "REPRINT_REQUIRED"):
        fail("ERR_LABEL_TASK_INVALID_STATE", "the label is already printed")
    line = DB["price_change_lines"][task["price_change_line_id"]]
    price_file = services.file_of_line(line)
    if price_file["status"] not in ("DISTRIBUTED", "PARTIALLY_EXECUTED"):
        fail("ERR_FILE_NOT_DISTRIBUTED", "the owning file is not distributed")
    store = DB["stores"][task["store_id"]]
    if store["compliance_posture"] == "FROZEN":
        fail("ERR_STORE_POSTURE_BLOCKED", "the store is frozen")
    assigned = DB["associates"].get(task["assigned_associate_id"])
    if assigned is not None and assigned["training_status"] == "SUSPENDED":
        fail("ERR_LABEL_TASK_INVALID_STATE", "the assigned associate is suspended")
    apply_changes(
        task,
        {
            "print_status": "PRINTED",
            "printed_label_serial": services.mint_label_serial(store["id"]),
        },
    )
    services.on_task_printed(line)
    return ok(views.label_task(task))


@bp.post("/price-integrity/label-tasks/<tid>/place")
@roles(R_LABEL_ASSOCIATE, R_STORE_MANAGER)
def place_label(tid):
    data = body()
    observed = req_int(data, "observed_shelf_price_cents", 0)
    task = must("label_tasks", tid)
    if task["placement_status"] not in ("UNPLACED", "REJECTED"):
        fail("ERR_LABEL_TASK_INVALID_STATE", "the placement is already recorded")
    if task["print_status"] != "PRINTED":
        fail("ERR_LABEL_NOT_PRINTED", "the label is not printed")
    me = actor()
    if me is None or me["store_id"] != task["store_id"]:
        fail("ERR_ASSOCIATE_STORE_MISMATCH", "the actor belongs to another store")
    apply_changes(
        task,
        {
            "placement_status": "PLACED",
            "placed_by_associate_id": me["id"],
            "placed_at": now(),
            "observed_shelf_price_cents": observed,
        },
    )
    line = DB["price_change_lines"][task["price_change_line_id"]]
    services.on_task_placed(line)
    services.recompute_store(DB["stores"][task["store_id"]])
    return ok(views.label_task(task))


@bp.post("/price-integrity/label-tasks/<tid>/verify-placement")
@roles(R_PRICE_AUDITOR, R_STORE_MANAGER)
def verify_placement(tid):
    data = body()
    outcome = req_enum(data, "outcome", VERIFY_OUTCOMES)
    rejection_reason = opt_str(data, "rejection_reason", 0, 500)
    task = must("label_tasks", tid)
    if task["placement_status"] == "VERIFIED":
        fail("ERR_TRANSITION_ALREADY_APPLIED", "the placement is already verified")
    if task["placement_status"] != "PLACED":
        fail("ERR_LABEL_TASK_INVALID_STATE", "the placement is not recorded")
    me = actor()
    if me is not None and me["id"] == task["placed_by_associate_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the placer may not verify their own work")
    if me is not None:
        if (
            me["training_status"] != "CERTIFIED"
            or me["certification_expires_at"] is None
            or not now() < me["certification_expires_at"]
        ):
            fail("ERR_ASSOCIATE_NOT_CERTIFIED", "the verifier is not currently certified")
    if task["placed_at"] is None or not now() < task["placed_at"] + timedelta(
        hours=VERIFICATION_GRACE_HOURS
    ):
        fail("ERR_VERIFICATION_WINDOW_CLOSED", "the verification window has closed")

    line = DB["price_change_lines"][task["price_change_line_id"]]
    store = DB["stores"][task["store_id"]]
    placer = DB["associates"].get(task["placed_by_associate_id"])
    if outcome == "VERIFIED":
        apply_changes(
            task,
            {
                "placement_status": "VERIFIED",
                "verified_by_associate_id": me["id"] if me is not None else None,
                "verified_at": now(),
                "observed_shelf_price_cents": task["observed_shelf_price_cents"],
            },
        )
        touch(task)
        services.on_task_verified(line)
        if placer is not None:
            services.recompute_associate(placer)
        services.recompute_store(store)
        return ok(views.label_task(task))

    count = task["rejection_count"] + 1
    changes = {"placement_status": "REJECTED", "rejection_count": count}
    if task["print_status"] == "PRINTED":
        changes["print_status"] = "REPRINT_REQUIRED"
        changes["printed_label_serial"] = None
    apply_changes(task, changes)
    services.on_task_rejected(line)
    if count == 2 and placer is not None:
        services.issue_action(
            placer, "VERIFICATION_REJECTED", "COACHING", "system", task["id"]
        )
    services.recompute_store(store)
    return ok(views.label_task(task))
