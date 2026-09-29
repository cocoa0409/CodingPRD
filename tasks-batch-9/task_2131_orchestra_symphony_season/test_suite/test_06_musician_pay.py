"""Musician settlement: provisional pay at publication, final pay at clock-out."""

from test_helpers import (
    ORCHESTRA_MANAGER,
    add_engagement,
    build_world,
    clock_service,
    create_musician,
    create_service,
    publish_service,
    read_engagement,
    read_musician,
    read_service,
    setup_published_service,
    validate_success,
)

UNION_TERMS = {
    "scale_service_fee_cents": 20000,
    "max_service_minutes": 150,
    "overtime_rate_cents_per_minute": 400,
    "min_rest_minutes_between_services": 90,
    "max_services_per_day": 2,
    "doubling_premium_bp": 1250,
    "mandatory_break_minutes": 20,
    "principal_premium_bp": 2000,
}

PRINCIPAL_HORN = {
    "full_name": "Ada Reed",
    "instrument": "HORN",
    "is_principal": True,
    "overscale_bp": 1000,
}


def _principal_horn_on_a_published_service():
    """Publish a 180-minute service carrying one principal horn doubling once."""
    return setup_published_service(
        world_kwargs={"union_overrides": UNION_TERMS},
        service_overrides={
            "scheduled_start_utc": "2026-11-04T14:00:00Z",
            "scheduled_end_utc": "2026-11-04T17:00:00Z",
            "minimum_complement": 1,
            "break_minutes": 30,
        },
        musician_specs=(PRINCIPAL_HORN,),
        doubling_counts=[1],
    )


def test_publication_prices_the_engagement_from_scale_plus_premiums_only(api):
    """PRD 3.3: "The premium in basis points is the sum of three additive terms: the
    agreement's `principal_premium_bp` if the player's `is_principal` is true and
    nothing if it is false, plus the player's own `overscale_bp`, plus the
    engagement's `doubling_count` multiplied by the agreement's
    `doubling_premium_bp`."
    PRD 3.3: "The **provisional** figure, `provisional_pay_cents`, is exactly that
    base pay: scheduled minutes are ignored entirely at publication and no
    overtime is anticipated."
    PRD 3.3: "When publication succeeds, every engagement of the service still in
    `CONFIRMED` status is priced provisionally, `compliance_status` is set to
    `COMPLIANT`, `provisional_service_cost_cents` is set to the sum of those
    provisional figures, each of those players has `services_charged_ytd`
    incremented by one and `ytd_earnings_cents` increased by their own provisional
    figure, the parent concert's promotion condition is re-evaluated, and the
    concert's `readiness_posture` is recomputed."

    Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_pay_diverge
    """
    world = _principal_horn_on_a_published_service()

    engagement = read_engagement(world.engagement["id"])
    assert engagement["provisional_pay_cents"] == 28500, (
        "20000 scale times 1 + 4250bp of additive premium (2000 + 1000 + 1250)"
    )
    assert engagement["final_pay_cents"] is None, "no overtime is anticipated yet"
    assert engagement["status"] == "CONFIRMED"

    service = read_service(world.service["id"])
    assert service["status"] == "PUBLISHED"
    assert service["provisional_service_cost_cents"] == 28500
    assert service["final_service_cost_cents"] is None
    assert service["compliance_status"] == "COMPLIANT"

    musician = read_musician(world.musician["id"])
    assert musician["ytd_earnings_cents"] == 28500
    assert musician["services_charged_ytd"] == 1


def test_clock_out_reprices_the_same_engagement_with_clocked_overtime(api):
    """PRD 3.3: "`final_pay_cents` is the same base pay computed at publication plus
    `overtime_minutes` multiplied by the agreement's
    `overtime_rate_cents_per_minute`."
    PRD 3.3: "Each engagement so priced moves from `CONFIRMED` to `SETTLED`, each
    player's `ytd_earnings_cents` is increased by the difference between that
    engagement's `final_pay_cents` and its `provisional_pay_cents`, and the
    service's `final_service_cost_cents` is set to the sum of `final_pay_cents`
    over the settled engagements."
    PRD 3.3: "Worked minutes are the number of minutes from `actual_start_utc` to
    `actual_end_utc` less the service's `break_minutes`."

    Design: Difficulty/dual_variant_calc/engagement_provisional_vs_final_pay_diverge
    """
    world = _principal_horn_on_a_published_service()

    settled_service = validate_success(
        api.clock_rehearsal(
            world.service["id"], "2026-11-04T14:00:00Z", "2026-11-04T17:20:00Z",
            ORCHESTRA_MANAGER,
        )
    )
    assert settled_service["status"] == "COMPLETED"

    engagement = read_engagement(world.engagement["id"])
    assert engagement["provisional_pay_cents"] == 28500
    assert engagement["overtime_minutes"] == 20, "200 clocked minutes less a 30-minute break is 170"
    assert engagement["final_pay_cents"] == 36500, "28500 base plus 20 minutes at 400 cents"
    assert engagement["status"] == "SETTLED"
    assert engagement["final_pay_cents"] > engagement["provisional_pay_cents"]

    service = read_service(world.service["id"])
    assert service["provisional_service_cost_cents"] == 28500
    assert service["final_service_cost_cents"] == 36500

    musician = read_musician(world.musician["id"])
    assert musician["ytd_earnings_cents"] == 36500
    assert musician["services_charged_ytd"] == 1


def _two_published_services_for_one_principal_horn():
    world = build_world(union_overrides=UNION_TERMS)
    player = create_musician(**PRINCIPAL_HORN)

    first = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T17:00:00Z",
        minimum_complement=1, break_minutes=30,
    )
    engagement_one = add_engagement(first["id"], player["id"], doubling_count=1)
    publish_service(first["id"])

    second = create_service(
        world.concert["id"], world.venue["id"], service_type="DRESS_REHEARSAL",
        scheduled_start_utc="2026-11-05T14:00:00Z",
        scheduled_end_utc="2026-11-05T17:00:00Z",
        minimum_complement=1, break_minutes=30,
    )
    engagement_two = add_engagement(second["id"], player["id"], doubling_count=1)
    publish_service(second["id"])

    return player, (first, engagement_one), (second, engagement_two)


def test_worked_minutes_exactly_at_the_cap_produce_no_overtime(api):
    """PRD 3.3: "`overtime_minutes` is the amount by which worked minutes exceed the
    agreement's `max_service_minutes`, or zero when they do not exceed it; the
    comparison is strict, so worked minutes exactly equal to `max_service_minutes`
    produce zero overtime."

    Design: Difficulty/boundary_precision_check/overtime_at_exactly_max_service_minutes
    """
    player, (first, engagement_one), (second, _) = (
        _two_published_services_for_one_principal_horn()
    )
    assert read_engagement(engagement_one["id"])["provisional_pay_cents"] == 28500

    clock_service(first["id"], "2026-11-04T14:00:00Z", "2026-11-04T17:00:00Z")

    settled = read_engagement(engagement_one["id"])
    assert settled["overtime_minutes"] == 0, (
        "180 clocked minutes less a 30-minute break is exactly the 150-minute cap"
    )
    assert settled["final_pay_cents"] == 28500
    assert settled["final_pay_cents"] == settled["provisional_pay_cents"]
    assert read_service(first["id"])["final_service_cost_cents"] == 28500


def test_one_minute_past_the_cap_adds_exactly_one_overtime_minute(api):
    """PRD 3.3: "`overtime_minutes` is the amount by which worked minutes exceed the
    agreement's `max_service_minutes`, or zero when they do not exceed it; the
    comparison is strict, so worked minutes exactly equal to `max_service_minutes`
    produce zero overtime."
    PRD 3.3: "Overtime is a flat per-minute rate and is never scaled by the premium
    — a principal and a rank-and-file player earn the identical overtime for the
    same minute."

    Design: Difficulty/boundary_precision_check/overtime_at_exactly_max_service_minutes
    """
    player, (first, _), (second, engagement_two) = (
        _two_published_services_for_one_principal_horn()
    )

    clock_service(first["id"], "2026-11-04T14:00:00Z", "2026-11-04T17:00:00Z")
    clock_service(second["id"], "2026-11-05T14:00:00Z", "2026-11-05T17:01:00Z")

    settled = read_engagement(engagement_two["id"])
    assert settled["overtime_minutes"] == 1, "181 clocked minutes less 30 is 151"
    assert settled["final_pay_cents"] == 28900, (
        "28500 base plus one flat overtime minute at 400 cents, not scaled by the premium"
    )

    musician = read_musician(player["id"])
    assert musician["ytd_earnings_cents"] == 57400
    assert musician["services_charged_ytd"] == 2


def test_premiums_are_added_not_compounded(api):
    """PRD 3.3: "These terms are added, never compounded — a principal on 2000 basis
    points who doubles once at 1250 basis points carries a premium of 3250 basis
    points, not a product of two uplifts."
    PRD 3.3: "Base pay in cents is the agreement's `scale_service_fee_cents`
    multiplied by 10000 plus that premium, divided by 10,000, and rounded half up
    to a whole cent."

    Design: Corner/calculations/musician_premiums_are_additive_not_compounded
    """
    world = setup_published_service(
        world_kwargs={
            "union_overrides": {
                "scale_service_fee_cents": 20000,
                "doubling_premium_bp": 1250,
                "principal_premium_bp": 2000,
                "mandatory_break_minutes": 20,
            }
        },
        service_overrides={
            "scheduled_start_utc": "2026-11-04T14:00:00Z",
            "scheduled_end_utc": "2026-11-04T15:00:00Z",
            "minimum_complement": 1,
            "break_minutes": 0,
        },
        musician_specs=(
            {
                "full_name": "Ada Reed",
                "instrument": "CLARINET",
                "is_principal": True,
                "overscale_bp": 1000,
            },
        ),
        doubling_counts=[2],
    )

    engagement = read_engagement(world.engagement["id"])
    assert engagement["provisional_pay_cents"] == 31000, (
        "2000 principal + 1000 overscale + 2 x 1250 doubling = 5500bp on 20000 scale"
    )
    assert engagement["provisional_pay_cents"] != 33825, (
        "compounding the three uplifts instead of adding them is wrong"
    )
    assert read_service(world.service["id"])["provisional_service_cost_cents"] == 31000

    musician = read_musician(world.musician["id"])
    assert musician["ytd_earnings_cents"] == 31000
    assert musician["services_charged_ytd"] == 1
