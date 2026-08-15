"""Monthly summaries: denominator aggregation, SIR computation variants and
boundaries, the submission cycle, and the covering-summary lock (PRD §2.10,
§3.1, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    accept_summary,
    adjudicate_hai,
    assert_approx_equal,
    assert_monthly_summary,
    create_device_day_count,
    create_device_day_rows,
    create_device_episode,
    create_monthly_summary,
    create_patient,
    correct_device_day_count,
    create_adjudicated_clabsi,
    get_device_day_count,
    get_summary,
    reject_summary,
    reopen_case,
    setup_case_under_review_with_open_summary,
    setup_open_summary_with_day_row,
    setup_or_unit_with_tiered_procedures_and_ssi,
    setup_submitted_summary_with_day_row,
    setup_summary_with_final_and_provisional_case,
    setup_two_units_straddling_sir_floor,
    setup_unit_with_patient,
    submit_summary,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Final vs provisional dual variant
# ---------------------------------------------------------------------------

def test_summary_counts_final_vs_provisional_variants(api, ip_headers):
    """PRD §3.7: "The **final** variant counts cases attributed to the unit
    whose status is `ADJUDICATED_HAI` and whose `date_of_event` calendar date
    falls in the month — producing `clabsi_count`, `cauti_count`, and
    `ssi_count` by case type. The **provisional** variant previews month-to-date
    exposure before adjudication completes: `provisional_clabsi_count`,
    `provisional_cauti_count`, and `provisional_ssi_count` each equal the
    corresponding final count plus cases of that type still in `UNDER_REVIEW`
    whose `first_positive_specimen_at` calendar date falls in the month."
    PRD §3.7: "`predicted_clabsi` is the facility's `clabsi_baseline_per_1000`
    multiplied by the month's `central_line_days` and divided by one thousand,
    rounded to three decimal places half-up; `predicted_cauti` follows the same
    shape with `cauti_baseline_per_1000` over `urinary_catheter_days`."

    Design: Difficulty/dual_variant_calc/sir_provisional_vs_final_on_monthly_summary
    """
    ctx = setup_summary_with_final_and_provisional_case()
    summary = get_summary(ctx["summary"]["id"])
    assert_monthly_summary(summary)
    assert summary["central_line_days"] == 500
    assert_approx_equal(summary["predicted_clabsi"], 1.0, "predicted_clabsi")
    assert summary["clabsi_count"] == 1, (
        f"final variant counts ADJUDICATED_HAI only, got {summary['clabsi_count']}"
    )
    assert summary["provisional_clabsi_count"] == 2, (
        "provisional variant adds the UNDER_REVIEW case, got "
        f"{summary['provisional_clabsi_count']}"
    )


def test_sir_values_differ_between_final_and_provisional(api, ip_headers):
    """PRD §3.7: "Each standardized infection ratio divides the observed count
    by the stored, already-rounded predicted value and rounds the quotient to
    three decimal places half-up."
    PRD §3.7: "This yields `sir_clabsi`, `sir_cauti`, and `sir_ssi` on the final
    variant, and `provisional_sir_clabsi`, `provisional_sir_cauti`, and
    `provisional_sir_ssi` dividing each provisional count by the same stored
    predicted value under the same not-calculated rule."
    PRD §3.7: "The `sir_flag` reads `HIGH` when any non-null SIR — across the
    three final ratios — is at least the facility's `sir_high_threshold`;
    `NORMAL` when at least one SIR is calculable and every calculable one sits
    below the threshold; and `NOT_CALCULATED` when no SIR is calculable at all."

    Design: Difficulty/dual_variant_calc/sir_provisional_vs_final_on_monthly_summary
    """
    ctx = setup_summary_with_final_and_provisional_case()
    summary = get_summary(ctx["summary"]["id"])
    assert_approx_equal(summary["sir_clabsi"], 1.0, "sir_clabsi")
    assert_approx_equal(summary["provisional_sir_clabsi"], 2.0, "provisional_sir_clabsi")
    assert summary["provisional_sir_clabsi"] != summary["sir_clabsi"], (
        "identical data must yield different variant results"
    )
    assert summary["sir_flag"] == "NORMAL", (
        f"final SIR 1.0 is below the 1.25 default threshold; got {summary['sir_flag']}"
    )


# ---------------------------------------------------------------------------
# SSI risk-tier mix
# ---------------------------------------------------------------------------

def test_predicted_ssi_combines_risk_weight_tiers(api, ip_headers):
    """PRD §3.7: "`predicted_ssi` is the facility's `ssi_baseline_per_procedure`
    multiplied by the sum of risk weights over the month's procedures, rounded
    to three decimals half-up. A procedure's risk weight is 2.0 (high) when its
    `asa_score` is at least 4 or its `wound_class` is `CONTAMINATED` or `DIRTY`;
    1.0 (low) when its `asa_score` is at most 2 and its `wound_class` is
    `CLEAN`; and 1.5 (medium) in every other case."

    Design: Difficulty/combinatorial_formula/ssi_predicted_risk_tier_mix_drives_sir
    """
    ctx = setup_or_unit_with_tiered_procedures_and_ssi()
    summary = get_summary(ctx["summary"]["id"])
    assert summary["procedure_count"] == 3
    # 0.25 * (1.0 LOW + 1.5 MEDIUM + 2.0 HIGH) = 1.125
    assert_approx_equal(summary["predicted_ssi"], 1.125, "predicted_ssi")


def test_sir_ssi_uses_stored_rounded_predicted(api, ip_headers):
    """PRD §3.7: "Each standardized infection ratio divides the observed count
    by the stored, already-rounded predicted value and rounds the quotient to
    three decimal places half-up."
    PRD §3.7: "The `sir_flag` reads `HIGH` when any non-null SIR — across the
    three final ratios — is at least the facility's `sir_high_threshold`;
    `NORMAL` when at least one SIR is calculable and every calculable one sits
    below the threshold; and `NOT_CALCULATED` when no SIR is calculable at all."

    Design: Difficulty/combinatorial_formula/ssi_predicted_risk_tier_mix_drives_sir
    """
    ctx = setup_or_unit_with_tiered_procedures_and_ssi()
    summary = get_summary(ctx["summary"]["id"])
    assert summary["ssi_count"] == 1
    # 1 / 1.125 = 0.8888... -> 0.889
    assert_approx_equal(summary["sir_ssi"], 0.889, "sir_ssi")
    assert summary["sir_flag"] == "NORMAL"


# ---------------------------------------------------------------------------
# SIR calculability floor
# ---------------------------------------------------------------------------

def test_sir_calculable_at_exactly_floor(api, ip_headers):
    """PRD §3.7: "Under the NHSN not-calculated rule, when the predicted value
    is below 1.0 the corresponding SIR is null rather than a number — the
    boundary is exactly 1.0, so a predicted value of exactly 1.0 does produce a
    ratio."

    Design: Difficulty/boundary_precision_check/sir_calculability_floor_exactly_one_vs_below
    """
    ctx = setup_two_units_straddling_sir_floor()
    summary_a = get_summary(ctx["summary_a"]["id"])
    assert_approx_equal(summary_a["predicted_clabsi"], 1.0, "predicted_clabsi")
    assert_approx_equal(summary_a["sir_clabsi"], 0.0, "sir_clabsi")
    assert summary_a["sir_flag"] == "NORMAL"


def test_sir_null_one_device_day_below_floor(api, ip_headers):
    """PRD §3.7: "Under the NHSN not-calculated rule, when the predicted value
    is below 1.0 the corresponding SIR is null rather than a number — the
    boundary is exactly 1.0, so a predicted value of exactly 1.0 does produce a
    ratio."
    PRD §3.7: "The `sir_flag` reads `HIGH` when any non-null SIR — across the
    three final ratios — is at least the facility's `sir_high_threshold`;
    `NORMAL` when at least one SIR is calculable and every calculable one sits
    below the threshold; and `NOT_CALCULATED` when no SIR is calculable at all."

    Design: Difficulty/boundary_precision_check/sir_calculability_floor_exactly_one_vs_below
    """
    ctx = setup_two_units_straddling_sir_floor()
    summary_b = get_summary(ctx["summary_b"]["id"])
    assert_approx_equal(summary_b["predicted_clabsi"], 0.998, "predicted_clabsi")
    assert summary_b["sir_clabsi"] is None, (
        f"0.998 < 1.0 must be NOT_CALCULATED, got {summary_b['sir_clabsi']}"
    )
    assert summary_b["sir_flag"] == "NOT_CALCULATED"


# ---------------------------------------------------------------------------
# Compensating invariants
# ---------------------------------------------------------------------------

def test_adjudication_credits_unit_month_count(api, ip_headers):
    """PRD §3.5: "The covering monthly summary, if it exists and is mutable, has
    its observed and provisional counts, predicted figures, SIR fields, and
    `sir_flag` recomputed, incrementing the summary's `version`."
    PRD §3.7: "The **final** variant counts cases attributed to the unit whose
    status is `ADJUDICATED_HAI` and whose `date_of_event` calendar date falls in
    the month — producing `clabsi_count`, `cauti_count`, and `ssi_count` by case
    type."

    Design: Difficulty/compensating_invariant/adjudicate_reopen_cycle_conserves_unit_month_case_count
    """
    ctx = setup_case_under_review_with_open_summary()
    assert ctx["summary"]["clabsi_count"] == 0, "baseline count must be 0"
    adjudicate_hai(ctx["case"]["id"], "2026-08-04T00:00:00Z",
                   rationale="BSI with matching cultures")
    summary = get_summary(ctx["summary"]["id"])
    assert summary["clabsi_count"] == 1, (
        f"adjudication must credit the unit-month, got {summary['clabsi_count']}"
    )


def test_reopen_restores_unit_month_count_to_baseline(api, ip_headers):
    """PRD §3.5: "Reopening clears `date_of_event`, `is_hai`, and
    `rit_blocked_until` to null, lands the case in `REOPENED`, and recomputes
    the covering summary's counts, SIRs, and `sir_flag` when mutable."

    Design: Difficulty/compensating_invariant/adjudicate_reopen_cycle_conserves_unit_month_case_count
    """
    ctx = setup_case_under_review_with_open_summary()
    base_count = ctx["summary"]["clabsi_count"]
    adjudicate_hai(ctx["case"]["id"], "2026-08-04T00:00:00Z",
                   rationale="BSI with matching cultures")
    assert get_summary(ctx["summary"]["id"])["clabsi_count"] == 1
    reopened = reopen_case(ctx["case"]["id"], reason="repeat culture negative")
    assert reopened["status"] == "REOPENED"
    assert reopened["date_of_event"] is None
    summary = get_summary(ctx["summary"]["id"])
    assert summary["clabsi_count"] == base_count == 0, (
        f"adjudicate+reopen must conserve the count, got {summary['clabsi_count']}"
    )


def test_forward_correction_recomputes_summary_denominator(api, nurse_manager_headers):
    """PRD §3.6: "A successful correction increments the row's `version` by one
    and recomputes the covering summary when mutable."
    PRD §3.7: "The denominator fields are straight aggregations over the unit's
    `DRAFT` or `LOCKED` denominator rows whose `count_date` falls in the month:
    `central_line_days`, `urinary_catheter_days`, `ventilator_days`, and
    `patient_days_total` are the respective sums."

    Design: Difficulty/compensating_invariant/device_day_correction_pair_conserves_denominator_total
    """
    ctx = setup_open_summary_with_day_row()
    assert ctx["summary"]["central_line_days"] == 20
    row_v1 = ctx["day_row"]["version"]
    corrected = correct_device_day_count(
        ctx["day_row"]["id"], row_v1, central_line_days=25,
        urinary_catheter_days=10, ventilator_days=5, patient_days=40,
    )
    assert corrected["version"] == row_v1 + 1, (
        f"each accepted correction bumps version by exactly 1: "
        f"{row_v1} -> {corrected['version']}"
    )
    summary = get_summary(ctx["summary"]["id"])
    assert summary["central_line_days"] == 25


def test_compensating_correction_conserves_denominator_total(
    api, nurse_manager_headers
):
    """PRD §3.6: "A successful correction increments the row's `version` by one
    and recomputes the covering summary when mutable."

    Design: Difficulty/compensating_invariant/device_day_correction_pair_conserves_denominator_total
    """
    ctx = setup_open_summary_with_day_row()
    row_v1 = ctx["day_row"]["version"]
    corrected = correct_device_day_count(
        ctx["day_row"]["id"], row_v1, central_line_days=25,
        urinary_catheter_days=10, ventilator_days=5, patient_days=40,
    )
    restored = correct_device_day_count(
        ctx["day_row"]["id"], corrected["version"], central_line_days=20,
        urinary_catheter_days=10, ventilator_days=5, patient_days=40,
    )
    assert restored["version"] == row_v1 + 2, (
        f"two accepted writes must each increment by exactly 1: "
        f"{row_v1} -> {restored['version']}"
    )
    summary = get_summary(ctx["summary"]["id"])
    assert summary["central_line_days"] == 20, (
        f"the correction pair must conserve the aggregate, got "
        f"{summary['central_line_days']}"
    )


# ---------------------------------------------------------------------------
# Covering-summary lock gating corrections and creates
# ---------------------------------------------------------------------------

def test_correction_rejected_while_summary_submitted(api, nurse_manager_headers):
    """PRD §2.10: "While the covering summary for a unit and month — the summary
    whose `month` matches the calendar month of the row in question — is locked,
    five operations are rejected with `ERR_SUMMARY_LOCKED`: creating a
    device-day count for that unit-month, correcting one, recording a surgical
    procedure whose `performed_at` falls in that unit-month, adjudicating an
    infection case whose attributed unit and date-of-event month are covered by
    the locked summary, and reopening a case covered by it."

    Design: Difficulty/cross_entity_state_dependency/device_day_correction_gated_by_summary_state
    """
    ctx = setup_submitted_summary_with_day_row()
    locked_row = ctx["day_row"]
    assert locked_row["status"] == "LOCKED"
    resp = api.update_device_day_count(
        locked_row["id"],
        {
            "central_line_days": 25,
            "urinary_catheter_days": 10,
            "ventilator_days": 5,
            "patient_days": 40,
            "expected_device_day_count_version": locked_row["version"],
        },
        nurse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SUMMARY_LOCKED)
    row_after = get_device_day_count(locked_row["id"])
    assert row_after["central_line_days"] == 20, "rejected correction must not persist"


def test_correction_succeeds_after_summary_rejected(api, nurse_manager_headers,
                                                    director_headers):
    """PRD §2.10: "Rejection and amendment of a summary compensate by reverting
    that unit-month's denominator rows from `LOCKED` back to `DRAFT`, restoring
    writability."
    PRD §3.6: "A successful correction increments the row's `version` by one and
    recomputes the covering summary when mutable."

    Design: Difficulty/cross_entity_state_dependency/device_day_correction_gated_by_summary_state
    """
    ctx = setup_submitted_summary_with_day_row()
    reject_summary(ctx["summary"]["id"], reason="denominator audit finding")
    row = get_device_day_count(ctx["day_row"]["id"])
    assert row["status"] == "DRAFT"
    corrected = correct_device_day_count(
        row["id"], row["version"], central_line_days=25,
        urinary_catheter_days=10, ventilator_days=5, patient_days=40,
    )
    assert corrected["version"] == row["version"] + 1
    summary = get_summary(ctx["summary"]["id"])
    assert summary["status"] == "REJECTED"
    assert summary["central_line_days"] == 25, (
        "the rejected summary is mutable again and must recompute"
    )


def test_locked_month_create_reports_lock_not_duplicate(api, nurse_manager_headers):
    """PRD §2.5: "When a single request violates more than one rule, the error
    it receives is determined by a fixed priority order, evaluated top-down; the
    request reports the violation with the lowest priority number."
    PRD §2.5: "**Covering-summary lock.** Mutations that would alter the inputs
    of a monthly summary — creating or correcting a device-day row, recording a
    surgical procedure, adjudicating or reopening an infection case — are
    rejected with `ERR_SUMMARY_LOCKED` (HTTP 409) when the covering summary
    exists and is not in a mutable status."
    PRD §3.6: "Only one row may exist per unit and calendar date — a duplicate
    yields `ERR_DUPLICATE_DEVICE_DAY_COUNT`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_locked_month_denominator
    """
    ctx = setup_submitted_summary_with_day_row(central_line_days=10)
    resp = api.create_device_day_count(
        {
            "unit_id": ctx["unit"]["id"],
            "count_date": "2026-08-01T00:00:00Z",
            "central_line_days": 11,
            "urinary_catheter_days": 5,
            "ventilator_days": 2,
            "patient_days": 40,
        },
        nurse_manager_headers,
    )
    # Both the covering-summary lock and the (unit, count_date) uniqueness
    # constraint are violated; the lock rule sits higher in the priority order.
    validate_error(resp, ApiErrorId.ERR_SUMMARY_LOCKED)


def test_locked_month_create_leaves_existing_row_untouched(
    api, nurse_manager_headers, director_headers
):
    """PRD §2.10: "Rejection and amendment of a summary compensate by reverting
    that unit-month's denominator rows from `LOCKED` back to `DRAFT`, restoring
    writability."
    PRD §3.6: "Only one row may exist per unit and calendar date — a duplicate
    yields `ERR_DUPLICATE_DEVICE_DAY_COUNT`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_locked_month_denominator
    """
    ctx = setup_submitted_summary_with_day_row(central_line_days=10)
    api.create_device_day_count(
        {
            "unit_id": ctx["unit"]["id"],
            "count_date": "2026-08-01T00:00:00Z",
            "central_line_days": 11,
            "urinary_catheter_days": 5,
            "ventilator_days": 2,
            "patient_days": 40,
        },
        nurse_manager_headers,
    )
    row = get_device_day_count(ctx["day_row"]["id"])
    assert row["central_line_days"] == 10, "the existing row must remain unchanged"
    assert get_summary(ctx["summary"]["id"])["status"] == "SUBMITTED"

    # Control: once the lock lifts (summary REJECTED), the identical payload
    # surfaces the uniqueness rule instead.
    reject_summary(ctx["summary"]["id"], reason="denominator audit finding")
    resp_dup = api.create_device_day_count(
        {
            "unit_id": ctx["unit"]["id"],
            "count_date": "2026-08-01T00:00:00Z",
            "central_line_days": 11,
            "urinary_catheter_days": 5,
            "ventilator_days": 2,
            "patient_days": 40,
        },
        nurse_manager_headers,
    )
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_DEVICE_DAY_COUNT)


# ---------------------------------------------------------------------------
# sir_flag HIGH and facility baseline recompute
# ---------------------------------------------------------------------------

def test_sir_high_flag_and_facility_baseline_recompute(api, admin_headers,
                                                       ip_headers):
    """PRD §3.7: "The `sir_flag` reads `HIGH` when any non-null SIR — across the
    three final ratios — is at least the facility's `sir_high_threshold`;
    `NORMAL` when at least one SIR is calculable and every calculable one sits
    below the threshold; and `NOT_CALCULATED` when no SIR is calculable at all."
    PRD §3.1: "The update increments the facility's `version` by one and
    immediately recomputes the predicted and SIR fields of every monthly summary
    in a mutable status — `OPEN`, `REJECTED`, or `UNDER_AMENDMENT` — across all
    of the facility's units, each such recompute incrementing that summary's own
    `version`."

    Design: Corner/calculations/sir_high_flag_and_facility_baseline_recompute
    """
    from test_helpers import create_facility, create_unit

    facility = create_facility()
    unit = create_unit(facility["id"], name="ICU-HI")
    create_device_day_rows(
        unit["id"],
        [
            {
                "count_date": f"2026-08-0{day}T00:00:00Z",
                "central_line_days": 100,
                "urinary_catheter_days": 0,
                "ventilator_days": 0,
                "patient_days": 120,
            }
            for day in range(1, 6)
        ],
    )
    patient_1 = create_patient(unit["id"])
    patient_2 = create_patient(unit["id"])
    episode_1 = create_device_episode(patient_1["id"])
    episode_2 = create_device_episode(patient_2["id"])
    create_adjudicated_clabsi(
        patient_1["id"], episode_1["id"], "E. coli",
        "2026-08-04T09:00:00Z", "2026-08-04T00:00:00Z",
    )
    create_adjudicated_clabsi(
        patient_2["id"], episode_2["id"], "S. aureus",
        "2026-08-06T09:00:00Z", "2026-08-06T00:00:00Z",
    )
    summary = create_monthly_summary(unit["id"], "2026-08")
    assert_approx_equal(summary["sir_clabsi"], 2.0, "sir_clabsi at creation")
    assert summary["sir_flag"] == "HIGH", (
        f"2.0 >= 1.25 default threshold must flag HIGH, got {summary['sir_flag']}"
    )

    updated = validate_success(
        api.update_facility(
            facility["id"],
            {
                "clabsi_baseline_per_1000": 4.0,
                "expected_facility_version": facility["version"],
            },
            admin_headers,
        )
    )
    assert updated["version"] == facility["version"] + 1

    recomputed = get_summary(summary["id"])
    assert_approx_equal(recomputed["predicted_clabsi"], 2.0, "predicted_clabsi")
    assert_approx_equal(recomputed["sir_clabsi"], 1.0, "sir_clabsi")
    assert recomputed["sir_flag"] == "NORMAL", (
        f"1.0 < 1.25 must drop the flag to NORMAL, got {recomputed['sir_flag']}"
    )


# ---------------------------------------------------------------------------
# Reconcile endpoint
# ---------------------------------------------------------------------------

def test_device_day_reconcile_matches_episode_derivation(api, nurse_manager_headers):
    """PRD §3.6: "The expected device days are the count of device episodes for
    that unit and device type that touched any instant of the calendar day —
    episodes placed before the next day's midnight and either never removed or
    removed no earlier than that day's midnight."
    PRD §3.6: "The response carries `expected_device_days`, the
    `recorded_device_days` from the matching row (null when no row exists),
    their `delta` (null when no row exists), and a `matches` boolean."

    Design: Corner/calculations/device_day_reconcile_matches_episode_derivation
    """
    ctx = setup_unit_with_patient()
    unit_id = ctx["unit"]["id"]
    patient_2 = create_patient(unit_id)
    patient_3 = create_patient(unit_id)
    create_device_episode(ctx["patient"]["id"], placed_at="2026-08-01T10:00:00Z")
    create_device_episode(patient_2["id"], placed_at="2026-08-03T06:00:00Z")
    episode_3 = create_device_episode(patient_3["id"], placed_at="2026-08-02T10:00:00Z")
    from test_helpers import remove_device_episode

    remove_device_episode(episode_3["id"], "2026-08-03T18:00:00Z")
    create_device_day_count(
        unit_id, "2026-08-03T00:00:00Z",
        central_line_days=2, urinary_catheter_days=0, ventilator_days=0,
        patient_days=3,
    )

    resp = api.reconcile_device_day_counts(
        unit_id, "CENTRAL_LINE", "2026-08-03T00:00:00Z", nurse_manager_headers
    )
    data = validate_success(resp)
    assert data["expected_device_days"] == 3, (
        f"three episodes touch 2026-08-03, got {data['expected_device_days']}"
    )
    assert data["recorded_device_days"] == 2
    # PRD §3.6 names a `delta` field (null when no row exists) but never pins
    # its sign convention (recorded - expected vs expected - recorded), so
    # only the magnitude is uniquely derivable.
    assert abs(data["delta"]) == 1
    assert data["matches"] is False


# ---------------------------------------------------------------------------
# Submission cycle
# ---------------------------------------------------------------------------

def test_summary_full_cycle_submit_reject_resubmit_accept(
    api, ip_headers, nurse_manager_headers
):
    """PRD §3.7: "Submission — from `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`,
    anything else rejected with `ERR_SUMMARY_NOT_SUBMITTABLE` — records
    `submitted_by_user_id` from the acting user's header, cascades every
    denominator row for the unit and month into `LOCKED`, and is refused
    outright with `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` when the unit's
    `surveillance_posture` is `OUTBREAK`."
    PRD §3.7: "Rejection, also from `SUBMITTED` under the same
    `ERR_SUMMARY_NOT_REVIEWABLE` guard, takes a `reason`, lands the summary in
    `REJECTED`, and compensates by reverting that unit-month's denominator rows
    from `LOCKED` back to `DRAFT`."

    Design: Corner/state_machines/summary_full_cycle_submit_reject_resubmit_accept
    """
    ctx = setup_open_summary_with_day_row()
    summary_id = ctx["summary"]["id"]
    row_id = ctx["day_row"]["id"]

    submitted = submit_summary(summary_id, user_id="ip-user-1")
    assert submitted["status"] == "SUBMITTED"
    assert get_device_day_count(row_id)["status"] == "LOCKED"

    rejected = reject_summary(summary_id, reason="incomplete device days",
                              user_id="dir-user-1")
    assert rejected["status"] == "REJECTED"
    assert get_device_day_count(row_id)["status"] == "DRAFT"

    resubmitted = submit_summary(summary_id, user_id="ip-user-1")
    assert resubmitted["status"] == "SUBMITTED"
    accepted = accept_summary(summary_id, user_id="dir-user-9")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["submitted_by_user_id"] == "ip-user-1"
    assert accepted["accepted_by_user_id"] == "dir-user-9"


def test_summary_accept_from_open_returns_not_reviewable(api, director_headers):
    """PRD §3.7: "Acceptance requires `SUBMITTED` status
    (`ERR_SUMMARY_NOT_REVIEWABLE`) and enforces segregation of duties: the
    accepting user's `X-User-ID` must differ from `submitted_by_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTY`."

    Design: Corner/state_machines/summary_accept_from_open_returns_not_reviewable
    """
    ctx = setup_open_summary_with_day_row()
    resp = api.accept_summary(ctx["summary"]["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_SUMMARY_NOT_REVIEWABLE)


def test_summary_amend_from_open_returns_not_amendable(api, ip_headers):
    """PRD §3.7: "Amendment — allowed only from `ACCEPTED`, otherwise
    `ERR_SUMMARY_NOT_AMENDABLE` — takes a `reason`, increments `amendment_count`
    by one, clears both `submitted_by_user_id` and `accepted_by_user_id` to
    null, reverts the denominator rows to `DRAFT`, and lands the summary in
    `UNDER_AMENDMENT`, from which the submit-review cycle can run again."

    Design: Corner/state_machines/summary_amend_from_open_returns_not_amendable
    """
    ctx = setup_open_summary_with_day_row()
    resp = api.amend_summary(
        ctx["summary"]["id"], {"reason": "premature amendment"}, ip_headers
    )
    validate_error(resp, ApiErrorId.ERR_SUMMARY_NOT_AMENDABLE)
