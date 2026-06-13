"""Reservation, league, and league-night state machines.

Covers Difficulty queue: non_linear_state_machine, cross_entity_state_dependency.
Covers Corner queue: state_machines instances (invalid transitions, terminal
lockdown, initial state, precondition enforcement, no-show, revision reprice).
"""

from test_helpers import (
    validate_success,
    validate_error,
    create_rate_card_payload,
    create_lane_payload,
    create_customer_payload,
    create_reservation_payload,
    create_rental_item_payload,
    create_rental_line_payload,
    create_league_payload,
    create_league_night_payload,
    set_clock,
    CM, FD, LA,
)


# =============================================================================
# Difficulty / non_linear_state_machine
# =============================================================================
def test_reservation_revision_loop_confirmed_held_confirmed(api):
    """PRD §3.5: "The system supports a **revision loop** so a confirmed booking
    can be re-opened to change its terms — this is the one cyclic edge in the
    reservation lifecycle. Revising drives `CONFIRMED → HELD`".
    PRD §3.5: "Once held, a reservation is confirmed by the owning `Customer` or a
    `FrontDesk` operator, advancing `HELD → CONFIRMED` while the deposit stays
    held."

    Design: Difficulty/non_linear_state_machine/reservation_revision_loop_confirmed_to_held_to_confirmed
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Rev", per_game_cents=500, per_hour_cents=2000, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-07T12:00:00.000Z", end_at="2026-07-07T13:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    assert confirmed["status"] == "CONFIRMED"

    revised = validate_success(api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 4}, FD), 200)
    assert revised["status"] == "HELD"

    reconfirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": revised["version"]}, FD), 200)
    assert reconfirmed["status"] == "CONFIRMED"


def test_league_night_branches_played_forfeited_rained_out_diverge(api):
    """PRD §3.8: "Marking a night **played** (`SCHEDULED → PLAYED`) ... sets the
    night's `night_fee_cents` to the league's `weekly_fee_cents`".
    PRD §3.8: "Marking a night **forfeited** (`SCHEDULED → FORFEITED`) still owes
    the fee: it likewise sets `night_fee_cents` to `weekly_fee_cents`".
    PRD §3.8: "Marking a night **rained out** (`SCHEDULED → RAINED_OUT`) is the
    divergent branch: no fee accrues, so `night_fee_cents` is set to zero".

    Design: Difficulty/non_linear_state_machine/league_night_branch_played_forfeited_rained_out_divergent
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Br", per_game_cents=0, per_hour_cents=0), CM), 201)
    for _ in range(3):
        validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=3, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    windows = [
        ("2026-07-02T18:00:00.000Z", "2026-07-02T20:00:00.000Z"),
        ("2026-07-09T18:00:00.000Z", "2026-07-09T20:00:00.000Z"),
        ("2026-07-16T18:00:00.000Z", "2026-07-16T20:00:00.000Z"),
    ]
    nights = []
    for i, (s, e) in enumerate(windows):
        nights.append(validate_success(api.create_league_night(create_league_night_payload(
            league["id"], night_index=i + 1, start_at=s, end_at=e), LA), 201))
    validate_success(api.activate_league(league["id"], LA), 200)
    set_clock("2026-07-17T00:00:00.000Z")

    played = validate_success(api.mark_played_league_night(nights[0]["id"], LA), 200)
    forfeited = validate_success(api.forfeit_league_night(nights[1]["id"], LA), 200)
    rained = validate_success(api.rain_out_league_night(nights[2]["id"], LA), 200)

    assert played["night_fee_cents"] == 5000
    assert forfeited["night_fee_cents"] == 5000
    assert rained["night_fee_cents"] == 0


# =============================================================================
# Difficulty / cross_entity_state_dependency
# =============================================================================
def test_confirm_blocked_when_lane_out_of_service(api):
    """PRD §3.5: "Confirmation is the first of the two version-guarded steps: the
    body must carry `expected_reservation_version` matching the reservation's
    current `version` ... the target lane or bay must still be `IN_SERVICE`
    (otherwise `ERR_RESOURCE_OUT_OF_SERVICE`)".

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_lane_out_of_service
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="X1", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-06T18:00:00.000Z", end_at="2026-08-06T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.set_lane_status(lane["id"], {"status": "OUT_OF_SERVICE"}, CM), 200)

    resp = api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD)
    validate_error(resp, "ERR_RESOURCE_OUT_OF_SERVICE", expected_status=409)


def test_mark_played_blocked_when_league_not_active(api):
    """PRD §3.8: "Each scheduled night resolves to one of three outcomes, all
    driven by the `LeagueAdmin` and all requiring the parent league to be
    `ACTIVE` — a transition attempted while the parent league is not active is
    rejected with `ERR_LEAGUE_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/mark_played_blocked_when_league_not_active
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="X2", per_game_cents=0, per_hour_cents=0), CM), 201)
    validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=1, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    night = validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-08-07T18:00:00.000Z", end_at="2026-08-07T20:00:00.000Z"), LA), 201)
    set_clock("2026-08-08T00:00:00.000Z")  # past night start, but league still DRAFT

    resp = api.mark_played_league_night(night["id"], LA)
    validate_error(resp, "ERR_LEAGUE_NOT_ACTIVE", expected_status=409)


# =============================================================================
# Corner / state_machines
# =============================================================================
def test_confirm_from_draft_is_invalid_state(api):
    """PRD §3.5: "A transition requested against a reservation not in the state
    that admits it — confirming something that is not `HELD`, checking in
    something that is not `CONFIRMED`, and so on — is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_draft_invalid_state
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S1", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-05T18:00:00.000Z", end_at="2026-09-05T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    resp = api.confirm_reservation(
        res["id"], {"expected_reservation_version": res["version"]}, FD)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_from_cancelled_terminal_lockdown(api):
    """PRD §3.6: "once a reservation has reached `CHECKED_IN` (or any terminal
    state) it can no longer be cancelled, and the attempt is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-06T18:00:00.000Z", end_at="2026-09-06T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.cancel_reservation(res["id"], FD), 200)

    resp = api.cancel_reservation(res["id"], FD)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


def test_new_reservation_starts_in_draft(api):
    """PRD §3.3: "A booking begins as a **reservation** in `DRAFT`."

    Design: Corner/state_machines/initial_state_reservation_is_draft
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S3", per_game_cents=500, per_hour_cents=0), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-07T18:00:00.000Z", end_at="2026-09-07T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    assert res["status"] == "DRAFT"


def test_complete_blocked_when_rentals_outstanding(api):
    """PRD §3.5: "**Completion** advances a `CHECKED_IN` reservation to
    `COMPLETED`, but only once every rental line on that reservation has been
    returned — any line still `OPEN` blocks completion with
    `ERR_RENTALS_OUTSTANDING`."

    Design: Corner/state_machines/complete_blocked_when_rentals_outstanding
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S4", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="SHOES", label="W8", unit_price_cents=300, total_count=4), CM), 201)
    set_clock("2026-09-08T17:55:00.000Z")
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-08T18:00:00.000Z", end_at="2026-09-08T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 2), FD), 201)
    after_rental = validate_success(api.get_reservation(res["id"], FD), 200)
    validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": after_rental["version"]}, FD), 200)
    validate_success(api.check_in_reservation(res["id"], FD), 200)

    resp = api.complete_reservation(res["id"], FD)
    validate_error(resp, "ERR_RENTALS_OUTSTANDING", expected_status=409)


def test_close_league_blocked_with_scheduled_nights(api):
    """PRD §3.8: "A league is **closed** by its admin, moving `ACTIVE → CLOSED`,
    but only once no night remains `SCHEDULED`; closing a league while any
    scheduled night is still pending is rejected with
    `ERR_LEAGUE_HAS_SCHEDULED_NIGHTS`."

    Design: Corner/state_machines/close_league_blocked_with_scheduled_nights
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S5", per_game_cents=0, per_hour_cents=0), CM), 201)
    validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=1, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-09-10T18:00:00.000Z", end_at="2026-09-10T20:00:00.000Z"), LA), 201)
    validate_success(api.activate_league(league["id"], LA), 200)

    resp = api.close_league(league["id"], LA)
    validate_error(resp, "ERR_LEAGUE_HAS_SCHEDULED_NIGHTS", expected_status=409)


def test_activate_league_with_no_nights_rejected(api):
    """PRD §3.8: "A league is **activated** by its admin, moving `DRAFT → ACTIVE`,
    but only if it has at least one league night scheduled; activating a league
    with no nights is rejected with `ERR_LEAGUE_NO_NIGHTS`."

    Design: Corner/state_machines/activate_league_with_no_nights_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S6", per_game_cents=0, per_hour_cents=0), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=2, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)

    resp = api.activate_league(league["id"], LA)
    validate_error(resp, "ERR_LEAGUE_NO_NIGHTS", expected_status=409)


def test_no_show_after_window_forfeits_deposit(api):
    """PRD §3.6: "front-desk staff record a **no-show**, driving
    `CONFIRMED → NO_SHOW`. This is permitted only when the current time is past
    `end_at` and the reservation never reached `CHECKED_IN`. A no-show forfeits
    the deposit entirely: `refund_cents` is zero, the held deposit is removed from
    `deposit_balance_cents`, and no wallet credit is granted."

    Design: Corner/state_machines/no_show_requires_past_end_window
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S7", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    set_clock("2026-09-11T17:00:00.000Z")
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-11T18:00:00.000Z", end_at="2026-09-11T19:00:00.000Z",
        bowler_count=2, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    set_clock("2026-09-11T20:00:00.000Z")

    no_show = validate_success(api.no_show_reservation(res["id"], FD), 200)
    assert no_show["status"] == "NO_SHOW"
    assert no_show["refund_cents"] == 0
    cust_after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert cust_after["deposit_balance_cents"] == 0


def test_revision_reprice_reconciles_deposit_delta(api):
    """PRD §3.5: "A revise applies any supplied new `start_at`, `end_at`,
    `pricing_mode`, `bowler_count`, `game_count`, or `guest_count`; re-runs the
    temporal-overlap check against the possibly-new window; recomputes the quoted
    total and the held deposit; and reconciles the customer's
    `deposit_balance_cents` by the difference between the new and old deposit."

    Design: Corner/state_machines/revision_loop_reprice_reconciles_deposit_delta
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="S8", per_game_cents=1000, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-12T18:00:00.000Z", end_at="2026-09-12T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)

    revised = validate_success(api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 4}, FD), 200)
    # quoted 1000*4*2 = 8000; deposit 20% = 1600
    assert revised["held_deposit_cents"] == 1600
    cust_after = validate_success(api.get_customer(cust["id"], FD), 200)
    assert cust_after["deposit_balance_cents"] == 1600


# =============================================================================
# Difficulty — second tests (distinct PRD-derivable facet per instance)
# =============================================================================
def test_revision_loop_increments_version_each_hop(api):
    """PRD §3.5: "A successful confirm increments the reservation's `version`."
    PRD §3.5: "The reservation returns to `HELD` and its `version` is incremented."

    Design: Difficulty/non_linear_state_machine/reservation_revision_loop_confirmed_to_held_to_confirmed
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Rev2", per_game_cents=500, per_hour_cents=2000, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-07T12:00:00.000Z", end_at="2026-07-07T13:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    revised = validate_success(api.revise_reservation(
        res["id"], {"expected_reservation_version": confirmed["version"], "game_count": 4}, FD), 200)
    reconfirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": revised["version"]}, FD), 200)
    # version strictly increases across each hop of the cycle
    assert confirmed["version"] > held["version"]
    assert revised["version"] > confirmed["version"]
    assert reconfirmed["version"] > revised["version"]


def test_league_night_rained_out_leaves_accrual_unchanged(api):
    """PRD §3.8: "Marking a night **rained out** (`SCHEDULED → RAINED_OUT`) is the
    divergent branch: no fee accrues, so `night_fee_cents` is set to zero, the
    league's `season_fee_accrued_cents` is left unchanged".
    PRD §3.8: "Marking a night **played** (`SCHEDULED → PLAYED`) ... adds that fee
    to the league's `season_fee_accrued_cents` as a chronological accrual".

    Design: Difficulty/non_linear_state_machine/league_night_branch_played_forfeited_rained_out_divergent
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Br2", per_game_cents=0, per_hour_cents=0), CM), 201)
    for _ in range(2):
        validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=2, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    n1 = validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-07-02T18:00:00.000Z", end_at="2026-07-02T20:00:00.000Z"), LA), 201)
    n2 = validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=2,
        start_at="2026-07-09T18:00:00.000Z", end_at="2026-07-09T20:00:00.000Z"), LA), 201)
    validate_success(api.activate_league(league["id"], LA), 200)
    set_clock("2026-07-10T00:00:00.000Z")

    validate_success(api.mark_played_league_night(n1["id"], LA), 200)
    after_played = validate_success(api.get_league(league["id"], LA), 200)
    assert after_played["season_fee_accrued_cents"] == 5000

    validate_success(api.rain_out_league_night(n2["id"], LA), 200)
    after_rain = validate_success(api.get_league(league["id"], LA), 200)
    # rained-out night accrues 0 -> accrual unchanged from the single played night
    assert after_rain["season_fee_accrued_cents"] == 5000


def test_confirm_succeeds_when_lane_back_in_service(api):
    """PRD §3.5: "the target lane or bay must still be `IN_SERVICE` (otherwise
    `ERR_RESOURCE_OUT_OF_SERVICE`)".
    PRD §3.1: "a manager may toggle it between `IN_SERVICE` and `OUT_OF_SERVICE`
    by supplying a new `status`".

    Restoring the lane to IN_SERVICE removes the cross-entity block, so the
    held reservation confirms normally.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_lane_out_of_service
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="X1b", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-06T18:00:00.000Z", end_at="2026-08-06T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    validate_success(api.set_lane_status(lane["id"], {"status": "OUT_OF_SERVICE"}, CM), 200)
    blocked = api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD)
    validate_error(blocked, "ERR_RESOURCE_OUT_OF_SERVICE", expected_status=409)

    validate_success(api.set_lane_status(lane["id"], {"status": "IN_SERVICE"}, CM), 200)
    confirmed = validate_success(api.confirm_reservation(
        res["id"], {"expected_reservation_version": held["version"]}, FD), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_mark_played_succeeds_once_league_active(api):
    """PRD §3.8: "Marking a night **played** (`SCHEDULED → PLAYED`) additionally
    requires the current time to be at or after the night's `start_at`; it sets
    the night's `night_fee_cents` to the league's `weekly_fee_cents`".

    Once the parent league is ACTIVE, the previously-blocked mark-played succeeds.

    Design: Difficulty/cross_entity_state_dependency/mark_played_blocked_when_league_not_active
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="X2b", per_game_cents=0, per_hour_cents=0), CM), 201)
    validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=1, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    night = validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-08-07T18:00:00.000Z", end_at="2026-08-07T20:00:00.000Z"), LA), 201)
    set_clock("2026-08-08T00:00:00.000Z")

    blocked = api.mark_played_league_night(night["id"], LA)
    validate_error(blocked, "ERR_LEAGUE_NOT_ACTIVE", expected_status=409)

    validate_success(api.activate_league(league["id"], LA), 200)
    played = validate_success(api.mark_played_league_night(night["id"], LA), 200)
    assert played["status"] == "PLAYED"
    assert played["night_fee_cents"] == 5000
