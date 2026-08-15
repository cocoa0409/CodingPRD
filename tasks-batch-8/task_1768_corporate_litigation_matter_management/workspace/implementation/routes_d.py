"""Routes: litigation holds, hold custodians, discovery vendors, work orders, deadlines."""
from datetime import timedelta

from flask import request

import calc
from db import new_common, parse_dt, store, touch
from errors import (
    ERR_CROSS_REFERENCE_MISMATCH,
    ERR_CUSTODIAN_SELF_ACK_REQUIRED,
    ERR_DEADLINE_TIMING,
    ERR_DUPLICATE,
    ERR_FIELD_CONSTRAINT,
    ERR_HOLD_COMPLIANCE_BLOCK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MATTER_POSTURE_FROZEN,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENCE_STATE_INVALID,
    ERR_SCHEDULE_CONFLICT,
    ERR_VENDOR_CAPACITY_EXCEEDED,
    ERR_VENDOR_CLEARANCE_INSUFFICIENT,
    raise_err,
)
from middleware import (
    READ_SET,
    apply_filters,
    auth,
    get_body,
    paginate,
    parse_bool_filter,
)
from response import ok_list, ok_object
from routes_b import get_matter
from serializers import serialize
from validation import check_constraints_11, check_shape_23, reject_extra_fields

LC = ("LitigationCounsel",)
LOA = ("LegalOperationsAnalyst",)
STAFF = ("StaffUser",)

RELEASE_REASONS = ("MATTER_RESOLVED", "SCOPE_NARROWED", "COURT_ORDER", "ERROR")
CLEARANCE_LEVELS = ("STANDARD", "ENHANCED", "RESTRICTED")
SERVICE_TYPES = ("COLLECTION", "PROCESSING", "HOSTING", "REVIEW", "PRODUCTION")
DEADLINE_TYPES = ("COURT_DEADLINE", "HEARING", "DISCOVERY_CUTOFF", "FILING", "INTERNAL_REVIEW", "LIMITATION_EXPIRY")

VENDOR_CREATE_SPEC = {
    "vendor_name": {"type": "str", "required": True},
    "security_clearance_level": {"type": "enum", "enum": CLEARANCE_LEVELS, "required": True},
    "capacity_gb": {"type": "int", "required": True, "positive": True},
    "is_active": {"type": "bool"},
}

WORK_ORDER_CREATE_SPEC = {
    "vendor_id": {"type": "str", "required": True},
    "hold_id": {"type": "str", "required": True},
    "service_type": {"type": "enum", "enum": SERVICE_TYPES, "required": True},
    "estimated_gb": {"type": "int", "required": True, "positive": True},
    "rate_per_gb_cents": {"type": "int", "required": True, "positive": True},
    "scheduled_start": {"type": "datetime", "required": True},
    "scheduled_end": {"type": "datetime", "required": True},
}

DEADLINE_CREATE_SPEC = {
    "deadline_type": {"type": "enum", "enum": DEADLINE_TYPES, "required": True},
    "title": {"type": "str", "required": True},
    "due_at": {"type": "datetime", "required": True},
    "is_jurisdictional": {"type": "bool"},
    "reminder_days": {"type": "int", "min": 0},
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_hold(hid):
    rec = store.holds.get(hid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Litigation hold %s does not exist." % hid)
    return rec


def get_custodian(cid):
    rec = store.custodians.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Hold custodian %s does not exist." % cid)
    return rec


def get_vendor(vid):
    rec = store.vendors.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Discovery vendor %s does not exist." % vid)
    return rec


def get_work_order(wid):
    rec = store.work_orders.get(wid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Work order %s does not exist." % wid)
    return rec


def get_deadline(did):
    rec = store.deadlines.get(did)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Deadline %s does not exist." % did)
    return rec


def _clearance_ok(matter_type, clearance):
    if matter_type in ("CLASS_ACTION", "REGULATORY"):
        return clearance == "RESTRICTED"
    if matter_type in ("EMPLOYMENT", "IP"):
        return clearance in ("ENHANCED", "RESTRICTED")
    return True


def register(app):

    # ------------------------------------------------------------------ holds
    @app.post("/litigation/matters/<mid>/holds")
    def create_hold(mid):
        auth(LC)
        get_matter(mid)
        body = get_body()
        check_shape_23(body, {"scope_description": {"type": "str", "required": True}})
        rec = new_common(
            {
                "matter_id": mid,
                "scope_description": body["scope_description"],
                "status": "DRAFT",
                "issued_at": None,
                "released_at": None,
                "release_reason": None,
            }
        )
        store.holds[rec["id"]] = rec
        return ok_object(serialize("hold", rec), 201)

    @app.get("/litigation/matters/<mid>/holds")
    def list_matter_holds(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [h for h in store.holds.values() if h["matter_id"] == mid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("hold", r) for r in page], limit, offset, total)

    @app.get("/litigation/holds/<hid>")
    def get_one_hold(hid):
        auth(READ_SET)
        return ok_object(serialize("hold", get_hold(hid)))

    @app.post("/litigation/holds/<hid>/issue")
    def issue_hold(hid):
        auth(LC)
        hold = get_hold(hid)
        body = get_body()
        if hold["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT hold may be issued.")
        matter = store.matters.get(hold["matter_id"])
        if matter is None or matter["status"] not in ("ASSESSMENT", "STAFFING", "ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter is not in a state that allows issuance.")
        # (9) posture gate
        if matter["posture"] == "FROZEN":
            raise_err(ERR_MATTER_POSTURE_FROZEN, "The matter posture is FROZEN.")
        if not any(c["hold_id"] == hid for c in store.custodians.values()):
            raise_err(ERR_INVALID_STATE, "At least one custodian is required before issuance.")
        reject_extra_fields(body, ())
        hold["status"] = "ISSUED"
        hold["issued_at"] = store.clock
        touch(hold)
        for c in store.custodians.values():
            if c["hold_id"] == hid and c["status"] == "NOTICED":
                if c["noticed_at"] != store.clock:
                    c["noticed_at"] = store.clock
                    touch(c)
        return ok_object(serialize("hold", hold))

    @app.post("/litigation/holds/<hid>/release")
    def release_hold_endpoint(hid):
        auth(LC)
        hold = get_hold(hid)
        body = get_body()
        if hold["status"] not in ("ISSUED", "ACKNOWLEDGED", "DRAFT"):
            raise_err(ERR_INVALID_STATE, "Only an ISSUED, ACKNOWLEDGED or DRAFT hold may be released.")
        # (8) work orders pin the hold
        for wo in store.work_orders.values():
            if wo["hold_id"] == hid and wo["status"] in ("AUTHORIZED", "IN_PROGRESS"):
                raise_err(ERR_HOLD_COMPLIANCE_BLOCK, "Active work orders pin this hold open.")
        # (11) release_reason enum
        check_constraints_11(body, {"release_reason": {"type": "enum", "enum": RELEASE_REASONS}})
        # (23) request shape
        check_shape_23(body, {"release_reason": {"type": "enum", "enum": RELEASE_REASONS, "required": True}})
        cascade = hold["status"] in ("ISSUED", "ACKNOWLEDGED")
        calc.release_hold(hold, body["release_reason"], cascade_custodians=cascade)
        return ok_object(serialize("hold", hold))

    # ------------------------------------------------------------- custodians
    @app.post("/litigation/holds/<hid>/custodians")
    def add_custodian(hid):
        auth(LC)
        hold = get_hold(hid)
        body = get_body()
        # (4) body FK existence
        staff = None
        if isinstance(body, dict):
            suid = body.get("staff_user_id")
            if isinstance(suid, str) and suid != "":
                staff = store.staff_users.get(suid)
                if staff is None:
                    raise_err(ERR_REFERENCE_NOT_FOUND, "staff_user_id does not name a staff user.")
        # (5) a RELEASED (terminal) hold takes no new custodians
        if hold["status"] == "RELEASED":
            raise_err(ERR_INVALID_STATE, "A RELEASED hold takes no new custodians.")
        # (12) custodian unique per hold
        if isinstance(body, dict) and isinstance(body.get("staff_user_id"), str):
            for c in store.custodians.values():
                if c["hold_id"] == hid and c["staff_user_id"] == body["staff_user_id"]:
                    raise_err(ERR_DUPLICATE, "This staff user is already a custodian of the hold.")
        # (16) a deactivated staff member may not be named as custodian
        if staff is not None and not staff.get("is_active", True):
            raise_err(ERR_REFERENCE_STATE_INVALID, "A deactivated staff member may not be a custodian.")
        # (23) request shape
        check_shape_23(body, {"staff_user_id": {"type": "str", "required": True}})
        rec = new_common(
            {
                "hold_id": hid,
                "staff_user_id": body["staff_user_id"],
                "status": "NOTICED",
                "noticed_at": store.clock,
                "acknowledged_at": None,
                "escalation_count": 0,
                "exemption_reason": None,
            }
        )
        store.custodians[rec["id"]] = rec
        return ok_object(serialize("custodian", rec), 201)

    @app.get("/litigation/holds/<hid>/custodians")
    def list_custodians(hid):
        auth(READ_SET)
        get_hold(hid)
        records = apply_filters(
            [c for c in store.custodians.values() if c["hold_id"] == hid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("custodian", r) for r in page], limit, offset, total)

    @app.get("/litigation/hold-custodians/<cid>")
    def get_one_custodian(cid):
        auth(READ_SET)
        return ok_object(serialize("custodian", get_custodian(cid)))

    @app.post("/litigation/hold-custodians/<cid>/acknowledge")
    def acknowledge_custodian(cid):
        uid, _ = auth(STAFF)
        cust = get_custodian(cid)
        body = get_body()
        if cust["status"] not in ("NOTICED", "ESCALATED"):
            raise_err(ERR_INVALID_STATE, "Only a NOTICED or ESCALATED custodian may acknowledge.")
        hold = store.holds.get(cust["hold_id"])
        if hold is None or hold["status"] not in ("DRAFT", "ISSUED"):
            raise_err(ERR_INVALID_STATE, "The parent hold is not in a state that allows acknowledgement.")
        # (27) the custodian acknowledges for self
        if uid != cust["staff_user_id"]:
            raise_err(ERR_CUSTODIAN_SELF_ACK_REQUIRED, "A custodian may only acknowledge their own notice.")
        reject_extra_fields(body, ())
        cust["status"] = "ACKNOWLEDGED"
        cust["acknowledged_at"] = store.clock
        touch(cust)
        calc.bubble_up_hold(hold)
        return ok_object(serialize("custodian", cust))

    @app.post("/litigation/hold-custodians/<cid>/escalate")
    def escalate_custodian(cid):
        auth(LC)
        cust = get_custodian(cid)
        body = get_body()
        if cust["status"] != "NOTICED":
            raise_err(ERR_INVALID_STATE, "Only a NOTICED custodian may be escalated.")
        hold = store.holds.get(cust["hold_id"])
        if hold is None or hold["status"] != "ISSUED":
            raise_err(ERR_INVALID_STATE, "The parent hold must be ISSUED to escalate a custodian.")
        # (13) five-day cooling period after noticed_at
        if store.clock < cust["noticed_at"] + timedelta(days=5):
            raise_err(ERR_SCHEDULE_CONFLICT, "The five-day escalation cooling period has not elapsed.")
        reject_extra_fields(body, ())
        cust["status"] = "ESCALATED"
        cust["escalation_count"] = cust.get("escalation_count", 0) + 1
        touch(cust)
        return ok_object(serialize("custodian", cust))

    @app.post("/litigation/hold-custodians/<cid>/exempt")
    def exempt_custodian(cid):
        auth(LC)
        cust = get_custodian(cid)
        body = get_body()
        if cust["status"] not in ("NOTICED", "ESCALATED"):
            raise_err(ERR_INVALID_STATE, "Only a NOTICED or ESCALATED custodian may be exempted.")
        check_shape_23(body, {"exemption_reason": {"type": "str", "required": True}})
        cust["status"] = "EXEMPTED"
        cust["exemption_reason"] = body["exemption_reason"]
        touch(cust)
        hold = store.holds.get(cust["hold_id"])
        if hold is not None:
            calc.bubble_up_hold(hold)
        return ok_object(serialize("custodian", cust))

    # ---------------------------------------------------------------- vendors
    @app.post("/litigation/discovery-vendors")
    def create_vendor():
        auth(LOA)
        body = get_body()
        check_constraints_11(body, VENDOR_CREATE_SPEC)
        check_shape_23(body, VENDOR_CREATE_SPEC)
        rec = new_common(
            {
                "vendor_name": body["vendor_name"],
                "security_clearance_level": body["security_clearance_level"],
                "capacity_gb": body["capacity_gb"],
                "committed_gb": 0,
                "is_active": body.get("is_active", True),
            }
        )
        store.vendors[rec["id"]] = rec
        return ok_object(serialize("vendor", rec), 201)

    @app.get("/litigation/discovery-vendors")
    def list_vendors():
        auth(READ_SET)
        records = apply_filters(
            store.vendors.values(),
            [
                ("security_clearance_level", request.args.get("security_clearance_level")),
                ("is_active", parse_bool_filter(request.args.get("is_active"))),
            ],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("vendor", r) for r in page], limit, offset, total)

    @app.get("/litigation/discovery-vendors/<vid>")
    def get_one_vendor(vid):
        auth(READ_SET)
        return ok_object(serialize("vendor", get_vendor(vid)))

    @app.get("/litigation/discovery-vendors/<vid>/work-orders")
    def list_vendor_work_orders(vid):
        auth(READ_SET)
        get_vendor(vid)
        records = apply_filters(
            [w for w in store.work_orders.values() if w["vendor_id"] == vid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("work_order", r) for r in page], limit, offset, total)

    # ------------------------------------------------------------ work orders
    @app.post("/litigation/matters/<mid>/work-orders")
    def create_work_order(mid):
        auth(LOA)
        get_matter(mid)
        body = get_body()
        # (4) body FK existence
        vendor = None
        hold = None
        if isinstance(body, dict):
            vid = body.get("vendor_id")
            if isinstance(vid, str) and vid != "":
                vendor = store.vendors.get(vid)
                if vendor is None:
                    raise_err(ERR_REFERENCE_NOT_FOUND, "vendor_id does not name a discovery vendor.")
            hid = body.get("hold_id")
            if isinstance(hid, str) and hid != "":
                hold = store.holds.get(hid)
                if hold is None:
                    raise_err(ERR_REFERENCE_NOT_FOUND, "hold_id does not name a litigation hold.")
        # (11) scalar + window constraints
        check_constraints_11(body, WORK_ORDER_CREATE_SPEC)
        if isinstance(body, dict):
            start = parse_dt(body.get("scheduled_start"))
            end = parse_dt(body.get("scheduled_end"))
            if start is not None and end is not None and end <= start:
                raise_err(ERR_FIELD_CONSTRAINT, "scheduled_end must be strictly after scheduled_start.")
        # (15) the hold must belong to this matter and be ISSUED or ACKNOWLEDGED
        if hold is not None:
            if hold["matter_id"] != mid or hold["status"] not in ("ISSUED", "ACKNOWLEDGED"):
                raise_err(
                    ERR_CROSS_REFERENCE_MISMATCH,
                    "hold_id must name a hold of the same matter in ISSUED or ACKNOWLEDGED.",
                )
        # (16) inactive vendors cannot receive new work orders
        if vendor is not None and not vendor.get("is_active", True):
            raise_err(ERR_REFERENCE_STATE_INVALID, "Inactive vendors cannot receive new work orders.")
        # (23) request shape
        check_shape_23(body, WORK_ORDER_CREATE_SPEC)
        rec = new_common(
            {
                "matter_id": mid,
                "vendor_id": body["vendor_id"],
                "hold_id": body["hold_id"],
                "service_type": body["service_type"],
                "status": "DRAFT",
                "estimated_gb": body["estimated_gb"],
                "actual_gb": None,
                "rate_per_gb_cents": body["rate_per_gb_cents"],
                "scheduled_start": parse_dt(body["scheduled_start"]),
                "scheduled_end": parse_dt(body["scheduled_end"]),
                "estimated_cost_cents": calc.work_order_cost(body["estimated_gb"], body["rate_per_gb_cents"]),
            }
        )
        store.work_orders[rec["id"]] = rec
        return ok_object(serialize("work_order", rec), 201)

    @app.get("/litigation/matters/<mid>/work-orders")
    def list_matter_work_orders(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [w for w in store.work_orders.values() if w["matter_id"] == mid],
            [("status", request.args.get("status"))],
        )
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("work_order", r) for r in page], limit, offset, total)

    @app.get("/litigation/holds/<hid>/work-orders")
    def list_hold_work_orders(hid):
        auth(READ_SET)
        get_hold(hid)
        records = [w for w in store.work_orders.values() if w["hold_id"] == hid]
        page, limit, offset, total = paginate(records)
        return ok_list([serialize("work_order", r) for r in page], limit, offset, total)

    @app.get("/litigation/work-orders/<wid>")
    def get_one_work_order(wid):
        auth(READ_SET)
        return ok_object(serialize("work_order", get_work_order(wid)))

    @app.post("/litigation/work-orders/<wid>/authorize")
    def authorize_work_order(wid):
        auth(LOA)
        wo = get_work_order(wid)
        body = get_body()
        if wo["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Only a DRAFT work order may be authorized.")
        matter = store.matters.get(wo["matter_id"])
        if matter is None or matter["status"] not in ("ACTIVE", "REOPENED"):
            raise_err(ERR_INVALID_STATE, "The linked matter must be ACTIVE or REOPENED.")
        # (9) posture gate: RESTRICTED or FROZEN blocks new spend authorization
        if matter["posture"] != "OPEN":
            raise_err(ERR_MATTER_POSTURE_FROZEN, "The matter posture blocks work-order authorization.")
        # (10) vendor clearance matrix
        vendor = store.vendors.get(wo["vendor_id"])
        if vendor is not None and not _clearance_ok(matter["matter_type"], vendor["security_clearance_level"]):
            raise_err(ERR_VENDOR_CLEARANCE_INSUFFICIENT, "Vendor clearance is insufficient for this matter type.")
        # (13) temporal conflict gate (half-open windows; adjacency permitted)
        for other in store.work_orders.values():
            if (
                other["id"] != wo["id"]
                and other["vendor_id"] == wo["vendor_id"]
                and other["status"] in ("AUTHORIZED", "IN_PROGRESS")
                and wo["scheduled_start"] < other["scheduled_end"]
                and other["scheduled_start"] < wo["scheduled_end"]
            ):
                raise_err(ERR_SCHEDULE_CONFLICT, "The window overlaps another authorized order of this vendor.")
        # (15) hold of the same matter in ISSUED or ACKNOWLEDGED
        hold = store.holds.get(wo["hold_id"])
        if hold is None or hold["matter_id"] != wo["matter_id"] or hold["status"] not in ("ISSUED", "ACKNOWLEDGED"):
            raise_err(
                ERR_CROSS_REFERENCE_MISMATCH,
                "hold_id must name a hold of the same matter in ISSUED or ACKNOWLEDGED.",
            )
        # (16) vendor must be active
        if vendor is None or not vendor.get("is_active", True):
            raise_err(ERR_REFERENCE_STATE_INVALID, "The vendor is not active.")
        # (18) capacity gate
        if vendor["committed_gb"] + wo["estimated_gb"] > vendor["capacity_gb"]:
            raise_err(ERR_VENDOR_CAPACITY_EXCEEDED, "The vendor's capacity would be exceeded.")
        reject_extra_fields(body, ())
        wo["status"] = "AUTHORIZED"
        wo["estimated_cost_cents"] = calc.work_order_cost(wo["estimated_gb"], wo["rate_per_gb_cents"])
        touch(wo)
        calc.vendor_recompute(vendor)
        return ok_object(serialize("work_order", wo))

    @app.post("/litigation/work-orders/<wid>/start")
    def start_work_order(wid):
        auth(LOA)
        wo = get_work_order(wid)
        body = get_body()
        if wo["status"] != "AUTHORIZED":
            raise_err(ERR_INVALID_STATE, "Only an AUTHORIZED work order may be started.")
        # (9) posture gate
        matter = store.matters.get(wo["matter_id"])
        if matter is not None and matter["posture"] == "FROZEN":
            raise_err(ERR_MATTER_POSTURE_FROZEN, "The matter posture is FROZEN.")
        # (13) cannot start before scheduled_start
        if store.clock < wo["scheduled_start"]:
            raise_err(ERR_SCHEDULE_CONFLICT, "The work order cannot start before its scheduled_start.")
        reject_extra_fields(body, ())
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        return ok_object(serialize("work_order", wo))

    @app.post("/litigation/work-orders/<wid>/complete")
    def complete_work_order(wid):
        auth(LOA)
        wo = get_work_order(wid)
        body = get_body()
        if wo["status"] != "IN_PROGRESS":
            raise_err(ERR_INVALID_STATE, "Only an IN_PROGRESS work order may be completed.")
        check_constraints_11(body, {"actual_gb": {"type": "int", "min": 0}})
        check_shape_23(body, {"actual_gb": {"type": "int", "required": True}})
        wo["status"] = "COMPLETED"
        wo["actual_gb"] = body["actual_gb"]
        if body["actual_gb"] > 0:
            wo["estimated_cost_cents"] = calc.work_order_cost(body["actual_gb"], wo["rate_per_gb_cents"])
        touch(wo)
        vendor = store.vendors.get(wo["vendor_id"])
        if vendor is not None:
            calc.vendor_recompute(vendor)
        return ok_object(serialize("work_order", wo))

    @app.post("/litigation/work-orders/<wid>/cancel")
    def cancel_work_order_endpoint(wid):
        auth(LOA)
        wo = get_work_order(wid)
        body = get_body()
        if wo["status"] not in ("DRAFT", "AUTHORIZED", "IN_PROGRESS"):
            raise_err(ERR_INVALID_STATE, "Only a DRAFT, AUTHORIZED or IN_PROGRESS work order may be cancelled.")
        reject_extra_fields(body, ())
        calc.cancel_work_order(wo)
        return ok_object(serialize("work_order", wo))

    # -------------------------------------------------------------- deadlines
    @app.post("/litigation/matters/<mid>/deadlines")
    def create_deadline(mid):
        auth(LC)
        get_matter(mid)
        body = get_body()
        check_constraints_11(body, DEADLINE_CREATE_SPEC)
        check_shape_23(body, DEADLINE_CREATE_SPEC)
        rec = new_common(
            {
                "matter_id": mid,
                "deadline_type": body["deadline_type"],
                "title": body["title"],
                "due_at": parse_dt(body["due_at"]),
                "status": "SCHEDULED",
                "is_jurisdictional": body.get("is_jurisdictional", False),
                "completed_at": None,
                "reminder_days": body.get("reminder_days", 7),
            }
        )
        store.deadlines[rec["id"]] = rec
        return ok_object(serialize("deadline", rec), 201)

    @app.get("/litigation/matters/<mid>/deadlines")
    def list_matter_deadlines(mid):
        auth(READ_SET)
        get_matter(mid)
        records = apply_filters(
            [d for d in store.deadlines.values() if d["matter_id"] == mid],
            [
                ("status", request.args.get("status")),
                ("deadline_type", request.args.get("deadline_type")),
            ],
        )
        # Calendar list sorts by due_at ascending (PRD 2.3 exception).
        page, limit, offset, total = paginate(records, sort_key=lambda r: (r["due_at"], r["_seq"]))
        return ok_list([serialize("deadline", r) for r in page], limit, offset, total)

    @app.get("/litigation/deadlines/<did>")
    def get_one_deadline(did):
        auth(READ_SET)
        return ok_object(serialize("deadline", get_deadline(did)))

    @app.post("/litigation/deadlines/<did>/mark-met")
    def mark_met_deadline(did):
        auth(LC)
        deadline = get_deadline(did)
        body = get_body()
        if deadline["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Only a SCHEDULED deadline may be marked met.")
        # (14) mark-met only while the clock is at or before due_at
        if store.clock > deadline["due_at"]:
            raise_err(ERR_DEADLINE_TIMING, "The deadline has already passed; record a miss instead.")
        reject_extra_fields(body, ())
        deadline["status"] = "MET"
        deadline["completed_at"] = store.clock
        touch(deadline)
        return ok_object(serialize("deadline", deadline))

    @app.post("/litigation/deadlines/<did>/mark-missed")
    def mark_missed_deadline(did):
        auth(LC)
        deadline = get_deadline(did)
        body = get_body()
        if deadline["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Only a SCHEDULED deadline may be marked missed.")
        reject_extra_fields(body, ())
        deadline["status"] = "MISSED"
        touch(deadline)
        if deadline.get("is_jurisdictional"):
            matter = store.matters.get(deadline["matter_id"])
            if matter is not None:
                calc.recompute_posture_bump(matter)
        return ok_object(serialize("deadline", deadline))

    @app.post("/litigation/deadlines/<did>/vacate")
    def vacate_deadline(did):
        auth(("LitigationCounsel", "DeputyGeneralCounsel"))
        deadline = get_deadline(did)
        body = get_body()
        if deadline["status"] not in ("SCHEDULED", "MISSED"):
            raise_err(ERR_INVALID_STATE, "Only a SCHEDULED or MISSED deadline may be vacated.")
        # (23) jurisdictional vacate requires a non-empty court_order_reference
        if deadline.get("is_jurisdictional"):
            check_shape_23(body, {"court_order_reference": {"type": "str", "required": True}})
        else:
            check_shape_23(body, {"court_order_reference": {"type": "str"}})
        was_jurisdictional_miss = deadline.get("is_jurisdictional") and deadline["status"] == "MISSED"
        deadline["status"] = "VACATED"
        touch(deadline)
        if was_jurisdictional_miss:
            matter = store.matters.get(deadline["matter_id"])
            if matter is not None:
                calc.recompute_posture_bump(matter)
        return ok_object(serialize("deadline", deadline))
