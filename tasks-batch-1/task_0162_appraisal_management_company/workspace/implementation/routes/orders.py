"""Order endpoints: placement, assignment (rotation), complete, cancel, nested GETs."""
from flask import Blueprint

import clock
import db
import errors
import middleware
import response
from services import calculations as calc
from services import domain, firewall, pagination, serialize, validate

bp = Blueprint("orders", __name__)

PRODUCT_TYPES = {"URAR_1004", "CONDO_1073", "EXTERIOR_2055"}


# ---------------------------------------------------------------------------
# POST /amc/orders  — place an order
# ---------------------------------------------------------------------------
@bp.route("/amc/orders", methods=["POST"])
def place_order():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"LenderUser", "AMCCoordinator", "PlatformAdmin"})
    data = validate.body()

    # Existence (priority 4) of referenced lender/property. A malformed/absent
    # reference cannot be resolved, so it surfaces as a field-shape error.
    lender_id = data.get("lender_id")
    property_id = data.get("property_id")
    if lender_id is None or property_id is None:
        raise errors.invalid_request("lender_id and property_id are required.")
    if not isinstance(lender_id, str) or not isinstance(property_id, str):
        raise errors.invalid_request("lender_id and property_id must be strings.")

    lender = db.lenders.get(lender_id)
    if lender is None:
        raise errors.not_found("Lender not found.")
    prop = db.properties.get(property_id)
    if prop is None:
        raise errors.not_found("Property not found.")

    # Field-shape (priority 14) — but budget (priority 13) is checked before
    # field-shape per ordering. We still need parsed/validated numeric fields to
    # do the budget math, so validate the fields needed for the budget check.
    order_fee = data.get("order_fee_cents")
    if order_fee is None:
        raise errors.invalid_request("order_fee_cents is required.")
    if isinstance(order_fee, bool) or not isinstance(order_fee, int):
        raise errors.invalid_request("order_fee_cents must be an integer.")
    if order_fee <= 0:
        raise errors.invalid_request("order_fee_cents must be > 0.")

    product_type = data.get("product_type")
    if product_type is None:
        raise errors.invalid_request("product_type is required.")
    if product_type not in PRODUCT_TYPES:
        raise errors.invalid_request("product_type out of range.")

    rush = validate.opt_bool(data, "rush", False)

    # Budget check (priority 13) BEFORE field-shape-only concerns are done; all
    # fields needed are validated above.
    domain.recompute_committed_fee(lender)
    if lender["committed_fee_cents"] + order_fee > lender["monthly_fee_budget_cents"]:
        raise errors.err(errors.ERR_LENDER_BUDGET_EXCEEDED,
                         "Lender monthly fee budget would be exceeded.")

    now = clock.now()
    order = {
        "lender_id": lender_id,
        "property_id": property_id,
        "order_fee_cents": order_fee,
        "product_type": product_type,
        "rush": rush,
        "sla_hours": calc.projected_sla_hours(product_type, rush),
        "placed_at": clock.format_iso(now),
        "_placed_dt": now,
        "status": "PLACED",
        "appraised_value_cents": None,
    }
    db.stamp_create(order)
    db.orders[order["id"]] = order

    # Create the FeeSplit (PROVISIONAL) for the order.
    fee_split = {
        "order_id": order["id"],
        "variant": "PROVISIONAL",
        "appraiser_fee_cents": 0,
        "amc_fee_cents": order_fee,
        "revision_penalty_cents": 0,
    }
    db.stamp_create(fee_split)
    db.fee_splits[fee_split["id"]] = fee_split

    # Increment lender committed fee.
    domain.recompute_committed_fee(lender)

    return response.ok_object(serialize.public(order), 201)


# ---------------------------------------------------------------------------
# GET /amc/orders  — list
# ---------------------------------------------------------------------------
@bp.route("/amc/orders", methods=["GET"])
def list_orders():
    from flask import request
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    limit, offset = pagination.parse()

    items = list(db.orders.values())
    lender_id = request.args.get("lender_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    if lender_id:
        items = [o for o in items if o["lender_id"] == lender_id]
    if property_id:
        items = [o for o in items if o["property_id"] == property_id]
    if status:
        items = [o for o in items if o["status"] == status]

    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# GET /amc/orders/{id}
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    return response.ok_object(serialize.public(order), 200)


# ---------------------------------------------------------------------------
# POST /amc/orders/{id}/assignments  — assign/reassign via rotation selector
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/assignments", methods=["POST"])
def create_assignment(oid):
    _, role = middleware.authenticate()

    # Priority 2: AIR firewall (LenderUser) BEFORE generic authorization.
    if role == "LenderUser":
        firewall.block_and_log(oid, role, "SELECT_APPRAISER")

    # Priority 3: generic authorization.
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})

    # Priority 4: existence.
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")

    data = validate.body()

    # Determine the order's current latest assignment (by creation time).
    own = [a for a in db.assignments.values() if a.get("order_id") == oid]
    latest = max(own, key=lambda a: a["_created_dt"]) if own else None

    # Priority 5: eligible-appraiser availability — but state legality (7) and
    # OCC (8) are higher priority numbers than 5, so eligibility comes first.
    # PRD §2.10 order: existence(4) -> eligible(5) -> ... -> state(7) -> OCC(8).
    lender = db.lenders.get(order["lender_id"])
    prop = db.properties.get(order["property_id"])

    # State legality (priority 7): transition must be defined.
    #   PLACED -> ASSIGNED (initial); ASSIGNED -> ASSIGNED (reassign, latest in
    #   {DECLINED, CANCELLED}). Otherwise ERR_INVALID_STATE.
    # OCC (priority 8): expected_order_version matches.
    # Per §2.10 numbering, eligibility(5) precedes state(7) precedes OCC(8).

    # Eligibility (priority 5): selector candidate set non-empty.
    selected = domain.select_appraiser(order, prop, lender)

    # State legality (priority 7).
    if order["status"] == "PLACED":
        is_reassign = False
    elif order["status"] == "ASSIGNED":
        if latest is None or latest["status"] not in ("DECLINED", "CANCELLED"):
            raise errors.invalid_state(
                "Order is ASSIGNED but its latest assignment is not declined/cancelled.")
        is_reassign = True
    else:
        raise errors.invalid_state("Order is not in a state that accepts assignment.")

    # OCC (priority 8).
    expected = data.get("expected_order_version")
    if expected is None:
        raise errors.invalid_request("expected_order_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_order_version must be an integer.")
    if expected != order["version"]:
        raise errors.stale_version("expected_order_version does not match current order version.")

    # --- Create the assignment (OFFERED). ---
    assignment = {
        "order_id": oid,
        "appraiser_id": selected["id"],
        "sla_hours": order["sla_hours"],
        "accepted_at": None,
        "inspection_start": None,
        "inspection_end": None,
        "revision_round": 0,
        "actual_turnaround_hours": None,
        "status": "OFFERED",
        "supersedes_assignment_id": latest["id"] if is_reassign else None,
    }
    db.stamp_create(assignment)
    db.assignments[assignment["id"]] = assignment

    # Order transition + version bump.
    if not is_reassign:
        order["status"] = "ASSIGNED"
    db.touch(order)

    # Recompute the PROVISIONAL fee split now that an appraiser is known, so the
    # provisional gross appraiser share is populated (PRD §3.6). The split's
    # variant stays PROVISIONAL until completion.
    fee_split = domain.fee_split_for_order(oid)
    if fee_split is not None and fee_split["variant"] == "PROVISIONAL":
        domain.recompute_fee_split(order, fee_split, "PROVISIONAL")
        db.touch(fee_split)

    return response.ok_object(serialize.public(assignment), 201)


# ---------------------------------------------------------------------------
# GET /amc/orders/{id}/assignments
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/assignments", methods=["GET"])
def list_order_assignments(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    limit, offset = pagination.parse()
    items = [a for a in db.assignments.values() if a.get("order_id") == oid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# GET /amc/orders/{id}/fee-split  (array of length 1)
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/fee-split", methods=["GET"])
def get_order_fee_split(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    limit, offset = pagination.parse()
    items = [f for f in db.fee_splits.values() if f.get("order_id") == oid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(f) for f in page], limit, offset, total)


# ---------------------------------------------------------------------------
# GET /amc/orders/{id}/reconsiderations
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/reconsiderations", methods=["GET"])
def list_order_reconsiderations(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    limit, offset = pagination.parse()
    items = [r for r in db.reconsiderations.values() if r.get("order_id") == oid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# GET /amc/orders/{id}/firewall-events
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/firewall-events", methods=["GET"])
def list_order_firewall_events(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    limit, offset = pagination.parse()
    items = [e for e in db.firewall_events.values() if e.get("order_id") == oid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /amc/orders/{id}/complete
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    data = validate.body()

    # State legality (priority 7).
    if order["status"] != "DELIVERED":
        # PRD §3.8: completion permitted only from DELIVERED. The "no open ROV"
        # precondition is also part of completion legality; the scaffold models
        # it as a state precondition -> ERR_INVALID_STATE.
        raise errors.invalid_state("Order is not DELIVERED.")
    open_rov = any(
        r.get("order_id") == oid and r["resolution"] in ("REQUESTED", "UNDER_REVIEW")
        for r in db.reconsiderations.values())
    if open_rov:
        raise errors.invalid_state("Order has an open reconsideration of value.")

    # OCC (priority 8).
    expected = data.get("expected_order_version")
    if expected is None:
        raise errors.invalid_request("expected_order_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_order_version must be an integer.")
    if expected != order["version"]:
        raise errors.stale_version("expected_order_version does not match current order version.")

    # Find the accepted assignment.
    appraiser, assignment = domain._scoring_assignment(order)

    order["status"] = "COMPLETED"
    db.touch(order)

    if assignment is not None and assignment["status"] == "ACCEPTED":
        accepted_dt = clock.parse_iso(assignment.get("accepted_at"))
        completed_dt = clock.now()
        if accepted_dt is not None:
            assignment["actual_turnaround_hours"] = calc.actual_turnaround_hours(
                accepted_dt, completed_dt)
        assignment["status"] = "COMPLETED"
        db.touch(assignment)

    if appraiser is not None:
        domain.recompute_appraiser(appraiser)
        db.touch(appraiser)

    # Finalize fee split (FINAL).
    fee_split = domain.fee_split_for_order(oid)
    if fee_split is not None:
        domain.recompute_fee_split(order, fee_split, "FINAL")
        db.touch(fee_split)

    return response.ok_object(serialize.public(order), 200)


# ---------------------------------------------------------------------------
# POST /amc/orders/{id}/cancel
# ---------------------------------------------------------------------------
@bp.route("/amc/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin"})
    order = db.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found.")
    data = validate.body()

    # State legality (priority 7): cancellable from PLACED/ASSIGNED/IN_PROGRESS/IN_QC.
    if order["status"] not in ("PLACED", "ASSIGNED", "IN_PROGRESS", "IN_QC"):
        raise errors.invalid_state("Order is not in a cancellable state.")

    # OCC (priority 8).
    expected = data.get("expected_order_version")
    if expected is None:
        raise errors.invalid_request("expected_order_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_order_version must be an integer.")
    if expected != order["version"]:
        raise errors.stale_version("expected_order_version does not match current order version.")

    order["status"] = "CANCELLED"
    db.touch(order)

    # Cascade: non-terminal assignment -> CANCELLED.
    own = [a for a in db.assignments.values() if a.get("order_id") == oid]
    affected_appraisers = set()
    for a in own:
        if a["status"] in ("OFFERED", "ACCEPTED", "REVISION"):
            was_active = a["status"] in ("ACCEPTED", "REVISION")
            a["status"] = "CANCELLED"
            db.touch(a)
            if was_active and a.get("appraiser_id"):
                affected_appraisers.add(a["appraiser_id"])

    # Cascade: submitted (non-terminal) report -> REJECTED.
    for a in own:
        for rpt in db.reports.values():
            if rpt.get("assignment_id") == a["id"] and rpt["status"] not in ("ACCEPTED", "REJECTED"):
                rpt["status"] = "REJECTED"
                db.touch(rpt)

    # Decrement appraiser active count (recompute from store; conserves count).
    for aid in affected_appraisers:
        ap = db.appraisers.get(aid)
        if ap is not None:
            domain.recompute_appraiser(ap)
            db.touch(ap)

    # FeeSplit zeroed.
    fee_split = domain.fee_split_for_order(oid)
    if fee_split is not None:
        fee_split["appraiser_fee_cents"] = 0
        fee_split["amc_fee_cents"] = 0
        db.touch(fee_split)

    # Lender committed fee recomputed (this order drops out).
    lender = db.lenders.get(order["lender_id"])
    if lender is not None:
        domain.recompute_committed_fee(lender)

    return response.ok_object(serialize.public(order), 200)
