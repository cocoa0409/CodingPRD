"""Event lifecycle gating, uniqueness of rounds and class codes, terminal
season lockdown, the event-cancellation cascade, and the season fee treasury."""
from test_helpers import (
    ApiErrorId,
    add_class,
    assert_entry,
    assert_event,
    conclude_awards,
    create_class_payload,
    create_event,
    create_event_payload,
    create_season,
    enter_driver,
    finalize_event,
    finalize_season,
    get_event,
    get_entry,
    get_season,
    pay_entry,
    register_active_driver,
    setup_active_season,
    setup_completed_event,
    setup_grid_locked_event,
    setup_open_event,
    validate_error,
    validate_success,
    withdraw_entry,
)


def test_event_creation_on_inactive_season_rejected(api, league_admin_headers):
    """PRD 3.3: "Events begin `SCHEDULED`, and the season gate applies: attempting to
    create an event in a season that is not `ACTIVE` is refused with
    `ERR_SEASON_NOT_ACTIVE`."

    Design: Corner/validations/event_create_on_inactive_season_rejected
    """
    season = create_season(name="Inactive Cup")
    add_class(season["id"])
    # Season never activated: it remains SCHEDULED.
    response = api.create_event(
        season["id"], create_event_payload(), league_admin_headers
    )
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_ACTIVE.value, 409)


def test_duplicate_round_number_rejected(api, league_admin_headers):
    """PRD 3.3: "Within an `ACTIVE` season, a `LeagueAdmin` schedules rounds as events,
    each with a `round_number` (a positive integer unique within the season — a repeat
    draws `ERR_DUPLICATE_ROUND`), an `event_date` (the reference date for driver age
    eligibility), and a `track_name`."

    Design: Corner/validations/duplicate_round_number_rejected
    """
    ctx = setup_active_season()
    create_event(ctx["season"]["id"], round_number=1)

    response = api.create_event(
        ctx["season"]["id"],
        create_event_payload(
            round_number=1, event_date="2026-09-19T00:00:00Z", track_name="Other Track"
        ),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ROUND.value, 409)


def test_duplicate_class_code_rejected(api, league_admin_headers):
    """PRD 3.1: "A `LeagueAdmin` creates them under a season with a `code` — one of
    `CADET`, `JUNIOR`, `SENIOR`, or `HEAVY`, unique within the season, with a repeat
    refused as `ERR_DUPLICATE_CLASS_CODE` — an inclusive age window from `min_age` to
    `max_age`, the `min_combined_weight_kg` a driver-and-kart combination must meet on
    the scales (a positive number), the per-event `entry_fee_cents` (a non-negative
    integer of cents), and `rental_kart_allowed`, which admits or refuses rental
    entries."

    Design: Corner/validations/duplicate_class_code_rejected
    """
    season = create_season(name="Class Cup")
    add_class(season["id"], code="SENIOR")

    response = api.create_class(
        season["id"],
        create_class_payload(
            code="SENIOR",
            min_age=18,
            max_age=40,
            min_combined_weight_kg=175.0,
            entry_fee_cents=6000,
            rental_kart_allowed=False,
        ),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLASS_CODE.value, 409)


def test_event_finalize_before_completion_rejected(api, race_director_headers):
    """PRD 3.3: "Finalization — `COMPLETED → FINALIZED` — requires that no incident of
    the event remains in `REPORTED`, `UNDER_REVIEW`, or `APPEALED`
    (`ERR_OPEN_INCIDENTS`); on finalization every result of the event's sessions that
    is still `PROVISIONAL` or `AMENDED` becomes `FINAL`, and the event counts toward
    the standings."
    PRD 2.8: "6. **State preconditions** — the target resources sit in states that
    permit the operation: the season `ACTIVE` for event creation and registration
    opening (`ERR_SEASON_NOT_ACTIVE`); the event `REGISTRATION_OPEN` for entry creation
    (`ERR_EVENT_REGISTRATION_CLOSED`); the driver `ACTIVE` for entries and practice
    bookings (`ERR_DRIVER_NOT_ACTIVE`); the kart `AVAILABLE` for entries and bookings
    (`ERR_KART_UNAVAILABLE`); no open incidents at event finalization
    (`ERR_OPEN_INCIDENTS`); no prior appeal on the incident (`ERR_APPEAL_LIMIT`); the
    session `CLOSED` for result submission and for scoring, with scoring from a
    non-closed session surfaced as `ERR_SESSION_NOT_CLOSED`; every `GRID_LOCKED` entry
    holding a result at scoring time (`ERR_RESULTS_INCOMPLETE`); every non-`WITHDRAWN`
    entry in `TECH_PASSED` at grid lock (`ERR_TECH_NOT_PASSED`); and any other invalid
    from-state for a requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/event_finalize_before_complete_rejected
    """
    ctx = setup_grid_locked_event(num_drivers=1)

    response = api.finalize_event(ctx["event"]["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    event = get_event(ctx["event"]["id"])
    assert event["status"] == "IN_PROGRESS", "a rejected finalize changes nothing"


def test_awards_concluded_season_locks_all_lifecycle_calls(api, league_admin_headers):
    """PRD 3.1: "Concluding the awards moves `FINALIZED → AWARDS_CONCLUDED`: the
    banquet is held, each class's champion is the rank-1 row of its final standings,
    and the season is locked — any further class or event creation is refused with
    `ERR_INVALID_STATE`."
    PRD 3.1: "Activation moves the season `SCHEDULED → ACTIVE` and requires at least
    one class to exist; activating a classless season fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/season_awards_concluded_terminal_lockdown
    """
    # Drive one season through its full lifecycle: one event must reach
    # FINALIZED before the season itself can be finalized.
    ctx = setup_completed_event([("A", 1, 45000, 600000)])
    finalize_event(ctx["event"]["id"])
    finalize_season(ctx["season"]["id"])
    season = conclude_awards(ctx["season"]["id"])
    assert season["status"] == "AWARDS_CONCLUDED"

    reactivated = api.activate_season(ctx["season"]["id"], league_admin_headers)
    validate_error(reactivated, ApiErrorId.ERR_INVALID_STATE.value, 409)

    new_class = api.create_class(
        ctx["season"]["id"], create_class_payload(code="JUNIOR"), league_admin_headers
    )
    validate_error(new_class, ApiErrorId.ERR_INVALID_STATE.value, 409)

    new_event = api.create_event(
        ctx["season"]["id"], create_event_payload(round_number=2), league_admin_headers
    )
    validate_error(new_event, ApiErrorId.ERR_INVALID_STATE.value, 409)

    season = get_season(ctx["season"]["id"])
    assert season["status"] == "AWARDS_CONCLUDED"


def test_event_cancel_withdraws_all_entries(api, league_admin_headers):
    """PRD 3.3: "A `LeagueAdmin` may instead cancel an event from `SCHEDULED`,
    `REGISTRATION_OPEN`, or `IN_PROGRESS`: the cancellation cascades, moving every
    child entry in `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, `TECH_PASSED`, or
    `GRID_LOCKED` to `WITHDRAWN`, refunding each withdrawn entry whose `fee_status` was
    `PAID` with `collected_fees_cents` recomputed accordingly, and excluding the event
    from all standings calculations."

    Design: Difficulty/transitive_cascade/event_cancel_withdraws_entries_refunds_fees
    """
    ctx = setup_open_event()
    entry_a = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True,
    )
    entry_b = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="B")["id"],
        ctx["race_class"]["id"], pay=True,
    )

    cancelled = validate_success(
        api.cancel_event(ctx["event"]["id"], league_admin_headers), 200
    )
    assert_event(cancelled)
    assert cancelled["status"] == "CANCELLED"

    for entry in (entry_a, entry_b):
        after = get_entry(entry["id"])
        assert after["status"] == "WITHDRAWN", (
            "hop 1: every child entry moves to WITHDRAWN on cancel"
        )


def test_event_cancel_refunds_paid_fees_to_treasury(api, league_admin_headers):
    """PRD 3.3: "A `LeagueAdmin` may instead cancel an event from `SCHEDULED`,
    `REGISTRATION_OPEN`, or `IN_PROGRESS`: the cancellation cascades, moving every
    child entry in `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, `TECH_PASSED`, or
    `GRID_LOCKED` to `WITHDRAWN`, refunding each withdrawn entry whose `fee_status` was
    `PAID` with `collected_fees_cents` recomputed accordingly, and excluding the event
    from all standings calculations."
    PRD 2.9: "The season's `collected_fees_cents` is a derived figure, defined as the
    sum of `entry_fee_cents` over all of the season's entries whose `fee_status` is
    `PAID`, recomputed as payments and refunds land: a payment adds the entry's fee to
    the total, and a refund subtracts it."

    Design: Difficulty/transitive_cascade/event_cancel_withdraws_entries_refunds_fees
    """
    ctx = setup_open_event()
    entry_a = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True,
    )
    entry_b = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="B")["id"],
        ctx["race_class"]["id"], pay=True,
    )
    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 10000, "two 5000-cent fees settled"

    validate_success(api.cancel_event(ctx["event"]["id"], league_admin_headers), 200)

    for entry in (entry_a, entry_b):
        after = get_entry(entry["id"])
        assert after["fee_status"] == "REFUNDED", (
            "hop 2: each withdrawn PAID entry is refunded"
        )
    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 0, (
        "the treasury gives back every refunded fee (was 10000 before cancel)"
    )


def test_payment_adds_fee_to_season_treasury(api, league_admin_headers):
    """PRD 3.3: "Settling the fee — by the owning driver or a `LeagueAdmin` — moves
    `fee_status` from `UNPAID` to `PAID` and adds the fee to the season's
    `collected_fees_cents`."
    PRD 2.9: "The season's `collected_fees_cents` is a derived figure, defined as the
    sum of `entry_fee_cents` over all of the season's entries whose `fee_status` is
    `PAID`, recomputed as payments and refunds land: a payment adds the entry's fee to
    the total, and a refund subtracts it."

    Design: Difficulty/compensating_invariant/pay_withdraw_conserves_collected_fees
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"],
    )
    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 0, "an UNPAID entry contributes nothing"

    paid = pay_entry(entry["id"])
    assert_entry(paid)
    assert paid["fee_status"] == "PAID"

    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 5000, (
        "the payment adds the entry's fee to the treasury"
    )


def test_withdrawal_refunds_fee_and_restores_treasury(api, league_admin_headers):
    """PRD 3.3: "A withdrawn entry whose fee was `PAID` is refunded — `fee_status`
    becomes `REFUNDED` and the season total gives the fee back — and a rental entry's
    kart assignment for the event is released."
    PRD 2.9: "The season's `collected_fees_cents` is a derived figure, defined as the
    sum of `entry_fee_cents` over all of the season's entries whose `fee_status` is
    `PAID`, recomputed as payments and refunds land: a payment adds the entry's fee to
    the total, and a refund subtracts it."

    Design: Difficulty/compensating_invariant/pay_withdraw_conserves_collected_fees
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True,
    )
    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 5000

    withdrawn = withdraw_entry(entry["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["fee_status"] == "REFUNDED"

    season = get_season(ctx["season"]["id"])
    assert season["collected_fees_cents"] == 0, (
        "forward pay (+5000) and compensating refund (-5000) conserve the ledger"
    )
