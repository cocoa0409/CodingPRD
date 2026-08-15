"""Show-schedule validation and on-sale gating (deposit / state / deal)."""
from test_helpers import (
    PROM,
    VM,
    ApiErrorId,
    accept_offer,
    create_agent,
    create_artist,
    create_confirmed_show,
    create_offer,
    create_show,
    create_show_with_deal,
    create_tier,
    get_show,
    make_booking_agent_headers,
    pay_deposit,
    set_clock,
    validate_error,
    validate_success,
)


def test_show_parallel_dimension_hold_and_deposit(api):
    """PRD §3.4: "Going on sale is a gated promotion from `CONFIRMED` to
    `ON_SALE`, performed by a `Promoter`, and every gate must swing open
    together: the show must be `CONFIRMED`, a deal must be in place
    (`deal_id` set by an accepted offer), the deposit must have landed —
    `deposit_paid_cents` at least equal to `deposit_required_cents` — the
    house clock must have reached the show's `on_sale_at_utc`, and at least
    one ticket tier must exist. A short deposit or an early clock is
    rejected with `ERR_DEPOSIT_NOT_CLEARED` (HTTP 422); a wrong from-state
    draws `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/show_parallel_dimension_hold_and_deposit
    """
    set_clock()
    artist = create_artist(guarantee_floor_cents=50000, deposit_pct=0.25)
    agent = create_agent()
    show, _ = create_confirmed_show(artist["id"], agent)
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent,
        deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
        artist_split_pct=0, versus_threshold_cents=0,
        expense_budget_cents=10000, support_budget_cents=0,
        bar_split_pct=0.10, merch_split_pct=0.20,
    )
    accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    # Deposit required = round_half_up(100000 * 0.25) = 25000.
    # Pay only 10000 (partial).
    pay_deposit(show["id"], artist["id"], 10000)
    create_tier(show["id"])
    set_clock("2026-08-10T10:00:01Z")

    show_now = get_show(show["id"])
    assert show_now["status"] == "CONFIRMED"
    assert show_now["deposit_paid_cents"] == 10000
    assert show_now["deposit_required_cents"] == 25000

    resp = api.place_on_sale(
        show["id"], {"expected_show_version": show_now["version"]}, PROM,
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_CLEARED, 422)
    assert get_show(show["id"])["status"] == "CONFIRMED"


def test_show_on_sale_blocked_until_deposit_axis_catches_up(api):
    """PRD §3.4: "Going on sale is a gated promotion from `CONFIRMED` to
    `ON_SALE`, performed by a `Promoter`, and every gate must swing open
    together: the show must be `CONFIRMED`, a deal must be in place
    (`deal_id` set by an accepted offer), the deposit must have landed —
    `deposit_paid_cents` at least equal to `deposit_required_cents` — the
    house clock must have reached the show's `on_sale_at_utc`, and at least
    one ticket tier must exist. A short deposit or an early clock is
    rejected with `ERR_DEPOSIT_NOT_CLEARED` (HTTP 422); a wrong from-state
    draws `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/show_parallel_dimension_hold_and_deposit
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25, guarantee_floor_cents=50000)
    agent = create_agent()
    # Confirm + accept but do NOT pay deposit.
    _artist, _agent, show, _deal = create_show_with_deal(
        artist=artist, agent=agent,
        offer_overrides=dict(
            deal_kind="FLAT_GUARANTEE", guarantee_cents=100000,
            artist_split_pct=0, versus_threshold_cents=0,
            expense_budget_cents=10000, support_budget_cents=0,
            bar_split_pct=0.10, merch_split_pct=0.20,
        ),
    )
    create_tier(show["id"])
    set_clock("2026-08-10T10:00:01Z")
    v = get_show(show["id"])["version"]
    resp = api.place_on_sale(show["id"], {"expected_show_version": v}, PROM)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_CLEARED, 422)


def test_state_vs_business_fiscal_on_onsale(api):
    """PRD §2.8: "Every request walks a fixed validation pipeline, and the
    first failure stops evaluation and determines the response — an earlier
    failure is never masked by a later check."
    PRD §2.8 step 5: "From-state validity for the requested transition, per
    the state machines of §3; failures yield `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.8 step 7 places the deposit-clearance gate after the from-state
    check, so a show in HOLD_PENDING that also has no deposit reports the
    state failure.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_onsale
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    # Fresh show in HOLD_PENDING; no hold confirmed; no deposit paid.
    show = create_show(artist["id"], agent=agent)
    resp = api.place_on_sale(
        show["id"], {"expected_show_version": show["version"]}, PROM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_show(show["id"])["status"] == "HOLD_PENDING"


def test_state_fires_before_deposit_gate_on_onsale(api):
    """PRD §2.8: "Every request walks a fixed validation pipeline, and the
    first failure stops evaluation and determines the response — an earlier
    failure is never masked by a later check."
    PRD §2.8 step 5: "From-state validity for the requested transition, per
    the state machines of §3; failures yield `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.8 step 7: "Business rules, in their own fixed sequence: the
    low-ticket-sales cancellation gate, then the deposit-clearance gate on
    going on sale, then hold-expiry timing on confirms, then challenge
    priority, then show-schedule validity, then tier capacity, then ticket
    availability, then the support budget, then deal terms, then the
    guarantee floor, then wire-amount matching, then settlement readiness,
    then segregation of duties, and finally the self-negotiation bar."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_onsale
    """
    set_clock()
    artist = create_artist(deposit_pct=0.25, guarantee_floor_cents=50000)
    agent = create_agent()
    # Show in HOLD_PENDING (never confirmed), and no deposit either — both
    # rule 5 (state) and rule 8 (deposit) would fail; rule 5 wins.
    show = create_show(artist["id"], agent=agent)
    resp = api.place_on_sale(
        show["id"], {"expected_show_version": show["version"]}, PROM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_show_schedule_doors_curfew_overlap_validation(api):
    """PRD §3.2: "the `show_date` must fall at least seven days after the
    current date, the curfew must be strictly later than doors, and doors
    must fall on the show date itself; any violation is rejected with
    `ERR_INVALID_SHOW_SCHEDULE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/show_schedule_doors_curfew_overlap_validation
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    # Zero-length interval: curfew == doors.
    resp = api.create_show(
        {
            "artist_id": artist["id"], "room": "MAIN_ROOM",
            "show_date": "2026-12-05",
            "doors_at_utc": "2026-12-05T20:00:00Z",
            "curfew_at_utc": "2026-12-05T20:00:00Z",
            "total_capacity": 500,
            "on_sale_at_utc": "2026-09-01T10:00:00Z",
        },
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SHOW_SCHEDULE, 422)
    # No show persisted.
    shows_resp = api.list_shows(VM, params={"artist_id": artist["id"]})
    body = shows_resp.json()
    assert body["meta"]["total_count"] == 0


def test_show_schedule_doors_not_on_show_date_rejected(api):
    """PRD §3.2: "the `show_date` must fall at least seven days after the
    current date, the curfew must be strictly later than doors, and doors
    must fall on the show date itself; any violation is rejected with
    `ERR_INVALID_SHOW_SCHEDULE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/show_schedule_doors_curfew_overlap_validation
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    # doors on 2026-12-06 but show_date 2026-12-05.
    resp = api.create_show(
        {
            "artist_id": artist["id"], "room": "MAIN_ROOM",
            "show_date": "2026-12-05",
            "doors_at_utc": "2026-12-06T19:00:00Z",
            "curfew_at_utc": "2026-12-06T23:00:00Z",
            "total_capacity": 500,
            "on_sale_at_utc": "2026-09-01T10:00:00Z",
        },
        make_booking_agent_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SHOW_SCHEDULE, 422)
