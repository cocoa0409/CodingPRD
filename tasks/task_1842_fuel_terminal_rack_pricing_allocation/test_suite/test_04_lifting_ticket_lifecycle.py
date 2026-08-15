"""Lifting-ticket lifecycle claims: the post/reverse cycle, compensating
inventory and aggregation effects, suspension cascade, invalid exits, and
read-after-write consistency."""
from test_helpers import (
    ALLOC,
    BILLING,
    OPER,
    ApiErrorId,
    create_posted_ticket,
    get_customer,
    get_lifting_right,
    get_lifting_ticket,
    get_supply_contract,
    get_terminal,
    post_bol,
    reserve_ticket,
    set_clock,
    setup_liftable_right,
    validate_error,
    validate_success,
)

DIESEL_TAXES = [
    ("FEDERAL", "US", "DIESEL", 24),
    ("STATE", "TX", "DIESEL", 20),
]


class TestBolReverseCycle:
    def test_post_reverse_repost_inventory_walk(self, api):
        """PRD §3.7: "A reversal returns the ticket `BOL_ISSUED` → `RESERVED`
        and unwinds the posting symmetrically — the terminal's
        `inventory_gallons` is credited back, the right's
        `lifted_today_gallons` is decremented and its `reserved_gallons`
        restored, the contract's `lifted_to_date_gallons` is decremented, and
        any exchange agreement counter previously incremented is decremented
        in turn."

        Design: Difficulty/non_linear_state_machine/lifting_ticket_bol_reverse_cycle
        """
        env = setup_liftable_right(
            inventory_gallons=50000, tax_rules=DIESEL_TAXES,
            posted_rack_cents_per_gal=280,
        )
        ticket = reserve_ticket(env["right"]["id"], 5000)

        post_bol(ticket["id"])
        assert get_terminal(env["terminal"]["id"])["inventory_gallons"] == 45000

        validate_success(api.reverse_bol(ticket["id"], OPER))
        assert get_terminal(env["terminal"]["id"])["inventory_gallons"] == 50000

        reposted = post_bol(ticket["id"])
        assert reposted["status"] == "BOL_ISSUED"
        assert get_terminal(env["terminal"]["id"])["inventory_gallons"] == 45000

    def test_cycle_nets_right_counters_to_single_post(self, api):
        """PRD §3.6: "the right's `lifted_today_gallons` grows and its
        `reserved_gallons` shrinks by the same amount".
        PRD §3.7: "A reversal returns the ticket `BOL_ISSUED` → `RESERVED`
        and unwinds the posting symmetrically — the terminal's
        `inventory_gallons` is credited back, the right's
        `lifted_today_gallons` is decremented and its `reserved_gallons`
        restored, the contract's `lifted_to_date_gallons` is decremented, and
        any exchange agreement counter previously incremented is decremented
        in turn."

        Design: Difficulty/non_linear_state_machine/lifting_ticket_bol_reverse_cycle
        """
        env = setup_liftable_right(
            inventory_gallons=50000, tax_rules=DIESEL_TAXES,
            posted_rack_cents_per_gal=280,
        )
        ticket = reserve_ticket(env["right"]["id"], 5000)
        post_bol(ticket["id"])
        validate_success(api.reverse_bol(ticket["id"], OPER))
        post_bol(ticket["id"])

        right = get_lifting_right(env["right"]["id"])
        assert right["lifted_today_gallons"] == 5000, (
            "post -> reverse -> post must net to one posted lifting"
        )
        assert right["reserved_gallons"] == 0
        assert get_lifting_ticket(ticket["id"])["status"] == "BOL_ISSUED"


class TestInventoryConservation:
    def test_post_then_reverse_leaves_zero_drift(self, api):
        """PRD §3.6: "The terminal's `inventory_gallons` is debited by the
        requested gallons".
        PRD §3.7: "A reversal returns the ticket `BOL_ISSUED` → `RESERVED`
        and unwinds the posting symmetrically — the terminal's
        `inventory_gallons` is credited back, the right's
        `lifted_today_gallons` is decremented and its `reserved_gallons`
        restored, the contract's `lifted_to_date_gallons` is decremented, and
        any exchange agreement counter previously incremented is decremented
        in turn."

        Design: Difficulty/compensating_invariant/inventory_gallons_conserved_over_post_reverse_cycle
        """
        env = setup_liftable_right(
            inventory_gallons=10000,
            tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
            posted_rack_cents_per_gal=280,
        )
        ticket = reserve_ticket(env["right"]["id"], 3000)

        post_bol(ticket["id"])
        mid = get_terminal(env["terminal"]["id"])["inventory_gallons"]
        assert mid == 7000

        validate_success(api.reverse_bol(ticket["id"], OPER))
        end = get_terminal(env["terminal"]["id"])["inventory_gallons"]
        assert end == 10000, (
            f"post+reverse must conserve inventory exactly (drift 0), got {end}"
        )

    def test_reverse_restores_right_and_contract_counters(self, api):
        """PRD §3.7: "A reversal returns the ticket `BOL_ISSUED` → `RESERVED`
        and unwinds the posting symmetrically — the terminal's
        `inventory_gallons` is credited back, the right's
        `lifted_today_gallons` is decremented and its `reserved_gallons`
        restored, the contract's `lifted_to_date_gallons` is decremented, and
        any exchange agreement counter previously incremented is decremented
        in turn."

        Design: Difficulty/compensating_invariant/inventory_gallons_conserved_over_post_reverse_cycle
        """
        env = setup_liftable_right(
            inventory_gallons=10000,
            tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
            posted_rack_cents_per_gal=280,
        )
        ticket = reserve_ticket(env["right"]["id"], 3000)
        post_bol(ticket["id"])

        right = get_lifting_right(env["right"]["id"])
        assert right["lifted_today_gallons"] == 3000
        assert right["reserved_gallons"] == 0
        assert get_supply_contract(env["contract"]["id"])["lifted_to_date_gallons"] == 3000

        validate_success(api.reverse_bol(ticket["id"], OPER))

        right = get_lifting_right(env["right"]["id"])
        assert right["lifted_today_gallons"] == 0
        assert right["reserved_gallons"] == 3000
        assert get_supply_contract(env["contract"]["id"])["lifted_to_date_gallons"] == 0


def test_suspend_cancels_reserved_tickets_and_credits_exposure(api):
    """PRD §3.4: "Suspension cascades through the right's open pipeline:
    every lifting ticket of that right still in `RESERVED` transitions to
    `CANCELLED`, each cancelled ticket's gallons are credited back out of the
    right's `reserved_gallons`, and the customer's
    `open_lifting_exposure_cents` is credited by the sum of those tickets'
    `gross_cents`."

    Design: Corner/state_machines/lifting_right_suspend_cascades_reserved_tickets_to_cancelled
    """
    env = setup_liftable_right(
        tax_rules=DIESEL_TAXES, posted_rack_cents_per_gal=262,
    )
    ticket = reserve_ticket(env["right"]["id"], 1000)
    assert get_customer(env["customer"]["id"])["open_lifting_exposure_cents"] > 0

    validate_success(api.suspend_lifting_right(env["right"]["id"], ALLOC))

    right = get_lifting_right(env["right"]["id"])
    assert right["status"] == "SUSPENDED"
    assert right["reserved_gallons"] == 0
    assert get_lifting_ticket(ticket["id"])["status"] == "CANCELLED"
    assert get_customer(env["customer"]["id"])["open_lifting_exposure_cents"] == 0


def test_cancel_from_bol_issued_rejected(api):
    """PRD §3.7: "Cancellation, by a `TerminalOperator`, applies only while
    the ticket is `RESERVED` (`ERR_TICKET_NOT_RESERVED` otherwise): the
    right's `reserved_gallons` is relieved by the requested gallons, the
    customer's `open_lifting_exposure_cents` drops by the ticket's
    `gross_cents`, the ticket transitions `RESERVED` → `CANCELLED`, and a
    `CANCELLED` BOL event is appended."

    Design: Corner/state_machines/ticket_cancel_from_bol_issued_returns_invalid_state
    """
    env = setup_liftable_right(
        inventory_gallons=50000,
        tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
        posted_rack_cents_per_gal=280,
    )
    ticket = create_posted_ticket(env["right"]["id"], 1000)
    assert ticket["status"] == "BOL_ISSUED"

    resp = api.cancel_lifting_ticket(ticket["id"], OPER)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_RESERVED, 409)
    assert get_lifting_ticket(ticket["id"])["status"] == "BOL_ISSUED"


def test_invoice_from_reserved_rejected(api):
    """PRD §3.7: "Invoicing is the `BillingClerk`'s finalization: the ticket
    must be `BOL_ISSUED` (`ERR_TICKET_NOT_BOL_ISSUED` otherwise), transitions
    `BOL_ISSUED` → `INVOICED`, and the customer's
    `open_lifting_exposure_cents` drops by the ticket's `gross_cents`,
    closing out that load's claim on the credit line."

    Design: Corner/state_machines/invoice_from_reserved_returns_invalid_state
    """
    env = setup_liftable_right()
    ticket = reserve_ticket(env["right"]["id"], 100)

    resp = api.invoice_lifting_ticket(ticket["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_BOL_ISSUED, 409)
    assert get_lifting_ticket(ticket["id"])["status"] == "RESERVED"


def test_post_bol_without_published_price_rejected(api):
    """PRD §3.6: "and a `PUBLISHED` price schedule must cover the terminal,
    product, and the logical clock's date (`ERR_NO_PUBLISHED_PRICE`,
    HTTP 422)."

    Design: Corner/validations/post_bol_without_published_price_returns_error
    """
    env = setup_liftable_right(
        inventory_gallons=50000,
        tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
        posted_rack_cents_per_gal=280,
        effective_date="2026-08-01",
    )
    ticket = reserve_ticket(env["right"]["id"], 100)

    # Next logical day begins; nothing is published for 2026-08-02.
    set_clock("2026-08-02T08:00:00Z")
    resp = api.post_bol(ticket["id"], OPER)
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_PRICE, 422)
    assert get_lifting_ticket(ticket["id"])["status"] == "RESERVED"


def test_reverse_bol_after_window_rejected(api):
    """PRD §3.7: "Reversal is the compensating action for a mis-posted load,
    and the clock bounds it: reversal must execute within 24 logical hours of
    the posting call, else `ERR_REVERSAL_WINDOW_EXPIRED` (HTTP 422), and the
    ticket must be `BOL_ISSUED`, else `ERR_TICKET_NOT_BOL_ISSUED`
    (HTTP 409)."

    Design: Corner/validations/reverse_bol_after_window_returns_error
    """
    env = setup_liftable_right(
        inventory_gallons=50000,
        tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
        posted_rack_cents_per_gal=280,
        effective_date="2026-08-01",
    )
    ticket = create_posted_ticket(env["right"]["id"], 1000)

    # 25 hours and one second past the 2026-08-01T08:00:00Z posting.
    set_clock("2026-08-02T09:00:01Z")
    resp = api.reverse_bol(ticket["id"], OPER)
    validate_error(resp, ApiErrorId.ERR_REVERSAL_WINDOW_EXPIRED, 422)
    assert get_lifting_ticket(ticket["id"])["status"] == "BOL_ISSUED"


def test_post_bol_inventory_visible_immediately(api):
    """PRD §3.6: "The terminal's `inventory_gallons` is debited by the
    requested gallons; the right's `lifted_today_gallons` grows and its
    `reserved_gallons` shrinks by the same amount; the governing contract's
    `lifted_to_date_gallons` grows by it; and when an `ACTIVE` exchange
    agreement matches the terminal and product, its
    `delivered_this_month_gallons` grows too."

    Design: Corner/consistency_model/immediate_consistency_post_bol_inventory_visible_in_same_response
    """
    env = setup_liftable_right(
        inventory_gallons=10000,
        tax_rules=[("FEDERAL", "US", "DIESEL", 24)],
        posted_rack_cents_per_gal=280,
    )
    ticket = reserve_ticket(env["right"]["id"], 5000)
    post_bol(ticket["id"])

    terminal = get_terminal(env["terminal"]["id"])
    assert terminal["inventory_gallons"] == 5000, (
        "drawdown must be visible on the immediately following read"
    )
