"""Clients, bookings, credentialing, disruption and collection (PRD 3.5-3.8)."""
from flask import Blueprint

import calc
import services
from auth import (
    CLIENT_PORTAL_USER,
    CLIENT_SERVICE_AGENT,
    FINANCE_CONTROLLER,
    guard,
    scope_client_id,
)
from common import (
    get_block,
    get_booking,
    get_client,
    get_event,
    get_installment,
    get_package,
    listing,
)
from errors import (
    ERR_ALLOCATION_UNITS_UNAVAILABLE,
    ERR_BLOCK_NOT_OPEN,
    ERR_BOOKING_NOT_ALLOCATED,
    ERR_BUILD_NOT_READY,
    ERR_CHANNEL_OR_DEAL_MISMATCH,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_EVENT_RISK_CRITICAL,
    ERR_INSTALLMENT_AMOUNT_MISMATCH,
    ERR_INSTALLMENT_NOT_PAYABLE,
    ERR_INVALID_BOOKING_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_INVALID_PACKAGE_STATE,
    ERR_REBOOK_WINDOW_CLOSED,
    ERR_STALE_BLOCK_VERSION,
    fail,
)
from response import object_response
from store import (
    apply_silent,
    booking_json,
    client_json,
    create_record,
    db,
    logical_now,
    payment_installment_json,
    touch,
    update_record,
)
from validation import body, opt_bool, opt_int, req_enum, req_id, req_int, req_string

bp = Blueprint("sales", __name__)

CHANNELS = ("INDIVIDUAL", "CORPORATE", "TRAVEL_PARTNER")
CLIENT_TYPES = ("INDIVIDUAL", "CORPORATE", "TRAVEL_PARTNER")


# --- Client -----------------------------------------------------------------


@bp.route("/clients", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT)
def create_client():
    data = body()
    name = req_string(data, "name")
    client_type = req_enum(data, "client_type", CLIENT_TYPES)
    credit_limit_cents = opt_int(data, "credit_limit_cents", default=0)

    client = create_record(
        db.clients,
        {
            "name": name,
            "client_type": client_type,
            "credit_limit_cents": credit_limit_cents,
            "client_status": "ACTIVE",
            "outstanding_cents": 0,
            "overdue_installment_count": 0,
        },
    )
    return object_response(client_json(client), 201)


@bp.route("/clients/<client_id>", methods=["GET"])
@guard(CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER, CLIENT_PORTAL_USER)
def read_client(client_id):
    scope_client_id(client_id)
    return object_response(client_json(get_client(client_id)))


# --- Booking ----------------------------------------------------------------


@bp.route("/bookings", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT)
def create_booking():
    data = body()
    client_id = req_id(data, "client_id")
    package_id = req_id(data, "package_product_id")
    channel = req_enum(data, "channel", CHANNELS)
    units = req_int(data, "units", minimum=1)
    risk_override_ack = opt_bool(data, "risk_override_ack", default=False)

    package = get_package(package_id)
    client = get_client(client_id)
    event = get_event(package["event_id"])

    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "This fixture can no longer be sold.")
    if package["package_status"] != "PUBLISHED":
        fail(ERR_INVALID_PACKAGE_STATE, "Only a published package can be sold.")

    apply_silent(event, calc.event_risk_values(event))
    if event["risk_posture"] == "CRITICAL" and not risk_override_ack:
        fail(
            ERR_EVENT_RISK_CRITICAL,
            "This fixture carries critical fulfillment risk; risk_override_ack is required.",
        )

    if client["client_status"] != "ACTIVE":
        fail(ERR_CLIENT_NOT_ACTIVE, "The client's credit standing does not permit new sales.")

    prices = calc.booking_price_values(package, units, channel)
    exposure = calc.client_exposure_values(client)["outstanding_cents"]
    if exposure + prices["net_price_cents"] > client["credit_limit_cents"]:
        fail(ERR_CREDIT_LIMIT_EXCEEDED, "This sale would exceed the client's credit limit.")

    fields = {
        "client_id": client_id,
        "package_product_id": package_id,
        "allocation_block_id": None,
        "channel": channel,
        "units": units,
        "risk_override_ack": risk_override_ack,
        "paid_cents": 0,
        "cancellation_fee_cents": 0,
        "refund_cents": 0,
        "balance_due_cents": 0,
        "settlement_variant": None,
        "payment_status": "UNPAID",
        "fulfillment_status": "RESERVED",
        "credentials_issued_count": 0,
        "credential_serial_prefix": None,
        "itinerary": None,
        "rebook_count": 0,
    }
    fields.update(prices)
    booking = create_record(db.bookings, fields)

    services.generate_schedule(booking, event)
    services.recompute_client(client)
    services.recompute_event_risk(event)
    return object_response(booking_json(booking), 201)


@bp.route("/bookings/<booking_id>", methods=["GET"])
@guard(CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER, CLIENT_PORTAL_USER)
def read_booking(booking_id):
    from auth import is_portal_user, portal_client, require_own_client_id

    if is_portal_user():
        portal_client()
    booking = get_booking(booking_id)
    if is_portal_user():
        require_own_client_id(booking["client_id"])
    return object_response(booking_json(booking))


@bp.route("/bookings", methods=["GET"])
@guard(CLIENT_SERVICE_AGENT, FINANCE_CONTROLLER)
def list_bookings():
    return listing(
        calc.all_of(db.bookings),
        booking_json,
        (
            "client_id",
            "package_product_id",
            "allocation_block_id",
            "fulfillment_status",
            "payment_status",
        ),
    )


@bp.route("/bookings/<booking_id>/allocate", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT)
def allocate_booking(booking_id):
    booking = get_booking(booking_id)
    data = body()
    block_id = req_id(data, "allocation_block_id")
    expected_version = req_int(data, "expected_allocation_block_version")

    block = get_block(block_id)
    if expected_version != block["version"]:
        fail(ERR_STALE_BLOCK_VERSION, "The allocation block has moved on since you read it.")
    if block["block_state"] not in calc.LIVE_BLOCK_STATES:
        fail(ERR_BLOCK_NOT_OPEN, "A recalled block cannot supply inventory.")
    if booking["fulfillment_status"] != "RESERVED":
        fail(ERR_INVALID_BOOKING_STATE, "Only a reserved booking can draw inventory.")

    deal = db.rights_deals.get(block["rights_deal_id"])
    if block["channel"] != booking["channel"]:
        fail(ERR_CHANNEL_OR_DEAL_MISMATCH, "The block serves a different sales channel.")
    if deal is None or deal["deal_status"] not in ("PARTIALLY_RELEASED", "FULLY_RELEASED"):
        fail(ERR_CHANNEL_OR_DEAL_MISMATCH, "The block's rights deal has released nothing yet.")

    consumed = calc.consumed_units(booking)
    if block["allocated_units"] - block["committed_units"] < consumed:
        fail(ERR_ALLOCATION_UNITS_UNAVAILABLE, "The block has too few free units.")

    booking["fulfillment_status"] = "ALLOCATED"
    booking["allocation_block_id"] = block_id
    touch(booking)
    update_record(block, {"committed_units": block["committed_units"] + consumed}, force=True)
    event = calc.event_of_booking(booking)
    if event is not None:
        services.recompute_event_risk(event)
    return object_response(booking_json(booking))


@bp.route("/bookings/<booking_id>/issue-credentials", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT)
def issue_credentials(booking_id):
    booking = get_booking(booking_id)
    body()
    if booking["fulfillment_status"] in ("CANCELLED", "DELIVERED", "REBOOK_PENDING", "CREDENTIALED"):
        fail(ERR_INVALID_BOOKING_STATE, "Credentials cannot be minted from this state.")

    package = calc.package_of_booking(booking)
    event = calc.event_of_package(package)
    ready = False
    if event is not None:
        for build in calc.builds_of_event(event["id"]):
            if build["build_state"] == "READY":
                ready = True
                break
    if not ready:
        fail(ERR_BUILD_NOT_READY, "The fixture has no hospitality build signed off as ready.")
    if booking["allocation_block_id"] is None:
        fail(ERR_BOOKING_NOT_ALLOCATED, "This booking holds no committed inventory.")

    booking["fulfillment_status"] = "CREDENTIALED"
    booking["credentials_issued_count"] = booking["units"] * (package["tickets_per_package"] + 1)
    booking["credential_serial_prefix"] = "CRD-" + booking["id"][:8].upper()
    booking["itinerary"] = services.build_itinerary(booking, package, event)
    touch(booking)
    return object_response(booking_json(booking))


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT, CLIENT_PORTAL_USER)
def cancel_booking(booking_id):
    from auth import is_portal_user, portal_client, require_own_client_id

    if is_portal_user():
        portal_client()
    booking = get_booking(booking_id)
    if is_portal_user():
        require_own_client_id(booking["client_id"])
    body()
    if booking["fulfillment_status"] in ("CANCELLED", "DELIVERED"):
        fail(ERR_INVALID_BOOKING_STATE, "This booking can no longer be cancelled.")

    package = calc.package_of_booking(booking)
    event = calc.event_of_package(package)
    previous_status = booking["fulfillment_status"]
    block_id = booking["allocation_block_id"]
    pre_paid = booking["paid_cents"]

    settlement = calc.cancellation_settlement(booking, package, event, pre_paid)

    if previous_status in ("ALLOCATED", "CREDENTIALED") and block_id is not None:
        services.return_units_to_block(booking, block_id)

    booking["fulfillment_status"] = "CANCELLED"
    booking["allocation_block_id"] = None
    booking.update(settlement)
    booking["payment_status"] = (
        "REFUNDED" if settlement["balance_due_cents"] == 0 else "SETTLEMENT_DUE"
    )
    booking["paid_cents"] = pre_paid - settlement["refund_cents"]
    if previous_status == "CREDENTIALED":
        booking["credentials_issued_count"] = 0
    touch(booking)

    services.void_open_installments(booking)
    if settlement["balance_due_cents"] > 0:
        services.create_settlement_installment(booking, settlement["balance_due_cents"])
    if previous_status == "CREDENTIALED":
        services.void_assignments_of_booking(booking)

    client = db.clients.get(booking["client_id"])
    if client is not None:
        services.recompute_client(client)
    if event is not None:
        services.recompute_event_risk(event)
    return object_response(booking_json(booking))


@bp.route("/bookings/<booking_id>/rebook", methods=["POST"])
@guard(CLIENT_SERVICE_AGENT)
def rebook_booking(booking_id):
    booking = get_booking(booking_id)
    data = body()
    target_id = req_id(data, "target_package_product_id")

    target = get_package(target_id)
    target_event = get_event(target["event_id"])
    old_event = calc.event_of_booking(booking)

    if target_event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "The target fixture is no longer live.")
    if target["package_status"] != "PUBLISHED":
        fail(ERR_INVALID_PACKAGE_STATE, "The target package is not published.")
    if booking["fulfillment_status"] != "REBOOK_PENDING":
        fail(ERR_INVALID_BOOKING_STATE, "Only a rebook-pending booking can be rebooked.")

    deadline = old_event["rebook_deadline_at"] if old_event else None
    if deadline is None or logical_now() > deadline:
        fail(ERR_REBOOK_WINDOW_CLOSED, "The rebooking window for this fixture has closed.")

    booking["package_product_id"] = target_id
    booking["rebook_count"] = booking["rebook_count"] + 1
    booking["fulfillment_status"] = "RESERVED"
    booking["allocation_block_id"] = None
    booking.update(calc.booking_price_values(target, booking["units"], booking["channel"]))
    touch(booking)

    services.void_open_installments(booking)
    services.generate_schedule(booking, target_event)

    client = db.clients.get(booking["client_id"])
    if client is not None:
        services.recompute_client(client)
    if old_event is not None:
        services.recompute_event_risk(old_event)
    if target_event is not None and (old_event is None or target_event["id"] != old_event["id"]):
        services.recompute_event_risk(target_event)
    return object_response(booking_json(booking))


# --- PaymentInstallment -----------------------------------------------------


@bp.route("/payment-installments/<installment_id>", methods=["GET"])
@guard(FINANCE_CONTROLLER, CLIENT_SERVICE_AGENT, CLIENT_PORTAL_USER)
def read_installment(installment_id):
    from auth import is_portal_user, portal_client, require_own_client_id

    if is_portal_user():
        portal_client()
    installment = get_installment(installment_id)
    if is_portal_user():
        booking = db.bookings.get(installment["booking_id"])
        require_own_client_id(booking["client_id"] if booking else None)
    return object_response(payment_installment_json(installment))


@bp.route("/payment-installments", methods=["GET"])
@guard(FINANCE_CONTROLLER, CLIENT_SERVICE_AGENT, CLIENT_PORTAL_USER)
def list_installments():
    rows = sorted(
        db.payment_installments.values(),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    return listing(
        rows,
        payment_installment_json,
        ("booking_id", "installment_state", "installment_kind"),
    )


@bp.route("/payment-installments/<installment_id>/pay", methods=["POST"])
@guard(FINANCE_CONTROLLER, CLIENT_PORTAL_USER)
def pay_installment(installment_id):
    from auth import is_portal_user, portal_client, require_own_client_id

    if is_portal_user():
        portal_client()
    installment = get_installment(installment_id)
    booking = db.bookings.get(installment["booking_id"])
    if is_portal_user():
        require_own_client_id(booking["client_id"] if booking else None)
    data = body()
    amount_paid = req_int(data, "amount_cents_paid")

    if installment["installment_state"] not in calc.OPEN_INSTALLMENT_STATES:
        fail(ERR_INSTALLMENT_NOT_PAYABLE, "This installment is no longer payable.")
    if (
        installment["installment_kind"] == "SCHEDULE"
        and booking is not None
        and booking["fulfillment_status"] == "CANCELLED"
    ):
        fail(ERR_INSTALLMENT_NOT_PAYABLE, "A schedule line on a cancelled booking is not payable.")
    if amount_paid != installment["amount_cents"]:
        fail(ERR_INSTALLMENT_AMOUNT_MISMATCH, "Installments must be paid exactly.")

    installment["installment_state"] = "PAID"
    installment["paid_amount_cents"] = installment["amount_cents"]
    installment["paid_at"] = logical_now()
    touch(installment)

    if booking is not None:
        changes = {"paid_cents": services.booking_paid_cents(booking)}
        if (
            installment["installment_kind"] == "SETTLEMENT"
            and booking["payment_status"] == "SETTLEMENT_DUE"
        ):
            changes["payment_status"] = "SETTLED"
            changes["balance_due_cents"] = 0
        elif booking["payment_status"] in ("UNPAID", "DEPOSIT_PAID"):
            changes["payment_status"] = (
                "DEPOSIT_PAID" if services.has_open_schedule_line(booking) else "PAID_IN_FULL"
            )
        update_record(booking, changes)
        client = db.clients.get(booking["client_id"])
        if client is not None:
            services.recompute_client(client)
    return object_response(payment_installment_json(installment))
