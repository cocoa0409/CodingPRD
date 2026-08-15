"""Corner queue: calculation claims (PRD §2.6, §3.3, §3.4, §3.5, §3.9)."""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    CLOCK_DEFAULT_ISO, assert_same_instant, api_client,
    TEST_USERS, make_medical_director_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    request_clinical_review, decide_grievance_from_in_review,
    create_notification_payload, ALL_DECISION_ELEMENTS,
    create_clinical_factors_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _setup_assigned_review(member_ref, npi, reviewer_id):
    """APPEAL in PENDING_CLINICAL with an ASSIGNED review. Returns review."""
    member = create_member(member_ref, full_name="Calc", program="MEDICARE")
    provider = create_provider(npi, legal_name="Calc Clinic", w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"])
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    get_success_data(api_client.assign_clinical_review(
        review["id"], {"reviewer_physician_id": reviewer_id},
        make_medical_director_headers("md-admin")))
    return review


def test_medical_necessity_weighted_sum_known_inputs(api):
    """PRD §3.4: "The weighted raw score takes 35 percent of `severity`, 25 percent of
    `acuity`, 20 percent of `guideline_match`, 10 percent of
    `comorbidity`, and 10 percent of `functional_impairment`; that sum is
    multiplied by ten and rounded half-up to two decimal places exactly
    once, after the summation, producing the `medical_necessity_score`
    between 0.00 and 100.00."

    Design: Corner/calculations/medical_necessity_weighted_sum_known_inputs
    """
    review = _setup_assigned_review("MBR-CA1", "1020304050", "md-801")
    data = validate_success(api.draft_determination(
        review["id"],
        create_clinical_factors_payload(severity=8, acuity=6,
                                        guideline_match=9, comorbidity=4,
                                        functional_impairment=5),
        make_medical_director_headers("md-801")))
    # 0.35*8 + 0.25*6 + 0.20*9 + 0.10*4 + 0.10*5 = 7.0; x10 -> 70.00.
    assert data["medical_necessity_score"] == 70.00


def test_medical_necessity_physician_override_rounds_and_stores(api):
    """PRD §3.4: "A physician override exists for the exceptional case: when the draft
    payload includes `override_score`, the stored
    `medical_necessity_score` is the override value rounded half-up to two
    decimals and clamped to the range from 0.00 to 100.00; the weighted
    formula result is retained in the draft's audit body even though the
    override is what gets stored."

    Design: Corner/calculations/medical_necessity_physician_override_clamps
    """
    review = _setup_assigned_review("MBR-CA2", "1122334455", "md-802")
    payload = create_clinical_factors_payload(
        severity=8, acuity=6, guideline_match=9, comorbidity=4,
        functional_impairment=5)
    payload["override_score"] = 88.555
    data = validate_success(api.draft_determination(
        review["id"], payload, make_medical_director_headers("md-802")))
    # round_half_up(88.555, 2) == 88.56; the weighted 70.00 is NOT stored.
    assert data["medical_necessity_score"] == 88.56


def _decide_grievance_at(member, decide_at):
    """Create + triage + begin-review + decide UNFAVORABLE at ``decide_at``."""
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    set_clock(decide_at)
    return decide_grievance_from_in_review(case["id"],
                                           decision_outcome="UNFAVORABLE")


def test_audit_universe_half_open_period_window(api):
    """PRD §3.9: "A `ComplianceOfficer` builds it for a `report_period` keyed in `YYYY-MM`
    form; the snapshot includes every case whose `decided_at` falls inside
    the half-open period window — inclusive of the period's first instant,
    exclusive of the next period's first instant — and cases that were
    never decided are excluded entirely."

    Design: Corner/calculations/audit_universe_half_open_period_boundary
    """
    member = create_member("MBR-CA3", full_name="Half Open",
                           program="MEDICARE")
    # Case B rides on a second member: both intakes stamp received_at at the
    # default clock, and an identical intake (same member/kind/provider)
    # within one hour is a duplicate (PRD §3.2).
    member_b = create_member("MBR-CA3B", full_name="Half Open B",
                             program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    # Case A decided at 2026-08-31T23:59:59Z: inside 2026-08 (inclusive start).
    case_a = _decide_grievance_at(member, "2026-08-31T23:59:59Z")
    # Case B decided at 2026-09-01T00:00:00Z: the exclusive end, outside.
    _decide_grievance_at(member_b, "2026-09-01T00:00:00Z")
    result = get_success_data(api.create_audit_snapshot(
        {"report_period": "2026-08"}, COMPLIANCE), expected_status=201)
    assert result["rows_created"] == 1
    rows = get_success_data(api.list_audit_universe(
        COMPLIANCE, params={"report_period": "2026-08"}))
    assert len(rows) == 1
    assert rows[0]["case_id"] == case_a["id"]


def test_audit_universe_snapshot_order_decided_at_then_created_at(api):
    """PRD §3.9: "Rows are captured in deterministic order: `decided_at` ascending, then
    `created_at` ascending, never by `id`."

    Design: Corner/calculations/audit_universe_snapshot_order_deterministic
    """
    member = create_member("MBR-CA4", full_name="Sort Order",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-10T00:00:00Z")
    case_a = intake_case(member["id"], case_kind="GRIEVANCE")
    # +2h: outside the duplicate-intake guard's one-hour look-back (PRD §3.2)
    # and gives case_b a later created_at, so the PRD's decided_at-then-
    # created_at ordering (not id) is what places case_a first.
    set_clock("2026-08-10T02:00:00Z")
    case_b = intake_case(member["id"], case_kind="GRIEVANCE")
    triage_case(case_a["id"])
    begin_review(case_a["id"])
    triage_case(case_b["id"])
    begin_review(case_b["id"])
    # Both decided at the same second; created_at breaks the tie.
    set_clock("2026-08-10T12:00:00Z")
    decide_grievance_from_in_review(case_a["id"], decision_outcome="UNFAVORABLE")
    decide_grievance_from_in_review(case_b["id"], decision_outcome="UNFAVORABLE")
    get_success_data(api.create_audit_snapshot(
        {"report_period": "2026-08"}, COMPLIANCE), expected_status=201)
    rows = get_success_data(api.list_audit_universe(
        COMPLIANCE, params={"report_period": "2026-08"}))
    assert [row["case_id"] for row in rows[:2]] == [case_a["id"], case_b["id"]], (
        "decided_at ties must be broken by created_at ascending, never by id")


def test_notification_completeness_full_score_is_one(api):
    """PRD §3.5: "Each required element carries a fixed weight: `citation_of_criteria` at
    0.25, `appeal_rights` at 0.25, `decision_rationale` at 0.20,
    `expedited_availability` at 0.10, `ire_notice` at 0.10,
    `contact_information` at 0.05, and `language_assistance` at 0.05, the
    weights summing to exactly 1.00."

    Design: Corner/calculations/notification_completeness_full_score_is_one
    """
    member = create_member("MBR-CA5", full_name="Full Score",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE")["id"],
        decision_outcome="UNFAVORABLE")
    data = validate_success(api.create_notification(
        case["id"],
        create_notification_payload(
            supplied_elements=list(ALL_DECISION_ELEMENTS)),
        MSR), expected_status=201)
    assert data["completeness_score"] == 1.00


def test_extension_adds_policy_extension_hours(api):
    """PRD §3.3: "Granting sets `extension_applied` to `true`, recomputes
    `resolution_due_at` as the previously computed deadline plus the
    policy's extension hours, appends an `EXTENSION_GRANTED` event, and
    increments the case's `version`."

    Design: Corner/calculations/case_deadline_extension_adds_policy_hours
    """
    member = create_member("MBR-CA6", full_name="Ext Calc", program="MEDICARE")
    provider = create_provider("6677889900", legal_name="Ext Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=168,
                  extension_hours=24, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triaged = triage_case(case["id"])
    assert_same_instant(triaged["resolution_due_at"], "2026-08-08T00:00:00Z")
    data = validate_success(api.extend_case(
        case["id"], {"expected_case_version": triaged["version"]}, MSR))
    assert data["extension_applied"] is True
    # 168h + 24h from received_at 2026-08-01T00:00:00Z.
    assert_same_instant(data["resolution_due_at"], "2026-08-09T00:00:00Z")
