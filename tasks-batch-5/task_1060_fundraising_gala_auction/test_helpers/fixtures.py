"""Composite setup helpers for multi-step gala test prerequisites.

Every helper uses get_success_data() (the lenient validator) so a broken
precondition surfaces as a clear "Setup failed" rather than as a confusing
assertion deep inside a test. The database is empty at the start of every test,
so every helper builds its own world from scratch.

Identity threading: Bidder and Sponsor are entity-backed roles, so ownership-
gated calls here always thread the real entity id through make_bidder_headers()
/ make_sponsor_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    FINANCE_USER_ID,
    FINANCE_USER_ID_2,
    TEST_DEFAULTS,
)
from .factories import (
    create_auction_item_payload,
    create_bid_payload,
    create_bidder_payload,
    create_event_payload,
    create_invoice_payload,
    create_paddle_raise_payload,
    create_payment_payload,
    create_pledge_payload,
    create_program_ad_payload,
    create_sponsor_payload,
    create_table_hold_payload,
    create_table_payload,
    create_ticket_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_bidder_headers,
    make_finance_headers,
    make_sponsor_headers,
)

ORGANIZER = TEST_USERS["organizer_headers"]
AUCTION_MANAGER = TEST_USERS["auction_manager_headers"]
FINANCE = TEST_USERS["finance_headers"]
FINANCE_2 = TEST_USERS["finance_headers_2"]

DEFAULT_CLOCK = TEST_DEFAULTS["PRE_CUTOFF_CLOCK_UTC"]


# ─── Logical clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ORGANIZER))


# ─── Plain reads ────────────────────────────────────────────────────────────

def read_event(event_id):
    return get_success_data(api_client.get_event(event_id, ORGANIZER))


def read_table(table_id):
    return get_success_data(api_client.get_table(table_id, ORGANIZER))


def read_hold(hold_id):
    return get_success_data(api_client.get_table_hold(hold_id, ORGANIZER))


def read_bidder(bidder_id):
    return get_success_data(api_client.get_bidder(bidder_id, ORGANIZER))


def read_sponsor(sponsor_id):
    return get_success_data(api_client.get_sponsor(sponsor_id, ORGANIZER))


def read_program_ad(ad_id):
    return get_success_data(api_client.get_program_ad(ad_id, ORGANIZER))


def read_ticket_order(order_id):
    return get_success_data(api_client.get_ticket_order(order_id, ORGANIZER))


def read_auction_item(item_id):
    return get_success_data(api_client.get_auction_item(item_id, AUCTION_MANAGER))


def read_bid(bid_id):
    return get_success_data(api_client.get_bid(bid_id, AUCTION_MANAGER))


def read_paddle_raise(paddle_raise_id):
    return get_success_data(api_client.get_paddle_raise(paddle_raise_id, ORGANIZER))


def read_pledge(pledge_id):
    return get_success_data(api_client.get_pledge(pledge_id, FINANCE))


def read_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, FINANCE))


def read_payment(payment_id):
    return get_success_data(api_client.get_payment(payment_id, FINANCE))


def read_receipt(receipt_id):
    return get_success_data(api_client.get_receipt(receipt_id, FINANCE))


def read_reconciliation_run(run_id):
    return get_success_data(api_client.get_reconciliation_run(run_id, FINANCE))


def event_version(event_id) -> int:
    """The event's current version, as a client would last have observed it."""
    return read_event(event_id)["version"]


# ─── Tier 1: single-step creates ────────────────────────────────────────────

def create_event(**overrides) -> dict:
    return get_success_data(
        api_client.create_event(create_event_payload(**overrides), ORGANIZER)
    )


def add_table(event_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_table(event_id, create_table_payload(**overrides), ORGANIZER)
    )


def register_bidder(event_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_bidder(create_bidder_payload(event_id, **overrides), ORGANIZER)
    )


def register_sponsor(event_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsor(create_sponsor_payload(event_id, **overrides), ORGANIZER)
    )


def publish_event(event_id) -> dict:
    return get_success_data(api_client.publish_event(event_id, ORGANIZER))


def go_live(event_id) -> dict:
    return get_success_data(api_client.go_live_event(event_id, ORGANIZER))


def start_settlement(event_id) -> dict:
    return get_success_data(api_client.start_settlement(event_id, ORGANIZER))


# ─── Tier 2: event setup ────────────────────────────────────────────────────

BIDDER_SPECS = [
    {"display_name": "Ada Lovelace", "email": "ada@example.org", "paddle_number": 101},
    {"display_name": "Grace Hopper", "email": "grace@example.org", "paddle_number": 102},
    {"display_name": "Cyd Card-less", "email": "cyd@example.org", "paddle_number": 103},
]


def setup_published_event(
    clock=DEFAULT_CLOCK,
    bidder_count=1,
    payment_methods_on_file=True,
    table_overrides=None,
    **event_overrides,
) -> dict:
    """Clock set, event created with one table and N registered guests, then
    published. Returns {"event", "table", "bidders"}.

    payment_methods_on_file may be a single bool applied to every guest or a
    list of bools, one per guest.
    """
    set_clock(clock)
    event = create_event(**event_overrides)
    table = add_table(event["id"], **(table_overrides or {}))

    if isinstance(payment_methods_on_file, bool):
        cards = [payment_methods_on_file] * bidder_count
    else:
        cards = list(payment_methods_on_file)

    bidders = []
    for index in range(bidder_count):
        spec = dict(BIDDER_SPECS[index])
        spec["payment_method_on_file"] = cards[index]
        bidders.append(register_bidder(event["id"], **spec))

    event = publish_event(event["id"])
    return {"event": event, "table": table, "bidders": bidders}


def setup_draft_event(clock=DEFAULT_CLOCK, **event_overrides) -> dict:
    """Clock set and a bare DRAFT event created — no table, no guests."""
    set_clock(clock)
    return create_event(**event_overrides)


# ─── Tier 3: auction lots and bids ──────────────────────────────────────────

def create_lot(event_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_auction_item(
            create_auction_item_payload(event_id, **overrides), AUCTION_MANAGER
        )
    )


def open_lot(item_id) -> dict:
    return get_success_data(api_client.open_auction_item(item_id, AUCTION_MANAGER))


def close_lot(item_id) -> dict:
    return get_success_data(api_client.close_auction_item(item_id, AUCTION_MANAGER))


def create_open_lot(event_id, **overrides) -> dict:
    """Create a lot and walk it DRAFT -> OPEN."""
    lot = create_lot(event_id, **overrides)
    return open_lot(lot["id"])


def place_bid(item_id, bidder_id, amount_cents, **overrides) -> dict:
    """Place a bid as the acting guest, threading their own id into the headers."""
    return get_success_data(
        api_client.place_bid(
            item_id,
            create_bid_payload(bidder_id, amount_cents, **overrides),
            make_bidder_headers(bidder_id),
        )
    )


def setup_open_lot_scenario(clock=DEFAULT_CLOCK, bidder_count=1, **lot_overrides) -> dict:
    """Published event + registered guests with cards + one OPEN lot.

    Returns {"event", "table", "bidders", "lot"}.
    """
    env = setup_published_event(clock=clock, bidder_count=bidder_count)
    env["lot"] = create_open_lot(env["event"]["id"], **lot_overrides)
    return env


def setup_proxy_leader_scenario(clock=DEFAULT_CLOCK, **lot_overrides) -> dict:
    """Published event, two guests holding cards, and one OPEN lot with a
    starting bid of 10000 and a minimum increment of 500. Guest A leads on a
    proxy ceiling of 20000 over a placed 10000; guest B has placed 12000 with
    no proxy, so the proxy-settled leading amount is 12500.

    Returns {"event", "table", "bidders", "lot", "bid_a", "bid_b"}.
    """
    env = setup_open_lot_scenario(clock=clock, bidder_count=2, **lot_overrides)
    guest_a, guest_b = env["bidders"]
    env["bid_a"] = place_bid(
        env["lot"]["id"], guest_a["id"], 10_000, proxy_max_cents=20_000
    )
    env["bid_b"] = place_bid(env["lot"]["id"], guest_b["id"], 12_000)
    env["lot"] = read_auction_item(env["lot"]["id"])
    return env


def setup_live_channel_lots(clock="2026-07-05T19:30:00Z") -> dict:
    """Published event carrying three LIVE lots that all occupy stage-channel
    sequence 1 on 2026-07-05: A over [18:00, 20:00), C over [19:00, 21:00) and
    B over [20:00, 22:00). Lot A is already OPEN.

    Returns {"event", "table", "lot_a", "lot_b", "lot_c"}.
    """
    env = setup_published_event(clock=clock, bidder_count=0)
    event_id = env["event"]["id"]
    windows = {
        "lot_a": ("Lot A", "2026-07-05T18:00:00Z", "2026-07-05T20:00:00Z"),
        "lot_c": ("Lot C", "2026-07-05T19:00:00Z", "2026-07-05T21:00:00Z"),
        "lot_b": ("Lot B", "2026-07-05T20:00:00Z", "2026-07-05T22:00:00Z"),
    }
    for key, (title, open_at, close_at) in windows.items():
        env[key] = create_lot(
            event_id,
            title=title,
            item_type="LIVE",
            open_at_utc=open_at,
            close_at_utc=close_at,
            live_lot_sequence=1,
        )
    env["lot_a"] = open_lot(env["lot_a"]["id"])
    return env


def setup_awarded_lot_scenario(
    clock=DEFAULT_CLOCK, bid_amount_cents=12_500, invoice_overrides=None, **lot_overrides
) -> dict:
    """Published event + one OPEN lot carrying a single ACTIVE bid from the
    first guest, then closed so the lot is AWARDED and an invoice exists.

    When invoice_overrides is given, an OPEN invoice for that guest is created
    before the close so the auction line lands on it.

    Returns {"event", "table", "bidders", "lot", "bid", "invoice_id"}.
    """
    env = setup_open_lot_scenario(clock=clock, bidder_count=1, **lot_overrides)
    bidder = env["bidders"][0]

    if invoice_overrides is not None:
        env["invoice"] = open_invoice(
            env["event"]["id"], bidder["id"], **invoice_overrides
        )

    env["bid"] = place_bid(env["lot"]["id"], bidder["id"], bid_amount_cents)
    env["lot"] = close_lot(env["lot"]["id"])
    env["invoice_id"] = env["lot"]["invoice_id"]
    return env


# ─── Tier 4: checkout, payments and receipts ────────────────────────────────

def open_invoice(event_id, bidder_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(event_id, bidder_id, **overrides), FINANCE
        )
    )


def finalize_invoice(invoice_id) -> dict:
    return get_success_data(api_client.finalize_invoice(invoice_id, FINANCE))


def capture_payment(invoice_id, amount_cents, user_id=FINANCE_USER_ID, **overrides) -> dict:
    """Capture a payment as the named FinanceOfficer operator."""
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(invoice_id, amount_cents, **overrides),
            make_finance_headers(user_id),
        )
    )


def void_payment(payment_id, reason="Card chargeback received from processor.",
                 user_id=FINANCE_USER_ID_2) -> dict:
    return get_success_data(
        api_client.void_payment(payment_id, reason, make_finance_headers(user_id))
    )


def issue_receipt(invoice_id) -> dict:
    return get_success_data(api_client.create_receipt(invoice_id, FINANCE))


def setup_finalized_invoice_scenario(
    clock=DEFAULT_CLOCK, bid_amount_cents=12_500, **lot_overrides
) -> dict:
    """AWARDED lot whose invoice has been finalized to PENDING_PAYMENT.

    Returns the awarded-lot scenario plus {"invoice"} at PENDING_PAYMENT.
    """
    env = setup_awarded_lot_scenario(
        clock=clock, bid_amount_cents=bid_amount_cents, **lot_overrides
    )
    env["invoice"] = finalize_invoice(env["invoice_id"])
    return env


def setup_paid_invoice_scenario(
    clock=DEFAULT_CLOCK,
    bid_amount_cents=12_500,
    captured_by=FINANCE_USER_ID,
    **lot_overrides,
) -> dict:
    """AWARDED lot on an invoice finalized and paid in full by `captured_by`.

    Returns the finalized scenario plus {"payment"} and a refreshed "invoice".
    """
    env = setup_finalized_invoice_scenario(
        clock=clock, bid_amount_cents=bid_amount_cents, **lot_overrides
    )
    env["payment"] = capture_payment(
        env["invoice_id"], env["invoice"]["balance_due_cents"], user_id=captured_by
    )
    env["invoice"] = read_invoice(env["invoice_id"])
    return env


# ─── Tier 4: tables, holds and ticket orders ────────────────────────────────

def place_hold(table_id, bidder_id, **overrides) -> dict:
    """Place a table hold. The organizer may act on any guest's behalf."""
    return get_success_data(
        api_client.create_table_hold(
            create_table_hold_payload(table_id, bidder_id, **overrides), ORGANIZER
        )
    )


def release_hold(hold_id) -> dict:
    return get_success_data(api_client.release_table_hold(hold_id, ORGANIZER))


def buy_ticket_order(event_id, bidder_id, table_id, **overrides) -> dict:
    """Buy a ticket order as the purchasing guest."""
    return get_success_data(
        api_client.create_ticket_order(
            create_ticket_order_payload(event_id, bidder_id, table_id, **overrides),
            make_bidder_headers(bidder_id),
        )
    )


def cancel_ticket_order(order_id) -> dict:
    return get_success_data(api_client.cancel_ticket_order(order_id, ORGANIZER))


# ─── Tier 4: appeal gifts and pledges ───────────────────────────────────────

def record_paddle_raise(event_id, bidder_id, level_cents, **overrides) -> dict:
    return get_success_data(
        api_client.create_paddle_raise(
            create_paddle_raise_payload(event_id, bidder_id, level_cents, **overrides),
            AUCTION_MANAGER,
        )
    )


def record_pledge(event_id, bidder_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pledge(
            create_pledge_payload(event_id, bidder_id, **overrides), FINANCE
        )
    )


def record_installment(pledge_id, amount_cents) -> dict:
    return get_success_data(
        api_client.record_installment(pledge_id, amount_cents, FINANCE)
    )


def setup_partially_fulfilled_pledge(
    clock=DEFAULT_CLOCK,
    total_amount_cents=300_000,
    received_amount_cents=50_000,
    publish=True,
    **pledge_overrides,
) -> dict:
    """Event with one guest holding a pledge that has taken partial cash.

    Returns {"event", "table", "bidders", "pledge"}.
    """
    if publish:
        env = setup_published_event(clock=clock, bidder_count=1)
    else:
        set_clock(clock)
        event = create_event()
        env = {
            "event": event,
            "table": None,
            "bidders": [register_bidder(event["id"], **BIDDER_SPECS[0],
                                        payment_method_on_file=True)],
        }
    pledge = record_pledge(
        env["event"]["id"],
        env["bidders"][0]["id"],
        total_amount_cents=total_amount_cents,
        **pledge_overrides,
    )
    if received_amount_cents:
        pledge = record_installment(pledge["id"], received_amount_cents)
    env["pledge"] = pledge
    return env


# ─── Tier 4: sponsorships and program ads ───────────────────────────────────

def confirm_sponsor(sponsor_id, paid_amount_cents) -> dict:
    return get_success_data(
        api_client.confirm_sponsor(sponsor_id, paid_amount_cents, FINANCE)
    )


def submit_program_ad(sponsor_id, event_id, **overrides) -> dict:
    """Submit an ad as the sponsoring organization itself."""
    return get_success_data(
        api_client.create_program_ad(
            create_program_ad_payload(sponsor_id, event_id, **overrides),
            make_sponsor_headers(sponsor_id),
        )
    )


def review_program_ad(ad_id, decision, notes=None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.review_program_ad(ad_id, payload, ORGANIZER))


def resubmit_program_ad(ad_id, sponsor_id, artwork_ref) -> dict:
    return get_success_data(
        api_client.resubmit_program_ad(
            ad_id, artwork_ref, make_sponsor_headers(sponsor_id)
        )
    )


def setup_sponsor_with_ad(clock=DEFAULT_CLOCK, ad_state="SUBMITTED",
                          confirm_cash=None, **sponsor_overrides) -> dict:
    """DRAFT event + one sponsor + one program ad walked to `ad_state`.

    ad_state is one of SUBMITTED, IN_REVIEW, CHANGES_REQUESTED or APPROVED.
    confirm_cash, when given, records that much sponsorship cash first.

    Returns {"event", "sponsor", "ad"}.
    """
    event = setup_draft_event(clock=clock)
    sponsor = register_sponsor(event["id"], **sponsor_overrides)
    if confirm_cash is not None:
        sponsor = confirm_sponsor(sponsor["id"], confirm_cash)

    ad = submit_program_ad(sponsor["id"], event["id"])
    if ad_state in ("IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"):
        ad = review_program_ad(ad["id"], "BEGIN_REVIEW")
    if ad_state == "CHANGES_REQUESTED":
        ad = review_program_ad(ad["id"], "REQUEST_CHANGES", notes="Logo resolution too low.")
    if ad_state == "APPROVED":
        ad = review_program_ad(ad["id"], "APPROVE")

    return {"event": event, "sponsor": sponsor, "ad": ad}


def setup_ad_at_revision_budget(clock=DEFAULT_CLOCK) -> dict:
    """An ad that has already completed two resubmissions and is back in
    CHANGES_REQUESTED, so its revision budget is exhausted.

    Returns {"event", "sponsor", "ad"}.
    """
    env = setup_sponsor_with_ad(clock=clock, ad_state="CHANGES_REQUESTED",
                                ad_size="HALF_PAGE")
    sponsor_id = env["sponsor"]["id"]
    ad_id = env["ad"]["id"]

    resubmit_program_ad(ad_id, sponsor_id, "art-v2")
    review_program_ad(ad_id, "BEGIN_REVIEW")
    review_program_ad(ad_id, "REQUEST_CHANGES", notes="Still low contrast.")
    env["ad_after_second_revision"] = resubmit_program_ad(ad_id, sponsor_id, "art-v3")
    review_program_ad(ad_id, "BEGIN_REVIEW")
    env["ad"] = review_program_ad(ad_id, "REQUEST_CHANGES", notes="Third pass needed.")
    return env


# ─── Tier 5: reconciliation and finalization ────────────────────────────────

def prepare_run(event_id, revenue_basis="BOOKED", user_id=FINANCE_USER_ID,
                expected_event_version=None) -> dict:
    """Prepare a reconciliation run, reading the event's current version first
    unless the caller pins a (possibly stale) one."""
    if expected_event_version is None:
        expected_event_version = event_version(event_id)
    payload = {
        "expected_event_version": expected_event_version,
        "revenue_basis": revenue_basis,
    }
    return get_success_data(
        api_client.create_reconciliation_run(
            event_id, payload, make_finance_headers(user_id)
        )
    )


def finalize_run(run_id, user_id=FINANCE_USER_ID_2, variance_override_note=None) -> dict:
    payload = {}
    if variance_override_note is not None:
        payload["variance_override_note"] = variance_override_note
    return get_success_data(
        api_client.finalize_reconciliation_run(
            run_id, payload, make_finance_headers(user_id)
        )
    )


def reopen_run(run_id, user_id=FINANCE_USER_ID_2) -> dict:
    return get_success_data(
        api_client.reopen_reconciliation_run(run_id, make_finance_headers(user_id))
    )


def setup_frozen_event(clock=DEFAULT_CLOCK, bidder_count=1, **event_overrides) -> dict:
    """Published event with no revenue at all, carrying a run prepared by fin-1
    and finalized by fin-2, so the event's posture is FROZEN.

    Returns {"event", "table", "bidders", "run"}.
    """
    env = setup_published_event(
        clock=clock, bidder_count=bidder_count, **event_overrides
    )
    run = prepare_run(env["event"]["id"], user_id=FINANCE_USER_ID)
    env["run"] = finalize_run(run["id"], user_id=FINANCE_USER_ID_2)
    env["event"] = read_event(env["event"]["id"])
    return env


def setup_restricted_event(clock=DEFAULT_CLOCK, bidder_count=1) -> dict:
    """An event walked DRAFT -> PUBLISHED -> LIVE -> SETTLING, whose single lot
    was auto-opened by go-live and then closed as PASSED so no lot remains open.
    Posture is RESTRICTED.

    Returns {"event", "table", "bidders", "lot"}.
    """
    set_clock(clock)
    event = create_event()
    table = add_table(event["id"])
    bidders = [
        register_bidder(event["id"], **dict(BIDDER_SPECS[index],
                                            payment_method_on_file=True))
        for index in range(bidder_count)
    ]
    lot = create_lot(event["id"])
    publish_event(event["id"])
    go_live(event["id"])
    lot = close_lot(lot["id"])
    event = start_settlement(event["id"])
    return {"event": event, "table": table, "bidders": bidders, "lot": lot}
