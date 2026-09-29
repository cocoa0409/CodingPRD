"""Proctor audit risk: the two scoring variants over one identical population,
and the cyclic registration machine that carries them."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    factories as f,
    file_incident,
    get_success_data,
    resolve_incident,
    setup_landscape,
    setup_terminal_sittings,
    take_incident_into_review,
    validate_success,
)

_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]


def _proctor_with_one_old_critical_incident(api):
    """Three back-to-back terminal sittings, the OLDEST carrying a substantiated
    CRITICAL incident, then the auto-suspended proctor reinstated."""
    env = setup_landscape()
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    sittings = setup_terminal_sittings(env, proctor, candidate, count=3)

    incident = file_incident(env, sittings[0]["session"], proctor, severity="CRITICAL")
    incident = take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    resolve_incident(env, incident, outcome="SUBSTANTIATE", admin_headers=_SECURITY_ADMIN)

    validate_success(api.reinstate_proctor(
        proctor["id"], f.create_reinstatement_payload(), env["admin_headers"]))
    env.update({"candidate": candidate, "proctor": proctor, "sittings": sittings,
                "incident": incident})
    return env


def test_substantiation_absorbs_the_frozen_critical_weight_into_the_proctor(api):
    """A CRITICAL incident is worth 5, and substantiation is what banks it.

    PRD: "Each contributing incident is worth its `severity_weight`, which is 1
    for `MINOR`, 3 for `MAJOR` and 5 for `CRITICAL`, frozen at the moment the
    incident was filed."

    Design: Difficulty/dual_variant_calc/proctor_risk_rolling_window_vs_lifetime_cumulative_divergence
    """
    env = _proctor_with_one_old_critical_incident(api)
    admin = env["admin_headers"]

    proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert proctor["substantiated_incident_weight_total"] == 5
    assert proctor["registration_status"] == "REGISTERED"
    assert proctor["suspended_reason"] is None

    oldest = get_success_data(api.get_exam_session(env["sittings"][0]["session"]["id"], admin))
    assert oldest["session_status"] == "INVALIDATED"
    assert oldest["proctoring_status"] == "COMPROMISED"
    report = get_success_data(api.get_score_report(
        env["sittings"][0]["score_report"]["id"], admin))
    assert report["status"] == "VOIDED"


def test_rolling_window_variant_scores_zero_because_the_incident_fell_out_of_window(api):
    """Opening the audit uses the two-sitting window, and the incident sits on the
    third-most-recent sitting, so the operator sees 0.00.

    PRD: "It takes the two most recent sittings from that ordered population,
    sums the `severity_weight` of every `SUBSTANTIATED` incident attached to those
    two sittings, multiplies the sum by ten, divides by the fixed window size of
    two, and rounds half up to two decimal places."

    PRD: "Opening an audit never suspends the proctor by itself, and sittings
    already `ASSIGNED` to that proctor are left completely untouched while the
    audit is open"

    Design: Difficulty/dual_variant_calc/proctor_risk_rolling_window_vs_lifetime_cumulative_divergence
    """
    env = _proctor_with_one_old_critical_incident(api)

    opened = get_success_data(api.open_proctor_audit(
        env["proctor"]["id"], f.create_audit_open_payload(
            audit_reason="Post-incident registration audit"),
        env["admin_headers"]))

    assert opened["registration_status"] == "UNDER_AUDIT"
    assert opened["risk_variant_applied"] == "ROLLING_WINDOW"
    assert float(opened["risk_score"]) == 0.00
    assert opened["substantiated_incident_weight_total"] == 5
    assert opened["suspended_reason"] is None


def test_lifetime_cumulative_variant_diverges_and_forces_a_suspension_on_pass(api):
    """Closing the same audit rescores lifetime-cumulative at 5*10/3 = 16.67,
    which overrides the operator's PASS and suspends the proctor.

    PRD: "It multiplies the proctor's lifetime `substantiated_incident_weight_total`
    by ten, divides by the total number of sittings in that terminal population,
    and rounds half up to two decimal places"

    PRD: "On `PASS` the registration returns `UNDER_AUDIT → REGISTERED`, but only
    when that freshly recomputed lifetime score is strictly below 10.00; a
    lifetime score of 10.00 or more overrides the operator's intent and forces
    `UNDER_AUDIT → SUSPENDED` with `suspended_reason` `RISK_THRESHOLD_BREACH`."

    Design: Difficulty/dual_variant_calc/proctor_risk_rolling_window_vs_lifetime_cumulative_divergence
    """
    env = _proctor_with_one_old_critical_incident(api)
    admin = env["admin_headers"]

    rolling = get_success_data(api.open_proctor_audit(
        env["proctor"]["id"], f.create_audit_open_payload(), admin))
    closed = get_success_data(api.close_proctor_audit(
        env["proctor"]["id"], f.create_audit_close_payload(
            outcome="PASS", audit_note="Operator saw no in-window findings."),
        admin))

    assert closed["risk_variant_applied"] == "LIFETIME_CUMULATIVE"
    assert float(closed["risk_score"]) == 16.67
    # The very same population and the very same weight yield two different scores.
    assert float(closed["risk_score"]) - float(rolling["risk_score"]) == 16.67
    assert closed["registration_status"] == "SUSPENDED"
    assert closed["suspended_reason"] == "RISK_THRESHOLD_BREACH"


def test_registration_audit_cycle_is_re_enterable_after_two_different_exits(api):
    """REGISTERED -> UNDER_AUDIT -> REGISTERED -> UNDER_AUDIT -> SUSPENDED ->
    REGISTERED -> UNDER_AUDIT: the same two states are reached repeatedly.

    PRD: "Opening an audit supplies an `audit_reason`, advances `REGISTERED →
    UNDER_AUDIT`, recomputes `risk_score` with the `ROLLING_WINDOW` variant and
    sets `risk_variant_applied` to `ROLLING_WINDOW`."

    PRD: "On `SUSPEND` the registration moves `UNDER_AUDIT → SUSPENDED` with
    `suspended_reason` `AUDIT_FAILURE`."

    Design: Difficulty/non_linear_state_machine/proctor_registration_audit_suspension_reinstatement_cycles
    """
    env = setup_landscape()
    proctor = add_proctor(env)
    admin = env["admin_headers"]
    pid = proctor["id"]
    assert proctor["registration_status"] == "REGISTERED"

    observed = []
    observed.append(get_success_data(api.open_proctor_audit(
        pid, f.create_audit_open_payload(audit_reason="Routine cycle-1 registration audit"),
        admin))["registration_status"])
    observed.append(get_success_data(api.close_proctor_audit(
        pid, f.create_audit_close_payload(outcome="PASS"), admin))["registration_status"])
    observed.append(get_success_data(api.open_proctor_audit(
        pid, f.create_audit_open_payload(audit_reason="Cycle-2 audit after a complaint"),
        admin))["registration_status"])
    suspended = get_success_data(api.close_proctor_audit(
        pid, f.create_audit_close_payload(outcome="SUSPEND",
                                          audit_note="Roster paperwork missing"), admin))
    observed.append(suspended["registration_status"])
    reinstated = get_success_data(api.reinstate_proctor(
        pid, f.create_reinstatement_payload(remediation_ref="REM-2026-0044"), admin))
    observed.append(reinstated["registration_status"])
    reopened = get_success_data(api.open_proctor_audit(
        pid, f.create_audit_open_payload(audit_reason="Cycle-3 post-remediation audit"),
        admin))
    observed.append(reopened["registration_status"])

    assert observed == ["UNDER_AUDIT", "REGISTERED", "UNDER_AUDIT",
                        "SUSPENDED", "REGISTERED", "UNDER_AUDIT"]
    assert suspended["suspended_reason"] == "AUDIT_FAILURE"
    assert reinstated["suspended_reason"] is None
    assert reopened["risk_variant_applied"] == "ROLLING_WINDOW"
    assert float(reopened["risk_score"]) == 0.00
    assert reopened["substantiated_incident_weight_total"] == 0
    assert reopened["reserved_minutes"] == 0


def test_pass_close_on_an_empty_sitting_population_scores_zero_and_returns_registered(api):
    """With no terminal sittings the lifetime variant is 0.00 by definition, so a
    PASS close is not overridden by the suspension gate.

    PRD: "when the population is empty the result is 0.00 rather than an error"

    PRD: "Both variants share one suspension gate: a recomputed `risk_score` of
    10.00 or more forces the proctor to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/proctor_registration_audit_suspension_reinstatement_cycles
    """
    env = setup_landscape()
    proctor = add_proctor(env)
    admin = env["admin_headers"]

    get_success_data(api.open_proctor_audit(
        proctor["id"], f.create_audit_open_payload(), admin))
    passed = get_success_data(api.close_proctor_audit(
        proctor["id"], f.create_audit_close_payload(outcome="PASS",
                                                    audit_note="No findings"), admin))

    assert passed["registration_status"] == "REGISTERED"
    assert passed["suspended_reason"] is None
    assert float(passed["risk_score"]) == 0.00
    assert passed["risk_variant_applied"] == "LIFETIME_CUMULATIVE"
