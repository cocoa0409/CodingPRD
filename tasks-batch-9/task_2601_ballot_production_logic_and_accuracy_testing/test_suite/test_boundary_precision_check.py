"""Thresholds proved one unit either side of their edge.

Three of the service's numeric guards are inclusive comparisons over integers
that were themselves floored or rounded on the way in, so the only way to pin
them is to sit exactly on the edge and then step one unit across it:

* the statutory public-notice lead, required in whole minutes rather than in
  whole hours, where a lead exactly equal to the requirement still opens the
  logic-and-accuracy session;
* the ballot-accountability tolerance, where both the spoilage allowance and the
  tolerance itself round down, and one ballot decides the verdict;
* the print-quality hold threshold, where a cumulative rate of exactly 150 basis
  points holds the job and 149 releases it.

Every figure asserted below - notice-lead minutes, worksheet lines, defect basis
points - is the exact integer the contract fixes for these inputs.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.api_errors import ERR_PUBLIC_NOTICE_TOO_LATE
from test_helpers.constants import (
    ACCOUNTABILITY_BALANCED,
    ACCOUNTABILITY_OUT_OF_BALANCE,
    ACCOUNTABILITY_PENDING,
    ASSET_TAG_1,
    ASSET_TAG_2,
    ASSET_TAG_3,
    BASIS_FINAL_CANVASS,
    CLOCK_START,
    DECK_DRAFT,
    DECK_SEALED,
    INVOICE_ESTIMATE,
    JOB_QC_HOLD,
    JOB_QC_PASSED,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_CODE_3,
    PHASE_POLLS_CLOSED,
    PHASE_RECONCILED,
    POLL_CLOSE_INSTANT,
    SEAL_1,
    SEAL_2,
    SEAL_3,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SESSION_START,
    UNIT_PROGRAMMED,
    USER_TECH_2,
)

# The three notice instants differ by one minute, which is the whole point: the
# leads they produce to a 2026-09-01T14:00:00Z start are 2881, 2880 and 2879.
_NOTICE_ONE_MINUTE_EARLY = "2026-08-30T13:59:00Z"
_NOTICE_EXACTLY_ON_TIME = "2026-08-30T14:00:00Z"
_NOTICE_ONE_MINUTE_LATE = "2026-08-30T14:01:00Z"

_PRESS_WINDOW_START_2 = "2026-08-11T08:00:00Z"
_PRESS_WINDOW_END_2 = "2026-08-13T08:00:00Z"


# ─── Private world builders ──────────────────────────────────────────────────

def _three_session_world(client: BallotProductionApiClient):
    """Three units, three decks and three sessions differing only in their notice.

    Each session sits on its own tabulator, so the window-exclusivity rule never
    fires, and every session is scheduled for the same four-hour slot with two
    observers signed in. The clock is left at the scheduled start, inside the
    admission window of all three.
    """
    sc = fx.styles_locked(client, CLOCK_START, registered_voter_count=100)
    first_unit = fx.add_tabulator(sc, asset_tag=ASSET_TAG_1)
    second_unit = fx.add_tabulator(sc, asset_tag=ASSET_TAG_2)
    third_unit = fx.add_tabulator(sc, asset_tag=ASSET_TAG_3)
    for unit in (first_unit, second_unit, third_unit):
        fx.program_unit(sc, tabulator_id=unit)
    deck_a = fx.add_test_deck(sc, deck_code="DECK-A")
    deck_b = fx.add_test_deck(sc, deck_code="DECK-B")
    deck_c = fx.add_test_deck(sc, deck_code="DECK-C")
    session_a = fx.schedule_session(sc, tabulator_id=first_unit, deck_id=deck_a,
                                    scheduled_start=SESSION_START,
                                    public_notice_posted_at=_NOTICE_ONE_MINUTE_EARLY)
    session_b = fx.schedule_session(sc, tabulator_id=second_unit, deck_id=deck_b,
                                    scheduled_start=SESSION_START,
                                    public_notice_posted_at=_NOTICE_EXACTLY_ON_TIME)
    session_c = fx.schedule_session(sc, tabulator_id=third_unit, deck_id=deck_c,
                                    scheduled_start=SESSION_START,
                                    public_notice_posted_at=_NOTICE_ONE_MINUTE_LATE)
    for session in (session_a, session_b, session_c):
        fx.sign_in_observers(sc, session_id=session)
    fx.set_clock(client, SESSION_START)
    return sc, (session_a, session_b, session_c), (first_unit, second_unit, third_unit)


def _deck_row(sc, deck_code: str):
    """Read one test deck of the scenario style back off its list endpoint."""
    rows, _meta = validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.TECHNICIAN, {"limit": 100}))
    return asserts.find_by(rows, "deck_code", deck_code)


def _five_thousand_ballot_world(client: BallotProductionApiClient):
    """A poll-closed election whose 5000 ballots went out as three issued lots.

    The first two lots have reported their board counts (1950 and 1961
    accounted); the third is still in the field with its full 1000 ballots
    issued and nothing accounted.
    """
    sc = fx.styles_locked(client, CLOCK_START, registered_voter_count=100)
    fx.add_vendor(sc)
    fx.add_print_job(sc, quantity_ordered=5000)
    fx.printed_job(sc)
    fx.inspect_job(sc, sample_size=500, defect_count=6)
    fx.deliver_job(sc, lots=[
        f.manifest_line(LOT_CODE_1, 2000, SEAL_1),
        f.manifest_line(LOT_CODE_2, 2000, SEAL_2),
        f.manifest_line(LOT_CODE_3, 1000, SEAL_3),
    ])
    lot_one, lot_two, lot_three = sc.lot_ids
    fx.receive_lot(sc, lot_one, SEAL_1, 2000)
    fx.issue_lot(sc, lot_one, issue_quantity=2000)
    fx.receive_lot(sc, lot_two, SEAL_2, 2000)
    fx.issue_lot(sc, lot_two, issue_quantity=2000)
    fx.receive_lot(sc, lot_three, SEAL_3, 1000)
    fx.issue_lot(sc, lot_three, issue_quantity=1000)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc)
    fx.schedule_session(sc)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc)
    fx.record_matching_results(sc)
    fx.deploy_unit(sc)
    get_success_data(sc.client.deploy_election(sc.election_id, users.DIRECTOR))
    fx.set_clock(client, POLL_CLOSE_INSTANT)
    get_success_data(sc.client.close_polls(sc.election_id, users.DIRECTOR))
    fx.return_lot_counts(sc, lot_one, 1900, 30, 20)
    fx.return_lot_counts(sc, lot_two, 1880, 25, 56)
    return sc, (lot_one, lot_two, lot_three)


def _worksheet(sc, basis: str):
    """Read the accountability worksheet under an explicit basis."""
    return validate_success(
        sc.client.get_accountability(sc.election_id, users.DIRECTOR,
                                     f.accountability_params(basis)), 200)


def _two_job_printing_world(client: BallotProductionApiClient):
    """Two proof-approved jobs on the same two-line vendor, both on press.

    Their press windows overlap by one day, which a two-line vendor accepts, so
    both jobs are inspectable at the same time and the vendor's rolling quality
    rate has two jobs to pool.
    """
    sc = fx.styles_locked(client, CLOCK_START, registered_voter_count=100)
    fx.add_vendor(sc)
    first_job = fx.add_print_job(sc, quantity_ordered=12500)
    fx.printed_job(sc, job_id=first_job)
    second_job = fx.add_print_job(sc, quantity_ordered=12500,
                                  press_window_start=_PRESS_WINDOW_START_2,
                                  press_window_end=_PRESS_WINDOW_END_2)
    fx.printed_job(sc, job_id=second_job)
    return sc, (first_job, second_job)


# ─── The public-notice lead, measured in whole minutes ────────────────────────

def test_bp_notice_lead_is_frozen_at_creation_as_whole_minutes(client):
    """One minute of difference in the posting instant is one minute of lead, not one hour.

    PRD Section 3.8: "`notice_lead_minutes` is derived once, at creation, as the whole minutes from `public_notice_posted_at` to `scheduled_start`, rounded down; a notice posted *after* the scheduled start yields a negative lead, which is retained as computed rather than clamped."

    Design: Difficulty/boundary_precision_check/bp_public_notice_lead_exactly_48_hours
    """
    sc, (session_a, session_b, session_c), _units = _three_session_world(client)

    first = sc.read_session(session_a)
    second = sc.read_session(session_b)
    third = sc.read_session(session_c)

    assert first["notice_lead_minutes"] == 2881, (
        "a notice posted at 2026-08-30T13:59:00Z leads a 2026-09-01T14:00:00Z start by 2881 minutes")
    assert second["notice_lead_minutes"] == 2880
    assert third["notice_lead_minutes"] == 2879
    asserts.assert_fields_equal(
        second,
        {"status": SESSION_SCHEDULED, "observer_count": 2, "started_at": None,
         "conducted_by_user_id": None},
        "session scheduled on the exact notice")


def test_bp_notice_lead_one_minute_over_the_requirement_opens_the_session(client):
    """A lead of 2881 minutes against a 2880-minute requirement starts the test.

    PRD Section 3.8: "On success the session moves `SCHEDULED → IN_PROGRESS`, `started_at` is stamped from the logical clock, `conducted_by_user_id` records the starting `X-User-ID`, and the referenced deck transitions `DRAFT → SEALED`, becoming immutable for the duration of the session."

    Design: Difficulty/boundary_precision_check/bp_public_notice_lead_exactly_48_hours
    """
    sc, (session_a, _session_b, _session_c), _units = _three_session_world(client)

    started = validate_success(
        sc.client.start_session(session_a, users.TECHNICIAN_2), 200)

    asserts.assert_fields_equal(
        started,
        {"status": SESSION_IN_PROGRESS,
         "conducted_by_user_id": USER_TECH_2, "notice_lead_minutes": 2881},
        "session started on a 2881-minute lead")
    asserts.assert_same_instant(started["started_at"], SESSION_START,
                               "session started on a 2881-minute lead.started_at")
    assert _deck_row(sc, "DECK-A")["status"] == DECK_SEALED


def test_bp_notice_lead_exactly_at_the_requirement_opens_the_session(client):
    """A lead of exactly 2880 minutes is sufficient, because the comparison is inclusive.

    PRD Section 3.8: "`notice_lead_minutes` must be at least the election's `la_notice_hours` multiplied by 60, or `ERR_PUBLIC_NOTICE_TOO_LATE` (rank 100). The comparison is inclusive: notice posted exactly the required number of hours ahead is sufficient."

    Design: Difficulty/boundary_precision_check/bp_public_notice_lead_exactly_48_hours
    """
    sc, (_session_a, session_b, _session_c), _units = _three_session_world(client)
    assert sc.read_election()["la_notice_hours"] == 48

    started = validate_success(
        sc.client.start_session(session_b, users.TECHNICIAN_2), 200)

    asserts.assert_fields_equal(
        started,
        {"status": SESSION_IN_PROGRESS,
         "conducted_by_user_id": USER_TECH_2, "notice_lead_minutes": 2880},
        "session started on a lead exactly equal to the requirement")
    asserts.assert_same_instant(
        started["started_at"], SESSION_START,
        "session started on a lead exactly equal to the requirement.started_at")
    assert _deck_row(sc, "DECK-B")["status"] == DECK_SEALED


def test_bp_notice_lead_one_minute_short_is_refused_and_changes_nothing(client):
    """A lead of 2879 minutes fails the notice rule and leaves the session scheduled.

    PRD Section 2.6: "| 100 | A temporal rule fails: public-notice lead, session admission window, tabulator test-window exclusivity, vendor press capacity | `ERR_PUBLIC_NOTICE_TOO_LATE`, `ERR_OUTSIDE_TEST_WINDOW`, `ERR_UNIT_TEST_WINDOW_CONFLICT`, `ERR_PRESS_CAPACITY_EXCEEDED` |"

    Design: Difficulty/boundary_precision_check/bp_public_notice_lead_exactly_48_hours
    """
    sc, (_session_a, _session_b, session_c), (_first, _second, third_unit) = (
        _three_session_world(client))

    validate_error(sc.client.start_session(session_c, users.TECHNICIAN_2),
                   ERR_PUBLIC_NOTICE_TOO_LATE)

    asserts.assert_fields_equal(
        sc.read_session(session_c),
        {"status": SESSION_SCHEDULED, "started_at": None,
         "conducted_by_user_id": None, "notice_lead_minutes": 2879},
        "session refused for late notice")
    assert _deck_row(sc, "DECK-C")["status"] == DECK_DRAFT
    asserts.assert_fields_equal(
        sc.read_tabulator(third_unit),
        {"program_status": UNIT_PROGRAMMED, "la_session_count": 0},
        "tabulator whose session never opened")


# ─── The accountability tolerance, one ballot either side ─────────────────────

def test_bp_net_variance_exactly_equal_to_the_tolerance_is_balanced(client):
    """Two returned lots leave a net variance of 79 against a tolerance of 79.

    PRD Section 3.9: "`tolerance_ballots` is `net_issued` multiplied by `tolerance_bp`, divided by 10 000, **rounded down**."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, _lots = _five_thousand_ballot_world(client)

    worksheet = _worksheet(sc, BASIS_FINAL_CANVASS)

    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_FINAL_CANVASS,
            "lot_count": 2,
            "gross_issued": 4000,
            "allowance_bp": 25,
            "spoilage_credit": 10,
            "net_issued": 3990,
            "accounted": 3911,
            "gross_variance": 89,
            "net_variance": 79,
            "tolerance_bp": 200,
            "tolerance_ballots": 79,
            "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
        })


def test_bp_net_variance_one_ballot_over_the_tolerance_is_out_of_balance(client):
    """With all 5000 ballots back the variance is 100 against a tolerance of 99.

    PRD Section 3.9: "Because step 3 keys on gross and step 8 keys on net, and step 4 has removed some ballots in between, an election sitting exactly on the gross tier edge lands in a different tolerance tier than a naive single-pass reading would predict: 5000 gross ballots take the 25-basis-point allowance and the resulting net figure falls strictly below 5000, still inside the first tolerance tier but no longer at its edge."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, (_lot_one, _lot_two, lot_three) = _five_thousand_ballot_world(client)
    fx.return_lot_counts(sc, lot_three, 950, 15, 12)

    worksheet = _worksheet(sc, BASIS_FINAL_CANVASS)

    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_FINAL_CANVASS,
            "lot_count": 3,
            "gross_issued": 5000,
            "allowance_bp": 25,
            "spoilage_credit": 12,
            "net_issued": 4988,
            "accounted": 4888,
            "gross_variance": 112,
            "net_variance": 100,
            "tolerance_bp": 200,
            "tolerance_ballots": 99,
            "ballot_accountability_status": ACCOUNTABILITY_OUT_OF_BALANCE,
        })


def test_bp_one_more_accounted_ballot_pulls_the_election_back_into_balance(client):
    """The same third lot returning one more unused ballot makes the variance 99 and balances it.

    PRD Section 3.9: "`ballot_accountability_status` is `BALANCED` when the absolute value of `net_variance` is less than or equal to `tolerance_ballots`, and `OUT_OF_BALANCE` otherwise. A variance exactly equal to the tolerance is balanced; one ballot more is not."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, (_lot_one, _lot_two, lot_three) = _five_thousand_ballot_world(client)
    fx.return_lot_counts(sc, lot_three, 950, 15, 13)

    worksheet = _worksheet(sc, BASIS_FINAL_CANVASS)

    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_FINAL_CANVASS,
            "lot_count": 3,
            "gross_issued": 5000,
            "allowance_bp": 25,
            "spoilage_credit": 12,
            "net_issued": 4988,
            "accounted": 4889,
            "gross_variance": 111,
            "net_variance": 99,
            "tolerance_bp": 200,
            "tolerance_ballots": 99,
            "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
        })


def test_bp_both_tiered_quantities_are_floored_not_rounded_to_nearest(client):
    """79.8 becomes 79 and 99.76 becomes 99, which is what decides both verdicts.

    PRD Section 3.9: "Both tiered quantities round down, so both the allowance and the tolerance are always the conservative, smaller integer."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, (_lot_one, _lot_two, lot_three) = _five_thousand_ballot_world(client)

    before = _worksheet(sc, BASIS_FINAL_CANVASS)
    fx.return_lot_counts(sc, lot_three, 950, 15, 12)
    after = _worksheet(sc, BASIS_FINAL_CANVASS)

    assert (before["net_issued"], before["tolerance_ballots"]) == (3990, 79), (
        "3990 * 200 / 10000 is 79.8, which floors to 79 rather than rounding to 80")
    assert (after["net_issued"], after["tolerance_ballots"]) == (4988, 99), (
        "4988 * 200 / 10000 is 99.76, which floors to 99 rather than rounding to 100")
    assert (before["gross_issued"], before["spoilage_credit"]) == (4000, 10)
    assert (after["gross_issued"], after["spoilage_credit"]) == (5000, 12), (
        "5000 * 25 / 10000 is 12.5, floored to 12")
    assert before["ballot_accountability_status"] == ACCOUNTABILITY_BALANCED
    assert after["ballot_accountability_status"] == ACCOUNTABILITY_OUT_OF_BALANCE


def test_bp_accountability_reads_mutate_nothing_before_reconciliation(client):
    """Two worksheet reads leave the election's stored accountability figures at rest.

    PRD Section 3.9: "The same worksheet is available as a pure computed read that mutates nothing, open to every role, and returning the whole line of intermediate figures rather than just the verdict: `basis`, `lot_count`, `gross_issued`, `allowance_bp`, `spoilage_credit`, `net_issued`, `accounted`, `gross_variance`, `net_variance`, `tolerance_bp`, `tolerance_ballots` and `ballot_accountability_status`."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, (_lot_one, _lot_two, lot_three) = _five_thousand_ballot_world(client)
    fx.return_lot_counts(sc, lot_three, 950, 15, 12)
    version_before = sc.election_version()

    _worksheet(sc, BASIS_FINAL_CANVASS)
    _worksheet(sc, BASIS_FINAL_CANVASS)

    asserts.assert_fields_equal(
        sc.read_election(),
        {
            "status": PHASE_POLLS_CLOSED,
            "ballot_accountability_status": ACCOUNTABILITY_PENDING,
            "net_ballot_variance": 0,
            "reconciliation_basis": None,
            "last_reconciled_at": None,
            "version": version_before,
        },
        "election after two accountability reads")


def test_bp_reconcile_persists_the_out_of_balance_reading(client):
    """Reconciliation writes the 100-ballot variance and the out-of-balance verdict onto the election.

    PRD Section 3.9: "A reconciliation writes the worksheet's results onto the election: `total_ballots_issued` becomes `gross_issued`, `net_ballot_variance` becomes `net_variance`, `ballot_accountability_status` becomes the derived status, `reconciliation_basis` records the basis used, `last_reconciled_at` is stamped from the logical clock, `status` becomes `RECONCILED`, and `version` is bumped — which is why a client re-reconciling must read the election again to obtain a fresh `expected_election_version`."

    Design: Difficulty/boundary_precision_check/bp_accountability_net_variance_exactly_at_tolerance
    """
    sc, (_lot_one, _lot_two, lot_three) = _five_thousand_ballot_world(client)
    fx.return_lot_counts(sc, lot_three, 950, 15, 12)
    version_before = sc.election_version()

    fx.reconcile(sc, BASIS_FINAL_CANVASS)

    asserts.assert_fields_equal(
        sc.read_election(),
        {
            "status": PHASE_RECONCILED,
            "ballot_accountability_status": ACCOUNTABILITY_OUT_OF_BALANCE,
            "net_ballot_variance": 100,
            "total_ballots_issued": 5000,
            "reconciliation_basis": BASIS_FINAL_CANVASS,
            "version": version_before + 1,
        },
        "reconciled election")
    asserts.assert_same_instant(sc.read_election()["last_reconciled_at"],
                               POLL_CLOSE_INSTANT,
                               "reconciled election.last_reconciled_at")


# ─── The print-quality hold threshold, one basis point either side ────────────

def test_bp_defect_rate_exactly_at_the_hold_threshold_holds_the_job(client):
    """Six defects in a sample of 400 is exactly 150 basis points, and 150 holds.

    PRD Section 3.6: "The derived rate decides the branch, and the threshold comparison is inclusive: a rate of 150 basis points — one and a half percent — or higher moves the job to `QC_HOLD`, and anything strictly below releases it to `QC_PASSED`."

    Design: Difficulty/boundary_precision_check/bp_qc_defect_rate_exactly_at_hold_threshold
    """
    sc, (first_job, _second_job) = _two_job_printing_world(client)

    inspected = validate_success(
        sc.client.inspect_print_job(first_job, f.inspect_payload(400, 6), users.CUSTODIAN), 200)

    asserts.assert_fields_equal(
        inspected,
        {"sample_size": 400, "defect_count": 6, "inspection_count": 1,
         "defect_rate_bp": 150, "status": JOB_QC_HOLD},
        "job inspected at exactly the hold threshold")


def test_bp_second_sample_dilutes_the_cumulative_rate_and_releases_the_job(client):
    """A clean 600-ballot sample folds into the running totals and drops the rate to 60.

    PRD Section 3.6: "Sampling is **cumulative**, never per-call: `inspection_count` increases by one, the payload's sample size is added to the job's running `sample_size`, the payload's defect count is added to the running `defect_count`, and `defect_rate_bp` is re-derived as the running defect count multiplied by 10 000 and divided by the running sample size, rounded half up to whole basis points."

    Design: Difficulty/boundary_precision_check/bp_qc_defect_rate_exactly_at_hold_threshold
    """
    sc, (first_job, _second_job) = _two_job_printing_world(client)
    fx.inspect_job(sc, sample_size=400, defect_count=6, job_id=first_job)

    reinspected = validate_success(
        sc.client.inspect_print_job(first_job, f.inspect_payload(600, 0), users.CUSTODIAN), 200)

    asserts.assert_fields_equal(
        reinspected,
        {"sample_size": 1000, "defect_count": 6, "inspection_count": 2,
         "defect_rate_bp": 60, "status": JOB_QC_PASSED},
        "job released by a diluting second sample")


def test_bp_defect_rate_one_basis_point_below_the_threshold_releases_the_job(client):
    """149 defects in 10000 ballots is exactly 149 basis points, and 149 passes.

    PRD Section 3.6: "A rate landing exactly on 150 holds the job; one basis point lower releases it."

    Design: Difficulty/boundary_precision_check/bp_qc_defect_rate_exactly_at_hold_threshold
    """
    sc, (_first_job, second_job) = _two_job_printing_world(client)

    inspected = validate_success(
        sc.client.inspect_print_job(second_job, f.inspect_payload(10000, 149),
                                    users.CUSTODIAN), 200)

    asserts.assert_fields_equal(
        inspected,
        {"sample_size": 10000, "defect_count": 149, "inspection_count": 1,
         "defect_rate_bp": 149, "status": JOB_QC_PASSED},
        "job inspected one basis point below the hold threshold")


def test_bp_vendor_rolling_rate_pools_every_sample_rather_than_averaging_jobs(client):
    """155 defects across 11000 sampled ballots is 141 basis points, not the 105-point job average.

    PRD Section 3.6: "Each inspection also re-derives the vendor's rolling `quality_defect_rate_bp` across all of that vendor's jobs that have been inspected at least once, as the sum of their defect counts multiplied by 10 000 and divided by the sum of their sample sizes, rounded half up; when no job of the vendor has been inspected the field is 0."

    Design: Difficulty/boundary_precision_check/bp_qc_defect_rate_exactly_at_hold_threshold
    """
    sc, (first_job, second_job) = _two_job_printing_world(client)
    fx.inspect_job(sc, sample_size=400, defect_count=6, job_id=first_job)
    fx.inspect_job(sc, sample_size=600, defect_count=0, job_id=first_job)
    fx.inspect_job(sc, sample_size=10000, defect_count=149, job_id=second_job)

    vendor = validate_success(sc.client.get_print_vendor(sc.vendor_id, users.DIRECTOR), 200)

    assert vendor["quality_defect_rate_bp"] == 141, (
        "the pooled rate is 141 basis points, neither job rate and not their 105-point average")
    assert sc.read_job(first_job)["defect_rate_bp"] == 60
    assert sc.read_job(second_job)["defect_rate_bp"] == 149


def test_bp_inspection_never_rewrites_the_estimate_invoice(client):
    """Two inspections change quality state only; the estimate invoice stays as approved.

    PRD Section 3.6: "`invoice_subtotal_cents` is the ordered quantity multiplied by the contract rate and divided by 1000, rounded half up to a whole cent — one rounding for the whole order."

    Design: Difficulty/boundary_precision_check/bp_qc_defect_rate_exactly_at_hold_threshold
    """
    sc, (first_job, _second_job) = _two_job_printing_world(client)
    fx.inspect_job(sc, sample_size=400, defect_count=6, job_id=first_job)
    fx.inspect_job(sc, sample_size=600, defect_count=0, job_id=first_job)

    job = sc.read_job(first_job)

    asserts.assert_fields_equal(
        job,
        {"invoice_basis": INVOICE_ESTIMATE, "invoice_subtotal_cents": 105625,
         "freight_cents": 45000, "defect_credit_cents": 0,
         "invoice_total_cents": 150625, "delivered_quantity": 0},
        "estimate invoice after two inspections")
    assert sc.lots_of_job(first_job) == [], (
        "inspection creates no ballot lot; only an accepted delivery manifest does")
    assert sc.read_election()["total_ballots_received"] == 0
