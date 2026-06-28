"""Retailer license lifecycle, terminal cross-entity guard, and revoke/suspend cascades.

Covers difficulty non_linear_state_machine (license revert cycle), transitive_cascade
(revoke chain), cross_entity_state_dependency (terminal activate requires retailer
active), plus several state-machine / cross-cutting corner instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_retailer, create_active_retailer, create_provisioned_terminal,
    create_active_terminal, setup_active_retailer_with_terminal,
    create_game, sell_ticket, set_clock, ApiErrorId, TEST_USERS,
)

LIC = TEST_USERS["licensing_admin_headers"]
OP = TEST_USERS["terminal_operator_headers"]
OFF = TEST_USERS["lottery_officer_headers"]


class TestLicenseRevertCycle:
    def test_reactivate_after_suspend_returns_active(self, api):
        """PRD 3.2: "A `SUSPENDED` license may be reactivated, transitioning
        `license_status` `SUSPENDED → ACTIVE` — the revert cycle"

        Design: Difficulty/non_linear_state_machine/retailer_license_revert_cycle_active_suspended_active
        """
        ret, term = setup_active_retailer_with_terminal()
        validate_success(api.suspend_license(ret["id"], LIC))
        data = validate_success(api.activate_license(ret["id"], LIC))
        assert data["license_status"] == "ACTIVE", data["license_status"]

    def test_reactivate_does_not_restore_cascaded_terminal(self, api):
        """PRD 3.2: "reactivation does **not** automatically restore the terminals that
        were deactivated during suspension; each such terminal must be activated again
        explicitly."

        Design: Difficulty/non_linear_state_machine/retailer_license_revert_cycle_active_suspended_active
        """
        ret, term = setup_active_retailer_with_terminal()
        validate_success(api.suspend_license(ret["id"], LIC))
        validate_success(api.activate_license(ret["id"], LIC))
        t = validate_success(api.get_terminal(term["id"], LIC))
        assert t["status"] == "DEACTIVATED", t["status"]


class TestRevokeCascadeChain:
    def test_revoke_deactivates_terminal_then_sale_blocked(self, api):
        """PRD 3.2: "a `SUSPENDED` license may be revoked, transitioning `license_status`
        `SUSPENDED → REVOKED`, which is terminal; revocation cascades to deactivate every
        terminal of that retailer whose `status` is either `PROVISIONED` or `ACTIVE`."
        PRD 3.4: "a sale through a terminal that is not active is rejected with
        `ERR_TERMINAL_NOT_ACTIVE`"

        Design: Difficulty/transitive_cascade/revoke_chain_retailer_terminal_then_sale_blocked
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal()
        validate_success(api.suspend_license(ret["id"], LIC))
        rdata = validate_success(api.revoke_license(ret["id"], LIC))
        assert rdata["license_status"] == "REVOKED"
        t = validate_success(api.get_terminal(term["id"], LIC))
        assert t["status"] == "DEACTIVATED"
        resp = api.create_ticket(
            {"game_id": game["id"], "terminal_id": term["id"], "serial": "RV-1",
             "price_cents": 200, "draw_date": "2026-01-10T00:00:00Z",
             "declared_tier": 0, "gross_prize_cents": 0}, OP)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_NOT_ACTIVE.value)

    def test_revoke_deactivates_both_provisioned_and_active_terminals(self, api):
        """PRD 3.2: "revocation cascades to deactivate every terminal of that retailer
        whose `status` is either `PROVISIONED` or `ACTIVE`."

        Design: Difficulty/transitive_cascade/revoke_chain_retailer_terminal_then_sale_blocked
        """
        ret = create_active_retailer()
        t_active = create_active_terminal(ret["id"])
        t_prov = create_provisioned_terminal(ret["id"])
        validate_success(api.suspend_license(ret["id"], LIC))
        rdata = validate_success(api.revoke_license(ret["id"], LIC))
        assert rdata["license_status"] == "REVOKED"
        assert validate_success(api.get_terminal(t_active["id"], LIC))["status"] == "DEACTIVATED"
        assert validate_success(api.get_terminal(t_prov["id"], LIC))["status"] == "DEACTIVATED"


class TestTerminalCrossEntityGuard:
    def test_activate_terminal_requires_retailer_active(self, api):
        """PRD 3.3: "Activating a terminal transitions its `status`
        `PROVISIONED → ACTIVE`, but only when the owning retailer's `license_status` is
        `ACTIVE`; if the retailer is not currently licensed, the activation is rejected
        with `ERR_RETAILER_NOT_LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/terminal_activate_requires_retailer_active
        """
        ret = create_retailer()  # PENDING, never activated
        term = create_provisioned_terminal(ret["id"])
        resp = api.activate_terminal(term["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_RETAILER_NOT_LICENSED.value)
        t = validate_success(api.get_terminal(term["id"], LIC))
        assert t["status"] == "PROVISIONED", t["status"]

    def test_activate_terminal_on_active_retailer_succeeds(self, api):
        """PRD 3.3: "Activating a terminal transitions its `status`
        `PROVISIONED → ACTIVE`, but only when the owning retailer's `license_status` is
        `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/terminal_activate_requires_retailer_active
        """
        ret = create_active_retailer()
        term = create_provisioned_terminal(ret["id"])
        data = validate_success(api.activate_terminal(term["id"], LIC))
        assert data["status"] == "ACTIVE", data["status"]


class TestLicenseStateMachineCorners:
    def test_suspend_pending_retailer_invalid_state(self, api):
        """PRD 3.2: "Activation, suspension, and revocation are each permitted only from
        the stated originating `license_status`; an attempt from any other state is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/suspend_pending_retailer_returns_invalid_state
        """
        ret = create_retailer()  # PENDING
        resp = api.suspend_license(ret["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert validate_success(api.get_retailer(ret["id"], LIC))["license_status"] == "PENDING"

    def test_revoke_active_retailer_invalid_state(self, api):
        """PRD 3.2: "a `SUSPENDED` license may be revoked, transitioning `license_status`
        `SUSPENDED → REVOKED`, which is terminal; revocation cascades to deactivate every
        terminal of that retailer whose `status` is either `PROVISIONED` or `ACTIVE`."
        PRD 3.2: "an attempt from any other state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/revoke_active_retailer_directly_returns_invalid_state
        """
        ret = create_active_retailer()
        resp = api.revoke_license(ret["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_revoked_retailer_terminal_no_reactivation(self, api):
        """PRD 3.2: "a `SUSPENDED` license may be revoked, transitioning `license_status`
        `SUSPENDED → REVOKED`, which is terminal; revocation cascades to deactivate every
        terminal of that retailer whose `status` is either `PROVISIONED` or `ACTIVE`."
        PRD 3.2: "an attempt from any other state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/revoked_retailer_is_terminal_no_reactivation
        """
        ret = create_active_retailer()
        validate_success(api.suspend_license(ret["id"], LIC))
        validate_success(api.revoke_license(ret["id"], LIC))
        resp = api.activate_license(ret["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert validate_success(api.get_retailer(ret["id"], LIC))["license_status"] == "REVOKED"

    def test_new_retailer_starts_pending(self, api):
        """PRD 3.2: "A new retailer begins with `license_status` `PENDING`."

        Design: Corner/state_machines/new_retailer_initial_state_pending
        """
        ret = create_retailer()
        assert ret["license_status"] == "PENDING", ret["license_status"]

    def test_suspend_cascade_only_deactivates_active_terminals(self, api):
        """PRD 3.2: "every terminal owned by that retailer whose `status` is `ACTIVE` is
        transitioned `ACTIVE → DEACTIVATED`, while terminals still in `PROVISIONED` and
        terminals already `DEACTIVATED` are left untouched."

        Design: Corner/state_machines/suspend_cascade_only_deactivates_active_terminals
        """
        ret = create_active_retailer()
        t_active = create_active_terminal(ret["id"])
        t_prov = create_provisioned_terminal(ret["id"])
        data = validate_success(api.suspend_license(ret["id"], LIC))
        assert data["license_status"] == "SUSPENDED"
        assert validate_success(api.get_terminal(t_active["id"], LIC))["status"] == "DEACTIVATED"
        assert validate_success(api.get_terminal(t_prov["id"], LIC))["status"] == "PROVISIONED"

    def test_revoke_cascade_multi_target_end_to_end(self, api):
        """PRD 3.2: "revocation cascades to deactivate every terminal of that retailer
        whose `status` is either `PROVISIONED` or `ACTIVE`."

        Design: Corner/cross_cutting_complexity_layers/revoke_cascade_n_level_end_to_end
        """
        ret = create_active_retailer()
        tA = create_active_terminal(ret["id"])
        tB = create_provisioned_terminal(ret["id"])
        validate_success(api.suspend_license(ret["id"], LIC))
        data = validate_success(api.revoke_license(ret["id"], LIC))
        assert data["license_status"] == "REVOKED"
        assert validate_success(api.get_terminal(tA["id"], LIC))["status"] == "DEACTIVATED"
        assert validate_success(api.get_terminal(tB["id"], LIC))["status"] == "DEACTIVATED"
