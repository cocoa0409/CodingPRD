"""Recording replacement properties and the boot / recognized-gain / deferred-gain
arithmetic, including the FORWARD-vs-IMPROVEMENT variant divergence and the gain
conservation invariant.

Translates difficulty rules dual_variant_calc, combinatorial_formula (boot min/max),
compensating_invariant (gain partition), cross_entity_state_dependency (NOT_IDENTIFIED);
and corner sections calculations / entities (defaults, computed fields) / endpoints.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    make_qi_coordinator_headers, make_exchanger_headers,
    assert_gain_partition,
    setup_closed_exchange, setup_finalized_identification, setup_with_replacement,
    create_exchanger,
)
from test_helpers.factories import (
    create_identification_payload, create_candidate_payload,
    create_relinquished_property_payload, create_replacement_property_payload,
)


# ── Variant divergence: IMPROVEMENT counts improvement_value ─────────

def test_improvement_variant_counts_improvement_value(api):
    """PRD §3.5: "For an `IMPROVEMENT` exchange whose improvement completed on or before
    `exchange_deadline_at`, the replacement value equals the `purchase_price` plus the
    `improvement_value`, which raises the cash applied and shrinks the cash boot
    relative to an otherwise identical forward case on the same `purchase_price`."

    Design: Difficulty/dual_variant_calc/boot_final_vs_improvement_variant_on_replacement
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="IMPROVEMENT", coordinator_id="coord-imp", candidate_fmv=420000,
        purchase_price=300000, replacement_debt=0, improvement_value=120000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 0, "adjusted_basis": 200000},
    )
    assert rp["cash_applied"] == pytest.approx(420000.00, abs=0.01), (
        "IMPROVEMENT cash_applied = (purchase 300000 + improvement 120000) - debt 0"
    )
    assert exchange["recognized_gain"] == pytest.approx(50000.00, abs=0.01)
    assert exchange["deferred_gain"] == pytest.approx(220000.00, abs=0.01)


def test_forward_variant_ignores_improvement_value(api):
    """PRD §3.5: "For a `FORWARD` or `REVERSE` exchange, the replacement value equals
    the `purchase_price` and any `improvement_value` is ignored entirely."

    Design: Difficulty/dual_variant_calc/boot_final_vs_improvement_variant_on_replacement
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-fwdv", candidate_fmv=420000,
        purchase_price=300000, replacement_debt=0,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 0, "adjusted_basis": 200000},
    )
    # FORWARD: cash_applied = 300000 - 0 = 300000; cash_boot = 470000 - 300000 = 170000;
    # mortgage_boot = max(0, 0 - 0) = 0; total_boot 170000; recognized = min(270000, 170000) = 170000.
    assert rp["cash_applied"] == pytest.approx(300000.00, abs=0.01)
    assert exchange["recognized_gain"] == pytest.approx(170000.00, abs=0.01), (
        "FORWARD ignores improvement so recognized_gain diverges from the IMPROVEMENT variant"
    )


# ── Boot nonlinear min/max branch ────────────────────────────────────

def test_boot_recognized_gain_nonlinear_min_max(api):
    """PRD §3.5: "The **cash boot** is the greater of zero and the trust's
    `deposited_amount` less the `cash_applied` ... The **mortgage boot** is the greater
    of zero and the relinquished property's `mortgage_payoff` less the
    `replacement_debt` ... The exchange's `recognized_gain` is the lesser of the
    exchange's `realized_gain` and the total boot."

    Design: Difficulty/combinatorial_formula/boot_recognized_gain_nonlinear_min_max_branch
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-boot", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=100000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    # cash_applied = 420000 - 100000 = 320000; cash_boot = 350000 - 320000 = 30000;
    # mortgage_boot = 120000 - 100000 = 20000; total_boot 50000; recognized = min(290000, 50000).
    assert rp["cash_applied"] == pytest.approx(320000.00, abs=0.01)
    assert exchange["recognized_gain"] == pytest.approx(50000.00, abs=0.01)
    assert exchange["deferred_gain"] == pytest.approx(240000.00, abs=0.01)


def test_boot_legs_cash_applied_and_recognized_capped_by_boot(api):
    """PRD §3.5: "The **cash applied** to the replacement — stored as `cash_applied` —
    is the replacement value less the `replacement_debt`."
    PRD §3.5: "The **total boot** is the sum of the cash boot and the mortgage boot."

    Design: Difficulty/combinatorial_formula/boot_recognized_gain_nonlinear_min_max_branch
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-boot2", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=100000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    assert rp["cash_applied"] == pytest.approx(320000.00, abs=0.01)
    # total_boot = cash_boot 30000 + mortgage_boot 20000 = 50000, which is below
    # realized_gain 290000, so recognized_gain equals the total boot, not realized.
    assert exchange["recognized_gain"] == pytest.approx(50000.00, abs=0.01)
    assert exchange["recognized_gain"] < exchange["realized_gain"], (
        "recognized_gain is min(realized, total_boot) and here total_boot is the binding term"
    )


def test_full_reinvestment_zero_boot(api):
    """PRD §3.5: "The **cash boot** is the greater of zero and the trust's
    `deposited_amount` less the `cash_applied`; it can never be negative ... The
    exchange's `recognized_gain` is the lesser of the exchange's `realized_gain` and
    the total boot."

    Design: Corner/calculations/full_reinvestment_zero_boot_recognized_gain_zero
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-ful", candidate_fmv=480000,
        purchase_price=480000, replacement_debt=120000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    # cash_applied = 480000 - 120000 = 360000 >= deposited 350000 -> cash_boot 0;
    # mortgage_boot = max(0, 120000 - 120000) = 0; total_boot 0; recognized 0.
    assert rp["cash_applied"] == pytest.approx(360000.00, abs=0.01)
    assert exchange["recognized_gain"] == pytest.approx(0.00, abs=0.01)
    assert exchange["deferred_gain"] == pytest.approx(290000.00, abs=0.01)


# ── Gain conservation invariant ──────────────────────────────────────

def test_gain_conserved_realized_equals_recognized_plus_deferred(api):
    """PRD §3.5: "The exchange's `deferred_gain` is the `realized_gain` less the
    `recognized_gain`, so that recognized and deferred gain always partition the
    realized gain exactly."

    Design: Difficulty/compensating_invariant/gain_conserved_realized_equals_recognized_plus_deferred
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-cn2", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=100000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    assert exchange["realized_gain"] == pytest.approx(290000.00, abs=0.01)
    assert exchange["recognized_gain"] == pytest.approx(50000.00, abs=0.01)
    assert exchange["deferred_gain"] == pytest.approx(240000.00, abs=0.01)
    assert_gain_partition(exchange)


def test_gain_partition_holds_for_full_reinvestment(api):
    """PRD §3.5: "The exchange's `deferred_gain` is the `realized_gain` less the
    `recognized_gain`, so that recognized and deferred gain always partition the
    realized gain exactly."

    Design: Difficulty/compensating_invariant/gain_conserved_realized_equals_recognized_plus_deferred
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-cn2b", candidate_fmv=480000,
        purchase_price=480000, replacement_debt=120000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    assert exchange["recognized_gain"] == pytest.approx(0.00, abs=0.01)
    assert exchange["deferred_gain"] == pytest.approx(290000.00, abs=0.01)
    assert_gain_partition(exchange)


# ── Defaults & computed fields ───────────────────────────────────────

def test_improvement_value_defaults_to_zero_on_forward(api):
    """PRD §3.5: "an `improvement_value` of zero or greater that defaults to zero."

    Design: Corner/entities/improvement_value_defaults_to_zero_on_forward_replacement
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-def", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=120000,
        rel_overrides={"fair_market_value": 500000, "selling_expenses": 30000,
                       "mortgage_payoff": 120000, "adjusted_basis": 180000},
    )
    assert rp["improvement_value"] == 0, "omitted improvement_value defaults to 0"
    assert rp["cash_applied"] == pytest.approx(300000.00, abs=0.01), (
        "cash_applied = purchase 420000 - debt 120000 with no improvement add"
    )


def test_net_proceeds_zero_before_close(api):
    """PRD §3.2: "The property's `net_proceeds` is a derived figure that remains zero
    until the relinquished leg closes."

    Design: Corner/entities/relinquished_net_proceeds_computed_input_ignored
    """
    from test_helpers.fixtures import set_clock
    set_clock("2026-03-01T00:00:00Z", "coord-cmp2")
    exr = create_exchanger("coord-cmp2")
    headers = make_qi_coordinator_headers("coord-cmp2")
    ex = validate_success(
        api.create_exchange({"exchanger_id": exr["id"], "exchange_type": "FORWARD"}, headers),
        expected_status=201,
    )
    rel = validate_success(
        api.create_relinquished_property(ex["id"], create_relinquished_property_payload(), headers),
        expected_status=201,
    )
    listed = validate_success(api.list_relinquished_properties(ex["id"], headers))[0]
    assert listed["net_proceeds"] == 0, "net_proceeds remains 0 before close"


# ── ERR_NOT_IDENTIFIED ───────────────────────────────────────────────

def test_replacement_requires_finalized_identification(api):
    """PRD §3.5: "The candidate referenced by `identified_property_id` must be an
    `IdentifiedProperty` under *this* exchange's finalized identification whose status
    is still `CANDIDATE`; a reference to a candidate that is not under this exchange's
    finalized identification, or that has already been withdrawn, is rejected with
    `ERR_NOT_IDENTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/replacement_requires_finalized_identification
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-nid")
    headers = make_qi_coordinator_headers("coord-nid")
    idn = validate_success(
        api.create_identification(closed["id"], create_identification_payload("THREE_PROPERTY"), headers),
        expected_status=201,
    )
    cand = validate_success(
        api.add_candidate(idn["id"], create_candidate_payload(estimated_fmv=420000), headers),
        expected_status=201,
    )
    # Identification is still DRAFT (never finalized).
    resp = api.create_replacement_property(
        closed["id"],
        create_replacement_property_payload(cand["id"], purchase_price=420000, replacement_debt=120000),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_IDENTIFIED.value)
    rps = validate_success(api.list_exchange_replacement_properties(closed["id"], headers))
    assert len(rps) == 0, "no replacement created when identification is not finalized"


def test_replacement_marks_candidate_acquired_and_sets_gains(api):
    """PRD §3.5: "Recording a replacement stamps its `acquired_at` to the current
    clock, reclassifies the linked candidate's status from `CANDIDATE` to `ACQUIRED`
    (a downward cascade), and recomputes the exchange's gain figures before
    incrementing the exchange's `version`."

    Design: Difficulty/cross_entity_state_dependency/replacement_requires_finalized_identification
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-nid2", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=120000,
    )
    headers = make_qi_coordinator_headers("coord-nid2")
    cand_after = validate_success(api.list_candidates(idn["id"], headers))[0]
    assert cand_after["status"] == "ACQUIRED", "linked candidate must become ACQUIRED"
    assert exchange["recognized_gain"] is not None and exchange["deferred_gain"] is not None


# ── Cross-reference reachability ─────────────────────────────────────

def test_replacement_reachable_via_exchange_subresource(api):
    """PRD §3.5: "replacements are listable both per exchange and globally with optional
    `exchange_id` and `identified_property_id` filters."

    Design: Corner/endpoints/replacement_property_reverse_reachable_via_subresource
    """
    exchange, trust, idn, cand, rp = setup_with_replacement(
        exchange_type="FORWARD", coordinator_id="coord-rr", candidate_fmv=420000,
        purchase_price=420000, replacement_debt=120000,
    )
    # The exchanger owns the exchange (entity_backed ownership read).
    exchanger_headers = make_exchanger_headers(exchange["exchanger_id"])
    listed = validate_success(api.list_exchange_replacement_properties(exchange["id"], exchanger_headers))
    assert any(r["id"] == rp["id"] for r in listed), "recorded replacement must be discoverable per exchange"
