"""Work orders: intake (OCC on the hangar slot), the lifecycle state machine
(PRD 3.2-3.7), checklist items, and labor entries."""

from flask import Blueprint, g

import clock as clockmod
import db
import envelope
import ops
from errors import ApiError
from middleware import require_roles
from validate import (
    apply_filters,
    body,
    get_row,
    paginate,
    req_enum,
    req_int,
    req_str,
    req_version,
)

bp = Blueprint("work_orders", __name__)

WO_STATUSES = (
    "DRAFT", "SCHEDULED", "IN_PROGRESS", "INSPECTION_COMPLETE",
    "AWAITING_OWNER_APPROVAL", "APPROVED", "WORK_IN_PROGRESS",
    "READY_FOR_RTS", "RETURNED_TO_SERVICE", "CLOSED", "CANCELLED",
)

# States in which the shop may still build the checklist (items are added
# while the order is opened/in progress; after inspection completes the list
# is frozen).
CHECKLIST_ADD_STATES = ("DRAFT", "SCHEDULED", "IN_PROGRESS")

# States in which labor may be posted.  Labor is state-gated only against the
# terminal states: posting to a RETURNED_TO_SERVICE order must surface
# ERR_INVOICE_LOCKED (priority 10) rather than ERR_INVALID_STATE, which
# requires the state gate to admit it.
LABOR_STATES = (
    "DRAFT", "SCHEDULED", "IN_PROGRESS", "INSPECTION_COMPLETE",
    "AWAITING_OWNER_APPROVAL", "APPROVED", "WORK_IN_PROGRESS",
    "READY_FOR_RTS", "RETURNED_TO_SERVICE",
)


def _wo(rid):
    return get_row(db.WORK_ORDERS, rid)


def _wo_out(wo):
    return envelope.ok(ops.pub(wo, ops.WO_F))


# --------------------------------------------------------------------------
# Create / read
# --------------------------------------------------------------------------


@bp.post("/api/work-orders")
@require_roles("ShopManager")
def create_work_order():
    b = body()
    aircraft_id = req_str(b, "aircraft_id")
    hangar_slot_id = req_str(b, "hangar_slot_id")
    opened_by_mechanic_id = req_str(b, "opened_by_mechanic_id")
    scope_type = req_enum(b, "scope_type", ("ANNUAL", "HUNDRED_HOUR", "UNSCHEDULED"))
    pricing_mode = req_enum(b, "pricing_mode", ("HOURLY", "FLAT_RATE"))
    expected_slot_version = req_version(b, "expected_hangar_slot_version")
    get_row(db.AIRCRAFT, aircraft_id)
    slot = get_row(db.HANGAR_SLOTS, hangar_slot_id)
    get_row(db.MECHANICS, opened_by_mechanic_id)
    # OCC (PRD 2.6): the client's observed slot version must still match.
    if expected_slot_version != slot["version"]:
        raise ApiError("ERR_STALE_VERSION")
    wo = {
        "aircraft_id": aircraft_id,
        "hangar_slot_id": hangar_slot_id,
        "opened_by_mechanic_id": opened_by_mechanic_id,
        "scope_type": scope_type,
        "pricing_mode": pricing_mode,
        "status": "DRAFT",
        "open_discrepancy_count": 0,
        "verified_discrepancy_count": 0,
        "labor_hours_tenths": 0,
    }
    db.stamp_new(wo)
    db.WORK_ORDERS[wo["id"]] = wo
    # Opening the work order advances the linked slot's version by one.
    db.touch(slot)
    return envelope.created(ops.pub(wo, ops.WO_F))


@bp.get("/api/work-orders")
@require_roles("ShopManager", "Mechanic", "Owner", "PartsClerk")
def list_work_orders():
    rows = apply_filters(
        list(db.WORK_ORDERS.values()),
        {
            "aircraft_id": "aircraft_id",
            "hangar_slot_id": "hangar_slot_id",
            "opened_by_mechanic_id": "opened_by_mechanic_id",
            "status": "status",
        },
    )
    return paginate(rows, ops.WO_F)


@bp.get("/api/work-orders/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner", "PartsClerk")
def get_work_order(rid):
    return _wo_out(_wo(rid))


# --------------------------------------------------------------------------
# Lifecycle transitions
# --------------------------------------------------------------------------


@bp.post("/api/work-orders/<rid>/schedule")
@require_roles("ShopManager")
def schedule_work_order(rid):
    wo = _wo(rid)
    if wo["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    slot = get_row(db.HANGAR_SLOTS, wo["hangar_slot_id"])
    if slot["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "Hangar slot is not RESERVED.")
    if slot["aircraft_id"] != wo["aircraft_id"]:
        raise ApiError(
            "ERR_INVALID_STATE", "Hangar slot aircraft does not match the work order."
        )
    for other in ops.aircraft_work_orders(wo["aircraft_id"]):
        if other["id"] != wo["id"] and other["status"] in (
            "IN_PROGRESS",
            "WORK_IN_PROGRESS",
        ):
            raise ApiError(
                "ERR_INVALID_STATE",
                "Another work order is already in progress for this aircraft.",
            )
    wo["status"] = "SCHEDULED"
    db.touch(wo)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/start")
@require_roles("Mechanic")
def start_work_order(rid):
    wo = _wo(rid)
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    ops.require_active_mechanic()
    slot = get_row(db.HANGAR_SLOTS, wo["hangar_slot_id"])
    if slot["status"] not in ("RESERVED", "OCCUPIED"):
        raise ApiError("ERR_INVALID_STATE", "Hangar slot is not RESERVED or OCCUPIED.")
    if slot["status"] != "OCCUPIED":
        slot["status"] = "OCCUPIED"
        db.touch(slot)
    wo["status"] = "IN_PROGRESS"
    db.touch(wo)
    ops.recompute_posture_for(wo["aircraft_id"])
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/complete-inspection")
@require_roles("Mechanic")
def complete_inspection(rid):
    wo = _wo(rid)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    ops.require_active_mechanic()
    items = ops.wo_checklist_items(wo["id"])
    if any(item["result"] == "PENDING" for item in items):
        raise ApiError(
            "ERR_CHECKLIST_INCOMPLETE", "Checklist items remain PENDING."
        )
    if wo["scope_type"] == "ANNUAL" and not any(
        item["result"] != "NA" for item in items
    ):
        raise ApiError(
            "ERR_CHECKLIST_INCOMPLETE",
            "An ANNUAL inspection requires at least one non-NA item.",
        )
    # Ensure every FAIL item is matched by an OPEN discrepancy.
    aircraft = get_row(db.AIRCRAFT, wo["aircraft_id"])
    owner = ops.aircraft_owner(aircraft)
    cap = owner["approval_cap_cents"] if owner else 50000
    for item in items:
        if item["result"] != "FAIL":
            continue
        existing = [
            d
            for d in ops.wo_discrepancies(wo["id"])
            if d["checklist_item_id"] == item["id"]
        ]
        if existing:
            continue
        disc = {
            "work_order_id": wo["id"],
            "checklist_item_id": item["id"],
            "description": item["description"],
            "severity": ops.AUTO_DISCREPANCY_SEVERITY,
            "estimated_cost_cents": ops.AUTO_DISCREPANCY_ESTIMATE_CENTS,
            "status": "OPEN",
            "requires_owner_decision": ops.AUTO_DISCREPANCY_ESTIMATE_CENTS >= cap,
            "decided_by_owner_id": None,
            "_rectified_by": None,
        }
        db.stamp_new(disc)
        db.DISCREPANCIES[disc["id"]] = disc
    wo["status"] = "INSPECTION_COMPLETE"
    wo["open_discrepancy_count"] = sum(
        1
        for d in ops.wo_discrepancies(wo["id"])
        if d["status"] in ops.DISC_OPEN_STATUSES
    )
    wo["verified_discrepancy_count"] = sum(
        1 for d in ops.wo_discrepancies(wo["id"]) if d["status"] == "VERIFIED"
    )
    db.touch(wo)  # one bump for the transition plus recomputation
    ops.recompute_posture(aircraft)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/submit-for-approval")
@require_roles("Mechanic")
def submit_for_approval(rid):
    wo = _wo(rid)
    if wo["status"] != "INSPECTION_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")
    ops.require_active_mechanic()
    discs = ops.wo_discrepancies(wo["id"])
    open_count = sum(1 for d in discs if d["status"] in ops.DISC_OPEN_STATUSES)
    actionable = [
        d for d in discs if d["status"] in ("OPEN", "PENDING_OWNER_DECISION")
    ]
    if open_count == 0 or not actionable:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Submission requires open findings with at least one awaiting disposition.",
        )
    aircraft = get_row(db.AIRCRAFT, wo["aircraft_id"])
    owner = ops.aircraft_owner(aircraft)
    cap = owner["approval_cap_cents"] if owner else 50000
    for disc in discs:
        if disc["status"] != "OPEN":
            continue
        # The owner's approval cap bites at this instant (PRD 3.5).
        disc["requires_owner_decision"] = disc["estimated_cost_cents"] >= cap
        if disc["requires_owner_decision"]:
            disc["status"] = "PENDING_OWNER_DECISION"
        else:
            disc["status"] = "APPROVED"  # under-cap auto-approval
        db.touch(disc)
    wo["status"] = "AWAITING_OWNER_APPROVAL"
    db.touch(wo)
    ops.maybe_auto_advance(wo)
    ops.recompute_posture(aircraft)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/reopen-inspection")
@require_roles("Owner")
def reopen_inspection(rid):
    wo = _wo(rid)
    if wo["status"] != "AWAITING_OWNER_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    aircraft = get_row(db.AIRCRAFT, wo["aircraft_id"])
    if aircraft["owner_id"] != g.user_id:
        raise ApiError(
            "ERR_OWNER_DECISION_REQUIRED",
            "Only the aircraft's registered owner may reopen the inspection.",
        )
    for disc in ops.wo_discrepancies(wo["id"]):
        if disc["status"] == "PENDING_OWNER_DECISION":
            disc["status"] = "OPEN"
            db.touch(disc)
    wo["status"] = "IN_PROGRESS"
    db.touch(wo)
    ops.recompute_posture(aircraft)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/begin-work")
@require_roles("Mechanic")
def begin_work(rid):
    wo = _wo(rid)
    if wo["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    ops.require_active_mechanic()
    discs = ops.wo_discrepancies(wo["id"])
    if any(d["status"] in ("OPEN", "PENDING_OWNER_DECISION") for d in discs):
        raise ApiError("ERR_INVALID_STATE", "Findings remain awaiting disposition.")
    any_approved = any(d["status"] == "APPROVED" for d in discs)
    all_done = bool(discs) and all(
        d["status"] in ("RECTIFIED", "VERIFIED") for d in discs
    )
    if not (any_approved or all_done):
        raise ApiError(
            "ERR_INVALID_STATE",
            "No approved work to begin and findings are not all rectified or verified.",
        )
    wo["status"] = "WORK_IN_PROGRESS"
    db.touch(wo)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/ready-for-rts")
@require_roles("Mechanic")
def ready_for_rts(rid):
    wo = _wo(rid)
    if wo["status"] != "WORK_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    ops.require_active_mechanic()
    discs = ops.wo_discrepancies(wo["id"])
    open_count = sum(1 for d in discs if d["status"] in ops.DISC_OPEN_STATUSES)
    air_unfinished = any(
        d["severity"] == "AIRWORTHINESS" and d["status"] != "VERIFIED" for d in discs
    )
    ads_open = any(
        d["directive_type"] == "AD"
        and d["compliance_status"] not in ("COMPLIED", "NOT_APPLICABLE")
        for d in ops.aircraft_directives(wo["aircraft_id"])
    )
    if open_count != 0 or air_unfinished or ads_open:
        raise ApiError(
            "ERR_AIRWORTHINESS_BLOCKED",
            "Regulatory gate: open findings, unverified airworthiness discrepancies, or open ADs.",
        )
    wo["status"] = "READY_FOR_RTS"
    db.touch(wo)
    ops.recompute_posture_for(wo["aircraft_id"])
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/return-to-service")
@require_roles("Mechanic")
def return_to_service(rid):
    wo = _wo(rid)
    if wo["status"] != "READY_FOR_RTS":
        raise ApiError("ERR_INVALID_STATE")
    mechanic = ops.require_active_mechanic()
    if wo["scope_type"] == "ANNUAL" and mechanic["certificate_class"] != "IA":
        raise ApiError(
            "ERR_CERTIFICATE_INSUFFICIENT",
            "Return to service of ANNUAL-scope work requires an IA certificate.",
        )
    aircraft = get_row(db.AIRCRAFT, wo["aircraft_id"])
    ops.recompute_posture(aircraft)
    if aircraft["airworthiness_posture"] != "AIRWORTHY":
        raise ApiError(
            "ERR_AIRWORTHINESS_BLOCKED",
            "Aircraft airworthiness posture is not AIRWORTHY.",
        )
    rts_entries = [
        e
        for e in db.LOGBOOK_ENTRIES.values()
        if e["work_order_id"] == wo["id"] and e["entry_type"] == "RTS_STATEMENT"
    ]
    if not rts_entries:
        raise ApiError(
            "ERR_AIRWORTHINESS_BLOCKED",
            "An RTS_STATEMENT logbook entry must exist before return to service.",
        )
    slot = get_row(db.HANGAR_SLOTS, wo["hangar_slot_id"])
    if slot["status"] != "RELEASED":
        slot["status"] = "RELEASED"
        db.touch(slot)
    wo["status"] = "RETURNED_TO_SERVICE"
    db.touch(wo)
    ops.create_invoice_for(wo)  # DRAFT invoice with all computed lines
    ops.recompute_posture(aircraft)
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/close")
@require_roles("ShopManager")
def close_work_order(rid):
    wo = _wo(rid)
    if wo["status"] != "RETURNED_TO_SERVICE":
        raise ApiError("ERR_INVALID_STATE")
    invoice = ops.active_invoice_for(wo["id"])
    if invoice is None or invoice["status"] not in ("PAID", "VOIDED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Invoice must be PAID or VOIDED before closing."
        )
    wo["status"] = "CLOSED"
    db.touch(wo)
    ops.recompute_posture_for(wo["aircraft_id"])
    return _wo_out(wo)


@bp.post("/api/work-orders/<rid>/cancel")
@require_roles("ShopManager")
def cancel_work_order(rid):
    wo = _wo(rid)
    if wo["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    slot = db.HANGAR_SLOTS.get(wo["hangar_slot_id"])
    if slot is not None and slot["status"] != "CANCELLED":
        slot["status"] = "CANCELLED"
        db.touch(slot)
    wo["status"] = "CANCELLED"
    db.touch(wo)
    ops.recompute_posture_for(wo["aircraft_id"])
    return _wo_out(wo)


# --------------------------------------------------------------------------
# Checklist items
# --------------------------------------------------------------------------


@bp.post("/api/work-orders/<rid>/checklist-items")
@require_roles("Mechanic")
def add_checklist_item(rid):
    wo = _wo(rid)
    b = body()
    item_code = req_str(b, "item_code")
    description = req_str(b, "description")
    flat_rate_cents = req_int(b, "flat_rate_cents")
    if wo["status"] not in CHECKLIST_ADD_STATES:
        raise ApiError(
            "ERR_INVALID_STATE", "Checklist items may be added only before inspection completes."
        )
    item = {
        "work_order_id": wo["id"],
        "item_code": item_code,
        "description": description,
        "flat_rate_cents": flat_rate_cents,
        "result": "PENDING",
        "inspected_by_mechanic_id": None,
    }
    db.stamp_new(item, versioned=False)
    db.CHECKLIST_ITEMS[item["id"]] = item
    return envelope.created(ops.pub(item, ops.CHECKLIST_F))


@bp.get("/api/work-orders/<rid>/checklist-items")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_wo_checklist_items(rid):
    _wo(rid)
    rows = [c for c in db.CHECKLIST_ITEMS.values() if c["work_order_id"] == rid]
    rows = apply_filters(
        rows, {"result": "result", "inspected_by_mechanic_id": "inspected_by_mechanic_id"}
    )
    return paginate(rows, ops.CHECKLIST_F)


@bp.get("/api/checklist-items/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_checklist_item(rid):
    item = get_row(db.CHECKLIST_ITEMS, rid)
    return envelope.ok(ops.pub(item, ops.CHECKLIST_F))


@bp.get("/api/checklist-items")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_checklist_items():
    rows = apply_filters(
        list(db.CHECKLIST_ITEMS.values()),
        {
            "work_order_id": "work_order_id",
            "inspected_by_mechanic_id": "inspected_by_mechanic_id",
            "result": "result",
        },
    )
    return paginate(rows, ops.CHECKLIST_F)


@bp.post("/api/work-orders/<rid>/checklist-items/<item_id>/record")
@require_roles("Mechanic")
def record_checklist_item(rid, item_id):
    wo = _wo(rid)
    item = db.CHECKLIST_ITEMS.get(item_id)
    if item is None or item["work_order_id"] != wo["id"]:
        raise ApiError("ERR_NOT_FOUND", "Checklist item not found: %s" % item_id)
    b = body()
    result = req_enum(b, "result", ("PASS", "FAIL", "NA"))
    inspected_by = req_str(b, "inspected_by_mechanic_id")
    get_row(db.MECHANICS, inspected_by)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE", "Results are recorded while the order is in progress."
        )
    item["result"] = result
    item["inspected_by_mechanic_id"] = inspected_by
    return envelope.ok(ops.pub(item, ops.CHECKLIST_F))


# --------------------------------------------------------------------------
# Labor entries
# --------------------------------------------------------------------------


@bp.post("/api/work-orders/<rid>/labor-entries")
@require_roles("Mechanic")
def post_labor_entry(rid):
    wo = _wo(rid)
    b = body()
    mechanic_id = req_str(b, "mechanic_id")
    duration_tenths = req_int(b, "duration_tenths")
    notes = req_str(b, "notes")
    get_row(db.MECHANICS, mechanic_id)
    if (
        duration_tenths <= 0
        or duration_tenths % 3 != 0
    ):
        raise ApiError(
            "ERR_VALIDATION",
            "duration_tenths must be positive and a multiple of 3.",
        )
    if wo["status"] not in LABOR_STATES:
        raise ApiError(
            "ERR_INVALID_STATE", "Labor cannot be posted in the current state."
        )
    # Priority 7: same-day cumulative billable time may not exceed 10.0h.
    today = clockmod.now().date()
    same_day = 0
    for entry in db.LABOR_ENTRIES.values():
        if entry["mechanic_id"] != mechanic_id or entry["status"] != "POSTED":
            continue
        if entry["_posted_at"].date() == today:
            same_day += entry["duration_tenths"]
    if same_day + duration_tenths > ops.MECHANIC_DAILY_CAP_TENTHS:
        raise ApiError("ERR_MECHANIC_OVERBOOKED")
    # Priority 10: an ISSUED/PAID invoice locks further labor.
    if ops.invoice_locked(wo["id"]):
        raise ApiError("ERR_INVOICE_LOCKED")
    entry = {
        "work_order_id": wo["id"],
        "mechanic_id": mechanic_id,
        "duration_tenths": duration_tenths,
        "notes": notes,
        "status": "POSTED",
        "_posted_at": clockmod.now(),
    }
    db.stamp_new(entry, versioned=False)
    db.LABOR_ENTRIES[entry["id"]] = entry
    ops.recompute_wo_counts(wo)
    return envelope.created(ops.pub(entry, ops.LABOR_F))


@bp.get("/api/work-orders/<rid>/labor-entries")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_wo_labor_entries(rid):
    _wo(rid)
    rows = [e for e in db.LABOR_ENTRIES.values() if e["work_order_id"] == rid]
    rows = apply_filters(rows, {"status": "status", "mechanic_id": "mechanic_id"})
    return paginate(rows, ops.LABOR_F)


@bp.get("/api/labor-entries/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_labor_entry(rid):
    entry = get_row(db.LABOR_ENTRIES, rid)
    return envelope.ok(ops.pub(entry, ops.LABOR_F))


@bp.get("/api/labor-entries")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_labor_entries():
    rows = apply_filters(
        list(db.LABOR_ENTRIES.values()),
        {
            "work_order_id": "work_order_id",
            "mechanic_id": "mechanic_id",
            "status": "status",
        },
    )
    return paginate(rows, ops.LABOR_F)


# --------------------------------------------------------------------------
# Nested listings
# --------------------------------------------------------------------------


@bp.get("/api/work-orders/<rid>/discrepancies")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_wo_discrepancies(rid):
    _wo(rid)
    rows = [d for d in db.DISCREPANCIES.values() if d["work_order_id"] == rid]
    rows = apply_filters(
        rows,
        {
            "status": "status",
            "checklist_item_id": "checklist_item_id",
            "decided_by_owner_id": "decided_by_owner_id",
        },
    )
    return paginate(rows, ops.DISCREPANCY_F)


@bp.get("/api/work-orders/<rid>/invoice")
@require_roles("ShopManager", "Owner")
def get_wo_invoice(rid):
    _wo(rid)
    rows = ops.wo_invoices(rid)
    return paginate(rows, ops.INVOICE_F)
