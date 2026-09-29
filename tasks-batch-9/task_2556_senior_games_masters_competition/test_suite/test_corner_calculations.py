"""Formula breadth: inclusive comparison boundaries, input-set filtering, the
single rounding step, unconditional constants and per-epoch recomputation."""
from test_helpers import (
    TEST_USERS,
    advance_slot,
    api_client,
    confirm_assignment,
    create_assignment,
    create_athlete,
    create_certified_official,
    create_entry,
    create_session_slot,
    create_sport_event,
    create_venue,
    get_athlete,
    get_edition,
    get_entry,
    get_event,
    get_result,
    ops_run,
    pay_fees,
    seed_event,
    set_clock,
    setup_accepted_entry,
    setup_open_edition,
    submit_result,
    validate_success,
    verify_result,
    REGISTRATION_OFFICER_USER_ID,
)

SPONSOR = TEST_USERS["sponsor_liaison_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]


def _three_marks_awaiting_verification():
    """Two events of one LOWER_IS_BETTER sport — one carrying a national
    standard of 16.500, one carrying none — each with completed blocks holding
    submitted marks: 16.500 and 16.600 on the standard-bearing event, 16.500 on
    the event without a standard.
    """
    base = setup_open_edition(
        event={"national_qualifying_standard": 16.5, "min_entries_to_stage": 1}
    )
    ed, sp, ev_a = base["edition"], base["sport"], base["event"]
    ev_b = create_sport_event(
        sp["id"], ed["id"], event_code="T200M", min_entries_to_stage=1
    )
    venue = create_venue(ed["id"], name="North Oval", competition_area_count=4)
    first = setup_accepted_entry(ed["id"], ev_a, full_name="Ada Fenn")
    second = setup_accepted_entry(ed["id"], ev_a, full_name="Bo Marsh")
    third = setup_accepted_entry(ed["id"], ev_b, full_name="Cara Idris")
    seed_event(ev_a["id"])
    seed_event(ev_b["id"])
    off_a = create_certified_official(ed["id"], sp["sport_code"], full_name="Dana Reyes")
    off_b = create_certified_official(ed["id"], sp["sport_code"], full_name="Eli Novak")
    slot_a = create_session_slot(venue["id"], ev_a["id"], teardown_buffer_minutes=0)
    slot_b = create_session_slot(venue["id"], ev_b["id"], teardown_buffer_minutes=0)
    asg_a = create_assignment(off_a["id"], slot_a["id"])
    asg_b = create_assignment(off_b["id"], slot_b["id"])
    confirm_assignment(asg_a["id"], off_a["id"])
    confirm_assignment(asg_b["id"], off_b["id"])
    set_clock("2026-09-12T09:05:00Z")
    advance_slot(slot_a["id"], "IN_PROGRESS")
    advance_slot(slot_b["id"], "IN_PROGRESS")
    res_1 = submit_result(
        first["entry"]["id"], slot_a["id"], off_a["id"], mark_value=16.5, placement=1
    )
    res_2 = submit_result(
        second["entry"]["id"], slot_a["id"], off_a["id"], mark_value=16.6, placement=2
    )
    res_3 = submit_result(
        third["entry"]["id"], slot_b["id"], off_b["id"], mark_value=16.5, placement=1
    )
    advance_slot(slot_a["id"], "COMPLETED")
    advance_slot(slot_b["id"], "COMPLETED")
    return {"event_with_standard": ev_a, "event_without": ev_b,
            "res_1": res_1, "res_2": res_2, "res_3": res_3}


def test_national_qualification_admits_an_exactly_equal_mark_and_null_disables_it(clock_at_epoch):
    """PRD §3.7: "Otherwise the sport's `mark_direction` decides the comparison: under
    `LOWER_IS_BETTER` the flag is true when the `mark_value` is at or below the
    standard, and under `HIGHER_IS_BETTER` it is true when the `mark_value` is at or
    above the standard."
    PRD §3.7: "Meeting the standard exactly qualifies in both directions."
    PRD §3.7: "When that standard is null the event has no national pathway and
    `national_qualifying` is false."
    PRD §3.7: "The flag stays false for as long as a mark is merely `SUBMITTED`; it is
    only computed at verification, on both branches alike."

    A mark equal to the standard qualifies under LOWER_IS_BETTER, a slower one
    does not, and an event with no standard yields false for the same mark.

    Design: Corner/calculations/corner_calculation_national_qualification_flag_inclusive_boundary_and_null_standard
    """
    ctx = _three_marks_awaiting_verification()

    # The flag is seeded false at submission and only settled on verification.
    assert ctx["res_1"]["national_qualifying"] is False

    first = verify_result(ctx["res_1"]["id"])
    second = verify_result(ctx["res_2"]["id"])
    third = verify_result(ctx["res_3"]["id"])

    # 16.500 is at the standard, and at-or-below qualifies.
    assert first["national_qualifying"] is True
    # 16.600 is past a 16.500 standard.
    assert second["national_qualifying"] is False
    # Identical mark, but that event has no national pathway at all.
    assert third["national_qualifying"] is False

    assert first["status"] == "RECORD_PENDING"
    assert first["verified_by_user_id"] == REGISTRATION_OFFICER_USER_ID
    assert get_event(ctx["event_without"]["id"])["national_qualifying_standard"] is None

    # Verification settles a flag; it does not rewrite the performance.
    stored = get_result(ctx["res_1"]["id"])
    assert float(stored["mark_value"]) == 16.5
    assert stored["placement"] == 1


def test_a_withdrawn_entry_leaves_both_the_entry_count_and_the_fee_base(clock_at_epoch):
    """PRD §3.2: "**Step one** counts the athlete's live entries: those in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED` or `ACCEPTED`, which becomes
    `entry_count`; entries on `MEDICAL_HOLD`, `REJECTED` or `WITHDRAWN` are excluded."
    PRD §3.2: "**Step two** sums the `entry_fee_cents` of the sport event behind each of
    those same entries into `event_fees_cents`, in whole cents with no rounding."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    Withdrawing one of three entries settles at 22800 instead of 30950 — the
    dropped fee also carries the total back under the surcharge threshold.

    Design: Corner/calculations/corner_calculation_fee_input_set_excludes_withdrawn_entries
    """
    base = setup_open_edition(event={"entry_fee_cents": 6000, "min_entries_to_stage": 1})
    ed, sp, ev_a = base["edition"], base["sport"], base["event"]
    ev_b = create_sport_event(
        sp["id"], ed["id"], event_code="T200M", entry_fee_cents=8500, min_entries_to_stage=1
    )
    ev_c = create_sport_event(
        sp["id"], ed["id"], event_code="T400M", entry_fee_cents=7000, min_entries_to_stage=1
    )

    quitter = create_athlete(ed["id"], full_name="Ada Fenn")
    kept_a = create_entry(quitter["id"], ev_a["id"])
    kept_b = create_entry(quitter["id"], ev_b["id"])
    dropped = create_entry(quitter["id"], ev_c["id"])

    stayer = create_athlete(ed["id"], full_name="Bo Marsh")
    for event in (ev_a, ev_b, ev_c):
        create_entry(stayer["id"], event["id"])

    validate_success(
        api_client.withdraw_sport_entry(
            dropped["id"], OFFICER, {"reason": "dropping the 400m"}
        )
    )

    settled = pay_fees(quitter["id"], 22800)
    assert settled["fee_total_cents"] == 22800
    assert settled["fee_paid_cents"] == 22800
    assert get_athlete(quitter["id"])["registration_status"] == "REGISTERED"

    dropped_breakdown = settled["fee_breakdown"]
    assert dropped_breakdown["entry_count"] == 2
    assert dropped_breakdown["event_fees_cents"] == 14500
    assert dropped_breakdown["subtotal_cents"] == 24000
    assert float(dropped_breakdown["discount_pct"]) == 0.05
    assert dropped_breakdown["discount_cents"] == 1200
    assert dropped_breakdown["discounted_cents"] == 22800
    assert dropped_breakdown["surcharge_cents"] == 0

    intact = pay_fees(stayer["id"], 30950)
    assert intact["fee_total_cents"] == 30950
    kept_breakdown = intact["fee_breakdown"]
    assert kept_breakdown["entry_count"] == 3
    assert kept_breakdown["event_fees_cents"] == 21500
    assert kept_breakdown["subtotal_cents"] == 31000
    assert kept_breakdown["discount_cents"] == 1550
    assert kept_breakdown["discounted_cents"] == 29450
    assert kept_breakdown["surcharge_cents"] == 1500

    # The 8150-cent gap is not merely the dropped event's 7000: the withdrawal
    # also took discounted_cents from 29450 to 22800, below the 25000 threshold,
    # cancelling the 1500 surcharge.
    assert intact["fee_total_cents"] - settled["fee_total_cents"] == 8150
    assert kept_breakdown["surcharge_cents"] - dropped_breakdown["surcharge_cents"] == 1500

    assert get_entry(dropped["id"])["status"] == "WITHDRAWN"
    assert get_entry(kept_a["id"])["status"] == "SUBMITTED"
    assert get_entry(kept_b["id"])["status"] == "SUBMITTED"


def test_the_projection_is_recomputed_once_per_checkpoint_and_counts_unpaid_heads(clock_at_epoch):
    """PRD §3.9: "First, the edition's `ops_epoch` is incremented by one, stamping the
    run."
    PRD §3.9: "Sixth, and only now that heads and stays have settled,
    `provisional_impact_cents` is recomputed."
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
    PRD §3.9: "That reading reports the `provisional_impact_cents` and
    `final_impact_cents` figures, the `sponsorship_recognized_cents` and
    `municipal_support_cents` ledgers, and the three underlying counts —
    `registered_heads`, `checked_in_heads` and `actual_room_nights` — so that the
    projection can be audited without recomputing it."

    Three unpaid registrants project 901320; a fourth raises it to 1201760 —
    but only when the next checkpoint run recomputes the figure.

    Design: Corner/calculations/corner_calculation_provisional_impact_recomputed_each_ops_epoch
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed = base["edition"]
    assert ed["provisional_impact_cents"] == 0

    first = create_athlete(ed["id"], full_name="Ada Fenn")
    create_athlete(ed["id"], full_name="Bo Marsh")
    create_athlete(ed["id"], full_name="Cara Idris")

    # 3 athlete heads + 3 * 1.8 visitor heads = 8.4; 8.4 * 18500 * 4 = 621600;
    # 621600 * 1.45 = 901320.
    after_first_run = ops_run(ed["id"])
    assert after_first_run["ops_epoch"] == 1
    assert after_first_run["provisional_impact_cents"] == 901320
    assert after_first_run["status"] == "REGISTRATION_OPEN"

    create_athlete(ed["id"], full_name="Dov Halloran")
    assert get_edition(ed["id"])["provisional_impact_cents"] == 901320

    # 4 + 7.2 = 11.2; 11.2 * 18500 * 4 = 828800; 828800 * 1.45 = 1201760.
    after_second_run = ops_run(ed["id"])
    assert after_second_run["ops_epoch"] == 2
    assert after_second_run["provisional_impact_cents"] == 1201760
    assert after_second_run["status"] == "REGISTRATION_OPEN"

    # The clock never reached the deadline, so nobody was expired: the unpaid
    # heads were counted, not swept.
    assert get_athlete(first["id"])["registration_status"] == "PENDING_PAYMENT"

    reading = validate_success(api_client.get_economic_impact(ed["id"], SPONSOR))
    assert reading["provisional_impact_cents"] == 1201760
    assert reading["final_impact_cents"] is None
    assert reading["registered_heads"] == 4
    assert reading["checked_in_heads"] == 0
    assert reading["actual_room_nights"] == 0
    assert reading["sponsorship_recognized_cents"] == 0
    assert reading["municipal_support_cents"] == 0


def test_the_discount_rounds_half_up_and_nothing_else_rounds(clock_at_epoch):
    """PRD §2.8: "`municipal_support_cents`, `entry_fee_cents`, `nightly_rate_cents`,
    `pledged_cents`, `fee_total_cents`, `fee_paid_cents`, `recognized_cents`,
    `sponsorship_recognized_cents`, `provisional_impact_cents`, `final_impact_cents` and
    `total_charge_cents` are all whole cents, and every rounding step named in this
    document uses the round-half-up convention — a fractional part of exactly one half
    rounds away from zero."
    PRD §2.8: "The registration fee settlement rounds exactly once, on the discount
    amount, and never again."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."

    A 24010-cent subtotal makes the five-percent discount exactly 1200.5, which
    settles at 1201 and leaves the rest of the arithmetic exact.

    Design: Corner/calculations/corner_calculation_fee_precision_round_half_up_at_step_four_only
    """
    base = setup_open_edition(event={"entry_fee_cents": 6000, "min_entries_to_stage": 1})
    ed, sp, ev_a = base["edition"], base["sport"], base["event"]
    ev_b = create_sport_event(
        sp["id"], ed["id"], event_code="T200M", entry_fee_cents=8510, min_entries_to_stage=1
    )

    athlete = create_athlete(ed["id"], full_name="Ada Fenn")
    create_entry(athlete["id"], ev_a["id"])
    create_entry(athlete["id"], ev_b["id"])

    settled = pay_fees(athlete["id"], 22809)
    assert settled["fee_total_cents"] == 22809

    breakdown = settled["fee_breakdown"]
    assert breakdown["subtotal_cents"] == 24010
    # 24010 * 0.05 == 1200.5 exactly: half up gives 1201, half even would give 1200.
    assert breakdown["discount_cents"] == 1201
    assert breakdown["discounted_cents"] == 22809
    assert breakdown["surcharge_cents"] == 0

    stored = get_athlete(athlete["id"])
    assert stored["fee_paid_cents"] == 22809
    assert stored["registration_status"] == "REGISTERED"


def test_the_base_registration_fee_is_charged_even_with_no_entries_at_all(clock_at_epoch):
    """PRD §3.2: "**Step one** counts the athlete's live entries: those in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED` or `ACCEPTED`, which becomes
    `entry_count`; entries on `MEDICAL_HOLD`, `REJECTED` or `WITHDRAWN` are excluded."
    PRD §3.2: "**Step two** sums the `entry_fee_cents` of the sport event behind each of
    those same entries into `event_fees_cents`, in whole cents with no rounding."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    An entry-less athlete owes exactly the 9500-cent base fee: no discount tier
    and no surcharge tier engages.

    Design: Corner/calculations/corner_calculation_fee_constants_base_registration_applied_with_zero_entries
    """
    base = setup_open_edition(event={"min_entries_to_stage": 1})
    ed, event = base["edition"], base["event"]
    athlete = create_athlete(ed["id"], full_name="Ada Fenn")

    settled = pay_fees(athlete["id"], 9500)
    assert settled["fee_total_cents"] == 9500

    breakdown = settled["fee_breakdown"]
    assert breakdown["entry_count"] == 0
    assert breakdown["event_fees_cents"] == 0
    assert breakdown["subtotal_cents"] == 9500
    assert float(breakdown["discount_pct"]) == 0.0
    assert breakdown["discount_cents"] == 0
    assert breakdown["discounted_cents"] == 9500
    assert breakdown["surcharge_cents"] == 0

    # Registration can be completed on the base fee alone.
    assert get_athlete(athlete["id"])["registration_status"] == "REGISTERED"
    assert get_event(event["id"])["accepted_entry_count"] == 0
