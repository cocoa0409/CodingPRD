"""Version guards on the two ledger-bearing parents, and immediate consistency.

The window guard and the entity guard are each walked through conflict and
recovery, the cumulative point total is landed exactly on its first tier floor,
and the two places the program promises no intermediate state -- a suspension that
must void a firm's live filings before it answers, and ledgers that are current in
the very response that moved them -- are read with no retry and no delay.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_lateness,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_price_statistics,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    DelinquencyTier,
    RegistrationStatus,
    SubmissionStatus,
    SuspendedReason,
    ViolationType,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}
THREE_DAYS_PAST_DEADLINE = "2026-08-14T15:00:00Z"


def test_01_two_reporters_holding_one_window_snapshot_cannot_both_file(api):
    """The same window version replayed is a lost update, not a second filing.

    One snapshot of the window is taken before any filing. The first filing writes
    and moves the window on; the second, presenting that same now-superseded
    snapshot, is refused and writes nothing; re-reading the parent lets the identical
    call through, and the window has moved exactly once per successful write.

    PRD §2.6: "A filing decision depends on the window's collected state —
    `accepted_submission_count`, `total_head_reported`, and whether the new filing
    has to supersede an already-accepted one — so if the window's `version` has
    advanced past the supplied value, the creation is rejected with
    `ERR_STALE_WINDOW_VERSION` (HTTP 412) rather than being filed against an
    out-of-date view."

    Design: Corner/cross_cutting_complexity_layers/stale_window_version_on_filing_create_conflicts_then_succeeds
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
            },
        ],
        legal_name="Alpha Packing",
    )
    reporter = u.reporter_agent(firm["entity"]["id"])
    window = fx.create_standard_window(api)
    snapshot = fx.window_version(api, window["id"])

    first = get_success_data(
        api.create_submission(
            f.submission_payload(firm["plants"][0]["id"], window["id"], snapshot),
            reporter,
        ),
        expected_status=201,
    )
    assert first["status"] == SubmissionStatus.DRAFT.value, first
    assert fx.window_version(api, window["id"]) == snapshot + 1

    validate_error(
        api.create_submission(
            f.submission_payload(firm["plants"][1]["id"], window["id"], snapshot),
            reporter,
        ),
        ApiErrorId.ERR_STALE_WINDOW_VERSION.value,
        412,
    )
    _refused_rows, refused_meta = validate_paginated(
        api.list_submissions(u.PROGRAM_ADMIN)
    )
    assert refused_meta["total_count"] == 1, refused_meta
    fresh = fx.window_version(api, window["id"])
    assert fresh == snapshot + 1

    second = get_success_data(
        api.create_submission(
            f.submission_payload(firm["plants"][1]["id"], window["id"], fresh),
            reporter,
        ),
        expected_status=201,
    )
    assert second["status"] == SubmissionStatus.DRAFT.value, second
    assert second["plant_id"] == firm["plants"][1]["id"], second
    assert fx.window_version(api, window["id"]) == snapshot + 2

    _rows, meta = validate_paginated(
        api.list_submissions(
            u.PROGRAM_ADMIN, params={"reporting_window_id": window["id"]}
        )
    )
    assert meta["total_count"] == 2, meta


def test_02_a_replayed_entity_version_would_have_been_a_double_assessment(api):
    """The refusal is not a delay: the retry is deliberately a different figure.

    The first assessment moves the firm's version, so the second officer's replay of
    the pre-assessment snapshot is refused with nothing written. After refreshing,
    the identical request is accepted at one and a half times the first amount,
    because recidivism has moved on -- which is exactly what the version guard
    stopped from happening twice at the first price.

    PRD §2.6: "The assessed amount and the point escalation are both functions of
    the firm's `delinquency_points` and ledger balances as of assessment time, and
    another assessment stacking under the recidivism rule will have moved them; if
    the entity's `version` no longer equals the supplied value, the assessment is
    rejected with `ERR_STALE_ENTITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_entity_version_on_penalty_create_conflicts_then_succeeds
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing", activate=False)
    entity_id = firm["entity"]["id"]
    snapshot = fx.entity_version(api, entity_id)

    first = get_success_data(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id, ViolationType.NON_REGISTRATION.value, snapshot
            ),
            u.PENALTY_OFFICER,
        ),
        expected_status=201,
    )
    assert_penalty_breakdown(
        first,
        repeat_index=0,
        volume_factor=1.000,
        suspension_surcharge=1.00,
        assessed_amount_cents=1000000,
        points=8,
    )

    validate_error(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id, ViolationType.NON_REGISTRATION.value, snapshot
            ),
            u.PENALTY_OFFICER_2,
        ),
        ApiErrorId.ERR_STALE_ENTITY_VERSION.value,
        412,
    )
    _refused_rows, refused_meta = validate_paginated(
        api.list_penalty_assessments(u.PENALTY_OFFICER)
    )
    assert refused_meta["total_count"] == 1, refused_meta
    assert fx.read_entity(api, entity_id)["delinquency_points"] == 8

    fresh = fx.entity_version(api, entity_id)
    assert fresh == snapshot + 1

    second = get_success_data(
        api.create_penalty_assessment(
            f.penalty_assessment_payload(
                entity_id, ViolationType.NON_REGISTRATION.value, fresh
            ),
            u.PENALTY_OFFICER_2,
        ),
        expected_status=201,
    )
    assert_penalty_breakdown(
        second,
        repeat_index=1,
        repeat_multiplier=1.50,
        assessed_amount_cents=1500000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )

    settled = fx.read_entity(api, entity_id)
    assert_penalty_ledger(
        settled,
        assessed_penalty_cents=2500000,
        outstanding_penalty_cents=2500000,
        delinquency_points=16,
    )
    assert settled["version"] == snapshot + 2, settled
    assert (
        fx.read_registration(api, firm["registration"]["id"])["status"]
        == RegistrationStatus.DETERMINED.value
    )


def test_03_ten_points_is_the_first_tier_floor_and_nothing_cascades_there(api):
    """Eight points plus two land exactly on the floor with no consequence.

    A registration failure and a late filing three days past the deadline together
    total exactly ten points -- the inclusive floor of the first tier -- and each
    assessment reads the tier as it stood before its own points, so both record the
    bottom tier while the firm ends on the first. Nothing follows: only the top tier
    carries an enforcement cascade, so the registration is untouched and neither
    row's points were doubled.

    PRD §3.8: "The platform first reads the firm's `delinquency_points` as they
    stand *before* this row, and classifies them into
    `delinquency_tier_at_assessment`: `TIER_0` for a total of 9 points or fewer,
    `TIER_1` for 10 through 19 points, and `TIER_2` for 20 points or more — the tier
    floors are inclusive, so exactly 10 points is `TIER_1` and exactly 20 points is
    `TIER_2`."

    Design: Corner/cross_cutting_complexity_layers/cumulative_delinquency_points_land_exactly_on_the_tier_1_floor
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(api, entity_id, firm["plant"]["id"], window["id"])
    fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )
    fx.set_clock(api, THREE_DAYS_PAST_DEADLINE)
    late = validate_success(
        api.submit_submission(filing["id"], u.reporter_agent(entity_id))
    )
    assert_lateness(late, 4320, True, 3)

    non_registration = fx.assess_penalty(
        api, entity_id, ViolationType.NON_REGISTRATION.value
    )
    assert_penalty_breakdown(
        non_registration,
        base_amount_cents=1000000,
        day_tier_multiplier=1.00,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        assessed_amount_cents=1126000,
        points=8,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )

    late_filing = fx.assess_penalty(
        api,
        entity_id,
        ViolationType.LATE_FILING.value,
        submission_id=filing["id"],
    )
    assert_penalty_breakdown(
        late_filing,
        base_amount_cents=250000,
        days_late=3,
        day_tier_multiplier=1.50,
        repeat_index=0,
        repeat_multiplier=1.00,
        volume_factor=1.126,
        assessed_amount_cents=422250,
        points=2,
        delinquency_tier_at_assessment=DelinquencyTier.TIER_0.value,
    )

    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=1548250,
        outstanding_penalty_cents=1548250,
        delinquency_points=k.TIER_1_FLOOR_POINTS,
    )
    resting = fx.read_registration(api, firm["registration"]["id"])
    assert resting["status"] == RegistrationStatus.ACTIVE.value, resting
    assert resting["suspended_reason"] is None, resting


def test_04_one_suspension_call_answers_with_its_whole_cascade_already_done(api):
    """The voiding is finished before the suspend response is written.

    The suspend response itself reports the suspended status and its reason, and the
    immediately following reads -- no retry, no delay -- already show both of the
    firm's live filings voided. A peer firm's accepted filing and the window's ledger
    are outside the cascade, because a draft or filed submission was never counted in
    one.

    PRD §3.2: "Suspension immediately voids the firm's in-flight work: every
    submission belonging to any of the firm's plants whose status is `DRAFT` or
    `SUBMITTED` transitions to `VOIDED`."

    Design: Corner/consistency_model/suspension_cascade_is_visible_in_the_same_response
    """
    alpha = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
            },
        ],
        legal_name="Alpha Packing",
    )
    bravo = fx.obligated_firm(
        api, legal_name="Bravo Beef", plant_code="EST-202"
    )
    window = fx.create_standard_window(api)

    draft = fx.draft_filing(
        api, alpha["entity"]["id"], alpha["plants"][0]["id"], window["id"]
    )
    submitted = fx.submitted_filing(
        api,
        alpha["entity"]["id"],
        alpha["plants"][1]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=60,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    peer = fx.accepted_filing(
        api,
        bravo["entity"]["id"],
        bravo["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    version_before = fx.window_version(api, window["id"])

    suspended = validate_success(
        api.suspend_registration(
            alpha["registration"]["id"],
            f.suspend_payload(suspended_reason=SuspendedReason.ADMIN_ACTION.value),
            u.PROGRAM_ADMIN,
        )
    )
    assert suspended["status"] == RegistrationStatus.SUSPENDED.value, suspended
    assert (
        suspended["suspended_reason"] == SuspendedReason.ADMIN_ACTION.value
    ), suspended

    assert (
        fx.read_submission(api, draft["id"])["status"]
        == SubmissionStatus.VOIDED.value
    )
    assert (
        fx.read_submission(api, submitted["id"])["status"]
        == SubmissionStatus.VOIDED.value
    )
    assert (
        fx.read_submission(api, peer["id"])["status"]
        == SubmissionStatus.ACCEPTED.value
    )

    resting_window = fx.read_window(api, window["id"])
    assert_window_ledger(
        resting_window, total_head_reported=100, accepted_submission_count=1
    )
    assert resting_window["version"] == version_before, resting_window
    assert (
        fx.read_registration(api, bravo["registration"]["id"])["status"]
        == RegistrationStatus.ACTIVE.value
    )


def test_05_the_ledger_and_the_aggregate_are_current_in_the_call_that_moved_them(api):
    """Acceptance, aggregation and reopening, each read at its own response.

    Acceptance answers with the filing accepted and the window's ledger already
    carrying its head; the aggregation answers with the figures themselves rather
    than a projection to be filled in later; and reopening answers with the filing
    reopened, the ledger already back to nothing and the report already stale --
    keeping the figures it last computed, which is what makes the staleness
    observable at all.

    PRD §2.10: "Whenever any submission of a window enters or leaves `ACCEPTED`
    status, the window's collected ledger is recomputed, and every `MarketReport` of
    that window whose `aggregation_state` is `COMPUTED` is forced to `STALE`."

    Design: Corner/consistency_model/derived_counters_are_current_in_the_mutating_response
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_relaxed_window(api)
    filing = fx.submitted_filing(
        api,
        entity_id,
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    report = fx.create_report(api, window["id"])
    assert report["aggregation_state"] == AggregationState.PENDING.value, report

    accepted = validate_success(
        api.review_submission(
            filing["id"], f.review_payload(review_note="clean"), u.MARKET_ANALYST
        )
    )
    assert accepted["status"] == SubmissionStatus.ACCEPTED.value, accepted
    assert_clock_stamp(accepted["accepted_at"], k.CLOCK_BASE_UTC, "accepted_at")
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=100,
        accepted_submission_count=1,
    )

    computed = validate_success(
        api.compute_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert_price_statistics(computed, 280.00, 280.00, 280.00)
    assert computed["total_head"] == 100, computed
    assert computed["reporter_count"] == 1, computed
    assert computed["max_reporter_share_pct"] == 100.00, computed
    assert computed["source_submission_count"] == 1, computed
    assert_clock_stamp(computed["computed_at"], k.CLOCK_BASE_UTC, "computed_at")

    reopened = validate_success(
        api.open_correction(
            filing["id"],
            f.correction_payload(
                correction_reason="plant reported the wrong lot"
            ),
            u.COMPLIANCE_AUDITOR,
        )
    )
    assert (
        reopened["status"] == SubmissionStatus.UNDER_CORRECTION.value
    ), reopened
    assert reopened["resubmission_count"] == 0, reopened

    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )

    stale = fx.read_report(api, report["id"])
    assert stale["aggregation_state"] == AggregationState.STALE.value, stale
    assert_price_statistics(stale, 280.00, 280.00, 280.00)
    assert stale["total_head"] == 100, stale
