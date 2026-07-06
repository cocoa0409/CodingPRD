"""Quarantine holds, release windows, and the escalation / void cascades."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS,
    set_clock, investigating_case, make_kennel, make_impound,
    make_quarantine_hold, make_rabies_report,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]

BITE_COMPLAINT = {"animal_type": "DOG", "complaint_type": "BITE"}


# ==========================================================================
# Difficulty: non_linear_state_machine / quarantine_branching_divergent_side_effects
# ==========================================================================
def test_escalate_hold_euthanizes_held_impound(api):
    """PRD 3.5: "A Supervisor may escalate a hold when the animal turns
    symptomatic, moving it from ACTIVE to ESCALATED. Escalation triggers a
    cascade: every impound on the same case still in HELD is euthanized (driven
    from HELD to EUTHANIZED), which in turn frees the kennel and escalates the
    case's outstanding rabies reports and flags the case for public health, as
    detailed in Section 3.6."

    Design: Difficulty/non_linear_state_machine/quarantine_branching_divergent_side_effects
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-2")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           hold_until="2026-03-20T00:00:00Z")
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="FACILITY_QUARANTINE")
    escalated = validate_success(api.escalate_quarantine_hold(hold["id"], SUPERVISOR))
    assert escalated["status"] == "ESCALATED"
    impound_after = validate_success(api.get_impound(impound["id"], SUPERVISOR))
    assert impound_after["status"] == "EUTHANIZED"


def test_release_branch_leaves_impound_held(api):
    """PRD 3.5: "A hold may be released by a FieldOfficer or Supervisor, moving
    it from ACTIVE to RELEASED, but only once the observation window has elapsed:
    the logical clock must be at or after release_due_at."

    Design: Difficulty/non_linear_state_machine/quarantine_branching_divergent_side_effects
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-2b")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           hold_until="2026-03-20T00:00:00Z")
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="FACILITY_QUARANTINE",
                                start_at="2026-03-01T00:00:00Z")
    set_clock(api, "2026-03-11T00:00:00Z")  # bite hold: release_due = start + 10 days
    released = validate_success(api.release_quarantine_hold(hold["id"], SUPERVISOR))
    assert released["status"] == "RELEASED"
    # The RELEASED branch carries no euthanasia cascade, unlike ESCALATED.
    impound_after = validate_success(api.get_impound(impound["id"], SUPERVISOR))
    assert impound_after["status"] == "HELD"


# ==========================================================================
# Difficulty: transitive_cascade / escalate_hold_impound_rabies_case_depth3
# ==========================================================================
def _setup_escalation_chain(api):
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    kennel = make_kennel(api, code="K-3")
    impound = make_impound(api, ctx["case"]["id"], kennel["id"], ctx["case_version"],
                           hold_until="2026-03-20T00:00:00Z")
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="FACILITY_QUARANTINE")
    report = make_rabies_report(api, ctx["case"]["id"], hold["id"], victim_name="Pat V")
    return ctx, kennel, impound, hold, report


def test_escalation_cascade_full_chain(api):
    """PRD 3.5: "Escalation triggers a cascade: every impound on the same case
    still in HELD is euthanized (driven from HELD to EUTHANIZED), which in turn
    frees the kennel and escalates the case's outstanding rabies reports and
    flags the case for public health, as detailed in Section 3.6." PRD 3.6: "but
    this cascade additionally escalates every rabies report on the same case
    (matched by case_id) still in SUBMITTED, driving each from SUBMITTED to
    ESCALATED."

    Design: Difficulty/transitive_cascade/escalate_hold_impound_rabies_case_depth3
    """
    ctx, kennel, impound, hold, report = _setup_escalation_chain(api)
    escalated = validate_success(api.escalate_quarantine_hold(hold["id"], SUPERVISOR))
    assert escalated["status"] == "ESCALATED"
    assert validate_success(api.get_impound(impound["id"], SUPERVISOR))["status"] == "EUTHANIZED"
    assert validate_success(api.get_kennel(kennel["id"], SUPERVISOR))["occupied_slots"] == 0
    assert validate_success(api.get_rabies_report(report["id"], SUPERVISOR))["status"] == "ESCALATED"


def test_escalation_cascade_flags_case_and_bumps_risk(api):
    """PRD 3.6: "Each such rabies escalation is itself consequential: it sets the
    linked case's public_health_flag to true and adds 20 points to the case's
    risk_score, clamped to the range 0 through 100."

    Design: Difficulty/transitive_cascade/escalate_hold_impound_rabies_case_depth3
    """
    ctx, kennel, impound, hold, report = _setup_escalation_chain(api)
    validate_success(api.escalate_quarantine_hold(hold["id"], SUPERVISOR))
    case_after = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    assert case_after["public_health_flag"] is True
    # Provisional risk 70 (40 + 0.5*60) + 20 escalation bonus = 90.00.
    assert case_after["risk_score"] == pytest.approx(90.00, abs=0.01)


# ==========================================================================
# Difficulty: transitive_cascade / unfounded_resolve_hold_rabies_depth2
# ==========================================================================
def _setup_unfounded_chain(api):
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="HOME_QUARANTINE")
    report = make_rabies_report(api, ctx["case"]["id"], hold["id"], victim_name="Lee V")
    return ctx, hold, report


def test_unfounded_resolution_voids_hold_and_clears_report(api):
    """PRD 3.4: "Resolving as unfounded advances the case from
    UNDER_INVESTIGATION to UNFOUNDED and sets risk_score to 0; it additionally
    cascades to every quarantine hold on that case still in ACTIVE, driving each
    from ACTIVE to VOIDED (with the further downstream effects described in
    Section 3.5)." PRD 3.5: "voiding cascades to every rabies report tied to that
    hold by quarantine_hold_id still in SUBMITTED, driving each from SUBMITTED to
    CLEARED."

    Design: Difficulty/transitive_cascade/unfounded_resolve_hold_rabies_depth2
    """
    ctx, hold, report = _setup_unfounded_chain(api)
    resolved = validate_success(api.resolve_case(ctx["case"]["id"], {"resolution": "UNFOUNDED"}, SUPERVISOR))
    assert resolved["status"] == "UNFOUNDED"
    assert resolved["risk_score"] == pytest.approx(0.00, abs=0.01)
    assert validate_success(api.get_quarantine_hold(hold["id"], SUPERVISOR))["status"] == "VOIDED"
    assert validate_success(api.get_rabies_report(report["id"], SUPERVISOR))["status"] == "CLEARED"


def test_unfounded_void_cascade_reaches_rabies_report(api):
    """PRD 3.5: "the system itself voids a hold as part of unfounded-case
    resolution: each ACTIVE hold on a case resolved unfounded is driven from
    ACTIVE to VOIDED, and voiding cascades to every rabies report tied to that
    hold by quarantine_hold_id still in SUBMITTED, driving each from SUBMITTED to
    CLEARED."

    Design: Difficulty/transitive_cascade/unfounded_resolve_hold_rabies_depth2
    """
    ctx, hold, report = _setup_unfounded_chain(api)
    validate_success(api.resolve_case(ctx["case"]["id"], {"resolution": "UNFOUNDED"}, SUPERVISOR))
    assert validate_success(api.get_quarantine_hold(hold["id"], SUPERVISOR))["status"] == "VOIDED"
    assert validate_success(api.get_rabies_report(report["id"], SUPERVISOR))["status"] == "CLEARED"


# ==========================================================================
# Difficulty: boundary_precision_check / quarantine_release_datetime_boundary_inclusive
# ==========================================================================
def test_release_at_exactly_due_instant_permitted(api):
    """PRD 3.5: "A hold may be released by a FieldOfficer or Supervisor, moving
    it from ACTIVE to RELEASED, but only once the observation window has elapsed:
    the logical clock must be at or after release_due_at. The boundary is
    inclusive — a clock reading exactly release_due_at is releasable — and any
    earlier attempt is rejected with ERR_QUARANTINE_NOT_ELAPSED."

    Design: Difficulty/boundary_precision_check/quarantine_release_datetime_boundary_inclusive
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="HOME_QUARANTINE",
                                start_at="2026-03-01T00:00:00Z")
    set_clock(api, "2026-03-11T00:00:00Z")
    released = validate_success(api.release_quarantine_hold(hold["id"], SUPERVISOR))
    assert released["status"] == "RELEASED"


def test_bite_release_due_is_ten_days_after_start(api):
    """PRD 3.5: "required_days is 10 for a bite case and 14 for a dangerous-dog
    case (and 10 for any other eligible input). The release_due_at is start_at
    advanced by exactly that many days."

    Design: Difficulty/boundary_precision_check/quarantine_release_datetime_boundary_inclusive
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="HOME_QUARANTINE",
                                start_at="2026-03-01T00:00:00Z")
    assert hold["required_days"] == 10
    assert hold["release_due_at"].startswith("2026-03-11T00:00:00")
    set_clock(api, "2026-03-11T00:00:00Z")
    assert validate_success(api.release_quarantine_hold(hold["id"], SUPERVISOR))["status"] == "RELEASED"


# ==========================================================================
# Corner: validations
# ==========================================================================
def test_quarantine_on_stray_case_not_eligible(api):
    """PRD 3.5: "Placing an animal under observation is permitted only when the
    linked case's case_type is BITE or DANGEROUS_DOG — any other type is
    ERR_CASE_TYPE_NOT_ELIGIBLE — and only when the case is in
    UNDER_INVESTIGATION or SUBSTANTIATED, otherwise ERR_CASE_NOT_ACTIONABLE."

    Design: Corner/validations/quarantine_on_stray_case_not_eligible
    """
    ctx = investigating_case(api, case_type="STRAY")
    resp = api.create_quarantine_hold(
        {"case_id": ctx["case"]["id"], "hold_type": "HOME_QUARANTINE", "start_at": "2026-03-01T00:00:00Z"},
        SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CASE_TYPE_NOT_ELIGIBLE)


def test_release_before_due_rejected(api):
    """PRD 3.5: "The boundary is inclusive — a clock reading exactly
    release_due_at is releasable — and any earlier attempt is rejected with
    ERR_QUARANTINE_NOT_ELAPSED."

    Design: Corner/validations/quarantine_release_before_due_rejected
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    hold = make_quarantine_hold(api, ctx["case"]["id"], hold_type="HOME_QUARANTINE",
                                start_at="2026-03-01T00:00:00Z")
    set_clock(api, "2026-03-10T00:00:00Z")  # one day before the 2026-03-11 due instant
    resp = api.release_quarantine_hold(hold["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED)
