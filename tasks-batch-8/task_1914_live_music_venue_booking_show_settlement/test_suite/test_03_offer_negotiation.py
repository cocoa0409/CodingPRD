"""Offer lifecycle: proposal, counter, accept, reject, withdraw, OCC."""
from test_helpers import (
    VM,
    ApiErrorId,
    assert_deal,
    assert_offer,
    create_agent,
    create_artist,
    create_confirmed_show,
    create_offer,
    create_show_with_deal,
    get_show,
    make_booking_agent_headers,
    pay_deposit,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_offer_negotiation_cycle(api):
    """PRD §3.3: "A counter — allowed while the show is `HOLD_PENDING` or
    `CONFIRMED` — moves the answered offer from `PENDING` to `COUNTERED` and
    creates a fresh `PENDING` offer in one motion: its `round_number` is the
    answered offer's round plus one, its `proposed_by_role` is the
    countering side, and its `supersedes_offer_id` points at the offer it
    answers."
    PRD §3.3 (acceptance): "Every other offer on the show still sitting in
    `PENDING` or `COUNTERED` is swept to `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25, guarantee_floor_cents=30000)
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)

    # Round 1: agent proposes
    r1 = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=80000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=10000, support_budget_cents=5000,
        bar_split_pct=0.10, merch_split_pct=0.20,
    )
    assert r1["round_number"] == 1
    assert r1["status"] == "PENDING"

    # Round 2: venue counters
    r2_resp = api.counter_offer(
        show["id"], r1["id"],
        {
            "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 70000,
            "artist_split_pct": 0, "versus_threshold_cents": 0,
            "expense_budget_cents": 10000, "support_budget_cents": 5000,
            "bar_split_pct": 0.10, "merch_split_pct": 0.20,
        },
        VM,
    )
    r2 = validate_success(r2_resp, 201)
    assert r2["round_number"] == 2
    assert r2["supersedes_offer_id"] == r1["id"]
    assert r2["status"] == "PENDING"

    # Round 3: agent counters back
    r3_resp = api.counter_offer(
        show["id"], r2["id"],
        {
            "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 75000,
            "artist_split_pct": 0, "versus_threshold_cents": 0,
            "expense_budget_cents": 10000, "support_budget_cents": 5000,
            "bar_split_pct": 0.10, "merch_split_pct": 0.20,
        },
        make_booking_agent_headers(agent["id"]),
    )
    r3 = validate_success(r3_resp, 201)
    assert r3["round_number"] == 3
    assert r3["supersedes_offer_id"] == r2["id"]

    # Venue accepts round 3
    v = get_show(show["id"])["version"]
    deal_resp = api.accept_offer(
        show["id"], r3["id"], {"expected_show_version": v}, VM,
    )
    deal = validate_success(deal_resp, 200)
    assert_deal(deal)
    assert deal["guarantee_cents"] == 75000

    # Terminal states on prior offers: accepting r3 sweeps every other offer
    # still in PENDING or COUNTERED to SUPERSEDED (PRD §3.3), so the countered
    # rounds 1 and 2 land in SUPERSEDED, and the accepted round 3 is ACCEPTED.
    r1_after = validate_success(api.get_offer(r1["id"], VM), 200)
    r2_after = validate_success(api.get_offer(r2["id"], VM), 200)
    r3_after = validate_success(api.get_offer(r3["id"], VM), 200)
    assert r1_after["status"] == "SUPERSEDED"
    assert r2_after["status"] == "SUPERSEDED"
    assert r3_after["status"] == "ACCEPTED"


def test_offer_round_numbers_increment_across_cycle(api):
    """PRD §3.3: "The platform stamps each offer with its `round_number`,
    one greater than the highest existing round on that show, or 1 for the
    first offer; it records the proposing side in `proposed_by_role` as
    `BOOKING_AGENT` or `VENUE_MANAGER` taken from the caller; and round 1's
    `supersedes_offer_id` is null."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)

    r1 = create_offer(show["id"], as_role="BOOKING_AGENT", agent=agent)
    r2 = validate_success(
        api.counter_offer(
            show["id"], r1["id"],
            {
                "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 90000,
                "artist_split_pct": 0, "versus_threshold_cents": 0,
                "expense_budget_cents": 10000, "support_budget_cents": 0,
                "bar_split_pct": 0.10, "merch_split_pct": 0.20,
            },
            VM,
        ),
        201,
    )
    r3 = validate_success(
        api.counter_offer(
            show["id"], r2["id"],
            {
                "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 85000,
                "artist_split_pct": 0, "versus_threshold_cents": 0,
                "expense_budget_cents": 10000, "support_budget_cents": 0,
                "bar_split_pct": 0.10, "merch_split_pct": 0.20,
            },
            make_booking_agent_headers(agent["id"]),
        ),
        201,
    )
    assert (r1["round_number"], r2["round_number"], r3["round_number"]) == (1, 2, 3)
    assert r2["proposed_by_role"] == "VENUE_MANAGER"
    assert r3["proposed_by_role"] == "BOOKING_AGENT"


def test_offer_initial_state_pending(api):
    """PRD §3.3: "Every offer is born `PENDING`, and the negotiation loop
    turns on one iron rule: the side that proposed an offer can never be the
    side that answers it."

    Design: Corner/state_machines/offer_initial_state_pending
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)

    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
    )
    assert_offer(offer)
    assert offer["status"] == "PENDING"
    assert offer["round_number"] == 1


def test_offer_counter_creates_new_offer(api):
    """PRD §3.3: "A counter — allowed while the show is `HOLD_PENDING` or
    `CONFIRMED` — moves the answered offer from `PENDING` to `COUNTERED` and
    creates a fresh `PENDING` offer in one motion: its `round_number` is the
    answered offer's round plus one, its `proposed_by_role` is the
    countering side, and its `supersedes_offer_id` points at the offer it
    answers."

    Design: Corner/endpoints/offer_counter_creates_new_offer
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    o1 = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=80000,
    )
    o2 = validate_success(
        api.counter_offer(
            show["id"], o1["id"],
            {
                "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 70000,
                "artist_split_pct": 0, "versus_threshold_cents": 0,
                "expense_budget_cents": 5000, "support_budget_cents": 0,
                "bar_split_pct": 0.10, "merch_split_pct": 0.20,
            },
            VM,
        ),
        201,
    )
    assert o2["supersedes_offer_id"] == o1["id"]
    assert o2["round_number"] == 2
    o1_after = validate_success(api.get_offer(o1["id"], VM), 200)
    assert o1_after["status"] == "COUNTERED"


def test_offer_reject_is_terminal_and_idempotent(api):
    """PRD §3.3: "A rejection moves the offer from `PENDING` to `REJECTED`
    with no further effect."
    PRD §2.8: "From-state validity for the requested transition, per the
    state machines of §3; failures yield `ERR_INVALID_STATE` (HTTP 409).
    When the target entity is already in a terminal state and no transition
    is defined at all, the rejection is `ERR_ALREADY_TERMINAL` (HTTP 409)."
    A REJECTED offer is terminal with no outbound transitions, so the two
    §2.8 sentences overlap on a second reject; either member of the pair is
    a faithful rejection (both are HTTP 409).

    Design: Corner/state_machines/offer_reject_is_terminal_and_idempotent
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
    )
    validate_success(api.reject_offer(show["id"], offer["id"], VM), 200)
    resp = api.reject_offer(show["id"], offer["id"], VM)
    assert resp.status_code == 409
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL],
    )


def test_self_negotiation_rejected(api):
    """PRD §3.3: "Countering, accepting, or rejecting requires the caller's
    role to differ from the offer's `proposed_by_role`; a matching role is
    rejected with `ERR_SELF_NEGOTIATION` (HTTP 422)."

    Design: Corner/validations/self_negotiation_rejected
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
    )
    resp = api.reject_offer(
        show["id"], offer["id"], make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_NEGOTIATION, 422)


def test_guarantee_below_artist_floor(api):
    """PRD §3.3: "for guarantee-bearing kinds, an offer whose
    `guarantee_cents` falls below the artist's `guarantee_floor_cents` is
    rejected with `ERR_GUARANTEE_BELOW_FLOOR` (HTTP 422)."

    Design: Corner/validations/guarantee_below_artist_floor
    """
    set_clock()
    artist = create_artist(guarantee_floor_cents=50000)
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    resp = api.create_offer(
        show["id"],
        {
            "deal_kind": "FLAT_GUARANTEE", "guarantee_cents": 40000,
            "artist_split_pct": 0, "versus_threshold_cents": 0,
            "expense_budget_cents": 5000, "support_budget_cents": 0,
            "bar_split_pct": 0.10, "merch_split_pct": 0.20,
        },
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_BELOW_FLOOR, 422)


def test_get_show_deal_returns_active_snapshot(api):
    """PRD §3.3: "On acceptance the offer becomes `ACCEPTED` and the
    platform mints a `Deal`: an `ACTIVE` snapshot copying the accepted
    offer's `offer_id` and every commercial term — `deal_kind`,
    `guarantee_cents`, `artist_split_pct`, `versus_threshold_cents`,
    `expense_budget_cents`, `support_budget_cents`, `bar_split_pct`, and
    `merch_split_pct` — so that later negotiation can never rewrite
    history."

    Design: Corner/endpoints/get_show_deal_returns_active_snapshot
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="VERSUS", guarantee_cents=80000, artist_split_pct=0.65,
        versus_threshold_cents=120000, expense_budget_cents=15000,
        support_budget_cents=8000, bar_split_pct=0.12, merch_split_pct=0.22,
    )
    v = get_show(show["id"])["version"]
    deal = validate_success(
        api.accept_offer(
            show["id"], offer["id"], {"expected_show_version": v}, VM,
        ),
        200,
    )
    assert_deal(deal)
    assert deal["deal_kind"] == "VERSUS"
    assert deal["versus_threshold_cents"] == 120000
    assert deal["status"] == "ACTIVE"
    assert deal["artist_split_pct"] == 0.65

    fetched = validate_success(api.get_show_deal(show["id"], VM), 200)
    assert fetched["id"] == deal["id"]
    assert fetched["deal_kind"] == "VERSUS"


def test_occ_stale_version_on_offer_accept(api):
    """PRD §2.6: "If the show's current `version` has advanced beyond that
    observed value — because a deposit wire completed, a competing hold
    confirmed, another offer was accepted, or any other mutation landed in
    between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    protecting the caller from writing against a show it has not seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_offer_accept
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25)
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=50000,
    )
    # Capture a stale version, then advance show.version via a deposit wire.
    stale_v = get_show(show["id"])["version"]
    pay_deposit(show["id"], artist["id"], 100)

    resp = api.accept_offer(
        show["id"], offer["id"], {"expected_show_version": stale_v}, VM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    offer_after = validate_success(api.get_offer(offer["id"], VM), 200)
    assert offer_after["status"] == "PENDING"
