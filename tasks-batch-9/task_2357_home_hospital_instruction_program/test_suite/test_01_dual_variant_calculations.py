"""Two named variants of the same quantity, computed from identical inputs.

Each test in this module drives one pair of readings — provisional against
final-verified apportionment, per-session rounded credit against the unrounded
weekly projection, and the self-reported against the onsite-verified risk score
— and pins the divergence the PRD requires between them.
"""

from test_helpers import (
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    MIDDLE_VIRTUAL_RULE,
    PA_HEADERS,
    api_client,
    finalize_safety_review,
    ledger_entries_for_case,
    log_session_delivered,
    open_case,
    read_case,
    read_session,
    record_safety_review,
    register_student,
    review_certification,
    schedule_session,
    set_clock,
    setup_active_case,
    setup_catalogue,
    submit_certification,
    validate_success,
    verify_session,
)

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}


def _case_with_four_verified_in_home_sessions() -> dict:
    """An ACTIVE / ACCRUING case whose four verified 120-minute sessions all sit
    inside one ISO week, with the clock parked at 2026-09-20T00:00:00Z."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review={"hazard_findings": ["UNLIT_ACCESS"], "escort_available": False},
    )
    slots = [
        ("2026-09-07T09:00:00Z", "2026-09-07T11:00:00Z", "MATH"),
        ("2026-09-07T13:00:00Z", "2026-09-07T15:00:00Z", "ELA"),
        ("2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z", "MATH"),
        ("2026-09-08T13:00:00Z", "2026-09-08T15:00:00Z", "ELA"),
    ]
    sessions = [
        schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject=subject,
        )
        for start, end, subject in slots
    ]
    set_clock("2026-09-09T18:00:00Z")
    for session in sessions:
        log_session_delivered(session["id"], bundle["teacher"]["id"], 120)
    for session in sessions:
        verify_session(session["id"])
    set_clock("2026-09-20T00:00:00Z")
    bundle["sessions"] = sessions
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _virtual_case_with_two_seventy_five_minute_sessions() -> dict:
    """An ACTIVE virtual case with two 90-minute slots each delivered for 75
    reported minutes, logged at 2026-09-09T18:00:00Z."""
    bundle = setup_active_case(
        rules=[MIDDLE_VIRTUAL_RULE],
        student={
            "student_number": "S-0003",
            "full_name": "Ivo Park",
            "grade_level": 8,
            "campus_code": "MS-02",
        },
        case={"delivery_mode": "VIRTUAL_SYNC"},
        certification=dict(CERT_WINDOW),
        include_safety_review=False,
    )
    slots = [
        ("2026-09-07T09:00:00Z", "2026-09-07T10:30:00Z", "MATH"),
        ("2026-09-07T10:40:00Z", "2026-09-07T12:10:00Z", "ELA"),
    ]
    sessions = [
        schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="VIRTUAL_SYNC",
            subject=subject,
        )
        for start, end, subject in slots
    ]
    set_clock("2026-09-09T18:00:00Z")
    bundle["sessions"] = [
        log_session_delivered(session["id"], bundle["teacher"]["id"], 75)
        for session in sessions
    ]
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def _two_eligible_cases_with_identical_hazards() -> dict:
    """Two grade-7 in-home cases, each ELIGIBLE at 390 weekly minutes, carrying
    the same three hazards and an available escort but different evidence."""
    rules = setup_catalogue(rules=[MIDDLE_IN_HOME_RULE, MIDDLE_VIRTUAL_RULE])
    hazards = {
        "hazard_findings": ["AGGRESSIVE_ANIMAL", "NO_SECONDARY_EXIT", "UNLIT_ACCESS"],
        "escort_available": True,
    }

    student_a = register_student(student_number="S-0001", full_name="Ada Lin")
    case_a = open_case(student_a["id"], delivery_mode="IN_HOME")
    cert_a = submit_certification(case_a["id"], physician_npi="1234567890", **CERT_WINDOW)
    review_certification(cert_a["id"], "ACCEPT")

    student_b = register_student(student_number="S-0002", full_name="Ben Ortiz")
    case_b = open_case(student_b["id"], delivery_mode="IN_HOME")
    cert_b = submit_certification(case_b["id"], physician_npi="1234567891", **CERT_WINDOW)
    review_certification(cert_b["id"], "ACCEPT")

    review_a = record_safety_review(
        case_a["id"], evidence_source="PARENT_ATTESTATION", **hazards
    )
    review_b = record_safety_review(
        case_b["id"], evidence_source="ONSITE_WALKTHROUGH", **hazards
    )
    return {
        "rule_in_home": rules[0],
        "rule_virtual": rules[1],
        "case_a": case_a,
        "case_b": case_b,
        "review_a": review_a,
        "review_b": review_b,
    }


class TestProvisionalVersusFinalVerifiedApportionment:
    """The two apportionment variants and the cap scope that separates them."""

    def test_provisional_total_is_capped_once_over_the_whole_certified_window(self):
        """Four 120-minute delivered sessions sum to 480 provisional minutes because
        the provisional cap is 390 weekly minutes times five window weeks.

        The PRD states: "Those contributions are summed into a raw provisional
        total, and the total is capped once — over the whole certified window
        rather than week by week — at the case's `weekly_entitled_minutes`
        multiplied by the number of window weeks, where window weeks is the number
        of days separating `service_start_date` from `certified_end_date`, plus
        one, divided by seven and rounded up to a whole week."

        Design: Difficulty/dual_variant_calc/provisional_accrual_vs_final_verified_apportionment_diverge_on_weekly_cap
        """
        bundle = _case_with_four_verified_in_home_sessions()
        case_id = bundle["case"]["id"]

        reported = validate_success(api_client.report_case_funding(case_id, PA_HEADERS))
        assert reported["weekly_entitled_minutes"] == 390, (
            "a MEDICAL_ACUTE case on a 360-minute base with a 30-day expected "
            "absence is entitled to 390 weekly minutes"
        )
        assert reported["provisional_apportionment_minutes"] == 480, (
            "the four delivered sessions contribute 120 credited minutes each and "
            "the whole-window cap of 1950 minutes never binds"
        )

        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["window_weeks"] == 5, (
            "2026-09-07 to 2026-10-07 spans 31 days, which is five whole weeks "
            "once rounded up"
        )
        assert summary["provisional_minutes"] == 480, (
            "the funding summary reports the same provisional figure the case holds"
        )

    def test_final_verified_total_is_capped_inside_each_iso_week(self):
        """The identical four sessions yield only 390 final minutes because all four
        fall in one ISO week, a 90-minute divergence from the provisional figure.

        The PRD states: "Because verification is required and because the cap binds
        inside each ISO week rather than across the whole window, the same data
        yields a strictly smaller final figure than the provisional one whenever
        sessions cluster inside a single ISO week or remain unverified."

        Design: Difficulty/dual_variant_calc/provisional_accrual_vs_final_verified_apportionment_diverge_on_weekly_cap
        """
        bundle = _case_with_four_verified_in_home_sessions()
        case_id = bundle["case"]["id"]

        validate_success(api_client.report_case_funding(case_id, PA_HEADERS))
        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["final_verified_minutes"] == 390, (
            "the fourth session in ISO week 37 finds only 30 minutes of room left "
            "under the 390-minute weekly entitlement"
        )
        assert summary["service_weeks"] == 2, (
            "service weeks is the lesser of two elapsed weeks and five window weeks"
        )
        assert summary["entitled_total_minutes"] == 780, (
            "390 weekly minutes across two service weeks"
        )

        reconciled = validate_success(
            api_client.reconcile_case_funding(case_id, PA_HEADERS)
        )
        assert reconciled["final_apportionment_minutes"] == 390
        assert (
            reconciled["provisional_apportionment_minutes"]
            - reconciled["final_apportionment_minutes"]
            == 90
        ), "the cap scope alone accounts for a 90-minute divergence"
        assert reconciled["funding_status"] == "RECONCILED"
        assert reconciled["service_status"] == "ACTIVE", (
            "the funding dimension settles without disturbing the service dimension"
        )


class TestPerSessionRoundingVersusUnroundedProjection:
    """Rounding once per session against rounding once over the whole projection."""

    def test_each_virtual_session_rounds_its_own_credit_to_the_nearest_five(self):
        """Two virtual sessions reported at 75 minutes each credit 70 minutes apiece
        and put 140 minutes on the ledger.

        The PRD states: "take the lesser of the reported `actual_minutes` and the
        rule's `max_session_minutes`; multiply that capped figure by 0.90 when the
        session's `delivery_mode` is `VIRTUAL_SYNC` and leave it unchanged when the
        mode is `IN_HOME`; then divide by five, round half up to a whole number, and
        multiply back by five."

        Design: Difficulty/dual_variant_calc/credited_minutes_per_session_rounding_vs_weekly_unrounded_projection
        """
        bundle = _virtual_case_with_two_seventy_five_minute_sessions()

        for session in bundle["sessions"]:
            assert read_session(session["id"])["credited_minutes"] == 70, (
                "75 minutes discounted to 67.5 rounds half up to 70 in five-minute "
                "steps"
            )
        assert bundle["case"]["reported_apportionment_minutes"] == 140, (
            "the case re-sums its whole attendance ledger after every outcome"
        )

        entries = ledger_entries_for_case(bundle["case"]["id"])
        assert len(entries) == 2, "each logged outcome writes exactly one ledger row"
        for entry in entries:
            assert entry["attendance_code"] == "HB_VIRTUAL_PRESENT"
            assert entry["apportionment_minutes"] == 70, (
                "a ledger row carries the session's credited minutes verbatim"
            )

    def test_projected_unrounded_diagnostic_rounds_once_at_the_end(self):
        """The same two sessions project 135 unrounded minutes against a ledger total
        of 140 — a five-minute rounding-accumulation delta.

        The PRD states: "The `projected_unrounded_minutes` field is the one place in
        the system where per-session rounding is *not* applied first: it sums the
        un-rounded intermediate credit values across all of the case's delivered
        sessions and applies the round-half-up-to-the-nearest-five step exactly once
        at the end."

        Design: Difficulty/dual_variant_calc/credited_minutes_per_session_rounding_vs_weekly_unrounded_projection
        """
        bundle = _virtual_case_with_two_seventy_five_minute_sessions()

        summary = validate_success(
            api_client.get_funding_summary(bundle["case"]["id"], CM_HEADERS)
        )
        assert summary["reported_apportionment_minutes"] == 140
        assert summary["projected_unrounded_minutes"] == 135, (
            "67.5 plus 67.5 is 135, and 135 is already a multiple of five"
        )
        assert (
            summary["reported_apportionment_minutes"]
            - summary["projected_unrounded_minutes"]
            == 5
        ), "rounding each session first accumulates five extra minutes"


class TestSelfReportedVersusOnsiteVerifiedRiskScore:
    """One hazard set, two scoring variants, two clearance bands."""

    def test_parent_attestation_discounts_the_raw_sum_and_ignores_the_escort(self):
        """A parent-attested review of the same three hazards scores 34 and bands
        CLEARED_WITH_ESCORT, leaving the case in-home at 390 weekly minutes.

        The PRD states: "Under `SELF_REPORTED`, the raw sum is multiplied by 0.75,
        rounded half up to a whole point, and then capped at 100; `escort_available`
        is ignored entirely, on the reasoning that a parent attestation cannot vouch
        for an escort arrangement."

        Design: Difficulty/dual_variant_calc/safety_risk_self_reported_versus_onsite_verified_band_split
        """
        bundle = _two_eligible_cases_with_identical_hazards()

        finalized = finalize_safety_review(bundle["review_a"]["id"])
        assert finalized["scoring_variant"] == "SELF_REPORTED"
        assert finalized["risk_score"] == 34, (
            "a raw 45 discounted by 0.75 is 33.75, which rounds half up to 34"
        )
        assert finalized["clearance"] == "CLEARED_WITH_ESCORT", (
            "34 points sits below the 35-point virtual-only lower bound"
        )

        case = read_case(bundle["case_a"]["id"])
        assert case["escort_required"] is True, (
            "escort_required is true exactly when the clearance is "
            "CLEARED_WITH_ESCORT"
        )
        assert case["delivery_mode"] == "IN_HOME", (
            "only a VIRTUAL_ONLY clearance rewrites the case's delivery mode"
        )
        assert case["weekly_entitled_minutes"] == 390, (
            "the in-home entitlement is untouched by this finalization"
        )

    def test_onsite_walkthrough_uses_the_raw_sum_and_forces_the_virtual_mode(self):
        """The onsite review of the same three hazards scores 35, bands VIRTUAL_ONLY,
        and cascades the case onto the virtual rule at 270 weekly minutes.

        The PRD states: "When the resulting `clearance` is `VIRTUAL_ONLY` and the
        case's `delivery_mode` is `IN_HOME` or `HYBRID`, the case's `delivery_mode`
        is rewritten to `VIRTUAL_SYNC`; its `entitlement_rule_id` is re-resolved
        against the student's `grade_band` paired with `VIRTUAL_SYNC`, failing with
        `ERR_NO_PUBLISHED_ENTITLEMENT_RULE` when no published rule covers that pair;
        its `weekly_entitled_minutes` is recomputed per §3.3."

        Design: Difficulty/dual_variant_calc/safety_risk_self_reported_versus_onsite_verified_band_split
        """
        bundle = _two_eligible_cases_with_identical_hazards()

        finalized = finalize_safety_review(bundle["review_b"]["id"])
        assert finalized["scoring_variant"] == "ONSITE_VERIFIED"
        assert finalized["risk_score"] == 35, (
            "a raw 45 less the flat 10 points of escort mitigation is 35"
        )
        assert finalized["clearance"] == "VIRTUAL_ONLY", (
            "35 points meets the inclusive virtual-only lower bound"
        )

        case = read_case(bundle["case_b"]["id"])
        assert case["escort_required"] is False
        assert case["delivery_mode"] == "VIRTUAL_SYNC"
        assert case["entitlement_rule_id"] == bundle["rule_virtual"]["id"], (
            "the case re-resolves against the MIDDLE / VIRTUAL_SYNC published rule"
        )
        assert case["weekly_entitled_minutes"] == 270, (
            "240 base minutes at a 1.00 diagnosis factor plus the 30-minute "
            "mid-duration bonus"
        )
