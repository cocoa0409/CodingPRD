"""Corner queue: case state machine claims (PRD §2.8, §3.2, §3.3, §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    CLOCK_DEFAULT_ISO, assert_same_instant,
    TEST_USERS,
    create_member, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, create_and_send_decision_notification,
    setup_notified_case, get_member_fresh, create_notification_payload,
    DECISION_ELEMENTS_MINUS_LANGUAGE, ALL_DECISION_ELEMENTS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_case_initial_state_is_received(api):
    """PRD §3.2: "The server stamps `received_at` at intake, sets `status` to `RECEIVED`,
    and increments the member's `open_case_count` by one."
PRD §2.4: "Before any operator call to the clock-setting capability, the logical
    clock reads exactly `2026-08-01T00:00:00Z`; this is the mandatory
    startup default, and the clock never falls back to wall-clock time
    thereafter."

    Design: Corner/state_machines/case_initial_state_received
    """
    member = create_member("MBR-SM1", full_name="Ini State", program="MEDICARE")
    set_clock(CLOCK_DEFAULT_ISO)
    data = validate_success(api.create_case(
        {"member_id": member["id"], "case_kind": "GRIEVANCE"}, INTAKE),
        expected_status=201)
    assert data["status"] == "RECEIVED"
    assert data["decision_outcome"] is None
    # §2.4 pins the instant; §2.5 renders timestamps with three fractional
    # digits, so compare instants rather than string forms.
    assert_same_instant(data["received_at"], "2026-08-01T00:00:00Z")


def test_triage_from_in_review_is_invalid_state(api):
    """PRD §3.3: "An `IntakeSpecialist` triages a case in `RECEIVED`, and four preconditions
    stand in front of the transition."
PRD §2.8: "Fifth, transition validity: if the requested action is not declared from
    the resource's current state, the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/triage_from_in_review_returns_invalid_state
    """
    member = create_member("MBR-SM2", full_name="Inv Tr", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    validate_error(api.triage_case(case["id"], INTAKE),
                   ApiErrorId.ERR_INVALID_STATE)


def test_mutation_on_closed_case_is_already_terminal(api):
    """PRD §2.8: "Sixth, terminal-state lockdown: any mutation attempted on a resource
    already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409)."
PRD §2.8: "Terminal states are `CLOSED` and `WITHDRAWN` for cases (with the sole
    exception that a reopening may still be requested against a `CLOSED`
    case), `DETERMINED` and `SUPERSEDED` for clinical reviews, `DELIVERED`
    and `FAILED` for notifications (with the sole exception that a
    `FAILED` notification may be retried), `EFFECTUATED` and `WAIVED` for
    effectuations, and `GRANTED` and `DENIED` for reopenings."

    Design: Corner/state_machines/terminal_case_lockdown_close_returns_already_terminal
    """
    member = create_member("MBR-SM3", full_name="Term Lock", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = setup_notified_case(member["id"], case_kind="GRIEVANCE",
                               decision_outcome="UNFAVORABLE")
    validate_success(api.close_case(case["id"], COMPLIANCE))
    validate_error(api.expedite_case(case["id"], MD),
                   ApiErrorId.ERR_ALREADY_TERMINAL)


def test_second_withdraw_fails_and_count_decremented_once(api):
    """PRD §2.8: "Terminal states are `CLOSED` and `WITHDRAWN` for cases (with the sole
    exception that a reopening may still be requested against a `CLOSED`
    case), `DETERMINED` and `SUPERSEDED` for clinical reviews, `DELIVERED`
    and `FAILED` for notifications (with the sole exception that a
    `FAILED` notification may be retried), `EFFECTUATED` and `WAIVED` for
    effectuations, and `GRANTED` and `DENIED` for reopenings."
PRD §3.2: "Withdrawal moves the case to `WITHDRAWN`, stamps `closed_at`, decrements
    the member's `open_case_count` by one (and `ctm_linked_case_count` as
    well when the case was CTM-linked), and appends a `NOTE` event whose
    `body` reads `WITHDRAWN`, incrementing the case's `version`."

    Design: Corner/state_machines/withdraw_idempotency_second_attempt_fails
    """
    member = create_member("MBR-SM4", full_name="Idem Pot", program="MEDICARE")
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="GRIEVANCE")
    first = validate_success(api.withdraw_case(case["id"], MSR))
    assert first["status"] == "WITHDRAWN"
    validate_error(api.withdraw_case(case["id"], MSR),
                   ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_member_fresh(member["id"])["open_case_count"] == 0, (
        "The decrement must fire exactly once")


def test_decide_creates_effectuation_only_when_favorable(api):
    """PRD §3.5: "When the outcome is anything other than `UNFAVORABLE`, the decision
    simultaneously arms effectuation: `effectuation_due_at` is computed as
    `decided_at` plus the active policy's `effectuation_hours`, and an
    Effectuation is created in `PENDING` status with
    `payment_amount_cents` taken from the decision payload."
PRD §3.5: "An `UNFAVORABLE` outcome carries no such obligation —
    `effectuation_due_at` stays null and no effectuation is created — and
    fiscal discipline bars payment in that direction:
    `payment_amount_cents` must never be negative, and supplying a payment
    alongside an `UNFAVORABLE` outcome is rejected with
    `ERR_PAYMENT_NOT_ALLOWED`."

    Design: Corner/state_machines/decide_side_effect_creates_effectuation_only_when_favorable
    """
    member = create_member("MBR-SM5", full_name="Side Eff", program="MEDICARE")
    # A second member for the second case: an identical intake (same
    # member/kind/provider) within one hour is a duplicate (PRD §3.2).
    member_b = create_member("MBR-SM5B", full_name="Side Eff B",
                             program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case_unfavorable = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE")["id"],
        decision_outcome="UNFAVORABLE")
    case_favorable = decide_grievance_from_in_review(
        create_in_review_case(member_b["id"], case_kind="GRIEVANCE")["id"],
        decision_outcome="FULLY_FAVORABLE", payment_amount_cents=0)
    effs_unfavorable = get_success_data(
        api.list_case_effectuations(case_unfavorable["id"], COMPLIANCE))
    assert effs_unfavorable == []
    assert case_unfavorable["effectuation_due_at"] is None
    effs_favorable = get_success_data(
        api.list_case_effectuations(case_favorable["id"], COMPLIANCE))
    assert len(effs_favorable) == 1
    assert effs_favorable[0]["status"] == "PENDING"
    # decided at the pinned default clock + 72h effectuation window.
    assert_same_instant(case_favorable["effectuation_due_at"],
                        "2026-08-04T00:00:00Z")


def test_mark_sent_requires_complete_then_patch_allows(api):
    """PRD §3.5: "A `QUEUED` notification is marked sent only when its `completeness_score`
    is exactly 1.00 — every required element supplied — else
    `ERR_NOTIFICATION_INCOMPLETE`; the first transition into `SENT` stamps
    `sent_at`."
PRD §3.5: "The server resolves `required_elements` from the notification content
    matrix keyed by the tuple of notification kind, recipient kind, the
    member's program, the case kind, and the decision outcome, and
    computes the `completeness_score` on creation and again whenever the
    representative patches `supplied_elements` — a patch permitted only
    while the notification is still `QUEUED`."

    Design: Corner/state_machines/notification_mark_sent_requires_complete
    """
    member = create_member("MBR-SM6", full_name="Pre Cond", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE")["id"],
        decision_outcome="UNFAVORABLE")
    notif = get_success_data(api.create_notification(
        case["id"],
        create_notification_payload(
            supplied_elements=list(DECISION_ELEMENTS_MINUS_LANGUAGE)),
        MSR), expected_status=201)
    assert notif["completeness_score"] < 1.00
    validate_error(api.mark_notification_sent(notif["id"], MSR),
                   ApiErrorId.ERR_NOTIFICATION_INCOMPLETE)
    patched = validate_success(api.patch_notification(
        notif["id"], {"supplied_elements": list(ALL_DECISION_ELEMENTS)}, MSR))
    assert patched["completeness_score"] == 1.00
    sent = validate_success(api.mark_notification_sent(notif["id"], MSR))
    assert sent["status"] == "SENT"
