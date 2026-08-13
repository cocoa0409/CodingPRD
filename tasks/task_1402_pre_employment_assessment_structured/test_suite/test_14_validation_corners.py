"""Corner coverage — validations: auth, role, ownership, FK-existence, OCC,
segregation of duties, cross-entity gates, duration/length bounds, and aggregate
gates."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_vendor,
    create_instrument,
    create_instrument_payload,
    create_evidence_payload,
    create_guide,
    create_guide_payload,
    create_guide_revision_payload,
    create_requisition,
    create_cycle_payload,
    patch_cycle_payload,
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
    create_decision_payload,
    freeze_cycle_payload,
    unfreeze_cycle_payload,
    set_clock_payload,
    setup_active_cycle,
    setup_quorum_ready_candidate,
    setup_decided_candidate,
    book_completed_session,
    submit_scorecard,
    make_interviewer_headers,
    make_candidate_headers,
    make_vendorrep_headers,
    make_hm_headers,
    make_admin_headers,
    void_scorecard_payload,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]
DO = TEST_USERS["do_headers"]


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing, if `X-User-Role` is not one of the
    declared roles, or if an entity-backed role's `X-User-ID` does not reference an
    existing instance of its backing entity, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." and PRD §2.8: "an authentication failure masks
    everything beneath it" — so even a non-existent path id answers 401 before 404.

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api._request("GET", f"/talent/vendors/{NON_EXISTENT_UUID}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_interviewer_role_cannot_create_vendor_returns_403(api):
    """PRD §2.1: "If the authenticated role is not listed among the roles authorized
    for the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)" and
    §4 lists vendor registration as TalentAssessmentAdmin-only.

    Design: Corner/validations/interviewer_role_cannot_create_vendor_returns_403
    """
    iv1 = get_success_data(api.create_interviewer(
        {"full_name": "Ivy One", "email": "ivy1@x.com", "department": "Risk"}, ADMIN,
    ))
    resp = api.create_vendor({"name": "Sneaky Vendor"}, make_interviewer_headers(iv1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_hm_other_requisition_cycle_forbidden(api):
    """PRD §2.10: "A requisition is owned through its `hiring_manager_id`, and that
    ownership extends to every child-cycle operation beneath it — activation, freezing
    aside (a compliance duty), scoring, closing, invitations, sessions, assessments,
    and feedback." and "Any mismatch is `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    hm-2 activating a cycle of hm-1's requisition is rejected.

    Design: Corner/validations/hm_other_requisition_cycle_forbidden
    """
    from test_helpers import create_validated_instrument, create_approved_guide
    vendor = create_vendor()
    instrument = create_validated_instrument(vendor["id"])
    guide = create_approved_guide()
    req = create_requisition(HM)  # hiring_manager_id = hm-1
    cycle = get_success_data(api.create_cycle(
        req["id"], create_cycle_payload(instrument["id"], guide["id"]), HM,
    ))
    assert cycle["posture"] == "SETUP"
    resp = api.activate_cycle(cycle["id"], make_hm_headers("hm-2"))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["posture"] == "SETUP"


def test_interviewer_other_session_scorecard_forbidden(api):
    """PRD §3.6: "the caller to be the session's own interviewer — the scorecard's
    `interviewer_id` and `candidate_id` are copied from the session, and ownership
    demands the session's `interviewer_id` equal `X-User-ID`" — a different
    interviewer draws `ERR_OWNERSHIP_MISMATCH` (PRD §2.10).

    Design: Corner/validations/interviewer_other_session_scorecard_forbidden
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = book_completed_session(cycle["id"], c1["id"], iv1["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    resp = api.create_scorecard(
        s1["id"],
        create_scorecard_payload(ratings=[{"competency_code": "COMM", "rating": 3}],
                                 overall_recommendation="NO"),
        make_interviewer_headers(iv2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_candidate_other_assessment_accommodation_forbidden(api):
    """PRD §3.5: "Filing one — against the candidate's own assessment, so
    `candidate_id` must equal `X-User-ID`" and §2.10: "A candidate owns assessments
    through `candidate_id`, and accommodation requests inherit that ownership through
    their parent assessment." and "Any mismatch is `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/candidate_other_assessment_accommodation_forbidden
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"])
    resp = api.create_accommodation_request(
        a1["id"],
        {"request_type": "OTHER",
         "justification": "This request is filed by the wrong candidate here.",
         "requested_extension_days": 1},
        make_candidate_headers(c2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_vendorrep_other_vendor_evidence_forbidden(api):
    """PRD §3.2: evidence is filed "by the administrator, or by a vendor representative
    whose `X-User-ID` equals the instrument's `vendor_id`" — a representative of
    another vendor draws `ERR_OWNERSHIP_MISMATCH` (PRD §2.10).

    Design: Corner/validations/vendorrep_other_vendor_evidence_forbidden
    """
    v1 = create_vendor()
    v2 = create_vendor(name="Beta Bench")
    i1 = create_instrument(v1["id"], code="COG-A")
    i2 = create_instrument(v2["id"], code="COG-B")
    resp = api.create_evidence(
        i1["id"],
        create_evidence_payload(title="Misfiled criterion study", issuer="Beta Lab"),
        make_vendorrep_headers(v2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    resp = api.create_evidence(
        i2["id"],
        create_evidence_payload(title="Own criterion study", issuer="Beta Lab"),
        make_vendorrep_headers(v2["id"]),
    )
    validate_success(resp, expected_status=201)


def test_body_fk_not_found_returns_404(api):
    """PRD §2.9: "Foreign keys carried in a request body are likewise resolved left to
    right in the order the endpoint declares them — a cycle-creation payload, for
    example, resolves `instrument_id` before `guide_id` — and the first unresolvable
    reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/body_fk_not_found_returns_404
    """
    resp = api.create_instrument(
        create_instrument_payload(NON_EXISTENT_UUID), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)


def test_occ_stale_cycle_version_rejected(api):
    """PRD §2.6: "The cycle update endpoint, `PATCH /talent/cycles/{id}` — updating a
    `SETUP` cycle's administration window, daily capacity, or pinned instrument or
    guide — requires the request to carry `expected_cycle_version`, a non-optional
    field holding the cycle `version` the client last observed." and "If that value no
    longer matches the cycle's current `version` — because another writer has modified
    the cycle since the client last read it — the update is rejected with
    `ERR_STALE_CYCLE_VERSION` (HTTP 412), and no field of the request is applied." and
    §2.4: "Every mutation of a resource increments its `version` by exactly one".

    Design: Corner/validations/occ_stale_cycle_version_rejected
    """
    ctx = setup_active_cycle()
    # Re-create a SETUP cycle for the PATCH (active cycle would hit ERR_INVALID_STATE)
    from test_helpers import create_cycle_payload
    resp = api.create_cycle(
        ctx["requisition"]["id"],
        create_cycle_payload(ctx["instrument"]["id"], ctx["guide"]["id"], label="Second Cycle"),
        HM,
    )
    cycle = get_success_data(resp)
    cy_v = cycle["version"]
    resp = api.patch_cycle(cycle["id"], patch_cycle_payload(cy_v, max_sessions_per_day=5), HM)
    patched = validate_success(resp)
    assert patched["max_sessions_per_day"] == 5
    assert patched["version"] == cy_v + 1, "exactly one increment"
    # Replay the now-stale expected version
    resp = api.patch_cycle(cycle["id"], patch_cycle_payload(cy_v, max_sessions_per_day=6), HM)
    validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION)
    data = validate_success(api.get_cycle(cycle["id"], HM))
    assert data["max_sessions_per_day"] == 5


def test_occ_stale_guide_version_supersede_rejected(api):
    """PRD §2.6: "The guide revisions endpoint,
    `POST /talent/interview-guides/{id}/revisions` — creating a revision guide that
    supersedes an existing approved guide — requires the request to carry
    `expected_superseded_guide_version`, again non-optional, holding the superseded
    guide's `version` as the client last observed it." and "A supersede legitimately
    mutates the current head — it sets the superseded guide's `superseded_by_guide_id`
    and increments that guide's `version` by one — so a client whose observed version
    has been advanced by another writer is authoring against an out-of-date head and
    must re-read before revising; the create is rejected with `ERR_STALE_GUIDE_VERSION`
    (HTTP 412)."

    Design: Corner/validations/occ_stale_guide_version_supersede_rejected
    """
    g1 = get_success_data(api_client.create_guide(create_guide_payload(title="Guide v1"), ADMIN))
    get_success_data(api_client.pilot_guide(g1["id"], ADMIN))
    g1 = get_success_data(api_client.approve_guide(g1["id"], ADMIN2))
    g1v = g1["version"]

    resp = api.create_guide_revision(g1["id"], create_guide_revision_payload(g1v, title="Guide v2a"), ADMIN2)
    g2a = validate_success(resp, expected_status=201)
    assert g2a["version_label"] == 2
    g1_after = validate_success(api.get_guide(g1["id"], ADMIN))
    assert g1_after["version"] == g1v + 1
    assert g1_after["superseded_by_guide_id"] == g2a["id"]
    # Second revision carrying the same (stale) observed head version
    resp = api.create_guide_revision(
        g1["id"],
        create_guide_revision_payload(
            g1v, title="Guide v2b",
            rubric_items=[{"competency_code": "COMM", "weight": 0.8, "scale_max": 5},
                          {"competency_code": "ANAL", "weight": 0.2, "scale_max": 5}],
        ),
        ADMIN2,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_GUIDE_VERSION)


def test_sod_guide_author_cannot_approve(api):
    """PRD §2.10: "The administrator who authored an interview guide may not approve it
    — the approver's `X-User-ID` must differ from the guide's `created_by_user_id`,
    else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/validations/sod_guide_author_cannot_approve
    """
    g = get_success_data(api_client.create_guide(create_guide_payload(title="Guide v1"), ADMIN))
    get_success_data(api_client.pilot_guide(g["id"], ADMIN))
    resp = api.approve_guide(g["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp = api.approve_guide(g["id"], ADMIN2)
    assert validate_success(resp)["status"] == "APPROVED"


def test_sod_decision_officer_who_scored_rejected(api):
    """PRD §2.10: "The officer recording a hiring decision must not have scored that
    candidate — the decider's `X-User-ID` must not equal the `interviewer_id` of any
    submitted scorecard counted toward that candidate's quorum, else the same
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_decision_officer_who_scored_rejected
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    iv1 = ctx["interviewers"][0]
    # DecisionOfficer whose X-User-ID equals iv1's id — an author of a quorum scorecard
    from test_helpers import make_do_headers
    resp = api.create_decision(
        ctx["cycle"]["id"], create_decision_payload(ctx["candidate"]["id"]),
        make_do_headers(iv1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # A clean officer succeeds
    resp = api.create_decision(ctx["cycle"]["id"], create_decision_payload(ctx["candidate"]["id"]), DO)
    validate_success(resp, expected_status=201)


def test_cycle_create_rejects_unvalidated_instrument(api):
    """PRD §3.4: "Creation is gated on four cross-entity conditions, evaluated after
    ownership: the requisition must be `OPEN` (`ERR_REQUISITION_NOT_OPEN`), the
    instrument must be `VALIDATED` (`ERR_INSTRUMENT_NOT_VALIDATED`), the vendor must be
    `ACTIVE` with the instrument's `vendor_suspended` flag false
    (`ERR_VENDOR_NOT_ACTIVE`), and the guide must be `APPROVED`
    (`ERR_GUIDE_NOT_APPROVED`)."

    A cycle referencing a DRAFT instrument is rejected at create.

    Design: Corner/validations/cycle_create_rejects_unvalidated_instrument
    """
    vendor = create_vendor()
    instrument = create_instrument(vendor["id"])  # stays DRAFT
    guide = get_success_data(api_client.create_guide(create_guide_payload(), ADMIN))
    get_success_data(api_client.pilot_guide(guide["id"], ADMIN))
    get_success_data(api_client.approve_guide(guide["id"], ADMIN2))
    req = create_requisition(HM)
    resp = api.create_cycle(
        req["id"], create_cycle_payload(instrument["id"], guide["id"]), HM,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_VALIDATED)


def test_scorecard_void_blocked_after_decision(api):
    """PRD §3.6: "no finalized hiring decision may yet exist for that candidate in that
    cycle (else `ERR_DECISION_ALREADY_FINALIZED`)".

    Design: Corner/validations/scorecard_void_blocked_after_decision
    """
    ctx = setup_decided_candidate()
    sc1 = ctx["scorecards"][0]
    resp = api.void_scorecard(
        sc1["id"], void_scorecard_payload(void_reason="Late conflict-of-interest disclosure."), CO,
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_ALREADY_FINALIZED)
    data = validate_success(api.get_scorecard(sc1["id"], ADMIN))
    assert data["status"] == "SUBMITTED"


def test_session_duration_bounds(api):
    """PRD §3.6: "the session must last at least fifteen minutes and at most four hours
    (240 minutes) with `scheduled_end` strictly after `scheduled_start`, else
    `ERR_SESSION_DURATION_INVALID` (HTTP 400)".

    10 minutes and 241 minutes rejected; exactly 15 and exactly 240 accepted.

    Design: Corner/validations/session_duration_bounds
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)

    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T09:10:00Z"), HM)
    validate_error(resp, ApiErrorId.ERR_SESSION_DURATION_INVALID)
    validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T09:15:00Z"), HM),
        expected_status=201)
    validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-13T09:00:00Z", scheduled_end="2026-08-13T13:00:00Z"), HM),
        expected_status=201)
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-14T09:00:00Z", scheduled_end="2026-08-14T13:01:00Z"), HM)
    validate_error(resp, ApiErrorId.ERR_SESSION_DURATION_INVALID)


def test_rationale_min_length_boundary(api):
    """PRD §3.8: "a `rationale` of at least fifty characters (`ERR_RATIONALE_TOO_SHORT`,
    HTTP 400)".

    49 characters rejected; exactly 50 accepted.

    Design: Corner/validations/rationale_min_length_boundary
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    cycle = ctx["cycle"]
    c1 = ctx["candidate"]
    assert len("Candidate did fine overall in panel sessions toda") == 49
    resp = api.create_decision(
        cycle["id"],
        create_decision_payload(c1["id"], rationale="Candidate did fine overall in panel sessions toda"),
        DO,
    )
    validate_error(resp, ApiErrorId.ERR_RATIONALE_TOO_SHORT)
    assert len("Candidate did fine overall in panel sessions today") == 50
    resp = api.create_decision(
        cycle["id"],
        create_decision_payload(c1["id"], rationale="Candidate did fine overall in panel sessions today"),
        DO,
    )
    validate_success(resp, expected_status=201)


def test_begin_scoring_blocked_with_scheduled_sessions(api):
    """PRD §3.4: "the hiring manager begins scoring, moving `ACTIVE` → `SCORING`; the
    transition requires zero sessions still in `SCHEDULED` within the cycle, else
    `ERR_SESSIONS_STILL_SCHEDULED` (HTTP 409)".

    Design: Corner/validations/begin_scoring_blocked_with_scheduled_sessions
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
        scheduled_start="2026-08-14T10:00:00Z", scheduled_end="2026-08-14T11:00:00Z"), HM))
    resp = api.begin_cycle_scoring(cycle["id"], HM)
    validate_error(resp, ApiErrorId.ERR_SESSIONS_STILL_SCHEDULED)
    validate_success(api.cancel_session(s1["id"], HM))
    resp = api.begin_cycle_scoring(cycle["id"], HM)
    assert validate_success(resp)["posture"] == "SCORING"


def test_requisition_close_blocked_with_open_cycles(api):
    """PRD §3.4: "Closing a requisition — from `OPEN` or `FILLED` — is an owner-only
    operation and requires every cycle of the requisition to have reached `CLOSED`;
    otherwise the close is refused with `ERR_CYCLE_NOT_CLOSED` (HTTP 409)."

    Design: Corner/validations/requisition_close_blocked_with_open_cycles
    """
    ctx = setup_active_cycle()
    req = ctx["requisition"]
    cycle = ctx["cycle"]
    resp = api.close_requisition(req["id"], HM)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSED)
    validate_success(api.close_cycle(cycle["id"], HM))
    resp = api.close_requisition(req["id"], HM)
    assert validate_success(resp)["status"] == "CLOSED"


def test_unfreeze_missing_resolution_note_returns_400(api):
    """PRD §3.4: "It requires a `resolution_note` of at least twenty characters
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/validations/unfreeze_missing_resolution_note_returns_400
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    validate_success(api.freeze_cycle(cycle["id"], freeze_cycle_payload(), CO))
    resp = api.unfreeze_cycle(cycle["id"], {}, CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["posture"] == "FROZEN"


def test_duplicate_scorecard_per_session_rejected(api):
    """PRD §3.6: "A session carries at most one non-`VOIDED` scorecard; a second live
    scorecard is `ERR_DUPLICATE_SCORECARD` (HTTP 409)."

    Design: Corner/validations/duplicate_scorecard_per_session_rejected
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = book_completed_session(cycle["id"], c1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    headers = make_interviewer_headers(interviewer["id"])
    validate_success(api.create_scorecard(
        s1["id"], create_scorecard_payload(ratings=[{"competency_code": "COMM", "rating": 4}]),
        headers,
    ), expected_status=201)
    resp = api.create_scorecard(
        s1["id"], create_scorecard_payload(ratings=[{"competency_code": "ANAL", "rating": 5}]),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORECARD)


def test_duplicate_calibration_open_record_rejected(api):
    """PRD §3.6: "at most one record per interviewer-guide pair may be open — that is,
    in `TRAINED` or `CALIBRATED` — at a time, a duplicate drawing
    `ERR_DUPLICATE_CALIBRATION` (HTTP 409)."

    Design: Corner/validations/duplicate_calibration_open_record_rejected
    """
    guide = get_success_data(api_client.create_guide(create_guide_payload(), ADMIN))
    get_success_data(api_client.pilot_guide(guide["id"], ADMIN))
    get_success_data(api_client.approve_guide(guide["id"], ADMIN2))
    iv1 = create_interviewer(full_name="Ivy One", email="ivy1@x.com")
    get_success_data(api.create_calibration(iv1["id"], create_calibration_payload(guide["id"]), ADMIN))
    resp = api.create_calibration(iv1["id"], create_calibration_payload(guide["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CALIBRATION)


def test_supersede_non_approved_guide_rejected(api):
    """PRD §3.3: "Creating a revision of an existing guide requires the target to be
    `APPROVED` — otherwise `ERR_GUIDE_NOT_APPROVED`".

    Design: Corner/validations/supersede_non_approved_guide_rejected
    """
    g1 = get_success_data(api_client.create_guide(create_guide_payload(title="Guide v1"), ADMIN))
    resp = api.create_guide_revision(g1["id"], create_guide_revision_payload(g1["version"]), ADMIN2)
    validate_error(resp, ApiErrorId.ERR_GUIDE_NOT_APPROVED)


def test_guide_retire_while_pinned_rejected(api):
    """PRD §3.3: "Retirement of a guide by direct request is admitted from `DRAFT`,
    `PILOT`, or `APPROVED` but only while the guide's `pinned_cycle_count` — the number
    of assessment cycles pinning this guide whose posture is not `CLOSED` — is zero; a
    pinned guide refuses retirement with `ERR_GUIDE_PINNED` (HTTP 409)."

    Design: Corner/validations/guide_retire_while_pinned_rejected
    """
    ctx = setup_active_cycle()
    pinned_guide = ctx["guide"]  # pinned by ctx["cycle"] (non-CLOSED)
    free_guide = get_success_data(api_client.create_guide(create_guide_payload(title="Guide Free"), ADMIN))
    get_success_data(api_client.pilot_guide(free_guide["id"], ADMIN))
    get_success_data(api_client.approve_guide(free_guide["id"], ADMIN2))
    resp = api.retire_guide(pinned_guide["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_GUIDE_PINNED)
    resp = api.retire_guide(free_guide["id"], ADMIN)
    assert validate_success(resp)["status"] == "RETIRED"


def test_scorecard_window_closed_isolated(api):
    """PRD §3.6: "the logical now must be no later than seventy-two hours after the
    session's `completed_at` — the boundary is inclusive, and a submission later than
    that is `ERR_SCORECARD_WINDOW_CLOSED` (HTTP 422)".

    Sessions completed at clock 2026-08-12T11:00:00Z; submitting at exactly
    2026-08-15T11:00:00Z succeeds, at +1s fails.

    Design: Corner/validations/scorecard_window_closed_isolated
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    # Book both sessions first, then complete BOTH at clock 2026-08-12T11:00:00Z so
    # their 72h windows close at exactly 2026-08-15T11:00:00Z.
    s1 = get_success_data(api.create_session(cycle["id"], create_session_payload(
        c1["id"], iv1["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T10:00:00Z"), HM))
    s2 = get_success_data(api.create_session(cycle["id"], create_session_payload(
        c1["id"], iv2["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM))
    api.set_clock(set_clock_payload("2026-08-12T11:00:00Z"), ADMIN)
    get_success_data(api.complete_session(s1["id"], HM))
    get_success_data(api.complete_session(s2["id"], HM))
    sc1 = get_success_data(api.create_scorecard(
        s1["id"], create_scorecard_payload(ratings=[{"competency_code": "COMM", "rating": 4}]),
        make_interviewer_headers(iv1["id"])))
    sc2 = get_success_data(api.create_scorecard(
        s2["id"], create_scorecard_payload(ratings=[{"competency_code": "COMM", "rating": 5}]),
        make_interviewer_headers(iv2["id"])))
    # At exactly completed_at + 72h: inclusive boundary admits submission
    api.set_clock(set_clock_payload("2026-08-15T11:00:00Z"), ADMIN)
    resp = api.submit_scorecard(sc1["id"], make_interviewer_headers(iv1["id"]))
    assert validate_success(resp)["status"] == "SUBMITTED"
    # One second later the window has closed
    api.set_clock(set_clock_payload("2026-08-15T11:00:01Z"), ADMIN)
    resp = api.submit_scorecard(sc2["id"], make_interviewer_headers(iv2["id"]))
    validate_error(resp, ApiErrorId.ERR_SCORECARD_WINDOW_CLOSED)
    data = validate_success(api.get_scorecard(sc2["id"], ADMIN))
    assert data["status"] == "DRAFT"


def test_feedback_after_retention_expired_rejected(api):
    """PRD §3.9: "the feedback gate is inclusive, permitting feedback at the exact
    expiry instant" — and §3.8: "the retention window must still be open, meaning
    `retention_expires_at` is either not yet set or the logical now is at or before
    it — exactly at expiry still passes, later is `ERR_RETENTION_EXPIRED` (HTTP 422)".

    Decision anchored 2026-08-15T12:00:00Z + 730 days -> expiry 2028-08-14T12:00:00Z;
    one second past expiry feedback fails while the assessment is still COMPLETED
    (no sweep has run).

    Design: Corner/validations/feedback_after_retention_expired_rejected
    """
    ctx = setup_decided_candidate(retention_days=730)
    api.set_clock(set_clock_payload("2028-08-14T12:00:01Z"), ADMIN)
    resp = api.send_feedback(
        ctx["assessment"]["id"],
        {"feedback_text": "Panel feedback summary for your records."},
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_RETENTION_EXPIRED)
    after = validate_success(api.get_assessment(ctx["assessment"]["id"], HM))
    assert after["feedback_status"] == "NOT_SENT"
    assert after["admin_status"] == "COMPLETED"


def test_feedback_already_sent_rejected(api):
    """PRD §3.8: "the `feedback_status` must still be `NOT_SENT`, a second send drawing
    `ERR_FEEDBACK_ALREADY_SENT` (HTTP 409)".

    Design: Corner/validations/feedback_already_sent_rejected
    """
    ctx = setup_decided_candidate()
    validate_success(api.send_feedback(ctx["assessment"]["id"],
                                       {"feedback_text": "Strong panel performance; advance to final round."}, HM))
    resp = api.send_feedback(
        ctx["assessment"]["id"],
        {"feedback_text": "Duplicate feedback attempt text here."},
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_FEEDBACK_ALREADY_SENT)
