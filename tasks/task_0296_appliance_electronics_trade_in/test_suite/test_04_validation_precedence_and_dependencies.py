"""Validation precedence (state vs business checks) and cross-entity state
dependencies (device-model retirement, data-wipe gate).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_catalog_model_customer,
    create_draft_trade_in,
    create_quoted_trade_in,
    create_received_trade_in,
    inspect,
    set_clock,
    api_client,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / state_beats_datawipe_on_payout
# ─────────────────────────────────────────────────────────────────────────────

def test_state_check_beats_datawipe_on_payout(api):
    """PRD §2.4: "State legality — the target `TradeIn`, `Quote`, or `Payout` is in a
    state from which the requested transition is legal, otherwise `ERR_INVALID_STATE`."
    PRD §2.4: "the remaining business checks (model retirement, promotion validity,
    defect membership, quote expiry, data-wipe presence, window and slot overlaps,
    uniqueness, and multiplier validity) fire after the structural checks above".

    A payout attempted on a still-RECEIVED (not ACCEPTED) wipe-required trade-in that
    also lacks a data-wipe cert fails the higher-priority state check first:
    ERR_INVALID_STATE, not ERR_DATA_WIPE_REQUIRED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_datawipe_on_payout
    """
    _cat, model, customer = setup_catalog_model_customer(
        catalog_overrides={"data_wipe_required_categories": ["SMARTPHONE"]}
    )
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")

    resp = api.create_payout(ti["id"], {"method": "ACH"}, FINANCE)
    validate_error(resp, "ERR_INVALID_STATE")
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "RECEIVED"


def test_state_check_beats_datawipe_no_payout_created(api):
    """PRD §3.7: "A `FinanceOperator` settles an `ACCEPTED` trade-in by issuing a
    **payout**, advancing the trade-in from `ACCEPTED` to the terminal `PAID` state."
    PRD §2.4: "the remaining business checks (model retirement, promotion validity,
    defect membership, quote expiry, data-wipe presence, window and slot overlaps,
    uniqueness, and multiplier validity) fire after the structural checks above".

    Because the state check fires first on a still-RECEIVED wipe-required trade-in, no
    payout is created at all (the data-wipe gate is never reached).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_datawipe_on_payout
    """
    _cat, model, customer = setup_catalog_model_customer(
        catalog_overrides={"data_wipe_required_categories": ["SMARTPHONE"]}
    )
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")

    resp = api.create_payout(ti["id"], {"method": "ACH"}, FINANCE)
    validate_error(resp, "ERR_INVALID_STATE")
    listed, meta = validate_paginated(api.list_payouts(ti["id"], FINANCE))
    assert meta["total_count"] == 0, "no payout should exist after the state check rejects"


def test_quote_expired_decides_shipkit_when_state_legal(api):
    """PRD §3.5: "This is permitted only while the locked quote has not expired — its
    `lock_expires_at` must be later than the current logical time — otherwise the
    request is refused with `ERR_QUOTE_EXPIRED` (HTTP 409)."

    Ship-kit on a QUOTED trade-in (state precondition satisfied) whose locked quote
    has expired is refused with ERR_QUOTE_EXPIRED, and the trade-in stays QUOTED.

    Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_invalid_state_on_shipkit
    """
    _cat, model, customer = setup_catalog_model_customer()
    set_clock("2026-06-01T00:00:00Z")
    ti = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    set_clock("2026-06-30T00:00:00Z")

    resp = api.ship_kit(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_QUOTE_EXPIRED")
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "QUOTED"


def test_ship_kit_succeeds_before_quote_expiry(api):
    """PRD §3.5: "Once a trade-in is `QUOTED`, the owning `Customer` requests a
    **shipping kit**, advancing the trade-in from `QUOTED` to `KIT_SENT`. This is
    permitted only while the locked quote has not expired — its `lock_expires_at` must
    be later than the current logical time".

    The mirror of the expiry case: ship-kit on the same QUOTED trade-in while the lock
    is still live succeeds, advancing the trade-in to KIT_SENT — confirming the temporal
    check is what flips the outcome, not the state.

    Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_invalid_state_on_shipkit
    """
    _cat, model, customer = setup_catalog_model_customer()
    set_clock("2026-06-01T00:00:00Z")
    ti = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    # Still well within the 168h price-lock window.
    shipped = validate_success(api.ship_kit(ti["id"], make_customer_headers(customer["id"])))
    assert shipped["status"] == "KIT_SENT"


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / quote_requires_devicemodel_active
# ─────────────────────────────────────────────────────────────────────────────

def test_quote_rejected_when_model_retired(api):
    """PRD §3.4: "the referenced device model's `status` must be `ACTIVE`, otherwise
    the quote is refused with `ERR_MODEL_RETIRED` (HTTP 409)".

    A DRAFT trade-in whose device model is retired before /quote is refused with
    ERR_MODEL_RETIRED and stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/quote_requires_devicemodel_active
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_draft_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=True)
    validate_success(api.retire_device_model(model["id"], ADMIN))

    resp = api.quote_trade_in(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_MODEL_RETIRED")
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "DRAFT"


def test_quote_succeeds_while_model_active(api):
    """PRD §3.4: "Before pricing, three preconditions are checked: the referenced
    device model's `status` must be `ACTIVE`, otherwise the quote is refused with
    `ERR_MODEL_RETIRED` (HTTP 409)".
    PRD §3.4: "A `Customer` who owns a `DRAFT` trade-in asks the system to **quote** it,
    advancing it from `DRAFT` to `QUOTED`."

    The same DRAFT trade-in quotes successfully (DRAFT -> QUOTED) while its device model
    is still ACTIVE — the model-status dependency is what gates the transition.

    Design: Difficulty/cross_entity_state_dependency/quote_requires_devicemodel_active
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_draft_trade_in(customer, model, declared_grade="GOOD", declared_defects=[], declared_powers_on=True)

    quoted = validate_success(api.quote_trade_in(ti["id"], make_customer_headers(customer["id"])))
    assert quoted["status"] == "QUOTED"


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / payout_requires_datawipe_certificate
# ─────────────────────────────────────────────────────────────────────────────

def test_payout_blocked_without_passing_datawipe(api):
    """PRD §3.7: "if the device model's `category` is among the catalog's
    `data_wipe_required_categories`, a `DataWipeCertificate` with `result` of `PASS`
    must already exist for this trade-in, otherwise the payout is refused with
    `ERR_DATA_WIPE_REQUIRED` (HTTP 409)."

    An ACCEPTED wipe-required trade-in with no PASS certificate cannot be paid out;
    the payout is refused with ERR_DATA_WIPE_REQUIRED and the trade-in stays ACCEPTED.

    Design: Difficulty/cross_entity_state_dependency/payout_requires_datawipe_certificate
    """
    _cat, model, customer = setup_catalog_model_customer(
        catalog_overrides={"data_wipe_required_categories": ["SMARTPHONE"]}
    )
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])

    resp = api.create_payout(ti["id"], {"method": "ACH"}, FINANCE)
    validate_error(resp, "ERR_DATA_WIPE_REQUIRED")
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "ACCEPTED"


def test_payout_succeeds_after_passing_datawipe(api):
    """PRD §3.7: "if the device model's `category` is among the catalog's
    `data_wipe_required_categories`, a `DataWipeCertificate` with `result` of `PASS`
    must already exist for this trade-in, otherwise the payout is refused with
    `ERR_DATA_WIPE_REQUIRED` (HTTP 409)."
    PRD §3.7: "advancing the trade-in from `ACCEPTED` to the terminal `PAID` state."

    Once a PASS data-wipe certificate exists for the same wipe-required ACCEPTED
    trade-in, the payout is allowed and the trade-in reaches PAID — proving the gate
    is the certificate's existence/state.

    Design: Difficulty/cross_entity_state_dependency/payout_requires_datawipe_certificate
    """
    _cat, model, customer = setup_catalog_model_customer(
        catalog_overrides={"data_wipe_required_categories": ["SMARTPHONE"]}
    )
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    validate_success(api.create_data_wipe(ti["id"], {"method": "NIST_PURGE", "result": "PASS"}, AGENT), expected_status=201)

    validate_success(api.create_payout(ti["id"], {"method": "ACH"}, FINANCE), expected_status=201)
    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "PAID"
