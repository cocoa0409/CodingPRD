"""SAR lifecycle: QA rework cycle, deadline branches, filing boundary and
priority conflicts, activity-window overlap, filing cascades, narrative OCC
and segregation of duties (PRD §2.8, §2.9, §2.10, §3.5)."""
from test_helpers import (
    NARRATIVE_CONTINUING,
    NARRATIVE_REWORKED,
    NARRATIVE_SHORT,
    NARRATIVE_STANDARD,
    NARRATIVE_STALE_ATTEMPT,
    NARRATIVE_WINDOW_PROBE,
    ApiErrorId,
    approve_sar,
    assert_case,
    assert_same_instant,
    assert_sar_report,
    create_customer,
    create_sar_draft,
    create_staff,
    drive_case_to_sar_in_progress,
    drive_sar_to_approved,
    first_continuing_review,
    get_success_data,
    make_manager_headers,
    make_qa_reviewer_headers,
    qa_review_case,
    qa_review_sar,
    set_clock,
    setup_deadline_branch_scenario,
    setup_filed_sar,
    setup_risk_cascade_scenario,
    start_and_complete_review,
    submit_sar_for_qa,
    update_narrative_payload,
    validate_error,
    validate_paginated,
    validate_success,
    write_narrative,
)


def test_sar_qa_fail_returns_to_draft_and_recovers_to_filed(api):
    """PRD §3.5: "A fail returns the SAR to `DRAFT`; a pass moves it to
    `QA_PASSED` and stamps `qa_reviewer_id`."
    PRD §3.5: "Approval by a `BSAManager` — again never the drafter — moves the
    SAR from `QA_PASSED` to `APPROVED` and stamps `approved_by_analyst_id`."
    PRD §3.5: "A successful filing sets `filed_at` and assigns a
    `filing_reference` of the form `SAR-<filed year>-<zero-padded sequence>`".

    The SAR machine is cyclic: after QA FAIL the draft is reworked and
    traverses DRAFT -> IN_QA -> QA_PASSED -> APPROVED -> FILED.

    Design: Difficulty/non_linear_state_machine/sar_qa_fail_rework_cycle
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    sar = write_narrative(staff, sar, NARRATIVE_STANDARD)
    sar = submit_sar_for_qa(staff, sar["id"])
    failed = validate_success(api.review_sar_qa(
        sar["id"], {"outcome": "FAIL", "notes": "Narrative omits prior SAR check"},
        staff.qa), 200)
    assert failed["status"] == "DRAFT", "IN_QA -> DRAFT cycle traversed"

    sar = write_narrative(staff, failed, NARRATIVE_REWORKED)
    sar = submit_sar_for_qa(staff, sar["id"])
    sar = qa_review_sar(staff, sar["id"], "PASS")
    assert sar["status"] == "QA_PASSED"
    assert sar["qa_reviewer_id"] == staff.qa_id
    sar = approve_sar(staff, sar["id"])
    assert sar["status"] == "APPROVED"
    filed = validate_success(api.file_sar(sar["id"], staff.manager), 200)
    assert_sar_report(filed)
    assert filed["status"] == "FILED"
    assert_same_instant(filed["filed_at"], "2026-05-01T00:00:00Z",
                        "filed at the default logical clock")
    assert filed["filing_reference"] is not None


def test_sar_filing_cascades_case_and_creates_continuing_review(api):
    """PRD §3.5: "Filing fans out into four cascades. The parent case moves
    from `SAR_IN_PROGRESS` to `PENDING_QA`."
    PRD §3.5: "A `ContinuingReview` is created in `SCHEDULED` against the
    freshly filed SAR, with `due_at` set to `filed_at` plus 90 days and
    `filing_deadline_at` set to `filed_at` plus 120 days; `cycle_number` is 1
    for the first review of a SAR chain root and increments along the
    `prior_sar_id` chain."

    Filed at the default clock 2026-05-01: due_at 2026-07-30, filing deadline
    2026-08-29.

    Design: Difficulty/non_linear_state_machine/sar_qa_fail_rework_cycle
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = drive_sar_to_approved(staff, case["id"])
    validate_success(api.file_sar(sar["id"], staff.manager), 200)

    case_after = validate_success(api.get_case(case["id"], staff.analyst), 200)
    assert_case(case_after)
    assert case_after["status"] == "PENDING_QA", "file cascade on the parent case"

    review = first_continuing_review(staff, sar["id"])
    assert review["status"] == "SCHEDULED"
    assert review["cycle_number"] == 1
    assert_same_instant(review["due_at"], "2026-07-30T00:00:00Z")
    assert_same_instant(review["filing_deadline_at"], "2026-08-29T00:00:00Z")


def test_initial_sar_deadline_identified_subject(api):
    """PRD §2.8: "For an initial SAR (one with no `prior_sar_id`), the deadline
    starts from the parent case's `initial_detection_at` — the `created_at` of
    the earliest alert linked to the case, or the case's own `created_at` if no
    alert is linked — and adds 30 days."

    The case has one LINKED alert created at the default clock 2026-05-01, so
    the filed SAR's deadline is 2026-05-31T00:00:00Z.

    Design: Difficulty/combinatorial_formula/sar_deadline_conditional_branches
    """
    staff = create_staff()
    built = setup_deadline_branch_scenario(staff)
    sar1 = built.sar_identified
    assert_sar_report(sar1)
    assert sar1["status"] == "FILED"
    assert_same_instant(sar1["deadline_at"], "2026-05-31T00:00:00Z")


def test_initial_sar_deadline_unidentified_subject(api):
    """PRD §2.8: "When the subject is unidentified (`subject_unidentified` is
    true), a further 30 days are added, so the outside deadline is 60 days from
    initial detection."

    The second case has no linked alerts (detection == case created_at
    2026-05-01); the unidentified-subject SAR's deadline is
    2026-06-30T00:00:00Z.

    Design: Difficulty/combinatorial_formula/sar_deadline_conditional_branches
    """
    staff = create_staff()
    built = setup_deadline_branch_scenario(staff)
    sar2 = built.sar_unidentified
    assert sar2["subject_unidentified"] is True
    assert_same_instant(sar2["deadline_at"], "2026-06-30T00:00:00Z")


def test_continuing_sar_deadline_from_prior_filing(api):
    """PRD §2.8: "For a continuing-activity SAR, the deadline is simply 120
    days after the `filed_at` of the prior SAR in the chain — 90 days to the
    next review, then a 30-day drafting window on top."
    PRD §3.6: "When the outcome is `FILE_CONTINUING_SAR`, the system creates
    the continuing SAR draft automatically: it links to the reviewed SAR via
    `prior_sar_id` (which flips `is_continuing` to true), inherits the same
    `case_id` and `customer_id`, sets the activity window to start the day
    after the prior SAR's `activity_end_date` and to end 90 days later,
    computes `deadline_at` as the review's `filing_deadline_at` (the prior
    filing plus 120 days), and stores its id on the review's
    `created_continuing_sar_id`."

    Prior SAR filed 2026-05-05: review due 2026-08-03, continuing deadline
    2026-09-02 — the detection date is ignored for continuing SARs.

    Design: Difficulty/combinatorial_formula/sar_deadline_conditional_branches
    """
    staff = create_staff()
    built = setup_deadline_branch_scenario(staff)
    sar3 = built.sar_continuing
    assert sar3["is_continuing"] is True
    assert sar3["prior_sar_id"] == built.sar_identified["id"]
    assert_same_instant(sar3["deadline_at"], "2026-09-02T00:00:00Z")
    assert_same_instant(built.review["due_at"], "2026-08-03T00:00:00Z")
    assert_same_instant(built.review["filing_deadline_at"], "2026-09-02T00:00:00Z")
    assert built.review["created_continuing_sar_id"] == sar3["id"]


def test_filing_one_second_past_deadline_rejected(api):
    """PRD §2.8: "Filing is permitted up to and including `deadline_at`; once
    the logical clock passes it, the filing attempt is rejected with
    `ERR_FILING_DEADLINE_PASSED` (HTTP 422). All comparisons are at second
    precision and are inclusive of the deadline instant."

    Design: Difficulty/boundary_precision_check/file_sar_deadline_instant_boundary
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = drive_sar_to_approved(staff, case["id"])
    assert_same_instant(sar["deadline_at"], "2026-05-31T00:00:00Z")

    set_clock(staff, "2026-05-31T00:00:01Z")  # one second past the deadline
    res = api.file_sar(sar["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_FILING_DEADLINE_PASSED)
    assert res.status_code == 422
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "APPROVED"
    assert after["filed_at"] is None


def test_filing_exactly_at_deadline_succeeds(api):
    """PRD §2.8: "Filing is permitted up to and including `deadline_at`; once
    the logical clock passes it, the filing attempt is rejected with
    `ERR_FILING_DEADLINE_PASSED` (HTTP 422). All comparisons are at second
    precision and are inclusive of the deadline instant."

    Design: Difficulty/boundary_precision_check/file_sar_deadline_instant_boundary
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = drive_sar_to_approved(staff, case["id"])
    assert_same_instant(sar["deadline_at"], "2026-05-31T00:00:00Z")

    set_clock(staff, "2026-05-31T00:00:00Z")  # exactly the deadline instant
    filed = validate_success(api.file_sar(sar["id"], staff.manager), 200)
    assert filed["status"] == "FILED"
    assert_same_instant(filed["filed_at"], "2026-05-31T00:00:00Z")


def test_file_draft_sar_past_deadline_returns_invalid_state(api):
    """PRD §2.10: "Priority order, from highest to lowest, is:
    malformed-request checks (missing fields, bad enums, non-positive amounts,
    incoherent date windows, a QA review lacking exactly one target, or a
    duplicate active QA sample on the same target — all `ERR_INVALID_REQUEST`);
    then authentication (`ERR_UNAUTHENTICATED`); then role authorization
    (`ERR_FORBIDDEN_ROLE`); then segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`); then existence of every referenced id
    (`ERR_NOT_FOUND`); then state-machine legality (`ERR_INVALID_STATE`); then
    OCC stale-version (`ERR_STALE_VERSION`); then the law-enforcement-inquiry
    safety hold (`ERR_LE_INQUIRY_OPEN`); then the customer-prohibited gate
    (`ERR_CUSTOMER_PROHIBITED`); then the threshold-window overlap check
    (`ERR_THRESHOLD_WINDOW_OVERLAP`); then the SAR activity-window overlap
    check (`ERR_ACTIVITY_WINDOW_OVERLAP`); then the 314(b) duplicate-window
    check (`ERR_314B_DUPLICATE_WINDOW`); then narrative length
    (`ERR_NARRATIVE_INSUFFICIENT`); then analyst capacity
    (`ERR_ANALYST_AT_CAPACITY`); then scenario retirement blocked by open
    alerts (`ERR_SCENARIO_HAS_OPEN_ALERTS`); then QA quota
    (`ERR_QA_QUOTA_EXCEEDED`); then filing deadline
    (`ERR_FILING_DEADLINE_PASSED`); then 314(b) certification expiry
    (`ERR_CERTIFICATION_EXPIRED`); then subject mismatch across a link
    (`ERR_SUBJECT_MISMATCH`); then the no-active-threshold check
    (`ERR_NO_ACTIVE_THRESHOLD`); and finally the scenario-not-active check
    (`ERR_SCENARIO_NOT_ACTIVE`)."

    Filing a SAR still in DRAFT past its deadline reports the state failure,
    not the temporal one.

    Design: Difficulty/priority_pair_validation_conflict/file_sar_state_beats_temporal
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])  # stays DRAFT; deadline 2026-05-31
    set_clock(staff, "2026-06-05T00:00:00Z")  # past the deadline

    res = api.file_sar(sar["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409, (
        "state (priority 6) outranks business_temporal (priority 17): the "
        "response must be 409 ERR_INVALID_STATE, not 422 ERR_FILING_DEADLINE_PASSED"
    )


def test_rejected_filing_leaves_sar_untouched(api):
    """PRD §3.5: "A successful filing sets `filed_at` and assigns a
    `filing_reference`".
    PRD §3.5: "A `ContinuingReview` is created in `SCHEDULED` against the
    freshly filed SAR".

    A filing rejected on the state gate performs none of the filing side
    effects.

    Design: Difficulty/priority_pair_validation_conflict/file_sar_state_beats_temporal
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    set_clock(staff, "2026-06-05T00:00:00Z")

    res = api.file_sar(sar["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "DRAFT"
    assert after["filed_at"] is None
    reviews, meta = validate_paginated(
        api.list_continuing_reviews(sar["id"], staff.analyst))
    assert reviews == [] and meta["total_count"] == 0, (
        "no ContinuingReview exists for a SAR that was never filed"
    )


def test_filing_overlapping_activity_window_rejected(api):
    """PRD §3.5: "Second, the activity window — a closed interval from
    `activity_start_date` to `activity_end_date` inclusive at date granularity
    — must not share even a single calendar day with any other `FILED` SAR for
    the same customer; adjacency (one SAR's start the day after another's end)
    is allowed, and a violation is `ERR_ACTIVITY_WINDOW_OVERLAP`."

    The continuing draft's window is amended to start 2026-04-10 — the prior
    FILED SAR's inclusive end date — so the closed intervals share one
    calendar day. The clock (2026-05-20) sits inside the continuing deadline,
    so only the window check can fail.

    Design: Difficulty/resource_temporal_overlap/sar_activity_window_closed_overlap
    """
    staff = create_staff()
    customer = create_customer(staff)
    filed = setup_filed_sar(staff, customer["id"],
                            file_clock="2026-05-05T00:00:00Z")
    qa_review_case(staff, filed.case["id"], "PASS")
    review = first_continuing_review(staff, filed.sar["id"])
    review = start_and_complete_review(staff, review["id"], "FILE_CONTINUING_SAR")
    sar2 = get_success_data(
        api.get_sar_report(review["created_continuing_sar_id"], staff.analyst))
    sar2 = write_narrative(staff, sar2, NARRATIVE_WINDOW_PROBE,
                           activity_start_date="2026-04-10")
    sar2 = submit_sar_for_qa(staff, sar2["id"])
    sar2 = qa_review_sar(staff, sar2["id"], "PASS")
    sar2 = approve_sar(staff, sar2["id"])
    set_clock(staff, "2026-05-20T00:00:00Z")

    res = api.file_sar(sar2["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_ACTIVITY_WINDOW_OVERLAP)
    assert res.status_code == 409, (
        "closed intervals sharing the single calendar day 2026-04-10 conflict"
    )
    after = validate_success(api.get_sar_report(sar2["id"], staff.analyst), 200)
    assert after["status"] == "APPROVED"
    assert after["filed_at"] is None


def test_filing_adjacent_activity_window_succeeds(api):
    """PRD §3.5: "adjacency (one SAR's start the day after another's end) is
    allowed, and a violation is `ERR_ACTIVITY_WINDOW_OVERLAP`."
    PRD §3.6: "sets the activity window to start the day after the prior SAR's
    `activity_end_date` and to end 90 days later".

    The system-built continuing window starts 2026-04-11, the day after the
    prior FILED SAR's 2026-04-10 end — adjacent at day granularity, so filing
    succeeds.

    Design: Difficulty/resource_temporal_overlap/sar_activity_window_closed_overlap
    """
    staff = create_staff()
    customer = create_customer(staff)
    filed = setup_filed_sar(staff, customer["id"],
                            file_clock="2026-05-05T00:00:00Z")
    qa_review_case(staff, filed.case["id"], "PASS")
    review = first_continuing_review(staff, filed.sar["id"])
    review = start_and_complete_review(staff, review["id"], "FILE_CONTINUING_SAR")
    sar2 = get_success_data(
        api.get_sar_report(review["created_continuing_sar_id"], staff.analyst))
    assert sar2["activity_start_date"] == "2026-04-11", (
        "the continuing window starts the day after the prior SAR's end"
    )
    assert sar2["activity_end_date"] == "2026-07-09", "and ends 90 days later"
    sar2 = write_narrative(staff, sar2, NARRATIVE_CONTINUING)
    sar2 = submit_sar_for_qa(staff, sar2["id"])
    sar2 = qa_review_sar(staff, sar2["id"], "PASS")
    sar2 = approve_sar(staff, sar2["id"])
    set_clock(staff, "2026-05-20T00:00:00Z")

    filed2 = validate_success(api.file_sar(sar2["id"], staff.manager), 200)
    assert filed2["status"] == "FILED"
    assert_same_instant(filed2["filed_at"], "2026-05-20T00:00:00Z")


def test_first_filing_below_high_band_leaves_accounts_open(api):
    """PRD §2.6: "Whenever a recompute causes the rating to cross into `HIGH`
    or `PROHIBITED` from a lower band, every account of that customer whose
    status is `OPEN` is moved to `RESTRICTED` with `restriction_reason` set to
    `RISK_CASCADE`."

    After the first filing the standard score is 350 (100 + 250), band MEDIUM
    — the crossing has not happened, so the account stays OPEN.

    Design: Difficulty/transitive_cascade/sar_file_risk_restriction_cascade
    """
    staff = create_staff()
    built = setup_risk_cascade_scenario(staff)
    customer = validate_success(api.get_customer(built.customer["id"], staff.analyst), 200)
    assert customer["sar_filings_365d"] == 1
    assert customer["risk_score_standard"] == 350
    assert customer["risk_rating"] == "MEDIUM"
    account = validate_success(api.get_account(built.account["id"], staff.analyst), 200)
    assert account["status"] == "OPEN"
    assert account["restriction_reason"] is None


def test_second_filing_crossing_into_high_restricts_accounts(api):
    """PRD §2.6: "Whenever a recompute causes the rating to cross into `HIGH`
    or `PROHIBITED` from a lower band, every account of that customer whose
    status is `OPEN` is moved to `RESTRICTED` with `restriction_reason` set to
    `RISK_CASCADE`."
    PRD §3.5: "The customer's `sar_filings_365d` increments, the risk recompute
    runs, and if the rating crosses into `HIGH` or `PROHIBITED` every `OPEN`
    account of the customer becomes `RESTRICTED` with `restriction_reason`
    `RISK_CASCADE` (§2.6)."

    The second filing lifts the standard score to 600 (100 + 2*250), crossing
    MEDIUM -> HIGH; the restriction is caused by the crossing, not by any
    direct account action. The second SAR files at 2026-05-06, so its review
    is due 2026-08-04.

    Design: Difficulty/transitive_cascade/sar_file_risk_restriction_cascade
    """
    staff = create_staff()
    built = setup_risk_cascade_scenario(staff)
    filed2 = validate_success(api.file_sar(built.sar_second["id"], staff.manager), 200)
    assert filed2["status"] == "FILED"

    customer = validate_success(api.get_customer(built.customer["id"], staff.analyst), 200)
    assert customer["sar_filings_365d"] == 2
    assert customer["risk_score_standard"] == 600
    assert customer["risk_rating"] == "HIGH", "crossed INTO HIGH"
    account = validate_success(api.get_account(built.account["id"], staff.analyst), 200)
    assert account["status"] == "RESTRICTED"
    assert account["restriction_reason"] == "RISK_CASCADE"

    case_after = validate_success(api.get_case(built.case_second["id"], staff.analyst), 200)
    assert case_after["status"] == "PENDING_QA"
    review = first_continuing_review(staff, filed2["id"])
    assert review["status"] == "SCHEDULED"
    assert_same_instant(review["due_at"], "2026-08-04T00:00:00Z")


def test_short_narrative_submit_rejected(api):
    """PRD §3.5: "Submitting the draft for QA requires the caller to be the
    drafter and requires `narrative_length` of at least 500 characters; a
    shorter narrative is rejected with `ERR_NARRATIVE_INSUFFICIENT`."

    Design: Corner/errors/short_narrative_submit_rejected
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    sar = write_narrative(staff, sar, NARRATIVE_SHORT)
    assert len(NARRATIVE_SHORT) < 500

    res = api.submit_sar_for_qa(sar["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_NARRATIVE_INSUFFICIENT)
    assert res.status_code == 422
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "DRAFT"


def test_stale_narrative_edit_rejected(api):
    """PRD §2.9: "Editing the narrative or activity window of a SAR draft
    requires `expected_sar_version` equal to the SAR report's current
    `version`; a mismatch is likewise `ERR_STALE_VERSION`."
    PRD §2.9: "In every case, a successful mutation increments the parent
    entity's `version` by exactly 1, so a stale writer cannot silently
    overwrite work it has not observed."

    Design: Corner/complexity_layers/narrative_update_stale_version_rejected
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    stale_version = sar["version"]

    edited = validate_success(api.update_sar_narrative(
        sar["id"],
        update_narrative_payload(stale_version, narrative=NARRATIVE_STANDARD),
        staff.analyst), 200)
    assert edited["version"] == stale_version + 1
    assert edited["narrative_length"] == len(NARRATIVE_STANDARD)

    res = api.update_sar_narrative(
        sar["id"],
        update_narrative_payload(stale_version, narrative=NARRATIVE_STALE_ATTEMPT),
        staff.analyst)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["narrative_length"] == len(NARRATIVE_STANDARD), "no partial write"
    assert after["version"] == stale_version + 1


def test_narrative_length_recomputed_on_edit(api):
    """PRD §3.5: "edits may touch `narrative`, `activity_start_date`,
    `activity_end_date`, and `subject_unidentified`, and each successful edit
    recomputes `narrative_length` and increments the SAR's `version`."

    Design: Corner/complexity_layers/narrative_length_computed_exactly
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    edited = validate_success(api.update_sar_narrative(
        sar["id"],
        update_narrative_payload(sar["version"], narrative=NARRATIVE_STANDARD),
        staff.analyst), 200)
    assert edited["narrative_length"] == len(NARRATIVE_STANDARD), (
        f"exact character count of the stored narrative ({len(NARRATIVE_STANDARD)})"
    )
    assert edited["version"] == sar["version"] + 1


def test_analyst_cannot_approve_sar(api):
    """PRD §4: POST /sar-reports/{id}/approve is authorized for `BSAManager`
    only.
    PRD §2.1: "A request whose role is not listed among the endpoint's
    permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/analyst_cannot_approve_sar_returns_403
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    sar = write_narrative(staff, sar, NARRATIVE_STANDARD)
    sar = submit_sar_for_qa(staff, sar["id"])
    sar = qa_review_sar(staff, sar["id"], "PASS")
    assert sar["status"] == "QA_PASSED"

    res = api.approve_sar(sar["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert res.status_code == 403
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "QA_PASSED"


def test_sar_approve_by_drafter_rejected(api):
    """PRD §3.5: "Approval by a `BSAManager` — again never the drafter — moves
    the SAR from `QA_PASSED` to `APPROVED` and stamps
    `approved_by_analyst_id`."
    PRD §2.1: "On each, the caller's `X-User-ID` must differ from the actor who
    performed the prior step (the proposer, the drafter, or the assigned
    analyst as applicable), or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_sar_approve_by_drafter_rejected
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    sar = write_narrative(staff, sar, NARRATIVE_STANDARD)
    sar = submit_sar_for_qa(staff, sar["id"])
    sar = qa_review_sar(staff, sar["id"], "PASS")
    assert sar["drafted_by_analyst_id"] == staff.analyst_id

    drafter_as_manager = make_manager_headers(staff.analyst_id)
    res = api.approve_sar(sar["id"], drafter_as_manager)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert res.status_code == 403
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "QA_PASSED"


def test_sar_qa_by_drafter_rejected(api):
    """PRD §3.5: "A `QAReviewer` — never the drafter — then records an
    `outcome` of `PASS` or `FAIL` with optional `notes`."
    PRD §2.1: "On each, the caller's `X-User-ID` must differ from the actor who
    performed the prior step (the proposer, the drafter, or the assigned
    analyst as applicable), or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_sar_qa_by_drafter_rejected
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    sar = create_sar_draft(staff, case["id"])
    sar = write_narrative(staff, sar, NARRATIVE_STANDARD)
    sar = submit_sar_for_qa(staff, sar["id"])
    assert sar["status"] == "IN_QA"

    drafter_as_qa = make_qa_reviewer_headers(staff.analyst_id)
    res = api.review_sar_qa(sar["id"], {"outcome": "PASS"}, drafter_as_qa)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert res.status_code == 403
    after = validate_success(api.get_sar_report(sar["id"], staff.analyst), 200)
    assert after["status"] == "IN_QA"

