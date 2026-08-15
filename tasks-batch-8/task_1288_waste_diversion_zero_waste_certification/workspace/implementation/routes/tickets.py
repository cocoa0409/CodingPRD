"""WeightTicket endpoints: capture, stewardship, and the correction loop."""

from flask import Blueprint

from db import base_record, store, touch
from errors import (
    ApiError,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CROSS_SITE_REFERENCE,
    ERR_DUPLICATE_TICKET_REF,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WEIGHTS,
    ERR_NO_OPEN_PERIOD,
    ERR_STREAM_CONTRACT_MISMATCH,
    ERR_TICKET_DATE_FUTURE,
    ERR_TICKET_NOT_PENDING,
    ERR_TICKET_NOT_REJECTED,
    ERR_TICKET_NOT_VALIDATED,
    ERR_VENDOR_MISMATCH,
    ERR_VENDOR_NOT_ACTIVE,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_date,
    f_enum,
    f_int,
    f_pct,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.lifecycle import (
    bump_period_for,
    open_period_containing,
    pub_ticket,
    reject_ticket,
    void_ticket,
)
from util import (
    DISPOSAL_ROUTES,
    MATERIAL_STREAMS,
    TICKET_STATUSES,
    apply_filters,
    paginate,
    sort_items,
)

bp = Blueprint("tickets", __name__)


def _weight_value(b, k, required=True):
    """Weights must be JSON integers; non-positive handled later as 422."""
    v = b.get(k)
    if v is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {k}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} must be an integer")
    return v


def _check_weights(gross, tare):
    """Layer 8: both positive integers and gross strictly greater than tare."""
    if gross <= 0 or tare <= 0 or gross <= tare:
        raise ApiError(ERR_INVALID_WEIGHTS, 422,
                       "gross_weight_lbs must be a positive integer strictly "
                       "greater than tare_weight_lbs")


@bp.route("/tickets", methods=["POST"])
def create_ticket():
    uid, _ = authenticate(["VendorUser"])
    b = get_body()

    # Ownership is enforced before anything else about the payload.
    if "vendor_id" in b and b["vendor_id"] is not None and b["vendor_id"] != uid:
        raise ApiError(ERR_VENDOR_MISMATCH, 403,
                       "VendorUser may only create tickets for its own vendor_id")

    # Layer 3: well-formedness (net_weight_lbs is server-computed; client input
    # is explicitly ignored, so it is accepted and discarded).
    check_unknown(b, ["site_id", "vendor_id", "contract_id", "material_stream",
                      "disposal_route", "gross_weight_lbs", "tare_weight_lbs",
                      "net_weight_lbs", "contamination_pct", "ticket_date",
                      "external_ticket_ref"])
    site_id = f_str(b, "site_id")
    vendor_id = f_str(b, "vendor_id")
    contract_id = f_str(b, "contract_id")
    stream = f_enum(b, "material_stream", MATERIAL_STREAMS)
    route = f_enum(b, "disposal_route", DISPOSAL_ROUTES)
    gross = _weight_value(b, "gross_weight_lbs")
    tare = _weight_value(b, "tare_weight_lbs")
    ticket_date = f_date(b, "ticket_date")
    ref = f_str(b, "external_ticket_ref")
    pct = f_pct(b, "contamination_pct", required=False, nullable=True)

    # Layer 4: existence of referenced site, vendor, contract.
    if site_id not in store.sites:
        raise not_found("Site not found")
    if vendor_id not in store.vendors:
        raise not_found("Vendor not found")
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise not_found("Contract not found")

    # Layer 8: uniqueness of (vendor_id, external_ticket_ref) over non-VOIDED.
    for t in store.tickets.values():
        if (t["vendor_id"] == vendor_id
                and t["external_ticket_ref"] == ref
                and t["validation_status"] != "VOIDED"):
            raise ApiError(ERR_DUPLICATE_TICKET_REF, 409,
                           "external_ticket_ref already exists for this vendor")

    # Layer 8: weight arithmetic.
    _check_weights(gross, tare)

    # Layer 8: stream must equal the contract's stream.
    if stream != contract["material_stream"]:
        raise ApiError(ERR_STREAM_CONTRACT_MISMATCH, 422,
                       "material_stream differs from the contract's stream")

    # Layer 9: contract must be ACTIVE.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "Contract is not ACTIVE")

    # Layer 9: contract scope must match the ticket body.
    if contract["site_id"] != site_id or contract["vendor_id"] != vendor_id:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 422,
                       "Contract belongs to another site or vendor")

    rec = base_record({
        "site_id": site_id,
        "vendor_id": vendor_id,
        "contract_id": contract_id,
        "material_stream": stream,
        "disposal_route": route,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_weight_lbs": gross - tare,
        "contamination_pct": pct,
        "ticket_date": ticket_date,
        "external_ticket_ref": ref,
        "validation_status": "PENDING",
        "rejection_reason": None,
    })
    store.tickets[rec["id"]] = rec
    # Joins the containing OPEN period's provisional set (live computation).
    bump_period_for(site_id, ticket_date)
    return success_object(pub_ticket(rec), 201)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    authenticate(ALL_ROLES)
    rec = store.tickets.get(ticket_id)
    if rec is None:
        raise not_found("Ticket not found")
    return success_object(pub_ticket(rec))


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    authenticate(ALL_ROLES)
    items = apply_filters(store.tickets.values(), [
        ("site_id", "site_id", None),
        ("vendor_id", "vendor_id", None),
        ("contract_id", "contract_id", None),
        ("validation_status", "validation_status", TICKET_STATUSES),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_ticket(t) for t in page], meta)


@bp.route("/tickets/<ticket_id>/validate", methods=["POST"])
def validate_ticket(ticket_id):
    authenticate(["DataSteward"])
    no_input(get_body())
    t = store.tickets.get(ticket_id)
    if t is None:
        raise not_found("Ticket not found")

    if t["validation_status"] != "PENDING":
        raise ApiError(ERR_TICKET_NOT_PENDING, 409, "Ticket is not PENDING")
    contract = store.contracts.get(t["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "Contract is not ACTIVE")
    vendor = store.vendors.get(t["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409, "Vendor is not ACTIVE")
    if t["ticket_date"] > store.clock_date():
        raise ApiError(ERR_TICKET_DATE_FUTURE, 422,
                       "ticket_date is later than the logical clock date")
    period = open_period_containing(t["site_id"], t["ticket_date"])
    if period is None:
        raise ApiError(ERR_NO_OPEN_PERIOD, 409,
                       "No OPEN scorecard period contains ticket_date")

    t["validation_status"] = "VALIDATED"
    touch(t)
    touch(period)  # certified totals and rebate estimate accrue (live)
    return success_object(pub_ticket(t))


@bp.route("/tickets/<ticket_id>/reject", methods=["POST"])
def reject_ticket_endpoint(ticket_id):
    authenticate(["DataSteward"])
    b = get_body()
    check_unknown(b, ["reason"])
    reason = f_str(b, "reason")
    t = store.tickets.get(ticket_id)
    if t is None:
        raise not_found("Ticket not found")
    if t["validation_status"] != "PENDING":
        raise ApiError(ERR_TICKET_NOT_PENDING, 409, "Ticket is not PENDING")

    reject_ticket(t, reason)
    return success_object(pub_ticket(t))


@bp.route("/tickets/<ticket_id>/resubmit", methods=["POST"])
def resubmit_ticket(ticket_id):
    uid, _ = authenticate(["VendorUser"])
    b = get_body()
    check_unknown(b, ["gross_weight_lbs", "tare_weight_lbs", "ticket_date",
                      "contamination_pct", "disposal_route"])
    gross = _weight_value(b, "gross_weight_lbs", required=False)
    tare = _weight_value(b, "tare_weight_lbs", required=False)
    new_date = f_date(b, "ticket_date", required=False)
    pct = f_pct(b, "contamination_pct", required=False, nullable=True)
    route = f_enum(b, "disposal_route", DISPOSAL_ROUTES, required=False)

    t = store.tickets.get(ticket_id)
    if t is None:
        raise not_found("Ticket not found")
    # Vendor ownership on the ticket's vendor_id.
    if t["vendor_id"] != uid:
        raise ApiError(ERR_VENDOR_MISMATCH, 403,
                       "VendorUser does not own this ticket")
    if t["validation_status"] != "REJECTED":
        raise ApiError(ERR_TICKET_NOT_REJECTED, 409, "Ticket is not REJECTED")

    # Apply corrections and recompute.
    new_gross = gross if gross is not None else t["gross_weight_lbs"]
    new_tare = tare if tare is not None else t["tare_weight_lbs"]
    _check_weights(new_gross, new_tare)
    t["gross_weight_lbs"] = new_gross
    t["tare_weight_lbs"] = new_tare
    t["net_weight_lbs"] = new_gross - new_tare
    if new_date is not None:
        t["ticket_date"] = new_date
    if "contamination_pct" in b:
        t["contamination_pct"] = pct
    if route is not None:
        t["disposal_route"] = route
    t["rejection_reason"] = None
    t["validation_status"] = "PENDING"
    touch(t)
    bump_period_for(t["site_id"], t["ticket_date"])
    return success_object(pub_ticket(t))


@bp.route("/tickets/<ticket_id>/void", methods=["POST"])
def void_ticket_endpoint(ticket_id):
    authenticate(["DataSteward"])
    b = get_body()
    check_unknown(b, ["reason"])
    f_str(b, "reason", required=False, nullable=True)
    t = store.tickets.get(ticket_id)
    if t is None:
        raise not_found("Ticket not found")
    if t["validation_status"] != "VALIDATED":
        raise ApiError(ERR_TICKET_NOT_VALIDATED, 409, "Ticket is not VALIDATED")

    void_ticket(t)
    return success_object(pub_ticket(t))
