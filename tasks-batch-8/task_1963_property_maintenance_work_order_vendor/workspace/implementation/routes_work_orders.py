"""Work-order endpoints: intake, triage edit (OCC), dispatch, start, sign-off,
complete, reopen, close, cancel, plus nested part reservation and purchase
request creation."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import new_record, store, touch
from domain import (
    clear_assignment,
    compute_dues,
    release_reserved_lines,
    stock_consume,
    stock_release,
    stock_reserve,
    technician_conflict,
    vendor_schedule_conflict,
)
from errors import (
    entry_rule,
    invalid_state,
    not_found,
    not_owner,
    notice_too_short,
    open_purchase_requests,
    part_stock,
    photos_required,
    recall_expired,
    chargeback_lines,
    signoff_required,
    stale,
    tech_conflict,
    trade_mismatch,
    validation,
    vendor_conflict_err,
    vendor_insurance,
    vendor_not_active,
)
from helpers import (
    ASSIGNMENT_TYPES,
    body,
    ENTRY_AUTHS,
    is_int,
    is_str,
    pagination,
    PRIORITIES,
    sorted_page,
    TRADES,
)
from middleware import authn, authorize, require_assigned_party
from response import ok_list, ok_object
from serializers import purchase_request_out, work_order_out, work_order_part_out
from timeutil import parse_dt

bp = Blueprint("work_orders", __name__)

ALL_ROLES = ("Resident", "Dispatcher", "Technician", "Vendor", "PropertyManager")


def _get_work_order(wo_id):
    wo = store.work_orders.get(wo_id)
    if wo is None:
        not_found("work order")
    return wo


# --- Intake --------------------------------------------------------------------

@bp.post("/work-orders")
def create_work_order():
    uid, role = authn()
    authorize(role, {"Resident"})
    b = body()
    # Ownership (priority 3): a resident files only under their own id.
    rid = b.get("resident_id")
    if isinstance(rid, str) and rid and rid != uid:
        not_owner()
    # Existence (priority 4) of payload foreign keys.
    pid = b.get("property_id")
    prop = None
    if isinstance(pid, str) and pid:
        prop = store.properties.get(pid)
        if prop is None:
            not_found("property")
    resident = None
    if isinstance(rid, str) and rid:
        resident = store.residents.get(rid)
        if resident is None:
            not_found("resident")
    # General shape (priority 21).
    if not isinstance(pid, str) or not pid:
        validation("property_id is required")
    if not isinstance(rid, str) or not rid:
        validation("resident_id is required")
    if b.get("category") not in TRADES:
        validation("category must be a declared trade")
    if b.get("priority") not in PRIORITIES:
        validation("priority must be EMERGENCY, URGENT, or ROUTINE")
    if not isinstance(b.get("description"), str):
        validation("description is required")

    rec = new_record()
    response_due, completion_due = compute_dues(prop, b["priority"], rec["created_at"])
    rec.update(
        {
            "property_id": pid,
            "resident_id": rid,
            "unit_number": resident["unit_number"],
            "category": b["category"],
            "priority": b["priority"],
            "description": b["description"],
            "status": "TRIAGED",
            "assignment_type": None,
            "assigned_technician_id": None,
            "assigned_vendor_id": None,
            "scheduled_start_at": None,
            "scheduled_end_at": None,
            "entry_authorization": None,
            "notice_posted_at": None,
            "first_responded_at": None,
            "started_at": None,
            "completed_at": None,
            "closed_at": None,
            "response_due_at": response_due,
            "completion_due_at": completion_due,
            "response_sla_breached": False,
            "completion_sla_breached": False,
            "resident_signoff": False,
            "photo_urls": [],
            "damage_reported": False,
            "estimated_damage_cost_cents": None,
            "recall_count": 0,
            "parts_total_cents": 0,
        }
    )
    store.work_orders[rec["id"]] = rec
    return ok_object(work_order_out(rec), 201)


@bp.get("/work-orders")
def list_work_orders():
    authn_role = authn()[1]
    authorize(authn_role, ALL_ROLES)
    limit, offset = pagination()
    items = list(store.work_orders.values())
    for param in (
        "property_id",
        "resident_id",
        "assigned_technician_id",
        "assigned_vendor_id",
        "status",
    ):
        value = request.args.get(param)
        if value is not None:
            items = [wo for wo in items if wo.get(param) == value]
    page, total = sorted_page(items, limit, offset)
    return ok_list([work_order_out(wo) for wo in page], limit, offset, total)


@bp.get("/work-orders/<wo_id>")
def get_work_order(wo_id):
    authn_role = authn()[1]
    authorize(authn_role, ALL_ROLES)
    return ok_object(work_order_out(_get_work_order(wo_id)))


# --- Triage edit (OCC-guarded) --------------------------------------------------

@bp.patch("/work-orders/<wo_id>")
def patch_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Dispatcher"})
    wo = _get_work_order(wo_id)
    b = body()
    expected = b.get("expected_work_order_version")
    # Concurrency (priority 5).
    if is_int(expected) and expected != wo["version"]:
        stale()
    # State (priority 6).
    if wo["status"] != "TRIAGED":
        invalid_state("only a TRIAGED work order can be triage-edited")
    # General shape (priority 21).
    if not is_int(expected):
        validation("expected_work_order_version is required and must be an integer")
    if "priority" in b and b["priority"] not in PRIORITIES:
        validation("priority must be EMERGENCY, URGENT, or ROUTINE")
    if "category" in b and b["category"] not in TRADES:
        validation("category must be a declared trade")
    if "description" in b and not isinstance(b["description"], str):
        validation("description must be a string")

    if "priority" in b and b["priority"] != wo["priority"]:
        wo["priority"] = b["priority"]
        prop = store.properties.get(wo["property_id"])
        # SLA clock always starts at intake (created_at), never at reclassification.
        wo["response_due_at"], wo["completion_due_at"] = compute_dues(
            prop, wo["priority"], wo["created_at"]
        )
    if "category" in b:
        wo["category"] = b["category"]
    if "description" in b:
        wo["description"] = b["description"]
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Dispatch -------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/dispatch")
def dispatch_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Dispatcher"})
    wo = _get_work_order(wo_id)
    b = body()
    prop = store.properties.get(wo["property_id"])

    assignment_type = b.get("assignment_type")
    technician_id = b.get("technician_id")
    vendor_id = b.get("vendor_id")
    ss_raw = b.get("scheduled_start_at")
    se_raw = b.get("scheduled_end_at")
    entry = b.get("entry_authorization")
    np_raw = b.get("notice_posted_at")
    sched_start = parse_dt(ss_raw) if ss_raw is not None else None
    sched_end = parse_dt(se_raw) if se_raw is not None else None
    notice_posted = parse_dt(np_raw) if np_raw is not None else None

    # Existence (priority 4) of the named assignee.
    tech = None
    vend = None
    if assignment_type == "IN_HOUSE" and isinstance(technician_id, str) and technician_id:
        tech = store.technicians.get(technician_id)
        if tech is None:
            not_found("technician")
    if assignment_type == "VENDOR" and isinstance(vendor_id, str) and vendor_id:
        vend = store.vendors.get(vendor_id)
        if vend is None:
            not_found("vendor")

    # State (priority 6).
    if wo["status"] not in ("TRIAGED", "REOPENED"):
        invalid_state("work order is not awaiting dispatch")

    # Entry rules (priority 7): EMERGENCY_ACCESS only on EMERGENCY orders.
    if entry == "EMERGENCY_ACCESS" and wo["priority"] != "EMERGENCY":
        entry_rule("EMERGENCY_ACCESS is lawful only for EMERGENCY priority")

    # Notice lead time at dispatch (priority 8).
    if entry == "NOTICE_POSTED":
        lead = timedelta(hours=prop["entry_notice_min_hours"])
        if notice_posted is None or sched_start is None or sched_start < notice_posted + lead:
            notice_too_short()

    # Vendor activity gate (priority 9).
    if assignment_type == "VENDOR" and vend is not None and vend["status"] != "ACTIVE":
        vendor_not_active()

    # Vendor insurance gate (priority 10).
    if (
        assignment_type == "VENDOR"
        and vend is not None
        and sched_start is not None
        and vend["insurance_valid_until"] < sched_start
    ):
        vendor_insurance()

    # Technician half-open overlap (priority 11).
    if (
        assignment_type == "IN_HOUSE"
        and tech is not None
        and sched_start is not None
        and sched_end is not None
        and technician_conflict(tech["id"], sched_start, sched_end)
    ):
        tech_conflict()

    # Vendor travel-buffer rule (priority 12).
    if (
        assignment_type == "VENDOR"
        and vend is not None
        and sched_start is not None
        and sched_end is not None
        and vendor_schedule_conflict(
            vend["id"], sched_start, sched_end, prop["vendor_travel_buffer_minutes"]
        )
    ):
        vendor_conflict_err()

    # Trade and same-property match (priority 14).
    assignee = tech if assignment_type == "IN_HOUSE" else vend
    if assignee is not None and (
        assignee["property_id"] != wo["property_id"] or assignee["trade"] != wo["category"]
    ):
        trade_mismatch()

    # General shape (priority 21).
    if assignment_type not in ASSIGNMENT_TYPES:
        validation("assignment_type must be IN_HOUSE or VENDOR")
    if assignment_type == "IN_HOUSE" and not (isinstance(technician_id, str) and technician_id):
        validation("technician_id is required for IN_HOUSE dispatch")
    if assignment_type == "VENDOR" and not (isinstance(vendor_id, str) and vendor_id):
        validation("vendor_id is required for VENDOR dispatch")
    if sched_start is None:
        validation("scheduled_start_at must be a well-formed ISO 8601 datetime")
    if sched_end is None:
        validation("scheduled_end_at must be a well-formed ISO 8601 datetime")
    if sched_end <= sched_start:
        validation("scheduled_end_at must be strictly after scheduled_start_at")
    if entry not in ENTRY_AUTHS:
        validation("entry_authorization must be a declared entry authorization")
    if np_raw is not None and notice_posted is None:
        validation("notice_posted_at must be a well-formed ISO 8601 datetime")

    # Side effects.
    now = store.clock
    wo["assignment_type"] = assignment_type
    wo["assigned_technician_id"] = tech["id"] if assignment_type == "IN_HOUSE" else None
    wo["assigned_vendor_id"] = vend["id"] if assignment_type == "VENDOR" else None
    wo["scheduled_start_at"] = sched_start
    wo["scheduled_end_at"] = sched_end
    wo["entry_authorization"] = entry
    wo["notice_posted_at"] = notice_posted if entry == "NOTICE_POSTED" else None
    if wo["first_responded_at"] is None:
        # Only the FIRST dispatch stamps first_responded_at; re-dispatch keeps it.
        wo["first_responded_at"] = now
    wo["response_sla_breached"] = wo["first_responded_at"] > wo["response_due_at"]
    wo["status"] = "ASSIGNED"
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Start ----------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/start")
def start_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Technician", "Vendor"})
    wo = _get_work_order(wo_id)
    # Ownership (priority 3): caller must be the assigned party.
    require_assigned_party(wo, uid, role)
    # State (priority 6).
    if wo["status"] != "ASSIGNED":
        invalid_state("only an ASSIGNED work order can be started")
    b = body()
    # Entry permission is enforced again at the moment work begins (priority 7).
    if wo["entry_authorization"] == "RESIDENT_CONSENT":
        if b.get("resident_consent_confirmed") is not True:
            entry_rule("resident_consent_confirmed must be true at start")
    elif wo["entry_authorization"] == "NOTICE_POSTED":
        prop = store.properties.get(wo["property_id"])
        lead = timedelta(hours=prop["entry_notice_min_hours"])
        if store.clock < wo["notice_posted_at"] + lead:
            entry_rule("entry notice lead time has not elapsed")
    wo["status"] = "IN_PROGRESS"
    wo["started_at"] = store.clock
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Sign-off (self-transition on IN_PROGRESS) -----------------------------------

@bp.post("/work-orders/<wo_id>/sign-off")
def sign_off_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Resident"})
    wo = _get_work_order(wo_id)
    # Ownership (priority 3): only the reporting resident signs off.
    if wo["resident_id"] != uid:
        not_owner()
    if wo["status"] != "IN_PROGRESS":
        invalid_state("only an IN_PROGRESS work order can be signed off")
    wo["resident_signoff"] = True
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Complete ---------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/complete")
def complete_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Technician", "Vendor"})
    wo = _get_work_order(wo_id)
    # PRD 3.4 fixes the completion gate order: state, then ownership, then the
    # open-purchase-request block, then sign-off, then photos, then the
    # damage-estimate shape check.
    if wo["status"] != "IN_PROGRESS":
        invalid_state("only an IN_PROGRESS work order can be completed")
    require_assigned_party(wo, uid, role)
    for pr in store.purchase_requests.values():
        if pr["work_order_id"] == wo["id"] and pr["status"] in ("PENDING", "APPROVED"):
            open_purchase_requests()
    if not wo["resident_signoff"]:
        signoff_required()
    b = body()
    photos = b.get("photo_urls")
    if not isinstance(photos, list) or len(photos) < 1:
        photos_required()
    damage = b.get("damage_reported")
    damage_flag = damage is True
    estimate = b.get("estimated_damage_cost_cents")
    if damage_flag and (not is_int(estimate) or estimate <= 0):
        chargeback_lines(
            "estimated_damage_cost_cents must be present and > 0 when damage_reported is true"
        )
    # General shape (priority 21).
    if any(not is_str(p) for p in photos):
        validation("photo_urls must be an array of strings")
    if damage is not None and not isinstance(damage, bool):
        validation("damage_reported must be a boolean")

    now = store.clock
    wo["status"] = "COMPLETED"
    wo["completed_at"] = now
    wo["completion_sla_breached"] = now > wo["completion_due_at"]
    wo["photo_urls"] = list(photos)
    wo["damage_reported"] = damage_flag
    wo["estimated_damage_cost_cents"] = estimate if damage_flag else None

    # Consumption cascade: every RESERVED line becomes CONSUMED; consumption
    # debits reserved_quantity only (on_hand was debited at reserve time) and
    # recomputes each affected part's restock_status.
    for line in store.work_order_parts.values():
        if line["work_order_id"] == wo["id"] and line["status"] == "RESERVED":
            line["status"] = "CONSUMED"
            touch(line)
            part = store.parts.get(line["part_id"])
            if part is not None:
                stock_consume(part, line["quantity"])
    wo["parts_total_cents"] = sum(
        line["line_total_cents"]
        for line in store.work_order_parts.values()
        if line["work_order_id"] == wo["id"] and line["status"] == "CONSUMED"
    )

    if damage_flag:
        cb = new_record()
        cb.update(
            {
                "work_order_id": wo["id"],
                "resident_id": wo["resident_id"],
                "provisional_amount_cents": estimate,
                "line_items": [],
                "final_amount_cents": None,
                "status": "PENDING",
                "dispute_reason": None,
            }
        )
        store.chargebacks[cb["id"]] = cb

    touch(wo)
    return ok_object(work_order_out(wo))


# --- Reopen (recall) --------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/reopen")
def reopen_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Resident", "Dispatcher"})
    wo = _get_work_order(wo_id)
    if role == "Resident" and wo["resident_id"] != uid:
        not_owner()
    if wo["status"] != "COMPLETED":
        invalid_state("only a COMPLETED work order can be reopened")
    prop = store.properties.get(wo["property_id"])
    # Equality is allowed: exactly recall_window_days after completion reopens.
    deadline = wo["completed_at"] + timedelta(days=prop["recall_window_days"])
    if store.clock > deadline:
        recall_expired()
    wo["status"] = "REOPENED"
    wo["recall_count"] += 1
    wo["resident_signoff"] = False
    clear_assignment(wo)
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Close -------------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/close")
def close_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"PropertyManager"})
    wo = _get_work_order(wo_id)
    if wo["status"] != "COMPLETED":
        invalid_state("only a COMPLETED work order can be closed")
    wo["status"] = "CLOSED"
    wo["closed_at"] = store.clock
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Cancel ------------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/cancel")
def cancel_work_order(wo_id):
    uid, role = authn()
    authorize(role, {"Resident", "Dispatcher"})
    wo = _get_work_order(wo_id)
    if role == "Resident" and wo["resident_id"] != uid:
        not_owner()
    if wo["status"] not in ("TRIAGED", "ASSIGNED", "REOPENED"):
        invalid_state("only TRIAGED, ASSIGNED, or REOPENED work orders can be cancelled")
    if wo["status"] == "ASSIGNED":
        # Release cascade: every RESERVED line returns its stock.
        release_reserved_lines(wo)
        clear_assignment(wo)
    wo["status"] = "CANCELLED"
    touch(wo)
    return ok_object(work_order_out(wo))


# --- Work-order parts (reserve / release) -------------------------------------------

@bp.post("/work-orders/<wo_id>/parts")
def reserve_part(wo_id):
    uid, role = authn()
    authorize(role, {"Technician", "Vendor"})
    wo = _get_work_order(wo_id)
    # Ownership (priority 3): caller must be the assigned party.
    require_assigned_party(wo, uid, role)
    b = body()
    part_id = b.get("part_id")
    part = None
    # Existence (priority 4).
    if isinstance(part_id, str) and part_id:
        part = store.parts.get(part_id)
        if part is None:
            not_found("part")
    # State (priority 6).
    if wo["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        invalid_state("parts can be reserved only on ASSIGNED or IN_PROGRESS work orders")
    qty = b.get("quantity")
    # Business constraint (priority 15): quantity >= 1, same property, and
    # enough on-hand stock — an invalid quantity is rejected as a stock error
    # per PRD 3.6 ("a shortfall, a foreign-property part, or an invalid
    # quantity is rejected with ERR_PART_INSUFFICIENT_STOCK").
    if part is not None and is_int(qty):
        if qty < 1 or part["property_id"] != wo["property_id"] or part["quantity_on_hand"] < qty:
            part_stock()
    # General shape (priority 21).
    if not (isinstance(part_id, str) and part_id):
        validation("part_id is required")
    if not is_int(qty):
        validation("quantity must be an integer")

    rec = new_record()
    snapshot = part["unit_cost_cents"]
    rec.update(
        {
            "work_order_id": wo["id"],
            "part_id": part["id"],
            "quantity": qty,
            "unit_cost_cents_snapshot": snapshot,
            "line_total_cents": qty * snapshot,
            "status": "RESERVED",
        }
    )
    store.work_order_parts[rec["id"]] = rec
    stock_reserve(part, qty)
    return ok_object(work_order_part_out(rec), 201)


@bp.post("/work-orders/<wo_id>/parts/<wop_id>/release")
def release_part(wo_id, wop_id):
    uid, role = authn()
    authorize(role, {"Technician", "Vendor", "Dispatcher"})
    wo = _get_work_order(wo_id)
    # Ownership (priority 3): Technician/Vendor callers must be the assigned party;
    # Dispatcher is opaque and always permitted.
    if role in ("Technician", "Vendor"):
        require_assigned_party(wo, uid, role)
    line = store.work_order_parts.get(wop_id)
    if line is None or line["work_order_id"] != wo["id"]:
        not_found("work order part")
    if line["status"] != "RESERVED":
        invalid_state("only a RESERVED line can be released")
    line["status"] = "RELEASED"
    touch(line)
    part = store.parts.get(line["part_id"])
    if part is not None:
        stock_release(part, line["quantity"])
    return ok_object(work_order_part_out(line))


# --- Purchase requests (creation, OCC-guarded) --------------------------------------

@bp.post("/work-orders/<wo_id>/purchase-requests")
def create_purchase_request(wo_id):
    uid, role = authn()
    authorize(role, {"Technician", "Vendor"})
    wo = _get_work_order(wo_id)
    # Ownership (priority 3).
    require_assigned_party(wo, uid, role)
    b = body()
    part_id = b.get("part_id")
    part = None
    # Existence (priority 4).
    if isinstance(part_id, str) and part_id:
        part = store.parts.get(part_id)
        if part is None:
            not_found("part")
    # Concurrency (priority 5).
    expected = b.get("expected_work_order_version")
    if is_int(expected) and expected != wo["version"]:
        stale()
    # State (priority 6).
    if wo["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        invalid_state("purchase requests require an ASSIGNED or IN_PROGRESS work order")
    # General shape (priority 21).
    if not is_int(expected):
        validation("expected_work_order_version is required and must be an integer")
    if not (isinstance(part_id, str) and part_id):
        validation("part_id is required")
    qty = b.get("quantity")
    if not is_int(qty) or qty < 1:
        validation("quantity must be an integer >= 1")
    quoted = b.get("quoted_unit_cost_cents")
    if not is_int(quoted) or quoted < 0:
        validation("quoted_unit_cost_cents must be an integer >= 0")
    shipping = b.get("shipping_fee_cents", 0)
    if not is_int(shipping) or shipping < 0:
        validation("shipping_fee_cents must be an integer >= 0")

    # purchase_request_total calculation (PRD 3.7 / 2.6).
    subtotal = qty * quoted
    handling = (
        0
        if qty >= 10
        else int(
            (Decimal(subtotal) * Decimal("0.08")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    )
    total = subtotal + shipping + handling
    prop = store.properties.get(wo["property_id"])
    auto = total <= prop["purchase_auto_approve_threshold_cents"]

    # One active negotiation per (work order, part): supersede prior PENDING.
    for other in store.purchase_requests.values():
        if (
            other["work_order_id"] == wo["id"]
            and other["part_id"] == part["id"]
            and other["status"] == "PENDING"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    rec = new_record()
    rec.update(
        {
            "work_order_id": wo["id"],
            "part_id": part["id"],
            "quantity": qty,
            "quoted_unit_cost_cents": quoted,
            "shipping_fee_cents": shipping,
            "items_subtotal_cents": subtotal,
            "handling_fee_cents": handling,
            "estimated_total_cents": total,
            "auto_approved": auto,
            "status": "APPROVED" if auto else "PENDING",
            "decision_reason": None,
        }
    )
    store.purchase_requests[rec["id"]] = rec
    touch(wo)  # creation mutates the work order's version (scaffold side effect)
    return ok_object(purchase_request_out(rec), 201)
