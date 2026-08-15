"""Corner coverage — endpoints, errors, rbac, cross-cutting layers, and consistency:
snapshot immutability, decision preconditions, error envelope, role denials and
ownership-scoped lists, guide version pinning, monitor-flag freeze, adverse-impact
unfreeze gate, and immediate consistency."""
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
    create_validated_instrument,
    create_guide_payload,
    create_guide_revision_payload,
    create_approved_guide,
    create_requisition,
    create_cycle_payload,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    create_calibrated_interviewer,
    create_interviewer,
    create_session_payload,
    create_snapshot_payload,
    create_decision_payload,
    freeze_cycle_payload,
    unfreeze_cycle_payload,
    create_content_ledger_event_payload,
    set_clock_payload,
    setup_active_cycle,
    setup_quorum_ready_candidate,
    setup_decided_candidate,
    book_completed_session,
    submit_scorecard,
    make_interviewer_headers,
    make_candidate_headers,
    make_vendorrep_headers,
    make_do_headers,
    assert_snapshot,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]
DO = TEST_USERS["do_headers"]


# ---------------------------------------------------------------------------
# Corner/endpoints
# ---------------------------------------------------------------------------

def test_snapshot_computed_read_is_persisted_and_immutable(api):
    """PRD §3.7: "The snapshot is immutable once computed, is stamped with the logical
    time as `computed_at`, and persists its full result in `group_breakdowns`,
    `highest_rate_group_code`, and `flagged`."

    A GET by id returns the persisted snapshot identical to the POST response; a later
    POST creates a new id and never mutates the first.

    Design: Corner/endpoints/snapshot_computed_read_is_persisted_and_immutable
    """
    ctx = setup_active_cycle(openings_count=4)
    cycle = ctx["cycle"]
    for ref in ("C-A1", "C-A2"):
        c = create_candidate(external_ref=ref, full_name=f"Cand {ref}",
                             email=f"{ref.lower()}@x.com", group_code="GROUP_A")
        a = invite_candidate(cycle["id"], c["id"])
        schedule_assessment(a["id"])
    resp = api.create_adverse_impact_snapshot(cycle["id"], create_snapshot_payload(), CO)
    sn1 = validate_success(resp, expected_status=201)
    resp = api.create_adverse_impact_snapshot(
        cycle["id"], create_snapshot_payload(snapshot_type="FINAL"), CO,
    )
    sn2 = validate_success(resp, expected_status=201)
    assert sn1["id"] != sn2["id"], "every POST persists a new immutable snapshot row"
    rb = validate_success(api.get_adverse_impact_snapshot(sn1["id"], CO))
    assert rb["snapshot_type"] == "PROVISIONAL"
    assert rb["computed_at"] == sn1["computed_at"], "persisted at write, unchanged later"
    assert rb["group_breakdowns"] == sn1["group_breakdowns"]
    assert rb["flagged"] == sn1["flagged"]


def test_decision_rejected_when_assessment_not_completed(api):
    """PRD §3.8: "the candidate's assessment in the cycle must be `COMPLETED`
    (`ERR_ASSESSMENT_NOT_COMPLETED`)".

    A merely SCHEDULED candidate's decision is rejected before quorum is evaluated.

    Design: Corner/endpoints/decision_rejected_when_assessment_not_completed
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"])
    resp = api.create_decision(cycle["id"], create_decision_payload(c1["id"]), DO)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_COMPLETED)


# ---------------------------------------------------------------------------
# Corner/errors
# ---------------------------------------------------------------------------

def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format" — the body's response_type is error and its data carries an
    error_id machine string plus a human-readable message — and "The `meta` object
    for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api.get_interviewer(NON_EXISTENT_UUID, ADMIN)
    body = resp.json()
    assert body.get("response_type") == "error"
    data = body.get("data", {})
    assert data.get("error_id") == "ERR_NOT_FOUND"
    assert isinstance(data.get("message"), str) and len(data["message"]) > 0
    meta = body.get("meta", {})
    assert meta.get("api_request_id", "").startswith("req_")
    assert set(meta.keys()) <= {"api_request_id", "api_request_timestamp"}


# ---------------------------------------------------------------------------
# Corner/rbac
# ---------------------------------------------------------------------------

def test_decision_officer_cannot_void_scorecard(api):
    """PRD §4: scorecard void is listed as ComplianceOfficer-only, and §2.1: "If the
    authenticated role is not listed among the roles authorized for the endpoint, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/decision_officer_cannot_void_scorecard
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    sc1 = ctx["scorecards"][0]
    resp = api.void_scorecard(
        sc1["id"],
        {"void_reason": "Officer attempting to void a scorecard."},
        DO,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_compliance_officer_cannot_create_guide(api):
    """PRD §4: guide creation is listed as TalentAssessmentAdmin-only; §2.1 rejects
    unlisted roles with `ERR_FORBIDDEN` (HTTP 403).

    Design: Corner/rbac/compliance_officer_cannot_create_guide
    """
    resp = api_client.create_guide(
        create_guide_payload(title="Compliance Guide"), CO,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_candidate_reads_own_decision(api):
    """PRD §2.10: "when a `Candidate` lists sessions or decisions and supplies the
    `candidate_id` filter, it likewise must equal their `X-User-ID`; and a `Candidate`
    listing assessments must pass `candidate_id` equal to their own `X-User-ID`." and
    "A filter naming anyone else is `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/candidate_reads_own_decision
    """
    ctx = setup_decided_candidate()
    c1 = ctx["candidate"]
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    # Own filter: sees exactly the decision
    data, _meta = validate_paginated(
        api.list_decisions(make_candidate_headers(c1["id"]), params={"candidate_id": c1["id"]})
    )
    assert [d["id"] for d in data] == [ctx["decision"]["id"]]
    # Another candidate's id: ownership mismatch
    resp = api.list_decisions(make_candidate_headers(c1["id"]), params={"candidate_id": c2["id"]})
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_vendorrep_distribute_direction_forbidden(api):
    """PRD §3.1: "Only the administrator may record a `DISTRIBUTE`, and only while the
    vendor is `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`); a `DESTROY` may be recorded
    by the administrator or by the vendor's own representative — the chain-of-custody
    segregation of duties, in which the admin distributes and the vendor confirms
    destruction — while the vendor is `ACTIVE` or `SUSPENDED`."

    A representative DISTRIBUTE is ERR_FORBIDDEN; an admin DESTROY succeeds.

    Design: Corner/rbac/vendorrep_distribute_direction_forbidden
    """
    vendor = create_vendor()
    validate_success(api.create_content_ledger_event(
        vendor["id"],
        create_content_ledger_event_payload(direction="DISTRIBUTE", copies=3,
                                            note="Initial workbook shipment out."),
        ADMIN,
    ), expected_status=201)
    resp = api.create_content_ledger_event(
        vendor["id"],
        create_content_ledger_event_payload(direction="DISTRIBUTE", copies=1,
                                            note="Rep tries to record distribution."),
        make_vendorrep_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    resp = api.create_content_ledger_event(
        vendor["id"],
        create_content_ledger_event_payload(direction="DESTROY", copies=1,
                                            note="Admin records destruction instead."),
        ADMIN,
    )
    validate_success(resp, expected_status=201)
    v = validate_success(api.get_vendor(vendor["id"], ADMIN))
    assert v["content_copies_outstanding"] == 2


def test_interviewer_list_filter_ownership(api):
    """PRD §2.10: "When an `Interviewer` lists calibration records, sessions, or
    scorecards and supplies the `interviewer_id` filter, the supplied value must equal
    their `X-User-ID`" and "A filter naming anyone else is `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/interviewer_list_filter_ownership
    """
    iv1 = create_interviewer(full_name="Ivy One", email="ivy1@x.com")
    iv2 = create_interviewer(full_name="Ivy Two", email="ivy2@x.com")
    resp = api.list_sessions(make_interviewer_headers(iv1["id"]),
                             params={"interviewer_id": iv2["id"]})
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    resp = api.list_sessions(make_interviewer_headers(iv1["id"]),
                             params={"interviewer_id": iv1["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers
# ---------------------------------------------------------------------------

def test_version_pinning_keeps_retired_guide_usable(api):
    """PRD §3.6: "finally the version pin — the supplied `guide_id` must equal the
    cycle's pinned `guide_id`, else `ERR_GUIDE_VERSION_MISMATCH` (HTTP 422), which is
    how the system guarantees a cycle is scored against exactly the rubric it was
    created with."

    After supersede-approval retires the pinned guide, a session naming the new
    approved guide is rejected while the retired pinned guide is still accepted.

    Design: Corner/cross_cutting_layers/version_pinning_keeps_retired_guide_usable
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    g1 = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(g1["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    # Supersede g1 -> g2; approving g2 retires g1
    g1_now = get_success_data(api.get_guide(g1["id"], ADMIN))
    g2 = get_success_data(api.create_guide_revision(
        g1["id"], create_guide_revision_payload(g1_now["version"]), ADMIN2,
    ))
    get_success_data(api_client.pilot_guide(g2["id"], ADMIN2))
    get_success_data(api_client.approve_guide(g2["id"], ADMIN))
    g1_after = get_success_data(api.get_guide(g1["id"], ADMIN))
    assert g1_after["status"] == "RETIRED"
    # The CURRENT APPROVED guide g2 does not match the pin
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv1["id"], g2["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_GUIDE_VERSION_MISMATCH)
    # The pinned (RETIRED) guide is still the one that works inside its cycle
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv1["id"], g1["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_success(resp, expected_status=201)


def test_adverse_impact_monitor_flag_controls_freeze(api):
    """PRD §3.7: "A flagged `FINAL` snapshot taken while the cycle is `ACTIVE` or
    `SCORING` freezes the cycle — posture to `FROZEN`, `frozen_from_posture` capturing
    the prior posture, `frozen_reason` of `ADVERSE_IMPACT` — but only when the cycle's
    instrument has `adverse_impact_monitor_enabled` set to true; with monitoring
    disabled, a flagged final snapshot is recorded without disturbing the cycle."

    Design: Corner/cross_cutting_layers/adverse_impact_monitor_flag_controls_freeze
    """
    vendor = create_vendor()
    i_off = create_validated_instrument(vendor["id"], adverse_impact_monitor_enabled=False,
                                        code="COG-OFF", title="Battery OFF")
    i_on = create_validated_instrument(vendor["id"], adverse_impact_monitor_enabled=True,
                                       code="COG-ON", title="Battery ON")
    guide = create_approved_guide()
    req = create_requisition(HM, openings_count=10)
    cycles = {}
    for key, instrument in (("off", i_off), ("on", i_on)):
        cycle = get_success_data(api.create_cycle(
            req["id"], create_cycle_payload(instrument["id"], guide["id"],
                                            label=f"Cycle {key.upper()}"), HM,
        ))
        get_success_data(api.activate_cycle(cycle["id"], HM))
        cycles[key] = cycle

    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")

    def _two_groups_one_decided(cycle, prefix, day):
        """GROUP_A: 2 COMPLETED, one decided ADVANCE. GROUP_B: 2 COMPLETED, no decision.
        FINAL rates: A 0.5000, B 0.0000 -> flagged."""
        cands = {}
        for suffix, grp in (("A1", "GROUP_A"), ("A2", "GROUP_A"),
                            ("B1", "GROUP_B"), ("B2", "GROUP_B")):
            cands[suffix] = create_candidate(
                external_ref=f"C-{prefix}{suffix}", full_name=f"Cand {prefix}{suffix}",
                email=f"c{prefix.lower()}{suffix.lower()}@x.com", group_code=grp,
            )
        raws = {"A1": 60, "A2": 55, "B1": 50, "B2": 45}
        for suffix, c in cands.items():
            invite_and_complete_candidate(cycle["id"], c["id"], raw_score=raws[suffix])
        # Quorum for candidate A1: two submitted scorecards
        s1 = book_completed_session(cycle["id"], cands["A1"]["id"], iv1["id"], guide["id"],
                                    f"2026-08-{day}T09:00:00Z", f"2026-08-{day}T10:00:00Z")
        s2 = book_completed_session(cycle["id"], cands["A1"]["id"], iv2["id"], guide["id"],
                                    f"2026-08-{day}T10:00:00Z", f"2026-08-{day}T11:00:00Z")
        submit_scorecard(s1["id"], iv1["id"],
                         ratings=[{"competency_code": "COMM", "rating": 4},
                                  {"competency_code": "ANAL", "rating": 4}])
        submit_scorecard(s2["id"], iv2["id"],
                         ratings=[{"competency_code": "COMM", "rating": 4},
                                  {"competency_code": "ANAL", "rating": 4}])
        resp = api.create_decision(cycle["id"], create_decision_payload(cands["A1"]["id"]), DO)
        validate_success(resp, expected_status=201)

    _two_groups_one_decided(cycles["off"], "F", 12)
    _two_groups_one_decided(cycles["on"], "N", 13)

    # FINAL snapshot on the monitor-disabled cycle: flagged but no freeze
    resp = api.create_adverse_impact_snapshot(
        cycles["off"]["id"], create_snapshot_payload(snapshot_type="FINAL"), CO,
    )
    snap_off = validate_success(resp, expected_status=201)
    assert snap_off["flagged"] is True
    cyc_off = validate_success(api.get_cycle(cycles["off"]["id"], CO))
    assert cyc_off["posture"] == "ACTIVE", "monitoring disabled -> cycle undisturbed"

    # FINAL snapshot on the monitor-enabled cycle: flagged and frozen
    resp = api.create_adverse_impact_snapshot(
        cycles["on"]["id"], create_snapshot_payload(snapshot_type="FINAL"), CO,
    )
    snap_on = validate_success(resp, expected_status=201)
    assert snap_on["flagged"] is True
    cyc_on = validate_success(api.get_cycle(cycles["on"]["id"], CO))
    assert cyc_on["posture"] == "FROZEN"
    assert cyc_on["frozen_reason"] == "ADVERSE_IMPACT"
    assert cyc_on["frozen_from_posture"] == "ACTIVE"
    # A FINAL snapshot now exists, so the unfreeze gate is satisfiable
    resp = api.unfreeze_cycle(
        cycles["on"]["id"],
        unfreeze_cycle_payload(resolution_note="Reviewed FINAL snapshot; remediation plan filed."),
        CO,
    )
    assert validate_success(resp)["posture"] == "ACTIVE"


def test_adverse_impact_unfreeze_requires_final_snapshot(api):
    """PRD §3.4: "unfreezing an `ADVERSE_IMPACT` hold requires at least one `FINAL`
    adverse-impact snapshot to exist for the cycle, else `ERR_ADVERSE_IMPACT_UNRESOLVED`
    (HTTP 422) — so a manual hold placed before any snapshot cannot be lifted until a
    final snapshot has been computed".

    Design: Corner/cross_cutting_layers/adverse_impact_unfreeze_requires_final_snapshot
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    resp = api.freeze_cycle(
        cycle["id"],
        freeze_cycle_payload(freeze_reason="ADVERSE_IMPACT",
                             reason_note="Proactive hold pending metrics."),
        CO,
    )
    frozen = validate_success(resp)
    assert frozen["posture"] == "FROZEN"
    assert frozen["frozen_reason"] == "ADVERSE_IMPACT"
    # Unfreeze without any FINAL snapshot is rejected
    resp = api.unfreeze_cycle(
        cycle["id"],
        unfreeze_cycle_payload(resolution_note="Attempting release without any snapshot."),
        CO,
    )
    validate_error(resp, ApiErrorId.ERR_ADVERSE_IMPACT_UNRESOLVED)
    # Snapshot creation is admitted while FROZEN
    resp = api.create_adverse_impact_snapshot(
        cycle["id"], create_snapshot_payload(snapshot_type="FINAL"), CO,
    )
    snap = validate_success(resp, expected_status=201)
    assert snap["flagged"] is False, "empty cycle: all groups INSUFFICIENT_N"
    # With a FINAL on file, unfreeze succeeds
    resp = api.unfreeze_cycle(
        cycle["id"],
        unfreeze_cycle_payload(resolution_note="FINAL snapshot reviewed and documented."),
        CO,
    )
    assert validate_success(resp)["posture"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/consistency_model
# ---------------------------------------------------------------------------

def test_immediate_consistency_on_transition_and_derived_count(api):
    """PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field" — the activate response itself carries
    the new posture; and §3.5: "Inviting a candidate into a cycle creates a candidate
    assessment in `INVITED` status and increments the cycle's `active_candidate_count`"
    — a directly following read shows the derived counter already updated.

    Design: Corner/consistency_model/immediate_consistency_on_transition_and_derived_count
    """
    from test_helpers import create_validated_instrument, create_approved_guide
    vendor = create_vendor()
    instrument = create_validated_instrument(vendor["id"])
    guide = create_approved_guide()
    req = create_requisition(HM)
    cycle = get_success_data(api.create_cycle(
        req["id"], create_cycle_payload(instrument["id"], guide["id"]), HM,
    ))
    resp = api.activate_cycle(cycle["id"], HM)
    activated = validate_success(resp)
    assert activated["posture"] == "ACTIVE", "transition response carries the new posture"
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    resp = api.create_invitation(cycle["id"], {"candidate_id": c1["id"]}, HM)
    validate_success(resp, expected_status=201)
    after = validate_success(api.get_cycle(cycle["id"], HM))
    assert after["active_candidate_count"] == 1
    assert after["posture"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/difficulty_covered_stubs (the one non-stub instance in that section)
# ---------------------------------------------------------------------------

def test_candidate_withdraw_cascade(api):
    """PRD §3.5: "Withdrawal of the candidate altogether — by the candidate (whose
    `X-User-ID` must equal the candidate's `id`) or by a hiring manager — moves the
    candidate `ACTIVE` → `WITHDRAWN` and fans the same cascade across every cycle: each
    of the candidate's assessments in `INVITED`, `SCHEDULED`, `ACCOMMODATION_HOLD`, or
    `IN_PROGRESS` is cancelled with the count decrement and unsent-feedback flip; each
    of the candidate's `SCHEDULED` sessions anywhere is cancelled with
    `cancellation_reason` of `CANDIDATE_WITHDRAWN` and the minutes debit; and every
    `PENDING` accommodation request on those assessments is withdrawn. Inviting or
    withdrawing an already-`WITHDRAWN` candidate fails with `ERR_CANDIDATE_WITHDRAWN`
    (HTTP 409)."

    The COMPLETED assessment is terminal and untouched by the cascade — and
    because "those assessments" scopes the accommodation withdrawal to the
    assessments the cascade actually cancels, the PENDING request on the
    COMPLETED assessment survives while the one on the still-INVITED second
    assessment is withdrawn.

    Design: Corner/difficulty_covered_stubs/candidate_withdraw_cascade
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _ = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"])
    # PENDING accommodation filed by the candidate while SCHEDULED
    from test_helpers import create_accommodation_request_payload
    ar1 = validate_success(api.create_accommodation_request(
        a1["id"], create_accommodation_request_payload(), make_candidate_headers(c1["id"]),
    ), expected_status=201)
    # Complete the assessment (terminal) and book a SCHEDULED session afterwards
    api.set_clock(set_clock_payload("2026-08-10T09:00:00Z"), ADMIN)
    get_success_data(api.start_assessment(a1["id"], HM))
    get_success_data(api.complete_assessment(a1["id"], {"raw_score": 72}, HM))
    s1 = get_success_data(api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], interviewer["id"], guide["id"],
                               scheduled_start="2026-08-14T10:00:00Z",
                               scheduled_end="2026-08-14T11:00:00Z"),
        HM,
    ))
    mins_pre = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins_pre == 60

    # Second cycle (same requisition/instrument/guide): c1 merely INVITED, with a
    # PENDING accommodation — an assessment the cascade DOES cancel.
    from test_helpers import create_cycle_payload
    cycle2 = get_success_data(api.create_cycle(
        ctx["requisition"]["id"],
        create_cycle_payload(ctx["instrument"]["id"], guide["id"], label="Second Cycle"),
        HM,
    ))
    get_success_data(api.activate_cycle(cycle2["id"], HM))
    a2 = invite_candidate(cycle2["id"], c1["id"])
    ar2 = validate_success(api.create_accommodation_request(
        a2["id"], create_accommodation_request_payload(), make_candidate_headers(c1["id"]),
    ), expected_status=201)

    resp = api.withdraw_candidate(c1["id"], make_candidate_headers(c1["id"]))
    assert validate_success(resp)["status"] == "WITHDRAWN"
    # Terminal assessment untouched
    a1_after = validate_success(api.get_assessment(a1["id"], HM))
    assert a1_after["admin_status"] == "COMPLETED"
    assert a1_after["feedback_status"] == "NOT_SENT"
    # Session cascade
    sess = validate_success(api.get_session(s1["id"], ADMIN))
    assert sess["status"] == "CANCELLED"
    assert sess["cancellation_reason"] == "CANDIDATE_WITHDRAWN"
    mins_post = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins_post == 0
    # PENDING accommodation on the terminal assessment is NOT in the cascade's
    # scope ("those assessments" = the cancelled ones) -> survives as PENDING
    ar = validate_success(api.get_accommodation_request(ar1["id"], CO))
    assert ar["status"] == "PENDING"
    # PENDING accommodation on the cancelled (INVITED) assessment IS withdrawn
    a2_after = validate_success(api.get_assessment(a2["id"], HM))
    assert a2_after["admin_status"] == "CANCELLED"
    ar2_after = validate_success(api.get_accommodation_request(ar2["id"], CO))
    assert ar2_after["status"] == "WITHDRAWN"
    # Count not decremented for the terminal assessment
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["active_candidate_count"] == 1
    cyc2 = validate_success(api.get_cycle(cycle2["id"], CO))
    assert cyc2["active_candidate_count"] == 0
    # Re-inviting the withdrawn candidate is rejected
    resp = api.create_invitation(cycle["id"], {"candidate_id": c1["id"]}, HM)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_WITHDRAWN)
