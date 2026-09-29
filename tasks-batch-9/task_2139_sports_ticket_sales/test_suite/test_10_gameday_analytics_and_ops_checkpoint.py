"""Gate scans, attendance analytics, churn scoring and the ops checkpoint cascades."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ops_summary,
    assert_season_census_invariant,
    create_confirmed_order,
    create_game,
    create_order,
    create_published_plan,
    create_season,
    mint_seats,
    open_renewal,
    pay_order,
    place_hold,
    read_account,
    read_game,
    read_hold,
    read_order,
    read_plan,
    read_season,
    read_seat,
    run_ops,
    scan_seat,
    set_clock,
    setup_selling_world,
    setup_world_with_confirmed_order,
    validate_error,
    validate_success,
    OPS_HEADERS,
)


def _churn_world():
    """A tenure-4 account with one CONFIRMED, fully paid, never-scanned seat."""
    world = setup_selling_world(
        games=[{"opponent_tier": "PREMIUM", "day_bucket": "WEEKEND", "demand_index": 85}],
        account={"tenure_years": 4},
    )
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], installment_count=1,
    )
    assert order["final_total_cents"] == 7785
    pay_order(order["id"], world["rep_headers"], 7785)
    world["order"] = read_order(order["id"])
    set_clock("2026-10-11T00:00:00Z")
    world["ops_summary"] = run_ops(world["season_id"])
    return world


def test_rolling_churn_score_applies_tenure_relief_to_lifetime_no_shows():
    """PRD 3.11: "The recency component starts from the whole number of days of silence — the elapsed seconds between the current instant and the account's `last_touchpoint_at_utc`, or its `created_at` when it has never been touched, divided by 86,400 with the fraction discarded — then takes the whole number of complete weeks in that figure, multiplies by 5, and caps the result at 20. The delinquency component is 40 when the account's `billing_status` is `LAPSED` or `WRITTEN_OFF`, 25 when it is `PAST_DUE`, and 0 otherwise. The tenure relief is the account's `tenure_years` multiplied by 3, capped at 15."
    PRD 3.11: "Its no-show component is the account's lifetime `no_show_count` multiplied by 8, capped at 40. The score is that no-show component plus the delinquency component plus the recency component, minus the tenure relief, then clamped into the range 0 through 100."

    Design: Difficulty/dual_variant_calc/account_churn_risk_rolling_and_campaign_variants_disagree_after_ops_run
    """
    world = _churn_world()

    account = read_account(world["account_id"])
    assert world["order"]["payment_status"] == "PAID_IN_FULL"
    assert read_game(world["game"]["id"])["game_status"] == "PLAYED"
    assert account["no_show_count"] == 1
    assert account["season_no_show_count"] == 1
    assert account["churn_risk_rolling"] == 16, (
        "8 no-show + 0 delinquency + 20 recency - 12 tenure relief"
    )


def test_campaign_churn_score_drops_tenure_relief_once_the_season_moves_on():
    """PRD 3.11: "Its no-show component is the account's `season_no_show_count` — this season only — multiplied by 8, capped at 40. It adds a renewal-intent penalty of 30 points when the account has no plan order in `order_status` `CONFIRMED` in this season, and 0 points when it has at least one. And it applies the tenure relief only while the season's `season_status` is `RENEWAL_OPEN`, dropping the relief entirely once the season has moved on. The score is the no-show component plus the delinquency component plus the recency component plus the intent penalty, minus whatever relief applies, clamped into the range 0 through 100."

    Design: Difficulty/dual_variant_calc/account_churn_risk_rolling_and_campaign_variants_disagree_after_ops_run
    """
    world = _churn_world()

    account = read_account(world["account_id"])
    assert read_season(world["season_id"])["season_status"] == "IN_SEASON"
    assert account["service_status"] == "ACTIVE"
    assert account["churn_risk_campaign"] == 28, (
        "8 no-show + 0 delinquency + 20 recency + 0 intent, relief dropped"
    )
    assert account["churn_risk_campaign"] != account["churn_risk_rolling"]


def _renewal_cascade_world():
    world = setup_selling_world(account={"tenure_years": 2})
    world["hold"] = place_hold(
        world["seat_ids"][0], world["account_id"], world["rep_headers"],
        hold_type="RENEWAL_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-30T00:00:00Z",
    )
    set_clock("2026-09-16T00:00:00Z")
    world["ops_summary"] = run_ops(world["season_id"])
    return world


def test_renewal_close_expires_renewal_holds_and_frees_their_seats():
    """PRD 3.11: "A season in `RENEWAL_OPEN` moves to `GENERAL_ONSALE` once the current instant has reached or passed its `renewal_deadline_utc`. Four linked effects follow. **First**, every hold in `ACTIVE` status whose `hold_type` is `RENEWAL_HOLD` and whose seat belongs to this season becomes `EXPIRED` with `released_reason` recorded as `RENEWAL_WINDOW_CLOSED`, processed in `hold_window_end_utc` ascending order with ties broken by `created_at` ascending. **Second**, because those holds left `ACTIVE`, the occupancy rule re-evaluates each affected seat — a seat that was `HELD` returns to `AVAILABLE` unless some other `ACTIVE` hold still covers the current instant — and the season's `available_seat_count`, `held_seat_count` and `assigned_seat_count` are rewritten."

    Design: Difficulty/transitive_cascade/renewal_deadline_cascade_hold_then_seat_then_priority_then_at_risk
    """
    world = _renewal_cascade_world()

    season = read_season(world["season_id"])
    assert season["season_status"] == "GENERAL_ONSALE"
    hold = read_hold(world["hold"]["id"])
    assert hold["hold_status"] == "EXPIRED"
    assert hold["released_reason"] == "RENEWAL_WINDOW_CLOSED"
    assert read_seat(world["seat_ids"][0])["seat_status"] == "AVAILABLE"
    assert season["held_seat_count"] == 0
    assert season["available_seat_count"] == 2
    assert season["total_seat_count"] == 2
    assert_season_census_invariant(season)


def test_renewal_close_clears_renewal_priority_and_moves_the_account_at_risk():
    """PRD 3.11: "**Third**, because those seats left `HELD`, every account that held one of the expired renewal holds and is now left with zero `ACTIVE` `RENEWAL_HOLD` rows has its `renewal_priority_active` flag flipped from true to false. **Fourth**, because that flag flipped to false, every such account whose `service_status` is `PROSPECT` or `ACTIVE` and which has zero plan orders in `order_status` `CONFIRMED` for this season moves to `AT_RISK`, with `at_risk_since_utc` stamped at the current instant and `churn_risk_campaign` recomputed."
    PRD 3.3: "When the hold's `hold_type` is `RENEWAL_HOLD`, the holding account's `renewal_priority_active` flag becomes true — that flag is true exactly while the account holds at least one `ACTIVE` `RENEWAL_HOLD`, and it is what the renewal campaign reads to decide who is still engaged."

    Design: Difficulty/transitive_cascade/renewal_deadline_cascade_hold_then_seat_then_priority_then_at_risk
    """
    world = _renewal_cascade_world()

    account = read_account(world["account_id"])
    assert account["renewal_priority_active"] is False
    assert account["service_status"] == "AT_RISK"
    assert account["at_risk_since_utc"] == "2026-09-16T00:00:00.000Z"


def _empty_attendance_world():
    season = create_season()
    game = create_game(season["id"])
    mint_seats(season["id"])
    plan = create_published_plan(season["id"], [game["id"]])
    open_renewal(season["id"])
    set_clock("2026-10-11T00:00:00Z")
    summary = run_ops(season["id"])
    return {"season_id": season["id"], "game_id": game["id"], "summary": summary}


def test_no_show_rate_short_circuits_to_zero_when_nobody_is_entitled():
    """PRD 3.11: "`no_show_rate_pct` is `no_show_count` multiplied by 100 and divided by `expected_attendance`, rounded half-up to exactly two decimal places — except that when `expected_attendance` is 0 the figure short-circuits to 0.00 and no division is performed."
    PRD 3.11: "The entitled seats of a game are those seats that appear in the `seat_ids` of some plan order whose `order_status` is `CONFIRMED` and whose plan's `game_ids` contains that game — orders in `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `CANCELLED` never contribute."

    Design: Difficulty/boundary_precision_check/no_show_rate_is_zero_when_expected_attendance_is_empty
    """
    world = _empty_attendance_world()

    game = validate_success(api_client.get_game(world["game_id"], OPS_HEADERS), 200)

    assert game["game_status"] == "PLAYED"
    assert game["expected_attendance"] == 0
    assert game["scanned_count"] == 0
    assert game["no_show_count"] == 0
    assert float(game["no_show_rate_pct"]) == 0.00


def test_settling_a_game_with_no_entitlements_is_reported_by_the_checkpoint():
    """PRD 3.11: "**Settling a game** happens in the ops checkpoint's game phase, for every game whose `game_date_utc` the current instant has reached or passed. The game moves from `SCHEDULED` to the terminal `PLAYED`."
    PRD 2.11: "The response is a summary object rather than an entity: it reports `ops_run_at_utc`, the resulting `season_status`, and eight counters — `expired_hold_count`, `played_game_count`, `released_package_count`, `settled_package_count`, `delinquent_order_count`, `at_risk_account_count`, `churned_account_count` and `written_off_account_count` — each counting the rows that phase actually changed during this run."

    Design: Difficulty/boundary_precision_check/no_show_rate_is_zero_when_expected_attendance_is_empty
    """
    world = _empty_attendance_world()

    assert_ops_summary(world["summary"])
    assert world["summary"]["played_game_count"] == 1
    assert read_game(world["game_id"])["no_show_count"] == 0


def test_gate_scan_updates_attendance_and_the_checkpoint_attributes_the_no_show():
    """PRD 3.11: "A successful scan appends the game's id to the seat's `scanned_game_ids`, increases the game's `scanned_count` by 1 and the entitled account's `attended_count` by 1, recomputes the game's attendance analytics, moves any `APPROVED` transfer for that seat-and-game pair to `COMPLETED`, and recomputes the entitled account's `churn_risk_rolling`."
    PRD 3.11: "`expected_attendance` is the count of entitled seats plus the hospitality heads. `scanned_count` is the number of admitted scans recorded for the game. `no_show_count` is `expected_attendance` minus `scanned_count`, floored at zero so it is never negative. `no_show_rate_pct` is `no_show_count` multiplied by 100 and divided by `expected_attendance`, rounded half-up to exactly two decimal places — except that when `expected_attendance` is 0 the figure short-circuits to 0.00 and no division is performed."
    PRD 3.11: "No-shows are then attributed to accounts: for every seat entitled to that game whose `scanned_game_ids` does not contain the game's id, the entitled account's `no_show_count` and `season_no_show_count` each increase by 1, processed in seat order — `section_code` ascending, then `row_label` ascending, then `seat_number` ascending."

    Design: Corner/calculations/calc_scan_ingest_updates_attendance_then_ops_run_attributes_the_no_show
    """
    world = setup_world_with_confirmed_order(seat_count=2)
    set_clock("2026-10-10T22:00:00Z")

    scanned_game = scan_seat(world["game"]["id"], world["seat_ids"][0])

    assert scanned_game["expected_attendance"] == 2
    assert scanned_game["scanned_count"] == 1
    assert scanned_game["no_show_count"] == 1
    assert float(scanned_game["no_show_rate_pct"]) == 50.00
    assert world["game"]["id"] in read_seat(world["seat_ids"][0])["scanned_game_ids"]
    assert read_account(world["account_id"])["attended_count"] == 1

    set_clock("2026-10-11T00:00:00Z")
    run_ops(world["season_id"])

    account = read_account(world["account_id"])
    assert account["no_show_count"] == 1
    assert account["season_no_show_count"] == 1
    assert read_game(world["game"]["id"])["game_status"] == "PLAYED"


def test_second_scan_of_the_same_seat_and_game_is_rejected():
    """PRD 3.11: "And the seat must not already have been admitted for this game — the game's id must not already appear in the seat's `scanned_game_ids` array — or the scan is refused as `ERR_DUPLICATE_SCAN`."

    Design: Corner/errors/err_second_scan_of_the_same_seat_game_returns_duplicate_scan
    """
    world = setup_world_with_confirmed_order(seat_count=1)
    set_clock("2026-10-10T22:00:00Z")
    first = scan_seat(world["game"]["id"], world["seat_ids"][0])
    assert first["scanned_count"] == 1

    response = api_client.create_scan(
        world["game"]["id"], {"seat_id": world["seat_ids"][0]}, OPS_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SCAN.value, 409)
    game = read_game(world["game"]["id"])
    assert game["scanned_count"] == 1
    assert game["expected_attendance"] == 1
    assert game["no_show_count"] == 0
    assert float(game["no_show_rate_pct"]) == 0.00
    assert read_account(world["account_id"])["attended_count"] == 1


def test_scan_of_an_unentitled_seat_is_rejected():
    """PRD 3.11: "The seat must be entitled to that game, either through a `CONFIRMED` plan order whose `seat_ids` contains the seat and whose plan's `game_ids` contains the game, or through an `APPROVED` transfer for that seat and game; an unentitled seat is `ERR_SEAT_NOT_ENTITLED`."

    Design: Corner/errors/err_scan_of_an_unentitled_seat_returns_seat_not_entitled
    """
    season = create_season()
    game = create_game(season["id"])
    seats = mint_seats(season["id"])

    response = api_client.create_scan(
        game["id"], {"seat_id": seats[0]["id"]}, OPS_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_SEAT_NOT_ENTITLED.value, 422)
    assert read_game(game["id"])["scanned_count"] == 0
    assert read_seat(seats[0]["id"])["scanned_game_ids"] == []


def test_ops_checkpoint_reports_the_rows_each_phase_changed():
    """PRD 2.11: "**P2** expires holds: every hold in `ACTIVE` status whose `hold_window_end_utc` is at or before the current instant becomes `EXPIRED`, processed in `hold_window_end_utc` ascending order with ties broken by `created_at` ascending."
    PRD 2.11: "Each checkpoint stamps the season's `last_ops_run_at_utc` with the current instant and increments the season's `version` by 1. The response is a summary object rather than an entity: it reports `ops_run_at_utc`, the resulting `season_status`, and eight counters — `expired_hold_count`, `played_game_count`, `released_package_count`, `settled_package_count`, `delinquent_order_count`, `at_risk_account_count`, `churned_account_count` and `written_off_account_count` — each counting the rows that phase actually changed during this run."

    Design: Corner/endpoints/ep_run_ops_returns_its_phase_summary_counts
    """
    world = setup_selling_world(account={"account_type": "GROUP"})
    hold = place_hold(
        world["seat_ids"][0], world["account_id"], world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-08-05T00:00:00Z",
    )
    set_clock("2026-08-06T00:00:00Z")

    summary = run_ops(world["season_id"])

    assert_ops_summary(summary)
    assert summary["expired_hold_count"] == 1
    assert summary["played_game_count"] == 0
    assert summary["delinquent_order_count"] == 0
    assert summary["season_status"] == "RENEWAL_OPEN"
    assert summary["ops_run_at_utc"] == "2026-08-06T00:00:00.000Z"
    assert read_hold(hold["id"])["hold_status"] == "EXPIRED"
    season = read_season(world["season_id"])
    assert season["available_seat_count"] == 2
    assert season["held_seat_count"] == 0
    assert season["last_ops_run_at_utc"] == "2026-08-06T00:00:00.000Z"


def test_archiving_closes_published_plans_and_cancels_open_orders():
    """PRD 3.11: "A season in `IN_SEASON` moves to the terminal `ARCHIVED` once the current instant has reached or passed the latest `game_date_utc` among that season's games plus a seven-day archive grace period. Archiving closes the books: every plan of that season whose `plan_status` is `PUBLISHED` becomes `CLOSED`; every hold still `ACTIVE` on that season's seats becomes `EXPIRED` with `released_reason` recorded as `SEASON_ARCHIVED`; every plan order against that season whose `order_status` is `DRAFT`, `PENDING_APPROVAL` or `APPROVED` becomes `CANCELLED` with `cancelled_reason` recorded as `SEASON_ARCHIVED`; the seat census is recomputed; and the season's `version` increments by 1."
    PRD 2.11: "**P8** advances the season status, applying `RENEWAL_OPEN` → `GENERAL_ONSALE` → `IN_SEASON` → `ARCHIVED` in that order and running each transition's full cascade before evaluating whether the next step also applies."

    Design: Corner/state_machines/sm_season_archive_closes_plans_and_cancels_open_orders
    """
    world = setup_selling_world()
    order = create_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )
    set_clock("2026-10-18T00:00:00Z")

    run_ops(world["season_id"])

    season = read_season(world["season_id"])
    assert season["season_status"] == "ARCHIVED"
    assert read_plan(world["plan_id"])["plan_status"] == "CLOSED"
    cancelled = read_order(order["id"])
    assert cancelled["order_status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "SEASON_ARCHIVED"
    assert read_game(world["game"]["id"])["game_status"] == "PLAYED"
    assert season["available_seat_count"] == 2
    assert season["held_seat_count"] == 0
