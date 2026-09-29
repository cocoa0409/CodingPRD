"""Pricing a delivery: the capped fee, the per-session reimbursements, and the
encumbrance swap that a delivery performs on the residency's money ledger."""
from test_helpers import (
    TEST_USERS,
    confirm_session_as_liaison,
    create_confirmed_session,
    deliver_session,
    open_voucher,
    read_residency,
    read_session,
    schedule_session,
    set_clock_to_default,
    setup_active_residency,
    setup_two_delivered_evaluated_sessions,
)

RC = TEST_USERS["roster_coordinator_headers"]


# ==========================================================================
# The cap is applied before the proration factor
# ==========================================================================
def _documentary_studio_confirmed_session() -> dict:
    """A MASTER-tier lead artist on a G9_12 MEDIA_ARTS residency, with one
    confirmed session holding the full-length projection."""
    set_clock_to_default()
    scenario = setup_active_residency(
        artist_overrides={
            "full_name": "Diego Marek",
            "email": "diego.marek@arts.org",
            "primary_discipline": "MEDIA_ARTS",
            "secondary_disciplines": [],
            "grade_bands": ["G9_12"],
            "languages": ["en", "es"],
            "roster_tier_assigned": "MASTER",
            "demo_rubric_score": 4.6,
            "portfolio_reviews": [
                ("panelist-1", 4.5, 4.5, 4.5),
                ("panelist-2", 4.0, 4.0, 4.0),
            ],
        },
        residency_overrides={
            "title": "Documentary Studio",
            "discipline": "MEDIA_ARTS",
            "grade_band": "G9_12",
            "contracted_session_count": 4,
            "budget_cents": 100000,
            "materials_stipend_cents": 0,
            "collaboration_expectation": "OBSERVE",
            "co_planning_hours_required": 0,
            "required_strands": ["CREATING"],
            "enrolled_student_count": 30,
        },
    )
    session = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        start_time="13:00",
        end_time="14:00",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    scenario["session"] = confirm_session_as_liaison(
        session["id"],
        scenario["school"]["id"],
        classroom_teacher_name="Mr. Okafor",
        co_planning_completed=False,
    )
    return scenario


def test_half_length_delivery_is_priced_by_capping_before_prorating(api):
    """PRD §3.7: "**Cap before prorating** — this order is load-bearing. Clamp
    the result into the band from 9,000 cents to 19,000 cents: take the larger of
    the result and 9,000, then take the smaller of that and 19,000."
    PRD §3.7: "Round `minutes_delivered` **up** to the next whole 5-minute block
    to get billed minutes, then form the proration factor as billed minutes
    divided by the residency's `session_length_minutes`, capped at 1.00 so
    overtime is never paid."
    PRD §3.7: "Prorating before capping would produce a different — and wrong —
    number whenever the uncapped fee exceeds 19,000 cents and the artist taught
    less than the full scheduled length."

    Design: Difficulty/combinatorial_formula/session_fee_cap_before_proration_mode_a_nonlinear
    """
    scenario = _documentary_studio_confirmed_session()
    assert scenario["artist"]["roster_tier_effective"] == "MASTER"
    assert scenario["session"]["encumbered_cents"] == 19000, (
        "the full-length projection is the capped ceiling, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    delivered = deliver_session(
        scenario["session"]["id"],
        scenario["artist"]["id"],
        students_present_count=18,
        minutes_delivered=30,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    assert delivered["fee_cents"] == 9500, (
        f"expected the capped 19000 prorated by one half, got {delivered['fee_cents']}"
    )
    assert delivered["fee_cents"] != 10617, (
        "prorating the uncapped 21234 before clamping is the wrong order"
    )
    assert delivered["travel_reimbursement_cents"] == 0
    assert delivered["materials_reimbursement_cents"] == 0
    assert delivered["payable_cents"] == 9500


def test_half_length_delivery_swaps_its_hold_for_the_capped_payable(api):
    """PRD §3.7: "The money held by the session is swapped for the real figure:
    the residency's `encumbered_cents` gains the difference between
    `payable_cents` and what the session was holding, the session's
    `encumbered_cents` becomes `payable_cents`, and `available_cents` is
    recomputed."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."

    Design: Difficulty/combinatorial_formula/session_fee_cap_before_proration_mode_a_nonlinear
    """
    scenario = _documentary_studio_confirmed_session()
    deliver_session(
        scenario["session"]["id"],
        scenario["artist"]["id"],
        students_present_count=18,
        minutes_delivered=30,
        travel_miles=0.0,
        materials_spend_cents=0,
    )

    session = read_session(scenario["session"]["id"])
    assert session["encumbered_cents"] == 9500, (
        f"the hold must become the payable figure, got {session['encumbered_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 9500
    assert residency["available_cents"] == 90500
    assert residency["earned_to_date_cents"] == 9500
    assert (
        residency["available_cents"]
        + residency["encumbered_cents"]
        + residency["disbursed_cents"]
        == 100000
    )


# ==========================================================================
# Travel is rounded per session, then summed
# ==========================================================================
def _two_deliveries_with_mileage() -> dict:
    set_clock_to_default()
    return setup_two_delivered_evaluated_sessions()


def test_each_session_rounds_its_own_travel_before_the_voucher_sums_them(api):
    """PRD §3.7: "Billable miles are `travel_miles` less 10.0, floored at zero,
    and `travel_reimbursement_cents` is billable miles multiplied by 67 cents per
    mile, rounded half up."
    PRD §3.7: "Each session's reimbursement is rounded on its own before any
    voucher sums it."
    PRD §2.5: "Second, travel reimbursement is rounded **per session** and only
    then summed onto a voucher; summing raw mileage across sessions and rounding
    once produces a different — and wrong — total."

    Design: Difficulty/combinatorial_formula/travel_reimbursement_round_per_session_then_sum_mode_b
    """
    scenario = _two_deliveries_with_mileage()
    one = read_session(scenario["session_one"]["id"])
    two = read_session(scenario["session_two"]["id"])
    assert one["travel_reimbursement_cents"] == 704, (
        f"10.5 billable miles at 67 cents rounds to 704, got "
        f"{one['travel_reimbursement_cents']}"
    )
    assert two["travel_reimbursement_cents"] == 302, (
        f"4.5 billable miles at 67 cents rounds to 302, got "
        f"{two['travel_reimbursement_cents']}"
    )

    voucher = open_voucher(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [one["id"], two["id"]],
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    assert voucher["travel_reimbursement_cents"] == 1006, (
        f"expected 704 + 302, got {voucher['travel_reimbursement_cents']}"
    )
    assert voucher["travel_reimbursement_cents"] != 1005, (
        "summing 15.0 raw miles and rounding once is the wrong order"
    )


def test_voucher_subtotals_aggregate_fees_and_the_capped_materials(api):
    """PRD §3.8: "Voucher money is pure aggregation over the claimed sessions,
    with no further rounding: `session_fee_subtotal_cents` is the sum of their
    `fee_cents`, `travel_reimbursement_cents` is the sum of their per-session
    travel figures — already rounded individually, which is why summing raw
    mileage first would give a different answer — `materials_reimbursement_cents`
    is the sum of their per-session materials figures, and `total_cents` is those
    three subtotals added together."
    PRD §3.7: "`materials_reimbursement_cents` is the lesser of the reported
    `materials_spend_cents` and a per-session cap of 2,500 cents — the
    residency's `materials_stipend_cents` earmark does not raise or lower that
    cap."
    PRD §3.8: "A new voucher starts with a `status` of `DRAFT`, both review
    tracks at `PENDING`, and its `void_reason` null; each claimed session gets
    its `payment_voucher_id` pointed at the new voucher."

    Design: Difficulty/combinatorial_formula/travel_reimbursement_round_per_session_then_sum_mode_b
    """
    scenario = _two_deliveries_with_mileage()
    voucher = open_voucher(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [scenario["session_one"]["id"], scenario["session_two"]["id"]],
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    assert voucher["session_fee_subtotal_cents"] == 27948, (
        f"expected two full-length fees of 13974, got "
        f"{voucher['session_fee_subtotal_cents']}"
    )
    assert voucher["materials_reimbursement_cents"] == 2500, (
        f"3000 cents of spend is capped at 2500, got "
        f"{voucher['materials_reimbursement_cents']}"
    )
    assert voucher["total_cents"] == 31454, (
        f"expected 27948 + 1006 + 2500, got {voucher['total_cents']}"
    )
    assert voucher["status"] == "DRAFT"


# ==========================================================================
# The delivery budget test is a delta against pre-swap available
# ==========================================================================
def _tight_budget_residency_with_two_confirmed_sessions() -> dict:
    """A two-session residency whose budget leaves only 2052 cents of headroom
    once both sessions hold their full-length projection."""
    set_clock_to_default()
    scenario = setup_active_residency(
        residency_overrides={
            "title": "Story in Motion Pilot",
            "contracted_session_count": 2,
            "budget_cents": 30000,
            "materials_stipend_cents": 2000,
            "co_planning_hours_required": 2,
            "required_strands": ["CREATING"],
            "enrolled_student_count": 20,
        }
    )
    scenario["pilot_one"] = create_confirmed_session(
        scenario, session_date="2026-10-20"
    )
    scenario["pilot_two"] = create_confirmed_session(
        scenario, session_date="2026-10-27"
    )
    return scenario


def test_two_confirmations_hold_the_full_length_projection_of_a_tight_budget(api):
    """PRD §3.6: "The server evaluates the session fee rules of §3.7 as though
    the artist had taught the full `session_length_minutes`, writes that amount
    into the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."
    PRD §2.12: "The **money ledger** partitions the budget across three
    accounts: `encumbered_cents`, the sum of the amounts currently held by this
    residency's sessions; `disbursed_cents`, the sum of `total_cents` over this
    residency's `APPROVED` vouchers; and `available_cents`, which is
    `budget_cents` less encumbered less disbursed."

    Design: Difficulty/combinatorial_formula/delivery_encumbrance_swap_delta_evaluation_order_mode_c
    """
    scenario = _tight_budget_residency_with_two_confirmed_sessions()
    assert scenario["pilot_one"]["encumbered_cents"] == 13974
    assert scenario["pilot_two"]["encumbered_cents"] == 13974

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 27948, (
        f"expected both full-length projections held, got "
        f"{residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 2052, (
        f"expected 30000 less 27948, got {residency['available_cents']}"
    )


def test_delivery_charges_only_the_delta_against_pre_swap_available(api):
    """PRD §3.7: "And the money must be there: the amount by which the session's
    final payable figure exceeds what the session was already holding must not
    exceed the residency's `available_cents`, or the refusal is
    `ERR_RESIDENCY_BUDGET_EXCEEDED`."
    PRD §3.7: "The money held by the session is swapped for the real figure: the
    residency's `encumbered_cents` gains the difference between `payable_cents`
    and what the session was holding, the session's `encumbered_cents` becomes
    `payable_cents`, and `available_cents` is recomputed."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."

    Design: Difficulty/combinatorial_formula/delivery_encumbrance_swap_delta_evaluation_order_mode_c
    """
    scenario = _tight_budget_residency_with_two_confirmed_sessions()
    delivered = deliver_session(
        scenario["pilot_one"]["id"],
        scenario["artist"]["id"],
        students_present_count=19,
        minutes_delivered=60,
        travel_miles=0.0,
        materials_spend_cents=2000,
    )
    assert delivered["fee_cents"] == 13974
    assert delivered["materials_reimbursement_cents"] == 2000
    assert delivered["payable_cents"] == 15974, (
        "the delta over the 13974 already held is only 2000, which fits the "
        f"2052 of available headroom, got payable {delivered['payable_cents']}"
    )
    assert delivered["encumbered_cents"] == 15974

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 29948
    assert residency["available_cents"] == 52, (
        f"expected 30000 less 29948, got {residency['available_cents']}"
    )
    assert residency["disbursed_cents"] == 0
    assert (
        residency["available_cents"]
        + residency["encumbered_cents"]
        + residency["disbursed_cents"]
        == 30000
    )
