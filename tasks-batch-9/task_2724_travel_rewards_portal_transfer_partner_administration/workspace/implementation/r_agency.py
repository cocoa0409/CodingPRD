"""Travel agencies and portal inventory offers (PRD 3.5)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_agency_scope, require_ownership
from core import (
    DB,
    clock_iso,
    fmt_dt,
    must_find,
    new_row,
    ok,
    ordered,
    store,
    touch,
)
from errors import ApiError, invalid
from rhelp import (
    require_account_open,
    require_agency_active,
    require_available_points,
    require_in_parity,
    require_not_locked,
    require_offer_bookable,
    require_seat,
    require_state,
)
from shapes import body, opt_dt, opt_int, req_dt, req_int, req_string
from svc_ledger import count_committed, recompute_seats, refresh_account
from svc_pricing import apply_offer_pricing, blank_order, price_portal_booking
from views import (
    ADMIN,
    AGENCY_READ,
    CARDHOLDER,
    OFFER_READ,
    SUPPLIER,
    listing,
    offer_view,
    plain,
)

bp = Blueprint("agency", __name__)


@bp.post("/agency-partners")
@endpoint(ADMIN)
def create_agency():
    data = body()
    row = store(
        "agencies",
        new_row(
            "agencies",
            {
                "name": req_string(data, "name"),
                "contracted_markup_bps": req_int(
                    data, "contracted_markup_bps", minimum=0, maximum=5000
                ),
                "parity_tolerance_bps": req_int(
                    data, "parity_tolerance_bps", minimum=0, maximum=5000
                ),
                "invoice_terms_days": opt_int(data, "invoice_terms_days", 30, minimum=0),
                "status": "ACTIVE",
                "payable_cents": 0,
                "suspended_reason": None,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/agency-partners/<agency_id>")
@endpoint(AGENCY_READ)
def read_agency(agency_id):
    return ok(plain(must_find("agencies", agency_id)))


@bp.get("/agency-partners")
@endpoint(AGENCY_READ)
def list_agencies():
    args = request.args
    return listing("agencies", args, {"status": args.get("status")})


@bp.post("/agency-partners/<agency_id>/suspend")
@endpoint(ADMIN)
def suspend_agency(agency_id):
    agency = must_find("agencies", agency_id)
    reason = req_string(body(), "suspended_reason")
    require_state(agency, ("ACTIVE",))
    agency["status"] = "SUSPENDED"
    agency["suspended_reason"] = reason
    touch(agency)
    offers = ordered(
        "offers",
        [
            o
            for o in DB["offers"].values()
            if o["agency_partner_id"] == agency_id and o["status"] == "OPEN"
        ],
    )
    for offer in offers:
        offer["status"] = "SUSPENDED"
        offer["suspension_reason"] = "AGENCY_SUSPENDED"
        touch(offer)
    return ok(plain(agency))


# --------------------------------------------------------------------------
# portal inventory offers
# --------------------------------------------------------------------------
def _availability_guard(portal_seats, agency_public_seats):
    if portal_seats > agency_public_seats:
        raise ApiError(
            "ERR_AVAILABILITY_PARITY_BREACH",
            "portal_seats may not exceed agency_public_seats.",
        )


@bp.post("/inventory-offers")
@endpoint(SUPPLIER)
def create_offer():
    data = body()
    agency_id = data.get("agency_partner_id")
    if isinstance(agency_id, str):
        require_agency_scope(agency_id)
    if not isinstance(agency_id, str) or agency_id.strip() == "":
        raise invalid("'agency_partner_id' is required")
    agency = must_find("agencies", agency_id)

    itinerary_code = req_string(data, "itinerary_code")
    depart_at = req_dt(data, "depart_at")
    return_at = opt_dt(data, "return_at")
    net_rate_cents = req_int(data, "net_rate_cents", minimum=1)
    agency_public_price_cents = req_int(data, "agency_public_price_cents", minimum=1)
    agency_public_seats = req_int(data, "agency_public_seats", minimum=0)
    portal_seats = req_int(data, "portal_seats", minimum=1)
    tax_cents = req_int(data, "tax_cents", minimum=0)

    require_agency_active(agency)
    _availability_guard(portal_seats, agency_public_seats)

    row = new_row(
        "offers",
        {
            "agency_partner_id": agency_id,
            "itinerary_code": itinerary_code,
            "depart_at": fmt_dt(depart_at),
            "return_at": fmt_dt(return_at),
            "net_rate_cents": net_rate_cents,
            "agency_public_price_cents": agency_public_price_cents,
            "agency_public_seats": agency_public_seats,
            "portal_seats": portal_seats,
            "tax_cents": tax_cents,
            "portal_price_cents": 0,
            "cash_copay_cents": 0,
            "parity_status": "IN_PARITY",
            "seats_committed": 0,
            "status": "OPEN",
            "last_resynced_at": None,
            "suspension_reason": None,
        },
    )
    apply_offer_pricing(row, agency)
    store("offers", row)
    return ok(plain(row), 201)


@bp.get("/inventory-offers/<offer_id>")
@endpoint(OFFER_READ)
def read_offer(offer_id):
    return ok(offer_view(must_find("offers", offer_id)))


@bp.get("/inventory-offers")
@endpoint(OFFER_READ)
def list_offers():
    args = request.args
    filters = {
        "agency_partner_id": args.get("agency_partner_id"),
        "itinerary_code": args.get("itinerary_code"),
        "status": args.get("status"),
        "parity_status": args.get("parity_status"),
    }
    return listing("offers", args, filters, offer_view)


@bp.post("/inventory-offers/<offer_id>/resync")
@endpoint(SUPPLIER)
def resync_offer(offer_id):
    offer = must_find("offers", offer_id)
    require_agency_scope(offer["agency_partner_id"])
    agency = must_find("agencies", offer["agency_partner_id"])
    data = body()
    net_rate_cents = req_int(data, "net_rate_cents", minimum=1)
    agency_public_price_cents = req_int(data, "agency_public_price_cents", minimum=1)
    agency_public_seats = req_int(data, "agency_public_seats", minimum=0)
    portal_seats = req_int(data, "portal_seats", minimum=1)
    _availability_guard(portal_seats, agency_public_seats)

    offer["net_rate_cents"] = net_rate_cents
    offer["agency_public_price_cents"] = agency_public_price_cents
    offer["agency_public_seats"] = agency_public_seats
    offer["portal_seats"] = portal_seats
    apply_offer_pricing(offer, agency)
    offer["last_resynced_at"] = clock_iso()
    touch(offer)
    return ok(offer_view(offer))


@bp.post("/inventory-offers/<offer_id>/suspend")
@endpoint(ADMIN)
def suspend_offer(offer_id):
    offer = must_find("offers", offer_id)
    reason = req_string(body(), "suspension_reason")
    require_state(offer, ("OPEN",))
    offer["status"] = "SUSPENDED"
    offer["suspension_reason"] = reason
    touch(offer)
    return ok(offer_view(offer))


@bp.post("/inventory-offers/<offer_id>/reinstate")
@endpoint(ADMIN)
def reinstate_offer(offer_id):
    offer = must_find("offers", offer_id)
    agency = must_find("agencies", offer["agency_partner_id"])
    require_state(offer, ("SUSPENDED",))
    require_agency_active(agency)
    offer["seats_committed"] = count_committed(offer["id"])
    if offer["seats_committed"] >= offer["portal_seats"]:
        raise ApiError(
            "ERR_OFFER_HAS_COMMITTED_SEATS",
            "Offer '%s' has no free portal seat to reinstate into." % offer_id,
        )
    offer["status"] = "OPEN"
    offer["suspension_reason"] = None
    touch(offer)
    return ok(offer_view(offer))


@bp.post("/inventory-offers/<offer_id>/withdraw")
@endpoint(SUPPLIER)
def withdraw_offer(offer_id):
    offer = must_find("offers", offer_id)
    require_agency_scope(offer["agency_partner_id"])
    require_state(offer, ("OPEN", "SUSPENDED"))
    offer["seats_committed"] = count_committed(offer["id"])
    if offer["seats_committed"] != 0:
        raise ApiError(
            "ERR_OFFER_HAS_COMMITTED_SEATS",
            "Offer '%s' has committed seats and cannot be withdrawn." % offer_id,
        )
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return ok(offer_view(offer))


@bp.post("/inventory-offers/<offer_id>/book")
@endpoint(CARDHOLDER)
def book_offer(offer_id):
    data = body()
    account_id = data.get("account_id")
    if isinstance(account_id, str):
        require_ownership(account_id)
    offer = must_find("offers", offer_id)
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)

    traveler_name = req_string(data, "traveler_name")
    expected_offer_version = req_int(data, "expected_offer_version", minimum=0)
    if expected_offer_version != offer["version"]:
        raise ApiError(
            "ERR_STALE_OFFER_VERSION",
            "Offer '%s' is at version %d." % (offer_id, offer["version"]),
        )

    require_account_open(account)
    require_not_locked(account)
    require_offer_bookable(offer)
    require_in_parity(offer)
    offer["seats_committed"] = count_committed(offer["id"])
    require_seat(offer)

    row = new_row("orders", blank_order(account_id, "PORTAL_BOOKING"))
    row["inventory_offer_id"] = offer_id
    row["traveler_name"] = traveler_name
    price_portal_booking(row, offer, account)
    require_available_points(account, row["points_debited"])

    store("orders", row)
    recompute_seats(offer)
    touch(offer)
    refresh_account(account)
    touch(account)
    return ok(plain(row), 201)
