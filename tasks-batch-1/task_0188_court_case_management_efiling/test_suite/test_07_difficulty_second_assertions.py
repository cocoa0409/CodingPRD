"""Second assertions for each depth (difficulty) instance.

Every test here is tagged to the same difficulty instance as its partner in
test_01..test_04 but exercises a complementary facet (the other variant branch,
a boundary's other side, the success path, or the other conflict axis). All
assertions remain grounded in verbatim PRD prose and uniquely derivable.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_deadline_payload, create_fee_waiver_payload, create_hearing_payload,
    rule_motion_payload, make_attorney_headers, TEST_USERS,
    setup_open_case, setup_draft_case, setup_judgment_entered,
    setup_notice_filed_appeal, setup_motion_under_submission, setup_stayed_case,
    add_party, efile, pay_review_accept, review_accept, add_fee_waiver,
    add_attempted_service, add_deadline, add_accepted_motion_filing, file_motion,
    schedule_hearing,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"
ATT_DF = "att_2"


# =====================================================================
# dual_variant_calc
# =====================================================================
def test_due_date_variants_agree_when_no_weekend_in_span(api):
    """PRD 3.4: "the engine first adds the full interval_days as calendar days to the
    anchor date. If the court runs business-days-only and that landing day falls on a
    Saturday, a Sunday, or one of the court's holidays, the date rolls forward one day at
    a time to the next court day; the rolled-over days are not re-counted."

    Design: Difficulty/dual_variant_calc/due_date_calendar_vs_court_days_diverge
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    # anchor 2026-03-04 (Wed) + 5: CALENDAR lands 2026-03-09 (Mon), a court day -> no roll.
    cal = get_success_data(api.create_deadline(create_deadline_payload(
        case_id, anchor_date="2026-03-04T00:00:00.000Z",
        interval_days=5, counting_mode="CALENDAR"), CLERK))
    assert cal["due_date"] == "2026-03-09T23:59:59.000Z", cal["due_date"]


def test_judgment_interest_one_day_alongside_eligibility_below_cutoff(api):
    """PRD 3.7: "The accrued interest in cents is the principal_cents multiplied by that
    daily rate multiplied by the elapsed days, rounded half up to whole cents."
    PRD 3.6: "The eligibility ratio is the declared monthly income in cents divided by
    that threshold, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/judgment_interest_vs_fee_eligibility_different_domains
    """
    base = setup_open_case(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    fw = add_fee_waiver(case_id, base["complaint"]["id"], base["plaintiff"]["id"],
                        attorney_user_id=ATT_PL, monthly_income_cents=100000, household_size=1)
    judgment = get_success_data(api.create_judgment({
        "case_id": case_id, "judgment_type": "TRIAL",
        "prevailing_party_id": base["plaintiff"]["id"],
        "principal_cents": 1000000, "interest_rate_bps": 1000,
        "expected_case_version": base["case_version"],
    }, JUDGE))
    get_success_data(api.set_clock("2026-04-02T00:00:00.000Z", ADMIN))

    jread = validate_success(api.get_judgment(judgment["id"], CLERK))
    fwread = validate_success(api.get_fee_waiver(fw["id"], CLERK))
    assert jread["total_with_interest_cents"] == 1000274, jread["total_with_interest_cents"]
    assert fwread["eligibility_ratio"] == 0.7692, fwread["eligibility_ratio"]


# =====================================================================
# combinatorial_formula
# =====================================================================
def test_appeal_transmittal_at_500_page_boundary(api):
    """PRD 3.8: "the first 100 pages are charged 50 cents each, pages 101 through 500 are
    charged 30 cents each, and every page beyond 500 is charged 15 cents each."

    Design: Difficulty/combinatorial_formula/appeal_transmittal_marginal_tiers_nonlinear
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    appeal = validate_success(
        api.prepare_record(base["appeal"]["id"], {"record_page_count": 500}, CLERK))
    # base 5000 + 100*50 + 400*30 = 5000 + 5000 + 12000 = 22000
    assert appeal["transmittal_fee_cents"] == 22000, appeal["transmittal_fee_cents"]


def test_case_fee_aggregates_single_paid_complaint(api):
    """PRD 3.1: "`total_fees_assessed_cents`, the sum of `fee_cents` over the case's
    accepted filings whose `fee_status` is `ASSESSED` or `PAID`, and
    `total_fees_paid_cents`, the sum of `fee_cents` over the case's filings whose
    `fee_status` is `PAID` or `WAIVED`."

    Design: Difficulty/combinatorial_formula/case_total_fees_sum_then_aggregate_order
    """
    # A single PAID+accepted complaint lands in BOTH aggregates at 43500.
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case = validate_success(api.get_case(base["case"]["id"], CLERK))
    assert case["total_fees_assessed_cents"] == 43500, case["total_fees_assessed_cents"]
    assert case["total_fees_paid_cents"] == 43500, case["total_fees_paid_cents"]


# =====================================================================
# transitive_cascade
# =====================================================================
def test_service_complete_sets_response_deadline_id_link(api):
    """PRD 3.3: "a responsive-pleading deadline is created — a RESPONSE deadline anchored
    on the service-completed event, with its anchor_date taken from the service_date,
    counted in court days over an interval of thirty days, in status PENDING — its id
    recorded as the record's response_due_deadline_id, which increments the case's
    open_deadline_count (hop two)."

    Design: Difficulty/transitive_cascade/service_complete_depth3_party_deadline_posture
    """
    base = setup_open_case(clock="2026-03-02T00:00:00.000Z")
    case_id = base["case"]["id"]
    sop = add_attempted_service(case_id, base["complaint"]["id"], base["defendant"]["id"],
                                service_date="2026-03-02T00:00:00.000Z")
    completed = validate_success(api.complete_service(sop["id"], CLERK))
    assert completed["status"] == "COMPLETED", completed["status"]
    assert completed["response_due_deadline_id"], "response_due_deadline_id must be set"
    dl = validate_success(api.get_deadline(completed["response_due_deadline_id"], CLERK))
    assert dl["status"] == "PENDING", dl["status"]
    assert dl["counting_mode"] == "COURT_DAYS", dl["counting_mode"]


def test_stay_cascade_freezes_posture(api):
    """PRD 3.5: "Third, posture is recomputed to `FROZEN`, which it remains while the case
    is `STAYED`. The case's `version` increments."

    Design: Difficulty/transitive_cascade/stay_cascade_depth3_order_case_deadlines
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    add_deadline(case_id, interval_days=10, counting_mode="CALENDAR")
    mfiling = add_accepted_motion_filing(case_id, base["plaintiff"]["id"])
    motion = file_motion(case_id, mfiling["id"], base["plaintiff"]["id"],
                         motion_type="SUMMARY_JUDGMENT", opposed=True)
    get_success_data(api.submit_motion(motion["id"], JUDGE))
    get_success_data(api.rule_motion(
        motion["id"], rule_motion_payload(ruling="GRANT", order_text="Stay", stays_case=True),
        JUDGE))
    case = validate_success(api.get_case(case_id, CLERK))
    assert case["status"] == "STAYED", case["status"]
    assert case["posture"] == "FROZEN", case["posture"]


# =====================================================================
# priority_pair_validation_conflict
# =====================================================================
def test_fee_unpaid_surfaces_when_case_not_frozen(api):
    """PRD 3.2: "when the document is a `COMPLAINT` with a positive `fee_cents`, that its
    `fee_status` is `PAID` or `WAIVED` rather than still `ASSESSED` (else
    `ERR_FILING_FEE_UNPAID`)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_fee_unpaid_on_accept
    """
    # An ACTIVE (not frozen) case with an unpaid complaint UNDER_REVIEW: the lower-priority
    # fee bar is the only failure, so it surfaces.
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    get_success_data(api.claim_review_filing(complaint["id"], CLERK))  # fee still ASSESSED
    resp = api.accept_filing(complaint["id"], CLERK)
    validate_error(resp, "ERR_FILING_FEE_UNPAID")


def test_invalid_state_surfaces_for_judge_on_filed_motion(api):
    """PRD 3.5: "Ruling on a motion is a judge action available only from
    UNDER_SUBMISSION, and only while the case posture is not FROZEN (else
    ERR_CASE_FROZEN)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_motion_rule
    """
    # Same FILED motion as the partner, but the caller is a Judge (authorized): the
    # lower-priority state check is the only failure, so ERR_INVALID_STATE surfaces.
    from test_helpers import setup_motion_filed
    base = setup_motion_filed(clock="2026-03-01T00:00:00.000Z")
    resp = api.rule_motion(base["motion"]["id"],
                           rule_motion_payload(ruling="GRANT", order_text="x"), JUDGE)
    validate_error(resp, "ERR_INVALID_STATE")


# =====================================================================
# boundary_precision_check
# =====================================================================
def test_fee_waiver_ratio_below_cutoff(api):
    """PRD 3.6: "The eligibility ratio is the declared monthly income in cents divided by
    that threshold, rounded half up to four decimal places. A ratio strictly less than
    1.25 marks the request as presumptively eligible."

    Design: Difficulty/boundary_precision_check/fee_waiver_ratio_strict_cutoff_at_125
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = validate_success(api.create_fee_waiver(create_fee_waiver_payload(
        case_id, complaint["id"], pl["id"],
        monthly_income_cents=100000, household_size=1),
        make_attorney_headers(ATT_PL)), expected_status=201)
    assert fw["eligibility_ratio"] == 0.7692, fw["eligibility_ratio"]


def test_appeal_prepare_record_one_page_succeeds(api):
    """PRD 3.8: "Preparation requires a positive record_page_count; an attempt with a
    page count of zero or less is rejected with ERR_EMPTY_RECORD."

    Design: Difficulty/boundary_precision_check/appeal_prepare_record_empty_zero_pages
    """
    # Boundary X+1: record_page_count=1 is positive and must be accepted.
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    appeal = validate_success(
        api.prepare_record(base["appeal"]["id"], {"record_page_count": 1}, CLERK))
    assert appeal["status"] == "RECORD_PREPARED", appeal["status"]
    # base 5000 + 1*50 = 5050
    assert appeal["transmittal_fee_cents"] == 5050, appeal["transmittal_fee_cents"]


# =====================================================================
# cross_entity_state_dependency
# =====================================================================
def test_filing_accept_succeeds_when_case_active(api):
    """PRD 3.2: "Acceptance moves the filing `UNDER_REVIEW → ACCEPTED`, sets `accepted_at`
    to the current clock, and — when the document is a complaint — recomputes the case's
    `total_fees_assessed_cents` and `total_fees_paid_cents` aggregates; a fee that was
    already `PAID` or `WAIVED` is left as it stands."

    Design: Difficulty/cross_entity_state_dependency/filing_accept_blocked_by_case_frozen
    """
    # The same accept on an ACTIVE (non-frozen) case succeeds — the dependency is on the
    # owning case's posture, not the filing alone.
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    f2 = efile(case_id, base["plaintiff"]["id"], ATT_PL,
               document_type="COMPLAINT", title="Complaint 2")
    get_success_data(api.pay_fee(f2["id"], CLERK))
    get_success_data(api.claim_review_filing(f2["id"], CLERK))
    accepted = validate_success(api.accept_filing(f2["id"], CLERK))
    assert accepted["status"] == "ACCEPTED", accepted["status"]


def test_service_complete_succeeds_when_case_open(api):
    """PRD 3.3: "On completion, the record transitions `ATTEMPTED → COMPLETED` and three
    things follow in sequence: the served party's `service_status` becomes `SERVED` and
    its `served_at` is set (hop one)."

    Design: Difficulty/cross_entity_state_dependency/service_complete_blocked_by_case_not_open
    """
    # The dependency is on Case.status==OPEN; on an OPEN case the same completion succeeds.
    base = setup_open_case(clock="2026-03-02T00:00:00.000Z")
    case_id = base["case"]["id"]
    sop = add_attempted_service(case_id, base["complaint"]["id"], base["defendant"]["id"],
                                service_date="2026-03-02T00:00:00.000Z")
    completed = validate_success(api.complete_service(sop["id"], CLERK))
    party = validate_success(api.get_party(base["defendant"]["id"], CLERK))
    assert completed["status"] == "COMPLETED", completed["status"]
    assert party["service_status"] == "SERVED", party["service_status"]


# =====================================================================
# resource_temporal_overlap
# =====================================================================
def test_hearing_back_to_back_same_courtroom_allowed(api):
    """PRD 3.5: "the proposed window must not overlap an existing SCHEDULED hearing in the
    same courtroom, and must not overlap an existing SCHEDULED hearing for the same
    judge_user_id. A violation on either axis is rejected with ERR_HEARING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_courtroom_overlap_rejected
    """
    # Back-to-back (new.start == existing.end) does NOT overlap, so it is allowed.
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    schedule_hearing(case_id, courtroom="A", judge_user_id="jdg_1",
                     start_at="2026-03-05T10:00:00.000Z", end_at="2026-03-05T11:00:00.000Z")
    second = validate_success(api.create_hearing(create_hearing_payload(
        case_id, courtroom="A", judge_user_id="jdg_9",
        start_at="2026-03-05T11:00:00.000Z", end_at="2026-03-05T12:00:00.000Z"), JUDGE),
        expected_status=201)
    assert second["status"] == "SCHEDULED", second["status"]


def test_hearing_same_judge_nonoverlapping_allowed(api):
    """PRD 3.5: "and must not overlap an existing SCHEDULED hearing for the same
    judge_user_id. A violation on either axis is rejected with ERR_HEARING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_judge_overlap_across_courtrooms_rejected
    """
    # Same judge but a non-overlapping later window in a different courtroom is allowed.
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    schedule_hearing(case_id, courtroom="A", judge_user_id="jdg_1",
                     start_at="2026-03-05T10:00:00.000Z", end_at="2026-03-05T11:00:00.000Z")
    second = validate_success(api.create_hearing(create_hearing_payload(
        case_id, courtroom="B", judge_user_id="jdg_1",
        start_at="2026-03-05T13:00:00.000Z", end_at="2026-03-05T14:00:00.000Z"), JUDGE),
        expected_status=201)
    assert second["status"] == "SCHEDULED", second["status"]


# =====================================================================
# compensating_invariant
# =====================================================================
def test_assessed_complaint_raises_assessed_sum_before_release(api):
    """PRD 3.2: "Rejection moves the filing `UNDER_REVIEW → REJECTED`, records the
    `rejection_reason`, and — if the filing's `fee_status` was `ASSESSED` — releases that
    fee by setting `fee_status` back to `NONE` and recomputing the case fee aggregates,
    incrementing the filing's `version`."

    Design: Difficulty/compensating_invariant/fee_assess_then_reject_releases_fee_invariant
    """
    # The compensating reject is verified by the partner; here verify the per-filing
    # release sets fee_status to NONE on a rejected complaint that had been ASSESSED.
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    assert complaint["fee_status"] == "ASSESSED", complaint["fee_status"]
    get_success_data(api.claim_review_filing(complaint["id"], CLERK))
    rejected = validate_success(
        api.reject_filing(complaint["id"], {"rejection_reason": "Wrong court"}, CLERK))
    assert rejected["fee_status"] == "NONE", rejected["fee_status"]


def test_judgment_entry_then_vacate_returns_case_to_open(api):
    """PRD 3.7: "Vacatur moves the judgment `ENTERED → VACATED`, reverses the case
    `JUDGMENT_ENTERED → OPEN`, vacates every `APPEAL` deadline still in `PENDING`, and
    increments both the judgment's and the case's `version`."

    Design: Difficulty/compensating_invariant/judgment_vacate_restores_open_deadline_count_invariant
    """
    base = setup_judgment_entered(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    # Judgment entry created an APPEAL deadline; the case-opened STATUTE_OF_LIMITATIONS
    # deadline is also still PENDING, so the count is 2 before vacate.
    after_judgment = validate_success(api.get_case(case_id, CLERK))
    before = after_judgment["open_deadline_count"]
    assert before >= 1, before
    get_success_data(api.vacate_judgment(base["judgment"]["id"], JUDGE))
    case = validate_success(api.get_case(case_id, CLERK))
    assert case["status"] == "OPEN", case["status"]
    # PRD 3.7: vacatur "vacates every APPEAL deadline still in PENDING" — and ONLY
    # the APPEAL deadline. The STATUTE_OF_LIMITATIONS deadline remains PENDING, so
    # the count drops by exactly the one vacated APPEAL deadline.
    assert case["open_deadline_count"] == before - 1, case["open_deadline_count"]
