"""ServiceVisit endpoints: schedule, pickup, deliver, reconcile (PRD §3.8-3.10)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, touch, public_view, sort_by_created
from services.ledger import (
    recompute_account, create_charge,
    provisional_service_charge, finalized_service_charge,
)
from services import validate

bp = Blueprint("service_visits", __name__)


def _ensure_stop(stop_id):
    s = db.route_stops.get(stop_id)
    if s is None:
        raise errors.not_found("Route stop not found.")
    return s


def _ensure_visit(visit_id):
    v = db.service_visits.get(visit_id)
    if v is None:
        raise errors.not_found("Service visit not found.")
    return v


@bp.route("/route-stops/<stop_id>/service-visits", methods=["POST"])
def schedule_visit(stop_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver"})
    stop = _ensure_stop(stop_id)
    body = validate.get_body()

    week_index = validate.require_int(body, "week_index", minimum=0)

    # week_index unique per route_stop_id.
    for v in db.service_visits.values():
        if v["route_stop_id"] == stop_id and v["week_index"] == week_index:
            raise errors.duplicate_key("week_index already used for this stop.")

    visit = make_record("service_visits", {
        "route_stop_id": stop_id,
        "account_id": stop["account_id"],
        "week_index": week_index,
        "status": "SCHEDULED",
        "expected_soil_count": 0,
        "actual_soil_count": 0,
        "provisional_charge_cents": 0,
        "finalized_charge_cents": 0,
    })
    return object_response(public_view(visit), 201)


@bp.route("/service-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver", "AccountManager"})
    v = _ensure_visit(visit_id)
    return object_response(public_view(v), 200)


@bp.route("/route-stops/<stop_id>/service-visits", methods=["GET"])
def list_stop_visits(stop_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver", "AccountManager"})
    _ensure_stop(stop_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = [v for v in db.service_visits.values() if v["route_stop_id"] == stop_id]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(v) for v in page], limit, offset, total)


@bp.route("/service-visits", methods=["GET"])
def list_visits():
    role = get_role()
    require_role(role, {"ProgramAdmin", "RouteDriver", "AccountManager"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    rows = list(db.service_visits.values())
    if account_id is not None:
        rows = [v for v in rows if v["account_id"] == account_id]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(v) for v in page], limit, offset, total)


@bp.route("/service-visits/<visit_id>/pickup", methods=["POST"])
def pickup(visit_id):
    role = get_role()
    require_role(role, {"RouteDriver"})
    visit = _ensure_visit(visit_id)
    body = validate.get_body()

    # State legality (priority 5) before body checks tied to this transition.
    if visit["status"] != "SCHEDULED":
        raise errors.invalid_state("pickup requires a SCHEDULED visit.")

    # actual_soil_count required, must be present.
    if "actual_soil_count" not in body or body["actual_soil_count"] is None:
        raise errors.invalid_request("actual_soil_count is required.")
    actual = body["actual_soil_count"]
    if isinstance(actual, bool) or not isinstance(actual, int):
        raise errors.invalid_request("actual_soil_count must be an integer.")
    # Negative -> dedicated error.
    if actual < 0:
        raise errors.soil_count_negative()

    acct_id = visit["account_id"]

    # Snapshot expected_soil_count = ASSIGNED garments AT_CUSTOMER for the account.
    out_garments = [
        g for g in db.garments.values()
        if g["account_id"] == acct_id
        and g["lifecycle_status"] == "ASSIGNED"
        and g["wash_location"] == "AT_CUSTOMER"
    ]
    expected = len(out_garments)

    # actual above expected -> ERR_INVALID_REQUEST (can't scan back more than out).
    if actual > expected:
        raise errors.invalid_request("actual_soil_count exceeds expected_soil_count.")

    visit["expected_soil_count"] = expected
    visit["actual_soil_count"] = actual

    # Reset cycled_through_wash_this_visit for every ASSIGNED garment of account.
    for g in db.garments.values():
        if g["account_id"] == acct_id and g["lifecycle_status"] == "ASSIGNED":
            if g["cycled_through_wash_this_visit"]:
                g["cycled_through_wash_this_visit"] = False
                touch(g)
            else:
                g["cycled_through_wash_this_visit"] = False

    # Move min(actual, expected) garments AT_CUSTOMER -> IN_SOIL, oldest first
    # (assigned_at_iso asc, then created_at asc). Remaining stay AT_CUSTOMER and
    # each gets soil_strikes += 1.
    def _assigned_at(g):
        a = _assignment_for_garment(g["id"])
        return a["assigned_at_iso"] if a else g["created_at"]

    ordered = sorted(out_garments, key=lambda g: (_assigned_at(g), g["created_at"], g["_seq"]))
    n_soil = min(actual, expected)
    to_soil = ordered[:n_soil]
    stayed = ordered[n_soil:]

    for g in to_soil:
        g["wash_location"] = "IN_SOIL"
        touch(g)
    for g in stayed:
        g["soil_strikes"] += 1
        touch(g)

    visit["status"] = "PICKED_UP"
    touch(visit)
    return object_response(public_view(visit), 200)


def _assignment_for_garment(garment_id):
    """Most relevant assignment for ordering: prefer the ASSIGNED one."""
    candidates = [a for a in db.assignments.values() if a["garment_id"] == garment_id]
    for a in candidates:
        if a["status"] == "ASSIGNED":
            return a
    return candidates[0] if candidates else None


@bp.route("/service-visits/<visit_id>/deliver", methods=["POST"])
def deliver(visit_id):
    role = get_role()
    require_role(role, {"RouteDriver"})
    visit = _ensure_visit(visit_id)

    if visit["status"] != "PICKED_UP":
        raise errors.invalid_state("deliver requires a PICKED_UP visit.")

    acct_id = visit["account_id"]

    # No garment for the account may remain IN_SOIL or IN_WASH.
    for g in db.garments.values():
        if g["account_id"] == acct_id and g["wash_location"] in ("IN_SOIL", "IN_WASH"):
            raise errors.visit_garments_not_clean()

    # ASSIGNED garments AT_PLANT -> AT_CUSTOMER (clean delivery).
    for g in db.garments.values():
        if (
            g["account_id"] == acct_id
            and g["lifecycle_status"] == "ASSIGNED"
            and g["wash_location"] == "AT_PLANT"
        ):
            g["wash_location"] = "AT_CUSTOMER"
            touch(g)

    account = db.accounts[acct_id]
    rental, shortage = provisional_service_charge(visit, account)
    visit["provisional_charge_cents"] = rental + shortage

    # Create RENTAL charge always; SHORTAGE only when > 0.
    create_charge(visit_id, acct_id, "RENTAL", rental)
    if shortage > 0:
        create_charge(visit_id, acct_id, "SHORTAGE", shortage)

    recompute_account(account)

    visit["status"] = "DELIVERED"
    touch(visit)
    return object_response(public_view(visit), 200)


@bp.route("/service-visits/<visit_id>/reconcile", methods=["POST"])
def reconcile(visit_id):
    role = get_role()
    require_role(role, {"ProgramAdmin"})
    visit = _ensure_visit(visit_id)
    body = validate.get_body()

    # State legality (priority 5) precedes OCC (priority 13) and body
    # well-formedness (priority 14) per PRD §2.9.
    if visit["status"] != "DELIVERED":
        raise errors.invalid_state("reconcile requires a DELIVERED visit.")

    # expected_service_visit_version required (PRD §2.7).
    if "expected_service_visit_version" not in body or body["expected_service_visit_version"] is None:
        raise errors.invalid_request("expected_service_visit_version is required.")
    expected_version = body["expected_service_visit_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("expected_service_visit_version must be an integer.")

    # OCC check (priority 13).
    if expected_version != visit["version"]:
        raise errors.stale_visit_version()

    account = db.accounts[visit["account_id"]]
    rental, shortage = finalized_service_charge(visit, account)
    visit["finalized_charge_cents"] = rental + shortage

    # Delete provisional RENTAL + SHORTAGE rows for this visit, write finalized.
    to_delete = [
        cid for cid, sc in db.service_charges.items()
        if sc["service_visit_id"] == visit_id and sc["charge_type"] in ("RENTAL", "SHORTAGE")
    ]
    for cid in to_delete:
        del db.service_charges[cid]

    create_charge(visit_id, visit["account_id"], "RENTAL", rental)
    if shortage > 0:
        create_charge(visit_id, visit["account_id"], "SHORTAGE", shortage)

    recompute_account(account)

    visit["status"] = "RECONCILED"
    touch(visit)
    return object_response(public_view(visit), 200)
