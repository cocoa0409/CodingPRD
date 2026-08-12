"""The funding waterfall: pinned order, per-line rounding and the refusal."""

from test_helpers import (
    ApiErrorId,
    allocation_total,
    allocations_for_charge,
    allocations_of,
    assert_charge_conservation,
    assert_grant_partition,
    book_session,
    complete_session,
    confirm_session,
    make_grant,
    make_scholarship_award,
    only_charge_for_session,
    positive_allocation,
    read_award,
    read_charge,
    read_grant,
    read_session,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CLERK


def _grant_and_scholarship_scenario():
    """BAND_B rider with a 3000-cent grant and a 0.5 / 5000-cent scholarship."""
    scenario = setup_active_rider(rider={"household_income_band": "BAND_B"})
    scenario["grant"] = make_grant(
        grant_name="Hooves Fund",
        funder_name="County",
        awarded_amount_cents=3000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    scenario["award"] = make_scholarship_award(
        scenario["rider_id"],
        cap_pct=0.5,
        period_cap_cents=5000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    scenario.update({"session": session, "session_id": session["id"]})
    return scenario


def test_waterfall_lines_follow_the_pinned_order(api):
    """PRD 3.8: "Each line records its `source_type`, its `sequence_index` — 1
    for grant, 2 for scholarship, 3 for sliding scale, 4 for payer, 5 for private
    pay — and its `amount_cents`, and lines are created in ascending
    `sequence_index`, with the grant lines in the candidate order below."
    PRD 3.8: "That same figure becomes the charge's `balance_due_cents`, and
    `allocated_cents` becomes the sum of every emitted line, which by
    construction equals the gross."

    Design: Difficulty/combinatorial_formula/waterfall_scholarship_pct_of_gross_then_sliding_pct_of_remaining
    """
    scenario = _grant_and_scholarship_scenario()
    complete_session(scenario["session_id"], scenario["instructor_id"], 45)

    charge = only_charge_for_session(scenario["session_id"])
    assert charge["amount_cents"] == 6750
    allocations = allocations_for_charge(charge["id"])

    assert positive_allocation(allocations, "GRANT")["sequence_index"] == 1
    assert positive_allocation(allocations, "SCHOLARSHIP")["sequence_index"] == 2
    assert positive_allocation(allocations, "SLIDING_SCALE")["sequence_index"] == 3
    assert positive_allocation(allocations, "PRIVATE_PAY")["sequence_index"] == 5

    assert charge["allocated_cents"] == 6750
    assert_charge_conservation(charge, allocations)
    assert charge["status"] == "PENDING"
    assert read_session(scenario["session_id"])["billing_status"] == "CHARGED"


def test_scholarship_is_pct_of_gross_and_sliding_scale_pct_of_remainder(api):
    """PRD 3.8: "Its contribution is the smallest of three figures: the
    percentage cap, which is `cap_pct` of the **gross** charge amount rounded
    half-up to whole cents; the period room, which is `period_cap_cents` less
    `period_used_cents`; and the current remainder."
    PRD 3.8: "The scholarship cap is a percentage of the **gross** while the
    sliding-scale discount is a percentage of the **remainder**, so a rider
    holding a scholarship arrives at step 3 with a smaller base and receives a
    smaller absolute sliding-scale discount than an otherwise identical rider
    without one."
    PRD 2.11: "A grant is `EXHAUSTED` when `remaining_amount_cents` is exactly 0
    and `OPEN` otherwise."

    Design: Difficulty/combinatorial_formula/waterfall_scholarship_pct_of_gross_then_sliding_pct_of_remaining
    """
    scenario = _grant_and_scholarship_scenario()
    complete_session(scenario["session_id"], scenario["instructor_id"], 45)

    charge = only_charge_for_session(scenario["session_id"])
    allocations = allocations_for_charge(charge["id"])

    assert allocation_total(allocations, "GRANT") == 3000
    assert allocation_total(allocations, "SCHOLARSHIP") == 3375
    assert allocation_total(allocations, "SLIDING_SCALE") == 150
    assert allocation_total(allocations, "PRIVATE_PAY") == 225
    assert charge["balance_due_cents"] == 225

    grant = read_grant(scenario["grant"]["id"])
    assert grant["remaining_amount_cents"] == 0
    assert grant["status"] == "EXHAUSTED"
    assert_grant_partition(grant)

    award = read_award(scenario["award"]["id"])
    assert award["period_used_cents"] == 3375
    assert award["status"] == "ACTIVE"


def test_scholarship_line_rounds_half_up_on_an_exact_half_cent(api):
    """PRD 2.6: "Wherever a monetary amount is produced by multiplying by a
    percentage, the result is rounded to whole cents using round-half-up."
    PRD 3.8: "Each line's amount is rounded to whole cents **at line level**
    before it is subtracted from the remainder; there is never a sum-then-round
    step, and every draw is additionally capped at the remainder so the lines can
    never over-allocate."

    Design: Corner/calculations/scholarship_line_rounds_half_up_on_an_exact_half_cent
    """
    scenario = setup_active_rider(rider={"household_income_band": "BAND_C"})
    award = make_scholarship_award(
        scenario["rider_id"],
        cap_pct=0.35,
        period_cap_cents=100000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )
    confirm_session(session["id"], scenario["instructor_id"])
    complete_session(session["id"], scenario["instructor_id"], 45)

    charge = only_charge_for_session(session["id"])
    allocations = allocations_for_charge(charge["id"])
    assert charge["amount_cents"] == 6750

    scholarship = allocation_total(allocations, "SCHOLARSHIP")
    sliding = allocation_total(allocations, "SLIDING_SCALE")
    private = allocation_total(allocations, "PRIVATE_PAY")
    assert scholarship == 2363, "2362.5 rounds half up to 2363, never down to 2362"
    assert sliding == 877, "877.4 rounds half up to 877"
    assert private == 3510
    assert charge["balance_due_cents"] == 3510
    assert scholarship + sliding + private == 6750, (
        "Per-line rounding never loses or creates a cent"
    )
    assert read_award(award["id"])["period_used_cents"] == 2363


def test_no_show_fee_costs_more_out_of_pocket_than_the_session(api):
    """PRD 3.6: "a `NO_SHOW_FEE` charge is created for the full quoted fee — 100
    per cent of it, rounded half-up to whole cents — which then runs the
    waterfall with grant and scholarship money excluded."
    PRD 3.8: "And because grant and scholarship money cannot touch a cancellation
    or no-show fee, the same rider pays substantially **more** out of pocket for
    a no-show fee than for the delivered session it replaced — the scholarship
    that shielded the session fee is unavailable, and the sliding-scale base is
    no longer shrunken."

    Design: Corner/calculations/no_show_fee_costs_more_out_of_pocket_than_the_session_it_replaced
    """
    scenario = setup_active_rider(rider={"household_income_band": "BAND_A"})
    award = make_scholarship_award(
        scenario["rider_id"],
        cap_pct=0.75,
        period_cap_cents=100000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    delivered = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-11T10:00:00Z",
        duration_minutes=60,
    )
    confirm_session(delivered["id"], scenario["instructor_id"])
    missed = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-05-12T10:00:00Z",
        duration_minutes=60,
    )
    confirm_session(missed["id"], scenario["instructor_id"])

    set_clock("2026-05-11T11:30:00Z")
    complete_session(delivered["id"], scenario["instructor_id"], 60)
    set_clock("2026-05-12T10:30:00Z")
    validate_success(api.record_no_show(missed["id"], scenario["instructor_headers"]))

    session_charge = only_charge_for_session(delivered["id"])
    session_allocations = allocations_for_charge(session_charge["id"])
    assert session_charge["charge_type"] == "SESSION_FEE"
    assert session_charge["amount_cents"] == 9000
    assert allocation_total(session_allocations, "SCHOLARSHIP") == 6750
    assert allocation_total(session_allocations, "SLIDING_SCALE") == 1350
    assert allocation_total(session_allocations, "PRIVATE_PAY") == 900
    assert session_charge["balance_due_cents"] == 900

    no_show_charge = only_charge_for_session(missed["id"])
    no_show_allocations = allocations_for_charge(no_show_charge["id"])
    assert no_show_charge["charge_type"] == "NO_SHOW_FEE"
    assert no_show_charge["amount_cents"] == 9000
    assert allocation_total(no_show_allocations, "SLIDING_SCALE") == 5400
    assert allocation_total(no_show_allocations, "PRIVATE_PAY") == 3600
    assert no_show_charge["balance_due_cents"] == 3600
    assert allocations_of(no_show_allocations, "SCHOLARSHIP") == []
    assert allocations_of(no_show_allocations, "GRANT") == []

    assert read_award(award["id"])["period_used_cents"] == 6750
    assert no_show_charge["balance_due_cents"] > session_charge["balance_due_cents"]


def test_funded_only_rider_with_no_cover_is_refused(api):
    """PRD 3.8: "Before the line is written, one refusal applies: when the charge
    is a `SESSION_FEE`, the rider's `funding_mode` is `FUNDED_ONLY`, and a
    remainder survives, the whole request is rejected with `ERR_FUNDS_EXHAUSTED`
    and nothing at all is persisted — the session stays `CONFIRMED` and no charge
    or allocation line exists."

    Design: Corner/validations/funded_only_rider_with_no_cover_returns_funds_exhausted
    """
    scenario = setup_active_rider(rider={"funding_mode": "FUNDED_ONLY"})
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        duration_minutes=30,
    )
    confirmed = confirm_session(session["id"], scenario["instructor_id"])

    refused = api.complete_session(
        session["id"], {"mounted_minutes": 30}, scenario["instructor_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_FUNDS_EXHAUSTED.value)

    after = read_session(session["id"])
    assert after["schedule_status"] == "CONFIRMED"
    assert after["mounted_minutes"] is None
    assert after["billing_status"] == "UNBILLED"
    assert after["version"] == confirmed["version"]

    _, charge_meta = validate_paginated(
        api.list_charges(CLERK, params={"session_id": session["id"]})
    )
    assert charge_meta["total_count"] == 0
    _, alloc_meta = validate_paginated(api.list_funding_allocations(CLERK))
    assert alloc_meta["total_count"] == 0


def test_preferred_grant_failing_its_restriction_is_refused(api):
    """PRD 3.8: "It is validated against exactly the step-1 eligibility filter
    for this rider and this session date — `OPEN` status, a period covering the
    date, and both restrictions satisfied — and a grant that fails any limb is
    rejected with `ERR_GRANT_RESTRICTION_VIOLATION`."
    PRD 3.8: "A grant whose restrictions do not match is silently skipped: an
    empty candidate set contributes 0 and the waterfall simply proceeds, never an
    error."

    Design: Corner/validations/preferred_grant_failing_its_demographic_restriction_returns_grant_restriction_violation
    """
    scenario = setup_active_rider()
    veterans_grant = make_grant(
        grant_name="Veterans Ride",
        funder_name="VA Foundation",
        awarded_amount_cents=100000,
        period_start="2026-01-01",
        period_end="2026-12-31",
        restricted_demographic="VETERAN",
    )
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        duration_minutes=30,
    )
    confirm_session(session["id"], scenario["instructor_id"])

    refused = api.complete_session(
        session["id"],
        {"mounted_minutes": 30, "preferred_grant_id": veterans_grant["id"]},
        scenario["instructor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_GRANT_RESTRICTION_VIOLATION.value)

    completed = validate_success(
        api.complete_session(
            session["id"], {"mounted_minutes": 30}, scenario["instructor_headers"]
        )
    )
    assert completed["schedule_status"] == "COMPLETED"

    grant = read_grant(veterans_grant["id"])
    assert grant["remaining_amount_cents"] == 100000
    assert grant["allocated_amount_cents"] == 0

    charge = only_charge_for_session(session["id"])
    assert charge["amount_cents"] == 4500
    allocations = allocations_for_charge(charge["id"])
    assert allocation_total(allocations, "PRIVATE_PAY") == 4500
    assert allocations_of(allocations, "GRANT") == []
    assert charge["balance_due_cents"] == 4500


def _grant_only_scenario():
    """BAND_D rider, payer 0, one 5000-cent unrestricted grant, a 30-minute session."""
    scenario = setup_active_rider()
    scenario["grant"] = make_grant(
        grant_name="Hooves Fund",
        funder_name="County",
        awarded_amount_cents=5000,
        period_start="2026-01-01",
        period_end="2026-12-31",
    )
    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        duration_minutes=30,
    )
    confirm_session(session["id"], scenario["instructor_id"])
    scenario.update({"session": session, "session_id": session["id"]})
    return scenario


def test_grant_partition_holds_before_during_and_after_a_charge(api):
    """PRD 2.12: "A grant's `awarded_amount_cents` always equals its
    `remaining_amount_cents` plus the sum of `amount_cents` across allocated
    lines that name it, so reversing a charge returns `remaining_amount_cents` to
    exactly its pre-charge value and returns the grant to `OPEN`."
    PRD 2.11: "A charge is `REVERSED` once `reversed_at` is set; otherwise
    `FUNDED` when `balance_due_cents` is 0; otherwise `PENDING`."

    Design: Difficulty/compensating_invariant/grant_awarded_equals_remaining_plus_allocated_across_reversal
    """
    scenario = _grant_only_scenario()
    grant_id = scenario["grant"]["id"]

    before = read_grant(grant_id)
    assert before["awarded_amount_cents"] == 5000
    assert before["remaining_amount_cents"] == 5000
    assert before["allocated_amount_cents"] == 0
    assert_grant_partition(before)

    complete_session(scenario["session_id"], scenario["instructor_id"], 30)
    charge = only_charge_for_session(scenario["session_id"])
    allocations = allocations_for_charge(charge["id"])

    assert charge["amount_cents"] == 4500
    assert allocation_total(allocations, "GRANT") == 4500
    after = read_grant(grant_id)
    assert after["remaining_amount_cents"] == 500
    assert after["allocated_amount_cents"] == 4500
    assert after["status"] == "OPEN"
    assert_grant_partition(after)

    assert charge["balance_due_cents"] == 0
    assert charge["status"] == "FUNDED"
    assert read_session(scenario["session_id"])["billing_status"] == "FUNDED"


def test_reversal_restores_the_grant_ledger_with_zero_drift(api):
    """PRD 2.12: "A grant's `awarded_amount_cents` always equals its
    `remaining_amount_cents` plus the sum of `amount_cents` across allocated
    lines that name it, so reversing a charge returns `remaining_amount_cents` to
    exactly its pre-charge value and returns the grant to `OPEN`."
    PRD 3.8: "Hop two, caused by hop one, moves every one of that charge's
    allocation lines from `ALLOCATED` to `RELEASED`, incrementing each line's
    `version`."

    Design: Difficulty/compensating_invariant/grant_awarded_equals_remaining_plus_allocated_across_reversal
    """
    scenario = _grant_only_scenario()
    grant_id = scenario["grant"]["id"]
    complete_session(scenario["session_id"], scenario["instructor_id"], 30)
    charge = only_charge_for_session(scenario["session_id"])

    validate_success(
        api.reverse_charge(charge["id"], {"reason": "Duplicate billing"}, CLERK)
    )

    restored = read_grant(grant_id)
    assert restored["remaining_amount_cents"] == 5000
    assert restored["allocated_amount_cents"] == 0
    assert_grant_partition(restored)

    grant_lines, meta = validate_paginated(
        api.list_funding_allocations(CLERK, params={"grant_id": grant_id})
    )
    assert meta["total_count"] >= 1
    assert all(line["status"] == "RELEASED" for line in grant_lines)

    reversed_charge = read_charge(charge["id"])
    assert_charge_conservation(reversed_charge, allocations_for_charge(charge["id"]))
