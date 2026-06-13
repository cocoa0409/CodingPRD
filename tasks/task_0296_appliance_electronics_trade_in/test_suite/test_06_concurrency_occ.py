"""Optimistic concurrency control on the customer re-quote decisions, and the
version-increment contract.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    setup_catalog_model_customer,
    create_draft_trade_in,
    create_received_trade_in,
    setup_requoted_trade_in,
    inspect,
    api_client,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# cross_cutting / occ_accept_requote_stale_version_conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_accept_requote_stale_version_rejected(api):
    """PRD §2.7: "Accepting a re-quote requires the request to carry
    `expected_trade_in_version`, and that value must equal the target `TradeIn`'s
    current `version`. If a grading agent has revised the findings since the customer
    last read the trade-in — which legitimately supersedes the prior re-quote, mints a
    new one, and advances `version` — then the customer's `expected_trade_in_version`
    no longer matches, and the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Client captures version V at REQUOTED; a /reinspect bumps it to V+1 while the
    trade-in stays REQUOTED; an accept carrying V is rejected ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_accept_requote_stale_version_conflict
    """
    _cat, model, customer = setup_catalog_model_customer()
    inspected, stale_version = setup_requoted_trade_in(customer, model)
    ch = make_customer_headers(customer["id"])

    # Grading agent re-inspects (POOR+BATTERY_DEGRADED+MISSING_PARTS -> 12000, a fresh
    # downgrade below the 16000 REQUOTE quote's tolerance band), bumping version.
    validate_success(api.reinspect_trade_in(
        inspected["id"], {"verified_grade": "POOR", "verified_defects": ["BATTERY_DEGRADED", "MISSING_PARTS"], "verified_powers_on": True}, AGENT
    ))

    resp = api.accept_requote(inspected["id"], {"expected_trade_in_version": stale_version}, ch)
    validate_error(resp, "ERR_STALE_VERSION")
    refreshed = validate_success(api.get_trade_in(inspected["id"], ADMIN))
    assert refreshed["status"] == "REQUOTED"


# ─────────────────────────────────────────────────────────────────────────────
# cross_cutting / occ_decline_requote_correct_version_succeeds
# ─────────────────────────────────────────────────────────────────────────────

def test_decline_requote_with_current_version_succeeds(api):
    """PRD §2.7: "Declining a re-quote is guarded identically: the decline request must
    carry `expected_trade_in_version` matching the trade-in's current `version`, and a
    stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "**declines** it, advancing from `REQUOTED` to the terminal `REJECTED` state."

    A decline carrying the version read straight from the inspect response (current,
    not stale) passes the OCC check and drives the trade-in to REJECTED.

    Design: Corner/cross_cutting_complexity_layers/occ_decline_requote_correct_version_succeeds
    """
    _cat, model, customer = setup_catalog_model_customer()
    inspected, current_version = setup_requoted_trade_in(customer, model)
    ch = make_customer_headers(customer["id"])

    validate_success(api.decline_requote(inspected["id"], {"expected_trade_in_version": current_version}, ch))
    refreshed = validate_success(api.get_trade_in(inspected["id"], ADMIN))
    assert refreshed["status"] == "REJECTED"


# ─────────────────────────────────────────────────────────────────────────────
# cross_cutting / version_increments_on_each_mutation
# ─────────────────────────────────────────────────────────────────────────────

def test_version_starts_at_one_and_increments_on_quote(api):
    """PRD §2.6: "a `version` (an integer that starts at its initial value and
    increments by one on every mutation)."
    PRD §3.3: "The new trade-in is created in `DRAFT` status ... and a `version` that
    the lifecycle's later steps will advance."

    A freshly created trade-in has version 1; the /quote mutation advances it to 2.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_draft_trade_in(customer, model, declared_grade="GOOD")
    assert ti["version"] == 1, f"freshly created trade-in version should be 1, got {ti['version']}"

    quoted = validate_success(api.quote_trade_in(ti["id"], make_customer_headers(customer["id"])))
    assert quoted["version"] == 2, f"after /quote version should be 2, got {quoted['version']}"
