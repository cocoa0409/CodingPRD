"""Depth coverage: the two-accounting reads and the pinned arithmetic orders."""
from test_helpers import (
    TEST_USERS,
    activate_tuition_agreement,
    assert_tuition_cents_identity,
    create_tuition_agreement,
    drive_segment_to_good_faith,
    fetch_dq_file,
    file_dq_document,
    order_screening_check,
    record_employment_segment,
    request_and_verify_segment,
    set_clock,
    setup_hired_applicant,
    setup_submitted_application,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]

GOOD_FAITH_CLOCK_STOPS = (
    "2026-08-15T00:00:00Z",
    "2026-08-29T00:00:00Z",
    "2026-09-12T00:00:00Z",
)


def _submitted_file_with_two_waived_artifacts(dot_number: str):
    """One submitted application whose CDL_COPY and CRIMINAL_CHECK rows are WAIVED."""
    ctx = setup_submitted_application(carrier_overrides={"dot_number": dot_number})
    file_dq_document(
        ctx["dq_file_id"], "CDL_COPY", status="WAIVED", effective_on="2026-08-01"
    )
    file_dq_document(
        ctx["dq_file_id"], "CRIMINAL_CHECK", status="WAIVED", effective_on="2026-08-01"
    )
    return ctx


def _application_with_good_faith_and_verified_segments(dot_number: str):
    """One good-faith-documented segment and one verified segment, clock back at startup."""
    ctx = setup_submitted_application(carrier_overrides={"dot_number": dot_number})
    good_faith = record_employment_segment(
        ctx["application_id"], "Blue Line Cartage", "2022-01-01", "2024-09-01"
    )
    verified = record_employment_segment(
        ctx["application_id"], "Northgate Haul", "2024-09-01", "2026-08-01"
    )
    ctx["good_faith_verification"] = drive_segment_to_good_faith(
        good_faith["id"], GOOD_FAITH_CLOCK_STOPS
    )
    ctx["verified_verification"] = request_and_verify_segment(verified["id"])
    set_clock("2026-08-01T00:00:00Z")
    return ctx


# ─── dual_variant_calc ────────────────────────────────────────────────────────

def test_provisional_accounting_counts_waived_rows_against_a_denominator_of_28(api):
    """PRD §3.7: "The provisional accounting, named `pre_hire_provisional`, is the default and
    the only one persisted: it is what `completeness_pct` and `deficiency_count` hold on the
    file and what drives the file's status between `OPEN`, `COMPLETE` and `DEFICIENT`. It
    excludes `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` from scope, leaving a denominator of 28, and
    it treats both `PRESENT` and `WAIVED` as satisfying, so a waived artifact counts toward the
    score."
    PRD §3.7: "It adds up the integer weights of the satisfied rows, divides that total by the
    denominator, multiplies by 100, and rounds half up to two decimal places **once**."
    PRD §3.7: "The `deficiency_count` is the plain count of in-scope rows minus the count of
    satisfied rows — a count of documents, not of weight."

    Design: Difficulty/dual_variant_calc/dq_completeness_prehire_vs_annual_variants_diverge
    """
    ctx = _submitted_file_with_two_waived_artifacts("DOT-2166-A")

    payload = validate_success(
        api.get_dq_file_completeness(
            ctx["dq_file_id"], AUDITOR, params={"variant": "pre_hire_provisional"}
        )
    )

    assert float(payload["completeness_pct"]) == 21.43
    assert payload["satisfied_weight"] == 6
    assert payload["denominator_weight"] == 28
    assert payload["deficiency_count"] == 7

    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert float(dq_file["completeness_pct"]) == 21.43, (
        "the persisted figure always tracks the provisional accounting"
    )
    assert dq_file["status"] == "OPEN"


def test_final_accounting_drops_waived_rows_against_a_denominator_of_30(api):
    """PRD §3.7: "The final accounting, named `annual_review_final`, is the figure a DOT
    auditor certifies against and is available only on demand: it excludes `PSP_REPORT` and
    `CRIMINAL_CHECK`, which are pre-employment-only artifacts, and brings `MVR_ANNUAL` and
    `ANNUAL_REVIEW_CERT` into scope, leaving a denominator of 30, and it treats only `PRESENT`
    as satisfying, so a `WAIVED` artifact does not count. The same twelve rows therefore yield
    two different percentages."
    PRD §3.7: "The `deficiency_count` is the plain count of in-scope rows minus the count of
    satisfied rows — a count of documents, not of weight."

    Design: Difficulty/dual_variant_calc/dq_completeness_prehire_vs_annual_variants_diverge
    """
    ctx = _submitted_file_with_two_waived_artifacts("DOT-2166-A")

    final = validate_success(
        api.get_dq_file_completeness(
            ctx["dq_file_id"], AUDITOR, params={"variant": "annual_review_final"}
        )
    )
    provisional = validate_success(
        api.get_dq_file_completeness(
            ctx["dq_file_id"], AUDITOR, params={"variant": "pre_hire_provisional"}
        )
    )

    assert float(final["completeness_pct"]) == 10.00
    assert final["satisfied_weight"] == 3
    assert final["denominator_weight"] == 30
    assert final["deficiency_count"] == 9
    assert float(final["completeness_pct"]) != float(provisional["completeness_pct"]), (
        "the same twelve rows must yield two different percentages"
    )


def test_strict_coverage_excludes_the_good_faith_segment(api):
    """PRD §3.3: "The strict accounting, named `strict_verified`, admits only segments in
    `RESPONDED_VERIFIED`; it is the default, it is the one persisted into the application's
    `verified_coverage_days` and `gap_days_unexplained`, and it is the one the hiring gate
    enforces."
    PRD §3.3: "Once `request_round` has reached 3, the same trigger instead lands the segment
    in the terminal `GOOD_FAITH_DOCUMENTED` state, and that transition recomputes the parent
    application's `verified_coverage_days` and `gap_days_unexplained` — which, under the strict
    accounting those two fields use, does *not* credit the good-faith segment."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by the
    merged runs, and `gap_days_unexplained` is 1,095 minus that figure."

    Design: Difficulty/dual_variant_calc/employment_coverage_strict_vs_good_faith_variants_diverge
    """
    ctx = _application_with_good_faith_and_verified_segments("DOT-2166-B")

    assert ctx["good_faith_verification"]["status"] == "GOOD_FAITH_DOCUMENTED"
    assert ctx["good_faith_verification"]["request_round"] == 3
    assert ctx["verified_verification"]["status"] == "RESPONDED_VERIFIED"

    strict = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "strict_verified"}
        )
    )
    assert strict["verified_coverage_days"] == 699
    assert strict["gap_days_unexplained"] == 396
    assert strict["merged_segment_count"] == 1

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["verified_coverage_days"] == 699
    assert application["gap_days_unexplained"] == 396


def test_projected_coverage_credits_the_good_faith_segment_and_merges_it(api):
    """PRD §3.3: "The projected accounting, named `good_faith_projected`, admits segments in
    `RESPONDED_VERIFIED` and `GOOD_FAITH_DOCUMENTED` alike, so an employer that never answered
    three documented requests still counts as covered; identical rows therefore yield a larger
    coverage and a smaller gap under the projected accounting than under the strict one."
    PRD §3.3: "They are then merged left to right: the next segment joins the run in progress
    when its lower bound is less than or equal to the run's current upper bound, so that two
    segments which merely touch at a shared date *do* merge, while a one-day hole between them
    does *not*."
    PRD §3.3: "The window opens 1,095 days before the current logical-clock calendar date and
    closes at that date, and it is half-open: the opening day is included and the closing day is
    not."

    Design: Difficulty/dual_variant_calc/employment_coverage_strict_vs_good_faith_variants_diverge
    """
    ctx = _application_with_good_faith_and_verified_segments("DOT-2166-B")

    projected = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "good_faith_projected"}
        )
    )

    assert projected["verified_coverage_days"] == 1095
    assert projected["gap_days_unexplained"] == 0
    assert projected["merged_segment_count"] == 1, (
        "the clipped good-faith run touches the verified run and merges with it"
    )


def test_an_mvr_score_applies_the_credit_and_the_carrier_multiplier(api):
    """PRD §3.4: "The raw score is always the sum of three weighted terms: each moving-violation
    point contributes 1.0, each serious violation contributes 4.0, and each preventable crash
    contributes 6.0."
    PRD §3.4: "The net is then multiplied by the carrier's safety-rating multiplier — 1.00 when
    the carrier's `safety_rating` is `SATISFACTORY`, 1.25 when it is `CONDITIONAL`, and 1.50 when
    it is `UNSATISFACTORY` — and only that product is rounded half up to two decimal places to
    produce `adjudication_score`."
    PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as `issued_on`
    advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening Program report
    and for a criminal check `expires_on` stays null."

    Design: Difficulty/dual_variant_calc/screening_score_mvr_variant_vs_raw_variant_diverge
    """
    ctx = setup_submitted_application(
        carrier_overrides={
            "legal_name": "Cutbank Transport",
            "dot_number": "DOT-2166-C",
            "safety_rating": "CONDITIONAL",
        },
        applicant_overrides={"experience_months": 24},
    )
    mvr = order_screening_check(ctx["application_id"], "MVR")

    recorded = validate_success(
        api.record_screening_result(
            mvr["id"],
            {
                "issued_on": "2026-07-01",
                "violation_points": 5,
                "serious_violation_count": 1,
                "crash_preventable_count": 0,
            },
            RECRUITER,
        )
    )

    assert float(recorded["adjudication_score"]) == 7.50, (
        "raw 9.0 less the 3.0 credit, scaled by the 1.25 conditional multiplier"
    )
    assert recorded["expires_on"] == "2027-07-01"
    assert recorded["status"] == "RECEIVED"


def test_a_psp_score_skips_the_credit_and_the_multiplier(api):
    """PRD §3.4: "For a `PSP` or `CRIMINAL` report the adjudication score is that raw sum
    rounded half up to two decimal places and nothing more — no experience credit, no multiplier
    — and it is informational only, never blocking a pass."
    PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as `issued_on`
    advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening Program report
    and for a criminal check `expires_on` stays null."

    Design: Difficulty/dual_variant_calc/screening_score_mvr_variant_vs_raw_variant_diverge
    """
    ctx = setup_submitted_application(
        carrier_overrides={
            "legal_name": "Cutbank Transport",
            "dot_number": "DOT-2166-C",
            "safety_rating": "CONDITIONAL",
        },
        applicant_overrides={"experience_months": 24},
    )
    psp = order_screening_check(ctx["application_id"], "PSP")

    recorded = validate_success(
        api.record_screening_result(
            psp["id"],
            {
                "issued_on": "2026-07-01",
                "violation_points": 5,
                "serious_violation_count": 1,
                "crash_preventable_count": 0,
            },
            RECRUITER,
        )
    )

    assert float(recorded["adjudication_score"]) == 9.00, "the raw sum, unadjusted"
    assert recorded["expires_on"] is None
    assert recorded["status"] == "RECEIVED"


# ─── combinatorial_formula ────────────────────────────────────────────────────

def test_the_experience_credit_is_capped_before_the_multiplier_is_applied(api):
    """PRD §3.4: "The credit is 1.5 for each full year of the applicant's `experience_months`,
    taking the whole number of years by discarding any remaining months, and it is capped at 6.0
    however long the driver has been on the road; the credit is not rounded before it is
    subtracted."
    PRD §3.4: "The net is the raw sum minus that credit, floored at zero so a very experienced
    clean driver never scores below nothing. The net is then multiplied by the carrier's
    safety-rating multiplier — 1.00 when the carrier's `safety_rating` is `SATISFACTORY`, 1.25
    when it is `CONDITIONAL`, and 1.50 when it is `UNSATISFACTORY` — and only that product is
    rounded half up to two decimal places to produce `adjudication_score`."
    PRD §3.4: "The raw score is always the sum of three weighted terms: each moving-violation
    point contributes 1.0, each serious violation contributes 4.0, and each preventable crash
    contributes 6.0."

    Design: Difficulty/combinatorial_formula/mvr_score_five_input_nonlinear_branching_mode_a
    """
    ctx = setup_submitted_application(
        carrier_overrides={"legal_name": "Grayhill Bulk", "dot_number": "DOT-2166-D"},
        applicant_overrides={"experience_months": 72},
    )
    carrier = validate_success(api.get_carrier(ctx["carrier_id"], SAFETY_DIRECTOR))
    validate_success(
        api.update_carrier(
            ctx["carrier_id"],
            {"safety_rating": "UNSATISFACTORY", "expected_carrier_version": carrier["version"]},
            SAFETY_DIRECTOR,
        )
    )
    mvr = order_screening_check(ctx["application_id"], "MVR")

    recorded = validate_success(
        api.record_screening_result(
            mvr["id"],
            {
                "issued_on": "2026-07-01",
                "violation_points": 8,
                "serious_violation_count": 1,
                "crash_preventable_count": 1,
            },
            RECRUITER,
        )
    )

    assert float(recorded["adjudication_score"]) == 18.00, (
        "six years would earn 9.0 of credit but the cap holds it at 6.0, "
        "so the net 12.0 scaled by 1.50 is 18.00 rather than 13.50"
    )


def test_the_capped_credit_score_lands_the_report_in_received_with_its_expiry(api):
    """PRD §3.4: "It is accepted from `ORDERED` and, identically, from `DISPUTED` — a corrected
    report simply overwrites the earlier figures — and in both cases the row lands in
    `RECEIVED`."
    PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as `issued_on`
    advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening Program report
    and for a criminal check `expires_on` stays null."
    PRD §3.1: "the posture is `FROZEN` when the carrier's `safety_rating` is `UNSATISFACTORY`"

    Design: Difficulty/combinatorial_formula/mvr_score_five_input_nonlinear_branching_mode_a
    """
    ctx = setup_submitted_application(
        carrier_overrides={"legal_name": "Grayhill Bulk", "dot_number": "DOT-2166-D"},
        applicant_overrides={"experience_months": 72},
    )
    carrier = validate_success(api.get_carrier(ctx["carrier_id"], SAFETY_DIRECTOR))
    frozen = validate_success(
        api.update_carrier(
            ctx["carrier_id"],
            {"safety_rating": "UNSATISFACTORY", "expected_carrier_version": carrier["version"]},
            SAFETY_DIRECTOR,
        )
    )
    assert frozen["posture"] == "FROZEN"
    mvr = order_screening_check(ctx["application_id"], "MVR")

    recorded = validate_success(
        api.record_screening_result(
            mvr["id"],
            {
                "issued_on": "2026-07-01",
                "violation_points": 8,
                "serious_violation_count": 1,
                "crash_preventable_count": 1,
            },
            RECRUITER,
        )
    )

    assert recorded["status"] == "RECEIVED"
    assert recorded["expires_on"] == "2027-07-01"


def test_completeness_rounds_the_ratio_once_rather_than_per_document(api):
    """PRD §3.7: "The service first selects the in-scope rows for the accounting being applied
    and adds up their integer weights to form the denominator."
    PRD §3.7: "It adds up the integer weights of the satisfied rows, divides that total by the
    denominator, multiplies by 100, and rounds half up to two decimal places **once**. Computing
    each document's own percentage contribution, rounding each of those, and adding them up is a
    different computation and produces a different number."

    Design: Difficulty/combinatorial_formula/dq_completeness_rounding_order_mode_b
    """
    ctx = _submitted_file_with_two_waived_artifacts("DOT-2166-E")

    payload = validate_success(
        api.get_dq_file_completeness(
            ctx["dq_file_id"], AUDITOR, params={"variant": "pre_hire_provisional"}
        )
    )

    assert float(payload["completeness_pct"]) == 21.43, (
        "summing the weights 3 + 2 + 1 and rounding 6/28 once yields 21.43, "
        "not the 21.42 that per-document rounding produces"
    )
    assert float(payload["completeness_pct"]) != 21.42
    assert payload["satisfied_weight"] == 6
    assert payload["denominator_weight"] == 28


def test_the_persisted_completeness_uses_the_same_single_rounding(api):
    """PRD §3.7: "The provisional accounting, named `pre_hire_provisional`, is the default and
    the only one persisted: it is what `completeness_pct` and `deficiency_count` hold on the file
    and what drives the file's status between `OPEN`, `COMPLETE` and `DEFICIENT`."
    PRD §3.7: "It adds up the integer weights of the satisfied rows, divides that total by the
    denominator, multiplies by 100, and rounds half up to two decimal places **once**."
    PRD §2.8: "A qualification file's completeness percentage is carried to exactly 2 decimal
    places."

    Design: Difficulty/combinatorial_formula/dq_completeness_rounding_order_mode_b
    """
    ctx = _submitted_file_with_two_waived_artifacts("DOT-2166-E")

    dq_file = fetch_dq_file(ctx["dq_file_id"])

    assert float(dq_file["completeness_pct"]) == 21.43
    assert dq_file["deficiency_count"] == 7
    assert dq_file["total_weight"] == 33


def test_the_retention_tier_is_keyed_on_the_base_month_not_the_result(api):
    """PRD §3.9: "Step one divides `tuition_total_cents` by `commitment_months` and takes the
    floor, giving `base_monthly_cents`, the principal retired per served month."
    PRD §3.9: "Step two keys a retention tier off that base figure and off nothing else: a base
    of at least 20,000 cents — two hundred dollars a month — earns a bonus rate of zero percent,
    a base of at least 10,000 cents but below that earns five percent, and anything below 10,000
    cents earns ten percent. The tier is deliberately keyed on `base_monthly_cents` and is never
    re-keyed on the larger figure step three produces, even though that larger figure can fall in
    a different tier; re-keying would be circular and yields a wrong answer."
    PRD §3.9: "Step three sets `monthly_reimbursement_cents` to `base_monthly_cents` plus the
    bonus, where the bonus is `base_monthly_cents` multiplied by the tier rate and rounded half up
    to a whole cent."

    Design: Difficulty/combinatorial_formula/tuition_tier_keyed_on_base_monthly_mode_c
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-2166-F"})
    agreement = create_tuition_agreement(
        ctx["applicant_id"],
        school_name="Prairie CDL Academy",
        tuition_total_cents=115205,
        commitment_months=12,
    )

    activated = validate_success(api.activate_tuition_agreement(agreement["id"], SCHOOL))

    assert activated["base_monthly_cents"] == 9600
    assert activated["monthly_reimbursement_cents"] == 10560, (
        "a base of 9600 sits in the ten-percent tier; re-keying on the 10560 result "
        "would wrongly yield 10080"
    )


def test_activation_writes_off_the_floor_remainder_and_opens_the_balance(api):
    """PRD §3.9: "Step four sets `forgiven_cents` to `tuition_total_cents` minus the product of
    `base_monthly_cents` and `commitment_months` — the floor remainder the carrier writes off at
    activation — and opens `outstanding_cents` at `tuition_total_cents` minus `forgiven_cents`.
    The agreement moves `PENDING → ACTIVE`."
    PRD §3.9: "The agreement opens in `PENDING` with every ledger figure at zero."
    PRD §3.9: "One identity holds after every one of those three operations without exception:
    `tuition_total_cents` always equals `reimbursed_cents` plus `clawback_cents` plus
    `outstanding_cents` plus `forgiven_cents`."

    Design: Difficulty/combinatorial_formula/tuition_tier_keyed_on_base_monthly_mode_c
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-2166-F"})
    agreement = create_tuition_agreement(
        ctx["applicant_id"],
        school_name="Prairie CDL Academy",
        tuition_total_cents=115205,
        commitment_months=12,
    )
    assert agreement["status"] == "PENDING"

    activated = validate_success(api.activate_tuition_agreement(agreement["id"], SCHOOL))

    assert activated["forgiven_cents"] == 5
    assert activated["outstanding_cents"] == 115200
    assert activated["reimbursed_cents"] == 0
    assert activated["clawback_cents"] == 0
    assert activated["months_served"] == 0
    assert activated["status"] == "ACTIVE"
    assert_tuition_cents_identity(activated)
