"""Motion rulings, the stay cascade, service-of-process depth-3 cascade, and the
related hearing/appeal side effects.
"""
from test_helpers import (
    validate_success, get_success_data,
    rule_motion_payload, create_hearing_payload, make_attorney_headers, TEST_USERS,
    setup_open_case, setup_motion_under_submission, setup_stayed_case,
    setup_notice_filed_appeal, add_attempted_service, add_deadline,
    add_accepted_motion_filing, file_motion, schedule_hearing,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"


# =====================================================================
# Queue A: non_linear_state_machine
# =====================================================================
def test_motion_grant_with_stay_freezes_case(api):
    """PRD 3.5: "A ruling of grant moves the motion `UNDER_SUBMISSION → GRANTED` and
    creates an order with disposition `GRANT`; if that order's `stays_case` is true, the
    case stay cascade is triggered."
    PRD 3.5: "First, the case transitions `OPEN → STAYED` (this is the system transition
    triggered by an order entered with `stays_case` true and a granting disposition while
    the case is `OPEN`)."
    PRD 3.5: "Third, posture is recomputed to `FROZEN`, which it remains while the case is
    `STAYED`."

    Design: Difficulty/non_linear_state_machine/motion_ruling_branch_fork_grant_deny_part
    """
    base = setup_motion_under_submission(clock="2026-03-01T00:00:00.000Z",
                                         motion_overrides={"opposed": True})
    ruled = validate_success(api.rule_motion(
        base["motion"]["id"],
        rule_motion_payload(ruling="GRANT", order_text="Granted and stayed", stays_case=True),
        JUDGE))
    case = validate_success(api.get_case(base["case"]["id"], CLERK))

    assert ruled["status"] == "GRANTED", ruled["status"]
    assert case["status"] == "STAYED", case["status"]
    assert case["posture"] == "FROZEN", case["posture"]


def test_motion_deny_never_stays_case(api):
    """PRD 3.5: "A ruling of denial moves the motion `UNDER_SUBMISSION → DENIED` and
    creates an order with disposition `DENY` for which `stays_case` is forced false, so
    denial never stays the case and never vacates deadlines."

    Design: Difficulty/non_linear_state_machine/motion_ruling_branch_fork_grant_deny_part
    """
    base = setup_motion_under_submission(clock="2026-03-01T00:00:00.000Z",
                                         motion_overrides={"opposed": True})
    ruled = validate_success(api.rule_motion(
        base["motion"]["id"],
        rule_motion_payload(ruling="DENY", order_text="Denied", stays_case=True),
        JUDGE))
    case = validate_success(api.get_case(base["case"]["id"], CLERK))

    assert ruled["status"] == "DENIED", ruled["status"]
    assert case["status"] == "OPEN", case["status"]


def test_fee_waiver_resubmit_recomputes_ratio(api):
    """PRD 3.6: "On resubmission the attorney may optionally update monthly_income_cents
    or household_size, after which the eligibility_ratio is recomputed. This revision
    loop may cycle between PENDING and NEEDS_INFO any number of times."

    Design: Difficulty/non_linear_state_machine/fee_waiver_revision_cycle_pending_needs_info
    """
    from test_helpers import (setup_draft_case, add_party, efile, add_fee_waiver)
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = add_fee_waiver(case_id, complaint["id"], pl["id"], attorney_user_id=ATT_PL,
                        monthly_income_cents=150000, household_size=1)
    get_success_data(api.request_info_fee_waiver(fw["id"], CLERK))

    resubmitted = validate_success(api.resubmit_fee_waiver(
        fw["id"], {"monthly_income_cents": 200000, "household_size": 3},
        make_attorney_headers(ATT_PL)))

    assert resubmitted["status"] == "PENDING", resubmitted["status"]
    assert resubmitted["eligibility_ratio"] == 0.8929, resubmitted["eligibility_ratio"]


def test_fee_waiver_request_info_then_resubmit_cycles_back_to_pending(api):
    """PRD 3.6: "A clerk who needs more information moves the waiver `PENDING → NEEDS_INFO`."
    PRD 3.6: "The attorney then resubmits, which moves it `NEEDS_INFO → PENDING`;
    resubmission is restricted to the requesting party's counsel, so the acting
    `attorney_user_id` must equal the requesting party's `attorney_user_id`, else
    `ERR_NOT_REQUESTING_PARTY`."

    Design: Difficulty/non_linear_state_machine/fee_waiver_revision_cycle_pending_needs_info
    """
    from test_helpers import (setup_draft_case, add_party, efile, add_fee_waiver)
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = add_fee_waiver(case_id, complaint["id"], pl["id"], attorney_user_id=ATT_PL,
                        monthly_income_cents=150000, household_size=1)

    needs_info = validate_success(api.request_info_fee_waiver(fw["id"], CLERK))
    assert needs_info["status"] == "NEEDS_INFO", needs_info["status"]

    back = validate_success(api.resubmit_fee_waiver(
        fw["id"], {}, make_attorney_headers(ATT_PL)))
    assert back["status"] == "PENDING", back["status"]


# =====================================================================
# Queue A: transitive_cascade
# =====================================================================
def test_service_complete_depth3_party_deadline_posture(api):
    """PRD 3.3: "the served party's service_status becomes SERVED and its served_at is
    set (hop one); a responsive-pleading deadline is created — a RESPONSE deadline
    anchored on the service-completed event, with its anchor_date taken from the
    service_date, counted in court days over an interval of thirty days, in status
    PENDING — its id recorded as the record's response_due_deadline_id, which increments
    the case's open_deadline_count (hop two); and the case posture is recomputed, since
    the new pending deadline may flip the posture to RESTRICTED (hop three)."

    Design: Difficulty/transitive_cascade/service_complete_depth3_party_deadline_posture
    """
    base = setup_open_case(clock="2026-03-02T00:00:00.000Z")
    case_id = base["case"]["id"]
    sop = add_attempted_service(case_id, base["complaint"]["id"], base["defendant"]["id"],
                                service_date="2026-03-02T00:00:00.000Z")

    completed = validate_success(api.complete_service(sop["id"], CLERK))
    dl = validate_success(api.get_deadline(completed["response_due_deadline_id"], CLERK))
    party = validate_success(api.get_party(base["defendant"]["id"], CLERK))
    case = validate_success(api.get_case(case_id, CLERK))

    assert party["service_status"] == "SERVED", party["service_status"]
    assert dl["deadline_type"] == "RESPONSE", dl["deadline_type"]
    assert dl["due_date"] == "2026-04-13T23:59:59.000Z", dl["due_date"]
    # statute-of-limitations deadline (on open) + this RESPONSE deadline = 2.
    assert case["open_deadline_count"] == 2, case["open_deadline_count"]


def test_stay_cascade_depth3_vacates_pending_deadlines(api):
    """PRD 3.5: "Second, every deadline under the case still in PENDING is moved to
    VACATED, each such vacatur decrementing the case's open_deadline_count."

    Design: Difficulty/transitive_cascade/stay_cascade_depth3_order_case_deadlines
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    manual_dl = add_deadline(case_id, interval_days=10, counting_mode="CALENDAR")

    # File and submit a motion, then rule GRANT with stays_case=true.
    mfiling = add_accepted_motion_filing(case_id, base["plaintiff"]["id"])
    motion = file_motion(case_id, mfiling["id"], base["plaintiff"]["id"],
                         motion_type="SUMMARY_JUDGMENT", opposed=True)
    get_success_data(api.submit_motion(motion["id"], JUDGE))
    get_success_data(api.rule_motion(
        motion["id"],
        rule_motion_payload(ruling="GRANT", order_text="Granted; case stayed", stays_case=True),
        JUDGE))

    dl = validate_success(api.get_deadline(manual_dl["id"], CLERK))
    case = validate_success(api.get_case(case_id, CLERK))

    assert case["status"] == "STAYED", case["status"]
    assert dl["status"] == "VACATED", dl["status"]
    assert case["open_deadline_count"] == 0, case["open_deadline_count"]


# =====================================================================
# Queue B (Corner): state_machines side-effect instances
# =====================================================================
def test_hold_hearing_moves_linked_motion_under_submission(api):
    """PRD 3.5: "Holding moves the hearing `SCHEDULED → HELD`, and if the hearing names a
    motion still in status `FILED`, that motion is advanced `FILED → UNDER_SUBMISSION` as a
    cascade; the hearing's `version` increments."

    Design: Corner/state_machines/hold_hearing_moves_linked_motion_under_submission
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    mfiling = add_accepted_motion_filing(case_id, base["plaintiff"]["id"])
    motion = file_motion(case_id, mfiling["id"], base["plaintiff"]["id"],
                         motion_type="COMPEL_DISCOVERY")
    hearing = schedule_hearing(case_id, motion_id=motion["id"], courtroom="A",
                               judge_user_id="jdg_1",
                               start_at="2026-03-05T10:00:00.000Z",
                               end_at="2026-03-05T11:00:00.000Z")
    get_success_data(api.set_clock("2026-03-05T10:30:00.000Z", ADMIN))

    held = validate_success(api.hold_hearing(hearing["id"], JUDGE))
    motion_after = validate_success(api.get_motion(motion["id"], CLERK))

    assert held["status"] == "HELD", held["status"]
    assert motion_after["status"] == "UNDER_SUBMISSION", motion_after["status"]


def test_motion_withdraw_cancels_linked_hearing(api):
    """PRD 3.5: "Withdrawal moves the motion `FILED → WITHDRAWN`, and if a `SCHEDULED`
    hearing is linked via `hearing_id` that hearing is cancelled as a cascade; the
    motion's `version` increments."

    Design: Corner/state_machines/motion_withdraw_cancels_linked_hearing
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    mfiling = add_accepted_motion_filing(case_id, base["plaintiff"]["id"])
    motion = file_motion(case_id, mfiling["id"], base["plaintiff"]["id"],
                         motion_type="CONTINUANCE")
    hearing = schedule_hearing(case_id, motion_id=motion["id"], courtroom="A",
                               judge_user_id="jdg_1",
                               start_at="2026-03-09T10:00:00.000Z",
                               end_at="2026-03-09T11:00:00.000Z")

    withdrawn = validate_success(api.withdraw_motion(motion["id"], make_attorney_headers(ATT_PL)))
    hearing_after = validate_success(api.get_hearing(hearing["id"], CLERK))

    assert withdrawn["status"] == "WITHDRAWN", withdrawn["status"]
    assert hearing_after["status"] == "CANCELLED", hearing_after["status"]


def test_appeal_dismiss_reverts_case_and_judgment(api):
    """PRD 3.8: "A judge may dismiss an appeal from either `NOTICE_FILED` or
    `RECORD_PREPARED`, in both cases moving it to `DISMISSED` with the same cascade: if no
    other non-terminal appeal remains on the case, the appealed judgment is restored
    `APPEALED → ENTERED` and the case is restored `ON_APPEAL → JUDGMENT_ENTERED`; the
    appeal's `version` increments."

    Design: Corner/state_machines/appeal_dismiss_reverts_case_and_judgment
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    dismissed = validate_success(api.dismiss_appeal(base["appeal"]["id"], JUDGE))
    case = validate_success(api.get_case(base["case"]["id"], CLERK))
    judgment = validate_success(api.get_judgment(base["judgment"]["id"], CLERK))

    assert dismissed["status"] == "DISMISSED", dismissed["status"]
    assert case["status"] == "JUDGMENT_ENTERED", case["status"]
    assert judgment["status"] == "ENTERED", judgment["status"]
