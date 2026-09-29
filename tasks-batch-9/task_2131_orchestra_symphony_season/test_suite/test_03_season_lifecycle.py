"""The season lifecycle: opening the renewal window, going on sale, closing, and ops runs."""

from test_helpers import (
    ARTISTIC_ADMIN,
    BOX_OFFICE,
    ApiErrorId,
    build_renewal_window_world,
    build_world,
    create_package,
    create_patron,
    inventory_for,
    read_concert,
    read_patron,
    read_season,
    read_subscription,
    run_ops,
    set_clock,
    start_season,
    validate_error,
    validate_success,
)


def test_opening_the_renewal_window_moves_programmed_concerts_to_renewal_only(api):
    """PRD 3.5: "When it succeeds, every concert of the season whose
    `programming_status` is `PROGRAMMED` or `LOCKED` and whose `sale_status` is
    still `UNANNOUNCED` moves to `RENEWAL_ONLY`, processed in ascending order of
    `performance_start_utc` with ties broken by ascending `created_at`. Concerts
    still in `DRAFT` programming are left `UNANNOUNCED`."

    Design: Corner/state_machines/advance_to_renewal_window_flips_programmed_concerts_to_renewal_only
    """
    world = build_world(concert_count=2, program_indexes=[0])
    programmed, still_draft = world.concerts

    season = validate_success(
        api.advance_season(world.season["id"], "RENEWAL_WINDOW", ARTISTIC_ADMIN)
    )
    assert season["status"] == "RENEWAL_WINDOW"
    assert season["concerts_programmed_count"] == 1

    assert read_concert(programmed["id"])["sale_status"] == "RENEWAL_ONLY"
    refreshed_draft = read_concert(still_draft["id"])
    assert refreshed_draft["sale_status"] == "UNANNOUNCED"
    assert refreshed_draft["programming_status"] == "DRAFT"


def test_skipping_straight_to_single_on_sale_is_refused(api):
    """PRD 2.6: "a season advance requires the declared from-state together with
    that transition's own preconditions"
    PRD 3.7: "Two things must hold: the season is currently in `RENEWAL_WINDOW`,
    and the logical clock has reached or passed the season's
    `renewal_deadline_utc` — an earlier instant refuses the advance with
    `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/state_machines/season_skip_to_single_on_sale_returns_invalid_transition
    """
    world = build_world()

    response = api.advance_season(world.season["id"], "SINGLE_ON_SALE", ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value, 409)

    assert read_season(world.season["id"])["status"] == "PLANNING"
    assert read_concert(world.concert["id"])["sale_status"] == "UNANNOUNCED"


def test_going_on_sale_one_second_before_the_deadline_is_refused(api):
    """PRD 3.7: "Two things must hold: the season is currently in `RENEWAL_WINDOW`,
    and the logical clock has reached or passed the season's
    `renewal_deadline_utc` — an earlier instant refuses the advance with
    `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/state_machines/advance_before_renewal_deadline_returns_invalid_transition
    """
    world = build_renewal_window_world()
    set_clock("2026-09-30T23:59:59Z")

    response = api.advance_season(world.season["id"], "SINGLE_ON_SALE", ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value, 409)

    assert read_season(world.season["id"])["status"] == "RENEWAL_WINDOW"
    assert read_concert(world.concert["id"])["sale_status"] == "RENEWAL_ONLY"


def test_renewal_window_requires_a_registered_union_agreement(api):
    """PRD 3.5: "The season must currently be in `PLANNING`; it must have exactly
    one union agreement registered against it, without which the advance is
    refused with `ERR_UNION_AGREEMENT_MISSING`; and its
    `concerts_programmed_count` must be at least 1, without which the advance is
    refused with `ERR_NO_PROGRAMMED_CONCERTS`."

    Design: Corner/state_machines/advance_without_union_agreement_returns_agreement_missing
    """
    world = build_world(with_union=False)

    response = api.advance_season(world.season["id"], "RENEWAL_WINDOW", ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_UNION_AGREEMENT_MISSING.value, 409)

    assert read_season(world.season["id"])["status"] == "PLANNING"


def test_renewal_window_requires_at_least_one_programmed_concert(api):
    """PRD 3.5: "The season must currently be in `PLANNING`; it must have exactly
    one union agreement registered against it, without which the advance is
    refused with `ERR_UNION_AGREEMENT_MISSING`; and its
    `concerts_programmed_count` must be at least 1, without which the advance is
    refused with `ERR_NO_PROGRAMMED_CONCERTS`."

    Design: Corner/state_machines/advance_without_programmed_concert_returns_no_programmed_concerts
    """
    world = build_world(program_indexes=[])

    response = api.advance_season(world.season["id"], "RENEWAL_WINDOW", ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_NO_PROGRAMMED_CONCERTS.value, 409)

    assert read_season(world.season["id"])["concerts_programmed_count"] == 0


def test_closing_a_season_expires_packages_and_closes_every_sale(api):
    """PRD 3.9: "Closing drives every concert of the season to a `sale_status` of
    `SALES_CLOSED`, moves every subscription package of the season still in
    `ACTIVE` status to `EXPIRED`, and increments the season's `version` by one."
    PRD 3.9: "Settlement moves `performance_status` to `PERFORMED`, drives
    `sale_status` to `SALES_CLOSED`, and freezes `gross_ticket_revenue_cents` as
    the sum of `amount_paid_cents` over that concert's ticket orders in `PAID`
    status."

    Design: Corner/state_machines/season_close_expires_packages_and_closes_all_sales
    """
    world = build_renewal_window_world(section_specs=[{"_balcony": True}])
    patron = create_patron(full_name="Iris Lund", email="iris-close@patron.test",
                           subscriber_since_year=2018)
    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids
    )
    validate_success(api.pay_subscription(package["id"], BOX_OFFICE))

    set_clock(world.season["renewal_deadline_utc"])
    validate_success(api.advance_season(world.season["id"], "SINGLE_ON_SALE",
                                        ARTISTIC_ADMIN))
    start_season(world.season["id"])
    validate_success(api.settle_concert(world.concert["id"], ARTISTIC_ADMIN))

    season = validate_success(
        api.advance_season(world.season["id"], "CLOSED", ARTISTIC_ADMIN)
    )
    assert season["status"] == "CLOSED"

    closed_package = read_subscription(package["id"])
    assert closed_package["status"] == "EXPIRED"
    assert closed_package["price_cents"] == 4800

    concert = read_concert(world.concert["id"])
    assert concert["sale_status"] == "SALES_CLOSED"
    assert concert["performance_status"] == "PERFORMED"
    assert concert["gross_ticket_revenue_cents"] == 0, "no single tickets were sold"
    element = inventory_for(concert, world.section["id"])
    assert element["sold_count"] == 1, "an EXPIRED package still counts as sold"


def test_ops_run_after_the_deadline_lapses_an_unpaid_package_and_frees_its_seats(api):
    """PRD 3.7: "Alongside this, every subscription package of the season still in
    `PENDING_PAYMENT` whose season's `renewal_deadline_utc` now lies strictly
    behind the logical clock moves to `LAPSED` and releases its held seats the
    same way, `renewal_priority_score` is recomputed and persisted for every
    patron holding a package in this season, and the season's `version`
    increments by one."
    PRD 2.13: "Ticket holds expire against a **housekeeping epoch counter**,
    `ops_run_index`, which lives on the season, starts at 0, and advances by
    exactly one each time an operator runs the season's ops-run checkpoint."

    Design: Corner/state_machines/run_ops_lapses_unpaid_package_and_releases_its_seats
    """
    world = build_renewal_window_world(section_specs=[{"_balcony": True}])
    patron = create_patron(full_name="Iris Lund", email="iris-lapse@patron.test",
                           subscriber_since_year=2018)
    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids,
        seat_count=3,
    )
    assert package["status"] == "PENDING_PAYMENT"

    set_clock("2026-10-02T00:00:00Z")
    season = run_ops(world.season["id"])

    assert season["ops_run_index"] == 1
    assert read_subscription(package["id"])["status"] == "LAPSED"

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 0
    assert element["sold_count"] == 0
    assert element["available_count"] == 50

    assert read_patron(patron["id"])["lifetime_cash_in_cents"] == 0
