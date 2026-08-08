"""RFP solicitation, the bidding cycle, quote submission, and OCC.

Queue A (difficulty): the RFP BEST_AND_FINAL↔OPEN cycle, the account-verified
cross-entity gate on opening, and the temporal-beats-fiscal precedence pair.
Queue B (corner): stale-version OCC, no-quotes and LOA-scope preconditions.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_agent_headers,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


# ===========================================================================
# Difficulty: non_linear_state_machine / rfp_cycle_best_and_final_then_reopen
# ===========================================================================

def _rfp_at_best_and_final(api):
    ctx = fx.setup_open_rfp_with_shortlisted_quote(api)
    get_success_data(api.transition_rfp(ctx["rfp"]["id"], {"action": "BEST_AND_FINAL"}, ctx["agent_headers"]))
    return ctx


def test_rfp_reopen_returns_to_open_state(api):
    """PRD §3.2: "The RFP may then cycle back the other way, BEST_AND_FINAL → OPEN,
    to invite yet another round — a re-open that again bumps version."

    Design: Difficulty/non_linear_state_machine/rfp_cycle_best_and_final_then_reopen
    """
    ctx = _rfp_at_best_and_final(api)
    reopened = get_success_data(api.transition_rfp(ctx["rfp"]["id"], {"action": "REOPEN"}, ctx["agent_headers"]))
    assert reopened["status"] == "OPEN", f"expected OPEN after REOPEN, got {reopened['status']}"


def test_rfp_reopen_keeps_shortlisted_quote(api):
    """PRD §3.2: "The RFP may then cycle back the other way, BEST_AND_FINAL → OPEN,
    to invite yet another round — a re-open that again bumps version."

    Design: Difficulty/non_linear_state_machine/rfp_cycle_best_and_final_then_reopen
    """
    ctx = _rfp_at_best_and_final(api)
    get_success_data(api.transition_rfp(ctx["rfp"]["id"], {"action": "REOPEN"}, ctx["agent_headers"]))
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "SHORTLISTED", f"quote should survive the cycle, got {quote['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / rfp_open_requires_account_verified
# ===========================================================================

def _unverified_account_with_signed_loa(api):
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    loa = fx.draft_loa(api, account["id"], agent["id"], scope="USAGE_AND_ENROLL")
    fx.sign_loa(api, loa["id"], customer["id"])
    fx.add_usage(api, account["id"], agent["id"], "2025-12", 5000, is_actual=False)
    return agent, customer, account


def test_rfp_open_rejected_when_account_not_verified(api):
    """PRD §3.2: "Opening the RFP for bidding (action OPEN) advances it
    DRAFT → OPEN, but only once the account is ready: the referenced account
    must be VERIFIED (else ERR_ACCOUNT_NOT_VERIFIED)".

    Design: Difficulty/cross_entity_state_dependency/rfp_open_requires_account_verified
    """
    agent, customer, account = _unverified_account_with_signed_loa(api)
    hdr = make_agent_headers(agent["id"])
    rfp = get_success_data(api.create_rfp(fac.create_rfp_payload(account["id"], agent["id"]), hdr))

    resp = api.transition_rfp(rfp["id"], {"action": "OPEN"}, hdr)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_VERIFIED.value)
    after = get_success_data(api.get_rfp(rfp["id"], hdr))
    assert after["status"] == "DRAFT"


def test_rfp_open_succeeds_once_account_verified(api):
    """PRD §3.2: "Opening the RFP for bidding (action OPEN) advances it
    DRAFT → OPEN, but only once the account is ready: the referenced account
    must be VERIFIED (else ERR_ACCOUNT_NOT_VERIFIED)".

    Design: Difficulty/cross_entity_state_dependency/rfp_open_requires_account_verified
    """
    ctx = fx.setup_verified_account(api)  # account VERIFIED, USAGE_AND_ENROLL LOA
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))
    opened = get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    assert opened["status"] == "OPEN"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / quote_temporal_beats_margin_fiscal
# ===========================================================================

def _open_rfp_past_due(api, adder_ok=True):
    ctx = fx.setup_verified_account(api)
    ctx["supplier"] = fx.new_supplier(api)
    ctx["supplier_headers"] = fx.make_supplier_headers(ctx["supplier"]["id"])
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"], due_at="2026-05-10T00:00:00Z"),
        ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    fx.set_clock(api, "2026-05-15T00:00:00Z")  # past due_at
    ctx["rfp"] = rfp
    ctx["version"] = fx.rfp_version(api, rfp["id"], ctx["agent_headers"])
    return ctx


def test_quote_after_due_with_low_margin_reports_rfp_closed(api):
    """PRD §3.2: "A quote submitted at or after the RFP's due_at is rejected with
    ERR_RFP_CLOSED."
    PRD §2.6: "Temporal windows." at priority 10 precede "Fiscal floors and
    ceilings." at priority 11, and "the first failing check determines the error
    returned."

    Design: Difficulty/priority_pair_validation_conflict/quote_temporal_beats_margin_fiscal
    """
    ctx = _open_rfp_past_due(api)
    payload = fac.create_quote_payload(ctx["rfp"]["id"], ctx["supplier"]["id"], ctx["version"],
                                       broker_adder_mills=1)  # also below the 2-mill floor
    resp = api.create_quote(payload, ctx["supplier_headers"])
    validate_error(resp, ApiErrorId.ERR_RFP_CLOSED.value)


def test_quote_after_due_with_valid_margin_reports_rfp_closed(api):
    """PRD §3.2: "A quote submitted at or after the RFP's due_at is rejected with
    ERR_RFP_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/quote_temporal_beats_margin_fiscal
    """
    ctx = _open_rfp_past_due(api)
    payload = fac.create_quote_payload(ctx["rfp"]["id"], ctx["supplier"]["id"], ctx["version"],
                                       broker_adder_mills=5)  # margin OK; only temporal fails
    resp = api.create_quote(payload, ctx["supplier_headers"])
    validate_error(resp, ApiErrorId.ERR_RFP_CLOSED.value)


# ===========================================================================
# Corner: optimistic concurrency + solicitation preconditions
# ===========================================================================

def test_stale_rfp_version_on_second_quote_submit(api):
    """PRD §2.7: "If that value does not equal the RFP's current version — because
    the round advanced, the RFP re-opened, or another supplier's quote arrived in
    the interim — the submission is rejected with ERR_STALE_RFP_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_rfp_version_on_quote_submit
    """
    ctx = fx.setup_verified_account(api)
    supplier = fx.new_supplier(api)
    sup_hdr = fx.make_supplier_headers(supplier["id"])
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    observed = fx.rfp_version(api, rfp["id"], sup_hdr)

    # First submit succeeds and bumps the version.
    get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], supplier["id"], observed, rate_mills_per_kwh=60, broker_adder_mills=5),
        sup_hdr))
    # Second submit still carries the now-stale observed version.
    resp = api.create_quote(
        fac.create_quote_payload(rfp["id"], supplier["id"], observed, rate_mills_per_kwh=59, broker_adder_mills=4),
        sup_hdr)
    validate_error(resp, ApiErrorId.ERR_STALE_RFP_VERSION.value, expected_status=412)


def test_best_and_final_with_no_quotes_rejected(api):
    """PRD §3.2: "moving the RFP OPEN → BEST_AND_FINAL demands a best-and-final
    round; this requires at least one quote already in SUBMITTED or SHORTLISTED
    (else ERR_NO_QUOTES) and bumps the RFP version".

    Design: Corner/state_machines/rfp_best_and_final_with_no_quotes
    """
    ctx = fx.setup_verified_account(api)
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))

    resp = api.transition_rfp(rfp["id"], {"action": "BEST_AND_FINAL"}, ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_QUOTES.value)
    after = get_success_data(api.get_rfp(rfp["id"], ctx["agent_headers"]))
    assert after["status"] == "OPEN"


def test_rfp_open_with_usage_only_loa_scope_insufficient(api):
    """PRD §3.2: "a SIGNED authorization whose scope is USAGE_AND_ENROLL must
    exist for the account (else ERR_LOA_SCOPE_INSUFFICIENT). A USAGE_ONLY LOA is
    insufficient to open a solicitation."

    Design: Corner/state_machines/rfp_open_loa_scope_usage_only_insufficient
    """
    ctx = fx.setup_verified_account(api, loa_scope="USAGE_ONLY")  # verified, but scope too narrow
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))

    resp = api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_LOA_SCOPE_INSUFFICIENT.value)
    after = get_success_data(api.get_rfp(rfp["id"], ctx["agent_headers"]))
    assert after["status"] == "DRAFT"
