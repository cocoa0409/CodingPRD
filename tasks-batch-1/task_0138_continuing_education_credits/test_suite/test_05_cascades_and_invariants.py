"""Transitive cascades (provider revoke, reciprocity bubble-up), compensating
invariants (approve/revoke, reject/resubmit conservation), and cross-entity
state dependencies (suspended-provider verify gate, open-audit renew block).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
)

ADMIN = FX.ADMIN
ADMIN_INITIATOR = FX.ADMIN_INITIATOR


# ===========================================================================
# Difficulty/transitive_cascade  (>=2 tests per instance)
# ===========================================================================
def test_provider_revoke_four_hop_cascade_reverts_cycle(api):
    """PRD §3.2: "First, every `ACTIVE` course belonging to the revoked provider
    is set to `DEACTIVATED`. Second, for each course thus deactivated, every
    `VERIFIED` completion recorded against that course is set to the terminal
    `INVALIDATED` state. Third, each completion invalidation recomputes the
    earned-hour figures (`final_earned_hours` and `provisional_earned_hours`) of
    the renewal cycle that completion belonged to."
    PRD §3.2: "Fourth, for any cycle that was in `REQUIREMENTS_MET` and whose
    `final_earned_hours` now falls below what the requirement demands, the cycle
    reverts from `REQUIREMENTS_MET` back to `OPEN`."

    Design: Difficulty/transitive_cascade/provider_revoke_four_hop_cascade_reverts_cycle
    """
    met = FX.setup_requirements_met_cycle()  # ETHICS 4, SUBSTANCE 2, GENERAL 24 -> final 30
    provider, cycle, courses, comps = (
        met["provider"], met["cycle"], met["courses"], met["completions"])
    assert cycle["status"] == "REQUIREMENTS_MET"

    validate_success(api.revoke_provider(provider["id"], ADMIN), 200)

    course_e = get_success_data(api.get_course(courses["ETHICS"]["id"], ADMIN))
    assert course_e["status"] == "DEACTIVATED", "hop 1: course deactivated"

    comp_e = get_success_data(api.get_completion(comps["ETHICS"]["id"], ADMIN))
    assert comp_e["status"] == "INVALIDATED", "hop 2: verified completion invalidated"

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["final_earned_hours"]) == pytest.approx(0.0, abs=0.01), (
        "hop 3: all three completions invalidated")
    assert cyc["status"] == "OPEN", "hop 4: reverted from REQUIREMENTS_MET"


def test_reciprocity_approve_two_hop_bubble_up(api):
    """PRD §3.7: "Approval adds the grant's `credit_hours` to the target cycle's
    `reciprocity_hours`, recomputes that cycle's `final_earned_hours` and
    `provisional_earned_hours`, and — if the requirement is now met — bubbles the
    cycle from `OPEN` to `REQUIREMENTS_MET` and computes its `carryover_out_hours`."

    Design: Difficulty/transitive_cascade/reciprocity_approve_two_hop_bubble_up
    """
    # ETHICS 4 + SUBSTANCE 2 + GENERAL 22 verified -> final 28.0, GENERAL short by 2.0 -> OPEN.
    met = FX.setup_requirements_met_cycle(general_hours=22.0)
    licensee, cycle = met["licensee"], met["cycle"]
    assert cycle["status"] == "OPEN"
    grant = FX.request_reciprocity(licensee["id"], cycle["id"], "GENERAL", 2.0, "NY")

    validate_success(api.approve_reciprocity_grant(grant["id"], ADMIN), 200)

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["reciprocity_hours"]) == pytest.approx(2.0, abs=0.01), "hop 1"
    assert float(cyc["final_earned_hours"]) == pytest.approx(30.0, abs=0.01), (
        "hop 1 recompute: 28.0 + 2.0")
    assert cyc["status"] == "REQUIREMENTS_MET", "hop 2 bubble-up"


def test_provider_revoke_invalidates_completion_terminal_state(api):
    """PRD §3.2: "Second, for each course thus deactivated, every `VERIFIED`
    completion recorded against that course is set to the terminal `INVALIDATED`
    state."
    PRD §3.4: "A completion also reaches the terminal `INVALIDATED` state, but
    only as a system consequence of its parent course being deactivated through
    provider revocation."

    Design: Difficulty/transitive_cascade/provider_revoke_four_hop_cascade_reverts_cycle
    """
    met = FX.setup_requirements_met_cycle()
    provider, comps = met["provider"], met["completions"]

    validate_success(api.revoke_provider(provider["id"], ADMIN), 200)

    # Every previously-VERIFIED completion is now terminally INVALIDATED.
    for category in ("ETHICS", "SUBSTANCE", "GENERAL"):
        comp = get_success_data(api.get_completion(comps[category]["id"], ADMIN))
        assert comp["status"] == "INVALIDATED", (
            f"{category} completion invalidated by the revoke cascade")


def test_reciprocity_approve_adds_to_reciprocity_hours(api):
    """PRD §3.7: "Approval adds the grant's `credit_hours` to the target cycle's
    `reciprocity_hours`, recomputes that cycle's `final_earned_hours` and
    `provisional_earned_hours`."

    Design: Difficulty/transitive_cascade/reciprocity_approve_two_hop_bubble_up
    """
    # Cycle stays OPEN even after approval (general still short), isolating hop 1.
    met = FX.setup_requirements_met_cycle(general_hours=20.0)  # final 26.0, short by 4.0
    licensee, cycle = met["licensee"], met["cycle"]
    assert cycle["status"] == "OPEN"
    grant = FX.request_reciprocity(licensee["id"], cycle["id"], "GENERAL", 2.0, "NY")

    validate_success(api.approve_reciprocity_grant(grant["id"], ADMIN), 200)

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["reciprocity_hours"]) == pytest.approx(2.0, abs=0.01), (
        "approved grant's 2.0h added to reciprocity_hours")
    assert float(cyc["final_earned_hours"]) == pytest.approx(28.0, abs=0.01), (
        "26.0 + 2.0 recomputed")
    assert cyc["status"] == "OPEN", "still short of GENERAL requirement -> no bubble-up"


# ===========================================================================
# Difficulty/compensating_invariant  (>=2 tests per instance)
# ===========================================================================
def test_reciprocity_approve_then_revoke_conserves_reciprocity_hours(api):
    """PRD §3.7: "An approved grant may be revoked as a compensating action ...
    Revocation moves the grant from `APPROVED` to `DENIED` and is the exact
    inverse of approval: it subtracts the grant's `credit_hours` from the target
    cycle's `reciprocity_hours`, recomputes the cycle's earned hours, and — if
    the requirement is no longer met — reverts the cycle from `REQUIREMENTS_MET`
    to `OPEN` and resets `carryover_out_hours` to 0."
    PRD §3.7: "An approve followed by a revoke leaves the cycle's
    `reciprocity_hours` and `final_earned_hours` exactly as they were before the
    approval."

    Design: Difficulty/compensating_invariant/reciprocity_approve_then_revoke_conserves_reciprocity_hours
    """
    met = FX.setup_requirements_met_cycle(general_hours=22.0)  # final 28.0 -> OPEN
    licensee, cycle = met["licensee"], met["cycle"]
    grant = FX.request_reciprocity(licensee["id"], cycle["id"], "GENERAL", 2.0, "NY")
    get_success_data(api.approve_reciprocity_grant(grant["id"], ADMIN))

    validate_success(api.revoke_reciprocity_grant(grant["id"], ADMIN), 200)

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["reciprocity_hours"]) == pytest.approx(0.0, abs=0.01), (
        "approve +2.0 then revoke -2.0; conserved")
    assert float(cyc["final_earned_hours"]) == pytest.approx(28.0, abs=0.01), (
        "back to pre-approve value")
    assert cyc["status"] == "OPEN", "reverted from REQUIREMENTS_MET"


def test_reciprocity_revoke_moves_grant_to_denied(api):
    """PRD §3.7: "An approved grant may be revoked as a compensating action, but
    only while the target cycle is `OPEN` or `REQUIREMENTS_MET`. Revocation moves
    the grant from `APPROVED` to `DENIED` and is the exact inverse of approval."

    Design: Difficulty/compensating_invariant/reciprocity_approve_then_revoke_conserves_reciprocity_hours
    """
    met = FX.setup_requirements_met_cycle(general_hours=22.0)  # final 28.0 -> OPEN
    licensee, cycle = met["licensee"], met["cycle"]
    grant = FX.request_reciprocity(licensee["id"], cycle["id"], "GENERAL", 2.0, "NY")
    get_success_data(api.approve_reciprocity_grant(grant["id"], ADMIN))

    data = validate_success(api.revoke_reciprocity_grant(grant["id"], ADMIN), 200)
    assert data["status"] == "DENIED", "compensating revoke moves APPROVED -> DENIED"


def test_completion_reject_resubmit_conserves_provisional_hours(api):
    """PRD §3.4: "Rejection moves it from `PENDING_VERIFICATION` to `REJECTED`,
    optionally recording a `reason`, recomputes the cycle's provisional tally to
    drop this completion's hours."
    PRD §3.4: "the owning `Licensee` may resubmit it, moving it from `REJECTED`
    back to `PENDING_VERIFICATION` ... and recomputing the cycle's provisional
    tally to re-add this completion's hours."

    Design: Difficulty/compensating_invariant/completion_reject_resubmit_conserves_provisional_hours
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    lic = make_licensee_headers(licensee["id"])
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])  # provisional 4.0

    get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "needs correction"}))
    validate_success(api.resubmit_completion(comp["id"], lic), 200)

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["provisional_earned_hours"]) == pytest.approx(4.0, abs=0.01), (
        "reject -4.0 then resubmit +4.0; conserved")
    comp_final = get_success_data(api.get_completion(comp["id"], ADMIN))
    assert comp_final["status"] == "PENDING_VERIFICATION"


def test_completion_reject_drops_provisional_to_zero_midway(api):
    """PRD §3.4: "Rejection moves it from `PENDING_VERIFICATION` to `REJECTED`,
    optionally recording a `reason`, recomputes the cycle's provisional tally to
    drop this completion's hours."

    Design: Difficulty/compensating_invariant/completion_reject_resubmit_conserves_provisional_hours
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    # Midway through the conservation loop: after reject, provisional is exactly 0.0.
    get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "x"}))
    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["provisional_earned_hours"]) == pytest.approx(0.0, abs=0.01), (
        "reject drops the completion's 4.0h from provisional")


# ===========================================================================
# Difficulty/cross_entity_state_dependency  (>=2 tests per instance)
# ===========================================================================
def test_completion_verify_blocked_by_suspended_provider(api):
    """PRD §3.4: "the cross-entity accreditation gate is satisfied: the provider
    behind the completed course must currently be `ACCREDITED` (not `SUSPENDED`,
    not `REVOKED`). A verify attempted while that provider is not accredited is
    rejected with `ERR_PROVIDER_NOT_ACCREDITED`."

    Design: Difficulty/cross_entity_state_dependency/completion_verify_blocked_by_suspended_provider
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])
    get_success_data(api.suspend_provider(provider["id"], ADMIN))

    resp = api.verify_completion(comp["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_ACCREDITED.value, 409)

    comp_final = get_success_data(api.get_completion(comp["id"], ADMIN))
    assert comp_final["status"] == "PENDING_VERIFICATION", "unchanged after rejected verify"


def test_completion_verify_succeeds_after_provider_reinstated(api):
    """PRD §3.4: "the provider behind the completed course must currently be
    `ACCREDITED` (not `SUSPENDED`, not `REVOKED`). A verify attempted while that
    provider is not accredited is rejected with `ERR_PROVIDER_NOT_ACCREDITED`."
    PRD §3.1: "A suspended provider may be reinstated back to `ACCREDITED`."

    Design: Difficulty/cross_entity_state_dependency/completion_verify_blocked_by_suspended_provider
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])
    get_success_data(api.suspend_provider(provider["id"], ADMIN))
    # Reinstating clears the cross-entity gate; verify now succeeds.
    get_success_data(api.reinstate_provider(provider["id"], ADMIN))

    data = validate_success(api.verify_completion(comp["id"], ADMIN), 200)
    assert data["status"] == "VERIFIED", "provider re-ACCREDITED clears the gate"


def test_renew_blocked_by_open_audit_on_cycle(api):
    """PRD §3.9: "moves the cycle into `AUDIT_HOLD` (from either `OPEN` or
    `REQUIREMENTS_MET`)."
    PRD §3.8: "Renewal is permitted only when the cycle is in `REQUIREMENTS_MET`."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_open_audit_on_cycle
    """
    met = FX.setup_requirements_met_cycle()  # final 30.0
    licensee, cycle = met["licensee"], met["cycle"]
    lic = make_licensee_headers(licensee["id"])

    FX.initiate_audit(cycle["id"], ADMIN_INITIATOR)  # cycle -> AUDIT_HOLD
    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], lic))

    resp = api.renew_cycle(cycle["id"], F.renew_cycle_payload(cyc["version"]), lic)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_initiating_audit_moves_cycle_to_audit_hold(api):
    """PRD §3.9: "starts the audit in `INITIATED`, and moves the cycle into
    `AUDIT_HOLD` (from either `OPEN` or `REQUIREMENTS_MET`)."

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_open_audit_on_cycle
    """
    met = FX.setup_requirements_met_cycle()  # REQUIREMENTS_MET
    cycle = met["cycle"]
    assert cycle["status"] == "REQUIREMENTS_MET"

    FX.initiate_audit(cycle["id"], ADMIN_INITIATOR)
    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert cyc["status"] == "AUDIT_HOLD", (
        "an open audit drives the renewable cycle into AUDIT_HOLD")
