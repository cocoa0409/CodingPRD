"""Hearing temporal conflicts, conserved-quantity invariants, and appeal record
boundary checks.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_hearing_payload, make_attorney_headers, TEST_USERS,
    setup_open_case, setup_judgment_entered, setup_notice_filed_appeal,
    schedule_hearing, add_party, efile, review_accept,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"


# =====================================================================
# Queue A: resource_temporal_overlap
# =====================================================================
def test_hearing_courtroom_overlap_rejected(api):
    """PRD 3.5: "Scheduling enforces a temporal non-overlap rule on two axes: the
    proposed window must not overlap an existing SCHEDULED hearing in the same courtroom,
    and must not overlap an existing SCHEDULED hearing for the same judge_user_id. A
    violation on either axis is rejected with ERR_HEARING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_courtroom_overlap_rejected
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    schedule_hearing(case_id, courtroom="A", judge_user_id="jdg_1",
                     start_at="2026-03-05T10:00:00.000Z",
                     end_at="2026-03-05T11:00:00.000Z")
    # Same courtroom, overlapping window, DIFFERENT judge -> courtroom conflict.
    resp = api.create_hearing(create_hearing_payload(
        case_id, courtroom="A", judge_user_id="jdg_9",
        start_at="2026-03-05T10:30:00.000Z", end_at="2026-03-05T11:30:00.000Z"), JUDGE)
    validate_error(resp, "ERR_HEARING_CONFLICT")


def test_hearing_judge_overlap_across_courtrooms_rejected(api):
    """PRD 3.5: "the proposed window must not overlap an existing SCHEDULED hearing in
    the same courtroom, and must not overlap an existing SCHEDULED hearing for the same
    judge_user_id. A violation on either axis is rejected with ERR_HEARING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_judge_overlap_across_courtrooms_rejected
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    schedule_hearing(case_id, courtroom="A", judge_user_id="jdg_1",
                     start_at="2026-03-05T10:00:00.000Z",
                     end_at="2026-03-05T11:00:00.000Z")
    # DIFFERENT courtroom, overlapping window, SAME judge -> judge conflict.
    resp = api.create_hearing(create_hearing_payload(
        case_id, courtroom="B", judge_user_id="jdg_1",
        start_at="2026-03-05T10:30:00.000Z", end_at="2026-03-05T11:30:00.000Z"), JUDGE)
    validate_error(resp, "ERR_HEARING_CONFLICT")


# =====================================================================
# Queue A: compensating_invariant
# =====================================================================
def test_fee_assess_then_reject_releases_fee(api):
    """PRD 3.2: "Rejection moves the filing `UNDER_REVIEW → REJECTED`, records the
    `rejection_reason`, and — if the filing's `fee_status` was `ASSESSED` — releases that
    fee by setting `fee_status` back to `NONE` and recomputing the case fee aggregates,
    incrementing the filing's `version`."

    Design: Difficulty/compensating_invariant/fee_assess_then_reject_releases_fee_invariant
    """
    # OPEN-less path is fine; use a DRAFT case with a prior zero-fee accepted ANSWER so
    # the assessed sum starts at 0, then assess a complaint and reject it.
    from test_helpers import setup_draft_case
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)

    answer = efile(case_id, pl["id"], ATT_PL, document_type="ANSWER", title="Answer")
    review_accept(answer["id"])
    case_before = get_success_data(api.get_case(case_id, CLERK))
    assert case_before["total_fees_assessed_cents"] == 0, case_before["total_fees_assessed_cents"]

    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint 2")
    get_success_data(api.claim_review_filing(complaint["id"], CLERK))

    rejected = validate_success(
        api.reject_filing(complaint["id"], {"rejection_reason": "Wrong court"}, CLERK))
    case_after = validate_success(api.get_case(case_id, CLERK))

    assert rejected["fee_status"] == "NONE", rejected["fee_status"]
    assert case_after["total_fees_assessed_cents"] == 0, case_after["total_fees_assessed_cents"]


def test_judgment_vacate_restores_open_deadline_count(api):
    """PRD 3.7: "Vacatur moves the judgment `ENTERED → VACATED`, reverses the case
    `JUDGMENT_ENTERED → OPEN`, vacates every `APPEAL` deadline still in `PENDING`, and
    increments both the judgment's and the case's `version`."

    Design: Difficulty/compensating_invariant/judgment_vacate_restores_open_deadline_count_invariant
    """
    base = setup_open_case(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    count_before = get_success_data(api.get_case(case_id, CLERK))["open_deadline_count"]

    judgment = get_success_data(api.create_judgment({
        "case_id": case_id, "judgment_type": "TRIAL",
        "prevailing_party_id": base["plaintiff"]["id"],
        "principal_cents": 0, "interest_rate_bps": 0,
        "expected_case_version": base["case_version"],
    }, JUDGE))

    get_success_data(api.vacate_judgment(judgment["id"], JUDGE))
    case_after = validate_success(api.get_case(case_id, CLERK))
    judgment_after = validate_success(api.get_judgment(judgment["id"], CLERK))

    assert case_after["status"] == "OPEN", case_after["status"]
    assert case_after["open_deadline_count"] == count_before, case_after["open_deadline_count"]
    assert judgment_after["status"] == "VACATED", judgment_after["status"]


# =====================================================================
# Queue A: boundary_precision_check (appeal empty record)
# =====================================================================
def test_appeal_prepare_record_zero_pages_rejected(api):
    """PRD 3.8: "Preparation requires a positive record_page_count; an attempt with a
    page count of zero or less is rejected with ERR_EMPTY_RECORD."

    Design: Difficulty/boundary_precision_check/appeal_prepare_record_empty_zero_pages
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    resp = api.prepare_record(base["appeal"]["id"], {"record_page_count": 0}, CLERK)
    validate_error(resp, "ERR_EMPTY_RECORD")


# =====================================================================
# Queue B (Corner): endpoints / errors clustering here
# =====================================================================
def test_service_complete_on_already_served_rejected(api):
    """PRD 3.3: "the `served_party_id` must refer to a `DEFENDANT` party whose
    `service_status` is not already `SERVED` (else `ERR_PARTY_ALREADY_SERVED`)."

    Design: Corner/endpoints/service_already_served_returns_already_served
    """
    from test_helpers import add_attempted_service
    base = setup_open_case(clock="2026-03-02T00:00:00.000Z")
    case_id = base["case"]["id"]
    sop1 = add_attempted_service(case_id, base["complaint"]["id"], base["defendant"]["id"],
                                 service_date="2026-03-02T00:00:00.000Z")
    get_success_data(api.complete_service(sop1["id"], CLERK))
    sop2 = add_attempted_service(case_id, base["complaint"]["id"], base["defendant"]["id"],
                                 service_date="2026-03-03T00:00:00.000Z", method="MAIL")

    resp = api.complete_service(sop2["id"], CLERK)
    validate_error(resp, "ERR_PARTY_ALREADY_SERVED")


def test_fee_waiver_approve_not_assessed_rejected(api):
    """PRD 3.6: "Approval requires that the target filing's fee_status is ASSESSED; if it
    is anything else, approval is rejected with ERR_FEE_NOT_ASSESSED."

    Design: Corner/errors/fee_waiver_approve_not_assessed_returns_fee_not_assessed
    """
    from test_helpers import setup_draft_case, add_fee_waiver
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = add_fee_waiver(case_id, complaint["id"], pl["id"], attorney_user_id=ATT_PL)
    # Pay the fee so its status is PAID (not ASSESSED).
    get_success_data(api.pay_fee(complaint["id"], CLERK))

    resp = api.approve_fee_waiver(fw["id"], CLERK)
    validate_error(resp, "ERR_FEE_NOT_ASSESSED")


def test_close_judgment_entered_with_open_appeal_window_rejected(api):
    """PRD 3.1: "A case in JUDGMENT_ENTERED may be closed only if no APPEAL-type deadline
    under it is still PENDING with a due_date at or after the current clock; if such a
    live appeal deadline exists, the close is rejected with ERR_APPEAL_WINDOW_OPEN."

    Design: Corner/errors/close_case_appeal_window_open_returns_error
    """
    base = setup_judgment_entered(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    resp = api.close_case(case_id, CLERK)
    validate_error(resp, "ERR_APPEAL_WINDOW_OPEN")


def test_close_on_appeal_with_untransmitted_appeal_rejected(api):
    """PRD 3.1: "A case in ON_APPEAL may be closed only if every appeal on the case is in
    status TRANSMITTED or DISMISSED; otherwise the close is rejected with
    ERR_APPEAL_NOT_TRANSMITTED."

    Design: Corner/errors/close_on_appeal_case_with_untransmitted_appeal_returns_error
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    resp = api.close_case(base["case"]["id"], CLERK)
    validate_error(resp, "ERR_APPEAL_NOT_TRANSMITTED")
