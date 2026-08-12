"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
these helpers build complete preconditions (event -> intake -> inspection ->
sale -> settlement) using only PRD-declared endpoints. Setup calls go through
get_success_data() so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    CLOCK_INTAKE_END,
    CLOCK_INTAKE_OPEN,
    CLOCK_PRESALE_START,
    CLOCK_SALE_END,
    CLOCK_SALE_START,
    advance_phase_payload,
    checkout_payload,
    create_consignor_payload,
    create_drop_off_booking_payload,
    create_drop_off_slot_payload,
    create_item_payload,
    create_markdown_rule_payload,
    create_pos_transaction_payload,
    create_sale_event_payload,
    create_shift_signup_payload,
    create_volunteer_payload,
    create_volunteer_shift_payload,
    generate_settlements_payload,
    inspect_item_payload,
    scan_line_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_consignor_headers,
    make_inspector_headers,
    make_volunteer_headers,
)

ORGANIZER = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# --- Tier 1: event + clock + phase progression ----------------------------

def create_event(**overrides) -> dict:
    """Create a sale event (phase DRAFT). Returns the SaleEvent."""
    return get_success_data(
        api_client.create_sale_event(create_sale_event_payload(**overrides), ORGANIZER)
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ORGANIZER))


def advance_phase(event_id: str, to_phase: str) -> dict:
    """Advance the event to the exact next phase. Returns the SaleEvent."""
    return get_success_data(
        api_client.advance_phase(event_id, advance_phase_payload(to_phase), ORGANIZER)
    )


def get_event(event_id: str) -> dict:
    return get_success_data(api_client.get_sale_event(event_id, ORGANIZER))


def open_intake(event_id: str):
    """DRAFT -> INTAKE_OPEN (clock set past intake_start first)."""
    set_clock(CLOCK_INTAKE_OPEN)
    return advance_phase(event_id, "INTAKE_OPEN")


def close_intake(event_id: str):
    """INTAKE_OPEN -> INTAKE_CLOSED (clock set to intake_end first)."""
    set_clock(CLOCK_INTAKE_END)
    return advance_phase(event_id, "INTAKE_CLOSED")


def start_presale(event_id: str):
    """INTAKE_CLOSED -> PRESALE_DAY (clock set to presale_start first)."""
    set_clock(CLOCK_PRESALE_START)
    return advance_phase(event_id, "PRESALE_DAY")


def start_sale(event_id: str):
    """PRESALE_DAY -> SALE_ACTIVE (clock set to sale_start first)."""
    set_clock(CLOCK_SALE_START)
    return advance_phase(event_id, "SALE_ACTIVE")


def start_settlement(event_id: str):
    """SALE_ACTIVE -> SETTLEMENT (clock set to sale_end first)."""
    set_clock(CLOCK_SALE_END)
    return advance_phase(event_id, "SETTLEMENT")


def advance_to_sale_active(event_id: str):
    """Walk INTAKE_OPEN -> INTAKE_CLOSED -> PRESALE_DAY -> SALE_ACTIVE."""
    close_intake(event_id)
    start_presale(event_id)
    return start_sale(event_id)


# --- Tier 2: registrations, slots, bookings, items, inspection ------------

def register_consignor(event_id: str, full_name: str = "Ann", **overrides) -> dict:
    """Self-register a consignor (Anonymous role). Returns the Consignor."""
    return get_success_data(
        api_client.create_consignor(
            create_consignor_payload(event_id, full_name=full_name, **overrides), ANONYMOUS
        )
    )


def register_volunteer(event_id: str, full_name: str = "Vic", linked_consignor_id=None,
                       **overrides) -> dict:
    """Self-register a volunteer (Anonymous role). Returns the Volunteer."""
    return get_success_data(
        api_client.create_volunteer(
            create_volunteer_payload(
                event_id, full_name=full_name,
                linked_consignor_id=linked_consignor_id, **overrides
            ),
            ANONYMOUS,
        )
    )


def get_consignor(consignor_id: str) -> dict:
    return get_success_data(api_client.get_consignor(consignor_id, ORGANIZER))


def get_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, ORGANIZER))


def get_item(item_id: str) -> dict:
    return get_success_data(api_client.get_item(item_id, ORGANIZER))


def create_slot(event_id: str, capacity: int = 2, start_time=None, end_time=None) -> dict:
    """Create a drop-off slot. Returns the DropOffSlot."""
    return get_success_data(
        api_client.create_drop_off_slot(
            create_drop_off_slot_payload(
                event_id, start_time=start_time, end_time=end_time, capacity=capacity
            ),
            ORGANIZER,
        )
    )


def get_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_drop_off_slot(slot_id, ORGANIZER))


def book_slot(slot_id: str, consignor_id: str) -> dict:
    """Book a slot as the owning consignor. Returns the DropOffBooking."""
    return get_success_data(
        api_client.create_drop_off_booking(
            create_drop_off_booking_payload(slot_id, consignor_id),
            make_consignor_headers(consignor_id),
        )
    )


def check_in_booking(booking_id: str) -> dict:
    """Organizer checks a BOOKED booking in. Returns the DropOffBooking."""
    return get_success_data(api_client.check_in_drop_off_booking(booking_id, ORGANIZER))


def book_and_check_in(slot_id: str, consignor_id: str) -> dict:
    """Book a slot and check the booking in. Returns the CHECKED_IN booking."""
    booking = book_slot(slot_id, consignor_id)
    return check_in_booking(booking["id"])


def create_item_for(consignor_id: str, price_cents: int = 1000, **overrides) -> dict:
    """Tag an item as the owning consignor. Returns the Item (status TAGGED)."""
    return get_success_data(
        api_client.create_item(
            create_item_payload(consignor_id, price_cents=price_cents, **overrides),
            make_consignor_headers(consignor_id),
        )
    )


def drop_off_item(item_id: str, consignor_id: str) -> dict:
    """Drop off a TAGGED item as the owning consignor. Returns the Item."""
    return get_success_data(
        api_client.drop_off_item(item_id, make_consignor_headers(consignor_id))
    )


def inspect_pass(item_id: str, inspector_volunteer_id: str) -> dict:
    """Inspect a DROPPED_OFF item with outcome PASS. Returns the Item."""
    return get_success_data(
        api_client.inspect_item(
            item_id, inspect_item_payload("PASS"),
            make_inspector_headers(inspector_volunteer_id),
        )
    )


def inspect_fail(item_id: str, inspector_volunteer_id: str, reasons: str = "stain") -> dict:
    """Inspect a DROPPED_OFF item with outcome FAIL. Returns the Item."""
    return get_success_data(
        api_client.inspect_item(
            item_id, inspect_item_payload("FAIL", reasons=reasons),
            make_inspector_headers(inspector_volunteer_id),
        )
    )


# --- Tier 2: shifts and signups --------------------------------------------

def create_shift(event_id: str, start_time="2026-05-28T09:00:00Z",
                 end_time="2026-05-28T13:00:00Z", role_name="Setup", capacity=5) -> dict:
    """Create a volunteer shift. Returns the VolunteerShift."""
    return get_success_data(
        api_client.create_volunteer_shift(
            create_volunteer_shift_payload(
                event_id, role_name=role_name, start_time=start_time,
                end_time=end_time, capacity=capacity,
            ),
            ORGANIZER,
        )
    )


def get_shift(shift_id: str) -> dict:
    return get_success_data(api_client.get_volunteer_shift(shift_id, ORGANIZER))


def sign_up(shift_id: str, volunteer_id: str) -> dict:
    """Sign the volunteer up for a shift. Returns the ShiftSignup (SIGNED_UP)."""
    return get_success_data(
        api_client.create_shift_signup(
            create_shift_signup_payload(shift_id, volunteer_id),
            make_volunteer_headers(volunteer_id),
        )
    )


def check_in_signup(signup_id: str) -> dict:
    return get_success_data(api_client.check_in_shift_signup(signup_id, ORGANIZER))


def check_out_signup(signup_id: str) -> dict:
    return get_success_data(api_client.check_out_shift_signup(signup_id, ORGANIZER))


def complete_shift_signup(event_id: str, volunteer_id: str,
                          start_time="2026-05-28T09:00:00Z",
                          end_time="2026-05-28T13:00:00Z") -> dict:
    """Create a shift, sign up, check in, check out -> COMPLETED with credited hours."""
    shift = create_shift(event_id, start_time=start_time, end_time=end_time)
    signup = sign_up(shift["id"], volunteer_id)
    check_in_signup(signup["id"])
    return check_out_signup(signup["id"])


def checked_in_shift_signup(event_id: str, volunteer_id: str,
                            start_time="2026-05-29T09:00:00Z",
                            end_time="2026-05-29T13:00:00Z") -> dict:
    """Create a shift, sign up, check in (no check-out) -> CHECKED_IN."""
    shift = create_shift(event_id, start_time=start_time, end_time=end_time)
    signup = sign_up(shift["id"], volunteer_id)
    return check_in_signup(signup["id"])


# --- Tier 3: presale passes -------------------------------------------------

def issue_passes(event_id: str) -> list:
    """Trigger event-wide pass issuance. Returns the issued PresalePass list."""
    return get_success_data(api_client.issue_presale_passes(event_id, ORGANIZER))


def get_pass_for_holder(event_id: str, holder_id: str) -> dict:
    """Fetch the (single) pass issued to a holder of the event."""
    data = get_success_data(
        api_client.list_presale_passes(
            ORGANIZER, params={"sale_event_id": event_id, "holder_id": holder_id}
        )
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one pass for holder {holder_id}, got {data}"
    )
    return data[0]


# --- Tier 3: POS ------------------------------------------------------------

def open_transaction(event_id: str, presale_pass_id=None) -> dict:
    """Cashier opens a sale ticket. Returns the OPEN POSTransaction."""
    return get_success_data(
        api_client.create_pos_transaction(
            create_pos_transaction_payload(event_id, presale_pass_id=presale_pass_id), CASHIER
        )
    )


def scan_barcode(transaction_id: str, barcode: str) -> dict:
    """Cashier scans a barcode into an OPEN ticket. Returns the TransactionLine."""
    return get_success_data(
        api_client.scan_line(transaction_id, scan_line_payload(barcode), CASHIER)
    )


def checkout_transaction(transaction_id: str, tendered_cents: int) -> dict:
    """Cashier checks out an OPEN ticket. Returns the COMPLETED POSTransaction."""
    return get_success_data(
        api_client.checkout(transaction_id, checkout_payload(tendered_cents), CASHIER)
    )


def get_transaction(transaction_id: str) -> dict:
    return get_success_data(api_client.get_pos_transaction(transaction_id, CASHIER))


# --- Tier 4: settlements ----------------------------------------------------

def generate_settlements(event_id: str) -> list:
    """Regenerate DRAFT settlements with a fresh OCC version. Returns the list."""
    event = get_event(event_id)
    return get_success_data(
        api_client.generate_settlements(
            event_id,
            generate_settlements_payload(event["version"]),
            ORGANIZER,
        )
    )


def generate_settlements_with_version(event_id: str, expected_version):
    """Raw regeneration call carrying an explicit expected_sale_event_version.
    Returns the raw Response so tests can assert stale-version rejection."""
    return api_client.generate_settlements(
        event_id, generate_settlements_payload(expected_version), ORGANIZER
    )


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, ORGANIZER))


def finalize_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.finalize_settlement(settlement_id, ORGANIZER))


# --- Tier 5: full-lifecycle composites --------------------------------------

def setup_item_on_floor(price_cents=10000, consignor_name="Ann",
                        item_overrides=None, markdown=None,
                        event_overrides=None) -> dict:
    """Full chain to SALE_ACTIVE with one item ON_FLOOR.

    event -> INTAKE_OPEN -> consignor -> slot -> booking+check-in -> item ->
    drop-off -> inspector PASS -> (optional markdown rule) -> walk to SALE_ACTIVE.
    Returns a context dict with event, consignor, slot, booking, item, barcode,
    inspector.
    """
    event = create_event(**(event_overrides or {}))
    open_intake(event["id"])
    consignor = register_consignor(event["id"], consignor_name)
    slot = create_slot(event["id"])
    booking = book_and_check_in(slot["id"], consignor["id"])
    item = create_item_for(consignor["id"], price_cents=price_cents,
                           **(item_overrides or {}))
    drop_off_item(item["id"], consignor["id"])
    inspector = register_volunteer(event["id"], "Insp Ira")
    inspect_pass(item["id"], inspector["id"])
    markdown_rule = None
    if markdown is not None:
        markdown_rule = get_success_data(
            api_client.create_markdown_rule(
                create_markdown_rule_payload(event["id"], **markdown), ORGANIZER
            )
        )
    advance_to_sale_active(event["id"])
    return {
        "event": event,
        "consignor": consignor,
        "slot": slot,
        "booking": booking,
        "item": item,
        "barcode": item["barcode"],
        "inspector": inspector,
        "markdown_rule": markdown_rule,
    }


def sell_item(ctx, tendered_cents=None, presale_pass_id=None) -> dict:
    """Open a ticket, scan the context's item, and check it out.
    Returns the COMPLETED POSTransaction."""
    item_price = ctx["item"]["price_cents"]
    tx = open_transaction(ctx["event"]["id"], presale_pass_id=presale_pass_id)
    scan_barcode(tx["id"], ctx["barcode"])
    return checkout_transaction(
        tx["id"], tendered_cents if tendered_cents is not None else item_price
    )


def setup_settlement_for_sold_item(price_cents=10000, consignor_name="Ann",
                                   item_overrides=None, markdown=None,
                                   tendered_cents=None,
                                   pre_sale_hook=None) -> dict:
    """Full lifecycle: one item ON_FLOOR -> sold at checkout -> SETTLEMENT phase
    -> DRAFT settlement generated. Returns the context plus `settlement`.

    `pre_sale_hook(ctx)` runs after reaching SALE_ACTIVE and before the sale
    (e.g., to generate a settlement while the item is still ON_FLOOR).
    """
    ctx = setup_item_on_floor(
        price_cents=price_cents, consignor_name=consignor_name,
        item_overrides=item_overrides, markdown=markdown,
    )
    if pre_sale_hook is not None:
        pre_sale_hook(ctx)
    ctx["transaction"] = sell_item(ctx, tendered_cents=tendered_cents)
    start_settlement(ctx["event"]["id"])
    settlements = generate_settlements(ctx["event"]["id"])
    assert len(settlements) == 1, f"Expected one settlement, got {settlements}"
    ctx["settlement"] = settlements[0]
    return ctx
