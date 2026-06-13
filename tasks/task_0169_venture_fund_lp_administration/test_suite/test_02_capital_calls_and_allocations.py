"""Capital-call issuance, allocation split, funding, default, and the branching
capital-call state machine. Covers difficulty queue branching/cascade instances
plus corner queue allocation/transition instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_limited_partner_headers,
    fund_allocation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]


# ---------------------------------------------------------------------------
# Allocation split (largest-remainder) and excused redistribution
# ---------------------------------------------------------------------------

def test_capital_call_largest_remainder_split(api):
    """PRD §3.3: "Each commitment first receives the floor of its exact share as its `allocated_amount_cents`; the leftover cents — the called amount minus the sum of those floors — are then distributed one cent each to the commitments with the largest fractional remainders, ties broken by the commitment's `created_at` in ascending order, exactly as the cent-ledger discipline of §2.5 prescribes."

    Design: Corner/calculations/capital_call_largest_remainder_split
    """
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Remainder Fund")
    c1, c2 = commitments
    call = fx.issue_capital_call(fund["id"], 1_000_001)
    a1 = fx.allocation_for_commitment(call["id"], c1["id"])
    a2 = fx.allocation_for_commitment(call["id"], c2["id"])
    # 1000001 * 6/10 = 600000.6 -> floor 600000, frac .6 (largest, c1 created first)
    # 1000001 * 4/10 = 400000.4 -> floor 400000, frac .4 ; leftover 1 cent -> c1
    assert a1["allocated_amount_cents"] == 600001
    assert a2["allocated_amount_cents"] == 400000


def test_excused_lp_redistribution_variant(api):
    """PRD §3.7: "When an LP holds an `EXECUTED` side letter whose `excused_purposes` contains the call's `purpose`, that LP's commitment is dropped from the participant set entirely, and its would-be share is redistributed pro-rata among the remaining commitments rather than being left unfunded — so the full `called_amount_cents` is still raised from the non-excused participants."

    Design: Corner/calculations/excused_lp_redistribution_variant
    """
    fund, commitments, lps = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Excuse Fund")
    c1, c2 = commitments
    sl = validate_success(api.create_side_letter(
        {"fund_id": fund["id"], "lp_id": lps[1]["id"], "mfn_rank": 1,
         "excused_purposes": ["EXPENSE"]}, TEST_USERS["compliance_officer_headers"]), 201)
    api.execute_side_letter(sl["id"], TEST_USERS["compliance_officer_headers"])
    call = fx.issue_capital_call(fund["id"], 1_000_000, purpose="EXPENSE")
    a1 = fx.allocation_for_commitment(call["id"], c1["id"])
    assert a1["allocated_amount_cents"] == 1_000_000
    # No allocation exists for the excused commitment c2 on this call.
    c2_allocs = validate_success(api.list_allocations(
        FA, params={"commitment_id": c2["id"], "capital_call_id": call["id"]}), 200)
    assert c2_allocs == [], "excused commitment must not receive an allocation"


# ---------------------------------------------------------------------------
# Branching state machine — partial default / full default / settle / cancel
# ---------------------------------------------------------------------------

def test_capital_call_branches_to_partially_defaulted(api):
    """PRD §3.3: "If, after the default, at least one allocation of the call is `DEFAULTED` while at least one other remains `PAID` or `PENDING`, the call moves from `ISSUED` to `PARTIALLY_DEFAULTED`."

    Design: Difficulty/non_linear_state_machine/capital_call_branches_to_partially_defaulted
    """
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Branch Fund")
    api.activate_fund(fund["id"], FM)
    c1, c2 = commitments
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    a1 = fx.allocation_for_commitment(call["id"], c1["id"])
    a2 = fx.allocation_for_commitment(call["id"], c2["id"])
    validate_success(api.default_allocation(a1["id"], FA), 200)
    final_call = validate_success(api.get_capital_call(call["id"], FM), 200)
    assert final_call["status"] == "PARTIALLY_DEFAULTED"
    assert validate_success(api.get_allocation(a1["id"], FM), 200)["status"] == "DEFAULTED"
    assert validate_success(api.get_allocation(a2["id"], FM), 200)["status"] == "PENDING"


def test_capital_call_partial_default_leaves_peer_fundable(api):
    """PRD §3.3: "If, after the default, at least one allocation of the call is `DEFAULTED` while at least one other remains `PAID` or `PENDING`, the call moves from `ISSUED` to `PARTIALLY_DEFAULTED`."

    Design: Difficulty/non_linear_state_machine/capital_call_branches_to_partially_defaulted
    """
    # Default the SECOND allocation instead of the first; the call still branches to
    # PARTIALLY_DEFAULTED because the peer (first) allocation is still PENDING.
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [5_000_000, 5_000_000], name="Branch Peer Fund")
    c1, c2 = commitments
    call = fx.issue_capital_call(fund["id"], 2_000_000)
    a1 = fx.allocation_for_commitment(call["id"], c1["id"])
    a2 = fx.allocation_for_commitment(call["id"], c2["id"])
    validate_success(api.default_allocation(a2["id"], FA), 200)
    assert validate_success(api.get_capital_call(call["id"], FM), 200)["status"] == "PARTIALLY_DEFAULTED"
    assert validate_success(api.get_allocation(a1["id"], FM), 200)["status"] == "PENDING"


def test_partially_defaulted_call_settles_after_remaining_funded(api):
    """PRD §3.3: "A call sitting in `PARTIALLY_DEFAULTED` settles by the same rule once every one of its non-`DEFAULTED` allocations is `PAID` or `WAIVED`, moving from `PARTIALLY_DEFAULTED` to `SETTLED`."

    Design: Corner/state_machines/fund_partially_defaulted_to_settled_after_remaining_funded
    """
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="PartSettle Fund")
    c1, c2 = commitments
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    a1 = fx.allocation_for_commitment(call["id"], c1["id"])
    a2 = fx.allocation_for_commitment(call["id"], c2["id"])
    api.default_allocation(a1["id"], FA)
    paid = validate_success(
        api.fund_allocation(a2["id"], fund_allocation_payload(a2["allocated_amount_cents"]), FA), 200)
    assert paid["status"] == "PAID"
    assert validate_success(api.get_capital_call(call["id"], FM), 200)["status"] == "SETTLED"


def test_single_allocation_call_fully_defaults(api):
    """PRD §3.3: "If instead every allocation of the call is now `DEFAULTED`, the call moves from `ISSUED` to `DEFAULTED`."

    Design: Corner/state_machines/distribution_default_branch_all_allocations_defaulted
    """
    fund = fx.create_fund(name="FullDefault Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP FD", tax_id_last4="2222")
    fx.create_accepted_commitment(fund["id"], lp["id"], 6_000_000)
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    alloc = fx.list_call_allocations(call["id"])[0]
    defaulted = validate_success(api.default_allocation(alloc["id"], FA), 200)
    assert defaulted["status"] == "DEFAULTED"
    assert validate_success(api.get_capital_call(call["id"], FM), 200)["status"] == "DEFAULTED"


def test_cancel_call_waives_all_allocations(api):
    """PRD §3.3: "A `FundManager` may cancel a call that is still `ISSUED` provided none of its allocations has yet been `PAID`; cancellation moves the call from `ISSUED` to `CANCELLED` and cascades every one of its allocations to `WAIVED`."

    Design: Corner/state_machines/cancel_call_waives_allocations_compensation
    """
    fund = fx.create_fund(name="Cancel Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP CW", tax_id_last4="1818")
    fx.create_accepted_commitment(fund["id"], lp["id"], 6_000_000)
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    alloc = fx.list_call_allocations(call["id"])[0]
    cancelled = validate_success(api.cancel_capital_call(call["id"], FM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_allocation(alloc["id"], FM), 200)["status"] == "WAIVED"


# ---------------------------------------------------------------------------
# Transitive cascade — commitment default -> allocation -> call
# ---------------------------------------------------------------------------

def test_commitment_default_cascades_to_call_partially_defaulted(api):
    """PRD §3.2: "Declaring the default cascades: every `CapitalCallAllocation` on that commitment still in `PENDING` status is moved to `DEFAULTED`, and each affected parent `CapitalCall` is re-evaluated and may move from `ISSUED` to `PARTIALLY_DEFAULTED` as described in §3.3."

    Design: Difficulty/transitive_cascade/commitment_default_cascades_to_call_partially_defaulted
    """
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Cascade Fund")
    api.activate_fund(fund["id"], FM)
    c_k, c_l = commitments
    # First call: default LP K's allocation to lift default_strike_count to 1.
    call1 = fx.issue_capital_call(fund["id"], 1_000_000)
    k_alloc1 = fx.allocation_for_commitment(call1["id"], c_k["id"])
    api.default_allocation(k_alloc1["id"], FA)
    # Second call: K and L both have PENDING allocations.
    call2 = fx.issue_capital_call(fund["id"], 900_000)
    k_alloc2 = fx.allocation_for_commitment(call2["id"], c_k["id"])
    # Declare default on commitment K (strike count now >= 1).
    defaulted = validate_success(api.declare_default_commitment(c_k["id"], FM), 200)
    assert defaulted["status"] == "DEFAULTED"
    assert validate_success(api.get_allocation(k_alloc2["id"], FM), 200)["status"] == "DEFAULTED"
    assert validate_success(api.get_capital_call(call2["id"], FM), 200)["status"] == "PARTIALLY_DEFAULTED"


def test_allocation_default_recomputes_lp_strike_count(api):
    """PRD §3.3: "Defaulting an allocation is reserved to the `FundAdministrator` and moves the allocation from `PENDING` to `DEFAULTED`. Doing so recomputes the owning LP's `default_strike_count` and re-evaluates the parent call."
    PRD §2.6: "A `LimitedPartner` carries `default_strike_count`, the count of that LP's capital-call allocations (across all of its commitments) whose `status` is `DEFAULTED`."

    Design: Difficulty/transitive_cascade/commitment_default_cascades_to_call_partially_defaulted
    """
    fund, commitments, lps = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="StrikeCount Fund")
    c_k = commitments[0]
    lp_k = lps[0]
    assert validate_success(api.get_limited_partner(lp_k["id"], FM), 200)["default_strike_count"] == 0
    call = fx.issue_capital_call(fund["id"], 1_000_000)
    k_alloc = fx.allocation_for_commitment(call["id"], c_k["id"])
    api.default_allocation(k_alloc["id"], FA)
    refreshed = validate_success(api.get_limited_partner(lp_k["id"], FM), 200)
    assert refreshed["default_strike_count"] == 1


# ---------------------------------------------------------------------------
# Derived field reconciliation after funding
# ---------------------------------------------------------------------------

def test_drawn_cents_reconciled_after_funding(api):
    """PRD §2.6: "Its `drawn_cents` is the sum of `paid_amount_cents` over its capital-call allocations whose `status` is `PAID`, reduced by any recycling restorations applied to that commitment."
    PRD §2.6: "Its `unfunded_cents` is `committed_cents` minus `drawn_cents`, floored at zero — the remaining callable capital."

    Design: Corner/cross_cutting_complexity_layers/derived_drawn_cents_reconciled_after_funding
    """
    fund = fx.create_fund(name="Derived Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP DR", tax_id_last4="4343")
    commitment = fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    call = fx.issue_capital_call(fund["id"], 5_000_000)
    alloc = fx.list_call_allocations(call["id"])[0]
    validate_success(
        api.fund_allocation(alloc["id"], fund_allocation_payload(alloc["allocated_amount_cents"]), FA), 200)
    refreshed = validate_success(api.get_commitment(commitment["id"], FM), 200)
    assert refreshed["drawn_cents"] == 5_000_000
    assert refreshed["unfunded_cents"] == 0


def test_partial_funding_rejected(api):
    """PRD §3.3: "Funding is all-or-nothing: the supplied `paid_amount_cents` must equal the allocation's `allocated_amount_cents`, and any other value — partial funding — is rejected with `ERR_PARTIAL_FUNDING_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/partial_funding_rejected
    """
    fund = fx.create_fund(name="Partial Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP PF", tax_id_last4="2828")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    call = fx.issue_capital_call(fund["id"], 5_000_000)
    alloc = fx.list_call_allocations(call["id"])[0]
    validate_error(api.fund_allocation(alloc["id"], fund_allocation_payload(1_000_000), FA),
                   "ERR_PARTIAL_FUNDING_NOT_ALLOWED", 422)


def test_capital_call_exceeds_unfunded_rejected(api):
    """PRD §3.3: "The aggregate `called_amount_cents` must not exceed the sum of `unfunded_cents` across those participating commitments; if it does, the call is rejected with `ERR_CALL_EXCEEDS_UNFUNDED` (HTTP 422)."

    Design: Corner/validations/capital_call_exceeds_unfunded_rejected
    """
    fund = fx.create_fund(name="Exceed Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP CE", tax_id_last4="2929")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    version = fx.fund_version(fund["id"])
    from test_helpers import create_capital_call_payload
    payload = create_capital_call_payload(fund["id"], version, called_amount_cents=7_000_000)
    validate_error(api.create_capital_call(payload, FM), "ERR_CALL_EXCEEDS_UNFUNDED", 422)
