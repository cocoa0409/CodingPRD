"""Partner settlement: the six-step pricing sequence, closed periods, and the
cyclic settlement dimension."""
import pytest

from test_helpers import (
    ADMIN,
    MONTH_WINDOWS,
    ApiErrorId,
    api_client,
    assert_gallons_equal,
    factories,
    fixtures,
    make_settlement_clerk_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]
SEPTEMBER_START, SEPTEMBER_END = MONTH_WINDOWS["2026-09"]


def _five_hundred_gallon_month():
    """Two 250-gallon fills at one partner station, drafted into one August
    batch that has not been submitted yet."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.partner_fuel_program(
        points=600,
        alt_id="5550000004",
        max_gallons_per_redemption=250,
        banner_code="SET",
        name="Settlement Banner",
    )
    first = fixtures.add_dispensed_fill(program, 300, 250.0)
    second = fixtures.add_dispensed_fill(program, 300, 250.0)
    batch = fixtures.open_batch(program["partner"]["id"], AUGUST_START, AUGUST_END)
    program["fills"] = [first, second]
    program["batch"] = batch
    return program


def test_admin_fee_is_taken_from_the_pre_fee_figure_and_not_from_the_gross():
    """The fee follows the tier discount rather than preceding it, which is a
    thirty-four cent difference on this batch.

    PRD: "`admin_fee_cents` is the lesser of a fee cap of 50,000 cents (five
    hundred dollars) and one and a half percent — a rate of 0.015 — of
    `pre_fee_reimbursement_cents`, rounded half up to whole cents. The fee is
    computed from the **pre-fee** figure and from nothing else — not from the
    final reimbursement, which would be self-referential, and not from
    `gross_discount_cents`, which gives a different answer."

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_is_taken_from_the_pre_fee_reimbursement
    """
    program = _five_hundred_gallon_month()

    priced = fixtures.submit_batch(program["batch"]["id"], program["partner"]["id"])

    assert priced["redemption_count"] == 2
    assert_gallons_equal(priced["gallons_total"], "500.000")
    assert priced["gross_discount_cents"] == 15000
    assert priced["tier_rate_pct"] == pytest.approx(0.85, abs=0.0001)
    assert priced["pre_fee_reimbursement_cents"] == 12750
    assert priced["admin_fee_cents"] == 191
    assert priced["admin_fee_cents"] != 225, (
        "225 is 1.5% of the gross discount, the forbidden order"
    )
    assert priced["reimbursement_cents"] == 12559


def test_submission_claims_every_pending_fill_and_empties_the_unbatched_pool():
    """Exactly 500.000 gallons still takes the low tier, and claiming the fills
    drains the site's pool.

    PRD: "Submission claims **every** qualifying pending redemption, driving each
    from `PENDING` to `BATCHED` on the settlement dimension and stamping its
    `settlement_batch_id` with this batch's identifier, which also removes that
    row's gallons and discount from the site's unbatched pool."

    PRD: "The band edges are inclusive upper bounds of the lower band, so a total
    of exactly 500.000 gallons is still the low tier and the mid tier begins at
    500.001, while exactly 2,000.000 gallons is still the mid tier and the high
    tier begins at 2,000.001."

    Design: Difficulty/combinatorial_formula/settlement_admin_fee_is_taken_from_the_pre_fee_reimbursement
    """
    program = _five_hundred_gallon_month()
    partner_id = program["partner"]["id"]
    batch_id = program["batch"]["id"]

    submitted = fixtures.submit_batch(batch_id, partner_id)
    assert submitted["status"] == "SUBMITTED"

    for fill in program["fills"]:
        claimed = fixtures.get_redemption(fill["id"])
        assert claimed["settlement_status"] == "BATCHED"
        assert claimed["settlement_batch_id"] == batch_id

    site = fixtures.get_site(partner_id)
    assert_gallons_equal(site["unbatched_gallons"], "0.000")
    assert site["unbatched_discount_cents"] == 0


def _submitted_first_half_of_august():
    """One partner station whose first-half-of-August batch is already
    submitted."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300,
        alt_id="5550000016",
        banner_code="PER",
        name="Period Banner",
    )
    fixtures.add_dispensed_fill(program, 300, 12.345)
    first = fixtures.open_batch(
        program["partner"]["id"], AUGUST_START, "2026-08-15T00:00:00Z"
    )
    fixtures.submit_batch(first["id"], program["partner"]["id"])
    program["first_batch"] = first
    return program


def _draft_attempt(site_id: str, period_start: str, period_end: str):
    """Draft a batch with a freshly read site version, as the site's clerk."""
    return api_client.create_settlement_batch(
        factories.settlement_batch_payload(
            site_id, period_start, period_end, fixtures.site_version(site_id)
        ),
        make_settlement_clerk_headers(site_id),
    )


def test_a_following_period_must_begin_strictly_after_the_prior_period_end():
    """Periods are closed on both ends, so touching at one instant overlaps and
    one millisecond of gap is enough.

    PRD: "Settlement periods are **closed** on both ends, so two periods that
    merely touch at one instant **do** overlap and a following period must begin
    strictly after the prior `period_end` — one millisecond of gap is
    sufficient."

    Design: Difficulty/resource_temporal_overlap/settlement_closed_periods_reject_touching_endpoints_then_hit_open_batch_limit
    """
    program = _submitted_first_half_of_august()
    partner_id = program["partner"]["id"]

    validate_error(
        _draft_attempt(partner_id, "2026-08-15T00:00:00Z", AUGUST_END),
        ApiErrorId.ERR_BATCH_PERIOD_OVERLAP.value,
    )

    accepted = validate_success(
        _draft_attempt(partner_id, "2026-08-15T00:00:00.001Z", AUGUST_END), 201
    )
    assert accepted["status"] == "DRAFT"


def test_a_third_open_batch_is_refused_by_the_open_batch_limit():
    """With one submitted and one draft batch standing, a non-overlapping third
    period is still refused.

    PRD: "Finally the site may not carry two or more batches in `DRAFT` or
    `SUBMITTED` status, counted **after** any such supersession has been applied,
    or the request fails with `ERR_OPEN_BATCH_LIMIT`."

    Design: Difficulty/resource_temporal_overlap/settlement_closed_periods_reject_touching_endpoints_then_hit_open_batch_limit
    """
    program = _submitted_first_half_of_august()
    partner_id = program["partner"]["id"]

    validate_success(
        _draft_attempt(partner_id, "2026-08-15T00:00:00.001Z", AUGUST_END), 201
    )

    validate_error(
        _draft_attempt(partner_id, SEPTEMBER_START, SEPTEMBER_END),
        ApiErrorId.ERR_OPEN_BATCH_LIMIT.value,
    )

    assert (
        fixtures.get_batch(program["first_batch"]["id"])["status"] == "SUBMITTED"
    )
    _rows, meta = validate_paginated(
        api_client.list_settlement_batches(ADMIN, {"site_id": partner_id})
    )
    assert meta["total_count"] == 2


def _submitted_single_fill_batch():
    """One 12.345-gallon fill priced into a submitted August batch."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300,
        alt_id="5550000018",
        banner_code="POOL",
        name="Pool Banner",
    )
    fill = fixtures.add_dispensed_fill(program, 300, 12.345)
    pool_before = fixtures.get_site(program["partner"]["id"])
    batch = fixtures.open_batch(program["partner"]["id"], AUGUST_START, AUGUST_END)
    priced = fixtures.submit_batch(batch["id"], program["partner"]["id"])
    program["fill"] = fill
    program["pool_before"] = pool_before
    program["batch"] = priced
    return program


def test_rejecting_a_batch_returns_the_unbatched_pool_to_the_exact_cent():
    """Rejection is the exact inverse of submission: the pool comes back with no
    drift and the fill returns to pending.

    PRD: "Rejection is the exact compensating action for submission: the site's
    unbatched gallons return to their pre-submission value with no drift
    whatsoever, and the settlement dimension of a redemption is genuinely cyclic
    — `PENDING → BATCHED → PENDING` — while its authorization dimension stays
    `DISPENSED` throughout."

    Design: Difficulty/compensating_invariant/batch_rejection_restores_partner_unbatched_pool_to_the_exact_cent
    """
    program = _submitted_single_fill_batch()
    partner_id = program["partner"]["id"]

    assert program["fill"]["discount_amount_cents"] == 370
    assert_gallons_equal(program["pool_before"]["unbatched_gallons"], "12.345")
    assert program["pool_before"]["unbatched_discount_cents"] == 370
    assert program["batch"]["reimbursement_cents"] == 310

    rejected = fixtures.reject_batch(program["batch"]["id"])
    assert rejected["status"] == "REJECTED"

    site = fixtures.get_site(partner_id)
    assert_gallons_equal(site["unbatched_gallons"], "12.345")
    assert site["unbatched_discount_cents"] == 370

    fill = fixtures.get_redemption(program["fill"]["id"])
    assert fill["settlement_status"] == "PENDING"
    assert fill["settlement_batch_id"] is None
    assert fill["authorization_status"] == "DISPENSED"


def test_rejecting_a_batch_zeroes_all_seven_totals_and_spares_the_site_balance():
    """The rejected batch keeps no priced figure, and the site's cumulative
    settlement balance never moved because nothing was approved.

    PRD: "All seven computed totals — `redemption_count`, `gallons_total`,
    `gross_discount_cents`, `tier_rate_pct`, `pre_fee_reimbursement_cents`,
    `admin_fee_cents` and `reimbursement_cents` — are reset to zero."

    PRD: "The site's `unbatched_gallons` and `unbatched_discount_cents` are
    recomputed and its `version` increments by one, while
    `settlement_balance_cents` is left completely untouched."

    Design: Difficulty/compensating_invariant/batch_rejection_restores_partner_unbatched_pool_to_the_exact_cent
    """
    program = _submitted_single_fill_batch()

    rejected = fixtures.reject_batch(program["batch"]["id"])

    assert rejected["redemption_count"] == 0
    assert_gallons_equal(rejected["gallons_total"], "0.000")
    assert rejected["gross_discount_cents"] == 0
    assert rejected["tier_rate_pct"] == pytest.approx(0, abs=0.0001)
    assert rejected["pre_fee_reimbursement_cents"] == 0
    assert rejected["admin_fee_cents"] == 0
    assert rejected["reimbursement_cents"] == 0

    site = fixtures.get_site(program["partner"]["id"])
    assert site["settlement_balance_cents"] == 0


def test_the_settlement_dimension_cycles_while_the_pump_dimension_stands_still():
    """A fill goes pending, batched and pending again without its authorization
    dimension ever leaving `DISPENSED`.

    PRD: "This is the only place the settlement dimension ever leaves
    `NOT_APPLICABLE`, and the two dimensions of a redemption are otherwise fully
    independent."

    Design: Difficulty/non_linear_state_machine/redemption_settlement_axis_cycles_while_authorization_axis_is_frozen
    """
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300, alt_id="5550000006", banner_code="PAR", name="Parallel Banner"
    )
    partner_id = program["partner"]["id"]
    fill = fixtures.add_dispensed_fill(program, 300, 12.345)

    assert fill["discount_amount_cents"] == 370
    assert fill["authorization_status"] == "DISPENSED"
    assert fill["settlement_status"] == "PENDING"

    first_batch = fixtures.open_batch(partner_id, AUGUST_START, AUGUST_END)
    fixtures.submit_batch(first_batch["id"], partner_id)
    assert fixtures.get_redemption(fill["id"])["settlement_status"] == "BATCHED"

    rejected = fixtures.reject_batch(first_batch["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["reimbursement_cents"] == 0

    after_reject = fixtures.get_redemption(fill["id"])
    assert after_reject["settlement_status"] == "PENDING"
    assert after_reject["authorization_status"] == "DISPENSED"


def test_a_second_batch_over_the_same_period_settles_the_fill_for_good():
    """The freed gallons are settleable again, and approval is what finally
    credits the partner.

    PRD: "Every claimed redemption is driven from `BATCHED` to `SETTLED` on the
    settlement dimension, and its gallons and discount stay out of the unbatched
    pool permanently. The batch's `reimbursement_cents` is added to the site's
    `settlement_balance_cents`, and the site's `version` increments by one."

    Design: Difficulty/non_linear_state_machine/redemption_settlement_axis_cycles_while_authorization_axis_is_frozen
    """
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300, alt_id="5550000006", banner_code="PAR", name="Parallel Banner"
    )
    partner_id = program["partner"]["id"]
    fill = fixtures.add_dispensed_fill(program, 300, 12.345)

    first_batch = fixtures.open_batch(partner_id, AUGUST_START, AUGUST_END)
    fixtures.submit_batch(first_batch["id"], partner_id)
    fixtures.reject_batch(first_batch["id"])

    second_batch = fixtures.open_batch(partner_id, AUGUST_START, AUGUST_END)
    fixtures.submit_batch(second_batch["id"], partner_id)
    approved = fixtures.approve_batch(second_batch["id"])

    assert approved["status"] == "APPROVED"
    assert approved["reimbursement_cents"] == 310

    settled = fixtures.get_redemption(fill["id"])
    assert settled["authorization_status"] == "DISPENSED"
    assert settled["settlement_status"] == "SETTLED"
    assert settled["settlement_batch_id"] == second_batch["id"]

    site = fixtures.get_site(partner_id)
    assert site["settlement_balance_cents"] == 310
