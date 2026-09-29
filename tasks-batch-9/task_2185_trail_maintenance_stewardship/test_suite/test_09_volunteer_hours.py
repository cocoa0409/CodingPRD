"""Crediting, verifying, disputing and certifying volunteer hours."""

from test_helpers import (
    TEST_USERS,
    assert_hour_invariant,
    check_in,
    check_out,
    complete_party,
    confirm_party,
    read_plan,
    read_volunteer,
    register_volunteer_on_party,
    set_clock,
    setup_briefed_party,
    setup_completed_party_with_hours,
    start_party,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
GRANTS = TEST_USERS["grants_admin_headers"]


def _two_shifts_of_395_and_397_billable_minutes():
    """Milo worked 380 minutes and Petra 382, both with a 45-minute travel allowance."""
    world = setup_briefed_party()
    world["shift_saw"] = register_volunteer_on_party(
        world["party_id"],
        world["lead_id"],
        world["saw_id"],
        expected_version=world["party_version_after_briefing"],
        role_on_crew="SAWYER",
    )
    world["shift_saw_id"] = world["shift_saw"]["id"]
    world["shift_gen"] = register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )
    world["shift_gen_id"] = world["shift_gen"]["id"]

    confirm_party(world["party_id"], world["lead_id"])
    set_clock("2026-09-05T09:00:00.000Z")
    start_party(world["party_id"], world["lead_id"])
    check_in(world["shift_saw_id"], world["lead_id"])
    check_in(world["shift_gen_id"], world["lead_id"])

    set_clock("2026-09-05T15:20:00.000Z")
    world["shift_saw"] = check_out(world["shift_saw_id"], world["lead_id"])
    set_clock("2026-09-05T15:22:00.000Z")
    world["shift_gen"] = check_out(world["shift_gen_id"], world["lead_id"])
    complete_party(world["party_id"], world["lead_id"])
    return world


def test_each_shift_is_quantized_to_the_quarter_hour_on_its_own(api):
    """PRD 3.7: "A meal break of 30 minutes is deducted from any shift of four hours or more — that is, whenever `worked_minutes` is at least 240 — and nothing is deducted from a shorter shift."
    PRD 3.7: "Travel is credited from the party's `travel_allowance_minutes`, but never more than 60 minutes per volunteer, so the creditable travel is whichever is smaller of the party's allowance and 60."
    PRD 3.7: "Finally the billable minutes are divided by 15, rounded half up to a whole number of quarter-hour units, and multiplied by 0.25 to give `credited_hours`, expressed to two decimal places."

    Design: Difficulty/combinatorial_formula/shift_hours_quantized_per_shift_then_summed_not_summed_then_quantized
    """
    world = _two_shifts_of_395_and_397_billable_minutes()

    assert world["shift_saw"]["worked_minutes"] == 380
    assert world["shift_saw"]["billable_minutes"] == 395
    assert float(world["shift_saw"]["credited_hours"]) == 6.50

    assert world["shift_gen"]["worked_minutes"] == 382
    assert world["shift_gen"]["billable_minutes"] == 397
    assert float(world["shift_gen"]["credited_hours"]) == 6.50


def test_plan_hour_totals_sum_the_already_quantized_per_shift_values(api):
    """PRD 2.9: "Hours are quantized to the nearest quarter hour **per shift first**, and every aggregate then sums the already-quantized per-shift values — that goes for `lifetime_credited_hours`, `pending_hours`, `verified_hours`, `certified_hours`, for a plan's `verified_volunteer_hours` and `certified_volunteer_hours`, and for every hour total inside the grant-match calculation."
    PRD 2.9: "Summing raw billable minutes across shifts and quantizing the total is forbidden and yields a different answer: two shifts of 395 and 397 billable minutes give 6.50 plus 6.50, which is 13.00 under the pinned order, but 13.25 under the forbidden one."
    PRD 3.7: "Verifying moves the shift `CHECKED_OUT → HOURS_VERIFIED` and requires the party to have reached `COMPLETED`; it records the acting `X-User-ID` as `hours_verified_by_user_id`, moves `credited_hours` out of the volunteer's `pending_hours` and into `verified_hours`, and adds the same amount to the plan's `verified_volunteer_hours`."

    Design: Difficulty/combinatorial_formula/shift_hours_quantized_per_shift_then_summed_not_summed_then_quantized
    """
    world = _two_shifts_of_395_and_397_billable_minutes()

    validate_success(
        api.review_shift_hours(world["shift_saw_id"], {"decision": "VERIFY"}, COORD)
    )
    validate_success(
        api.review_shift_hours(world["shift_gen_id"], {"decision": "VERIFY"}, COORD)
    )

    plan = read_plan(world["plan_id"])
    assert float(plan["verified_volunteer_hours"]) == 13.00
    assert float(plan["verified_volunteer_hours"]) != 13.25

    sawyer = read_volunteer(world["saw_id"])
    assert float(sawyer["verified_hours"]) == 6.50
    assert float(sawyer["pending_hours"]) == 0
    assert float(read_volunteer(world["gen_id"])["lifetime_credited_hours"]) == 6.50


def test_dispute_then_reset_restores_the_hour_identity_with_zero_drift(api):
    """PRD 3.7: "Disputing moves the shift `CHECKED_OUT → HOURS_DISPUTED`; it requires an `adjusted_hours` value that is a multiple of 0.25 and at least 0, and a non-empty `dispute_reason`, both of which are stored."
    PRD 3.7: "The difference between `adjusted_hours` and the shift's existing `credited_hours` is computed, `credited_hours` is overwritten with `adjusted_hours`, and both the volunteer's `lifetime_credited_hours` and `pending_hours` move by that same difference — upward if the correction added hours, downward if it removed them."
    PRD 3.7: "Resetting is the compensating action for a dispute and moves the shift `HOURS_DISPUTED → CHECKED_OUT`: `credited_hours` is recomputed from scratch by the hour calculation above, `adjusted_hours` and `dispute_reason` are cleared to null, and the volunteer's `lifetime_credited_hours` and `pending_hours` each move by the difference between the recomputed figure and the stored one."
    PRD 2.9: "The **hour invariant** governs a volunteer's four hour buckets."

    Design: Difficulty/compensating_invariant/hours_dispute_then_reset_restores_hour_identity_with_zero_drift
    """
    world = setup_completed_party_with_hours()
    assert float(world["shift_saw"]["credited_hours"]) == 6.50

    baseline = read_volunteer(world["saw_id"])
    assert float(baseline["lifetime_credited_hours"]) == 6.50
    assert float(baseline["pending_hours"]) == 6.50
    assert_hour_invariant(baseline)

    disputed = validate_success(
        api.review_shift_hours(
            world["shift_saw_id"],
            {
                "decision": "DISPUTE",
                "adjusted_hours": 5.00,
                "dispute_reason": "Two hours logged as travel were already covered.",
            },
            COORD,
        )
    )
    assert disputed["status"] == "HOURS_DISPUTED"
    assert float(disputed["credited_hours"]) == 5.00

    after_dispute = read_volunteer(world["saw_id"])
    assert float(after_dispute["lifetime_credited_hours"]) == 5.00
    assert float(after_dispute["pending_hours"]) == 5.00
    assert_hour_invariant(after_dispute)

    reset = validate_success(
        api.review_shift_hours(world["shift_saw_id"], {"decision": "RESET"}, COORD)
    )
    assert reset["status"] == "CHECKED_OUT"
    assert float(reset["credited_hours"]) == 6.50
    assert reset["adjusted_hours"] is None

    after_reset = read_volunteer(world["saw_id"])
    assert float(after_reset["lifetime_credited_hours"]) == 6.50
    assert float(after_reset["pending_hours"]) == 6.50
    assert_hour_invariant(after_reset)


def test_hours_migrate_from_pending_to_verified_to_certified_without_drift(api):
    """PRD 2.9: "`lifetime_credited_hours` is the running total of every hour ever credited to that volunteer by a check-out or by a dispute adjustment; `pending_hours`, `verified_hours` and `certified_hours` partition those hours by the state of the shift carrying them — pending while the shift is `CHECKED_OUT` or `HOURS_DISPUTED`, verified while it is `HOURS_VERIFIED`, certified while it is `HOURS_CERTIFIED`."
    PRD 2.9: "Every movement between shift states moves the same number of hours out of one bucket and into another, and every credit adjustment moves `lifetime_credited_hours` and `pending_hours` by the identical delta."
    PRD 3.7: "Certification records `hours_certified_by_user_id`, moves `credited_hours` out of the volunteer's `verified_hours` and into `certified_hours`, and correspondingly moves the same amount out of the plan's `verified_volunteer_hours` and into its `certified_volunteer_hours`."

    Design: Difficulty/compensating_invariant/hours_dispute_then_reset_restores_hour_identity_with_zero_drift
    """
    world = setup_completed_party_with_hours()

    verified = validate_success(
        api.review_shift_hours(world["shift_saw_id"], {"decision": "VERIFY"}, COORD)
    )
    assert verified["status"] == "HOURS_VERIFIED"

    after_verify = read_volunteer(world["saw_id"])
    assert float(after_verify["lifetime_credited_hours"]) == 6.50
    assert float(after_verify["pending_hours"]) == 0
    assert float(after_verify["verified_hours"]) == 6.50
    assert_hour_invariant(after_verify)

    certified = validate_success(
        api.certify_shift_hours(world["shift_saw_id"], GRANTS)
    )
    assert certified["status"] == "HOURS_CERTIFIED"

    after_certify = read_volunteer(world["saw_id"])
    assert float(after_certify["lifetime_credited_hours"]) == 6.50
    assert float(after_certify["pending_hours"]) == 0
    assert float(after_certify["verified_hours"]) == 0
    assert float(after_certify["certified_hours"]) == 6.50
    assert_hour_invariant(after_certify)


def test_the_break_deduction_boundary_makes_a_shorter_shift_earn_more(api):
    """PRD 3.7: "The `worked_minutes` figure is the whole number of minutes from `checked_in_at` to `checked_out_at`, truncated toward zero."
    PRD 3.7: "A meal break of 30 minutes is deducted from any shift of four hours or more — that is, whenever `worked_minutes` is at least 240 — and nothing is deducted from a shorter shift."
    PRD 3.7: "The `billable_minutes` figure is then the worked minutes less the break, floored at 0 so that a deduction can never drive the figure negative, plus the capped travel minutes."

    Design: Corner/calculations/shift_credited_hours_break_deduction_boundary_at_240_minutes
    """
    world = setup_briefed_party(party_overrides={"travel_allowance_minutes": 0})
    shift_saw = register_volunteer_on_party(
        world["party_id"],
        world["lead_id"],
        world["saw_id"],
        expected_version=world["party_version_after_briefing"],
        role_on_crew="SAWYER",
    )
    shift_gen = register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )
    confirm_party(world["party_id"], world["lead_id"])
    set_clock("2026-09-05T09:00:00.000Z")
    start_party(world["party_id"], world["lead_id"])
    check_in(shift_saw["id"], world["lead_id"])
    check_in(shift_gen["id"], world["lead_id"])

    set_clock("2026-09-05T12:59:00.000Z")
    short_shift = check_out(shift_gen["id"], world["lead_id"])
    set_clock("2026-09-05T13:00:00.000Z")
    long_shift = check_out(shift_saw["id"], world["lead_id"])

    assert short_shift["worked_minutes"] == 239
    assert short_shift["billable_minutes"] == 239
    assert float(short_shift["credited_hours"]) == 4.00

    assert long_shift["worked_minutes"] == 240
    assert long_shift["billable_minutes"] == 210
    assert float(long_shift["credited_hours"]) == 3.50
    assert float(long_shift["credited_hours"]) < float(short_shift["credited_hours"])

    assert float(read_volunteer(world["gen_id"])["lifetime_credited_hours"]) == 4.00
    assert float(read_volunteer(world["saw_id"])["lifetime_credited_hours"]) == 3.50
