"""The two economic-impact variants: the forward projection the checkpoint keeps
and the chronological settlement finalisation writes beside it."""
from test_helpers import (
    TEST_USERS,
    api_client,
    check_in,
    close_registration,
    create_accommodation_block,
    create_athlete,
    finalize_impact,
    get_edition,
    get_stay,
    pay_fees,
    reserve_stay,
    screen_athlete,
    setup_open_edition,
    start_competition,
    complete_competition,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]


def _completed_edition_with_one_arrival() -> dict:
    """Three athletes register and pay; one is screened, arrives on site and stays
    five real nights; the edition is then walked to `COMPLETED`.
    """
    ctx = setup_open_edition(edition={"municipal_support_cents": 500000})
    edition_id = ctx["edition"]["id"]
    names = ["Ada Frost", "Ben Hoyt", "Cleo Vance"]
    athletes = [create_athlete(edition_id, full_name=name) for name in names]
    for athlete in athletes:
        pay_fees(athlete["id"], 9500)
    screen_athlete(athletes[0]["id"])
    block = create_accommodation_block(
        edition_id, name="Village Block A", bed_capacity=4, nightly_rate_cents=8000
    )
    stay = reserve_stay(
        athletes[0]["id"], block["id"],
        check_in_date="2026-09-10", check_out_date="2026-09-15",
    )
    close_registration(edition_id)
    start_competition(edition_id)
    check_in(athletes[0]["id"])
    complete_competition(edition_id)
    return {"edition_id": edition_id, "athletes": athletes, "stay": stay}


def test_the_projection_counts_every_live_registrant_at_four_assumed_nights():
    """PRD §3.9: "Four figures are fixed for both: each competing athlete is assumed to
    bring accompanying visitors at a factor of one point eight heads per athlete; a
    projected stay is four nights; each head is assumed to spend eighteen thousand five
    hundred cents per day; and the regional output multiplier applied to direct spend is
    one point four five."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."
    PRD §3.9: "Visitor heads are that count multiplied by one point eight, and this
    intermediate figure is deliberately left unrounded and may be fractional."
    PRD §3.9: "Direct spend is the sum of athlete heads and visitor heads, multiplied by
    the daily spend of eighteen thousand five hundred cents and by the projected four
    nights, and that product is rounded to whole cents with a half cent going up."
    PRD §3.9: "`provisional_impact_cents` is then that rounded direct spend multiplied
    by one point four five and rounded again to whole cents, half up."
    PRD §3.9: "The final variant is computed once, when a `SponsorLiaison` finalises the
    impact of a `COMPLETED` edition, and it replaces projections with observed data."

    The checkpoint's variant takes all three athletes who have entered and not
    fallen away, adds 3 x 1.8 = 5.4 unrounded visitor heads, and spends 8.4 heads
    x 18500 x 4 nights = 621600 cents of direct spend, which the 1.45 regional
    multiplier lifts to 901320.  The settled figure is still absent.

    Design: Difficulty/dual_variant_calc/economic_impact_provisional_versus_final_divergence
    """
    ctx = _completed_edition_with_one_arrival()

    edition = get_edition(ctx["edition_id"])

    assert edition["status"] == "COMPLETED"
    assert edition["provisional_impact_cents"] == 901320
    assert edition["final_impact_cents"] is None


def test_finalisation_replaces_assumed_heads_and_nights_with_observed_ones():
    """PRD §3.9: "Its head count, reported as `checked_in_heads`, counts only athletes
    whose `registration_status` is `CHECKED_IN` — nobody who merely registered."
    PRD §3.9: "Instead of assuming four nights it uses `actual_room_nights`, the sum of
    the `nights` of every village stay whose accommodation block belongs to this edition
    and whose status is `CHECKED_IN` or `COMPLETED`, accumulated over the stays in
    ascending `check_in_date` order and, where two stays share a check-in date, in
    ascending `created_at` order."
    PRD §3.9: "Nights per head is `actual_room_nights` divided by the head count, or by
    one where the head count is zero so that the division is always defined; that
    quotient is kept as an exact fraction and is not rounded before it is used."
    PRD §3.9: "Visitor heads are again the head count multiplied by one point eight,
    unrounded."
    PRD §3.9: "Direct spend is the sum of athlete heads and visitor heads, multiplied by
    eighteen thousand five hundred cents and by that exact nights-per-head quotient,
    rounded to whole cents half up; and `final_impact_cents` is that figure multiplied
    by one point four five, rounded to whole cents half up."
    PRD §3.9: "The finalising call moves the edition `COMPLETED` → `IMPACT_FINALIZED`,
    writes `final_impact_cents`, and deliberately leaves `provisional_impact_cents`
    exactly as the last checkpoint run left it, so the projection and the settled figure
    remain side by side for comparison."

    The settled variant counts only the one athlete who actually arrived and
    replays their real five nights: 5 / 1 nights per head, 2.8 heads, 2.8 x 18500
    x 5 = 259000 direct, x 1.45 = 375550.  The projection is deliberately left
    beside it rather than overwritten, so the two figures diverge on one row.

    Design: Difficulty/dual_variant_calc/economic_impact_provisional_versus_final_divergence
    """
    ctx = _completed_edition_with_one_arrival()

    finalized = finalize_impact(ctx["edition_id"])

    assert finalized["status"] == "IMPACT_FINALIZED"
    assert finalized["final_impact_cents"] == 375550
    assert finalized["provisional_impact_cents"] == 901320
    assert finalized["final_impact_cents"] != finalized["provisional_impact_cents"]


def test_the_impact_reading_exposes_the_three_counts_behind_both_variants():
    """PRD §3.9: "That reading reports the `provisional_impact_cents` and
    `final_impact_cents` figures, the `sponsorship_recognized_cents` and
    `municipal_support_cents` ledgers, and the three underlying counts —
    `registered_heads`, `checked_in_heads` and `actual_room_nights` — so that the
    projection can be audited without recomputing it."
    PRD §3.9: "Its head count, reported as `registered_heads`, is the number of athletes
    in the edition whose `registration_status` is `PENDING_PAYMENT`, `REGISTERED` or
    `CHECKED_IN` — everyone who has entered and not fallen away."
    PRD §3.9: "Its head count, reported as `checked_in_heads`, counts only athletes
    whose `registration_status` is `CHECKED_IN` — nobody who merely registered."
    PRD §3.9: "Instead of assuming four nights it uses `actual_room_nights`, the sum of
    the `nights` of every village stay whose accommodation block belongs to this edition
    and whose status is `CHECKED_IN` or `COMPLETED`, accumulated over the stays in
    ascending `check_in_date` order and, where two stays share a check-in date, in
    ascending `created_at` order."
    PRD §3.8: "When the clock's date reaches or passes a `CHECKED_IN` stay's
    `check_out_date`, the ops-run checkpoint closes it `CHECKED_IN` → `COMPLETED`, again
    leaving `reserved_bed_nights` untouched, since the nights were genuinely consumed."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."

    The audit read reports the inputs, not just the money: three registered heads
    against one checked-in head, and five actual room nights from the stay the
    checkpoint closed on departure day.

    Design: Difficulty/dual_variant_calc/economic_impact_provisional_versus_final_divergence
    """
    ctx = _completed_edition_with_one_arrival()
    finalize_impact(ctx["edition_id"])

    reading = validate_success(
        api_client.get_economic_impact(ctx["edition_id"], ADMIN)
    )

    assert reading["registered_heads"] == 3
    assert reading["checked_in_heads"] == 1
    assert reading["actual_room_nights"] == 5
    assert reading["municipal_support_cents"] == 500000
    assert reading["provisional_impact_cents"] == 901320
    assert reading["final_impact_cents"] == 375550
    stay = get_stay(ctx["stay"]["id"])
    assert stay["status"] == "COMPLETED"
    assert stay["nights"] == 5
