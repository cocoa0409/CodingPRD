"""Compliance branching, cure/escalate boundaries, renewal gates, and the
forfeiture/reassignment and abandonment cascades with plot-pool conservation."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    ApiErrorId,
    set_clock,
    setup_assigned_plot, setup_assigned_with_waitlisted_rival, setup_warned_case,
    open_compliance_case, pay_full,
)

MANAGER = TEST_USERS["manager_headers"]


# ----------------------------------------------------------------------
# Difficulty: ComplianceCase WARNED -> CURED branch (within deadline)
# ----------------------------------------------------------------------

def test_warned_case_resolves_to_cured_within_deadline(api):
    """PRD §3.8: "A successful resolve moves the case from `WARNED` to `CURED` —
    terminal — which lifts the compliance block on the assignment's renewal."
    PRD §3.8: "Resolving requires the case to be `WARNED` (`ERR_COMPLIANCE_NOT_WARNED`,
    HTTP 409 otherwise) and the clock to be at or before the `cure_deadline`; resolving
    after the deadline is rejected with `ERR_CURE_PERIOD_EXPIRED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/compliance_case_branches_cured_vs_escalated
    """
    ctx = setup_warned_case(api, violation_type="RULE_BREACH", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-20T00:00:00Z")
    resolved = validate_success(api.resolve_case(ctx["case"]["id"], MANAGER), 200)
    assert resolved["status"] == "CURED"


def test_cured_branch_leaves_assignment_occupancy_active(api):
    """PRD §3.8: "A successful resolve moves the case from `WARNED` to `CURED` —
    terminal — which lifts the compliance block on the assignment's renewal."

    Design: Difficulty/non_linear_state_machine/compliance_case_branches_cured_vs_escalated
    """
    ctx = setup_warned_case(api, violation_type="RULE_BREACH", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-20T00:00:00Z")
    validate_success(api.resolve_case(ctx["case"]["id"], MANAGER), 200)
    assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert assignment["occupancy_status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Difficulty: forfeiture -> plot free -> auto-offer cascade (depth-3)
# ----------------------------------------------------------------------

def test_forfeit_reoffers_freed_plot_to_waitlist(api):
    """PRD §3.8: "It then returns the plot from `ASSIGNED` to `AVAILABLE` and, unlike
    settlement, immediately attempts to re-offer that freed plot to the top-ranked
    `WAITLISTED` applicant — a transitive cascade that carries the plot on from
    `AVAILABLE` to `RESERVED` and the selected application from `WAITLISTED` to
    `OFFERED`."

    Design: Difficulty/transitive_cascade/forfeiture_reassignment_cascade
    """
    ctx = setup_assigned_with_waitlisted_rival(api, size="MEDIUM")
    validate_success(api.forfeit_assignment(ctx["assignment"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    rival_app = validate_success(api.get_application(ctx["rival_app"]["id"], MANAGER), 200)
    assert plot["status"] == "RESERVED"
    assert rival_app["status"] == "OFFERED"


def test_forfeit_marks_assignment_forfeited_and_clears_pointer(api):
    """PRD §3.8: "Forfeiture, whether triggered directly by a `GardenManager` or
    cascaded from an escalation, drives an assignment whose `occupancy_status` is
    `ACTIVE` or `RENEWAL_PENDING` to `FORFEITED` (a direct forfeit against any other
    occupancy state fails with `ERR_ASSIGNMENT_NOT_ACTIVE`)."

    Design: Difficulty/transitive_cascade/forfeiture_reassignment_cascade
    """
    ctx = setup_assigned_with_waitlisted_rival(api, size="MEDIUM")
    forfeited = validate_success(api.forfeit_assignment(ctx["assignment"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    assert forfeited["occupancy_status"] == "FORFEITED"
    assert plot["current_assignment_id"] is None


# ----------------------------------------------------------------------
# Difficulty: escalation -> forced forfeiture -> plot freed (no waitlist)
# ----------------------------------------------------------------------

def test_escalate_past_deadline_forfeits_assignment(api):
    """PRD §3.8: "An escalation moves the case from `WARNED` to `ESCALATED` — terminal —
    and forces the linked assignment into forfeiture."
    PRD §3.8: "Escalating is the mirror image: it also requires the case to be `WARNED`
    (`ERR_COMPLIANCE_NOT_WARNED`), but requires the clock to be strictly after the
    `cure_deadline`; escalating at or before the deadline is rejected with
    `ERR_CURE_PERIOD_ACTIVE` (HTTP 409)."

    Design: Difficulty/transitive_cascade/abandonment_forfeiture_cascade
    """
    ctx = setup_warned_case(api, violation_type="NEGLECT", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-30T00:00:00Z")
    escalated = validate_success(api.escalate_case(ctx["case"]["id"], MANAGER), 200)
    assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert escalated["status"] == "ESCALATED"
    assert assignment["occupancy_status"] == "FORFEITED"


def test_escalate_frees_plot_with_no_waitlist(api):
    """PRD §3.8: "It then returns the plot from `ASSIGNED` to `AVAILABLE` ... This
    auto-offer is conditional: if no eligible waitlisted applicant exists for the
    plot's garden and size, the plot simply remains `AVAILABLE` and no offer is made."

    Design: Difficulty/transitive_cascade/abandonment_forfeiture_cascade
    """
    ctx = setup_warned_case(api, violation_type="NEGLECT", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-30T00:00:00Z")
    validate_success(api.escalate_case(ctx["case"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    assert plot["status"] == "AVAILABLE"
    assert plot["current_assignment_id"] is None


# ----------------------------------------------------------------------
# Difficulty: compliance block (safety) pre-empts outstanding-balance (fiscal)
# ----------------------------------------------------------------------

def test_compliance_block_wins_over_outstanding_balance(api):
    """PRD §3.7: "Two further gates guard renewal, and they are checked before the
    balance gate: the assignment must have no compliance case in `OPEN`, `WARNED`, or
    `ESCALATED`, otherwise the request is rejected with
    `ERR_RENEWAL_BLOCKED_BY_COMPLIANCE` (HTTP 409); and the gardener's
    `balance_owed_cents` must be exactly zero, otherwise the request is rejected with
    `ERR_OUTSTANDING_BALANCE` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/compliance_block_beats_outstanding_balance_returns_safety_error
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")  # balance 6000, unpaid
    open_compliance_case(api, ctx["assignment"]["id"], violation_type="WATER_ABUSE")
    resp = api.request_renewal(ctx["assignment"]["id"], ctx["gardener_headers"])
    validate_error(resp, ApiErrorId.ERR_RENEWAL_BLOCKED_BY_COMPLIANCE.value, 409)


def test_compliance_balance_conflict_leaves_occupancy_active(api):
    """PRD §3.7: "A leaseholder initiates renewal on their own assignment, which
    advances `occupancy_status` from `ACTIVE` to `RENEWAL_PENDING`. This step is
    available only while the assignment is `ACTIVE`; a request against any other
    occupancy state is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/compliance_block_beats_outstanding_balance_returns_safety_error
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    open_compliance_case(api, ctx["assignment"]["id"], violation_type="WATER_ABUSE")
    api.request_renewal(ctx["assignment"]["id"], ctx["gardener_headers"])
    assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert assignment["occupancy_status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Difficulty: renewal blocked by an OPEN compliance case (balance isolated)
# ----------------------------------------------------------------------

def test_open_compliance_blocks_renewal_request(api):
    """PRD §3.7: "the assignment must have no compliance case in `OPEN`, `WARNED`, or
    `ESCALATED`, otherwise the request is rejected with
    `ERR_RENEWAL_BLOCKED_BY_COMPLIANCE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/renewal_blocked_by_open_compliance_case
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    pay_full(api, ctx["assignment"]["id"], 6000)  # clear balance to isolate the compliance gate
    open_compliance_case(api, ctx["assignment"]["id"], violation_type="RULE_BREACH")
    resp = api.request_renewal(ctx["assignment"]["id"], ctx["gardener_headers"])
    validate_error(resp, ApiErrorId.ERR_RENEWAL_BLOCKED_BY_COMPLIANCE.value, 409)


def test_renewal_blocked_by_compliance_leaves_occupancy_active(api):
    """PRD §3.7: "the assignment must have no compliance case in `OPEN`, `WARNED`, or
    `ESCALATED`, otherwise the request is rejected with
    `ERR_RENEWAL_BLOCKED_BY_COMPLIANCE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/renewal_blocked_by_open_compliance_case
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    pay_full(api, ctx["assignment"]["id"], 6000)
    open_compliance_case(api, ctx["assignment"]["id"], violation_type="RULE_BREACH")
    api.request_renewal(ctx["assignment"]["id"], ctx["gardener_headers"])
    assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert assignment["occupancy_status"] == "ACTIVE"


# ----------------------------------------------------------------------
# Difficulty: plot-pool conservation across forfeit-then-autooffer
# ----------------------------------------------------------------------

def test_forfeit_autooffer_conserves_available_plot_count(api):
    """PRD §2.7: "A subtle consequence appears at forfeiture: when a forfeited plot
    moves from `ASSIGNED` back to `AVAILABLE` and, in the same operation, is immediately
    re-offered and moves on to `RESERVED`, the net count of `AVAILABLE` plots is left
    unchanged."

    Design: Difficulty/compensating_invariant/plot_pool_conservation_forfeit_then_autooffer
    """
    ctx = setup_assigned_with_waitlisted_rival(api, size="MEDIUM")
    validate_success(api.forfeit_assignment(ctx["assignment"]["id"], MANAGER), 200)
    garden = validate_success(api.get_garden(ctx["garden"]["id"], MANAGER), 200)
    assert garden["available_plot_count"] == 0


def test_forfeit_autooffer_moves_plot_to_reserved(api):
    """PRD §2.7: "`available_plot_count` is the running count of that garden's plots
    currently in `AVAILABLE`."
    PRD §3.8: "a transitive cascade that carries the plot on from `AVAILABLE` to
    `RESERVED` and the selected application from `WAITLISTED` to `OFFERED`."

    Design: Difficulty/compensating_invariant/plot_pool_conservation_forfeit_then_autooffer
    """
    ctx = setup_assigned_with_waitlisted_rival(api, size="MEDIUM")
    validate_success(api.forfeit_assignment(ctx["assignment"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    rival_app = validate_success(api.get_application(ctx["rival_app"]["id"], MANAGER), 200)
    assert plot["status"] == "RESERVED"
    assert rival_app["status"] == "OFFERED"


# ----------------------------------------------------------------------
# Corner: compliance state-machine guards
# ----------------------------------------------------------------------

def test_warn_already_warned_case_rejected(api):
    """PRD §3.8: "Issuing a warning requires the case to be `OPEN` (otherwise
    `ERR_COMPLIANCE_NOT_OPEN`, HTTP 409); it moves the case from `OPEN` to `WARNED` and
    sets its `cure_deadline` to the current clock plus a fixed cure grace period of
    exactly 14 days (`CURE_GRACE_DAYS` = 14)."

    Design: Corner/state_machines/warn_from_warned_returns_compliance_not_open
    """
    ctx = setup_warned_case(api, violation_type="NEGLECT", warn_clock="2026-03-15T00:00:00Z")
    resp = api.warn_case(ctx["case"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_OPEN.value, 409)


def test_resolve_after_cure_deadline_rejected(api):
    """PRD §3.8: "Resolving requires the case to be `WARNED` (`ERR_COMPLIANCE_NOT_WARNED`,
    HTTP 409 otherwise) and the clock to be at or before the `cure_deadline`; resolving
    after the deadline is rejected with `ERR_CURE_PERIOD_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/resolve_after_deadline_returns_cure_expired
    """
    ctx = setup_warned_case(api, violation_type="NEGLECT", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-30T00:00:00Z")  # deadline is 2026-03-29
    resp = api.resolve_case(ctx["case"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_EXPIRED.value, 409)


def test_escalate_before_cure_deadline_rejected(api):
    """PRD §3.8: "Escalating is the mirror image: it also requires the case to be
    `WARNED` (`ERR_COMPLIANCE_NOT_WARNED`), but requires the clock to be strictly after
    the `cure_deadline`; escalating at or before the deadline is rejected with
    `ERR_CURE_PERIOD_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/escalate_before_deadline_returns_cure_active
    """
    ctx = setup_warned_case(api, violation_type="NEGLECT", warn_clock="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-20T00:00:00Z")  # still within the cure window (deadline 2026-03-29)
    resp = api.escalate_case(ctx["case"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE.value, 409)
