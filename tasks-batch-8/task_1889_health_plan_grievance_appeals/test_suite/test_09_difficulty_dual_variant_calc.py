"""Difficulty queue: dual-variant calculations (PRD §3.7, §3.9).

Two variants of the same calculation must produce observably different results
on identical inputs.
"""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    CLOCK_DEFAULT_ISO,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    make_case_analyst_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, request_clinical_review,
    walk_review_to_determined, decide_case_clinical, get_case_effectuation,
    start_effectuation, get_effectuation_fresh, link_case_to_ctm,
    get_ctm_exposure, get_member_fresh, setup_member_with_ctm_cases,
    seed_standard_grievance_policy, seed_standard_appeal_policy,
    decide_grievance_from_in_review, create_in_review_case,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_decided_appeal_with_effectuation():
    """MEDICARE APPEAL decided FULLY_FAVORABLE at 2026-08-02T00:00:00Z with a
    72h effectuation window; returns (case, effectuation)."""
    member = create_member("MBR-DV1", full_name="Dora Vance", program="MEDICARE")
    provider = create_provider("1234567893", legal_name="Vance Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=168,
                  extension_hours=24, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-dv1"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-001",
                              factors={"severity": 8, "acuity": 6,
                                       "guideline_match": 9, "comorbidity": 4,
                                       "functional_impairment": 5},
                              determination="OVERTURN_SERVICE")
    set_clock("2026-08-02T00:00:00Z")
    case = decide_case_clinical(case["id"], decision_outcome="FULLY_FAVORABLE",
                                payment_amount_cents=50000,
                                decider_id="md-002")
    effectuation = get_case_effectuation(case["id"])
    return case, effectuation


def test_effectuation_timeliness_calendar_variant_value(api):
    """PRD §3.7: "The timeliness percentage measures window consumption: one hundred times
    the consumed hours divided by the window hours, where the window runs
    from the case's `decided_at` to its `effectuation_due_at` and the
    consumed hours run from `decided_at` to the effectuation's
    `completed_at`, the result rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/effectuation_timeliness_calendar_vs_business_hours
    """
    case, eff = _setup_decided_appeal_with_effectuation()
    start_effectuation(eff["id"])
    set_clock("2026-08-04T12:00:00Z")
    fresh = get_effectuation_fresh(eff["id"])
    data = validate_success(api.complete_effectuation(
        eff["id"], {"expected_effectuation_version": fresh["version"]}, CLAIMS))
    # decided 2026-08-02T00:00, completed 2026-08-04T12:00 -> 60h of 72h window.
    assert data["timeliness_percent"] == 83.33, (
        f"Expected 83.33 (60h/72h calendar variant), got {data['timeliness_percent']}")
    assert data["status"] == "EFFECTUATED"


def test_effectuation_timeliness_calendar_variant_not_business_hours(api):
    """PRD §3.7: "One calculation variant matters for Medi-Cal service-only work: when the
    governing Deadline Policy carries `business_hours_only` set to `true`,
    the consumed hours count only Monday-through-Friday 08:00–17:00 UTC
    hours, so the same wall-clock interval yields a smaller
    `timeliness_percent` than the default calendar-hours variant."
    A MEDICARE policy leaves business_hours_only at its default false, so the
    full wall-clock interval is consumed; under the business-hours variant
    the same interval would count only Mon-Fri 08:00-17:00 UTC hours.

    Design: Difficulty/dual_variant_calc/effectuation_timeliness_calendar_vs_business_hours
    """
    case, eff = _setup_decided_appeal_with_effectuation()
    start_effectuation(eff["id"])
    # Complete at a wall-clock point whose business-hours tally (Mon 08:00-17:00
    # = 9h plus Tue 08:00-12:00 = 4h, 13h total -> ~18.06) would be far
    # smaller than the calendar tally (60h -> 83.33).
    set_clock("2026-08-04T12:00:00Z")
    fresh = get_effectuation_fresh(eff["id"])
    data = validate_success(api.complete_effectuation(
        eff["id"], {"expected_effectuation_version": fresh["version"]}, CLAIMS))
    assert data["timeliness_percent"] > 50.0, (
        "Calendar-hours variant must consume the full 60h; a business-hours "
        "variant would count only 13h (Mon 08:00-17:00 + Tue 08:00-12:00) "
        "and yield ~18.06")
    assert data["timeliness_percent"] == 83.33


def _setup_two_ctm_linked_cases():
    member = create_member("MBR-DV2", full_name="Carl Myles", program="MEDICARE")
    provider = create_provider("1093817465", legal_name="Myles Clinic",
                               w9_on_file=True)
    set_clock(CLOCK_DEFAULT_ISO)
    case_a = intake_case(member["id"], case_kind="GRIEVANCE",
                         provider_id=provider["id"])
    link_case_to_ctm(case_a["id"], body="ctm-1")
    case_b = intake_case(member["id"], case_kind="APPEAL",
                         provider_id=provider["id"])
    link_case_to_ctm(case_b["id"], body="ctm-2")
    return member, case_a, case_b


def test_ctm_provisional_half_weight_pre_triage(api):
    """PRD §3.9: "Provisional weighting handles the pre-classification window: a case linked
    while still in `RECEIVED` — before triage confirms its classification
    — counts at half weight, 0.5, and the tier thresholds then compare
    against the ceiling of the total provisional weight; after triage the
    identical link counts at full weight, so the same data can yield a
    different tier before and after triage."

    Design: Difficulty/dual_variant_calc/ctm_provisional_vs_final_weight_tier_flip
    """
    member, _a, _b = _setup_two_ctm_linked_cases()
    exposure = get_ctm_exposure(member["id"])
    # Two RECEIVED links x 0.5 = 1.0 total provisional weight; ceil(1.0)=1 -> LOW.
    assert exposure["provisional_weight"] == 1.0
    assert exposure["tier"] == "LOW"
    assert exposure["ctm_linked_case_count"] == 2


def test_ctm_full_weight_after_triage(api):
    """PRD §3.9: "Provisional weighting handles the pre-classification window: a case linked
    while still in `RECEIVED` — before triage confirms its classification
    — counts at half weight, 0.5, and the tier thresholds then compare
    against the ceiling of the total provisional weight; after triage the
    identical link counts at full weight, so the same data can yield a
    different tier before and after triage."

    Design: Difficulty/dual_variant_calc/ctm_provisional_vs_final_weight_tier_flip
    """
    member, case_a, case_b = _setup_two_ctm_linked_cases()
    seed_standard_grievance_policy("MEDICARE")
    seed_standard_appeal_policy("MEDICARE", resolution_hours=168,
                                extension_hours=24)
    triage_case(case_a["id"])
    triage_case(case_b["id"])
    exposure = get_ctm_exposure(member["id"])
    # Both links now count at full weight: total 2.0, count 2 in the 1..2 band.
    assert exposure["provisional_weight"] == 2.0
    assert exposure["tier"] == "LOW"
    assert exposure["ctm_linked_case_count"] == 2
    assert get_member_fresh(member["id"])["ctm_linked_case_count"] == 2


def _setup_late_grievance_for_audit():
    """GRIEVANCE received at 2026-08-01T00:00, triaged within the ack window,
    decided UNFAVORABLE at 2026-08-08T01:00 (+169h vs a 168h policy)."""
    member = create_member("MBR-DV3", full_name="Ari Gold", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=168,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    set_clock("2026-08-08T01:00:00Z")
    case = decide_grievance_from_in_review(case["id"],
                                           decision_outcome="UNFAVORABLE")
    return member, case


def test_audit_universe_raw_snapshot_marks_late_case(api):
    """PRD §3.9: "Each resulting Audit Universe Record denormalizes the case's `case_kind`
    and `priority_track` at snapshot time, stamps `snapshot_at`, and
    records two booleans: `resolution_timely`, true when `decided_at` was
    on or before `resolution_due_at` — equality is timely — and
    `effectuation_timely`, true when the linked effectuation's
    `completed_at` was on or before the case's `effectuation_due_at`, and
    null when no effectuation was required."

    Design: Difficulty/dual_variant_calc/audit_universe_raw_vs_compliance_attribution_rate
    """
    member, case = _setup_late_grievance_for_audit()
    result = get_success_data(api.create_audit_snapshot(
        {"report_period": "2026-08"}, COMPLIANCE), expected_status=201)
    assert result["rows_created"] == 1
    rows = get_success_data(api.list_audit_universe(
        COMPLIANCE, params={"report_period": "2026-08"}))
    assert len(rows) == 1
    assert rows[0]["case_id"] == case["id"]
    # decided at +169h against a 168h policy: the raw snapshot marks it late.
    assert rows[0]["resolution_timely"] is False


def test_audit_universe_compliance_attribution_keeps_reviewer_lateness(api):
    """PRD §3.9: "The attribution rule separates intake lateness from reviewer lateness: a
    case that missed its resolution deadline solely because its
    acknowledgement ran past the 24-hour window of §3.3 is attributed to
    intake delay and excluded from the reviewer-lateness numerator,
    whereas the raw snapshot variant counts the identical case as simply
    late — the two views of the same data therefore produce different
    timeliness rates, deliberately."

    Design: Difficulty/dual_variant_calc/audit_universe_raw_vs_compliance_attribution_rate
    """
    member, case = _setup_late_grievance_for_audit()
    get_success_data(api.create_audit_snapshot(
        {"report_period": "2026-08"}, COMPLIANCE), expected_status=201)
    summary = get_success_data(api.get_compliance_summary(
        COMPLIANCE, params={"report_period": "2026-08"}))
    assert summary["total_cases"] == 1
    assert summary["resolution_timely_count"] == 0
    # Acknowledgement was within the 24h window, so the lateness stays on the
    # reviewer in the compliance-attribution variant.
    assert summary["intake_delay_count"] == 0
    assert summary["reviewer_late_count"] == 1
