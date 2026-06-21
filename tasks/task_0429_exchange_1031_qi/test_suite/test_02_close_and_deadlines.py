"""Closing the relinquished leg, deadline derivation, posture transitions, and the
45/180-day deadline boundaries.

Translates difficulty rules: combinatorial_formula (deadline order), transitive_cascade
(close depth-3), boundary_precision_check (45th-day inclusive), resource_temporal_overlap
(both deadline windows); and corner sections state_machines / consistency_model / validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    make_qi_coordinator_headers,
    set_clock, create_exchanger, create_exchange, get_trust,
    setup_draft_exchange_with_children, setup_closed_exchange,
    setup_draft_identification, setup_finalized_identification,
)
from test_helpers.factories import (
    create_relinquished_property_payload, create_identification_payload,
    create_candidate_payload,
)


# ── Close cascade & pinned evaluation order ──────────────────────────

def test_close_relinquished_cascade_to_trust(api):
    """PRD §3.3: "The computed `net_proceeds` is then deposited into the qualified
    trust, credited to both `deposited_amount` and `available_balance` (the cascade
    from relinquished close to trust deposit)."

    Design: Difficulty/transitive_cascade/close_relinquished_cascade_depth3
    """
    exchange, rel, trust = setup_draft_exchange_with_children("FORWARD", "coord-cas")
    headers = make_qi_coordinator_headers("coord-cas")
    validate_success(api.close_relinquished(exchange["id"], headers))
    rel_after = validate_success(api.list_relinquished_properties(exchange["id"], headers))[0]
    trust_after = validate_success(api.list_trust(exchange["id"], headers))[0]
    assert rel_after["net_proceeds"] == pytest.approx(350000.00, abs=0.01)
    assert trust_after["deposited_amount"] == pytest.approx(350000.00, abs=0.01)
    assert trust_after["available_balance"] == pytest.approx(350000.00, abs=0.01)


def test_close_relinquished_net_proceeds_and_available_balance_equal(api):
    """PRD §3.3: "The computed `net_proceeds` is then deposited into the qualified
    trust, credited to both `deposited_amount` and `available_balance` (the cascade
    from relinquished close to trust deposit)."

    Design: Difficulty/transitive_cascade/close_relinquished_cascade_depth3
    """
    exchange, rel, trust = setup_draft_exchange_with_children("FORWARD", "coord-cas2")
    headers = make_qi_coordinator_headers("coord-cas2")
    validate_success(api.close_relinquished(exchange["id"], headers))
    trust_after = validate_success(api.list_trust(exchange["id"], headers))[0]
    assert trust_after["deposited_amount"] == trust_after["available_balance"], (
        "available_balance must equal deposited_amount immediately after close (no disbursements)"
    )


def test_close_stamps_deadlines_in_pinned_order(api):
    """PRD §3.3: "It stamps `relinquished_closing_at` to the current logical clock —
    this is the Day-0 anchor. From that anchor it derives `id_deadline_at` as the
    closing instant plus 45 calendar days at the same time of day, and
    `exchange_deadline_at` as the closing instant plus 180 calendar days at the same
    time of day."

    Design: Difficulty/combinatorial_formula/deadline_evaluation_order_pinned_dependency
    """
    exchange, rel, trust = setup_draft_exchange_with_children("FORWARD", "coord-dl")
    headers = make_qi_coordinator_headers("coord-dl")
    closed = validate_success(api.close_relinquished(exchange["id"], headers))
    assert closed["relinquished_closing_at"] == "2026-03-01T00:00:00.000Z"
    assert closed["id_deadline_at"] == "2026-04-15T00:00:00.000Z"
    assert closed["exchange_deadline_at"] == "2026-08-28T00:00:00.000Z"


def test_close_computes_realized_gain_and_deposit_after_anchor(api):
    """PRD §3.3: "It computes the exchange's `realized_gain` by first taking the
    **amount realized** — the `fair_market_value` less the `selling_expenses` — and
    then subtracting the `adjusted_basis`."

    Design: Difficulty/combinatorial_formula/deadline_evaluation_order_pinned_dependency
    """
    exchange, rel, trust = setup_draft_exchange_with_children("FORWARD", "coord-dl2")
    headers = make_qi_coordinator_headers("coord-dl2")
    closed = validate_success(api.close_relinquished(exchange["id"], headers))
    assert closed["realized_gain"] == pytest.approx(290000.00, abs=0.01)
    trust_after = validate_success(api.list_trust(exchange["id"], headers))[0]
    assert trust_after["deposited_amount"] == pytest.approx(350000.00, abs=0.01)


def test_deposit_immediately_visible_after_close(api):
    """PRD §3.3: "The computed `net_proceeds` is then deposited into the qualified
    trust, credited to both `deposited_amount` and `available_balance` (the cascade
    from relinquished close to trust deposit)."

    Design: Corner/consistency_model/immediate_visibility_of_deposit_after_close
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-im2")
    headers = make_qi_coordinator_headers("coord-im2")
    trust_read = validate_success(api.list_trust(closed["id"], headers))[0]
    assert trust_read["deposited_amount"] == pytest.approx(350000.00, abs=0.01)
    assert trust_read["available_balance"] == pytest.approx(350000.00, abs=0.01)


# ── Realized-gain precision ──────────────────────────────────────────

def test_realized_gain_two_decimal_precision(api):
    """PRD §3.3: "It computes the exchange's `realized_gain` by first taking the
    **amount realized** — the `fair_market_value` less the `selling_expenses` — and
    then subtracting the `adjusted_basis`."
    PRD §2.6: "every rounding step uses the **round half up** convention."

    Design: Corner/calculations/realized_gain_precision_two_decimals
    """
    set_clock("2026-03-01T00:00:00Z", "coord-prc")
    exr = create_exchanger("coord-prc")
    ex = create_exchange(exr["id"], "FORWARD", "coord-prc")
    headers = make_qi_coordinator_headers("coord-prc")
    validate_success(
        api.create_relinquished_property(
            ex["id"],
            create_relinquished_property_payload(
                fair_market_value=500000, selling_expenses=30000.50,
                mortgage_payoff=120000, adjusted_basis=180000.25,
            ),
            headers,
        ),
        expected_status=201,
    )
    validate_success(api.create_trust(ex["id"], headers), expected_status=201)
    closed = validate_success(api.close_relinquished(ex["id"], headers))
    assert closed["realized_gain"] == pytest.approx(289999.25, abs=0.01)
    assert closed["recognized_gain"] is None, "recognized_gain is null until a replacement is recorded"


# ── Posture auto-transition ──────────────────────────────────────────

def test_posture_becomes_at_risk_after_45day_lapse(api):
    """PRD §3.3: "If the logical clock advances past `id_deadline_at` while no
    identification has reached `FINALIZED`, a posture recomputation moves the exchange
    to `AT_RISK`; this recomputation happens lazily whenever the exchange is read or
    otherwise mutated."

    Design: Corner/state_machines/posture_auto_transitions_at_risk_after_45day_lapse
    """
    closed, rel, trust = setup_closed_exchange("FORWARD", "coord-ar")
    set_clock("2026-04-16T00:00:00Z", "coord-ar")
    headers = make_qi_coordinator_headers("coord-ar")
    data = validate_success(api.get_exchange(closed["id"], headers))
    assert data["compliance_posture"] == "AT_RISK", (
        f"posture must be AT_RISK past id_deadline with no finalized id, got {data['compliance_posture']}"
    )


# ── Identification 45-day window boundary ────────────────────────────

def test_finalize_at_exact_45th_day_inclusive_succeeds(api):
    """PRD §3.4: "Finalizing requires the parent exchange to be in `ACTIVE` status, at
    least one candidate still in `CANDIDATE` status to exist, the current clock to be
    on or before `id_deadline_at`, and no other identification on the same exchange to
    have already reached `FINALIZED`."

    Design: Difficulty/boundary_precision_check/id_deadline_exact_45th_day_inclusive
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-e45")
    set_clock("2026-04-15T00:00:00Z", "coord-e45")
    headers = make_qi_coordinator_headers("coord-e45")
    data = validate_success(api.finalize_identification(idn["id"], headers))
    assert data["status"] == "FINALIZED", "45th-day-at-00:00:00Z finalize must succeed (inclusive)"
    ex = validate_success(api.get_exchange(exchange["id"], headers))
    assert ex["compliance_posture"] == "IDENTIFIED"


def test_finalize_at_exact_45th_day_stamps_finalized_at(api):
    """PRD §3.4: "A successful finalize stamps `finalized_at` to the current clock,
    sets the identification's `status` to `FINALIZED`."

    Design: Difficulty/boundary_precision_check/id_deadline_exact_45th_day_inclusive
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-e45b")
    set_clock("2026-04-15T00:00:00Z", "coord-e45b")
    headers = make_qi_coordinator_headers("coord-e45b")
    data = validate_success(api.finalize_identification(idn["id"], headers))
    assert data["status"] == "FINALIZED"
    assert data["finalized_at"] == "2026-04-15T00:00:00.000Z", (
        "finalize on the inclusive 45th-day boundary stamps finalized_at to that instant"
    )


def test_finalize_one_day_past_45day_window_rejected(api):
    """PRD §3.4: "A finalize attempted after `id_deadline_at` is rejected with
    `ERR_ID_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/id_window_closed_inclusive_45day_overlap
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-w45")
    set_clock("2026-04-16T00:00:00Z", "coord-w45")
    headers = make_qi_coordinator_headers("coord-w45")
    resp = api.finalize_identification(idn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_ID_DEADLINE_PASSED.value)
    after = validate_success(api.get_identification(idn["id"], headers))
    assert after["status"] == "DRAFT", "identification must remain DRAFT after rejected finalize"


def test_finalize_past_45day_window_leaves_posture_not_identified(api):
    """PRD §3.4: "A finalize attempted after `id_deadline_at` is rejected with
    `ERR_ID_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/id_window_closed_inclusive_45day_overlap
    """
    exchange, trust, idn, cands = setup_draft_identification("FORWARD", "coord-w45b")
    set_clock("2026-04-16T00:00:00Z", "coord-w45b")
    headers = make_qi_coordinator_headers("coord-w45b")
    resp = api.finalize_identification(idn["id"], headers)
    validate_error(resp, ApiErrorId.ERR_ID_DEADLINE_PASSED.value)
    ex = validate_success(api.get_exchange(exchange["id"], headers))
    assert ex["compliance_posture"] != "IDENTIFIED", (
        "a rejected past-deadline finalize must not flip posture to IDENTIFIED"
    )


# ── Replacement 180-day window boundary ──────────────────────────────

def test_replacement_at_exact_180th_day_inclusive_succeeds(api):
    """PRD §3.5: "Because acquisition is a deadline-bound act, it must occur on or
    before `exchange_deadline_at`; an acquisition attempted after the 180-day deadline
    is rejected with `ERR_EXCHANGE_DEADLINE_PASSED`."

    Design: Corner/validations/replacement_after_deadline_satisfaction_within_window_passes
    """
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-win")
    set_clock("2026-08-28T00:00:00Z", "coord-win")
    headers = make_qi_coordinator_headers("coord-win")
    from test_helpers.factories import create_replacement_property_payload
    rp = validate_success(
        api.create_replacement_property(
            exchange["id"],
            create_replacement_property_payload(cands[0]["id"], purchase_price=420000, replacement_debt=120000),
            headers,
        ),
        expected_status=201,
    )
    assert rp["acquired_at"] == "2026-08-28T00:00:00.000Z"
    cand_after = validate_success(api.list_candidates(idn["id"], headers))[0]
    assert cand_after["status"] == "ACQUIRED"


def test_replacement_one_day_past_180day_window_rejected(api):
    """PRD §3.5: "an acquisition attempted after the 180-day deadline is rejected with
    `ERR_EXCHANGE_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/exchange_window_closed_inclusive_180day_overlap
    """
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-w180")
    set_clock("2026-08-29T00:00:00Z", "coord-w180")
    headers = make_qi_coordinator_headers("coord-w180")
    from test_helpers.factories import create_replacement_property_payload
    resp = api.create_replacement_property(
        exchange["id"],
        create_replacement_property_payload(cands[0]["id"], purchase_price=420000, replacement_debt=120000),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_DEADLINE_PASSED.value)
    rps = validate_success(api.list_exchange_replacement_properties(exchange["id"], headers))
    assert len(rps) == 0, "no replacement may be created past the 180-day deadline"


def test_replacement_past_180day_leaves_candidate_unacquired(api):
    """PRD §3.5: "an acquisition attempted after the 180-day deadline is rejected with
    `ERR_EXCHANGE_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/exchange_window_closed_inclusive_180day_overlap
    """
    exchange, trust, idn, cands = setup_finalized_identification("FORWARD", "coord-w180b")
    set_clock("2026-08-29T00:00:00Z", "coord-w180b")
    headers = make_qi_coordinator_headers("coord-w180b")
    from test_helpers.factories import create_replacement_property_payload
    resp = api.create_replacement_property(
        exchange["id"],
        create_replacement_property_payload(cands[0]["id"], purchase_price=420000, replacement_debt=120000),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_DEADLINE_PASSED.value)
    cand_after = validate_success(api.list_candidates(idn["id"], headers))[0]
    assert cand_after["status"] == "CANDIDATE", (
        "a rejected past-deadline acquisition must not flip the candidate to ACQUIRED"
    )
