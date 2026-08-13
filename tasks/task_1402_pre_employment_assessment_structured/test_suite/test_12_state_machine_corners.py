"""Corner coverage — state machines: terminal lockdowns, invalid transitions,
idempotency, preconditions, auto-transitions, and accommodation side effects."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_vendor,
    create_guide,
    create_guide_payload,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    create_calibrated_interviewer,
    create_interviewer,
    create_calibration_payload,
    certify_calibration_payload,
    create_session_payload,
    create_scorecard_payload,
    create_accommodation_request_payload,
    approve_accommodation_payload,
    deny_accommodation_payload,
    schedule_assessment_payload,
    create_snapshot_payload,
    create_decision_payload,
    create_content_ledger_event_payload,
    set_clock_payload,
    setup_active_cycle,
    setup_quorum_ready_candidate,
    setup_decided_candidate,
    setup_purged_assessment,
    book_completed_session,
    submit_scorecard,
    make_interviewer_headers,
    make_candidate_headers,
    make_admin_headers,
    plus_days,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]
DO = TEST_USERS["do_headers"]


def test_terminate_terminal_lockdown(api):
    """PRD §3.1: "Once a vendor is `TERMINATED`, every ledger, suspension,
    reinstatement, and termination attempt against it is rejected as
    `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/terminate_terminal_lockdown
    """
    vendor = create_vendor()
    validate_success(api.terminate_vendor(vendor["id"], ADMIN))
    resp = api.suspend_vendor(vendor["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    resp = api.reinstate_vendor(vendor["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    data = validate_success(api.get_vendor(vendor["id"], ADMIN))
    assert data["status"] == "TERMINATED"


def test_guide_approve_from_draft_rejected(api):
    """PRD §3.3: "Approval moves `PILOT` → `APPROVED`" — approval on a DRAFT guide is
    a generic from-state violation: `ERR_INVALID_STATE` (PRD §2.8 tier 6: "the target
    resource's own state admits the transition").

    Design: Corner/state_machines/guide_approve_from_draft_rejected
    """
    guide = create_guide()
    resp = api.approve_guide(guide["id"], ADMIN2)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_guide(guide["id"], ADMIN))
    assert data["status"] == "DRAFT"


def test_scorecard_resubmit_rejected(api):
    """PRD §3.6: "The source-state check is `ERR_SCORECARD_NOT_DRAFT` (HTTP 409) for
    anything not `DRAFT`".

    Design: Corner/state_machines/scorecard_resubmit_rejected
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    sc1 = ctx["scorecards"][0]
    iv1 = ctx["interviewers"][0]
    assert sc1["status"] == "SUBMITTED"
    resp = api.submit_scorecard(sc1["id"], make_interviewer_headers(iv1["id"]))
    validate_error(resp, ApiErrorId.ERR_SCORECARD_NOT_DRAFT)
    data = validate_success(api.get_scorecard(sc1["id"], ADMIN))
    assert data["status"] == "SUBMITTED"


def test_session_complete_before_end_rejected(api):
    """PRD §3.6: "Completing a session moves `SCHEDULED` → `COMPLETED`, requires the
    cycle `ACTIVE`, requires the logical now to be at or after `scheduled_end` —
    earlier is `ERR_SESSION_NOT_ENDED` (HTTP 422)".

    Design: Corner/state_machines/session_complete_before_end_rejected
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = get_success_data(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM))
    # one second before scheduled_end
    api.set_clock(set_clock_payload("2026-08-12T10:59:59Z"), ADMIN)
    resp = api.complete_session(s1["id"], HM)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ENDED)
    # at exactly scheduled_end the >= boundary admits completion
    api.set_clock(set_clock_payload("2026-08-12T11:00:00Z"), ADMIN)
    resp = api.complete_session(s1["id"], HM)
    assert validate_success(resp)["status"] == "COMPLETED"


def test_cancelled_session_cannot_complete(api):
    """PRD §3.6: "`CANCELLED` is fully terminal." Completing a cancelled session is a
    generic from-state violation (`ERR_INVALID_STATE`, PRD §2.8 tier 6).

    Design: Corner/state_machines/cancelled_session_cannot_complete
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = get_success_data(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM))
    validate_success(api.cancel_session(s1["id"], HM))
    api.set_clock(set_clock_payload("2026-08-12T11:00:00Z"), ADMIN)
    resp = api.complete_session(s1["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_session(s1["id"], ADMIN))
    assert data["status"] == "CANCELLED"


def test_requisition_auto_filled_then_decision_rejected(api):
    """PRD §3.4: "when an `ADVANCE` decision pushes it to meet or exceed
    `openings_count`, the requisition's `status` automatically becomes `FILLED`" and
    "the requisition must still be `OPEN` (`ERR_REQUISITION_NOT_OPEN`)" for decision
    creation (PRD §3.8).

    Design: Corner/state_machines/requisition_auto_filled_then_decision_rejected
    """
    # openings_count == 1; two quorum-ready candidates in the same cycle
    ctx = setup_active_cycle(openings_count=1)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")

    def _ready_candidate(ref, grp, raw, r1, r2, rec):
        c = create_candidate(external_ref=ref, full_name=f"Cand {ref}",
                             email=f"{ref.lower()}@x.com", group_code=grp)
        invite_and_complete_candidate(cycle["id"], c["id"], raw_score=raw)
        return c

    c1 = _ready_candidate("C-1", "GROUP_A", 72, None, None, None)
    c2 = _ready_candidate("C-2", "GROUP_B", 60, None, None, None)
    s1 = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
    s2 = book_completed_session(cycle["id"], c1["id"], iv2["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    s3 = book_completed_session(cycle["id"], c2["id"], iv1["id"], guide["id"],
                                "2026-08-13T09:00:00Z", "2026-08-13T10:00:00Z")
    s4 = book_completed_session(cycle["id"], c2["id"], iv2["id"], guide["id"],
                                "2026-08-13T10:00:00Z", "2026-08-13T11:00:00Z")
    submit_scorecard(s1["id"], iv1["id"])
    submit_scorecard(s2["id"], iv2["id"],
                     ratings=[{"competency_code": "COMM", "rating": 5},
                              {"competency_code": "ANAL", "rating": 3}])
    submit_scorecard(s3["id"], iv1["id"],
                     ratings=[{"competency_code": "COMM", "rating": 3},
                              {"competency_code": "ANAL", "rating": 3}], overall_recommendation="NO")
    submit_scorecard(s4["id"], iv2["id"],
                     ratings=[{"competency_code": "COMM", "rating": 3},
                              {"competency_code": "ANAL", "rating": 4}], overall_recommendation="NO")

    resp = api.create_decision(cycle["id"], create_decision_payload(c1["id"]), DO)
    validate_success(resp, expected_status=201)
    req = validate_success(api.get_requisition(ctx["requisition"]["id"], HM))
    assert req["filled_count"] == 1
    assert req["status"] == "FILLED"
    resp = api.create_decision(
        cycle["id"],
        create_decision_payload(c2["id"], decision="HOLD",
                                rationale="Candidate showed partial proficiency; hold pending another panel review."),
        DO,
    )
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)


def test_cycle_auto_decided_when_all_decided(api):
    """PRD §3.4: "The cycle then advances `SCORING` → `DECIDED` automatically at the
    moment every candidate assessment in the cycle with `admin_status` of `COMPLETED`
    has a finalized hiring decision".

    Design: Corner/state_machines/cycle_auto_decided_when_all_decided
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    cycle = ctx["cycle"]
    # No SCHEDULED sessions remain (both are SCORED) -> begin-scoring is clean
    resp = api.begin_cycle_scoring(cycle["id"], HM)
    assert validate_success(resp)["posture"] == "SCORING"
    resp = api.create_decision(
        cycle["id"],
        create_decision_payload(ctx["candidate"]["id"], decision="HOLD",
                                rationale="Candidate showed solid skills; hold for cross-team calibration review."),
        DO,
    )
    validate_success(resp, expected_status=201)
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["posture"] == "DECIDED"
    assert cyc["decisions_finalized_count"] == 1


def test_supersede_approve_retires_old_guide(api):
    """PRD §3.3: "if the guide being approved declares a `supersedes_guide_id` and that
    predecessor is currently `APPROVED`, the predecessor automatically transitions
    `APPROVED` → `RETIRED` with its `version` incremented" and "the new guide starts in
    `DRAFT` with `supersedes_guide_id` taken from the path, `created_by_user_id` from
    the caller, and `version_label` equal to the superseded guide's `version_label`
    plus one."

    Design: Corner/state_machines/supersede_approve_retires_old_guide
    """
    # g1 created by admin-1, approved by admin-2
    from test_helpers import create_guide_revision_payload
    g1 = get_success_data(api_client.create_guide(create_guide_payload(title="Guide v1"), ADMIN))
    get_success_data(api_client.pilot_guide(g1["id"], ADMIN))
    g1 = get_success_data(api_client.approve_guide(g1["id"], ADMIN2))
    g1v = g1["version"]

    # revision authored by admin-2
    g2 = get_success_data(api_client.create_guide_revision(
        g1["id"], create_guide_revision_payload(g1v), ADMIN2,
    ))
    assert g2["version_label"] == 2
    assert g2["status"] == "DRAFT"
    get_success_data(api_client.pilot_guide(g2["id"], ADMIN2))
    # approved by admin-1 (SoD: approver != creator)
    g2 = get_success_data(api_client.approve_guide(g2["id"], ADMIN))
    assert g2["status"] == "APPROVED"
    g1_after = get_success_data(api_client.get_guide(g1["id"], ADMIN))
    assert g1_after["status"] == "RETIRED"
    assert g1_after["superseded_by_guide_id"] == g2["id"]
    # self-FK reverse lookup: guides superseding g1 == [g2]
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api.list_guides(ADMIN, params={"supersedes_guide_id": g1["id"]}))
    assert [g["id"] for g in data] == [g2["id"]]


def test_no_show_marks_feedback_not_applicable(api):
    """PRD §3.5: "A scheduled candidate who never presents may be marked no-show, moving
    `SCHEDULED` → `NO_SHOW`, only once the logical now is strictly later than
    `scheduled_for`; the mark also moves `feedback_status` from `NOT_SENT` to
    `NOT_APPLICABLE`."

    At exactly scheduled_for the mark is rejected (strictly-later rule); one second
    later it lands.

    Design: Corner/state_machines/no_show_marks_feedback_not_applicable
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"], scheduled_for="2026-08-10T09:00:00Z")
    api.set_clock(set_clock_payload("2026-08-10T09:00:00Z"), ADMIN)
    resp = api.mark_assessment_no_show(a1["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    api.set_clock(set_clock_payload("2026-08-10T09:00:01Z"), ADMIN)
    resp = api.mark_assessment_no_show(a1["id"], HM)
    data = validate_success(resp)
    assert data["admin_status"] == "NO_SHOW"
    assert data["feedback_status"] == "NOT_APPLICABLE"


def test_accommodation_approve_holds_extends_and_releases(api):
    """PRD §3.5: "Approval adds `approved_extension_days` to the assessment's
    `accommodation_extension_days`, and if the assessment was `SCHEDULED` it moves
    automatically to `ACCOMMODATION_HOLD` — the old slot can no longer be trusted, and
    the assessment must be rescheduled before it can start." and "Rescheduling moves
    `ACCOMMODATION_HOLD` → `SCHEDULED` with a fresh `scheduled_for`, again requiring
    the cycle `ACTIVE` and the manager's ownership." and "the effective end is the
    cycle's `administration_window_end` extended by the assessment's accumulated
    `accommodation_extension_days`".

    Approving 5 days against a 2-day request is `ERR_EXTENSION_OUT_OF_RANGE` ("at
    least one and at most the `requested_extension_days`").

    Design: Corner/state_machines/accommodation_approve_holds_extends_and_releases
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"], scheduled_for="2026-08-19T09:00:00Z")
    resp = api.create_accommodation_request(
        a1["id"], create_accommodation_request_payload(), make_candidate_headers(c1["id"]),
    )
    ar1 = validate_success(resp, expected_status=201)
    # Over-request approval rejected; request stays PENDING
    resp = api.approve_accommodation_request(
        ar1["id"], approve_accommodation_payload(approved_extension_days=5,
                                                 decision_note="Exceeds request."), CO,
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_OUT_OF_RANGE)
    # In-range approval lands
    resp = api.approve_accommodation_request(ar1["id"], approve_accommodation_payload(), CO)
    assert validate_success(resp)["status"] == "APPROVED"
    mid = validate_success(api.get_assessment(a1["id"], HM))
    assert mid["admin_status"] == "ACCOMMODATION_HOLD"
    assert mid["accommodation_extension_days"] == 2
    # Reschedule releases the hold
    resp = api.reschedule_assessment(
        a1["id"], schedule_assessment_payload(scheduled_for="2026-08-21T09:00:00Z"), HM,
    )
    assert validate_success(resp)["admin_status"] == "SCHEDULED"
    # Effective window end: 2026-08-20 + 2 days = 2026-08-22 -> 2026-08-21T09:00 is valid
    api.set_clock(set_clock_payload("2026-08-21T09:00:00Z"), ADMIN)
    get_success_data(api.start_assessment(a1["id"], HM))
    resp = api.complete_assessment(a1["id"], {"raw_score": 58}, HM)
    assert validate_success(resp)["admin_status"] == "COMPLETED"


def test_purged_assessment_feedback_rejected(api):
    """PRD §3.8: "the assessment must be `COMPLETED` (`ERR_ASSESSMENT_NOT_COMPLETED`)"
    — feedback on a purged assessment fails even though a finalized decision exists.
    PRD §3.9: "The purge then redacts the interview record: every scorecard for that
    candidate in that cycle has `redacted` (initially false on every scorecard) set to
    true, its `ratings` and `weighted_total` nulled, and its `version` incremented."

    Design: Corner/state_machines/purged_assessment_feedback_rejected
    """
    ctx = setup_purged_assessment()
    assert ctx["sweep"]["purged_count"] == 1
    resp = api.send_feedback(ctx["assessment"]["id"],
                             {"feedback_text": "Strong panel performance; advance to final round."},
                             HM)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_COMPLETED)
    # Purge side effect: scorecards redacted
    for sc in ctx["scorecards"]:
        data = validate_success(api.get_scorecard(sc["id"], ADMIN))
        assert data["redacted"] is True
        assert data["ratings"] is None
        assert data["weighted_total"] is None


def test_accommodation_second_pending_rejected(api):
    """PRD §3.5: "an assessment may carry at most one `PENDING` request at a time, a
    second one drawing `ERR_PENDING_ACCOMMODATION_EXISTS` (HTTP 409)".

    Design: Corner/state_machines/accommodation_second_pending_rejected
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"], scheduled_for="2026-08-19T09:00:00Z")
    resp = api.create_accommodation_request(
        a1["id"], create_accommodation_request_payload(), make_candidate_headers(c1["id"]),
    )
    ar1 = validate_success(resp, expected_status=201)
    # Second filing while the first is PENDING is rejected
    resp = api.create_accommodation_request(
        a1["id"],
        create_accommodation_request_payload(
            request_type="ALTERNATE_FORMAT",
            justification="Candidate also requests an alternate format version.",
            requested_extension_days=1,
        ),
        make_candidate_headers(c1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_ACCOMMODATION_EXISTS)
    # After denial, a fresh request is admitted
    validate_success(api.deny_accommodation_request(ar1["id"], deny_accommodation_payload(), CO))
    resp = api.create_accommodation_request(
        a1["id"],
        create_accommodation_request_payload(
            request_type="ALTERNATE_FORMAT",
            justification="Candidate re-files with full documentation attached.",
            requested_extension_days=1,
        ),
        make_candidate_headers(c1["id"]),
    )
    ar2 = validate_success(resp, expected_status=201)
    assert ar2["status"] == "PENDING"
