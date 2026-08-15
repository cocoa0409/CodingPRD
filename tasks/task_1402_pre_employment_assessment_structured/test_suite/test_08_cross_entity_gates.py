"""Cross-entity state gates: cycle activate gated by instrument/guide state,
session create gated by calibration state, feedback gated by decision existence."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_vendor,
    create_instrument,
    file_evidence,
    create_approved_guide,
    create_guide,
    create_requisition,
    create_cycle_payload,
    create_candidate,
    create_interviewer,
    create_calibration_payload,
    certify_calibration_payload,
    create_session_payload,
    set_clock_payload,
    setup_active_cycle,
    create_calibrated_interviewer,
    invite_and_complete_candidate,
    setup_quorum_ready_candidate,
    setup_decided_candidate,
    feedback_payload,
    create_decision_payload,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
DO = TEST_USERS["do_headers"]


def _validated_instrument(vendor_id, content_until="2027-08-01T00:00:00Z", **overrides):
    instrument = create_instrument(vendor_id, **overrides)
    file_evidence(instrument["id"], evidence_type="CRITERION")
    file_evidence(instrument["id"], evidence_type="CONTENT", effective_until=content_until)
    get_success_data(api_client.submit_instrument_validation_review(instrument["id"], ADMIN))
    return get_success_data(api_client.validate_instrument(instrument["id"], ADMIN))


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/cycle_activate_gated_by_instrument_and_guide_states
# ---------------------------------------------------------------------------

def _build_two_cycle_gate_setup():
    """i1 VALIDATED with CONTENT until 2026-09-01 (ages to EXPIRED at 2026-09-02);
    g1 APPROVED; cy1 pins i1+g1 with a September window.
    i2 VALIDATED until 2027-08-01; g2 APPROVED; cy2 pins i2+g2.

    g2 must be APPROVED at cy2 creation — PRD §3.4 gates cycle *creation* on the
    guide being APPROVED, so a cycle pinning a PILOT guide cannot be constructed
    through the API at all. The only PRD-reachable path to a pinned guide that is
    no longer APPROVED is supersede-approval retiring it (§3.3), which
    test_cycle_activate_rejected_when_guide_only_pilot performs."""
    vendor = create_vendor()
    i1 = _validated_instrument(vendor["id"], content_until="2026-09-01T00:00:00Z", code="COG-A")
    i2 = _validated_instrument(vendor["id"], code="COG-B", instrument_type="JOB_KNOWLEDGE",
                               title="Job Knowledge B", max_score=50, pass_floor=20)
    g1 = create_approved_guide(title="Guide One")
    g2 = create_approved_guide(
        title="Guide Two",
        rubric_items=[{"competency_code": "COMM", "weight": 0.5, "scale_max": 5},
                      {"competency_code": "ANAL", "weight": 0.5, "scale_max": 5}],
    )

    req = create_requisition(HM)
    cy1 = get_success_data(api_client.create_cycle(
        req["id"], create_cycle_payload(i1["id"], g1["id"], label="Cycle One",
                                        administration_window_start="2026-09-10T00:00:00Z",
                                        administration_window_end="2026-09-20T00:00:00Z"), HM))
    cy2 = get_success_data(api_client.create_cycle(
        req["id"], create_cycle_payload(i2["id"], g2["id"], label="Cycle Two"), HM))
    return cy1, cy2


def test_cycle_activate_rejected_when_instrument_expired(api):
    """PRD §3.4: "then the readiness tier — instrument `VALIDATED`
    (`ERR_INSTRUMENT_NOT_VALIDATED`), vendor `ACTIVE` and instrument not
    vendor-suspended (`ERR_VENDOR_NOT_ACTIVE`), guide `APPROVED`
    (`ERR_GUIDE_NOT_APPROVED`)".
    PRD §3.2: "when the logical clock advances strictly beyond `validity_expires_at`,
    the instrument moves `VALIDATED` → `EXPIRED`, with no cascade to cycles — the
    gating is enforced at cycle creation and activation instead."

    Design: Difficulty/cross_entity_state_dependency/cycle_activate_gated_by_instrument_and_guide_states
    """
    cy1, _ = _build_two_cycle_gate_setup()
    api.set_clock(set_clock_payload("2026-09-02T00:00:00Z"), ADMIN)
    resp = api.activate_cycle(cy1["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_VALIDATED)


def test_cycle_activate_rejected_when_guide_only_pilot(api):
    """PRD §3.4: "guide `APPROVED` (`ERR_GUIDE_NOT_APPROVED`)" — a cycle whose pinned
    guide is no longer APPROVED cannot activate.

    A pinned guide cannot return to PILOT through any PRD transition; the one
    reachable path to a non-APPROVED pinned guide is supersede-approval, which
    "retires a guide regardless of pins" (PRD §3.3). Retire cy2's pinned guide
    that way, then activation hits the guide-readiness gate.

    Design: Difficulty/cross_entity_state_dependency/cycle_activate_gated_by_instrument_and_guide_states
    """
    from test_helpers import create_guide_revision_payload
    _, cy2 = _build_two_cycle_gate_setup()
    cy2 = get_success_data(api.get_cycle(cy2["id"], HM))
    g2_id = cy2["guide_id"]
    g2 = get_success_data(api.get_guide(g2_id, ADMIN))
    # Supersede g2 and approve the successor -> g2 is retired despite the pin
    g3 = get_success_data(api.create_guide_revision(
        g2_id, create_guide_revision_payload(g2["version"]), TEST_USERS["admin2_headers"],
    ))
    get_success_data(api_client.pilot_guide(g3["id"], TEST_USERS["admin2_headers"]))
    get_success_data(api_client.approve_guide(g3["id"], ADMIN))
    g2_after = get_success_data(api.get_guide(g2_id, ADMIN))
    assert g2_after["status"] == "RETIRED"
    # Clock stays at startup 2026-08-01: window 2026-08-10..2026-08-20 is still open
    resp = api.activate_cycle(cy2["id"], HM)
    validate_error(resp, ApiErrorId.ERR_GUIDE_NOT_APPROVED)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/session_create_gated_by_calibration_record_state
# ---------------------------------------------------------------------------

def _build_trained_only_interviewer_setup():
    """Cycle ACTIVE pinning g; c1 COMPLETED; iv1 holds a TRAINED (uncertified) record."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1 = create_interviewer(full_name="Ivy One", email="ivy1@x.com")
    resp = api_client.create_calibration(iv1["id"], create_calibration_payload(guide["id"]), ADMIN)
    cal1 = get_success_data(resp)
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    return ctx, iv1, cal1, c1


def test_session_create_rejected_while_calibration_trained(api):
    """PRD §3.6: "then the safety gate — the interviewer must hold a `CALIBRATED`
    calibration record for the cycle's pinned guide, else `ERR_INTERVIEWER_NOT_CALIBRATED`
    (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/session_create_gated_by_calibration_record_state
    """
    ctx, iv1, _cal1, c1 = _build_trained_only_interviewer_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv1["id"], guide["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_NOT_CALIBRATED)


def test_session_create_succeeds_after_certify(api):
    """PRD §3.6: "Certification moves `TRAINED` → `CALIBRATED`, requires the guide to be
    `PILOT` or `APPROVED` (else `ERR_GUIDE_NOT_APPROVED`), and requires a
    `practice_score` of at least 0.7000" — and the safety gate requires "a `CALIBRATED`
    calibration record for the cycle's pinned guide", so the same session request
    succeeds after certification flips the record.

    Design: Difficulty/cross_entity_state_dependency/session_create_gated_by_calibration_record_state
    """
    ctx, iv1, cal1, c1 = _build_trained_only_interviewer_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    resp = api.certify_calibration(cal1["id"], certify_calibration_payload(), ADMIN)
    assert validate_success(resp)["status"] == "CALIBRATED"
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv1["id"], guide["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/feedback_gated_by_decision_finalized
# ---------------------------------------------------------------------------

def test_feedback_rejected_before_decision_finalized(api):
    """PRD §3.8: "a finalized hiring decision must exist for that candidate in that
    cycle, else `ERR_DECISION_NOT_FINALIZED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/feedback_gated_by_decision_finalized
    """
    ctx = setup_quorum_ready_candidate(num_sessions=2, raw_score=72)
    resp = api.send_feedback(ctx["assessment"]["id"], feedback_payload(), HM)
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_FINALIZED)


def test_feedback_succeeds_after_decision_finalized(api):
    """PRD §3.8: "Sending feedback moves the assessment's `feedback_status` from
    `NOT_SENT` to `SENT`".

    Once the FINALIZED decision exists, the same feedback call succeeds.

    Design: Difficulty/cross_entity_state_dependency/feedback_gated_by_decision_finalized
    """
    ctx = setup_decided_candidate()
    resp = api.send_feedback(ctx["assessment"]["id"], feedback_payload(), HM)
    sent = validate_success(resp)
    assert sent["feedback_status"] == "SENT"
