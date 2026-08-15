"""Refunds: OCC guard, snapshot/penalty arithmetic, open-trips guard, settle cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_card,
    confirm_trip,
    create_aircraft,
    create_member,
    create_program,
    create_refund,
    create_trip,
    fly_trip,
    get_card,
    get_escrow,
    get_ledger_entries,
    get_refund_via_list,
    make_member_headers,
    purchase_card,
    set_clock,
    setup_active_card,
    settle_refund,
    submit_refund,
    approve_refund,
    validate_error,
)

OPS = TEST_USERS["ops_headers"]


def test_stale_version_on_refund_create(api):
    """PRD §2.7: "Each request must carry `expected_card_version` as a non-optional input
    field, holding the `version` of the `JetCard` the client last observed. If the value
    does not match the card's current `version` — for example because a trip completion
    has since debited hours and advanced the version — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_on_refund_create
    """
    set_clock()
    program = create_program(program_code="VAL4")
    member = create_member()
    card = purchase_card(member["id"], program["id"])
    initial_version = card["version"]
    activate_card(card["id"])
    mh = make_member_headers(member["id"])
    resp = api.create_refund(
        card["id"], {"expected_card_version": initial_version - 1}, mh
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_stale_version_on_fractional_upgrade(api):
    """PRD §2.7: "Two write endpoints are stale-version guarded because they mutate the
    card's hour bank and escrow based on the caller's observed balance: refund creation
    and fractional-upgrade creation, both of which target a specific `JetCard`."
    PRD §2.7: "If the value does not match the card's current `version` — for example
    because a trip completion has since debited hours and advanced the version — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_fractional_upgrade
    """
    set_clock()
    program = create_program(program_code="OCC1")
    member = create_member()
    card = purchase_card(member["id"], program["id"])
    initial_version = card["version"]
    activate_card(card["id"])
    mh = make_member_headers(member["id"])
    resp = api.create_fractional_upgrade(
        card["id"], {"expected_card_version": initial_version - 1}, mh
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def _refund_ready_card(api, code="REF_TEST", clock_now="2026-12-01T00:00:00Z"):
    """Card activated at 2026-06-01 (25h, $100k, 20% penalty); clock advanced 6 months;
    refund created (DRAFT). Returns (member, card_id, refund)."""
    set_clock("2026-06-01T00:00:00Z")
    program = create_program(
        program_code=code,
        purchase_price_cents=10_000_000,
        hours_purchased=25,
        early_termination_penalty_pct=0.20,
    )
    member = create_member()
    card = purchase_card(member["id"], program["id"])
    activate_card(card["id"])
    set_clock(clock_now)
    refund = create_refund(card["id"], member["id"])
    return member, card["id"], refund


def test_refund_gross_and_penalty_computed_in_order(api):
    """PRD §3.10: "The gross amount is the escrow principal prorated by the snapshot:
    `hours_at_request` divided by `hours_total`, multiplied by `principal_cents`, rounded
    half-up to whole cents, stored as `gross_refund_cents`. The early-termination penalty
    is tiered on the card's age: when submission occurs before the first anniversary of
    `purchased_at` — within twelve months — `penalty_cents` is the gross amount multiplied
    by the program's `early_termination_penalty_pct`, rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/refund_penalty_evaluation_order_mode_c
    """
    member, card_id, refund = _refund_ready_card(api)
    submitted = submit_refund(refund["id"], member["id"])
    assert submitted["refund_status"] == "SUBMITTED"
    assert submitted["hours_at_request"] == pytest.approx(25.0, abs=0.005)
    # gross = (25/25) * 10,000,000 = 10,000,000
    assert submitted["gross_refund_cents"] == 10_000_000
    # 6 months after purchase < 12-month anniversary: penalty = 10,000,000 * 0.20
    assert submitted["penalty_cents"] == 2_000_000


def test_refund_net_is_gross_minus_penalty_floored(api):
    """PRD §3.10: "`net_refund_cents` is the gross minus the penalty, floored at zero."

    Design: Difficulty/combinatorial_formula/refund_penalty_evaluation_order_mode_c
    """
    member, card_id, refund = _refund_ready_card(api, code="REF_TEST_N")
    submitted = submit_refund(refund["id"], member["id"])
    gross = submitted["gross_refund_cents"]
    penalty = submitted["penalty_cents"]
    assert submitted["net_refund_cents"] == max(0, gross - penalty)
    assert submitted["net_refund_cents"] == 8_000_000


def test_refund_submit_with_confirmed_trip_rejected(api):
    """PRD §3.10: "Two preconditions guard it, evaluated in the global order: the card
    must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), and the card must have no trip in
    `CONFIRMED`, `DISPATCHED`, or `IN_FLIGHT` status (`ERR_OPEN_TRIPS_EXIST`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/refund_submit_requires_no_open_trips
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "XDEP2"})
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    refund = create_refund(card["id"], member["id"])
    mh = make_member_headers(member["id"])
    resp = api.submit_refund(refund["id"], mh)
    validate_error(resp, ApiErrorId.ERR_OPEN_TRIPS_EXIST, expected_status=409)


def test_refund_submit_rejection_leaves_draft(api):
    """PRD §3.10: "Submission is a member-only action from `DRAFT`" — a rejected
    submission never leaves `DRAFT`. "Two preconditions guard it ... the card must have
    no trip in `CONFIRMED`, `DISPATCHED`, or `IN_FLIGHT` status (`ERR_OPEN_TRIPS_EXIST`,
    HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/refund_submit_requires_no_open_trips
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "XDEP2B"})
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    refund = create_refund(card["id"], member["id"])
    mh = make_member_headers(member["id"])
    api.submit_refund(refund["id"], mh)
    after = get_refund_via_list(card["id"], refund["id"])
    assert after["refund_status"] == "DRAFT", (
        f"rejected submit must leave the refund in DRAFT, got {after['refund_status']}"
    )


def _approved_refund(api, code):
    """Card with full 25 hours; refund submitted + approved. Returns (member, card_id, refund)."""
    member, card_id, refund = _refund_ready_card(api, code=code, clock_now="2026-12-01T00:00:00Z")
    submit_refund(refund["id"], member["id"])
    approve_refund(refund["id"])
    return member, card_id, refund


def test_refund_settle_cascades_card_to_refunded(api):
    """PRD §3.10: "Settlement is the money-moving step: settling an `APPROVED` refund
    cascades the card from `ACTIVE` to `REFUNDED`, inserts a `REFUND_DEBIT` ledger entry
    for the negative of `hours_at_request`, reduces the escrow's `available_cents` by
    `net_refund_cents` while `released_cents` increases by the same amount, and reduces
    the card's `hours_remaining` by `hours_at_request`."

    Design: Difficulty/transitive_cascade/refund_settle_cascades_to_card_and_escrow
    """
    member, card_id, refund = _approved_refund(api, "CASCADE2")
    settled = settle_refund(refund["id"])
    assert settled["refund_status"] == "SETTLED"
    card = get_card(card_id)
    assert card["card_status"] == "REFUNDED", (
        f"settled refund must cascade the card to REFUNDED, got {card['card_status']}"
    )
    assert card["hours_remaining"] == pytest.approx(0.0, abs=0.005)
    debits = get_ledger_entries(card_id, entry_kind="REFUND_DEBIT")
    assert len(debits) == 1, f"exactly one REFUND_DEBIT expected, got {len(debits)}"
    assert debits[0]["hours_delta"] == pytest.approx(-25.0, abs=0.005)


def test_refund_settle_releases_escrow_net(api):
    """PRD §3.10: "Settlement is the money-moving step: settling an `APPROVED` refund
    cascades the card from `ACTIVE` to `REFUNDED`, inserts a `REFUND_DEBIT` ledger entry
    for the negative of `hours_at_request`, reduces the escrow's `available_cents` by
    `net_refund_cents` while `released_cents` increases by the same amount, and reduces
    the card's `hours_remaining` by `hours_at_request`."

    Design: Difficulty/transitive_cascade/refund_settle_cascades_to_card_and_escrow
    """
    member, card_id, refund = _approved_refund(api, "CASCADE2E")
    # gross 10,000,000, penalty 2,000,000 (6 months < 12), net 8,000,000.
    settle_refund(refund["id"])
    escrow = get_escrow(card_id)
    assert escrow["released_cents"] == 8_000_000, (
        f"released_cents must increase by net_refund_cents, got {escrow['released_cents']}"
    )
    assert escrow["available_cents"] == 2_000_000, (
        f"available_cents must drop by net_refund_cents, got {escrow['available_cents']}"
    )
