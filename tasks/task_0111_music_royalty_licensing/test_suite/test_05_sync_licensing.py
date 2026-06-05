"""Sync licensing negotiation loop and acceptance gating (PRD §3.4).

Covers the cyclic DRAFT->COUNTERED->DRAFT requote loop, the rights-window
precondition on acceptance, and terminal-state lockdown after a decline.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_licensee_headers,
    setup_draft_sync_license,
    setup_sync_catalog,
    create_sync_license,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Difficulty queue A — non_linear_state_machine (sync negotiation cycle)
# =============================================================================

class TestSyncNegotiationCycle:
    def test_counter_moves_draft_to_countered(self, api):
        """PRD §3.4: "From DRAFT, the owning Licensee may counter the quote by supplying
        a counter_fee_cents of at least 1, which is recorded on the license and moves it
        from DRAFT to COUNTERED; the version increments."

        Design: Difficulty/non_linear_state_machine/sync_license_negotiation_cycle
        """
        ctx = setup_draft_sync_license()
        sl = ctx["sync_license"]
        licensee_headers = make_licensee_headers(ctx["licensee"]["id"])
        countered = validate_success(
            api.counter_sync_license(sl["id"], {"counter_fee_cents": 150000}, licensee_headers)
        )
        assert countered["status"] == "COUNTERED"
        assert countered["counter_fee_cents"] == 150000

    def test_requote_returns_countered_to_draft_with_recomputed_quote(self, api):
        """PRD §3.4: "From COUNTERED, a RoyaltyOperator may requote by supplying a fresh
        base_fee_cents, which resets the base fee, recomputes quoted_fee_cents through the
        same sync pricing rule, and returns the license from COUNTERED to DRAFT,
        incrementing the version — this is the negotiation loop."

        Design: Difficulty/non_linear_state_machine/sync_license_negotiation_cycle
        """
        ctx = setup_draft_sync_license(media_type="FILM", territory="US", term_months=24, base_fee_cents=100000)
        sl = ctx["sync_license"]
        licensee_headers = make_licensee_headers(ctx["licensee"]["id"])
        validate_success(api.counter_sync_license(sl["id"], {"counter_fee_cents": 150000}, licensee_headers))

        requoted = validate_success(api.requote_sync_license(sl["id"], {"base_fee_cents": 50000}, OPERATOR))
        assert requoted["status"] == "DRAFT", "COUNTERED -> DRAFT closes the negotiation loop"
        # base 50000 FILM (2.0) -> sub 100000 (<500000 -> 1.2); 24mo (>=12 -> 1.3)
        # 100000 * 1.2 * 1.3 = 156000
        assert requoted["quoted_fee_cents"] == 156000, (
            f"recomputed: 50000*2.0 -> 100000 -> *1.2 -> *1.3 = 156000, got {requoted['quoted_fee_cents']}"
        )


# =============================================================================
# Difficulty queue A — cross_entity_state_dependency (accept requires window)
# =============================================================================

class TestAcceptRequiresActiveRightsWindow:
    def test_accept_blocked_after_window_revoked(self, api):
        """PRD §3.4: "The owning Licensee may accept a license that is in DRAFT; this
        requires DRAFT status (else ERR_INVALID_STATE), licensee ownership (else
        ERR_NOT_RESOURCE_OWNER), and an ACTIVE SYNC rights window on the recording whose
        territory covers the license's territory (else ERR_RIGHTS_NOT_AVAILABLE)."

        Design: Difficulty/cross_entity_state_dependency/sync_accept_requires_active_rights_window
        """
        ctx = setup_draft_sync_license(media_type="FILM", territory="US", term_months=12,
                                       base_fee_cents=100000, grant_sync_window=True)
        # Revoke the sole covering SYNC window.
        validate_success(api.revoke_rights_window(ctx["window"]["id"], ADMIN))
        licensee_headers = make_licensee_headers(ctx["licensee"]["id"])
        resp = api.accept_sync_license(ctx["sync_license"]["id"], licensee_headers)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_AVAILABLE)

    def test_accept_succeeds_with_active_window(self, api):
        """PRD §3.4: "It moves the license from DRAFT to ACCEPTED and increments the
        version."

        Design: Difficulty/cross_entity_state_dependency/sync_accept_requires_active_rights_window
        """
        ctx = setup_draft_sync_license(media_type="FILM", territory="US", term_months=12,
                                       base_fee_cents=100000, grant_sync_window=True)
        licensee_headers = make_licensee_headers(ctx["licensee"]["id"])
        accepted = validate_success(api.accept_sync_license(ctx["sync_license"]["id"], licensee_headers))
        assert accepted["status"] == "ACCEPTED"


# =============================================================================
# Corner queue B — state_machines (terminal-state lockdown)
# =============================================================================

class TestSyncTerminalState:
    def test_accept_after_decline_rejected(self, api):
        """PRD §3.4: "A RoyaltyOperator may decline a license that is in either DRAFT or
        COUNTERED status, moving it to DECLINED (a terminal state) and incrementing the
        version; a decline from any other state is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/sync_decline_then_accept_invalid_state
        """
        ctx = setup_sync_catalog()
        sl = create_sync_license(ctx["recording"]["id"], ctx["licensee"]["id"],
                                 media_type="TV", territory="US", term_months=12, base_fee_cents=50000)
        validate_success(api.decline_sync_license(sl["id"], OPERATOR))
        licensee_headers = make_licensee_headers(ctx["licensee"]["id"])
        resp = api.accept_sync_license(sl["id"], licensee_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
