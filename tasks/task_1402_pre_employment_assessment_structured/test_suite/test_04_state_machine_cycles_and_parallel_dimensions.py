"""Non-linear state machines: instrument validation cycle, freeze/unfreeze revert-loop,
and the parallel feedback/admin dimensions of a candidate assessment."""
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
    create_requisition,
    create_cycle_payload,
    create_snapshot_payload,
    set_clock_payload,
    freeze_cycle_payload,
    unfreeze_cycle_payload,
    feedback_payload,
    setup_active_cycle,
    setup_decided_candidate,
    setup_purged_assessment,
    plus_days,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/instrument_validation_expiry_revalidation_cycle
# ---------------------------------------------------------------------------

def _build_instrument_cycle_setup():
    """Instrument VALIDATED; CRITERION until 2026-09-01, CONTENT until 2026-09-01;
    plus an approved guide and an open requisition for later cycle-create attempts.

    Both pillars share the 2026-09-01 expiry so that, once the clock moves past
    it, the original CRITERION record is no longer current — the revalidation
    min-rule then provably recomputes from the freshly filed evidence only."""
    vendor = create_vendor()
    instrument = create_instrument(vendor["id"])
    file_evidence(instrument["id"], evidence_type="CRITERION",
                  effective_until="2026-09-01T00:00:00Z")
    file_evidence(instrument["id"], evidence_type="CONTENT",
                  effective_until="2026-09-01T00:00:00Z")
    get_success_data(api_client.submit_instrument_validation_review(instrument["id"], ADMIN))
    instrument = get_success_data(api_client.validate_instrument(instrument["id"], ADMIN))
    guide = create_approved_guide()
    requisition = create_requisition(HM, openings_count=1)
    return vendor, instrument, guide, requisition


def test_instrument_validity_expires_at_is_min_of_current_evidence(api):
    """PRD §3.2: "A successful validation sets `validity_expires_at` to the earliest
    `effective_until` among the currently valid `CRITERION` and `CONTENT` records".

    CRITERION until 2026-09-01, CONTENT until 2026-09-01 -> validity_expires_at
    is the 2026-09-01T00:00:00Z instant.

    Design: Difficulty/non_linear_state_machine/instrument_validation_expiry_revalidation_cycle
    """
    from test_helpers import assert_iso_instant_equal
    _, instrument, _, _ = _build_instrument_cycle_setup()
    assert instrument["validation_status"] == "VALIDATED"
    assert_iso_instant_equal(instrument["validity_expires_at"], "2026-09-01T00:00:00Z")


def test_instrument_expires_strictly_after_validity_and_gates_cycle_create(api):
    """PRD §3.2: "when the logical clock advances strictly beyond `validity_expires_at`,
    the instrument moves `VALIDATED` → `EXPIRED`, with no cascade to cycles — the gating
    is enforced at cycle creation and activation instead."
    PRD §3.4: "the instrument must be `VALIDATED` (`ERR_INSTRUMENT_NOT_VALIDATED`)".

    Design: Difficulty/non_linear_state_machine/instrument_validation_expiry_revalidation_cycle
    """
    _, instrument, guide, requisition = _build_instrument_cycle_setup()
    resp = api.set_clock(set_clock_payload("2026-09-02T00:00:00Z"), ADMIN)
    sweep = validate_success(resp)
    assert sweep["instruments_expired"] == 1
    data = validate_success(api.get_instrument(instrument["id"], ADMIN))
    assert data["validation_status"] == "EXPIRED"
    resp = api.create_cycle(
        requisition["id"],
        create_cycle_payload(instrument["id"], guide["id"], label="Late Cycle",
                             administration_window_start="2026-09-10T00:00:00Z",
                             administration_window_end="2026-09-20T00:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUMENT_NOT_VALIDATED)


def test_begin_revalidation_requires_fresh_criterion_evidence(api):
    """PRD §3.2: "An expired instrument may begin revalidation, moving `EXPIRED` →
    `REVALIDATION`, only when at least one `CRITERION` record has been filed strictly
    after `validity_expires_at` (its `filed_at` later than the expiry instant), else
    `ERR_EVIDENCE_TYPE_MISSING`".

    Design: Difficulty/non_linear_state_machine/instrument_validation_expiry_revalidation_cycle
    """
    _, instrument, _, _ = _build_instrument_cycle_setup()
    api.set_clock(set_clock_payload("2026-09-02T00:00:00Z"), ADMIN)
    # Before any fresh CRITERION evidence: rejected
    resp = api.begin_instrument_revalidation(instrument["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_TYPE_MISSING)
    # File fresh CRITERION evidence (filed_at = now = 2026-09-02 > expiry 2026-09-01)
    file_evidence(instrument["id"], evidence_type="CRITERION", title="Fresh criterion study",
                  effective_from="2026-09-01T00:00:00Z", effective_until="2028-01-01T00:00:00Z")
    resp = api.begin_instrument_revalidation(instrument["id"], ADMIN)
    data = validate_success(resp)
    assert data["validation_status"] == "REVALIDATION"


def test_revalidation_validate_fails_on_expired_content_then_succeeds(api):
    """PRD §3.2: "when records of the type exist but none is current, the failure is
    `ERR_EVIDENCE_EXPIRED` (HTTP 422)" and "revalidation then re-enters the validation
    gate above, which recomputes `validity_expires_at` from the current evidence."

    Design: Difficulty/non_linear_state_machine/instrument_validation_expiry_revalidation_cycle
    """
    _, instrument, _, _ = _build_instrument_cycle_setup()
    api.set_clock(set_clock_payload("2026-09-02T00:00:00Z"), ADMIN)
    file_evidence(instrument["id"], evidence_type="CRITERION", title="Fresh criterion study",
                  effective_from="2026-09-01T00:00:00Z", effective_until="2028-01-01T00:00:00Z")
    api.begin_instrument_revalidation(instrument["id"], ADMIN)
    # CONTENT evidence exists but is expired (effective_until 2026-09-01 <= now)
    resp = api.validate_instrument(instrument["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_EXPIRED)
    # Fresh CONTENT evidence clears the gate
    file_evidence(instrument["id"], evidence_type="CONTENT", title="Fresh content study",
                  effective_from="2026-09-01T00:00:00Z", effective_until="2027-12-01T00:00:00Z")
    resp = api.validate_instrument(instrument["id"], ADMIN)
    data = validate_success(resp)
    assert data["validation_status"] == "VALIDATED"
    # min over current CRITERION (2028-01-01) + CONTENT (2027-12-01) = 2027-12-01
    from test_helpers import assert_iso_instant_equal
    assert_iso_instant_equal(data["validity_expires_at"], "2027-12-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/candidate_assessment_parallel_dimensions
# ---------------------------------------------------------------------------

def test_feedback_sent_survives_purge(api):
    """PRD §3.9: "an unsent `feedback_status` flips to `NOT_APPLICABLE` while a sent one
    is untouched."
    PRD §3.8: "the parallel feedback dimension evolves independently of `admin_status`."

    Design: Difficulty/non_linear_state_machine/candidate_assessment_parallel_dimensions
    """
    ctx = setup_decided_candidate(retention_days=730)
    assessment = ctx["assessment"]
    # Pre-feedback: dimensions sit at COMPLETED / NOT_SENT independently
    before = validate_success(api.get_assessment(assessment["id"], HM))
    assert before["admin_status"] == "COMPLETED"
    assert before["feedback_status"] == "NOT_SENT"
    # retention_expires_at = finalized_at (2026-08-15T12:00:00Z) + 730 days
    from test_helpers import assert_iso_instant_equal
    expected_expiry = plus_days("2026-08-15T12:00:00Z", 730)
    assert_iso_instant_equal(before["retention_expires_at"], expected_expiry)
    # Send feedback: only the feedback dimension moves
    resp = api.send_feedback(assessment["id"], feedback_payload(), HM)
    sent = validate_success(resp)
    assert sent["feedback_status"] == "SENT"
    mid = validate_success(api.get_assessment(assessment["id"], HM))
    assert mid["admin_status"] == "COMPLETED"
    # Purge past expiry + 1s
    from test_helpers.fixtures import _plus_one_second
    api.set_clock(set_clock_payload(_plus_one_second(expected_expiry)), ADMIN)
    sweep = validate_success(api.run_retention_sweep(CO))
    assert sweep["purged_count"] == 1
    after = validate_success(api.get_assessment(assessment["id"], HM))
    assert after["admin_status"] == "PURGED"
    assert after["composite_score"] is None
    assert after["raw_score"] is None
    assert after["feedback_status"] == "SENT", (
        "purge does not touch the feedback dimension once SENT"
    )
    # Exactly one purge event carrying the audit snapshot of retention_expires_at
    events = validate_success(api.list_purge_events(assessment["id"], CO))
    assert len(events) == 1
    assert events[0]["event_type"] == "ASSESSMENT_PURGED"
    assert_iso_instant_equal(events[0]["retention_expires_at_snapshot"], expected_expiry)


def test_purge_nulls_scores_and_stamps_purged_at(api):
    """PRD §3.9: "Each purged assessment moves `COMPLETED` → `PURGED`; its `raw_score`,
    `composite_score`, and `completed_at` are nulled and `purged_at` is stamped".

    Design: Difficulty/non_linear_state_machine/candidate_assessment_parallel_dimensions
    """
    ctx = setup_purged_assessment()
    assessment = ctx["assessment"]
    after = validate_success(api.get_assessment(assessment["id"], HM))
    assert after["admin_status"] == "PURGED"
    assert after["raw_score"] is None
    assert after["composite_score"] is None
    assert after["completed_at"] is None
    assert after["purged_at"] is not None


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/cycle_freeze_unfreeze_restores_prior_posture
# ---------------------------------------------------------------------------

def test_freeze_unfreeze_active_roundtrip(api):
    """PRD §3.4: "Freezing captures the prior posture in `frozen_from_posture` and
    stores the `frozen_reason`; outside a freeze, both fields are null. Unfreezing
    returns the cycle to exactly the posture captured in `frozen_from_posture` —
    `SETUP`, `ACTIVE`, or `SCORING` — and clears both frozen fields."

    Design: Difficulty/non_linear_state_machine/cycle_freeze_unfreeze_restores_prior_posture
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    resp = api.freeze_cycle(cycle["id"], freeze_cycle_payload(), CO)
    frozen = validate_success(resp)
    assert frozen["posture"] == "FROZEN"
    assert frozen["frozen_from_posture"] == "ACTIVE"
    assert frozen["frozen_reason"] == "MANUAL"
    resp = api.unfreeze_cycle(cycle["id"], unfreeze_cycle_payload(), CO)
    restored = validate_success(resp)
    assert restored["posture"] == "ACTIVE"
    assert restored["frozen_from_posture"] is None
    assert restored["frozen_reason"] is None


def test_freeze_unfreeze_scoring_roundtrip_restores_scoring(api):
    """PRD §3.4: "Unfreezing returns the cycle to exactly the posture captured in
    `frozen_from_posture` — `SETUP`, `ACTIVE`, or `SCORING` — and clears both frozen
    fields."

    A SCORING -> FROZEN -> unfreeze must land back on SCORING, not ACTIVE.

    Design: Difficulty/non_linear_state_machine/cycle_freeze_unfreeze_restores_prior_posture
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    # No sessions exist, so begin-scoring is clean
    resp = api.begin_cycle_scoring(cycle["id"], HM)
    assert validate_success(resp)["posture"] == "SCORING"
    resp = api.freeze_cycle(cycle["id"], freeze_cycle_payload(reason_note="Second manual hold for audit."), CO)
    frozen = validate_success(resp)
    assert frozen["posture"] == "FROZEN"
    assert frozen["frozen_from_posture"] == "SCORING"
    resp = api.unfreeze_cycle(cycle["id"], unfreeze_cycle_payload(resolution_note="Audit complete; resume scoring."), CO)
    restored = validate_success(resp)
    assert restored["posture"] == "SCORING", "restore target is the captured posture, not a fixed state"
    assert restored["frozen_from_posture"] is None
    assert restored["frozen_reason"] is None
