"""Transitive cascades and scheduled state propagation.

Queue A: the depth-3 LOA-revocation chain and the supplier-suspension chain.
Queue B: scheduled LOA expiry suspending its account.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


# ===========================================================================
# Difficulty: transitive_cascade / loa_revoke_suspends_account_cancels_rfp_voids_quote
# ===========================================================================

def _open_rfp_with_submitted_quote(api):
    ctx = fx.setup_verified_account(api)
    ctx["supplier"] = fx.new_supplier(api)
    rfp = get_success_data(api.create_rfp(
        fac.create_rfp_payload(ctx["account"]["id"], ctx["agent"]["id"]), ctx["agent_headers"]))
    get_success_data(api.transition_rfp(rfp["id"], {"action": "OPEN"}, ctx["agent_headers"]))
    v = fx.rfp_version(api, rfp["id"], ctx["agent_headers"])
    quote = get_success_data(api.create_quote(
        fac.create_quote_payload(rfp["id"], ctx["supplier"]["id"], v),
        fx.make_supplier_headers(ctx["supplier"]["id"])))
    ctx["rfp"], ctx["quote"] = rfp, quote
    return ctx


def test_loa_revoke_cascades_suspend_cancel_void(api):
    """PRD §3.1: "the referenced account transitions to SUSPENDED (unless it is
    already in a terminal state), and that account suspension in turn cancels every
    one of the account's RFPs still in DRAFT, OPEN, or BEST_AND_FINAL (moving each
    to CANCELLED), and each such cancellation voids that RFP's quotes still in
    SUBMITTED or SHORTLISTED (moving each to VOID)."

    Design: Difficulty/transitive_cascade/loa_revoke_suspends_account_cancels_rfp_voids_quote
    """
    ctx = _open_rfp_with_submitted_quote(api)
    loa = get_success_data(api.revoke_authorization(ctx["loa"]["id"], ctx["customer_headers"]))
    assert loa["status"] == "REVOKED"
    assert get_success_data(api.get_account(ctx["account"]["id"], ctx["agent_headers"]))["status"] == "SUSPENDED"
    assert get_success_data(api.get_rfp(ctx["rfp"]["id"], ctx["agent_headers"]))["status"] == "CANCELLED"
    assert get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))["status"] == "VOID"


def test_loa_revoke_bumps_cascaded_account_version(api):
    """PRD §2.8: "Several operations trigger cascades that mutate more than one
    entity in a single request; each such secondary mutation refreshes the affected
    resource's updated_at and bumps its version."

    Design: Difficulty/transitive_cascade/loa_revoke_suspends_account_cancels_rfp_voids_quote
    """
    ctx = _open_rfp_with_submitted_quote(api)
    before = get_success_data(api.get_account(ctx["account"]["id"], ctx["agent_headers"]))["version"]
    get_success_data(api.revoke_authorization(ctx["loa"]["id"], ctx["customer_headers"]))
    after = get_success_data(api.get_account(ctx["account"]["id"], ctx["agent_headers"]))
    assert after["status"] == "SUSPENDED"
    assert after["version"] > before, "cascaded account suspension must bump version"


# ===========================================================================
# Difficulty: transitive_cascade / supplier_suspend_withdraws_quote_reverts_rfp
# ===========================================================================

def _best_and_final_rfp_with_shortlisted_quote(api):
    ctx = fx.setup_open_rfp_with_shortlisted_quote(api)
    get_success_data(api.transition_rfp(ctx["rfp"]["id"], {"action": "BEST_AND_FINAL"}, ctx["agent_headers"]))
    return ctx


def test_supplier_suspend_withdraws_its_shortlisted_quote(api):
    """PRD §3.6: "Suspension cascades: every quote from that supplier still in
    SUBMITTED or SHORTLISTED is withdrawn, and — as noted in §3.2 — any shortlisted
    quote so withdrawn from a best-and-final RFP reverts that RFP to OPEN."

    Design: Difficulty/transitive_cascade/supplier_suspend_withdraws_quote_reverts_rfp
    """
    ctx = _best_and_final_rfp_with_shortlisted_quote(api)
    supplier = get_success_data(api.set_supplier_status(
        ctx["supplier"]["id"], {"status": "SUSPENDED"}, ctx["ops_headers"]))
    assert supplier["status"] == "SUSPENDED"
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "WITHDRAWN"


def test_supplier_suspend_reverts_best_and_final_rfp_to_open(api):
    """PRD §3.2: "if that shortlisted quote was the anchor of a BEST_AND_FINAL RFP,
    its departure reverts that RFP BEST_AND_FINAL → OPEN so the round can be
    rebuilt. This same shortlisted-withdrawal reversion fires when a quote is
    withdrawn by the supplier-suspension cascade".

    Design: Difficulty/transitive_cascade/supplier_suspend_withdraws_quote_reverts_rfp
    """
    ctx = _best_and_final_rfp_with_shortlisted_quote(api)
    get_success_data(api.set_supplier_status(ctx["supplier"]["id"], {"status": "SUSPENDED"}, ctx["ops_headers"]))
    quote = get_success_data(api.get_quote(ctx["quote"]["id"], ctx["agent_headers"]))
    rfp = get_success_data(api.get_rfp(ctx["rfp"]["id"], ctx["agent_headers"]))
    assert quote["status"] == "WITHDRAWN"
    assert rfp["status"] == "OPEN", f"best-and-final RFP should revert to OPEN, got {rfp['status']}"


# ===========================================================================
# Corner: scheduled LOA expiry
# ===========================================================================

def test_scheduled_loa_expiry_suspends_account(api):
    """PRD §3.7: "It expires every SIGNED LOA whose expires_at the clock has
    reached or passed, moving each SIGNED → EXPIRED; if such an expiry leaves an
    account that was VERIFIED or ENROLLED with no remaining SIGNED LOA, that
    account is suspended through the same cascade described in §3.1".

    Design: Corner/cross_cutting_complexity_layers/scheduled_loa_expiry_suspends_account
    """
    ctx = fx.setup_verified_account(api, loa_expires="2026-05-05T00:00:00Z")
    fx.set_clock(api, "2026-05-10T00:00:00Z")
    get_success_data(api.run_scheduled(ctx["ops_headers"]))
    loa = get_success_data(api.get_authorization(ctx["loa"]["id"], ctx["agent_headers"]))
    account = get_success_data(api.get_account(ctx["account"]["id"], ctx["agent_headers"]))
    assert loa["status"] == "EXPIRED"
    assert account["status"] == "SUSPENDED"
