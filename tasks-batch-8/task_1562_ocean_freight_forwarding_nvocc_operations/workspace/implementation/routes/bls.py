"""Bill of lading endpoints (PRD section 3.11).

DRAFT -> ISSUED -> (AMENDMENT_PENDING -> DRAFT amendment cycle, cap 3);
ISSUED -> RELEASED direct only for SEAWAY; ORIGINAL/TELEX route through
SURRENDERED. Release is SoD-guarded (releaser != issuer), filings-gated
(ISF + AMS ACCEPTED), and PREPAID-payment-gated. Issue is bond-gated.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ACTIVE_BL_EXISTS,
    ERR_AMENDMENT_LIMIT_EXCEEDED,
    ERR_BL_INVALID_STATE,
    ERR_BL_NOT_FOUND,
    ERR_BOND_COVERAGE_INSUFFICIENT,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_FILINGS_NOT_CLEARED,
    ERR_OUTSTANDING_BALANCE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import ALL_ROLES, check_shipper_ownership, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    has_field,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("bills_of_lading", __name__)

BL_TYPES = {"HOUSE", "MASTER"}
RELEASE_MODES = {"ORIGINAL", "SEAWAY", "TELEX"}


def _get_bl(bl_id: str) -> dict:
    bl = db.bills_of_lading.get(bl_id)
    if bl is None:
        raise_err(ERR_BL_NOT_FOUND, "BillOfLading id does not exist")
    return bl


def _filings_cleared(booking_id: str) -> bool:
    filings = [f for f in db.compliance_filings.values() if f["booking_id"] == booking_id]
    isf_ok = any(f["filing_type"] == "ISF" and f["status"] == "ACCEPTED" for f in filings)
    ams_ok = any(f["filing_type"] == "AMS" and f["status"] == "ACCEPTED" for f in filings)
    return isf_ok and ams_ok


def _prepaid_paid(booking: dict) -> bool:
    """PREPAID payment gate: every FREIGHT invoice of the booking must be PAID
    (VOID invoices are dead and ignored)."""
    for inv in db.invoices.values():
        if (
            inv["booking_id"] == booking["id"]
            and inv["invoice_type"] == "FREIGHT"
            and inv["status"] not in ("PAID", "VOID")
        ):
            return False
    return True


@bp.route("/freight/bill-of-lading", methods=["POST"])
@require_roles("DocumentationOfficer")
def create_bl(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    bl_type = require_enum(body, "bl_type", BL_TYPES)
    release_mode = require_enum(body, "release_mode", RELEASE_MODES)

    # Band 6: booking state permits drafting.
    if booking["status"] not in ("CONFIRMED", "DOCUMENTATION_CLEARED", "LOADED", "DEPARTED", "ARRIVED"):
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit B/L creation")

    # Band 10: at most one non-terminal B/L per booking.
    for other in db.bills_of_lading.values():
        if other["booking_id"] == booking["id"] and other["status"] in (
            "DRAFT",
            "ISSUED",
            "AMENDMENT_PENDING",
            "SURRENDERED",
        ):
            raise_err(ERR_ACTIVE_BL_EXISTS, "Booking already has a non-terminal bill of lading")

    bl = {
        "booking_id": booking["id"],
        "bl_number": f"BL-{db.next_seq('bl')}",
        "bl_type": bl_type,
        "release_mode": release_mode,
        "issued_by_user_id": None,
        "released_by_user_id": None,
        "amendment_count": 0,
        "status": "DRAFT",
    }
    db.stamp_new(bl)
    db.bills_of_lading[bl["id"]] = bl
    return success_object(pub(bl), 201)


@bp.route("/freight/bill-of-lading", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bls(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.bills_of_lading.values()))
    items = apply_filters(items, ["booking_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(b) for b in page], limit, offset, total)


@bp.route("/freight/bill-of-lading/<bl_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_bl(bl_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_bl(bl_id)))


@bp.route("/freight/bill-of-lading/<bl_id>/issue", methods=["POST"])
@require_roles("DocumentationOfficer")
def issue_bl(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()
    if bl["status"] != "DRAFT":
        raise_err(ERR_BL_INVALID_STATE, "B/L must be DRAFT to issue")
    booking = db.bookings.get(bl["booking_id"])
    if booking is None or booking["status"] not in (
        "CONFIRMED",
        "DOCUMENTATION_CLEARED",
        "LOADED",
        "DEPARTED",
    ):
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit B/L issue")
    # Band 7: bond gate.
    if not domain.qualifying_bond_exists():
        raise_err(
            ERR_BOND_COVERAGE_INSUFFICIENT,
            "No ACTIVE surety bond in its window with sufficient available coverage",
        )
    bl["status"] = "ISSUED"
    bl["issued_by_user_id"] = _user_id
    db.touch(bl)
    # Booking DOCUMENTATION_CLEARED gate re-evaluation.
    domain.reevaluate_doc_gate(booking)
    return success_object(pub(bl))


@bp.route("/freight/bill-of-lading/<bl_id>/request-amendment", methods=["POST"])
@require_roles("DocumentationOfficer")
def request_amendment(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()
    if bl["status"] != "ISSUED":
        raise_err(ERR_BL_INVALID_STATE, "B/L must be ISSUED to request an amendment")
    if bl["amendment_count"] >= domain.MAX_AMENDMENTS:
        raise_err(ERR_AMENDMENT_LIMIT_EXCEEDED, "Amendment count cap reached")
    bl["status"] = "AMENDMENT_PENDING"
    bl["amendment_count"] += 1
    db.touch(bl)
    return success_object(pub(bl))


@bp.route("/freight/bill-of-lading/<bl_id>/reissue", methods=["POST"])
@require_roles("DocumentationOfficer")
def reissue_bl(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()
    if bl["status"] != "AMENDMENT_PENDING":
        raise_err(ERR_BL_INVALID_STATE, "B/L must be AMENDMENT_PENDING to reissue")
    bl["status"] = "DRAFT"
    db.touch(bl)
    # Documentation gate re-opens while no B/L is ISSUED.
    booking = db.bookings.get(bl["booking_id"])
    if booking is not None and booking["status"] == "DOCUMENTATION_CLEARED":
        booking["status"] = "CONFIRMED"
        db.touch(booking)
    return success_object(pub(bl))


@bp.route("/freight/bill-of-lading/<bl_id>/surrender", methods=["POST"])
@require_roles("Shipper")
def surrender_bl(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()
    # Band 2 ownership: the surrendering Shipper must own the booking.
    booking = db.bookings.get(bl["booking_id"])
    if booking is not None:
        check_shipper_ownership(_role, _user_id, booking["shipper_id"])
    if bl["status"] != "ISSUED":
        raise_err(ERR_BL_INVALID_STATE, "B/L must be ISSUED to surrender")
    if bl["release_mode"] not in ("ORIGINAL", "TELEX"):
        raise_err(ERR_BL_INVALID_STATE, "Only ORIGINAL or TELEX bills can be surrendered")
    bl["status"] = "SURRENDERED"
    db.touch(bl)
    return success_object(pub(bl))


@bp.route("/freight/bill-of-lading/<bl_id>/release", methods=["POST"])
@require_roles("DocumentationOfficer")
def release_bl(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()

    # Band 4: SoD — releaser must differ from issuer.
    if bl.get("issued_by_user_id") is not None and _user_id == bl["issued_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "B/L releaser must differ from the issuer")

    # Band 6: lawful paths — SEAWAY direct from ISSUED; ORIGINAL/TELEX from
    # SURRENDERED.
    if bl["status"] == "ISSUED" and bl["release_mode"] == "SEAWAY":
        pass
    elif bl["status"] == "SURRENDERED" and bl["release_mode"] in ("ORIGINAL", "TELEX"):
        pass
    else:
        raise_err(ERR_BL_INVALID_STATE, "B/L state and release mode do not permit release")

    # Band 7: both customs filings must be ACCEPTED.
    if not _filings_cleared(bl["booking_id"]):
        raise_err(ERR_FILINGS_NOT_CLEARED, "ISF and AMS filings must both be ACCEPTED")

    # Band 13: PREPAID requires every FREIGHT invoice PAID.
    booking = db.bookings.get(bl["booking_id"])
    if booking is not None and booking["terms"] == "PREPAID" and not _prepaid_paid(booking):
        raise_err(ERR_OUTSTANDING_BALANCE, "PREPAID booking has an unpaid FREIGHT invoice")

    bl["status"] = "RELEASED"
    bl["released_by_user_id"] = _user_id
    db.touch(bl)
    return success_object(pub(bl))


@bp.route("/freight/bill-of-lading/<bl_id>/void", methods=["POST"])
@require_roles("DocumentationOfficer")
def void_bl(bl_id: str, _user_id: str, _role: str):
    bl = _get_bl(bl_id)
    get_json_body()
    # Manual void is permitted only from DRAFT or AMENDMENT_PENDING.
    if bl["status"] not in ("DRAFT", "AMENDMENT_PENDING"):
        raise_err(ERR_BL_INVALID_STATE, "Only a DRAFT or AMENDMENT_PENDING B/L can be voided manually")
    bl["status"] = "VOIDED"
    db.touch(bl)
    return success_object(pub(bl))
