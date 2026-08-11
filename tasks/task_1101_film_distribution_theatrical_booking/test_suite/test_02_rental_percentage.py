"""Weekly rental percentage: decay, floor, and aggregate override (PRD §3.3, §3.4)."""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_distributor_film_theatre_screen,
    setup_accepted_booking,
    setup_proposed_booking,
    setup_in_play_agreement,
    setup_distributor,
    setup_film,
    setup_theatre,
    setup_screen,
    run_settled_week,
    close_week_with_reports,
    settle_latest,
    create_aggregate_deal_payload,
    create_dcp_shipment_payload,
    create_kdm_key_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_initial_current_week_rental_pct_is_week_one(api):
    """PRD §3.3: "The rental rate applied to each week's settlement is the agreement's
    `current_week_rental_pct`: start from `week_one_rental_pct`, subtract
    `rental_decay_per_week` once for each week already played, and take the greater of
    that difference and `floor_pct`, expressed at 4 decimal places with round-half-up."
    With zero weeks played the figure is max(floor, week_one) = 0.60 here.

    Design: Difficulty/combinatorial_formula/rental_pct_mode_a_multi_input_conditional_floor_and_aggregate_branch
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_accepted_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        week_one_rental_pct=0.60, rental_decay_per_week=0.05, floor_pct=0.30,
    )
    assert ba["weeks_played"] == 0
    assert ba["current_week_rental_pct"] == 0.60, (
        f"expected 0.60 (no decay at weeks_played=0), got {ba['current_week_rental_pct']}"
    )


def test_decay_applies_once_per_settled_week(api):
    """PRD §3.3: "start from `week_one_rental_pct`, subtract `rental_decay_per_week` once
    for each week already played, and take the greater of that difference and `floor_pct`".
    PRD §3.7: "Both actions advance the agreement's `weeks_played` by one and trigger
    recomputation of `current_week_rental_pct` for the coming week."
    After one settled week: max(0.30, 0.60 - 0.05*1) = 0.55.

    Design: Difficulty/combinatorial_formula/rental_pct_mode_a_multi_input_conditional_floor_and_aggregate_branch
    """
    env = setup_in_play_agreement(
        booking_overrides={
            "min_weeks_committed": 6,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
        }
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    run_settled_week(did, baid, 0)
    ba = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert ba["weeks_played"] == 1
    assert ba["current_week_rental_pct"] == 0.55, (
        f"expected 0.55 after one settled week, got {ba['current_week_rental_pct']}"
    )


def test_floor_binds_after_decay_exhausts_margin(api):
    """PRD §3.3: "take the greater of that difference and `floor_pct`, expressed at 4
    decimal places with round-half-up."
    After six settled weeks: max(0.30, 0.60 - 0.05*6) = max(0.30, 0.30) = 0.30 — the
    floor is reached exactly and never dips below.

    Design: Difficulty/combinatorial_formula/rental_pct_mode_a_multi_input_conditional_floor_and_aggregate_branch
    """
    env = setup_in_play_agreement(
        booking_overrides={
            "min_weeks_committed": 6,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
        }
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    for week in range(6):
        run_settled_week(did, baid, week)
    ba = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert ba["weeks_played"] == 6
    assert ba["current_week_rental_pct"] == 0.30, (
        f"expected floor 0.30 to bind after six settled weeks, "
        f"got {ba['current_week_rental_pct']}"
    )


def test_active_aggregate_deal_overrides_decay_and_floor(api):
    """PRD §3.4: "The effective rental percentage is simply `aggregate_rental_pct` —
    flat, with no weekly decay and no floor; `weeks_played`, `floor_pct`, and
    `rental_decay_per_week` are all ignored."
    PRD §3.3: "the aggregate-deal override of §3.4 replaces this computation entirely
    when it applies."

    Design: Difficulty/combinatorial_formula/rental_pct_mode_a_multi_input_conditional_floor_and_aggregate_branch
    """
    distributor = setup_distributor()
    did = distributor["id"]
    film = setup_film(did)
    t1 = setup_theatre(did, name="T1", circuit="Alamo")
    t2 = setup_theatre(did, name="T2", circuit="Alamo")
    s1 = setup_screen(did, t1["id"], auditorium_label="A1")
    s2 = setup_screen(did, t2["id"], auditorium_label="A1")
    deal = get_success_data(api.create_aggregate_deal(
        did,
        create_aggregate_deal_payload(
            film["id"], circuit="Alamo", aggregate_rental_pct=0.50,
            min_screens=2, aggregate_house_allowance_cents=200000,
        ),
        BOOKER,
    ))
    ba1 = setup_accepted_booking(
        did, film["id"], t1["id"], s1["id"],
        week_one_rental_pct=0.60, rental_decay_per_week=0.05, floor_pct=0.30,
        aggregate_deal_id=deal["id"],
    )
    setup_accepted_booking(
        did, film["id"], t2["id"], s2["id"],
        week_one_rental_pct=0.60, rental_decay_per_week=0.05, floor_pct=0.30,
        aggregate_deal_id=deal["id"],
    )
    deal = validate_success(api.activate_aggregate_deal(did, deal["id"], BOOKER), 200)
    assert deal["deal_status"] == "ACTIVE"

    # Walk BA1 through the print pipeline so the clock can move it to IN_PLAY.
    ship = get_success_data(api.create_dcp_shipment(
        did, ba1["id"], create_dcp_shipment_payload(tracking_number="TN-AGG-1"), BOOKER
    ))
    get_success_data(api.mark_dcp_delivered(did, ba1["id"], ship["id"], EXHIBITOR))
    get_success_data(api.create_kdm_key(
        did, ba1["id"], create_kdm_key_payload(), BOOKER
    ))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    ba1_live = validate_success(api.get_booking_agreement(did, ba1["id"], BOOKER), 200)
    assert ba1_live["deal_status"] == "IN_PLAY", (
        f"Setup failed: expected IN_PLAY, got {ba1_live['deal_status']}"
    )

    # One settled week triggers the recomputation; the aggregate path replaces
    # the decayed 0.55 with the flat 0.50.
    close_week_with_reports(did, 0, [(ba1["id"], 500000, 2000)])
    settle_latest(did, ba1["id"])

    ba1_after = validate_success(api.get_booking_agreement(did, ba1["id"], BOOKER), 200)
    assert ba1_after["weeks_played"] == 1
    assert ba1_after["current_week_rental_pct"] == 0.50, (
        f"aggregate override must replace decayed 0.55 with flat 0.50, "
        f"got {ba1_after['current_week_rental_pct']}"
    )
