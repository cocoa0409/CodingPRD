"""Chargeback allocation: pinned per-share rounding with remainder-to-top-weight,
the sum-conservation invariant, weight-sum validation, and cost-center gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_invoice_with_line, setup_three_cost_centers,
    allocations_payload, assert_allocation_sum_conserves_net,
    make_cost_center_owner_headers, new_cost_center,
    TEST_USERS,
)

_ANALYST = TEST_USERS["analyst_headers"]


def _line_with_net(api, net):
    """Reviewed-independent BILLED line whose net_amount_cents == billed == net."""
    scen = setup_invoice_with_line(
        api, line_overrides={"billed_amount_cents": net, "billed_quantity": 60}, do_review=False)
    return scen


# ---------------------------------------------------------------------------
# combinatorial_formula / chargeback_rounding_remainder_top_weight_mode_b
# ---------------------------------------------------------------------------

def test_chargeback_rounds_each_share_then_reconciles_to_top_weight(api):
    """PRD §3.6: "each raw share is rounded half up to whole cents individually first. The signed
    remainder — the line's net amount minus the sum of the rounded shares, which may be positive
    or negative — is then assigned in its entirety to the single allocation with the highest
    weight_pct (ties broken by the earliest cost center created_at). That top-weight allocation's
    amount_cents is its rounded share plus the remainder"

    net 90500 split 33.33/33.33/33.34: rounded shares 30164/30164/30173 sum to 90501; remainder
    -1 lands on the 33.34 top-weight share -> {30164, 30164, 30172}.

    Design: Difficulty/combinatorial_formula/chargeback_rounding_remainder_top_weight_mode_b
    """
    scen = _line_with_net(api, 90500)
    ccs = setup_three_cost_centers(api)
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([
            {"cost_center_id": ccs[0]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[1]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[2]["id"], "weight_pct": 33.34},
        ]),
        _ANALYST), 201)
    assert allocs[0]["amount_cents"] == 30164, f"share A should be 30164, got {allocs[0]['amount_cents']}"
    assert allocs[2]["amount_cents"] == 30172, f"top-weight share C should be 30172, got {allocs[2]['amount_cents']}"


def test_chargeback_middle_share_keeps_own_rounded_value(api):
    """PRD §3.6: "every other allocation's amount_cents is simply its own rounded share. This
    round-each-share-then-reconcile-to-top order is mandatory — a naive sum-then-round is
    explicitly not used"

    For net 90500 split 33.33/33.33/33.34 the non-top shares keep their own rounded 30164; only
    the top-weight share absorbs the -1 remainder -> {30164, 30164, 30172}.

    Design: Difficulty/combinatorial_formula/chargeback_rounding_remainder_top_weight_mode_b
    """
    scen = _line_with_net(api, 90500)
    ccs = setup_three_cost_centers(api)
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([
            {"cost_center_id": ccs[0]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[1]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[2]["id"], "weight_pct": 33.34},
        ]),
        _ANALYST), 201)
    amounts = [a["amount_cents"] for a in allocs]
    assert amounts == [30164, 30164, 30172], f"amounts should be [30164, 30164, 30172], got {amounts}"


# ---------------------------------------------------------------------------
# compensating_invariant / chargeback_sum_conserves_line_net
# ---------------------------------------------------------------------------

def test_chargeback_shares_sum_to_line_net(api):
    """PRD §2.7: "the chargeback invariant: the amount_cents of the allocations created for a
    single line item always sum to exactly that line's net_amount_cents at the time of
    allocation."

    net 90500 split 33.33/33.33/33.34 -> shares sum to exactly 90500.

    Design: Difficulty/compensating_invariant/chargeback_sum_conserves_line_net
    """
    scen = _line_with_net(api, 90500)
    ccs = setup_three_cost_centers(api)
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([
            {"cost_center_id": ccs[0]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[1]["id"], "weight_pct": 33.33},
            {"cost_center_id": ccs[2]["id"], "weight_pct": 33.34},
        ]),
        _ANALYST), 201)
    assert_allocation_sum_conserves_net(allocs, 90500)
    line = validate_success(api.get_line_item(scen["line"]["id"], _ANALYST))
    assert line["net_amount_cents"] == 90500, f"line net should be 90500, got {line['net_amount_cents']}"


def test_chargeback_invariant_holds_for_uneven_weights(api):
    """PRD §2.7: "the amount_cents of the allocations created for a single line item always sum to
    exactly that line's net_amount_cents at the time of allocation."
    PRD §3.6: "it guarantees the shares' amount_cents sum exactly to the line's net_amount_cents."

    A different weight split (50/30/20) still conserves the line net (90500).

    Design: Difficulty/compensating_invariant/chargeback_sum_conserves_line_net
    """
    scen = _line_with_net(api, 90500)
    ccs = setup_three_cost_centers(api)
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([
            {"cost_center_id": ccs[0]["id"], "weight_pct": 50.00},
            {"cost_center_id": ccs[1]["id"], "weight_pct": 30.00},
            {"cost_center_id": ccs[2]["id"], "weight_pct": 20.00},
        ]),
        _ANALYST), 201)
    assert_allocation_sum_conserves_net(allocs, 90500)


# ---------------------------------------------------------------------------
# Corner: validations / allocation_weight_sum_not_100_returns_error
# ---------------------------------------------------------------------------

def test_allocation_weight_sum_not_100_returns_error(api):
    """PRD §3.6: "The weights across the set must sum to exactly 100.00, or the whole request is
    rejected with ERR_INVALID_WEIGHT_SUM."

    50.00 + 40.00 = 90.00 (not 100.00).

    Design: Corner/validations/allocation_weight_sum_not_100_returns_error
    """
    scen = _line_with_net(api, 90000)
    cc_a = new_cost_center(api, "CC-A", "6000", "own_a")
    cc_b = new_cost_center(api, "CC-B", "6001", "own_b")
    resp = api.create_allocations(
        scen["line"]["id"],
        allocations_payload([
            {"cost_center_id": cc_a["id"], "weight_pct": 50.00},
            {"cost_center_id": cc_b["id"], "weight_pct": 40.00},
        ]),
        _ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT_SUM.value)


# ---------------------------------------------------------------------------
# Corner: validations / approve_allocation_frozen_cost_center_returns_error
# ---------------------------------------------------------------------------

def test_approve_allocation_frozen_cost_center_returns_error(api):
    """PRD §3.6: "the cost center must be ACTIVE — an allocation against a FROZEN cost center is
    rejected with ERR_COST_CENTER_FROZEN."
    PRD §3.6: "freezing an already-ACTIVE cost center sets its status to FROZEN and increments its
    version, and a FROZEN cost center blocks allocation approval."

    Design: Corner/validations/approve_allocation_frozen_cost_center_returns_error
    """
    scen = _line_with_net(api, 100000)
    cc = new_cost_center(api, "CC-A", "6000", "own_a")
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([{"cost_center_id": cc["id"], "weight_pct": 100.00}]),
        _ANALYST), 201)
    validate_success(api.freeze_cost_center(cc["id"], TEST_USERS["system_admin_headers"]))
    resp = api.approve_allocation(allocs[0]["id"], make_cost_center_owner_headers("own_a"))
    validate_error(resp, ApiErrorId.ERR_COST_CENTER_FROZEN.value)


# ---------------------------------------------------------------------------
# Corner: validations / approve_allocation_wrong_owner_returns_error
# ---------------------------------------------------------------------------

def test_approve_allocation_wrong_owner_returns_error(api):
    """PRD §3.6: "the caller's X-User-ID must equal the target cost center's owner_user_id, or the
    request is rejected with ERR_NOT_COST_CENTER_OWNER"

    Cost center owned by own_a; approval attempted by own_b.

    Design: Corner/validations/approve_allocation_wrong_owner_returns_error
    """
    scen = _line_with_net(api, 100000)
    cc = new_cost_center(api, "CC-A", "6000", "own_a")
    allocs = validate_success(api.create_allocations(
        scen["line"]["id"],
        allocations_payload([{"cost_center_id": cc["id"], "weight_pct": 100.00}]),
        _ANALYST), 201)
    resp = api.approve_allocation(allocs[0]["id"], make_cost_center_owner_headers("own_b"))
    validate_error(resp, ApiErrorId.ERR_NOT_COST_CENTER_OWNER.value)
