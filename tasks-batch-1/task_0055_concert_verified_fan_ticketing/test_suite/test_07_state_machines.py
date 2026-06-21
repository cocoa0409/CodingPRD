"""Corner queue B: state-machine transitions, preconditions, invalid transitions,
idempotency, terminal lockdown, and side-effect execution.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_event_with_tier,
    setup_held_ticket,
    setup_pending_transfer,
    setup_open_listing,
    register_and_verify_fan,
    create_event,
    create_tier,
    create_pending_order,
    create_paid_order,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER, SCANNER


def test_open_presale_requires_a_tier(api):
    """PRD §3.2: "Opening presale advances the event DRAFT → PRESALE, and is
    permitted only when at least one price tier already exists for the event and
    the supplied expected_event_version matches".

    Design: Corner/state_machines/open_presale_requires_a_tier
    """
    event = create_event(venue_capacity=100, presale_code="S", face_value_cents=10000)
    res = api.open_presale(event["id"], {"expected_event_version": event["version"]}, PROMOTER)
    validate_error(res, "ERR_INVALID_STATE")
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["sales_status"] == "DRAFT", ev_after


def test_open_general_from_draft_invalid_transition(api):
    """PRD §3.2: "Opening general sales advances PRESALE → GENERAL".

    open-general from DRAFT (no PRESALE precursor) is undefined -> ERR_INVALID_STATE.

    Design: Corner/state_machines/open_general_from_draft_invalid_transition
    """
    event = create_event(venue_capacity=100, presale_code="S", face_value_cents=10000)
    create_tier(event["id"], allocation=50)
    res = api.open_general(event["id"], {"expected_event_version": event["version"]}, PROMOTER)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_cancelled_order_invalid_state(api):
    """PRD §3.4: "A fan may abandon an unpaid order, moving it
    PENDING → CANCELLED and setting refund_amount_cents to 0".
    PRD §2.9: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)".

    Cancelling an already-CANCELLED order again is undefined -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_already_cancelled_order_invalid_state
    """
    event, tier = setup_event_with_tier(phase="PRESALE")
    fan = register_and_verify_fan("z@x.com", device="dev-z")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1, presale_code_used="S")
    validate_success(api.cancel_order(order["id"], make_fan_headers(fan["id"])), 200)
    res = api.cancel_order(order["id"], make_fan_headers(fan["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    o_after = validate_success(api.get_order(order["id"], make_fan_headers(fan["id"])), 200)
    assert o_after["status"] == "CANCELLED", o_after


def test_scan_terminal_void_ticket_invalid_state(api):
    """PRD §3.5: "A scan succeeds only when the ticket's entry_status is VALID".
    PRD §3.5: "A ticket also moves to VOID as a system cascade — when its owning
    order is refunded ... and VOID is terminal on the entry dimension."

    Design: Corner/state_machines/scan_terminal_void_ticket_invalid_state
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    validate_success(api.refund_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    res = api.scan_ticket(ticket["id"], {"device_channel": "MOBILE"}, SCANNER)
    validate_error(res, "ERR_INVALID_STATE")
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert t_after["entry_status"] == "VOID", t_after


def test_scan_valid_ticket_mobile_succeeds(api):
    """PRD §3.5: "A GateScanner admits a fan at the venue by scanning the ticket,
    which transitions entry_status from VALID to SCANNED. A scan succeeds only
    when the ticket's entry_status is VALID, the event's sales_status is one of
    GENERAL, SOLD_OUT, or CLOSED, the scan request carries a device_channel equal
    to MOBILE, and the ticket is not mid-transfer or listed".

    Design: Corner/state_machines/scan_valid_ticket_mobile_succeeds
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    scanned = validate_success(
        api.scan_ticket(ticket["id"], {"device_channel": "MOBILE"}, SCANNER), 200
    )
    assert scanned["entry_status"] == "SCANNED", scanned
    assert scanned["holding_status"] == "HELD", scanned


def test_transfer_accept_changes_holder_and_returns_held(api):
    """PRD §3.6: "it moves the transfer PENDING → ACCEPTED, sets the ticket's
    holder_fan_id to the recipient, and returns holding_status to HELD."

    Design: Corner/state_machines/transfer_accept_changes_holder_bubble
    """
    event, tier, sender, recipient, ticket, transfer = setup_pending_transfer(
        recipient_verified=True
    )
    accepted = validate_success(
        api.accept_transfer(transfer["id"], make_fan_headers(recipient["id"])), 200
    )
    assert accepted["status"] == "ACCEPTED", accepted
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(recipient["id"])), 200)
    assert t_after["holder_fan_id"] == recipient["id"], t_after
    assert t_after["holding_status"] == "HELD", t_after


def test_resale_buy_transfers_holder(api):
    """PRD §3.7: "On success the listing moves OPEN → SOLD, its buyer_fan_id is
    set to the acting fan, the underlying ticket's holder_fan_id becomes the
    buyer, the ticket's holding_status returns to HELD, and the listing's version
    increments".

    Design: Corner/state_machines/resale_buy_transfers_holder
    """
    event, tier, seller, ticket, listing = setup_open_listing(list_price_cents=11000)
    buyer = register_and_verify_fan("buyer@x.com", device="dev-buyer")
    sold = validate_success(api.buy_resale_listing(
        listing["id"],
        {"buyer_fan_id": buyer["id"], "expected_resalelisting_version": listing["version"]},
        make_fan_headers(buyer["id"]),
    ), 200)
    assert sold["status"] == "SOLD", sold
    assert sold["buyer_fan_id"] == buyer["id"], sold
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(buyer["id"])), 200)
    assert t_after["holder_fan_id"] == buyer["id"], t_after
