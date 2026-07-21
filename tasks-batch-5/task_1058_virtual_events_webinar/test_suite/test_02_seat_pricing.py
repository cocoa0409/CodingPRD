"""Pricing a seat twice: the provisional run at registration and the final run
at settlement, plus the boundary behaviour of each pricing component."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    reset_clock,
    new_event,
    add_ticket_type,
    publish_event,
    start_event,
    end_event,
    add_registration,
    pay_registration,
    read_registration,
    read_event,
    read_ticket_type,
    create_event_settlement,
    setup_published_event,
)

ORG = TEST_USERS["organizer_headers"]
FIN = TEST_USERS["finance_admin_headers"]


def _summit_a_settled():
    """Event 'Summit A' with a VIP seat bought inside the early-bird window on a
    claimed group of five that never materialised, driven to ENDED and settled.

    Provisional: (30000 + 5000) list, 20% early bird + 10% group capped at 25%
    -> 26250, fee round(787.5) = 788 -> 27038.
    Final: same clock (created_at) so early bird still applies, but the observed
    paid group is 1 -> 20% only -> 28000, fee 840 -> 28840.
    """
    reset_clock()
    event = new_event(
        name="Summit A",
        starts_at="2026-09-10T09:00:00Z",
        ends_at="2026-09-10T18:00:00Z",
        early_bird_ends_at="2026-08-01T00:00:00Z",
        capacity=100,
    )
    ticket_type = add_ticket_type(
        event["id"], name="VIP Pass", tier="VIP", price_cents=30000, quota=10,
        gating_level="BOTH",
    )
    publish_event(event["id"])
    registration = add_registration(
        event["id"], ticket_type["id"], "vip@example.com",
        group_code="TEAM7", group_size=5,
    )
    pay_registration(registration["id"], 27038)
    start_event(event["id"])
    end_event(event["id"])
    settlement = create_event_settlement(event["id"])
    return event, ticket_type, registration, settlement


def test_provisional_price_uses_claimed_group_size_final_uses_observed(api):
    """PRD 3.4: "The **provisional** run happens when a seat-holding registration
    is created and again when a waitlisted registration is promoted. Its pricing
    clock is the current logical clock at the moment of the call, and its
    effective group size is simply the `group_size` the registrant claimed in the
    request, defaulting to one."
    PRD 3.4: "Its effective group size is the **observed** number of
    registrations on the same event that share the same non-null `group_code` and
    whose `payment_status` is `PAID`; when the registration's `group_code` is null
    the observed size is one."
    PRD 3.4: "A registrant who claimed a group of five or more but whose
    colleagues never materialised — or never paid — therefore ends up with a
    `final_amount_due_cents` strictly greater than the `amount_due_cents` they
    were originally charged, and that difference is exactly what the settlement
    adjustment captures."

    Design: Difficulty/dual_variant_calc/registration_pricing_provisional_vs_final_diverges
    """
    event, ticket_type, registration, settlement = _summit_a_settled()

    assert registration["amount_due_cents"] == 27038, (
        f"Expected provisional 27038 cents, got {registration['amount_due_cents']}"
    )
    final = read_registration(registration["id"])
    assert final["amount_due_cents"] == 27038, (
        "The provisional charge must survive settlement unchanged"
    )
    assert final["final_amount_due_cents"] == 28840, (
        f"Expected final 28840 cents from the observed group of one, got "
        f"{final['final_amount_due_cents']}"
    )
    assert final["amount_paid_cents"] == 27038
    assert final["final_amount_due_cents"] > final["amount_due_cents"]


def test_settlement_adjustment_captures_the_pricing_divergence(api):
    """PRD 3.11: "**Step three** sums, over that same population, each
    registration's `final_amount_due_cents` less its `amount_paid_cents`, and
    writes the result to the event's `settlement_adjustment_cents` — this is the
    aggregate correction between what attendees were charged and what they
    actually owed."
    PRD 3.11: "**Step seven** sets `total_cents` to `platform_fee_cents` plus the
    streaming charge, and `organizer_payout_cents` to the gross ticket revenue
    less `total_cents` — a figure that may legitimately be negative."

    Design: Difficulty/dual_variant_calc/registration_pricing_provisional_vs_final_diverges
    """
    event, ticket_type, registration, settlement = _summit_a_settled()

    assert read_event(event["id"])["settlement_adjustment_cents"] == 1802, (
        "28840 owed less 27038 paid leaves an adjustment of 1802 cents"
    )
    assert settlement["subtotal_cents"] == 28840, (
        f"Expected subtotal 28840, got {settlement['subtotal_cents']}"
    )
    assert settlement["platform_fee_cents"] == 2307, (
        f"Expected 8% of 28840 rounded half up = 2307, got "
        f"{settlement['platform_fee_cents']}"
    )
    assert settlement["total_cents"] == 2307
    assert settlement["organizer_payout_cents"] == 26533, (
        f"Expected 28840 - 2307 = 26533, got {settlement['organizer_payout_cents']}"
    )


def test_early_bird_boundary_exactly_at_cutoff_gives_no_discount(api):
    """PRD 3.4: "**Second**, an early-bird component of twenty percent applies
    when the pricing clock falls strictly before the event's `early_bird_ends_at`,
    and is zero otherwise; a purchase made at the exact cut-off instant is too
    late."

    Design: Corner/calculations/corner_early_bird_boundary_exactly_at_cutoff_gives_no_discount
    """
    reset_clock()
    event = new_event(
        name="Cutoff",
        starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T17:00:00Z",
        early_bird_ends_at="2026-07-01T00:00:00Z",
    )
    ticket_type = add_ticket_type(event["id"], price_cents=20000, quota=10)
    publish_event(event["id"])

    registration = add_registration(
        event["id"], ticket_type["id"], "cutoff@example.com"
    )
    assert registration["amount_due_cents"] == 20600, (
        "At a clock exactly equal to early_bird_ends_at no discount applies, so a "
        f"20000-cent ticket costs 20600; got {registration['amount_due_cents']}"
    )


def test_processing_fee_floor_applies_to_free_ticket(api):
    """PRD 3.4: "**Sixth**, a processing fee is taken as three percent of that
    discounted amount, rounded half up to a whole cent, and then clamped so that
    it is never below 100 cents and never above 2,500 cents — this is the second
    and last rounding."
    PRD 3.4: "**Seventh**, the amount owed is the discounted amount plus the
    clamped processing fee. The sum itself is never rounded again."

    Design: Corner/calculations/corner_processing_fee_floor_applies_to_free_ticket
    """
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Free Tier"},
        ticket_overrides={"name": "Free", "price_cents": 0, "quota": 10},
    )
    registration = add_registration(
        event["id"], ticket_type["id"], "free@example.com"
    )
    assert registration["amount_due_cents"] == 100, (
        "A zero-cent ticket still carries the 100-cent fee floor; got "
        f"{registration['amount_due_cents']}"
    )


def test_registration_group_size_defaults_to_one(api):
    """PRD 3.3: "A registration is created by an `Organizer` on behalf of an
    attendee, naming the `event_id` and `ticket_type_id`, the `attendee_email`,
    and optionally a `group_code` shared with co-registering colleagues, a
    claimed `group_size` of at least one (defaulting to 1), and a
    `waitlist_if_full` flag."
    PRD 3.4: "**Third**, a group component of ten percent applies when the
    effective group size is at least five, and is zero otherwise."
    PRD 3.3: "The `payment_status` axis runs `UNPAID → PAID → REFUNDED` and
    begins at `UNPAID`."

    Design: Corner/entities/corner_registration_group_size_defaults_to_one
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Defaults"})
    registration = add_registration(event["id"], ticket_type["id"], "d1@example.com")

    assert registration["group_size"] == 1, (
        f"Omitted group_size must default to 1, got {registration['group_size']}"
    )
    assert registration["amount_due_cents"] == 20600, (
        "A group of one earns no group discount, so 20000 + 600 fee = 20600; got "
        f"{registration['amount_due_cents']}"
    )
    assert registration["payment_status"] == "UNPAID"
    assert registration["attendance_status"] == "REGISTERED"


def test_waitlisted_registration_excluded_from_sold_count(api):
    """PRD 3.3: "When `waitlist_if_full` **is** true, neither gate rejects:
    instead the row is created with `attendance_status` of `WAITLISTED` and
    `amount_due_cents` of zero, it does not consume a seat, and it does not
    advance `sold_count` or `registered_count`."

    Design: Corner/calculations/corner_waitlisted_registration_excluded_from_sold_count
    """
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Waitlist"}, ticket_overrides={"quota": 1}
    )
    add_registration(event["id"], ticket_type["id"], "seated@example.com")

    queued = validate_success(
        api.create_registration(
            {
                "event_id": event["id"],
                "ticket_type_id": ticket_type["id"],
                "attendee_email": "queued@example.com",
                "waitlist_if_full": True,
            },
            ORG,
        ),
        201,
    )
    assert queued["attendance_status"] == "WAITLISTED"
    assert queued["amount_due_cents"] == 0, (
        f"A waitlisted row is priced at zero, got {queued['amount_due_cents']}"
    )
    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 1, f"Expected sold_count still 1, got {tt['sold_count']}"
    assert tt["availability_status"] == "SOLD_OUT"
    assert read_event(event["id"])["registered_count"] == 1
