"""Reservation endpoints (PRD §3.3–§3.7)."""
from flask import Blueprint, request

import db
from clock import current_dt, parse_iso
from errors import err, ERR_INVALID_WINDOW, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers, reservation_ops

bp = Blueprint("reservations", __name__)


def _parse_iso_field(body, field):
    """Validate an ISO timestamp string field; raise ERR_INVALID_REQUEST on bad form."""
    value = helpers.as_str(body, field)
    try:
        parse_iso(value)
    except (ValueError, TypeError):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid timestamp")
    return value


@bp.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    body = helpers.get_json_body()

    # Existence (priority 3) for referenced FKs, left to right: customer, catalog, party.
    customer_id = helpers.as_str(body, "customer_id")
    helpers.find("Customer", customer_id)
    catalog_id = helpers.as_str(body, "catalog_id")
    helpers.find("Catalog", catalog_id)
    party_order_id = body.get("party_order_id")
    if party_order_id is not None:
        helpers.find("PartyOrder", party_order_id)

    # Ownership: a Customer may only book their own reservation.
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_FORBIDDEN, "Customer may only book their own reservation")

    # Well-formedness (priority 4).
    requested_size_code = helpers.as_enum(body, "requested_size_code", helpers.SIZE_VALUES)
    event_date_iso = _parse_iso_field(body, "event_date_iso")
    pickup_window_start_iso = _parse_iso_field(body, "pickup_window_start_iso")
    return_window_end_iso = _parse_iso_field(body, "return_window_end_iso")
    damage_waiver_opted = helpers.as_bool(body, "damage_waiver_opted", default=False)

    # Window coherence (priority 5, ERR_INVALID_WINDOW).
    pickup_start = parse_iso(pickup_window_start_iso)
    return_end = parse_iso(return_window_end_iso)
    event_date = parse_iso(event_date_iso)
    if pickup_start > return_end:
        raise err(ERR_INVALID_WINDOW, "pickup_window_start must be on/before return_window_end")
    if pickup_start > event_date:
        raise err(ERR_INVALID_WINDOW, "pickup window must end on/before event_date")
    if event_date <= current_dt():
        raise err(ERR_INVALID_WINDOW, "event_date must be in the future")

    reservation = {
        "customer_id": customer_id,
        "catalog_id": catalog_id,
        "garment_unit_id": None,
        "party_order_id": party_order_id,
        "requested_size_code": requested_size_code,
        "event_date_iso": event_date_iso,
        "pickup_window_start_iso": pickup_window_start_iso,
        "return_window_end_iso": return_window_end_iso,
        "damage_waiver_opted": damage_waiver_opted,
        "status": "PENDING",
        "rental_days": None,
        "quoted_charge_cents": None,
    }
    db.stamp_create(reservation)
    db.reservations[reservation["id"]] = reservation
    return success(views.reservation_view(reservation), status=201)


@bp.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    reservation = helpers.find("Reservation", rid)
    if role == "Customer" and user_id != reservation["customer_id"]:
        raise err(ERR_FORBIDDEN, "Customer may only access their own reservation")
    return success(views.reservation_view(reservation))


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.reservations.values())
    # Customer sees only their own reservations.
    if role == "Customer":
        records = [r for r in records if r["customer_id"] == user_id]
    for field in ("customer_id", "catalog_id", "garment_unit_id", "party_order_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.reservation_view(r) for r in page], limit, offset, total)


@bp.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    reservation = helpers.find("Reservation", rid)
    body = helpers.get_json_body()
    reservation_ops.confirm(reservation, body)
    return success(views.reservation_view(reservation))


@bp.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    reservation = helpers.find("Reservation", rid)
    if role == "Customer" and user_id != reservation["customer_id"]:
        raise err(ERR_FORBIDDEN, "Customer may only cancel their own reservation")
    reservation_ops.cancel(reservation)
    return success(views.reservation_view(reservation))


@bp.route("/reservations/<rid>/pickup", methods=["POST"])
def pickup_reservation(rid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    reservation = helpers.find("Reservation", rid)
    reservation_ops.pickup(reservation)
    return success(views.reservation_view(reservation))


@bp.route("/reservations/<rid>/return", methods=["POST"])
def return_reservation(rid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    reservation = helpers.find("Reservation", rid)
    body = helpers.get_json_body()

    returned_at_iso = _parse_iso_field(body, "returned_at_iso")
    disposition = helpers.as_enum(body, "disposition", helpers.DISPOSITION_VALUES)

    settlement = reservation_ops.record_return(reservation, returned_at_iso, disposition)
    return success(views.settlement_view(settlement))
