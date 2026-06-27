"""Booking lifecycle routes: create/list/get, offer, claim, depart, start,
complete, cancel, reschedule (propose/accept/decline), settlement, cancellation,
chat messages, rebook."""
from flask import Blueprint, request

import errors
from errors import err
from db import db, parse_iso, iso_millis, clock_now
from middleware import get_caller, require_roles
from response import object_response, array_response
from services import core, reqs
from services import booking_svc as bsvc

bp = Blueprint("bookings", __name__)


# =============================================================================
# Ownership helpers (PRD §2.1, §2.9 priority 4)
# =============================================================================
def _assert_client_owner(caller, booking):
    if caller.role == "Client" and caller.user_id != booking["client_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client does not own this booking")


def _assert_assigned_tasker(caller, booking):
    if caller.role == "Tasker" and caller.user_id != booking.get("tasker_id"):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Tasker is not assigned to this booking")


# =============================================================================
# Create / list / get
# =============================================================================
@bp.route("/bookings", methods=["POST"])
def create_booking():
    caller = get_caller()
    require_roles(caller, {"Client", "Dispatcher"})
    data = reqs.body()
    client_id = reqs.require_str(data, "client_id")
    category_id = reqs.require_str(data, "category_id")
    # existence left-to-right: client then category
    core.get_client_or_404(client_id)
    category = core.get_category_or_404(category_id)
    if caller.role == "Client" and caller.user_id != client_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only create own booking")
    if category["status"] == "RETIRED":
        raise err(errors.ERR_CATEGORY_RETIRED, "Category is retired")

    dispatch_mode = reqs.require_enum(data, "dispatch_mode", {"SAME_DAY", "SCHEDULED"})
    start_raw = reqs.require(data, "scheduled_start")
    try:
        start_dt = parse_iso(start_raw)
    except (ValueError, TypeError):
        reqs.invalid("scheduled_start must be an ISO 8601 instant")
    tip_cents = reqs.opt_int(data, "tip_cents", default=0, minimum=0)

    estimated_hours = None
    if category["pricing_model"] == "HOURLY":
        estimated_hours = reqs.require_number(data, "estimated_hours", minimum=0.25)
    # FIXED: estimated_hours ignored

    rec = bsvc.build_booking(
        client_id=client_id, category_id=category_id, dispatch_mode=dispatch_mode,
        scheduled_start_dt=start_dt, estimated_hours=estimated_hours, tip_cents=tip_cents,
    )
    db.bookings[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    core.lazy_expire_all()
    limit, offset = core.parse_pagination(request.args)
    items = list(db.bookings.values())
    for key in ("client_id", "tasker_id", "category_id", "series_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(b) for b in window], pagination=meta)


@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    return object_response(core.serialize(b))


# =============================================================================
# Offer (DRAFT -> OFFERED)
# =============================================================================
@bp.route("/bookings/<bid>/offer", methods=["POST"])
def offer_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Dispatcher"})
    b = core.get_booking_or_404(bid)
    _assert_client_owner(caller, b)
    if b["status"] != "DRAFT":
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Only DRAFT bookings may be offered")
    category = db.task_categories.get(b["category_id"])
    if category is None:
        raise err(errors.ERR_CATEGORY_NOT_FOUND, "Category not found")
    if category["status"] != "ACTIVE":
        raise err(errors.ERR_CATEGORY_RETIRED, "Category is not ACTIVE")
    # temporal (priority 7): same-day date then not-in-past
    now = clock_now()
    if b["dispatch_mode"] == "SAME_DAY":
        if b["_scheduled_start_dt"].date() != now.date():
            raise err(errors.ERR_SAME_DAY_DATE_MISMATCH,
                      "SAME_DAY booking not on the current clock's UTC date")
    if not b["_scheduled_start_dt"] > now:
        raise err(errors.ERR_START_IN_PAST, "scheduled_start is in the past")
    bsvc.apply_offer(b, category)
    b["status"] = "OFFERED"
    core.touch(b)
    return object_response(core.serialize(b))


# =============================================================================
# Claim (OFFERED -> CLAIMED), Dispatcher only, OCC on Tasker.version
# =============================================================================
@bp.route("/bookings/<bid>/claim", methods=["POST"])
def claim_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher"})
    b = core.get_booking_or_404(bid)
    data = reqs.body()
    tasker_id = reqs.require_str(data, "tasker_id")
    # existence: tasker referenced in body
    tasker = core.get_tasker_or_404(tasker_id)
    core.recompute_tasker(tasker)  # ensure status/version are current
    expected_version = reqs.require_int(data, "expected_tasker_version")

    # priority 5: state
    if b["status"] != "OFFERED":
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Only OFFERED bookings may be claimed")
    # priority 6: safety/vetting (suspended first, then vetting)
    if tasker["status"] == "SUSPENDED":
        raise err(errors.ERR_TASKER_SUSPENDED, "Suspended tasker cannot be claimed")
    category = db.task_categories.get(b["category_id"])
    if category and category.get("requires_vetting"):
        if not _has_vetted_skill(tasker_id, b["category_id"]):
            raise err(errors.ERR_VETTING_REQUIRED, "Tasker lacks a VETTED skill for this category")
    # priority 8/9: scheduling geometry
    bsvc.run_schedule_checks(tasker, b, b["_scheduled_start_dt"], b["_scheduled_end_dt"])
    # priority 11: OCC
    if expected_version != tasker["version"]:
        raise err(errors.ERR_STALE_TASKER_VERSION, "Stale tasker version")

    # commit
    b["tasker_id"] = tasker_id
    b["status"] = "CLAIMED"
    core.touch(b)
    core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(b))


def _has_vetted_skill(tasker_id, category_id):
    for s in db.tasker_skills.values():
        if (s["tasker_id"] == tasker_id and s["category_id"] == category_id
                and s["vetting_status"] == "VETTED"):
            return True
    return False


# =============================================================================
# Depart / Start / Complete
# =============================================================================
@bp.route("/bookings/<bid>/depart", methods=["POST"])
def depart_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_assigned_tasker(caller, b)
    if b["status"] != "CLAIMED":
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Only CLAIMED bookings may depart")
    tasker = db.taskers.get(b["tasker_id"])
    core.recompute_tasker(tasker)
    if tasker["status"] == "SUSPENDED":
        raise err(errors.ERR_TASKER_SUSPENDED, "Suspended tasker cannot depart")
    if b["reschedule_pending"]:
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Reschedule proposal pending")
    b["status"] = "EN_ROUTE"
    core.touch(b)
    return object_response(core.serialize(b))


@bp.route("/bookings/<bid>/start", methods=["POST"])
def start_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_assigned_tasker(caller, b)
    if b["status"] != "EN_ROUTE":
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Only EN_ROUTE bookings may start")
    b["status"] = "IN_PROGRESS"
    core.touch(b)
    return object_response(core.serialize(b))


@bp.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_assigned_tasker(caller, b)
    if b["status"] != "IN_PROGRESS":
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Only IN_PROGRESS bookings may complete")
    data = reqs.body()
    category = db.task_categories.get(b["category_id"])
    if category["pricing_model"] == "HOURLY":
        actual_hours = reqs.require_number(data, "actual_hours", minimum=0)
        b["actual_hours"] = actual_hours
    if "tip_cents" in data and data["tip_cents"] is not None:
        b["tip_cents"] = reqs.require_int(data, "tip_cents", minimum=0)

    tasker = db.taskers.get(b["tasker_id"])
    amounts = core.final_settlement_amounts(b, category, tasker)
    settlement = {
        "booking_id": b["id"],
        "final_labor_cents": amounts["final_labor_cents"],
        "final_service_fee_cents": amounts["final_service_fee_cents"],
        "tip_cents": amounts["tip_cents"],
        "total_charged_cents": amounts["total_charged_cents"],
        "tasker_payout_cents": amounts["tasker_payout_cents"],
    }
    core.stamp_create(settlement)
    db.settlements[settlement["id"]] = settlement

    b["status"] = "COMPLETED"
    core.touch(b)
    core.recompute_tasker(tasker)  # counts only; no version bump declared for complete
    return object_response(core.serialize(b))


# =============================================================================
# Cancel (OFFERED/CLAIMED/EN_ROUTE -> CANCELLED)
# =============================================================================
@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    data = reqs.body()
    cancelled_by = reqs.require_enum(data, "cancelled_by", {"CLIENT", "TASKER"})
    # ownership (priority 4): align caller role with cancelled_by
    if cancelled_by == "CLIENT":
        if caller.role != "Client" or caller.user_id != b["client_id"]:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "CLIENT cancel requires booking's client")
    else:  # TASKER
        if caller.role != "Tasker" or caller.user_id != b.get("tasker_id"):
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "TASKER cancel requires assigned tasker")
    # state (priority 5): only OFFERED/CLAIMED/EN_ROUTE
    if b["status"] not in ("OFFERED", "CLAIMED", "EN_ROUTE"):
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Booking cannot be cancelled in this state")

    fee_info = core.cancellation_fee(b)
    cancellation = {
        "booking_id": b["id"],
        "cancelled_by": cancelled_by,
        "hours_before_start": fee_info["hours_before_start"],
        "fee_tier": fee_info["fee_tier"],
        "cancellation_fee_cents": fee_info["cancellation_fee_cents"],
    }
    core.stamp_create(cancellation)
    db.cancellations[cancellation["id"]] = cancellation

    assigned_tasker_id = b.get("tasker_id")
    b["status"] = "CANCELLED"
    b["cancelled_by"] = cancelled_by
    core.touch(b)

    if assigned_tasker_id:
        tasker = db.taskers.get(assigned_tasker_id)
        # active_booking_count recomputed; version bumped
        core.recompute_tasker(tasker, bump_version=True)
        # cascade: tasker LAST_MINUTE cancel -> MEDIUM TrustIncident
        if cancelled_by == "TASKER" and fee_info["fee_tier"] == "LAST_MINUTE":
            incident = {
                "tasker_id": assigned_tasker_id,
                "booking_id": b["id"],
                "severity": "MEDIUM",
                "status": "OPEN",
                "penalty_points": core.PENALTY["MEDIUM"],
            }
            core.stamp_create(incident)
            db.trust_incidents[incident["id"]] = incident
            core.recompute_tasker(tasker)  # trust_score -> trust_gate

    return object_response(core.serialize(b))


# =============================================================================
# Reschedule cycle (propose / accept / decline)
# =============================================================================
def _assert_resched_party(caller, booking):
    """Either the booking's client or the assigned tasker may drive a reschedule."""
    if caller.role == "Client":
        if caller.user_id != booking["client_id"]:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's client")
    elif caller.role == "Tasker":
        if caller.user_id != booking.get("tasker_id"):
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's assigned tasker")


@bp.route("/bookings/<bid>/reschedule/propose", methods=["POST"])
def reschedule_propose(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_resched_party(caller, b)
    if b["status"] not in ("CLAIMED", "EN_ROUTE"):
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Reschedule only on CLAIMED/EN_ROUTE")
    data = reqs.body()
    proposed_raw = reqs.require(data, "proposed_start")
    try:
        proposed_dt = parse_iso(proposed_raw)
    except (ValueError, TypeError):
        reqs.invalid("proposed_start must be an ISO 8601 instant")
    # reschedule-flow (priority 10): already-pending then cap
    if b["reschedule_pending"]:
        raise err(errors.ERR_RESCHEDULE_ALREADY_PENDING, "A proposal is already pending")
    if b["reschedule_count"] >= core.MAX_RESCHEDULES:
        raise err(errors.ERR_RESCHEDULE_LIMIT, "Reschedule cap reached")
    # temporal (priority 7): not in the past
    if not proposed_dt > clock_now():
        raise err(errors.ERR_START_IN_PAST, "proposed_start is in the past")
    b["reschedule_pending"] = True
    b["proposed_start"] = iso_millis(proposed_dt)
    b["_proposed_start_dt"] = proposed_dt
    core.touch(b)
    return object_response(core.serialize(b))


@bp.route("/bookings/<bid>/reschedule/accept", methods=["POST"])
def reschedule_accept(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_resched_party(caller, b)
    if b["status"] not in ("CLAIMED", "EN_ROUTE"):
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Reschedule only on CLAIMED/EN_ROUTE")
    data = reqs.body()
    expected_version = reqs.require_int(data, "expected_tasker_version")
    # priority 10: must have a pending proposal
    if not b["reschedule_pending"]:
        raise err(errors.ERR_NO_RESCHEDULE_PENDING, "No pending proposal")

    tasker = db.taskers.get(b["tasker_id"])
    core.recompute_tasker(tasker)
    category = db.task_categories.get(b["category_id"])
    new_start = b["_proposed_start_dt"]
    new_end = core.schedule_window_end(new_start, b, category)
    # re-run scheduling checks against the new window (priority 8/9)
    bsvc.run_schedule_checks(tasker, b, new_start, new_end)
    # priority 11: OCC
    if expected_version != tasker["version"]:
        raise err(errors.ERR_STALE_TASKER_VERSION, "Stale tasker version")

    b["scheduled_start"] = iso_millis(new_start)
    b["_scheduled_start_dt"] = new_start
    b["scheduled_end"] = iso_millis(new_end)
    b["_scheduled_end_dt"] = new_end
    b["reschedule_count"] += 1
    b["reschedule_pending"] = False
    b["proposed_start"] = None
    b["_proposed_start_dt"] = None
    core.touch(b)
    core.recompute_tasker(tasker, bump_version=True)
    return object_response(core.serialize(b))


@bp.route("/bookings/<bid>/reschedule/decline", methods=["POST"])
def reschedule_decline(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    _assert_resched_party(caller, b)
    if b["status"] not in ("CLAIMED", "EN_ROUTE"):
        raise err(errors.ERR_BOOKING_INVALID_STATE, "Reschedule only on CLAIMED/EN_ROUTE")
    if not b["reschedule_pending"]:
        raise err(errors.ERR_NO_RESCHEDULE_PENDING, "No pending proposal")
    b["reschedule_pending"] = False
    b["proposed_start"] = None
    b["_proposed_start_dt"] = None
    core.touch(b)
    return object_response(core.serialize(b))


# =============================================================================
# Settlement / Cancellation reverse-reachability (array of 0..1)
# =============================================================================
@bp.route("/bookings/<bid>/settlement", methods=["GET"])
def get_settlement(bid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    core.get_booking_or_404(bid)
    items = [s for s in db.settlements.values() if s["booking_id"] == bid]
    items.sort(key=lambda r: r["_seq"])
    return array_response([core.serialize(s) for s in items])


@bp.route("/bookings/<bid>/cancellation", methods=["GET"])
def get_cancellation(bid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    core.get_booking_or_404(bid)
    items = [c for c in db.cancellations.values() if c["booking_id"] == bid]
    items.sort(key=lambda r: r["_seq"])
    return array_response([core.serialize(c) for c in items])


# =============================================================================
# Chat messages
# =============================================================================
@bp.route("/bookings/<bid>/messages", methods=["POST"])
def post_message(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker"})
    b = core.get_booking_or_404(bid)
    # ownership: caller must be this booking's client or assigned tasker
    if caller.role == "Client":
        if caller.user_id != b["client_id"]:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's client")
        sender_role = "CLIENT"
    else:  # Tasker
        if caller.user_id != b.get("tasker_id"):
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's assigned tasker")
        sender_role = "TASKER"
    data = reqs.body()
    body_text = reqs.require(data, "body")
    if not isinstance(body_text, str) or not (1 <= len(body_text) <= 1000):
        reqs.invalid("body must be 1..1000 chars")
    # ChatMessage carries only id and created_at among system fields
    rec = {
        "booking_id": bid,
        "sender_role": sender_role,
        "body": body_text,
    }
    core.stamp_create(rec, with_version=False)
    db.chat_messages[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/bookings/<bid>/messages", methods=["GET"])
def list_messages(bid):
    caller = get_caller()
    require_roles(caller, {"Client", "Tasker", "Dispatcher", "TrustSafetyOfficer"})
    b = core.get_booking_or_404(bid)
    # entity-backed callers may only read their own booking's chat
    if caller.role == "Client" and caller.user_id != b["client_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's client")
    if caller.role == "Tasker" and caller.user_id != b.get("tasker_id"):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not this booking's assigned tasker")
    limit, offset = core.parse_pagination(request.args)
    items = [m for m in db.chat_messages.values() if m["booking_id"] == bid]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(m) for m in window], pagination=meta)


# =============================================================================
# Rebook (COMPLETED -> new DRAFT)
# =============================================================================
@bp.route("/bookings/<bid>/rebook", methods=["POST"])
def rebook(bid):
    caller = get_caller()
    require_roles(caller, {"Client"})
    src = core.get_booking_or_404(bid)
    if caller.user_id != src["client_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only rebook own booking")
    if src["status"] != "COMPLETED":
        raise err(errors.ERR_BOOKING_NOT_COMPLETED, "Source booking is not COMPLETED")
    data = reqs.body()
    dispatch_mode = reqs.require_enum(data, "dispatch_mode", {"SAME_DAY", "SCHEDULED"})
    start_raw = reqs.require(data, "scheduled_start")
    try:
        start_dt = parse_iso(start_raw)
    except (ValueError, TypeError):
        reqs.invalid("scheduled_start must be an ISO 8601 instant")
    tip_cents = reqs.opt_int(data, "tip_cents", default=0, minimum=0)
    category = db.task_categories.get(src["category_id"])
    estimated_hours = None
    if category and category["pricing_model"] == "HOURLY":
        estimated_hours = reqs.require_number(data, "estimated_hours", minimum=0.25)

    rec = bsvc.build_booking(
        client_id=src["client_id"], category_id=src["category_id"],
        dispatch_mode=dispatch_mode, scheduled_start_dt=start_dt,
        estimated_hours=estimated_hours, tip_cents=tip_cents,
    )
    db.bookings[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)
