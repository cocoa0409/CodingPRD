"""Commission, clawback and exposure arithmetic at its pinned boundaries.

Every test here recomputes the money from the PRD's own arithmetic and asserts
exact cents, exact basis-point adders and exact integer scores: the volume-tier
boundary at the fifth closed unit (PRD 3.5, 3.7), the strict three-hundred
character radio limit (PRD 3.8), the inclusive one-hundred-and-eighty day
recapture boundary (PRD 3.7), the reconciliation input filter (PRD 3.7), the
single rounding of the assembled exposure sum (PRD 3.7) and the close-order
origin of `closed_unit_index` (PRD 3.5).
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import build_advertisement_review
from test_helpers.fixtures import (
    close_loan,
    decide_pricing_exception,
    draft_advertisement,
    get_originator,
    lock_loan,
    payoff_loan,
    request_pricing_exception,
    run_reconciliation,
    set_clock,
    setup_authorized_originator,
    setup_originator_with_plan,
    sole_record_for_loan,
    submit_advertisement,
    take_loan,
)
from test_helpers.test_users import OFFICER_USER_ID, officer_headers

# The 300-character radio script the boundary is measured on. It discloses both
# the originator's NMLS identifier and its CA licence number, so no disclosure
# finding other than the length one can possibly fire.
NMLS_ID = "2200001"
LICENSE_NUMBER = "CA-DFPI-70001"
RADIO_SCRIPT_300 = (
    "Avery Lane, NMLS 2200001, California licence CA-DFPI-70001. Rates and terms are "
    "subject to credit approval and may change without notice; ask your licensed "
    "originator for the current written estimate and disclosure packet before you "
    "apply for any residential mortgage loan product in California today"
)
RADIO_SCRIPT_301 = RADIO_SCRIPT_300 + "."


def _instant(value):
    """Parse an ISO 8601 UTC timestamp, so two encodings of one moment compare equal."""
    assert value is not None, "expected a timestamp, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _tiered_plan_context(api):
    """An authorised originator on an ACTIVE plan at 200 bps with the volume tier live."""
    return setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 200,
            "min_fee_cents": 0,
            "max_fee_cents": 5_000_000,
            "volume_tier_enabled": True,
            "concession_absorption_enabled": False,
        },
    )


def _flat_plan_context(api, **kwargs):
    """An authorised originator on an ACTIVE plan at 105 bps with no tier and no absorption."""
    return setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 0,
            "max_fee_cents": 5_000_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
        **kwargs,
    )


def _close_one_loan(api, originator_id, amount_cents, funded_at, **close_overrides):
    """Take, lock and close one loan whose funded amount equals its locked amount."""
    loan = take_loan(api, originator_id, requested_amount_cents=amount_cents, par_rate_bps=650)
    lock_loan(api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=amount_cents)
    close_payload = {
        "funded_amount_cents": amount_cents,
        "funded_at": funded_at,
        "lender_paid_comp_cents": 0,
        "borrower_paid_comp_cents": 0,
        "file_quality_score": 95,
        "hours_worked_pct": 80,
    }
    close_payload.update(close_overrides)
    return close_loan(api, loan["id"], **close_payload)


def test_fifth_close_lifts_every_final_line_to_the_second_volume_tier(api):
    """Reconciliation's forward-looking unit count moves all five lines off tier one.

    Every provisional line was priced with a unit count of four or fewer, so PRD
    3.5 gives each of them a zero adder: "A unit count of four or fewer yields a
    tier value of zero basis points. A count of five through nine - that is, more
    than four but no more than nine - yields fifteen basis points." The fifth
    close makes the reconciliation run count five closed units for *every* line,
    because PRD 3.7 says "the unit count it feeds into the volume tier is the
    count of the originator's loan applications whose `status` is `CLOSED` or
    `PAID_OFF` at the instant the reconciliation run executes, rather than the
    loan's own `closed_unit_index` less one."

    The quality-75 file keeps a lower adder because PRD 3.5 says "A score of at
    least seventy but below ninety incurs a penalty of ten basis points", and
    the clamp of PRD 3.5 step 3 held its provisional adder at zero rather than
    letting it go negative.

    Design: Corner/calculations/volume_tier_boundary_fifth_unit_lifts_final_lines_to_tier_two
    """
    context = _tiered_plan_context(api)
    originator_id = context["originator"]["id"]

    first = _close_one_loan(
        api, originator_id, 5_000_000, "2026-08-02T00:00:00Z", lender_paid_comp_cents=100_000
    )
    for funded_at in ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z"):
        _close_one_loan(
            api, originator_id, 5_000_000, funded_at, lender_paid_comp_cents=100_000
        )
    fifth = _close_one_loan(
        api,
        originator_id,
        10_000_000,
        "2026-08-06T00:00:00Z",
        lender_paid_comp_cents=200_000,
        file_quality_score=75,
    )

    assert first["closed_unit_index"] == 1
    assert fifth["closed_unit_index"] == 5

    # The fifth file's provisional line: unit count four, so tier zero; the
    # quality penalty of ten is clamped back up to zero, never negative.
    provisional_fifth = sole_record_for_loan(api, fifth["id"])
    assert provisional_fifth["variant"] == "PROVISIONAL"
    assert provisional_fifth["tier_bps_adder"] == 0
    assert provisional_fifth["accrued_cents"] == 200_000

    report = run_reconciliation(api, originator_id)
    assert report["reconciled_count"] == 5
    # 4 x round_half_up(5000000 * 215 / 10000) + round_half_up(10000000 * 205 / 10000)
    # = 4 x 107500 + 205000 = 635000, against a pre-run 4 x 100000 + 200000 = 600000.
    assert report["total_final_cents"] == 635_000
    assert report["total_delta_cents"] == 35_000

    final_first = sole_record_for_loan(api, first["id"])
    assert final_first["variant"] == "FINAL"
    assert final_first["tier_bps_adder"] == 15
    assert final_first["accrued_cents"] == 107_500
    assert final_first["paid_cents"] == 107_500

    final_fifth = sole_record_for_loan(api, fifth["id"])
    assert final_fifth["tier_bps_adder"] == 5
    assert final_fifth["accrued_cents"] == 205_000

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 635_000
    assert originator["net_compensation_cents"] == 635_000


def _radio_advertisement(api, content_text):
    """A submitted RADIO advertisement disclosing both required identifiers."""
    context = setup_authorized_originator(
        api,
        originator_overrides={"nmls_unique_id": NMLS_ID, "legal_name": "Avery Lane"},
        license_overrides={"license_number": LICENSE_NUMBER},
    )
    originator_id = context["originator"]["id"]
    advertisement = draft_advertisement(
        api,
        originator_id,
        medium="RADIO",
        content_text=content_text,
        target_state_codes=["CA"],
        disclosed_nmls_ids=[NMLS_ID],
        disclosed_license_numbers=[LICENSE_NUMBER],
    )
    return submit_advertisement(api, advertisement["id"], originator_id)


def test_radio_script_of_exactly_three_hundred_characters_is_approved(api):
    """At exactly the limit the inspection finds nothing and approval goes through.

    PRD 3.8 makes the comparison strict: "When the `medium` is `RADIO` and the
    `content_text` runs longer than three hundred characters, the finding
    `RADIO_SCRIPT_TOO_LONG` is produced." A script of exactly three hundred
    characters does not run longer than three hundred, so `disclosure_findings`
    is empty, and PRD 3.8 then permits the approval: "**Approval** advances the
    advertisement `SUBMITTED → APPROVED` and requires that `disclosure_findings`
    is empty after that recomputation; a non-empty list is rejected with
    `ERR_AD_DISCLOSURE_INCOMPLETE` (HTTP 422)."

    Design: Corner/calculations/radio_script_at_three_hundred_chars_passes_and_at_301_is_flagged
    """
    assert len(RADIO_SCRIPT_300) == 300

    submitted = _radio_advertisement(api, RADIO_SCRIPT_300)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["disclosure_findings"] == []

    response = api.create_advertisement_review(
        submitted["id"], build_advertisement_review("APPROVE"), officer_headers()
    )
    reviewed = validate_success(response)
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by_user_id"] == OFFICER_USER_ID


def test_radio_script_of_three_hundred_one_characters_blocks_approval(api):
    """One character past the limit produces the single length finding and blocks approval.

    PRD 3.8: "When the `medium` is `RADIO` and the `content_text` runs longer
    than three hundred characters, the finding `RADIO_SCRIPT_TOO_LONG` is
    produced." Because the copy discloses the originator's `nmls_unique_id` and
    its CA licence number, no other finding can fire, so the list is exactly one
    code long. PRD 3.8 then blocks the approval: "**Approval** advances the
    advertisement `SUBMITTED → APPROVED` and requires that `disclosure_findings`
    is empty after that recomputation; a non-empty list is rejected with
    `ERR_AD_DISCLOSURE_INCOMPLETE` (HTTP 422)." The rejected decision applies no
    transition, so the row is still `SUBMITTED` afterwards.

    Design: Corner/calculations/radio_script_at_three_hundred_chars_passes_and_at_301_is_flagged
    """
    assert len(RADIO_SCRIPT_301) == 301

    submitted = _radio_advertisement(api, RADIO_SCRIPT_301)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["disclosure_findings"] == ["RADIO_SCRIPT_TOO_LONG"]

    response = api.create_advertisement_review(
        submitted["id"], build_advertisement_review("APPROVE"), officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_AD_DISCLOSURE_INCOMPLETE.value)

    unchanged = validate_success(api.get_advertisement(submitted["id"], officer_headers()))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["disclosure_findings"] == ["RADIO_SCRIPT_TOO_LONG"]


def test_payoff_at_exactly_one_hundred_eighty_days_recaptures_half(api):
    """The outer recapture boundary is inclusive, so half the paid commission comes back.

    Funded 2026-08-20 and paid off 2027-02-16 is exactly one hundred and eighty
    whole days, which PRD 3.7 puts in the middle bucket: "A `days_held` of ninety
    days or fewer sets `recapture_pct` to one hundred percent; a `days_held`
    above ninety but no more than one hundred and eighty days sets it to fifty
    percent; anything longer sets `recapture_pct` to zero." The amount follows
    from PRD 3.7: "The amount recaptured, `clawback_cents`, is the line's
    `paid_cents` multiplied by `recapture_pct`, divided by one hundred, rounded
    half up to whole cents."

    The resulting clawback ratio of fifty percent enters the exposure score at
    the weight PRD 3.7 fixes - "the capped clawback ratio at twenty-five
    hundredths" - so the assembled sum is 12.5, one rounding gives 13, and PRD
    3.7's threshold ("`monitoring_status` is set to `ELEVATED` when
    `exposure_score` is sixty or more, and to `STANDARD` otherwise") leaves the
    originator STANDARD.

    Design: Corner/calculations/payoff_at_exactly_one_hundred_eighty_days_recaptures_fifty_percent
    """
    context = _flat_plan_context(api)
    originator_id = context["originator"]["id"]

    loan = _close_one_loan(
        api,
        originator_id,
        20_000_000,
        "2026-08-20T00:00:00Z",
        lender_paid_comp_cents=210_000,
    )
    # round_half_up(20000000 * 105 / 10000) == 210000, inside the fee band [0, 5000000].
    report = run_reconciliation(api, originator_id)
    assert report["total_final_cents"] == 210_000

    set_clock(api, "2027-02-16T00:00:00Z")
    paid_off = payoff_loan(api, loan["id"], "2027-02-16T00:00:00Z")
    assert paid_off["status"] == "PAID_OFF"
    assert paid_off["compensation_status"] == "CLAWED_BACK"

    record = sole_record_for_loan(api, loan["id"])
    assert record["status"] == "CLAWED_BACK"
    assert record["days_held"] == 180
    assert record["recapture_pct"] == 50
    assert record["clawback_cents"] == 105_000
    assert record["paid_cents"] == 210_000

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 210_000
    assert originator["lifetime_clawed_back_cents"] == 105_000
    assert originator["net_compensation_cents"] == 105_000
    assert originator["exposure_score"] == 13
    assert originator["monitoring_status"] == "STANDARD"


def test_reconciliation_skips_a_line_that_is_already_reconciled(api):
    """The second run reads only the still-accrued line and leaves the first one alone.

    PRD 3.7 fixes the input set: "The eligible set is every loan application
    belonging to that originator whose `status` is `CLOSED` or `PAID_OFF`
    **and** whose `compensation_status` is `ACCRUED` at the instant the run
    executes." And it fixes the exclusion: "Loans whose `compensation_status` is
    `NOT_APPLICABLE`, `PENDING`, `RECONCILED` or `CLAWED_BACK` are skipped
    entirely." So the second run reports one line, not two, and PRD 3.7's report
    contract - "a `total_final_cents` equal to the sum of the rewritten lines'
    new `accrued_cents`, a `total_delta_cents` equal to that total less the sum
    of those same lines' pre-run `accrued_cents`" - measures loan B alone.

    Loan B diverges because PRD 3.7 says of the final variant "The amount it
    multiplies is the loan's `funded_amount_cents` - the amount actually funded -
    rather than `locked_amount_cents`."

    Design: Corner/calculations/reconciliation_skips_lines_that_are_not_accrued
    """
    context = _flat_plan_context(api)
    originator_id = context["originator"]["id"]

    loan_a = _close_one_loan(
        api,
        originator_id,
        20_000_000,
        "2026-08-20T00:00:00Z",
        lender_paid_comp_cents=210_000,
    )

    set_clock(api, "2026-08-21T00:00:00Z")
    first_run = run_reconciliation(api, originator_id)
    assert first_run["reconciled_count"] == 1
    assert first_run["total_final_cents"] == 210_000
    assert first_run["total_delta_cents"] == 0

    loan_b = take_loan(api, originator_id, requested_amount_cents=10_000_000, par_rate_bps=650)
    lock_loan(api, loan_b["id"], originator_id, note_rate_bps=650, locked_amount_cents=10_000_000)
    set_clock(api, "2026-08-22T00:00:00Z")
    loan_b = close_loan(
        api,
        loan_b["id"],
        funded_amount_cents=10_100_000,
        funded_at="2026-08-22T00:00:00Z",
        lender_paid_comp_cents=106_050,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    assert loan_b["compensation_status"] == "ACCRUED"

    set_clock(api, "2026-08-23T00:00:00Z")
    second_run = run_reconciliation(api, originator_id)
    assert second_run["reconciled_count"] == 1
    # round_half_up(10100000 * 105 / 10000) == 106050, against a provisional
    # round_half_up(10000000 * 105 / 10000) == 105000, so the delta is 1050.
    assert second_run["total_final_cents"] == 106_050
    assert second_run["total_delta_cents"] == 1_050

    record_b = sole_record_for_loan(api, loan_b["id"])
    assert second_run["compensation_record_ids"] == [record_b["id"]]
    assert record_b["variant"] == "FINAL"
    assert record_b["accrued_cents"] == 106_050
    assert _instant(record_b["reconciled_at"]) == _instant("2026-08-23T00:00:00Z")

    record_a = sole_record_for_loan(api, loan_a["id"])
    assert record_a["status"] == "RECONCILED"
    assert record_a["accrued_cents"] == 210_000
    assert _instant(record_a["reconciled_at"]) == _instant("2026-08-21T00:00:00Z")

    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 316_050


def test_exposure_score_rounds_the_assembled_weighted_sum_once(api):
    """Two closed loans give 35, which only a single final rounding can produce.

    PRD 3.7 pins the weights - "Those four terms are weighted and added: the
    dual-compensation ratio at thirty-five hundredths, the capped average spread
    at twenty-five hundredths, the exception rate at fifteen hundredths, and the
    capped clawback ratio at twenty-five hundredths" - and then pins how the sum
    is rounded: "**One** rounding half up is applied to the fully assembled
    weighted sum; rounding the four terms individually and then adding them is
    forbidden and yields a different score."

    After the second close the terms are a dual ratio of 50, a capped average
    spread of 40 basis points, an exception rate of 50 and a clawback ratio of
    zero, so the assembled sum is 0.35*50 + 0.25*40 + 0.15*50 = 17.5 + 10 + 7.5 =
    35.0 and the score is 35. Rounding each term first would give 18 + 10 + 8 =
    36, so 35 is the observable that separates the two readings.

    Design: Corner/calculations/exposure_score_single_rounding_of_assembled_weighted_sum
    """
    context = _flat_plan_context(api)
    originator_id = context["originator"]["id"]

    first = take_loan(api, originator_id, requested_amount_cents=20_000_000, par_rate_bps=650)
    lock_loan(api, first["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000)
    exception = request_pricing_exception(
        api,
        first["id"],
        originator_id,
        requested_rate_bps=630,
        concession_cents=100_000,
        reason_code="COMPETITIVE_MATCH",
        justification_text=(
            "Competitor quoted 630 bps on an identical file; a 100000-cent "
            "concession retains the borrower."
        ),
    )
    decided = decide_pricing_exception(
        api,
        exception["id"],
        "APPROVE",
        decision_note="Documented competitive match within the 2 percent concession cap.",
    )
    assert decided["status"] == "APPROVED"

    # Dual pay is permitted while monitoring_status is STANDARD (PRD 3.5).
    close_loan(
        api,
        first["id"],
        funded_amount_cents=20_000_000,
        funded_at="2026-08-10T00:00:00Z",
        lender_paid_comp_cents=200_000,
        borrower_paid_comp_cents=10_000,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    # One closed loan: 0.35*100 + 0.25*0 + 0.15*100 + 0.25*0 == 50.
    after_first = get_originator(api, originator_id)
    assert after_first["exposure_score"] == 50
    assert after_first["monitoring_status"] == "STANDARD"

    second = take_loan(api, originator_id, requested_amount_cents=10_000_000, par_rate_bps=650)
    lock_loan(api, second["id"], originator_id, note_rate_bps=730, locked_amount_cents=10_000_000)
    second = close_loan(
        api,
        second["id"],
        funded_amount_cents=10_000_000,
        funded_at="2026-08-11T00:00:00Z",
        lender_paid_comp_cents=105_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    assert second["compensation_status"] == "ACCRUED"

    after_second = get_originator(api, originator_id)
    assert after_second["exposure_score"] == 35
    assert after_second["monitoring_status"] == "STANDARD"
    assert after_second["lifetime_accrued_cents"] == 315_000
    assert after_second["net_compensation_cents"] == 315_000


def test_closed_unit_index_follows_close_order_not_funded_at_order(api):
    """The file closed first takes index one even though it funded later.

    PRD 3.5 derives the ordinal from the closed set as it stands at the moment of
    the close: the loan "also receives its `closed_unit_index`: the one-based
    chronological ordinal of this loan among the originator's closed loans,
    computed as one plus the count of that originator's loans already sitting in
    `status` `CLOSED` or `PAID_OFF`, with the ordering taken by `funded_at`
    ascending and then `created_at` ascending." Loan X is reported closed first
    with a `funded_at` of 2026-08-25 and takes index one; loan Y is reported
    closed second with an earlier `funded_at` of 2026-08-10 and takes index two,
    because at that instant exactly one loan was already closed. Re-sorting the
    closed set by `funded_at` to assign the ordinal would invert the two.

    Design: Corner/calculations/closed_unit_index_follows_close_order_not_funded_at_order
    """
    context = _flat_plan_context(api)
    originator_id = context["originator"]["id"]

    loan_x = take_loan(api, originator_id, requested_amount_cents=5_000_000, par_rate_bps=650)
    lock_loan(api, loan_x["id"], originator_id, note_rate_bps=650, locked_amount_cents=5_000_000)
    loan_y = take_loan(api, originator_id, requested_amount_cents=5_000_000, par_rate_bps=650)
    lock_loan(api, loan_y["id"], originator_id, note_rate_bps=650, locked_amount_cents=5_000_000)

    set_clock(api, "2026-08-26T00:00:00Z")
    closed_x = close_loan(
        api,
        loan_x["id"],
        funded_amount_cents=5_000_000,
        funded_at="2026-08-25T00:00:00Z",
        lender_paid_comp_cents=52_500,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    closed_y = close_loan(
        api,
        loan_y["id"],
        funded_amount_cents=5_000_000,
        funded_at="2026-08-10T00:00:00Z",
        lender_paid_comp_cents=52_500,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )

    assert closed_x["closed_unit_index"] == 1
    assert closed_x["compensation_status"] == "ACCRUED"
    assert closed_y["closed_unit_index"] == 2

    _, meta = validate_paginated(
        api.list_compensation_records(officer_headers(), params={"originator_id": originator_id})
    )
    assert meta["total_count"] == 2

    # round_half_up(5000000 * 105 / 10000) == 52500 on each of the two lines.
    originator = get_originator(api, originator_id)
    assert originator["lifetime_accrued_cents"] == 105_000
