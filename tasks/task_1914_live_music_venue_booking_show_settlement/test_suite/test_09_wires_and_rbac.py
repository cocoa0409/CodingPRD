"""Wire amount matching, RBAC negative probes, and auth-header rejection."""
from test_helpers import (
    ACCT,
    NO_AUTH_HEADERS,
    PROM,
    VM,
    ApiErrorId,
    create_agent,
    create_artist,
    create_confirmed_show,
    create_offer,
    create_show,
    create_show_with_deal,
    create_support,
    make_booking_agent_headers,
    set_clock,
    submit_expense,
    validate_error,
    accept_offer,
)


def test_wire_amount_mismatch_on_support_fee(api):
    """PRD §3.8: "Wire amounts are held to their canonical sources and
    mismatches are rejected with `ERR_WIRE_AMOUNT_MISMATCH` (HTTP 422): an
    `ARTIST_BALANCE` wire must equal the settlement's
    `artist_total_due_cents`, a `SUPPORT_FEE` wire must equal the act's
    `agreed_fee_cents`, and a `SUPPORT_BUYOUT` wire must equal the act's
    `buyout_fee_cents`."

    Design: Corner/errors/wire_amount_mismatch_on_support_fee
    """
    set_clock()
    artist = create_artist(deposit_pct=0.0)
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=5000, support_budget_cents=20000,
        bar_split_pct=0, merch_split_pct=0,
    )
    accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    support = create_support(
        show["id"], artist_name="OP",
        agreed_fee_cents=8000, buyout_fee_cents=6000,
    )
    resp = api.create_wire_transfer(
        show["id"],
        {"purpose": "SUPPORT_FEE", "amount_cents": 9999,
         "recipient_artist_id": None, "support_act_id": support["id"],
         "settlement_id": None},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_WIRE_AMOUNT_MISMATCH, 422)


def test_promoter_cannot_approve_own_expense(api):
    """PRD §3.6: "A `VenueManager` alone adjudicates: approval requires the
    receipt still `PENDING` and the show in `CONFIRMED`, `ON_SALE`,
    `ADVANCED`, or `SHOW_NIGHT`, and moves the receipt to `APPROVED`;
    rejection requires a `rejection_reason` and moves it to `REJECTED`."
    PRD §2.1: "An authenticated operator whose role is not on the target
    endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/promoter_cannot_approve_own_expense
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    receipt = submit_expense(
        show["id"], as_role="PROMOTER",
        category="SOUND", amount_cents=5000, receipt_reference="R1",
        is_recoupable=True,
    )
    resp = api.approve_expense_receipt(show["id"], receipt["id"], PROM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_booking_agent_cannot_manage_wires(api):
    """PRD §3.8: "Every dollar that moves, moves as a wire transfer, and
    every wire is worked by the `Accountant`."
    PRD §2.1: "An authenticated operator whose role is not on the target
    endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/booking_agent_cannot_manage_wires
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(artist["id"], agent=agent)
    resp = api.create_wire_transfer(
        show["id"],
        {"purpose": "ARTIST_DEPOSIT", "amount_cents": 1000,
         "recipient_artist_id": artist["id"], "support_act_id": None,
         "settlement_id": None},
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_unauthenticated_missing_role_header(api):
    """PRD §2.1: "A request with either header missing or malformed, or
    carrying a role the platform does not recognize, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_role_header
    """
    set_clock()
    resp = api.get_artist(
        "00000000-0000-0000-0000-000000000000", NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
