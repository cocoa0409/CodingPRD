"""Grant awards, closed period intervals, the pre-line rate tier, the budget cap
and the reversal that compensates a posted line."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_charge_line,
    assert_grant_award,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_charge_line_payload,
    create_grant_award_payload,
    create_payer_claim_payload,
)
from test_helpers.test_users import BILLING_SPECIALIST, PROGRAM_ADMIN


def _award_with_three_maximal_encounters(employee_code, mrn):
    """One 200 000-cent June award plus three submitted 480-minute encounters."""
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code=employee_code,
        mrn=mrn, full_name="Ines Cruz", monthly_income_cents=120_000,
    )
    award = fx.open_award()
    encounters = [
        fx.submitted_encounter(
            chw_headers, patient["id"], worker["id"], date,
            direct_minutes=400, indirect_minutes=40, travel_minutes=0,
            documentation_minutes=40,
        )
        for date in ("2026-06-02", "2026-06-03", "2026-06-04")
    ]
    return worker, patient, chw_headers, award, encounters


def test_the_rate_tier_is_read_before_the_line_it_prices_posts(api):
    """PRD §3.9: "Second, the rate tier is selected from the award's
    `committed_cents` **as it stands before this line posts**, even though this
    very line is about to move that figure: when `committed_cents` is below
    50000 cents, `hourly_rate_cents` is 4200; when `committed_cents` is 50000
    cents or more, `hourly_rate_cents` is 3800. The tier break is inclusive on
    the upper tier — a `committed_cents` of exactly 50000 selects the 3800-cent
    rate."
    PRD §3.9: "Third, `direct_amount_cents` is `charged_minutes` multiplied by
    `hourly_rate_cents`, divided by 60, and rounded half up to whole cents.
    Fourth, `indirect_amount_cents` is `direct_amount_cents` multiplied by the
    award's `indirect_rate_pct`, divided by 100, and rounded half up to whole
    cents — indirect is a percentage of the direct amount alone, never of any
    combined figure. Fifth, `total_amount_cents` is `direct_amount_cents` plus
    `indirect_amount_cents`."

    Design: Difficulty/combinatorial_formula/grant_rate_tier_read_before_this_line_posts
    """
    worker, patient, chw_headers, award, encounters = (
        _award_with_three_maximal_encounters("W-004", "MRN-040")
    )

    first = fx.post_charge_line(award["id"], encounters[0]["id"])
    assert_charge_line(first)
    assert first["hourly_rate_cents"] == 4200
    assert_cents(first["direct_amount_cents"], 33_600, "line 1 direct_amount_cents")
    assert_cents(first["indirect_amount_cents"], 3_360, "line 1 indirect_amount_cents")
    assert_cents(first["total_amount_cents"], 36_960, "line 1 total_amount_cents")

    second = fx.post_charge_line(award["id"], encounters[1]["id"])
    assert second["hourly_rate_cents"] == 4200, (
        "the pre-line committed_cents of 36960 is still below the 50000 break, so "
        f"line 2 keeps the 4200 rate; got {second['hourly_rate_cents']}"
    )
    assert_cents(second["total_amount_cents"], 36_960, "line 2 total_amount_cents")


def test_the_third_line_is_the_first_to_fall_to_the_lower_rate(api):
    """PRD §3.9: "Second, the rate tier is selected from the award's
    `committed_cents` **as it stands before this line posts**, even though this
    very line is about to move that figure: when `committed_cents` is below
    50000 cents, `hourly_rate_cents` is 4200; when `committed_cents` is 50000
    cents or more, `hourly_rate_cents` is 3800. The tier break is inclusive on
    the upper tier — a `committed_cents` of exactly 50000 selects the 3800-cent
    rate."
    PRD §3.9: "Seventh and last, on success, the award's `committed_cents` rises
    by `total_amount_cents` and its `remaining_budget_cents` is recomputed as
    `budget_cap_cents` minus the new `committed_cents`, with the award's
    `version` incrementing by 1."

    Design: Difficulty/combinatorial_formula/grant_rate_tier_read_before_this_line_posts
    """
    worker, patient, chw_headers, award, encounters = (
        _award_with_three_maximal_encounters("W-004B", "MRN-040B")
    )
    fx.post_charge_line(award["id"], encounters[0]["id"])
    fx.post_charge_line(award["id"], encounters[1]["id"])

    third = fx.post_charge_line(award["id"], encounters[2]["id"])
    assert third["hourly_rate_cents"] == 3800, (
        "the pre-line committed_cents of 73920 sits at or above the break, so line 3 "
        f"drops to 3800; got {third['hourly_rate_cents']}"
    )
    assert_cents(third["direct_amount_cents"], 30_400, "line 3 direct_amount_cents")
    assert_cents(third["indirect_amount_cents"], 3_040, "line 3 indirect_amount_cents")
    assert_cents(third["total_amount_cents"], 33_440, "line 3 total_amount_cents")

    final_award = fx.read_award(award["id"])
    assert_grant_award(final_award)
    assert_cents(final_award["committed_cents"], 107_360, "committed_cents")
    assert_cents(final_award["remaining_budget_cents"], 92_640, "remaining_budget_cents")


def test_a_touching_award_period_collides_within_the_same_funder(api):
    """PRD §2.8: "**Grant award periods are closed.** An award's `period_start`
    and `period_end` are both inclusive service dates. Two award periods for the
    same funder collide when the new period's start falls on or before the
    existing period's end *and* the existing period's start falls on or before
    the new period's end. Touching dates therefore **do** collide: a new period
    beginning on the exact day an existing period ends is rejected. The same
    closed convention governs grant allowability — an encounter is inside an
    award's period when its service date falls on or after `period_start` and on
    or before `period_end`."
    PRD §3.9: "At rung 13, a new award is rejected with
    `ERR_GRANT_PERIOD_OVERLAP` (HTTP 409) when an existing award with the same
    `funder_name` and `status` of `OPEN` has a period that touches or overlaps
    the new one — that is, when the new `period_start` falls on or before the
    existing `period_end` and the existing `period_start` falls on or before the
    new `period_end`."

    Design: Difficulty/resource_temporal_overlap/grant_award_periods_closed_within_funder
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.open_award(
        funder_name="City Health Fund", period_start="2026-06-01",
        period_end="2026-06-30", budget_cap_cents=100_000,
    )

    response = api.create_grant_award(
        create_grant_award_payload(
            funder_name="City Health Fund", period_start="2026-06-30",
            period_end="2026-07-31", budget_cap_cents=100_000,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP.value, 409)
    assert response.status_code == 409


def test_the_day_after_an_award_ends_is_free_and_other_funders_are_unaffected(api):
    """PRD §3.9: "Because the convention is closed rather than half-open, a new
    period beginning on the exact day an existing period ends **is** rejected."
    PRD §3.9: "Two optional inputs shape how the award prices work:
    `indirect_rate_pct`, a number between 0 and 100 inclusive that defaults to
    10, and `allowable_cost_categories`, a non-empty subset of `DIRECT`,
    `INDIRECT` and `DOCUMENTATION` that defaults to all three."
    PRD §3.9: "The award is created with `status` `OPEN`, `committed_cents` of 0
    and `remaining_budget_cents` equal to `budget_cap_cents`."

    Design: Difficulty/resource_temporal_overlap/grant_award_periods_closed_within_funder
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    original = validate_success(
        api.create_grant_award(
            create_grant_award_payload(
                funder_name="City Health Fund", period_start="2026-06-01",
                period_end="2026-06-30", budget_cap_cents=100_000,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert original["indirect_rate_pct"] == 10, (
        f"an omitted indirect_rate_pct defaults to 10, got {original['indirect_rate_pct']}"
    )
    assert_cents(
        original["remaining_budget_cents"], 100_000, "remaining_budget_cents at creation"
    )
    assert_cents(original["committed_cents"], 0, "committed_cents at creation")

    touching = api.create_grant_award(
        create_grant_award_payload(
            funder_name="City Health Fund", period_start="2026-06-30",
            period_end="2026-07-31", budget_cap_cents=100_000,
        ),
        PROGRAM_ADMIN,
    )
    validate_error(touching, ApiErrorId.ERR_GRANT_PERIOD_OVERLAP.value, 409)

    day_after = validate_success(
        api.create_grant_award(
            create_grant_award_payload(
                funder_name="City Health Fund", period_start="2026-07-01",
                period_end="2026-07-31", budget_cap_cents=100_000,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert day_after["status"] == "OPEN", (
        "a period starting the day after an existing period_end is accepted"
    )

    other_funder = validate_success(
        api.create_grant_award(
            create_grant_award_payload(
                funder_name="State Wellness Trust", period_start="2026-06-15",
                period_end="2026-06-20", budget_cap_cents=50_000,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert other_funder["status"] == "OPEN", (
        "the overlap check is scoped to funder_name"
    )


def test_reversing_a_posted_line_returns_every_cent_to_the_award(api):
    """PRD §3.9: "Reversing a `POSTED` line stamps `reversed_at` with the
    current logical clock and moves `status` to `REVERSED`; the line's
    `reversal_reason` takes the supplied value when one is given and defaults to
    `MANUAL_REVERSAL` when it is omitted, while the value `ENCOUNTER_VOIDED` is
    what the void cascade of §3.7 writes."
    PRD §3.9: "The award's `committed_cents` falls by the line's
    `total_amount_cents`, its `remaining_budget_cents` rises by exactly the same
    amount and its `version` increments by 1 — a reversal subtracts precisely
    what the posting added, with no drift."

    Design: Difficulty/compensating_invariant/grant_line_post_then_reverse_conserves_budget_cents
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-024",
        mrn="MRN-220", full_name="Budget Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award, encounter, line = fx.grant_funded_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    assert_cents(line["total_amount_cents"], 4_620, "line total_amount_cents")

    reversed_line = validate_success(
        api.reverse_charge_line(
            line["id"], {"reversal_reason": "MANUAL_REVERSAL"}, BILLING_SPECIALIST
        )
    )
    assert reversed_line["status"] == "REVERSED"

    after = fx.read_award(award["id"])
    assert_cents(after["committed_cents"], 0, "committed_cents after reversal")
    assert_cents(
        after["remaining_budget_cents"], 200_000, "remaining_budget_cents after reversal"
    )


def test_the_reversal_frees_the_encounter_and_balances_the_budget(api):
    """PRD §3.9: "The encounter returns from `LOCKED` to `SUBMITTED` with
    `funding_source` back to `UNFUNDED`, making its minutes claimable again by
    either stream."
    PRD §2.10: "**Grant budget.** An award's `budget_cap_cents` always equals
    its `committed_cents` plus its `remaining_budget_cents`, where
    `committed_cents` is the sum of `total_amount_cents` over that award's
    charge lines whose `status` is `POSTED`. Reversing a line subtracts exactly
    the amount it added."

    Design: Difficulty/compensating_invariant/grant_line_post_then_reverse_conserves_budget_cents
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-024B",
        mrn="MRN-220B", full_name="Budget Case", household_size=1,
    )
    award, encounter, line = fx.grant_funded_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    assert fx.read_encounter(encounter["id"])["status"] == "LOCKED"

    fx.reverse_charge_line(line["id"], "MANUAL_REVERSAL")

    freed = fx.read_encounter(encounter["id"])
    assert freed["status"] == "SUBMITTED"
    assert freed["funding_source"] == "UNFUNDED"

    after = fx.read_award(award["id"])
    assert_grant_award(after)
    assert after["budget_cap_cents"] == (
        after["committed_cents"] + after["remaining_budget_cents"]
    ), "the budget partition must balance with zero drift after the reversal"
    assert_cents(after["budget_cap_cents"], 200_000, "budget_cap_cents")


def test_a_charge_line_with_a_stale_award_version_is_rejected(api):
    """PRD §2.7: "Posting a grant charge line requires
    `expected_grant_award_version`, carrying the client's last observed
    `version` of the `GrantAward` named by `grant_award_id`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_GRANT_VERSION` (HTTP
    412)."

    Design: Corner/validations/stale_grant_award_version_on_charge_line_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-034",
        mrn="MRN-C34", full_name="Grant OCC Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award = fx.open_award()
    observed_version = award["version"]
    first = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    second = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-11",
    )
    fx.post_charge_line(
        award["id"], first["id"], expected_grant_award_version=observed_version
    )

    response = api.create_charge_line(
        create_charge_line_payload(award["id"], second["id"], observed_version),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_STALE_GRANT_VERSION.value, 412)

    assert_cents(
        fx.read_award(award["id"])["committed_cents"], 4_620,
        "committed_cents after the rejected second line",
    )
    reread = fx.read_encounter(second["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["funding_source"] == "UNFUNDED"

    _rows, meta = validate_paginated(
        api.list_charge_lines(
            BILLING_SPECIALIST, params={"grant_award_id": award["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_line_that_would_breach_the_cap_is_rejected_outright(api):
    """PRD §3.9: "**The budget gate.** Sixth in that order, and at rung 17 of
    the ladder, the award's `committed_cents` plus this line's
    `total_amount_cents` must not exceed `budget_cap_cents`. A line that would
    breach the cap is rejected outright with `ERR_GRANT_BUDGET_EXCEEDED` (HTTP
    422); it is never trimmed to fit the remaining budget."

    Design: Corner/validations/grant_budget_exceeded_rejects_the_whole_line
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-041",
        mrn="MRN-C41", full_name="Budget Cap Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award = fx.open_award(funder_name="Small Fund", budget_cap_cents=4_000)
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    assert encounter["billable_minutes"] == 60

    response = api.create_charge_line(
        create_charge_line_payload(award["id"], encounter["id"], award["version"]),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED.value, 422)

    after = fx.read_award(award["id"])
    assert_cents(after["committed_cents"], 0, "committed_cents")
    assert_cents(after["remaining_budget_cents"], 4_000, "remaining_budget_cents")

    reread = fx.read_encounter(encounter["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["funding_source"] == "UNFUNDED"

    _rows, meta = validate_paginated(
        api.list_charge_lines(
            BILLING_SPECIALIST, params={"grant_award_id": award["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected line was never created"


def test_a_payer_locked_encounter_cannot_also_be_charged_to_a_grant(api):
    """PRD §3.9: "An encounter already carved to a payer claim, or to another
    grant line, has a `funding_source` of `PAYER` or `GRANT` and is rejected at
    rung 15 with `ERR_MINUTES_ALREADY_FUNDED` (HTTP 409)."

    Design: Corner/validations/grant_line_on_payer_locked_encounter_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-042",
        mrn="MRN-C42", full_name="Double Dip Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award = fx.open_award()
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    claim = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )

    response = api.create_charge_line(
        create_charge_line_payload(award["id"], encounter["id"], award["version"]),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_MINUTES_ALREADY_FUNDED.value, 409)

    reread = fx.read_encounter(encounter["id"])
    assert reread["funding_source"] == "PAYER"
    assert reread["funding_claim_id"] == claim["id"]
    assert_cents(fx.read_award(award["id"])["committed_cents"], 0, "committed_cents")


def test_an_encounter_dated_outside_the_closed_period_is_not_allowable(api):
    """PRD §3.9: "Then, still at rung 15 but after the funding check, comes
    allowability: the encounter's `encounter_date` must fall inside the award's
    closed period — on or after `period_start` and on or before `period_end` —
    and the encounter must carry at least one minute in a category the award's
    `allowable_cost_categories` lists, where `DIRECT` corresponds to
    `direct_minutes`, `INDIRECT` to `indirect_minutes` and `DOCUMENTATION` to
    `documentation_minutes`. An encounter dated outside the period, or one whose
    only minutes are `travel_minutes`, is rejected with
    `ERR_ENCOUNTER_NOT_ALLOWABLE` (HTTP 422)."

    Design: Corner/validations/grant_line_outside_award_period_not_allowable
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-07-10T00:00:00Z", employee_code="C-044",
        mrn="MRN-C44", full_name="Period Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award = fx.open_award()
    inside = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-30",
    )
    outside = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-07-01",
    )

    observed_version = fx.award_version(award["id"])
    refused = api.create_charge_line(
        create_charge_line_payload(award["id"], outside["id"], observed_version),
        BILLING_SPECIALIST,
    )
    validate_error(refused, ApiErrorId.ERR_ENCOUNTER_NOT_ALLOWABLE.value, 422)

    accepted = validate_success(
        api.create_charge_line(
            create_charge_line_payload(award["id"], inside["id"], observed_version),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert_cents(
        accepted["total_amount_cents"], 4_620,
        "2026-06-30 sits inside the closed period and prices normally",
    )

    assert fx.read_encounter(outside["id"])["service_month"] == "2026-07"
    assert fx.read_encounter(outside["id"])["funding_source"] == "UNFUNDED"
    assert_cents(
        fx.read_award(award["id"])["committed_cents"], 4_620, "committed_cents"
    )


def test_a_travel_only_encounter_is_never_allowable_to_a_grant(api):
    """PRD §3.9: "Travel is never an allowable cost category no matter what that
    list contains."
    PRD §3.9: "An encounter dated outside the period, or one whose only minutes
    are `travel_minutes`, is rejected with `ERR_ENCOUNTER_NOT_ALLOWABLE` (HTTP
    422)."

    Design: Corner/validations/travel_only_encounter_not_allowable_to_grant
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-045",
        mrn="MRN-C45", full_name="Travel Only Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award = fx.open_award()
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-12",
        direct_minutes=0, indirect_minutes=0, travel_minutes=45,
        documentation_minutes=0, travel_miles=12.0,
    )
    assert encounter["raw_billable_minutes"] == 0
    assert encounter["billable_minutes"] == 0
    assert encounter["total_minutes"] == 45
    assert_cents(
        encounter["travel_reimbursement_cents"], 780,
        "12 miles at 10x67 + 2x55 marginal band rates",
    )

    response = api.create_charge_line(
        create_charge_line_payload(award["id"], encounter["id"], award["version"]),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_ENCOUNTER_NOT_ALLOWABLE.value, 422)

    assert_cents(fx.read_award(award["id"])["committed_cents"], 0, "committed_cents")
