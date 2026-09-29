"""Thresholds tested on their exact boundary point and one unit either side."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.factories import create_claim_payload

# The three submissions differ only in hard_cost_value_cents, which walks the
# value component of the score through 14, 15 and 16 points.
FRAME_PART_PLAN = (
    ("SOFT_COST", 500000000),
    ("DELAY_IN_COMPLETION", 400000000),
)


def _frame_draft(name, site_address, hard_cost_value_cents):
    """A FRAME / FLOOD_A draft whose schedule is not yet rateable."""
    project_inputs = dict(fx.gulfside_project_inputs())
    project_inputs.update({
        "name": name,
        "site_address": site_address,
        "hard_cost_value_cents": hard_cost_value_cents,
        "engineering_grade": "B",
    })
    return fx.draft_account(
        parts=FRAME_PART_PLAN, with_owner=False,
        project_overrides=project_inputs, **fx.gulfside_policy_inputs())


def _rate(account):
    """Complete the schedule with the mandatory materials cover, then rate."""
    fx.schedule_part(account, "MATERIALS_ON_SITE", 6000000000)
    return get_success_data(api_client.quote_policy(account.policy_id, fx.UW))


def test_a_score_one_point_below_the_referral_threshold_quotes_straight_through():
    """74 points is below 75, so rating takes DRAFT -> QUOTED and the premium is
    offerable. The premium itself is untouched by the branch.

    Design: Difficulty/boundary_precision_check/referral_threshold_at_74_75_and_76_score_points
    """
    account = _frame_draft(
        "Gulfside Frame Towers A", "1 Gulfside Blvd, Port Cyrus", 7000000000)
    assert account.project["submission_risk_score"] == 74, account.project

    policy = _rate(account)
    assert policy["status"] == "QUOTED", policy
    assert policy["quoted_premium_cents"] == 19058460, policy


def test_the_referral_threshold_is_inclusive_so_the_boundary_point_itself_refers():
    """The comparison is 75 or more, not strictly greater than 75: the score that
    lands exactly on the threshold already refers, as does the score one point
    above it. Both still carry the rated premium with no referral load attached,
    because loading is the manager's act and not rating's.

    Design: Difficulty/boundary_precision_check/referral_threshold_at_74_75_and_76_score_points
    """
    at_threshold = _frame_draft(
        "Gulfside Frame Towers B", "3 Gulfside Blvd, Port Cyrus", 7500000000)
    assert at_threshold.project["submission_risk_score"] == 75, at_threshold.project
    above = _frame_draft(
        "Gulfside Frame Towers C", "5 Gulfside Blvd, Port Cyrus", 8000000000)
    assert above.project["submission_risk_score"] == 76, above.project

    boundary_policy = _rate(at_threshold)
    assert boundary_policy["status"] == "REFERRED", boundary_policy
    assert boundary_policy["quoted_premium_cents"] == 20385450, boundary_policy
    assert float(boundary_policy["referral_load_pct"]) == 0.0, boundary_policy

    above_policy = _rate(above)
    assert above_policy["status"] == "REFERRED", above_policy
    assert above_policy["quoted_premium_cents"] == 21712440, above_policy


DELAY_PART_PLAN = (
    ("DELAY_IN_COMPLETION", 250000000),
    ("SOFT_COST", 300000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def _delay_claim_at_six_raw_days():
    """Baseline 2027-06-01 against an actual completion of 2027-06-07."""
    account = fx.in_force_account(parts=DELAY_PART_PLAN)
    assert account.policy["quoted_premium_cents"] == 2750440, account.policy
    claim = fx.report_claim(
        account, peril="DELAY", loss_date="2027-06-09T00:00:00Z",
        description="Completion slipped past the projected date")
    fx.set_clock("2027-06-10T00:00:00Z")
    project = fx.declare_substantial_completion(
        account, "2027-06-07T00:00:00Z", advance_clock=False)
    assert project["status"] == "SUBSTANTIALLY_COMPLETE", project
    assert project["actual_substantial_completion_date"].startswith("2027-06-07"), project
    return account, claim


def test_one_raw_day_past_the_waiting_period_indemnifies_exactly_one_day():
    """Six whole days of slip less the five-day waiting period leaves one
    indemnified day, priced at the policy's daily delay rate. The delay line is
    never touched by the money deductible, so the indemnity is the full
    1200000 and adjustment reserves without eroding the bucket.

    Design: Difficulty/boundary_precision_check/delay_waiting_period_at_four_five_and_six_raw_days
    """
    account, claim = _delay_claim_at_six_raw_days()

    adjusted = fx.adjust_claim(account, claim, adjustment_basis="ACTUAL_LOSS")
    assert adjusted["delay_days_indemnified"] == 1, adjusted
    assert adjusted["indemnity_cents"] == 1200000, adjusted
    assert adjusted["adjustment_status"] == "ADJUSTED", adjusted

    delay_part = account.refresh_parts()["DELAY_IN_COMPLETION"]
    assert delay_part["eroded_cents"] == 0, delay_part


def test_approved_extensions_push_the_baseline_to_and_below_the_waiting_period():
    """Each approved extension moves the delay baseline forward by its days, so
    the same actual completion date yields fewer raw days. At exactly five raw
    days the subtraction floors to zero indemnified days, and at four it stays
    zero without going negative. The re-adjustments hold the axis at ADJUSTED,
    because the denial branch is only reachable out of REPORTED or REOPENED.

    Design: Difficulty/boundary_precision_check/delay_waiting_period_at_four_five_and_six_raw_days
    """
    account, claim = _delay_claim_at_six_raw_days()
    fx.adjust_claim(account, claim, adjustment_basis="ACTUAL_LOSS")

    first = fx.file_endorsement(account, 1, slip_reason="WEATHER")
    assert first["additional_premium_cents"] == 9107, first
    assert first["revised_completion_date"].startswith("2027-06-02"), first
    fx.decide_endorsement(account, first, "APPROVE", headers=fx.UM)

    at_threshold = fx.adjust_claim(account, claim, adjustment_basis="ACTUAL_LOSS")
    assert at_threshold["delay_days_indemnified"] == 0, at_threshold
    assert at_threshold["indemnity_cents"] == 0, at_threshold
    assert at_threshold["uncovered_cents"] == 0, at_threshold
    assert at_threshold["adjustment_status"] == "ADJUSTED", at_threshold

    second = fx.file_endorsement(account, 1, slip_reason="WEATHER")
    assert second["additional_premium_cents"] == 9107, second
    fx.decide_endorsement(account, second, "APPROVE", headers=fx.UM)

    below = fx.adjust_claim(account, claim, adjustment_basis="ACTUAL_LOSS")
    assert below["delay_days_indemnified"] == 0, below
    assert below["indemnity_cents"] == 0, below
    assert below["uncovered_cents"] == 0, below
    assert below["adjustment_status"] == "ADJUSTED", below

    delay_part = account.refresh_parts()["DELAY_IN_COMPLETION"]
    assert delay_part["eroded_cents"] == 0, delay_part


EXTENDED_PART_PLAN = (
    ("SOFT_COST", 300000000),
    ("DELAY_IN_COMPLETION", 250000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def _account_with_extended_term():
    """A 45-day approved extension pushes the expiry to 2027-08-14."""
    account = fx.in_force_account(parts=EXTENDED_PART_PLAN)
    assert account.policy["quoted_premium_cents"] == 2750440, account.policy
    endorsement = fx.file_endorsement(account, 45, slip_reason="MATERIAL_DELAY")
    assert endorsement["additional_premium_cents"] == 471287, endorsement
    fx.decide_endorsement(account, endorsement, "APPROVE", headers=fx.UM)
    policy = account.refresh_policy()
    assert policy["term_end_date"].startswith("2027-08-14"), policy
    return account


def _notice(account, peril, loss_date, description):
    payload = create_claim_payload(
        account.policy_id, peril=peril, loss_date=loss_date,
        description=description)
    return api_client.create_claim(payload, fx.CA)


def test_the_upper_loss_date_bound_follows_the_extension_and_stays_inclusive():
    """The closed upper bound is the term_end_date as it now stands, so a loss on
    2027-08-14 is accepted while one on 2027-08-15 is refused, and a loss on the
    originally bound 2027-06-30 end is still inside the term.

    Design: Difficulty/boundary_precision_check/loss_date_inclusive_bounds_against_the_extended_term_reject_one_day_out
    """
    account = _account_with_extended_term()

    on_bound = get_success_data(
        _notice(account, "WIND", "2027-08-14T00:00:00Z",
                "Loss on the last day of the extended term"), expected_status=201)
    assert on_bound["adjustment_status"] == "REPORTED", on_bound

    past_bound = _notice(account, "WIND", "2027-08-15T00:00:00Z",
                         "Loss one day after the extended term")
    validate_error(past_bound, "ERR_LOSS_DATE_OUTSIDE_TERM", expected_status=422)

    original_end = get_success_data(
        _notice(account, "WATER_DAMAGE", "2027-06-30T00:00:00Z",
                "Loss on the originally bound term end"), expected_status=201)
    assert original_end["adjustment_status"] == "REPORTED", original_end


def test_the_lower_loss_date_bound_is_inclusive_at_inception_and_rejects_the_day_before():
    """The lower bound is closed at term_start_date: a loss dated on the
    inception day is accepted and one dated the day before is refused. Across
    all five probes only the three admissible notices exist afterwards, so the
    rejections wrote nothing.

    Design: Difficulty/boundary_precision_check/loss_date_inclusive_bounds_against_the_extended_term_reject_one_day_out
    """
    account = _account_with_extended_term()

    get_success_data(_notice(account, "WIND", "2027-08-14T00:00:00Z",
                             "Loss on the last day of the extended term"),
                     expected_status=201)
    validate_error(_notice(account, "WIND", "2027-08-15T00:00:00Z",
                           "Loss one day after the extended term"),
                   "ERR_LOSS_DATE_OUTSIDE_TERM", expected_status=422)

    on_inception = get_success_data(
        _notice(account, "FIRE", "2026-09-01T00:00:00Z", "Loss on the inception day"),
        expected_status=201)
    assert on_inception["adjustment_status"] == "REPORTED", on_inception

    before_inception = _notice(
        account, "FIRE", "2026-08-31T00:00:00Z", "Loss one day before inception")
    validate_error(before_inception, "ERR_LOSS_DATE_OUTSIDE_TERM", expected_status=422)

    get_success_data(_notice(account, "WATER_DAMAGE", "2027-06-30T00:00:00Z",
                             "Loss on the originally bound term end"),
                     expected_status=201)

    rows, _meta = validate_paginated(api_client.list_policy_claims(
        account.policy_id, fx.CA, params={"limit": 100}))
    assert len(rows) == 3, f"only the admissible notices may persist: {rows}"
