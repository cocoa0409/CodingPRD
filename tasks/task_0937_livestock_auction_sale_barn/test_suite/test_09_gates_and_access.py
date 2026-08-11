"""The five ordered write gates, the ladder's precedence and role access."""

from test_helpers import (
    ApiErrorId,
    AUCTIONEER,
    BARN_ADMIN,
    RING_CLERK,
    YARD_OPERATOR,
    add_buyer,
    advance_sale_day,
    api_client,
    assert_money,
    create_bid_payload,
    create_consignment_payload,
    create_lot,
    create_party,
    lot_version,
    make_consignor_headers,
    open_the_ring,
    place_bid,
    read_bid,
    read_buyer_registration,
    read_lot,
    read_pen,
    read_sale_day,
    set_clock,
    set_party_status,
    setup_checked_in_consignment,
    setup_ready_lot,
    setup_yard,
    validate_error,
    validate_paginated,
    validate_success,
)


def _quarantined_lot_with_a_thin_credit_line():
    """An IN_RING lot under a quarantine hold, and a bidder who cannot afford it."""
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(
        scn,
        bond_type="UNSECURED",
        credit_limit=1000,
        buyer_number=77,
        cash_deposit_amount=0,
        buyer_party_overrides={
            "legal_name": "Small Time Dealer",
            "party_type": "DEALER",
            "origin_county": "Hall",
            "tax_id": "47-3333333",
        },
    )
    open_the_ring(scn)
    validate_success(_quarantine(scn, hold=True))
    return scn


def _quarantine(scn, hold=True):
    return api_client.quarantine_lot(scn.lot["id"], {"hold": hold}, YARD_OPERATOR)


def test_the_quarantine_gate_answers_before_the_credit_check(api):
    """PRD §2.6: "**G2 — the lot is quarantined.** Every write touching a `Lot` whose
    `quarantine_hold` is true is refused with `ERR_LOT_QUARANTINED` (HTTP 409)."
    PRD §2.7: "Evaluation walks the ladder from rung 1 downward and stops at the first
    rung that fails; the failing rung's error is what the client sees, and every lower
    rung is left unevaluated."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_rung12_preempts_credit_limit_fiscal_rung37_on_bid
    """
    scn = _quarantined_lot_with_a_thin_credit_line()

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], scn.registration["id"], 182.50), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_LOT_QUARANTINED.value)

    _, meta = validate_paginated(api.list_bids(RING_CLERK, params={"lot_id": scn.lot["id"]}))
    assert meta["total_count"] == 0
    assert read_lot(scn.lot["id"])["sale_status"] == "IN_RING"


def test_lifting_the_hold_surfaces_the_credit_limit_refusal_underneath(api):
    """PRD §3.6: "A `YardOperator` sets or lifts `quarantine_hold` by supplying
    `hold`."
    PRD §3.8: "That figure must be less than or equal to the buyer's `effective_limit`;
    exceeding it is refused with `ERR_CREDIT_LIMIT_EXCEEDED`, which answers HTTP 402."
    PRD §3.7: "The multiplier is 1.5 for a `BONDED` buyer, 1.0 for an `UNSECURED`
    buyer, and 0.0 for a `CASH_ONLY` buyer — meaning a cash-only bidder's whole line is
    the cash they posted plus any override, and their nominal credit line counts for
    nothing."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_rung12_preempts_credit_limit_fiscal_rung37_on_bid
    """
    scn = _quarantined_lot_with_a_thin_credit_line()
    validate_success(_quarantine(scn, hold=False))

    response = api.create_bid(
        create_bid_payload(scn.lot["id"], scn.registration["id"], 182.50), RING_CLERK
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    registration = read_buyer_registration(scn.registration["id"])
    assert_money(registration["effective_limit"], 1000.00, "1000 x 1.0 with no deposit:")
    assert_money(registration["exposure"], 0.00, "the refused bid took on no exposure:")

    _, meta = validate_paginated(api.list_bids(RING_CLERK, params={"lot_id": scn.lot["id"]}))
    assert meta["total_count"] == 0
    assert read_lot(scn.lot["id"])["sale_status"] == "IN_RING"


def _frozen_day_with_a_lot_aimed_at_a_tiny_pen():
    scn = setup_checked_in_consignment(head_received=10, pen_capacity=5, with_scale=False)
    scn.lot = create_lot(scn.consignment["id"], head_count=10)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    return scn


def test_the_frozen_sale_day_answers_before_the_pen_capacity_check(api):
    """PRD §2.6: "**G3 — the sale day is frozen.** Once a `SaleDay` reaches
    `BIDDING_CLOSED` or `SETTLED`, bidding, hammer-downs, weigh-ticket capture, pen
    assignment, pen moves and lot creation are refused with `ERR_SALE_DAY_FROZEN` (HTTP
    409)."
    PRD §2.6: "Each one describes a condition under which a broad family of writes is
    refused, and the five are **totally ordered**: when a single request violates more
    than one gate, the earlier gate in the list below is the one that answers."

    Design: Difficulty/priority_pair_validation_conflict/sale_day_frozen_state_rung13_preempts_pen_capacity_constraint_rung24
    """
    scn = _frozen_day_with_a_lot_aimed_at_a_tiny_pen()

    response = api.assign_pen(scn.lot["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_SALE_DAY_FROZEN.value)

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "DRAFT"
    assert lot["pen_id"] is None


def test_reopening_the_ring_surfaces_the_pen_capacity_refusal_underneath(api):
    """PRD §3.2: "The day is not necessarily finished at that point: `BIDDING_CLOSED →
    RINGING` reopens the ring, increments `reopen_count` by one and switches gate G3 back
    off."
    PRD §3.5: "and the pen's `current_head` plus the lot's `head_count` must be less
    than or equal to the pen's `head_capacity`, or the answer is
    `ERR_PEN_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/sale_day_frozen_state_rung13_preempts_pen_capacity_constraint_rung24
    """
    scn = _frozen_day_with_a_lot_aimed_at_a_tiny_pen()
    api.assign_pen(scn.lot["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)

    advance_sale_day(scn.sale_day["id"], "RINGING")
    response = api.assign_pen(scn.lot["id"], {"pen_id": scn.pen["id"]}, YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_PEN_CAPACITY_EXCEEDED.value)

    lot = read_lot(scn.lot["id"])
    assert lot["sale_status"] == "DRAFT"
    assert lot["pen_id"] is None

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 0
    assert pen["status"] == "AVAILABLE"
    assert read_sale_day(scn.sale_day["id"])["reopen_count"] == 1


def test_every_write_against_a_cancelled_sale_day_is_refused(api):
    """PRD §2.6: "**G1 — the sale day is cancelled.** Every write whose target
    resolves, directly or through a chain of foreign keys, to a `SaleDay` whose `status`
    is `CANCELLED` is refused with `ERR_SALE_DAY_CANCELLED` (HTTP 409). Nothing is
    exempt: once a sale day is cancelled, its entire subtree is read-only."
    PRD §3.2: "Cancellation is available from any of the four working postures —
    `SCHEDULED`, `CHECK_IN_OPEN`, `RINGING` and `BIDDING_CLOSED` all admit a move to
    `CANCELLED` — and it is irreversible."

    Design: Corner/validations/corner_write_against_cancelled_sale_day_is_rejected
    """
    scn = setup_yard(with_pen=False, with_scale=False)
    advance_sale_day(scn.sale_day["id"], "CANCELLED")

    response = api.create_consignment(
        create_consignment_payload(scn.sale_day["id"], scn.consignor["id"]),
        scn.consignor_headers,
    )
    validate_error(response, ApiErrorId.ERR_SALE_DAY_CANCELLED.value)

    assert read_sale_day(scn.sale_day["id"])["status"] == "CANCELLED"
    _, meta = validate_paginated(
        api.list_consignments(BARN_ADMIN, params={"sale_day_id": scn.sale_day["id"]})
    )
    assert meta["total_count"] == 0


def test_a_suspended_party_cannot_write_until_it_is_reinstated(api):
    """PRD §2.6: "**G4 — the owning party is suspended.** Any write whose owning
    `Party` — consignor, buyer or carrier — has `status` equal to `SUSPENDED` is refused
    with `ERR_PARTY_SUSPENDED` (HTTP 403). The single exemption is `POST
    /sale-barn/parties/{id}/status`, without which a suspended party could never be
    reinstated."
    PRD §3.1: "An administrator may toggle that standing in either direction: an
    `ACTIVE` party moves to `SUSPENDED` and a `SUSPENDED` party moves back to `ACTIVE`,
    each time by naming the target in `to_status`."

    Design: Corner/validations/corner_consignment_by_suspended_party_is_rejected
    """
    scn = setup_yard(with_pen=False, with_scale=False)
    set_party_status(scn.consignor["id"], "SUSPENDED")

    response = api.create_consignment(
        create_consignment_payload(scn.sale_day["id"], scn.consignor["id"]),
        scn.consignor_headers,
    )
    validate_error(response, ApiErrorId.ERR_PARTY_SUSPENDED.value)

    reinstated = set_party_status(scn.consignor["id"], "ACTIVE")
    assert reinstated["status"] == "ACTIVE"

    data = validate_success(
        api.create_consignment(
            create_consignment_payload(scn.sale_day["id"], scn.consignor["id"]),
            scn.consignor_headers,
        ),
        201,
    )
    assert data["status"] == "INTAKE"


def test_a_request_with_no_role_header_is_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, or that names a role outside the
    nine listed below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); so is a request
    from one of the party-backed roles that omits `X-User-ID`."

    Design: Corner/rbac/corner_request_without_x_user_role_header_returns_unauthenticated
    """
    set_clock("2026-06-01T08:00:00Z")
    party = create_party()

    response = api.get_party(party["id"], {"Content-Type": "application/json"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.json()["response_type"] == "error"


def test_a_ring_clerk_may_record_the_bid_but_may_not_drop_the_hammer(api):
    """PRD §2.1: "When the role is recognised and the headers are well-formed but that
    role is not among the roles the target endpoint admits, the rejection is
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "Dropping the hammer is the `IN_RING → SOLD` transition, requested by an
    `Auctioneer` naming the `winning_bid_id`, the expected-version guard of §2.8, and
    optionally electing `buy_back`."

    Design: Corner/rbac/corner_ring_clerk_cannot_hammer_down_and_gets_forbidden_role
    """
    scn = setup_ready_lot(head_received=10, head_count=10)
    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    open_the_ring(scn)
    bid = place_bid(scn.lot["id"], scn.registration["id"], 182.50)

    response = api.hammer_down(
        scn.lot["id"],
        {"winning_bid_id": bid["id"], "expected_lot_version": lot_version(scn.lot["id"])},
        RING_CLERK,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    assert read_lot(scn.lot["id"])["sale_status"] == "IN_RING"
    assert read_bid(bid["id"])["status"] == "WINNING"
    _, meta = validate_paginated(
        api.list_purchases(AUCTIONEER, params={"lot_id": scn.lot["id"]})
    )
    assert meta["total_count"] == 0


def test_a_consignor_cannot_book_a_consignment_for_another_party(api):
    """PRD §2.1: "When `X-User-Role` is `Consignor`, `Buyer` or `Carrier`, `X-User-ID`
    is the `id` of the acting `Party`, and ownership checks on any resource that
    references a `Party` compare that resource's party-valued field to `X-User-ID`."
    PRD §2.1: "When the acting party is not the owning party, the request is rejected
    with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_consignor_cannot_book_a_consignment_for_another_party
    """
    scn = setup_yard(with_pen=False, with_scale=False)
    other_party = create_party(
        legal_name="Bar-7 Cattle", origin_county="Perkins", tax_id="47-8888888"
    )

    response = api.create_consignment(
        create_consignment_payload(scn.sale_day["id"], other_party["id"]),
        make_consignor_headers(scn.consignor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value)

    _, meta = validate_paginated(
        api.list_consignments(BARN_ADMIN, params={"sale_day_id": scn.sale_day["id"]})
    )
    assert meta["total_count"] == 0
