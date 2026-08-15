"""SellerSession endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_SHOW_NOT_FOUND,
    ERR_SELLER_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_INVALID_SHOW_STATE,
    ERR_CROSS_TOUR_REFERENCE,
    ERR_SELLER_DOUBLE_BOOKED,
    ERR_SESSION_EXISTS,
    ERR_SESSION_NOT_OPEN,
    ERR_SESSION_NOT_COUNTED_OUT,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VARIANCE_OVERRIDE_REQUIRED,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_int,
    require_enum,
    require_bool,
    base_fields,
    touch,
    paginate,
)
from response import success_object, success_list
from services.core import calendar_date_of, session_variance, sessions_of_show
from services.serializers import session_view

bp = Blueprint("sessions", __name__)


def get_session_or_404(session_id):
    s = DB.sessions.get(session_id)
    if s is None:
        raise err(ERR_SESSION_NOT_FOUND, 404, "No SellerSession with the given id")
    return s


@bp.post("/merch/seller-sessions")
def create_session():
    require_role("TourManager")
    body = get_json_body()
    show_id = body.get("show_id")
    seller_id = body.get("seller_id")

    if show_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: show_id")
    if seller_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: seller_id")

    show = DB.shows.get(show_id)
    if show is None:
        raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")
    seller = DB.sellers.get(seller_id)
    if seller is None:
        raise err(ERR_SELLER_NOT_FOUND, 404, "No Seller with the given id")

    cash_float = require_int(body, "cash_float_cents", ge=0, required=True)

    if show["status"] != "OPEN":
        raise err(ERR_INVALID_SHOW_STATE, 409, "Staffing requires an OPEN show")

    if seller["tour_id"] != show["tour_id"]:
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Seller must belong to the show's tour")

    # Seller double-booking: no other non-CANCELLED session on a show with the
    # same calendar date.
    show_date = calendar_date_of(show)
    for other in DB.sessions.values():
        if other["seller_id"] != seller_id:
            continue
        other_show = DB.shows[other["show_id"]]
        if other_show["status"] == "CANCELLED":
            continue
        if calendar_date_of(other_show) == show_date:
            if other["show_id"] == show_id:
                raise err(ERR_SESSION_EXISTS, 409,
                          "A SellerSession already exists for this (show, seller)")
            raise err(ERR_SELLER_DOUBLE_BOOKED, 409,
                      "Seller already holds a session on another show that date")

    session = {
        **base_fields(),
        "show_id": show_id,
        "seller_id": seller_id,
        "cash_float_cents": cash_float,
        "status": "OPEN",
        "counted_cash_cents": None,
        "verified_by_user_id": None,
        "recount_count": 0,
    }
    DB.sessions[session["id"]] = session
    return success_object(session_view(session), status=201)


@bp.get("/merch/seller-sessions")
def list_sessions():
    require_auth()
    show_id = request.args.get("show_id")
    seller_id = request.args.get("seller_id")
    items = list(DB.sessions.values())
    if show_id is not None:
        items = [s for s in items if s["show_id"] == show_id]
    if seller_id is not None:
        items = [s for s in items if s["seller_id"] == seller_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([session_view(s) for s in page], limit, offset, total)


@bp.get("/merch/seller-sessions/<session_id>")
def get_session(session_id):
    require_auth()
    return success_object(session_view(get_session_or_404(session_id)))


@bp.post("/merch/seller-sessions/<session_id>/count-out")
def count_out(session_id):
    user_id, role = require_role("Seller")
    session = get_session_or_404(session_id)

    # Ownership (priority 2 in PRD §2.7 — but role check already ran; the
    # ownership check on a Seller-scoped endpoint belongs to the same tier).
    if session["seller_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, 403,
                  "Only the session's owning seller may count out")

    if session["status"] != "OPEN":
        raise err(ERR_SESSION_NOT_OPEN, 409, "Count-out requires an OPEN session")
    show = DB.shows[session["show_id"]]
    if show["status"] != "OPEN":
        raise err(ERR_INVALID_SHOW_STATE, 409, "Count-out requires the show to be OPEN")

    body = get_json_body()
    counted = require_int(body, "counted_cash_cents", ge=0, required=True)

    session["counted_cash_cents"] = counted
    session["status"] = "COUNTED_OUT"
    touch(session)
    return success_object(session_view(session))


@bp.post("/merch/seller-sessions/<session_id>/verify")
def verify_session(session_id):
    user_id, role = require_role("Seller", "TourManager")
    session = get_session_or_404(session_id)

    if session["status"] != "COUNTED_OUT":
        raise err(ERR_SESSION_NOT_COUNTED_OUT, 409,
                  "Verify requires a COUNTED_OUT session")

    show = DB.shows[session["show_id"]]
    if show["status"] not in ("OPEN", "RECONCILING"):
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Verify requires the show to be OPEN or RECONCILING")

    body = get_json_body()
    decision = require_enum(body, "decision", ("APPROVE", "REJECT"), required=True)
    variance_override = require_bool(body, "variance_override")

    # Segregation of duties: verifier must differ from the session's seller.
    if user_id == session["seller_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403,
                  "The verifier must differ from the session's seller")

    if decision == "APPROVE":
        tour = DB.tours[show["tour_id"]]
        variance = session_variance(session)
        if variance is not None and abs(variance) > tour["cash_variance_tolerance_cents"]:
            if not (variance_override is True and role == "TourManager"):
                raise err(ERR_VARIANCE_OVERRIDE_REQUIRED, 409,
                          "Over-tolerance variance requires variance_override by a TourManager")
        session["status"] = "VERIFIED"
        session["verified_by_user_id"] = user_id
    else:  # REJECT -> back to OPEN for a recount
        session["status"] = "OPEN"
        session["recount_count"] += 1
        session["counted_cash_cents"] = None
    touch(session)
    return success_object(session_view(session))
