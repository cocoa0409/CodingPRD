"""Validation precedence pairs, numeric/empty boundaries, and cross-entity state dependencies.

Queue A (Difficulty) rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_program, issue_card, create_active_card,
    setup_draft_redemption_over_cards, settle_redemption,
    setup_card_for_dormancy, setup_frozen_card,
    setup_approved_replacement, draft_redemption,
    create_card_payload, create_redemption_payload, create_bulk_order_payload,
    reload_card_payload,
    TEST_USERS, NON_EXISTENT_UUID,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]


# ── priority_pair_validation_conflict ──────────────────────────────────────

def test_invalid_state_beats_insufficient_balance_on_settle(api):
    """PRD §2.11: "Eighth, the target resource's state is checked against the transition,
    yielding ERR_INVALID_STATE."
    PRD §3.5: "that every card in card_id_order has lifecycle_status of ACTIVE
    (ERR_INVALID_STATE) ... and that the sum of available_balance_cents across the listed
    cards is at least requested_amount_cents (ERR_INSUFFICIENT_BALANCE)."

    Design: Difficulty/priority_pair_validation_conflict/state_invalid_beats_insufficient_balance
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    inactive = issue_card(program["id"])              # never activated → INACTIVE
    # Initial load must be >= reload_min_cents (PRD §3.3); 1000 satisfies that
    # yet leaves the pair under-funded for the 5000 redemption below.
    active = create_active_card(program["id"], 1000)  # ACTIVE but under-funded
    redemption = draft_redemption(
        program["id"], 5000, [inactive["id"], active["id"]])
    res = settle_redemption(redemption["id"], redemption["version"])
    # State check (priority 8) wins over the fiscal sufficiency check (priority 14).
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reference_not_found_beats_invalid_shape_on_bulk_quote(api):
    """PRD §2.11: "Fifth, body foreign keys are checked for same-program existence, yielding
    ERR_REFERENCE_NOT_FOUND. Sixth, domain-shape constraints are checked ... yielding
    ERR_INVALID_REDEMPTION."
    PRD §2.10: "every foreign-key field in the body — including ... buyer_customer_id ... must
    reference an existing entity in the same program, otherwise the request is rejected with
    ERR_REFERENCE_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_bulk_quote
    """
    program = create_program(b2b_discount_pct=0.035)
    # buyer FK missing AND card_count 0 (a domain-shape violation): referential check (5)
    # is evaluated before the shape check (6).
    payload = create_bulk_order_payload(
        program["id"], NON_EXISTENT_UUID, card_count=0, face_value_cents=2500,
        state_code="FL")
    res = api.create_bulk_order(payload, _ADMIN)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=422)


# ── boundary_precision_check ───────────────────────────────────────────────

def test_dormancy_expires_at_exactly_twelve_months_inclusive(api):
    """PRD §3.8: "A card is dormant when that count is at or beyond the applicable
    StateRule's dormancy_threshold_months — the boundary is inclusive, so reaching exactly
    the threshold counts as dormant."

    Design: Difficulty/boundary_precision_check/dormancy_threshold_inclusive_at_exactly_twelve_months
    """
    program, state_rule, card = setup_card_for_dormancy(
        state_rule_kwargs={"expiration_allowed": True, "dormancy_fee_allowed": False,
                           "breakage_policy": "RECOGNIZE", "dormancy_threshold_months": 12},
        activate_at_iso="2025-02-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",  # exactly 12 whole months
        settled_cents=4000)
    after = get_success_data(api.assess_dormancy(card["id"], _ADMIN))
    assert after["lifecycle_status"] == "EXPIRED"
    prog = validate_success(api.get_program(program["id"], _ADMIN), 200)
    assert prog["breakage_recognized_cents"] == 4000


def test_dormancy_not_due_one_day_before_twelve_months(api):
    """PRD §3.8: "If a dormancy assessment is requested but the card has not reached the
    threshold, or an ACTIVE waiver covers the current instant, the request is rejected with
    ERR_DORMANCY_NOT_DUE."

    Design: Difficulty/boundary_precision_check/dormancy_threshold_inclusive_at_exactly_twelve_months
    """
    program, state_rule, card = setup_card_for_dormancy(
        state_rule_kwargs={"expiration_allowed": True, "dormancy_fee_allowed": False,
                           "breakage_policy": "RECOGNIZE", "dormancy_threshold_months": 12},
        activate_at_iso="2025-02-01T00:00:00Z",
        assess_at_iso="2026-01-15T00:00:00Z",  # 11 whole months elapsed (< 12)
        settled_cents=4000)
    res = api.assess_dormancy(card["id"], _ADMIN)
    validate_error(res, "ERR_DORMANCY_NOT_DUE", expected_status=409)


def test_empty_card_order_redemption_draft_rejected(api):
    """PRD §3.5: "At draft and amend time, a positive amount and a non-empty card_id_order
    are required, failing which the request is rejected with ERR_INVALID_REDEMPTION."

    Design: Difficulty/boundary_precision_check/empty_card_order_redemption_draft_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    payload = create_redemption_payload(program["id"], 1000, [])
    res = api.create_redemption(payload, _STORE)
    validate_error(res, "ERR_INVALID_REDEMPTION", expected_status=422)


def test_nonempty_card_order_draft_accepted(api):
    """PRD §3.5: "At draft and amend time, a positive amount and a non-empty card_id_order
    are required, failing which the request is rejected with ERR_INVALID_REDEMPTION."

    Design: Difficulty/boundary_precision_check/empty_card_order_redemption_draft_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    card = create_active_card(program["id"], 2000)
    payload = create_redemption_payload(program["id"], 1000, [card["id"]])
    res = api.create_redemption(payload, _STORE)
    drafted = validate_success(res, 201)
    assert drafted["status"] == "DRAFT", "a non-empty card_id_order drafts successfully"


# ── cross_entity_state_dependency ──────────────────────────────────────────

def test_settle_blocked_when_a_card_is_voided(api):
    """PRD §3.5: "that every card in card_id_order has lifecycle_status of ACTIVE
    (ERR_INVALID_STATE)."

    Design: Difficulty/cross_entity_state_dependency/redemption_settle_requires_every_card_active
    """
    program, voided_card, _ = setup_approved_replacement(settled_cents=2000, reason="LOST")
    # A second, genuinely ACTIVE card in the same program.
    good = create_active_card(program["id"], 5000)
    redemption = draft_redemption(
        program["id"], 1000, [voided_card["id"], good["id"]])
    res = settle_redemption(redemption["id"], redemption["version"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reload_blocked_when_card_risk_frozen(api):
    """PRD §3.3: "The card's risk_status must not be FROZEN_RISK, otherwise the reload is
    rejected with ERR_CARD_RISK_FROZEN."

    Design: Difficulty/cross_entity_state_dependency/reload_blocked_when_card_risk_frozen
    """
    program, card = setup_frozen_card(settled_cents=5000)
    res = api.reload_card(card["id"], reload_card_payload(1000), _STORE)
    validate_error(res, "ERR_CARD_RISK_FROZEN", expected_status=409)
