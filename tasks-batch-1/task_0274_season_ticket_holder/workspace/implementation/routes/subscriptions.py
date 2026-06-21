"""Subscription lifecycle: create, activate, relocate cycle, renewal, cancel."""
from flask import Blueprint, request

import db
import services
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    paginate,
    require_int,
    require_str,
    seat_assignment_view,
    subscription_view,
)
from middleware import get_auth, require_role
from response import success, success_list
import calculations as calc

bp = Blueprint("subscriptions", __name__)

ALL_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}

SUB_TERMINAL = {"CANCELLED"}


def _ownership_check(sub, user_id, role):
    """AccountHolder may only act on a subscription they own."""
    if role == "AccountHolder" and sub["account_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Holder does not own this subscription")


def _state_error(current, terminal_set):
    """Raise the right error for an illegal transition from `current`."""
    if current in terminal_set:
        raise err(
            "ERR_VALIDATION_FROM_TERMINAL",
            "Resource is in terminal state %s" % current,
        )
    raise err("ERR_INVALID_STATE", "Illegal transition from state %s" % current)


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.route("/subscriptions", methods=["POST"])
def create_subscription():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    account_id = require_str(body, "account_id")
    season_plan_id = require_str(body, "season_plan_id")
    with db.lock:
        if account_id not in db.accounts:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "account_id not found")
        if season_plan_id not in db.season_plans:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "season_plan_id not found")
        row = db.new_common()
        row.update(
            {
                "account_id": account_id,
                "season_plan_id": season_plan_id,
                "status": "PENDING",
                "locked_price_cents": 0,
                "seat_count": 0,
                "renewal_cycle": 0,
            }
        )
        db.subscriptions[row["id"]] = row
        return success(subscription_view(row), 201)


@bp.route("/subscriptions/<rid>", methods=["GET"])
def get_subscription(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.subscriptions, rid)
        return success(subscription_view(row))


@bp.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent", "FinanceClerk"})
    account_id = request.args.get("account_id")
    season_plan_id = request.args.get("season_plan_id")
    status = request.args.get("status")
    with db.lock:
        rows = [
            s
            for s in db.subscriptions.values()
            if (account_id is None or s["account_id"] == account_id)
            and (season_plan_id is None or s["season_plan_id"] == season_plan_id)
            and (status is None or s["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([subscription_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------
@bp.route("/subscriptions/<rid>/activate", methods=["POST"])
def activate(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        if sub["status"] != "PENDING":
            _state_error(sub["status"], SUB_TERMINAL)
        account = db.accounts[sub["account_id"]]
        if account["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Holder account is not ACTIVE")
        if not services.assigned_assignments(sub["id"]):
            raise err("ERR_INVALID_STATE", "Subscription has no assigned seats")
        services.reprice_subscription(sub)
        services.accrue_points(sub)
        services.set_seat_count(sub)
        sub["status"] = "ACTIVE"
        db.touch(sub)
        return success(subscription_view(sub))


# ---------------------------------------------------------------------------
# Relocate begin / confirm / abort
# ---------------------------------------------------------------------------
@bp.route("/subscriptions/<rid>/relocate", methods=["POST"])
def relocate_begin(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    expected = require_int(body, "expected_subscription_version")
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        if sub["status"] != "ACTIVE":
            _state_error(sub["status"], SUB_TERMINAL)
        if expected != sub["version"]:
            raise err("ERR_STALE_SUBSCRIPTION_VERSION", "Stale subscription version")
        sub["status"] = "RELOCATING"
        db.touch(sub)
        return success(subscription_view(sub))


@bp.route("/subscriptions/<rid>/relocate/confirm", methods=["POST"])
def relocate_confirm(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    target_ids = body.get("target_seat_ids")
    if not isinstance(target_ids, list) or not target_ids or not all(
        isinstance(t, str) for t in target_ids
    ):
        raise err("ERR_INVALID_REQUEST", "target_seat_ids must be a non-empty list of ids")
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        # FK existence for each target seat.
        target_seats = []
        for sid in target_ids:
            seat = db.seats.get(sid)
            if seat is None:
                raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "target seat not found")
            target_seats.append(seat)
        # State.
        if sub["status"] != "RELOCATING":
            _state_error(sub["status"], SUB_TERMINAL)

        current = services.assigned_assignments(sub["id"])
        # Determine the released seats' section and window (reference).
        ref_seat = db.seats[current[0]["seat_id"]] if current else None

        # ERR_SECTION_MISMATCH: target must share section AND season window
        # with released seats.
        for seat in target_seats:
            if ref_seat is not None:
                if seat["section_id"] != ref_seat["section_id"]:
                    raise err("ERR_SECTION_MISMATCH", "target seat in different section")
                if (
                    seat["season_start_date"] != ref_seat["season_start_date"]
                    or seat["season_end_date"] != ref_seat["season_end_date"]
                ):
                    raise err("ERR_SECTION_MISMATCH", "target seat in different season window")

        # Every target seat must be AVAILABLE.
        for seat in target_seats:
            if seat["status"] != "AVAILABLE":
                raise err("ERR_INVALID_STATE", "target seat is not AVAILABLE")

        # Window-overlap guard (closed interval) against other ASSIGNED
        # assignments of OTHER subscriptions on the same seat.
        for seat in target_seats:
            _check_seat_window_conflict(seat, exclude_subscription_id=sub["id"])

        # --- Commit: release old, assign new ---
        for sa in current:
            sa["status"] = "REASSIGNED"
            db.touch(sa)
            old_seat = db.seats[sa["seat_id"]]
            old_seat["status"] = "AVAILABLE"
            db.touch(old_seat)
            db.touch(db.sections[old_seat["section_id"]])

        for seat in target_seats:
            sa = db.new_common()
            sa.update(
                {
                    "subscription_id": sub["id"],
                    "seat_id": seat["id"],
                    "assigned_price_cents": 0,
                    "status": "ASSIGNED",
                }
            )
            db.seat_assignments[sa["id"]] = sa
            seat["status"] = "SOLD"
            db.touch(seat)
            db.touch(db.sections[seat["section_id"]])

        services.reprice_subscription(sub)
        services.set_seat_count(sub)
        sub["status"] = "ACTIVE"
        db.touch(sub)
        return success(subscription_view(sub))


@bp.route("/subscriptions/<rid>/relocate/abort", methods=["POST"])
def relocate_abort(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        if sub["status"] != "RELOCATING":
            _state_error(sub["status"], SUB_TERMINAL)
        sub["status"] = "ACTIVE"
        db.touch(sub)
        return success(subscription_view(sub))


# ---------------------------------------------------------------------------
# Renewal offer / accept
# ---------------------------------------------------------------------------
@bp.route("/subscriptions/<rid>/renewal/offer", methods=["POST"])
def renewal_offer(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        if sub["status"] != "ACTIVE":
            _state_error(sub["status"], SUB_TERMINAL)
        sub["status"] = "RENEWAL_OFFERED"
        db.touch(sub)
        return success(subscription_view(sub))


@bp.route("/subscriptions/<rid>/renewal/accept", methods=["POST"])
def renewal_accept(rid):
    user_id, role = get_auth()
    require_role(role, {"AccountHolder"})
    body = get_json_body()
    expected = require_int(body, "expected_subscription_version")
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        # Priority order (PRD §2.8): state (6) before ownership (8) before OCC (13).
        if sub["status"] != "RENEWAL_OFFERED":
            _state_error(sub["status"], SUB_TERMINAL)
        _ownership_check(sub, user_id, role)
        account = db.accounts[sub["account_id"]]
        if account["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Holder account is not ACTIVE")
        if expected != sub["version"]:
            raise err("ERR_STALE_SUBSCRIPTION_VERSION", "Stale subscription version")
        services.reprice_subscription(sub)
        services.accrue_points(sub)
        account["consecutive_seasons"] += 1
        db.touch(account)
        sub["renewal_cycle"] += 1
        sub["status"] = "ACTIVE"
        db.touch(sub)
        return success(subscription_view(sub))


# ---------------------------------------------------------------------------
# Cancel (cascade)
# ---------------------------------------------------------------------------
@bp.route("/subscriptions/<rid>/cancel", methods=["POST"])
def cancel(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    with db.lock:
        sub = get_or_404(db.subscriptions, rid)
        if sub["status"] not in ("ACTIVE", "SUSPENDED"):
            _state_error(sub["status"], SUB_TERMINAL)

        # Release ASSIGNED seat assignments.
        for sa in services.assigned_assignments(sub["id"]):
            sa["status"] = "RELEASED"
            db.touch(sa)
            seat = db.seats[sa["seat_id"]]
            seat["status"] = "AVAILABLE"
            db.touch(seat)
            db.touch(db.sections[seat["section_id"]])
        sub["seat_count"] = 0

        # Claw back priority points granted for this subscription.
        granted = db.points_granted.get(sub["id"], 0)
        if granted:
            account = db.accounts[sub["account_id"]]
            account["priority_points"] -= granted
            db.touch(account)
            db.points_granted[sub["id"]] = 0

        # Capture the active plan BEFORE cancelling it (for refund recording).
        plan = services.active_payment_plan(sub["id"])
        amount_paid = plan["amount_paid_cents"] if plan else 0

        # Cancel active payment plan -> void scheduled installments.
        for cancelled_plan in services.cancel_payment_plans_for_subscription(sub["id"]):
            pass

        # Release ACTIVE parking add-ons.
        for addon in db.parking_addons.values():
            if addon["subscription_id"] == sub["id"] and addon["status"] == "ACTIVE":
                addon["status"] = "RELEASED"
                db.touch(addon)
                db.touch(db.parking_zones[addon["parking_zone_id"]])

        # Compute and record cancellation refund on the cancelled plan.
        refund = calc.cancellation_refund(amount_paid, sub["locked_price_cents"])
        if plan is not None:
            plan["refund_cents"] = refund
            db.touch(plan)

        sub["status"] = "CANCELLED"
        db.touch(sub)
        return success(subscription_view(sub))


# ---------------------------------------------------------------------------
# Reverse lookups under subscription
# ---------------------------------------------------------------------------
@bp.route("/subscriptions/<rid>/seat-assignments", methods=["GET"])
def list_subscription_seat_assignments(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    with db.lock:
        get_or_404(db.subscriptions, rid)
        rows = [
            sa
            for sa in db.seat_assignments.values()
            if sa["subscription_id"] == rid and (status is None or sa["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([seat_assignment_view(r) for r in page], limit, offset, total)


@bp.route("/subscriptions/<rid>/parking-addons", methods=["GET"])
def list_subscription_parking_addons(rid):
    from helpers import parking_addon_view

    _, role = get_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    with db.lock:
        get_or_404(db.subscriptions, rid)
        rows = [
            p
            for p in db.parking_addons.values()
            if p["subscription_id"] == rid and (status is None or p["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([parking_addon_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Shared: seat-window conflict check (closed interval, adjacency counts)
# ---------------------------------------------------------------------------
def _check_seat_window_conflict(seat, exclude_subscription_id=None):
    """A seat may not be assigned if the same physical seat already backs another
    ASSIGNED SeatAssignment whose subscription's season window overlaps the new
    one. The same physical seat is resold season after season as distinct `Seat`
    rows sharing a physical location (section + row_label + seat_number) but each
    carrying its own season window, so the guard keys on physical location rather
    than on the `Seat` row id (PRD §3.1/§3.4)."""
    new_start = seat["season_start_date"]
    new_end = seat["season_end_date"]
    for sa in db.seat_assignments.values():
        if sa["status"] != "ASSIGNED":
            continue
        if exclude_subscription_id and sa["subscription_id"] == exclude_subscription_id:
            continue
        other_seat = db.seats.get(sa["seat_id"])
        if other_seat is None:
            continue
        # Same physical seat = same section + row_label + seat_number.
        if (
            other_seat["section_id"] != seat["section_id"]
            or other_seat["row_label"] != seat["row_label"]
            or other_seat["seat_number"] != seat["seat_number"]
        ):
            continue
        if services.windows_overlap(
            new_start,
            new_end,
            other_seat["season_start_date"],
            other_seat["season_end_date"],
        ):
            raise err("ERR_SEAT_WINDOW_CONFLICT", "Seat window conflict")
