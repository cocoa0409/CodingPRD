"""The appeal tree and the derived program report."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_pct,
    assert_same_instant,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BILLING_SPECIALIST,
    PROGRAM_ADMIN,
    make_chw_headers,
)


def _denied_june_claim(employee_code, mrn, denied_at="2026-06-20T00:00:00Z"):
    """One 60-minute June encounter locked by a FINAL claim that is then denied."""
    worker, patient, chw_headers = fx.program_with_patient(
        clock=denied_at, employee_code=employee_code,
        mrn=mrn, full_name="Appeal Case", household_size=1,
        monthly_income_cents=80_000,
    )
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
        direct_minutes=50, indirect_minutes=5, travel_minutes=0,
        documentation_minutes=5,
    )
    claim = fx.denied_claim(patient["id"], "2026-06")
    return worker, patient, chw_headers, encounter, claim


def test_an_upheld_appeal_returns_the_minutes_to_the_unfunded_bucket(api):
    """PRD §3.8: "`UPHELD` moves the claim to `UPHELD` and **compensates**:
    every encounter whose `funding_claim_id` names this claim returns from
    `LOCKED` to `SUBMITTED`, with `funding_source` reset to `UNFUNDED` and
    `funding_claim_id` cleared to null, restoring the month's minute
    distribution to exactly what it was before the claim."
    PRD §3.8: "`DENIED` moves the claim to `DENIED`, records the supplied
    `denial_reason`, and stamps `denied_at` with the current logical clock —
    that instant anchors the appeal window — while the encounters likewise stay
    `LOCKED`, pending the appeal."

    Design: Difficulty/compensating_invariant/upheld_appeal_conserves_encounter_minutes_by_funding_source
    """
    worker, patient, chw_headers, encounter, claim = _denied_june_claim(
        "W-025", "MRN-230"
    )
    assert claim["claimed_minutes"] == 60
    assert_cents(claim["allowed_amount_cents"], 8_600, "allowed_amount_cents")
    assert_same_instant(claim["denied_at"], "2026-06-20T00:00:00Z", "claim.denied_at")
    assert fx.read_encounter(encounter["id"])["status"] == "LOCKED"

    fx.set_clock("2026-07-01T00:00:00Z")
    fx.appeal_claim(claim["id"])
    upheld = validate_success(
        api.decide_appeal(claim["id"], {"decision": "UPHELD"}, BILLING_SPECIALIST)
    )
    assert upheld["status"] == "UPHELD"

    freed = fx.read_encounter(encounter["id"])
    assert freed["status"] == "SUBMITTED", (
        f"an upheld denial returns the encounter to SUBMITTED, got {freed['status']}"
    )
    assert freed["funding_source"] == "UNFUNDED"
    assert freed["funding_claim_id"] is None


def test_the_report_shows_the_month_back_in_the_unfunded_bucket(api):
    """PRD §3.10: "The minute figures scope to the requested `service_month` and
    to encounters in `SUBMITTED` or `LOCKED`; `DRAFT` and `VOIDED` encounters
    never count. `payer_minutes` sums `billable_minutes` over those encounters
    whose `funding_source` is `PAYER`, `grant_minutes` over those whose
    `funding_source` is `GRANT`, and `unfunded_minutes` over those whose
    `funding_source` is `UNFUNDED`."
    PRD §2.10: "Furthermore, for every patient-and-service-month pair, the sum
    of `billable_minutes` over that pair's encounters in status `SUBMITTED` or
    `LOCKED` equals the payer-funded total plus the grant-funded total plus the
    unfunded total, where each total sums `billable_minutes` over the encounters
    whose `funding_source` is `PAYER`, `GRANT` and `UNFUNDED` respectively."

    Design: Difficulty/compensating_invariant/upheld_appeal_conserves_encounter_minutes_by_funding_source
    """
    worker, patient, chw_headers, encounter, claim = _denied_june_claim(
        "W-025B", "MRN-230B"
    )

    locked_report = validate_success(
        api.program_summary(
            BILLING_SPECIALIST,
            params={"service_month": "2026-06", "denominator_basis": "ENROLLED_ONLY"},
        )
    )
    assert locked_report["payer_minutes"] == 60, (
        "while the claim holds them, the minutes sit in the payer bucket"
    )
    assert locked_report["unfunded_minutes"] == 0

    fx.set_clock("2026-07-01T00:00:00Z")
    fx.appeal_claim(claim["id"])
    fx.decide_appeal(claim["id"], "UPHELD")

    report = validate_success(
        api.program_summary(
            BILLING_SPECIALIST,
            params={"service_month": "2026-06", "denominator_basis": "ENROLLED_ONLY"},
        )
    )
    assert report["payer_minutes"] == 0, (
        f"the compensation empties the payer bucket, got {report['payer_minutes']}"
    )
    assert report["grant_minutes"] == 0
    assert report["unfunded_minutes"] == 60, (
        f"every minute returns to the unfunded bucket, got {report['unfunded_minutes']}"
    )
    assert report["patient_denominator_count"] == 1


def test_the_appeal_window_is_inclusive_at_sixty_days(api):
    """PRD §3.8: "A `DENIED` claim may be appealed, moving it to `APPEALED` and
    stamping `appealed_at`, provided the elapsed time from `denied_at` to the
    current logical clock is no more than 60 days; exactly 60 days still
    appeals, and beyond that the request is rejected at rung 14 with
    `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/appeal_window_exactly_sixty_days_still_appeals
    """
    worker, patient, chw_headers, encounter, claim = _denied_june_claim(
        "C-037", "MRN-C37", denied_at="2026-06-15T00:00:00Z"
    )
    assert_same_instant(claim["denied_at"], "2026-06-15T00:00:00Z", "claim.denied_at")

    fx.set_clock("2026-08-15T00:00:00Z")
    too_late = api.appeal_claim(claim["id"], BILLING_SPECIALIST)
    validate_error(too_late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 422)

    fx.set_clock("2026-08-14T00:00:00Z")
    on_boundary = validate_success(api.appeal_claim(claim["id"], BILLING_SPECIALIST))

    assert on_boundary["status"] == "APPEALED", (
        f"exactly 60 days still appeals, got {on_boundary['status']}"
    )
    assert_same_instant(
        on_boundary["appealed_at"], "2026-08-14T00:00:00Z", "claim.appealed_at"
    )

    reread = fx.read_encounter(encounter["id"])
    assert reread["status"] == "LOCKED", "the encounter stays locked pending the appeal"
    assert reread["funding_source"] == "PAYER"


def test_the_report_denominator_variants_diverge_after_a_disenrolment(api):
    """PRD §3.10: "The denominator is the report's pivot and its dual variant.
    Under `ENROLLED_ONLY`, it is the set of patients whose `enrollment_status`
    is `ENROLLED`. Under `EVER_ENROLLED`, it is the set of patients whose
    `enrollment_status` is `ENROLLED` **or** `DISENROLLED`. Patients still in
    `PROSPECTIVE` are excluded under both variants."
    PRD §3.10: "`screening_coverage_pct` counts the denominator patients who
    have a screening in `SUBMITTED` or `AMENDED` whose `anchor_screened_at` is
    no more than 365 days before the current logical clock — screenings in
    `SUPERSEDED` never count — then reports 100 multiplied by that count,
    divided by `patient_denominator_count`, rounded half up to one decimal
    place. An empty denominator yields 0.0 rather than a division error."
    PRD §3.10: "It reports 100 multiplied by that count, divided by the number
    of resolved referrals, rounded half up to one decimal place, or 0.0 when no
    referral has resolved."

    Design: Corner/calculations/report_denominator_basis_variants_diverge_after_disenrollment
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    worker = fx.register_worker(employee_code="C-025")
    chw_headers = make_chw_headers(worker["id"])
    instrument = fx.published_instrument(rescreen_cadence_days=90)

    screened = fx.add_patient(
        chw_headers, mrn="MRN-C25", full_name="Screened Enrolled"
    )
    fx.administer_screening(
        chw_headers, screened["id"], instrument["id"],
        domain_scores={"FOOD": 3, "HOUSING": 2, "TRANSPORT": 1},
    )
    unscreened = fx.add_patient(
        chw_headers, mrn="MRN-C26", full_name="Unscreened Disenrolled"
    )
    fx.enroll_patient(unscreened["id"])
    fx.disenroll_patient(unscreened["id"])

    enrolled_only = validate_success(
        api.program_summary(
            PROGRAM_ADMIN,
            params={"service_month": "2026-06", "denominator_basis": "ENROLLED_ONLY"},
        )
    )
    ever_enrolled = validate_success(
        api.program_summary(
            PROGRAM_ADMIN,
            params={"service_month": "2026-06", "denominator_basis": "EVER_ENROLLED"},
        )
    )

    assert enrolled_only["patient_denominator_count"] == 1, (
        "ENROLLED_ONLY counts only the still-enrolled patient, got "
        f"{enrolled_only['patient_denominator_count']}"
    )
    assert_pct(
        enrolled_only["screening_coverage_pct"], 100.0,
        "ENROLLED_ONLY screening_coverage_pct",
    )
    assert ever_enrolled["patient_denominator_count"] == 2, (
        "EVER_ENROLLED keeps the disenrolled patient in the denominator, got "
        f"{ever_enrolled['patient_denominator_count']}"
    )
    assert_pct(
        ever_enrolled["screening_coverage_pct"], 50.0,
        "EVER_ENROLLED screening_coverage_pct",
    )

    for label, report in (("ENROLLED_ONLY", enrolled_only),
                          ("EVER_ENROLLED", ever_enrolled)):
        assert_pct(
            report["referral_loop_closure_pct"], 0.0,
            f"{label} referral_loop_closure_pct with no resolved referral",
        )
        assert report["payer_minutes"] == 0, f"{label} payer_minutes"
        assert report["grant_minutes"] == 0, f"{label} grant_minutes"
        assert report["unfunded_minutes"] == 0, f"{label} unfunded_minutes"
        assert_cents(
            report["travel_reimbursement_monthly_cents"], 0,
            f"{label} travel_reimbursement_monthly_cents",
        )

    assert fx.read_patient(unscreened["id"])["enrollment_status"] == "DISENROLLED"
