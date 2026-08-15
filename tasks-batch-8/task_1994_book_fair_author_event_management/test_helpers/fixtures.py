"""Composite setup helpers — multi-step entity bootstraps.

Every helper builds its own state from scratch because the runner restarts the
server between tests. Uses get_success_data() so setup failures produce clear
errors rather than confusing assertion traces.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_party_payload,
    create_fair_payload,
    create_venue_slot_payload,
    create_agreement_payload,
    create_stock_line_payload,
    create_booking_payload,
    create_session_payload,
    create_ticket_payload,
    create_preorder_payload,
    create_sale_payload,
    create_return_authorization_payload,
    create_media_blast_payload,
)
from .test_users import (
    TEST_USERS,
    make_school_coordinator_headers,
    make_publisher_rep_headers,
    make_author_rep_headers,
    make_organizer_headers,
)


ORGANIZER = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]
LINESTAFF = TEST_USERS["linestaff_headers"]


# ---------------------------------------------------------------------------
# Tier 1: party scaffolding
# ---------------------------------------------------------------------------

def make_school(name="Ridgeview Elementary", email="pta@ridgeview.example"):
    """Create a SCHOOL party. Returns the party dict."""
    return get_success_data(api_client.create_party(
        create_party_payload(kind="SCHOOL", name=name, contact_email=email), ORGANIZER
    ))


def make_publisher(name="Maple Press", email="rep@maple.example"):
    """Create a PUBLISHER party."""
    return get_success_data(api_client.create_party(
        create_party_payload(kind="PUBLISHER", name=name, contact_email=email), ORGANIZER
    ))


def make_author(name="Jane Writer", email="agent@jane.example"):
    """Create an AUTHOR party."""
    return get_success_data(api_client.create_party(
        create_party_payload(kind="AUTHOR", name=name, contact_email=email), ORGANIZER
    ))


# ---------------------------------------------------------------------------
# Tier 2: fair lifecycle states
# ---------------------------------------------------------------------------

def make_fair(school_party_id, **overrides):
    """Create a fair in DRAFT."""
    payload = create_fair_payload(school_party_id=school_party_id, **overrides)
    return get_success_data(api_client.create_fair(payload, ORGANIZER))


def make_confirmed_venue_slot(fair_id, school_id, **overrides):
    """Create a VenueSlot (HELD) and have the owning SchoolCoordinator confirm it."""
    payload = create_venue_slot_payload(fair_id=fair_id, **overrides)
    slot = get_success_data(api_client.create_venue_slot(payload, ORGANIZER))
    get_success_data(api_client.confirm_venue_slot(
        slot["id"], make_school_coordinator_headers(school_id)
    ))
    return slot


def make_fair_scheduled(school_id, **fair_overrides):
    """Fair in SCHEDULED with one confirmed slot."""
    fair = make_fair(school_id, **fair_overrides)
    # PRD section 2.9: the slot's venue_key must equal the linked fair's.
    make_confirmed_venue_slot(fair["id"], school_id, venue_key=fair["venue_key"])
    get_success_data(api_client.schedule_fair(fair["id"], ORGANIZER))
    return get_success_data(api_client.get_fair(fair["id"], ORGANIZER))


def make_accepted_agreement(fair_id, publisher_id, **overrides):
    """Create an agreement and have the scoped publisher accept it. Returns the ACCEPTED agreement."""
    payload = create_agreement_payload(fair_id=fair_id, publisher_party_id=publisher_id, **overrides)
    agr = get_success_data(api_client.create_agreement(payload, ORGANIZER))
    get_success_data(api_client.accept_agreement(
        agr["id"], make_publisher_rep_headers(publisher_id)
    ))
    return get_success_data(api_client.get_agreement(agr["id"], ORGANIZER))


def make_fair_stocking(school_id, publisher_id, **fair_overrides):
    """Fair in STOCKING with an ACCEPTED agreement. Returns (fair, agreement)."""
    fair = make_fair_scheduled(school_id, **fair_overrides)
    agr = make_accepted_agreement(fair["id"], publisher_id)
    get_success_data(api_client.open_stocking(fair["id"], ORGANIZER))
    return get_success_data(api_client.get_fair(fair["id"], ORGANIZER)), agr


def make_delivered_stock_line(fair_id, agreement_id, qty_committed=10, qty_delivered=10, **overrides):
    """QUOTED -> COMMITTED -> DELIVERED."""
    line = get_success_data(api_client.create_stock_line(
        create_stock_line_payload(
            fair_id=fair_id, agreement_id=agreement_id,
            qty_committed=qty_committed, **overrides
        ),
        ORGANIZER,
    ))
    get_success_data(api_client.commit_stock_line(line["id"], ORGANIZER))
    get_success_data(api_client.deliver_stock_line(
        line["id"], {"qty_delivered": qty_delivered}, ORGANIZER
    ))
    return get_success_data(api_client.get_stock_line(line["id"], ORGANIZER))


def make_fair_open(school_id, publisher_id, line_specs=None, **fair_overrides):
    """Fair fully progressed to OPEN. line_specs is a list of dicts each with
    qty_committed / qty_delivered / line_type / list_price_cents / title / isbn;
    when None a single FRONTLIST line of qty 10 is used.
    Returns (fair, agreement, [stock_line, ...])."""
    fair, agr = make_fair_stocking(school_id, publisher_id, **fair_overrides)
    if line_specs is None:
        line_specs = [{}]
    lines = []
    for spec in line_specs:
        spec = dict(spec)
        qty_committed = spec.pop("qty_committed", 10)
        qty_delivered = spec.pop("qty_delivered", qty_committed)
        lines.append(make_delivered_stock_line(
            fair["id"], agr["id"],
            qty_committed=qty_committed, qty_delivered=qty_delivered, **spec
        ))
    get_success_data(api_client.open_fair(fair["id"], ORGANIZER))
    return get_success_data(api_client.get_fair(fair["id"], ORGANIZER)), agr, lines


# ---------------------------------------------------------------------------
# Tier 3: bookings / sessions / tickets
# ---------------------------------------------------------------------------

def make_confirmed_booking(fair_id, author_id, **overrides):
    """Booking accepted by the scoped AuthorRep -> CONFIRMED."""
    booking = get_success_data(api_client.create_booking(
        create_booking_payload(fair_id=fair_id, author_party_id=author_id, **overrides),
        ORGANIZER,
    ))
    get_success_data(api_client.accept_booking(
        booking["id"], make_author_rep_headers(author_id)
    ))
    return get_success_data(api_client.get_booking(booking["id"], ORGANIZER))


def make_travel_booked_booking(fair_id, author_id, travel_actual_cents=1500, **overrides):
    """Booking CONFIRMED then travel recorded -> TRAVEL_BOOKED."""
    booking = make_confirmed_booking(fair_id, author_id, **overrides)
    get_success_data(api_client.book_travel(
        booking["id"], {"travel_actual_cents": travel_actual_cents}, ORGANIZER
    ))
    return get_success_data(api_client.get_booking(booking["id"], ORGANIZER))


def make_session(booking_id, fair_id, **overrides):
    """Create a SCHEDULED signing session."""
    return get_success_data(api_client.create_session(
        create_session_payload(booking_id=booking_id, fair_id=fair_id, **overrides),
        ORGANIZER,
    ))


def make_open_session_with_tickets(session, num_tickets, holder_prefix="Kid"):
    """Open the session for signing (clock must already be in window) and issue N tickets."""
    get_success_data(api_client.open_signing(session["id"], LINESTAFF))
    tickets = []
    for i in range(num_tickets):
        t = get_success_data(api_client.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name=f"{holder_prefix} {i+1}"),
            LINESTAFF,
        ))
        tickets.append(t)
    return tickets


# ---------------------------------------------------------------------------
# Tier 4: reconciliation flows
# ---------------------------------------------------------------------------

def make_reconciling_fair(school_id, publisher_id, line_specs=None, sales=None,
                          fair_overrides=None):
    """Fair progressed OPEN -> RECONCILING with one delivered FRONTLIST line
    (default qty 10) and zero or more tendered sales. Returns a dict carrying
    fair, agreement, lines, reconciliation, organizer-id used at close-sales."""
    fair_overrides = fair_overrides or {}
    fair, agr, lines = make_fair_open(school_id, publisher_id, line_specs=line_specs, **fair_overrides)
    if sales:
        for s in sales:
            sale = get_success_data(api_client.create_sale(
                create_sale_payload(fair_id=fair["id"], lines=s["lines"]), CASHIER
            ))
            get_success_data(api_client.tender_sale(
                sale["id"], {"tendered_amount_cents": s["tendered_amount_cents"]}, CASHIER
            ))
    closer_headers = make_organizer_headers("org_lead_1")
    get_success_data(api_client.close_sales(fair["id"], closer_headers))
    recon_resp = api_client.list_reconciliations(ORGANIZER, params={"fair_id": fair["id"]})
    data = get_success_data(recon_resp)
    recon = data[0]
    return {
        "fair": get_success_data(api_client.get_fair(fair["id"], ORGANIZER)),
        "agreement": agr,
        "lines": lines,
        "reconciliation": recon,
        "closer_user_id": "org_lead_1",
    }


def enter_counts_and_submit(recon_id, line_quantities, organizer_headers=None):
    """Post counts (each pair stock_line_id -> qty_on_hand) and submit-review.
    Returns the VARIANCE_REVIEW reconciliation."""
    organizer_headers = organizer_headers or ORGANIZER
    recon = get_success_data(api_client.get_reconciliation(recon_id, organizer_headers))
    get_success_data(api_client.post_counts(
        recon_id,
        {
            "lines": [
                {"stock_line_id": line_id, "qty_on_hand": qty}
                for line_id, qty in line_quantities.items()
            ],
            "expected_reconciliation_version": recon["version"],
        },
        organizer_headers,
    ))
    return get_success_data(api_client.submit_review(recon_id, organizer_headers))


def approve_reconciliation_as_other(recon_id, approver_user_id="org_lead_2"):
    """Approve a reconciliation with a DIFFERENT organizer than the closer (SoD)."""
    return get_success_data(api_client.approve_reconciliation(
        recon_id, make_organizer_headers(approver_user_id)
    ))


def make_accepted_reconciliation(school_id, publisher_id, line_specs=None, sales=None,
                                 counted_quantities=None, fair_overrides=None):
    """Fair through RECONCILING with the reconciliation fully ACCEPTED.
    counted_quantities: dict {stock_line_id_or_index: qty_on_hand}; by default each
    line's expected_on_hand is counted exactly (zero variance).
    Returns dict with fair, agreement, lines, reconciliation."""
    ctx = make_reconciling_fair(
        school_id, publisher_id, line_specs=line_specs, sales=sales, fair_overrides=fair_overrides
    )
    recon_id = ctx["reconciliation"]["id"]
    # Build the counted quantities map
    if counted_quantities is None:
        recon_now = get_success_data(api_client.get_reconciliation(recon_id, ORGANIZER))
        line_quantities = {
            entry["stock_line_id"]: entry["expected_on_hand"]
            for entry in recon_now["provisional_lines"]
        }
    else:
        line_quantities = {}
        for key, qty in counted_quantities.items():
            if isinstance(key, int):
                line_quantities[ctx["lines"][key]["id"]] = qty
            else:
                line_quantities[key] = qty
    enter_counts_and_submit(recon_id, line_quantities)
    approve_reconciliation_as_other(recon_id)
    get_success_data(api_client.submit_reconciliation(recon_id, ORGANIZER))
    get_success_data(api_client.accept_reconciliation(
        recon_id, make_publisher_rep_headers(publisher_id)
    ))
    ctx["reconciliation"] = get_success_data(api_client.get_reconciliation(recon_id, ORGANIZER))
    ctx["fair"] = get_success_data(api_client.get_fair(ctx["fair"]["id"], ORGANIZER))
    return ctx
