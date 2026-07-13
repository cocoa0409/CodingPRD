"""Violation penalties (per-violation rounding then aggregation, cure-deadline
boundary), escalation threshold, and the remediation revision / resolution cycles.
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, get_success_data,
    validate_success, validate_error,
    make_landlord_headers, make_inspector_headers,
    setup_property_with_violations, get_property, list_property_violations,
    schedule_inspection, begin_inspection, record_item,
    list_property_notices,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _by_code(violations, code):
    for v in violations:
        if v["code"] == code:
            return v
    raise AssertionError(f"no violation with code {code} in {[v['code'] for v in violations]}")


def _two_major_violations(api):
    """FAILED periodic (conducted 2026-06-01T09:00) minting two OPEN MAJOR violations
    (PLUMBING, HEAT); property stays REGISTERED (no critical)."""
    return setup_property_with_violations(
        api,
        fail_items=[{"category": "HABITABILITY", "code": "PLUMBING", "severity": "MAJOR"},
                    {"category": "HABITABILITY", "code": "HEAT", "severity": "MAJOR"}],
        pass_items=[{"category": "LIFE_SAFETY", "code": "SMOKE_DETECTOR"}],
    )


def _two_critical_violations(api):
    """FAILED periodic minting two OPEN CRITICAL violations (FIRE_EXIT, MOLD);
    property is SUSPENDED."""
    return setup_property_with_violations(
        api,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"},
                    {"category": "HABITABILITY", "code": "MOLD", "severity": "CRITICAL"}],
    )


# --- Difficulty: combinatorial_formula / property_penalty_total_rounding_order

def test_property_penalty_total_rounds_per_violation_then_sums(api):
    """PRD §3.6: "The per-violation penalties are each rounded to whole cents first, in
    created_at ascending order for deterministic accumulation, and only then summed — the
    rounding is never deferred to a single final rounding of the raw total."
    PRD §3.6: "Finally a 7.5% administrative fee is applied — the capped raw amount is
    multiplied by 1.075 and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/property_penalty_total_rounding_order
    """
    ctx = _two_major_violations(api)
    get_success_data(api.set_clock("2026-06-16T09:00:00Z", REGISTRAR))  # 1 day past 14-day deadline
    prop = get_property(api, ctx["property_id"])
    # each: 2500*1 day = 2500 raw, *1.075 = 2687.5 -> 2688; 2688+2688 = 5376 (not round(5375.0)).
    assert prop["total_penalty_cents"] == 5376


def test_each_major_violation_penalty_rounds_up(api):
    """PRD §3.6: "the daily rates are 1000 cents for MINOR, 2500 for MAJOR, and 10000 for
    CRITICAL, and the caps are 30000, 75000, and 300000 cents respectively. Finally a 7.5%
    administrative fee is applied — the capped raw amount is multiplied by 1.075 and rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/property_penalty_total_rounding_order
    """
    ctx = _two_major_violations(api)
    get_success_data(api.set_clock("2026-06-16T09:00:00Z", REGISTRAR))
    violations = list_property_violations(api, ctx["property_id"])
    for v in violations:
        assert v["penalty_cents"] == 2688, "round_half_up(2500 * 1.075) == round(2687.5) == 2688"


# --- Difficulty: boundary_precision_check / violation_penalty_zero_exactly_at_cure_deadline

def test_penalty_zero_exactly_at_cure_deadline(api):
    """PRD §3.6: "The clock is compared against the violation's cure_deadline, which is its
    originating inspection's conducted_at plus the severity's cure window (30 days for MINOR, 14
    for MAJOR, 3 for CRITICAL). At or before the cure deadline the penalty is exactly 0; strictly
    after it, the penalty is positive."

    Design: Difficulty/boundary_precision_check/violation_penalty_zero_exactly_at_cure_deadline
    """
    ctx = _two_major_violations(api)
    get_success_data(api.set_clock("2026-06-15T09:00:00Z", REGISTRAR))  # exactly conducted+14d
    v0 = list_property_violations(api, ctx["property_id"])[0]
    data = validate_success(api.get_violation(v0["id"], REGISTRAR))
    assert data["penalty_cents"] == 0, "clock exactly at cure_deadline → penalty 0"
    assert data["cure_deadline"].startswith("2026-06-15T09:00:00")


def test_penalty_positive_strictly_after_cure_deadline(api):
    """PRD §3.6: "At or before the cure deadline the penalty is exactly 0; strictly after it,
    the penalty is positive."

    Design: Difficulty/boundary_precision_check/violation_penalty_zero_exactly_at_cure_deadline
    """
    ctx = _two_major_violations(api)
    get_success_data(api.set_clock("2026-06-16T09:00:00Z", REGISTRAR))  # one day after deadline
    v0 = list_property_violations(api, ctx["property_id"])[0]
    data = validate_success(api.get_violation(v0["id"], REGISTRAR))
    assert data["penalty_cents"] > 0, "strictly after cure_deadline → positive penalty"


# --- Difficulty: boundary_precision_check / escalation_critical_count_at_two

def test_escalate_succeeds_at_exactly_two_critical(api):
    """PRD §3.6: "Escalation is permitted only when the violation is OPEN, its severity is
    CRITICAL, and the property's count of critical violations meets the escalation threshold of 2.
    That escalation count is the number of the property's violations whose severity is CRITICAL and
    whose status is either OPEN or REMEDIATION_SUBMITTED; exactly one such violation is not enough,
    while two or more is eligible."

    Design: Difficulty/boundary_precision_check/escalation_critical_count_at_two
    """
    ctx = _two_critical_violations(api)
    v0 = list_property_violations(api, ctx["property_id"])[0]
    data = get_success_data(api.escalate_violation(v0["id"], REGISTRAR))
    assert data["status"] == "ESCALATED", "count == 2 satisfies the >= 2 boundary"


def test_escalate_dispatches_violation_notice(api):
    """PRD §3.6: "Escalating a violation dispatches a VIOLATION_NOTICE tenant notice, created in
    SENT, for the property."

    Design: Difficulty/boundary_precision_check/escalation_critical_count_at_two
    """
    ctx = _two_critical_violations(api)
    v0 = list_property_violations(api, ctx["property_id"])[0]
    get_success_data(api.escalate_violation(v0["id"], REGISTRAR))
    notices = list_property_notices(api, ctx["property_id"])
    violation_notices = [n for n in notices if n["notice_type"] == "VIOLATION_NOTICE"]
    assert len(violation_notices) == 1
    assert violation_notices[0]["status"] == "SENT"


# --- Corner: validations / escalate_below_threshold_returns_error --------

def test_escalate_below_threshold_returns_error(api):
    """PRD §3.6: "exactly one such violation is not enough, while two or more is eligible. If the
    threshold is not met, escalation is rejected with ERR_ESCALATION_THRESHOLD_NOT_MET."

    Design: Corner/validations/escalate_below_threshold_returns_error
    """
    ctx = setup_property_with_violations(
        api,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"}],
        pass_items=[{"category": "HABITABILITY", "code": "HEAT"}],
    )
    v0 = list_property_violations(api, ctx["property_id"])[0]
    resp = api.escalate_violation(v0["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_THRESHOLD_NOT_MET.value)
    data = validate_success(api.get_violation(v0["id"], REGISTRAR))
    assert data["status"] == "OPEN", "unchanged"


# --- Difficulty: non_linear_state_machine / violation_remediation_revision_cycle

def _remediation_submitted_plumbing(api):
    """Two MAJOR violations; the PLUMBING one moved to REMEDIATION_SUBMITTED by the landlord."""
    ctx = _two_major_violations(api)
    violations = list_property_violations(api, ctx["property_id"])
    v_plumb = _by_code(violations, "PLUMBING")
    get_success_data(api.submit_remediation(v_plumb["id"], {"remediation_notes": "fixed the pipe"},
                                            make_landlord_headers(ctx["landlord_id"])))
    ctx["v_plumb"] = v_plumb
    return ctx


def test_remediation_submitted_intermediate_state(api):
    """PRD §3.6: "The owning Landlord responds by submitting remediation on an OPEN violation,
    which moves it to REMEDIATION_SUBMITTED".

    Design: Difficulty/non_linear_state_machine/violation_remediation_revision_cycle
    """
    ctx = _remediation_submitted_plumbing(api)
    data = validate_success(api.get_violation(ctx["v_plumb"]["id"], REGISTRAR))
    assert data["status"] == "REMEDIATION_SUBMITTED"


def test_remediation_reverts_to_open_on_reinspection_fail(api):
    """PRD §3.4: "If that item's result is FAIL and the violation was in REMEDIATION_SUBMITTED,
    the violation reverts to OPEN."

    Design: Difficulty/non_linear_state_machine/violation_remediation_revision_cycle
    """
    ctx = _remediation_submitted_plumbing(api)
    get_success_data(api.set_clock("2026-06-03T09:00:00Z", REGISTRAR))  # prior conducted + >=48h
    reins = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                                "2026-06-03T09:00:00Z", inspection_type="REINSPECTION",
                                prior_inspection_id=ctx["inspection"]["id"])
    begin_inspection(api, reins["id"], ctx["inspector_id"])
    record_item(api, reins["id"], ctx["inspector_id"], "LIFE_SAFETY", "SMOKE_DETECTOR", "PASS")
    record_item(api, reins["id"], ctx["inspector_id"], "HABITABILITY", "PLUMBING", "FAIL",
                severity="MAJOR")
    get_success_data(api.complete_inspection(reins["id"], make_inspector_headers(ctx["inspector_id"])))
    data = validate_success(api.get_violation(ctx["v_plumb"]["id"], REGISTRAR))
    assert data["status"] == "OPEN", "reinspection re-recorded PLUMBING FAIL → revert to OPEN"


# --- Difficulty: compensating_invariant / open_violation_count_conserved -----

def _single_major_violation_remediated(api):
    """FAILED periodic minting exactly one MAJOR violation (LIFE_SAFETY omitted forces the
    synthetic-critical final FAIL); landlord then submits remediation. Property REGISTERED."""
    ctx = setup_property_with_violations(
        api,
        fail_items=[{"category": "HABITABILITY", "code": "PLUMBING", "severity": "MAJOR"}],
    )
    v0 = list_property_violations(api, ctx["property_id"])[0]
    get_success_data(api.submit_remediation(v0["id"], {"remediation_notes": "repaired"},
                                            make_landlord_headers(ctx["landlord_id"])))
    ctx["violation"] = v0
    return ctx


def test_open_violation_count_rises_on_issue(api):
    """PRD §3.4: "When a PERIODIC or COMPLAINT inspection fails, each checklist item whose result
    is FAIL produces a new violation in status OPEN."
    PRD §3.4: "The property's open_violation_count rises by the number of violations created."

    Design: Difficulty/compensating_invariant/open_violation_count_conserved_on_issue_then_resolve
    """
    ctx = _single_major_violation_remediated(api)
    assert get_property(api, ctx["property_id"])["open_violation_count"] == 1


def test_open_violation_count_conserved_on_resolution(api):
    """PRD §3.4: "If that item's result is PASS, the violation is transitioned to
    VERIFIED_RESOLVED, the property's open_violation_count is decremented by one".

    Design: Difficulty/compensating_invariant/open_violation_count_conserved_on_issue_then_resolve
    """
    ctx = _single_major_violation_remediated(api)
    get_success_data(api.set_clock("2026-06-03T09:00:00Z", REGISTRAR))
    reins = schedule_inspection(api, ctx["property_id"], ctx["inspector_id"],
                                "2026-06-03T09:00:00Z", inspection_type="REINSPECTION",
                                prior_inspection_id=ctx["inspection"]["id"])
    begin_inspection(api, reins["id"], ctx["inspector_id"])
    record_item(api, reins["id"], ctx["inspector_id"], "LIFE_SAFETY", "SMOKE_DETECTOR", "PASS")
    record_item(api, reins["id"], ctx["inspector_id"], "HABITABILITY", "PLUMBING", "PASS")
    get_success_data(api.complete_inspection(reins["id"], make_inspector_headers(ctx["inspector_id"])))
    assert get_property(api, ctx["property_id"])["open_violation_count"] == 0, \
        "issue(+1) then resolve(-1) conserves the count"
    data = validate_success(api.get_violation(ctx["violation"]["id"], REGISTRAR))
    assert data["status"] == "VERIFIED_RESOLVED"
