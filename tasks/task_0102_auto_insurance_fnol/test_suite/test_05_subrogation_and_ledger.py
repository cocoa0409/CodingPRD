"""Subrogation recovery and the per-claim cash ledger.

Covers: comparative-negligence recovery (PURE vs MODIFIED_50 bar, round-once-at-end,
the 50%-fault boundary), the cyclic NEGOTIATING<->DEMAND_SENT revision loop, the
depth-3 resolve->disbursement->ledger cascade, the ledger computed read, the
settle-then-void cash-conservation invariant, and the resolve/send-demand guards
(incl. the state-vs-recovery-exceeds priority-pair conflict).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    setup_subrogation_case, setup_subrogation_negotiating, setup_subrogation_demand_sent,
    setup_settled_repair_claim, setup_repair_approved_claim,
    open_subrogation_case,
    create_policy, add_collision_coverage, create_adjuster, file_claim,
    verify_claim, assign_claim, submit_estimate, make_claims_adjuster_headers,
    TEST_USERS,
)

SUP = TEST_USERS["supervisor_headers"]
SUB = TEST_USERS["subrogation_headers"]


# ─── Comparative-negligence recovery (dual_variant_calc, combinatorial_formula, boundary) ───

def test_subrogation_recovery_pure_vs_modified_bar_diverge(api):
    """PRD §3.10: "Under the `PURE` rule the recovery is always the `demand_cents`
    multiplied by the quantity (100 minus the insured fault) divided by 100, rounded
    half-up to whole cents — the recovery is reduced by the fault percentage but never
    zeroed by a bar. Under the `MODIFIED_50` rule the recovery is zero when the insured
    fault is at or above 50". At 50% fault, demand 500000: PURE -> 250000, MODIFIED_50 -> 0.

    Design: Difficulty/dual_variant_calc/subrogation_recovery_pure_vs_modified_bar_diverge
    """
    pure_ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=50, comparative_fault_rule="PURE",
        third_party_fault_pct=50)
    assert pure_ctx["subrogation_case"]["recoverable_cents"] == 250_000

    mod_ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=50, comparative_fault_rule="MODIFIED_50",
        third_party_fault_pct=50)
    assert mod_ctx["subrogation_case"]["recoverable_cents"] == 0


def test_subrogation_rounding_order_pinned_round_once_at_end(api):
    """PRD §3.10: "In every rule the percentage multiply is performed first and the
    result is rounded half-up to whole cents exactly once at the end." PRD §2.6: "the
    comparative-negligence recovery is computed by multiplying a cent amount by a fault
    percentage and is rounded to whole cents using round-half-up, applied exactly once
    at the end of the computation rather than at any intermediate step." demand 333333,
    fault 33, PURE: 333333 * 67 / 100 = 223333.11 -> 223333.

    Design: Difficulty/combinatorial_formula/subrogation_rounding_order_pinned_round_once_at_end
    """
    ctx = setup_subrogation_case(
        demand_cents=333_333, insured_fault_pct=33, comparative_fault_rule="PURE",
        third_party_fault_pct=67)
    assert ctx["subrogation_case"]["recoverable_cents"] == 223_333


def test_subrogation_rounding_half_up_at_end(api):
    """PRD §2.6: "The comparative-negligence recovery is computed by multiplying a cent
    amount by a fault percentage and is rounded to whole cents using round-half-up,
    applied exactly once at the end of the computation rather than at any intermediate
    step." demand 100001, fault 50, PURE: 100001 * 50 / 100 = 50000.5 -> half-up = 50001.

    Design: Difficulty/combinatorial_formula/subrogation_rounding_order_pinned_round_once_at_end
    """
    ctx = setup_subrogation_case(
        demand_cents=100_001, insured_fault_pct=50, comparative_fault_rule="PURE",
        third_party_fault_pct=50)
    assert ctx["subrogation_case"]["recoverable_cents"] == 50_001


def test_modified_50_fault_bar_inclusive_at_exactly_50(api):
    """PRD §3.10: "Under the `MODIFIED_50` rule the recovery is zero when the insured
    fault is at or above 50, and otherwise the same reduced figure; so at exactly 50
    percent fault the recovery is zero."

    Design: Difficulty/boundary_precision_check/modified_50_fault_bar_inclusive_at_exactly_50
    """
    ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=50, comparative_fault_rule="MODIFIED_50",
        third_party_fault_pct=50)
    assert ctx["subrogation_case"]["recoverable_cents"] == 0


def test_modified_50_just_below_bar_recovers(api):
    """PRD §3.10: "Under the `MODIFIED_50` rule the recovery is zero when the insured
    fault is at or above 50, and otherwise the same reduced figure". Just below the bar
    (fault 49) recovery is the reduced figure: 500000 * 51 / 100 = 255000.

    Design: Difficulty/boundary_precision_check/modified_50_fault_bar_inclusive_at_exactly_50
    """
    ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=49, comparative_fault_rule="MODIFIED_50",
        third_party_fault_pct=51)
    assert ctx["subrogation_case"]["recoverable_cents"] == 255_000


def test_modified_51_recovers_half_at_exactly_50(api):
    """PRD §3.10: "Under the `MODIFIED_51` rule the recovery is zero only when the
    insured fault is at or above 51, and otherwise the same reduced figure; so at
    exactly 50 percent fault the insured still recovers half the demand." demand 500000,
    fault 50: 500000 * 50 / 100 = 250000.

    Design: Difficulty/dual_variant_calc/subrogation_recovery_pure_vs_modified_bar_diverge
    """
    ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=50, comparative_fault_rule="MODIFIED_51",
        third_party_fault_pct=50)
    assert ctx["subrogation_case"]["recoverable_cents"] == 250_000


# ─── Cyclic negotiation (non_linear_state_machine) ───

def test_subrogation_cyclic_negotiating_back_to_demand_sent(api):
    """PRD §3.10: "From negotiation, the parties may bounce back to a revised demand:
    the specialist re-sends with a new `demand_cents`, moving `NEGOTIATING →
    DEMAND_SENT` and recomputing `recoverable_cents` against the revised demand. This
    counter-offer loop may repeat any number of times." Re-send with demand 300000
    (PURE, fault 0) -> recoverable 300000.

    Design: Difficulty/non_linear_state_machine/subrogation_cyclic_negotiating_back_to_demand_sent
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    resent = validate_success(api.send_demand(case_id, {"demand_cents": 300_000}, SUB), 200)
    assert resent["status"] == "DEMAND_SENT"
    assert resent["recoverable_cents"] == 300_000


# ─── Resolve cascade + ledger (transitive_cascade + calculations corner) ───

def test_subrogation_resolve_cascade_depth3_to_claim_ledger(api):
    """PRD §3.10: "A successful recovery cascades in three hops: first the case's
    `status` becomes `RESOLVED` and its `recovered_cents` is stored; second, as a
    consequence, a `SUBROGATION_RECOVERY` disbursement is created in `APPROVED` status
    with an `amount_cents` of negative `recovered_cents` (an inbound credit); third, as a
    consequence of that disbursement creation, the parent claim's `total_disbursed_cents`
    is recomputed from the ledger." Net = settlement 550000 - recovery 300000 = 250000.

    Design: Difficulty/transitive_cascade/subrogation_resolve_cascade_depth3_to_claim_ledger
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=300_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100, vehicle_acv_cents=800_000)
    case_id = ctx["subrogation_case"]["id"]
    claim_id = ctx["claim"]["id"]
    resolved = validate_success(api.resolve_subrogation_case(case_id, {"recovered_cents": 300_000}, SUB), 200)
    assert resolved["status"] == "RESOLVED"
    claim_after = validate_success(api.get_claim(claim_id, SUP), 200)
    assert claim_after["total_disbursed_cents"] == 250_000


def test_subrogation_resolve_creates_negative_recovery_disbursement(api):
    """PRD §3.10: "a `SUBROGATION_RECOVERY` disbursement is created in `APPROVED` status
    with an `amount_cents` of negative `recovered_cents` (an inbound credit)". PRD §2.8:
    "a `SUBROGATION_RECOVERY` disbursement carries a negative `amount_cents`,
    representing money flowing back to the insurer."

    Design: Difficulty/transitive_cascade/subrogation_resolve_cascade_depth3_to_claim_ledger
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=300_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100, vehicle_acv_cents=800_000)
    case_id = ctx["subrogation_case"]["id"]
    claim_id = ctx["claim"]["id"]
    validate_success(api.resolve_subrogation_case(case_id, {"recovered_cents": 300_000}, SUB), 200)
    disbursements, _meta = _list(api.list_claim_disbursements(claim_id, SUP))
    recovery = [d for d in disbursements if d["disbursement_type"] == "SUBROGATION_RECOVERY"]
    assert len(recovery) == 1
    assert recovery[0]["amount_cents"] == -300_000
    assert recovery[0]["status"] == "APPROVED"


def test_claim_ledger_read_nets_settlement_and_recovery(api):
    """PRD §3.9: "The claim's net cash position can be read at any time through the
    computed ledger view, which returns `net_paid_cents` (the net approved-disbursement
    sum) and a `disbursement_count`." PRD §2.8: "A `SETTLEMENT` disbursement and a
    `RENTAL` disbursement carry a positive (outbound) `amount_cents`; a
    `SUBROGATION_RECOVERY` disbursement carries a negative `amount_cents`, representing
    money flowing back to the insurer." +550000 settlement - 300000 recovery = 250000 over 2
    APPROVED disbursements.

    Design: Corner/calculations/claim_ledger_read_nets_settlement_and_recovery
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=300_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100, vehicle_acv_cents=800_000)
    case_id = ctx["subrogation_case"]["id"]
    claim_id = ctx["claim"]["id"]
    validate_success(api.resolve_subrogation_case(case_id, {"recovered_cents": 300_000}, SUB), 200)
    ledger = validate_success(api.get_ledger(claim_id, SUP), 200)
    assert ledger["net_paid_cents"] == 250_000
    assert ledger["disbursement_count"] == 2


# ─── Compensating invariant: settle then void (compensating_invariant) ───

def test_settle_then_void_conserves_claim_net_cash(api):
    """PRD §3.9: "On success the system creates a `SETTLEMENT` disbursement in
    `APPROVED` status whose `amount_cents` equals the positive `settlement_cents`". PRD
    §3.9: "A `ClaimsSupervisor` may void an `APPROVED` disbursement as a compensating
    action, moving it `APPROVED → VOIDED`; this drops that disbursement's `amount_cents`
    out of the approved sum and, as a second hop, recomputes the parent claim's
    `total_disbursed_cents`, restoring it to the value it held before the disbursement
    was created."

    Design: Difficulty/compensating_invariant/settle_then_void_conserves_claim_net_cash
    """
    ctx = setup_repair_approved_claim(repair_total_cents=600_000)  # settlement 550000
    claim_id = ctx["claim"]["id"]
    settled = validate_success(api.settle_claim(claim_id, {"expected_claim_version": ctx["version"]}, SUP), 200)
    assert settled["total_disbursed_cents"] == 550_000

    disbursements, _meta = _list(api.list_claim_disbursements(claim_id, SUP))
    assert len(disbursements) == 1
    disb_id = disbursements[0]["id"]
    voided = validate_success(api.void_disbursement(disb_id, SUP), 200)
    assert voided["status"] == "VOIDED"

    claim_after = validate_success(api.get_claim(claim_id, SUP), 200)
    assert claim_after["total_disbursed_cents"] == 0


def test_void_drops_disbursement_from_ledger_read(api):
    """PRD §2.8: "The ledger is the net sum, over every `Disbursement` for the claim
    whose `status` is `APPROVED`, of that disbursement's `amount_cents`. Disbursements
    in any other status — and there is exactly one other, `VOIDED` — are excluded from
    the sum." After voiding the only settlement, the ledger read nets to 0.

    Design: Difficulty/compensating_invariant/settle_then_void_conserves_claim_net_cash
    """
    ctx = setup_repair_approved_claim(repair_total_cents=600_000)  # settlement 550000
    claim_id = ctx["claim"]["id"]
    validate_success(api.settle_claim(claim_id, {"expected_claim_version": ctx["version"]}, SUP), 200)
    before = validate_success(api.get_ledger(claim_id, SUP), 200)
    assert before["net_paid_cents"] == 550_000

    disbursements, _meta = _list(api.list_claim_disbursements(claim_id, SUP))
    validate_success(api.void_disbursement(disbursements[0]["id"], SUP), 200)
    after = validate_success(api.get_ledger(claim_id, SUP), 200)
    assert after["net_paid_cents"] == 0


# ─── Subrogation guards (validations + priority_pair) ───

def test_send_demand_requires_parent_claim_settled(api):
    """PRD §3.10: "A specialist sends the demand, moving the case `OPEN → DEMAND_SENT`;
    this requires that the parent claim is `SETTLED` and that `recoverable_cents` is
    greater than zero". Send-demand against a parent claim that is not SETTLED (here an
    UNDER_REVIEW claim) is refused by the state guard.

    Design: Difficulty/cross_entity_state_dependency/send_demand_requires_parent_claim_settled
    """
    # Build an UNDER_REVIEW claim with a THIRD_PARTY but never settle it.
    from test_helpers import (
        create_policy, add_collision_coverage, create_adjuster, file_claim,
        verify_claim, assign_claim, make_claims_adjuster_headers,
    )
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION",
                       vehicle_acv_cents=2_000_000, insured_fault_pct=0)
    adj_headers = make_claims_adjuster_headers(adjuster["id"])
    party = validate_success(api.create_claim_party(
        {"claim_id": claim["id"], "party_role": "THIRD_PARTY", "display_name": "Other Driver",
         "fault_pct": 100, "at_fault_carrier_name": "Rival Mutual"}, adj_headers), 201)
    verified = verify_claim(claim["id"], adjuster["id"])
    assign_claim(claim["id"], adjuster["id"], verified["version"])  # claim is UNDER_REVIEW
    # Open the case on the not-yet-settled claim, then attempt to send the demand: the
    # SETTLED precondition on send-demand is what the rule guards.
    case = open_subrogation_case(claim["id"], party["id"], demand_cents=400_000)
    res = api.send_demand(case["id"], {}, SUB)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_send_demand_zero_recoverable_rejected(api):
    """PRD §3.10: "this requires that the parent claim is `SETTLED` and that
    `recoverable_cents` is greater than zero — a fully barred recovery cannot be
    demanded and the attempt is rejected with `ERR_NO_RECOVERABLE_AMOUNT`." MODIFIED_50
    at fault 50 bars recovery (recoverable 0).

    Design: Corner/validations/send_demand_zero_recoverable_rejected
    """
    ctx = setup_subrogation_case(
        demand_cents=500_000, insured_fault_pct=50, comparative_fault_rule="MODIFIED_50",
        third_party_fault_pct=50)
    assert ctx["subrogation_case"]["recoverable_cents"] == 0
    case_id = ctx["subrogation_case"]["id"]
    res = api.send_demand(case_id, {}, SUB)
    validate_error(res, "ERR_NO_RECOVERABLE_AMOUNT", expected_status=409)


def test_subrogation_resolve_over_recoverable_rejected(api):
    """PRD §3.10: "the recovered amount must satisfy zero at or below `recovered_cents`
    at or below `recoverable_cents`; a `recovered_cents` above the recoverable amount or
    below zero is rejected with `ERR_RECOVERY_EXCEEDS_DEMAND`." recoverable 400000,
    recovered 500000 -> rejected.

    Design: Corner/validations/subrogation_resolve_over_recoverable_rejected
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    res = api.resolve_subrogation_case(case_id, {"recovered_cents": 500_000}, SUB)
    validate_error(res, "ERR_RECOVERY_EXCEEDS_DEMAND", expected_status=409)


def test_subrogation_resolve_no_recovery_closes_case(api):
    """PRD §3.10: "when `recovered_cents` is zero the case moves to `CLOSED_NO_RECOVERY`
    (reachable from either `DEMAND_SENT` or `NEGOTIATING`)."

    Design: Corner/state_machines/subrogation_resolve_no_recovery_closes_case
    """
    ctx = setup_subrogation_demand_sent(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    resolved = validate_success(api.resolve_subrogation_case(case_id, {"recovered_cents": 0}, SUB), 200)
    assert resolved["status"] == "CLOSED_NO_RECOVERY"


def test_state_beats_recovery_exceeds_on_subrogation_resolve(api):
    """PRD §3.6: "Only then does it confirm the target resource is in a state from which
    the requested transition is defined, rejecting an out-of-state request with
    `ERR_INVALID_STATE`; this state guard governs every transition endpoint in the
    system." Resolve is only defined from DEMAND_SENT/NEGOTIATING; from OPEN the state
    check (priority 5) wins over the recovery-exceeds business check (priority 15).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_recovery_exceeds_on_subrogation_resolve
    """
    # Case still OPEN (demand never sent), and recovered 900000 > recoverable 400000.
    ctx = setup_subrogation_case(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    res = api.resolve_subrogation_case(case_id, {"recovered_cents": 900_000}, SUB)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_resolve_from_open_state_blocked_even_with_valid_amount(api):
    """PRD §3.6: "rejecting an out-of-state request with `ERR_INVALID_STATE`; this
    state guard governs every transition endpoint in the system." PRD §3.10: "when
    `recovered_cents` is greater than zero the case moves to `RESOLVED` (reachable from
    `NEGOTIATING`)". Resolving an OPEN case (never demanded) is out of state regardless
    of a within-bounds recovered amount — confirming the state check gates resolve.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_recovery_exceeds_on_subrogation_resolve
    """
    # recoverable 400000 (PURE, fault 0); recovered 100000 is within bounds but case is OPEN.
    ctx = setup_subrogation_case(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    assert ctx["subrogation_case"]["recoverable_cents"] == 400_000
    case_id = ctx["subrogation_case"]["id"]
    res = api.resolve_subrogation_case(case_id, {"recovered_cents": 100_000}, SUB)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_send_demand_on_settled_claim_succeeds(api):
    """PRD §3.10: "A specialist sends the demand, moving the case `OPEN → DEMAND_SENT`;
    this requires that the parent claim is `SETTLED` and that `recoverable_cents` is
    greater than zero". With a SETTLED parent and positive recoverable, send-demand
    succeeds — the complement of the not-settled rejection.

    Design: Difficulty/cross_entity_state_dependency/send_demand_requires_parent_claim_settled
    """
    ctx = setup_subrogation_case(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    sent = validate_success(api.send_demand(case_id, {}, SUB), 200)
    assert sent["status"] == "DEMAND_SENT"


def test_subrogation_revision_loop_repeats(api):
    """PRD §3.10: "From negotiation, the parties may bounce back to a revised demand:
    the specialist re-sends with a new `demand_cents`, moving `NEGOTIATING →
    DEMAND_SENT` and recomputing `recoverable_cents` against the revised demand. This
    counter-offer loop may repeat any number of times." A second NEGOTIATING -> revised
    DEMAND_SENT round recomputes recoverable to the new demand.

    Design: Difficulty/non_linear_state_machine/subrogation_cyclic_negotiating_back_to_demand_sent
    """
    ctx = setup_subrogation_negotiating(
        demand_cents=400_000, insured_fault_pct=0, comparative_fault_rule="PURE",
        third_party_fault_pct=100)
    case_id = ctx["subrogation_case"]["id"]
    # First revision round.
    r1 = validate_success(api.send_demand(case_id, {"demand_cents": 350_000}, SUB), 200)
    assert r1["status"] == "DEMAND_SENT"
    assert r1["recoverable_cents"] == 350_000
    # Back to negotiation, then a second revision round with a different demand.
    validate_success(api.begin_negotiation(case_id, SUB), 200)
    r2 = validate_success(api.send_demand(case_id, {"demand_cents": 200_000}, SUB), 200)
    assert r2["status"] == "DEMAND_SENT"
    assert r2["recoverable_cents"] == 200_000


def test_settle_zero_settlement_rejected(api):
    """PRD §3.9: "Settlement additionally requires that the claim's `settlement_cents`
    is strictly greater than zero, so that no zero-value disbursement is ever emitted; a
    settle attempt against a zero settlement is rejected with `ERR_NO_SETTLEMENT_AMOUNT`."
    A deductible of 600000 fully absorbs a 600000 repair total, leaving settlement_cents 0.

    Design: Corner/validations/settle_zero_settlement_rejected
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"], limit_cents=1_000_000, deductible_cents=600_000)
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=2_000_000)
    verified = verify_claim(claim["id"], adjuster["id"])
    assigned = assign_claim(claim["id"], adjuster["id"], verified["version"])
    submit_estimate(claim["id"], adjuster["id"], repair_total_cents=600_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    decided = validate_success(api.decide_disposition(
        claim["id"], {"decision": "REPAIR", "expected_claim_version": assigned["version"]}, headers), 200)
    assert decided["settlement_cents"] == 0
    res = api.settle_claim(claim["id"], {"expected_claim_version": decided["version"]}, SUP)
    validate_error(res, "ERR_NO_SETTLEMENT_AMOUNT", expected_status=409)


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
