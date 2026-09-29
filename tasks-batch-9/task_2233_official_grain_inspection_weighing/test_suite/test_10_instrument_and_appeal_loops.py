"""Non-linear loops: instrument drift and recovery, and the appeal round trip."""

from test_helpers import (
    assert_ledger,
    assert_performance_score,
    create_inspector_row,
    dismiss,
    file_appeal,
    file_check,
    read_applicant,
    read_certificate,
    read_equipment,
    read_inspector,
    setup_filed_appeal,
    setup_office,
)


APPEAL_LOOP_SCHEDULES = (
    {
        "service_class": "GRADING",
        "base_fee_cents": 8000,
        "per_thousand_bushel_rate_cents": 2000,
        "minimum_fee_cents": 10000,
    },
    {"service_class": "APPEAL", "base_fee_cents": 20000},
)


def test_a_rolling_bias_of_exactly_030_is_drift_and_not_out_of_tolerance():
    """The check resolves to `OUT_OF_TOLERANCE` when the absolute deviation of
    this single check exceeds 0.50 percentage points **or** the absolute
    `rolling_bias_pct` exceeds 0.30.

    Boundaries are exclusive on the failing side: a rolling bias of exactly 0.30
    is drift, not out of tolerance, and a rolling bias of exactly 0.15 is a clean
    `APPROVED`.

    A `DRIFT_WATCH` resolution moves `APPROVED → DRIFT_WATCH`, resets
    `consecutive_out_of_tolerance_checks` to 0, and leaves the instrument fully
    usable for new analyses.

    Design: Difficulty/non_linear_state_machine/instrument_drift_watch_then_recovery_to_approved
    """
    office = setup_office("DESIGNATED")
    checked = create_inspector_row(office["area"]["id"], "L-2001")

    file_check(office["instrument"]["id"], checked["id"], 35.00, 35.30)
    after_first = read_equipment(office["instrument"]["id"])
    assert after_first["last_comparison_deviation_pct"] == 0.30
    assert after_first["rolling_bias_pct"] == 0.30
    assert after_first["approval_status"] == "DRIFT_WATCH"
    assert after_first["consecutive_out_of_tolerance_checks"] == 0

    file_check(office["instrument"]["id"], checked["id"], 35.00, 35.10)
    after_second = read_equipment(office["instrument"]["id"])
    assert after_second["last_comparison_deviation_pct"] == 0.10
    assert after_second["rolling_bias_pct"] == 0.20
    assert after_second["approval_status"] == "DRIFT_WATCH"


def test_a_rolling_bias_of_exactly_015_recovers_the_instrument_to_approved():
    """Otherwise, when the absolute `rolling_bias_pct` exceeds 0.15, it resolves
    to `DRIFT_WATCH`. Otherwise it resolves to `APPROVED`.

    An `APPROVED` resolution keeps an `APPROVED` instrument approved and recovers
    a `DRIFT_WATCH` instrument to `APPROVED` provided its `certified_until` is
    still in the future, resetting `consecutive_out_of_tolerance_checks` to 0.

    The instrument's `recent_deviations_pct` keeps at most the three most recent
    deviations including this one, oldest first in ascending creation order, and
    `rolling_bias_pct` is the arithmetic mean of those retained deviations,
    rounded half up to 2 decimals.

    A proficiency deviation counts against the inspector when the absolute value
    of a comparison check's deviation exceeds 0.25 percentage points, a
    deliberately tighter bar than the one that troubles the instrument itself.

    Design: Difficulty/non_linear_state_machine/instrument_drift_watch_then_recovery_to_approved
    """
    office = setup_office("DESIGNATED")
    checked = create_inspector_row(office["area"]["id"], "L-2001")

    file_check(office["instrument"]["id"], checked["id"], 35.00, 35.30)
    file_check(office["instrument"]["id"], checked["id"], 35.00, 35.10)
    file_check(office["instrument"]["id"], checked["id"], 35.00, 35.05)

    instrument = read_equipment(office["instrument"]["id"])
    assert instrument["recent_deviations_pct"] == [0.30, 0.10, 0.05]
    assert instrument["rolling_bias_pct"] == 0.15
    assert instrument["approval_status"] == "APPROVED"
    assert instrument["comparison_check_count"] == 3
    assert instrument["consecutive_out_of_tolerance_checks"] == 0

    inspector = read_inspector(checked["id"])
    assert inspector["check_sample_deviation_count"] == 1
    assert inspector["performance_score"] == 90
    assert_performance_score(inspector)


def test_dismissal_returns_the_certificate_to_issued_without_extending_deadlines():
    """In both cases `refund_cents` is half of `deposit_cents` truncated
    downward, credited to the applicant, and the challenged certificate returns
    to `ISSUED`; where the appeal had already reached `SAMPLE_ASSIGNED`, the
    retained portion is additionally released with `portions_retained`
    decreasing by one.

    Returning to `ISSUED` does not extend anything: the original
    `reinspection_deadline_at` and `appeal_deadline_at` stand exactly as they
    were.

    Two rights deadlines are computed and stored: `reinspection_deadline_at` is
    exactly 5 days after `issued_at` and `appeal_deadline_at` exactly 10 days
    after `issued_at`.

    Design: Difficulty/non_linear_state_machine/certificate_appeal_loop_reenters_issued_without_deadline_extension
    """
    office = setup_office("DELEGATED", fee_schedules=APPEAL_LOOP_SCHEDULES)
    staged = setup_filed_appeal(office, appeal_type="REINSPECTION")
    issued = staged["certificate"]
    assert issued["fee_total_cents"] == 10000
    assert issued["appeal_deadline_at"] == "2026-08-13T09:00:00.000Z"
    assert issued["reinspection_deadline_at"] == "2026-08-08T09:00:00.000Z"

    dismissed = dismiss(staged["appeal"]["id"])

    assert dismissed["status"] == "DISMISSED"
    assert dismissed["deposit_cents"] == 20000
    assert dismissed["refund_cents"] == 10000

    certificate = read_certificate(issued["id"])
    assert certificate["status"] == "ISSUED"
    assert certificate["appeal_deadline_at"] == issued["appeal_deadline_at"]
    assert certificate["reinspection_deadline_at"] == issued["reinspection_deadline_at"]


def test_a_dismissed_certificate_may_be_appealed_again_and_the_ledger_accumulates():
    """On success the appeal is created `FILED` with `deposit_cents` set,
    `refund_cents` 0, all four vote counters (`votes_cast_count`,
    `revise_votes_count`, `uphold_votes_count`, `abstain_votes_count`) and
    `effective_votes_count` at 0, a null `assigned_sample_id`, a null
    `outcome_grade` and a null `decided_at`; the deposit is added to the
    applicant's `charges_total_cents` with `open_balance_cents` recomputed; the
    certificate moves `ISSUED → UNDER_APPEAL`; and the inspection request's
    grading dimension moves `GRADE_CERTIFIED → UNDER_APPEAL`.

    No event ever edits an earlier event, which means the balance may
    legitimately go negative when a certificate that was already paid is later
    reversed.

    Design: Difficulty/non_linear_state_machine/certificate_appeal_loop_reenters_issued_without_deadline_extension
    """
    office = setup_office("DELEGATED", fee_schedules=APPEAL_LOOP_SCHEDULES)
    staged = setup_filed_appeal(office, appeal_type="REINSPECTION")
    dismiss(staged["appeal"]["id"])
    refreshed = read_certificate(staged["certificate"]["id"])

    second = file_appeal(
        refreshed["id"], office["applicant"]["id"], refreshed["version"], "APPEAL"
    )

    assert second["status"] == "FILED"
    assert second["deposit_cents"] == 20000
    assert second["refund_cents"] == 0
    assert second["round_number"] == 2
    assert second["required_panel_size"] == 3
    assert second["assigned_sample_id"] is None
    assert second["outcome_grade"] is None
    assert second["decided_at"] is None

    assert read_certificate(refreshed["id"])["status"] == "UNDER_APPEAL"
    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=50000,
        credits=10000,
        open_balance=40000,
    )
