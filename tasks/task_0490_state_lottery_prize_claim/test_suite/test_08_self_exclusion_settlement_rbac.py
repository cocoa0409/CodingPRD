"""Self-exclusion lifecycle, settlement segregation/priority/OCC, and RBAC denials.

Covers the calculations (self-exclusion), validations (segregation, priority,
reinstate-too-early), cross_cutting (OCC settlement create), and rbac corner sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, officer_headers,
    create_player, set_clock, create_settlement, fresh_retailer_version,
    create_settlement_payload, setup_window_with_sold_tickets, ApiErrorId,
    TEST_USERS,
)

LIC = TEST_USERS["licensing_admin_headers"]
OFF = TEST_USERS["lottery_officer_headers"]
CLERK = TEST_USERS["claims_clerk_headers"]
OP = TEST_USERS["terminal_operator_headers"]


class TestSelfExclusionLifecycle:
    def test_lapsed_exclusion_allows_reinstate(self, api):
        """PRD 3.6: "Once the logical clock reaches or passes `exclusion_until`, the active
        exclusion has lapsed and the player may be reinstated. Reinstatement, performed by
        a `LotteryOfficer`, moves `self_exclusion_status` `EXCLUDED → REINSTATED` and
        clears `exclusion_until` back to null."

        Design: Corner/calculations/self_exclusion_lapsed_allows_reinstate
        """
        player = create_player()
        set_clock("2026-01-05T00:00:00Z")
        validate_success(api.self_exclude_player(player["id"], {"exclusion_days": 10}, CLERK))
        set_clock("2026-01-15T00:00:00Z")  # == exclusion_until (enroll + 10 days)
        data = validate_success(api.reinstate_player(player["id"], OFF))
        assert data["self_exclusion_status"] == "REINSTATED", data["self_exclusion_status"]

    def test_reinstate_too_early_rejected(self, api):
        """PRD 3.6: "an attempt to reinstate while the exclusion is still active — that is,
        while the logical clock is strictly before `exclusion_until` — is rejected with
        `ERR_REINSTATE_TOO_EARLY`."

        Design: Corner/validations/reinstate_while_active_too_early_rejected
        """
        player = create_player()
        set_clock("2026-01-05T00:00:00Z")
        validate_success(api.self_exclude_player(player["id"], {"exclusion_days": 30}, CLERK))
        set_clock("2026-01-10T00:00:00Z")  # still within window
        resp = api.reinstate_player(player["id"], OFF)
        validate_error(resp, ApiErrorId.ERR_REINSTATE_TOO_EARLY.value)
        p = validate_success(api.get_player(player["id"], OFF))
        assert p["self_exclusion_status"] == "EXCLUDED", p["self_exclusion_status"]


class TestSettlementSegregationAndPriority:
    def test_finalize_same_preparer_segregation_rejected(self, api):
        """PRD 2.6: "When a settlement is finalized, the acting `X-User-ID` is compared
        against the `prepared_by_user_id` recorded at preparation; if they match, the
        finalization is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/settlement_finalize_same_user_segregation_rejected
        """
        game, ret, term, _ = setup_window_with_sold_tickets(
            prices=[100], game_type="DAILY", commission_rate=0.06,
            clock="2026-05-10T00:00:00Z", draw_date="2026-05-10T00:00:00Z")
        st = create_settlement(ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z",
                               prep_user_id="u-prep")
        resp = api.finalize_settlement(st["id"], officer_headers("u-prep"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        s = validate_success(api.get_settlement(st["id"], OFF))
        assert s["status"] == "DRAFT", s["status"]

    def test_state_beats_segregation_on_refinalize(self, api):
        """PRD 2.11: "then whether the target resource is in a state from which the
        requested transition is defined (`ERR_INVALID_STATE`)."
        PRD 2.11: "The practical effect is that, for instance, a request against a resource
        in the wrong state surfaces `ERR_INVALID_STATE` rather than a later business-rule
        error, and an over-threshold structural failure is never masked by a deeper domain
        check."

        Design: Corner/validations/priority_state_beats_segregation_on_finalize_pair
        """
        game, ret, term, _ = setup_window_with_sold_tickets(
            prices=[100], game_type="DAILY", commission_rate=0.06,
            clock="2026-05-10T00:00:00Z", draw_date="2026-05-10T00:00:00Z")
        st = create_settlement(ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z",
                               prep_user_id="u-prep")
        validate_success(api.finalize_settlement(st["id"], officer_headers("u-appr")))
        # second finalize, by the original preparer, on a now-FINALIZED settlement
        resp = api.finalize_settlement(st["id"], officer_headers("u-prep"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSettlementOCC:
    def test_stale_retailer_version_create_rejected(self, api):
        """PRD 2.5: "If the retailer's `version` has advanced since the client last
        observed it — because another writer already created a settlement that consumed the
        same accrued window, or because a counter-pay accrued additional balance — then
        `expected_retailer_version` no longer matches the retailer's current `version`, the
        snapshot would be stale, and the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_settlement_create_stale_retailer_version
        """
        game, ret, term, _ = setup_window_with_sold_tickets(
            prices=[100], game_type="DAILY", commission_rate=0.06,
            clock="2026-05-10T00:00:00Z", draw_date="2026-05-10T00:00:00Z")
        rv = fresh_retailer_version(ret["id"])
        # first create succeeds and bumps the retailer version
        validate_success(
            api.create_settlement(create_settlement_payload(
                ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv),
                officer_headers("u-prep")), expected_status=201)
        # second create still carrying the now-stale version
        resp = api.create_settlement(create_settlement_payload(
            ret["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", rv),
            officer_headers("u-prep"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_correct_version_create_succeeds_and_bumps(self, api):
        """PRD 2.5: "A request to prepare a settlement must carry
        `expected_retailer_version`, which is a non-optional input field carrying the
        client's last observed `version` of the target retailer."
        PRD 3.8: "Preparation snapshots the window and creates the settlement in `status`
        `DRAFT`, recording the preparing officer as `prepared_by_user_id` and incrementing
        the retailer's `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_settlement_create_correct_version_succeeds_and_bumps
        """
        game, ret, term, _ = setup_window_with_sold_tickets(
            prices=[100], game_type="DAILY", commission_rate=0.06,
            clock="2026-05-10T00:00:00Z", draw_date="2026-05-10T00:00:00Z")
        rv = fresh_retailer_version(ret["id"])
        st = validate_success(
            api.create_settlement(create_settlement_payload(
                ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv),
                officer_headers("u-prep")), expected_status=201)
        assert st["status"] == "DRAFT", st["status"]
        rv2 = fresh_retailer_version(ret["id"])
        assert rv2 == rv + 1, f"expected {rv + 1}, got {rv2}"


class TestRbac:
    def test_terminal_operator_cannot_create_game(self, api):
        """PRD 2.1: "When a role attempts an operation it is not authorized to perform, the
        request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/terminal_operator_cannot_create_game
        """
        resp = api.create_game({"name": "NoPerm", "game_type": "DAILY",
                                "claim_window_days": 7}, OP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_claims_clerk_cannot_approve_claim(self, api):
        """PRD 2.1: "When a role attempts an operation it is not authorized to perform, the
        request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/claims_clerk_cannot_approve_claim
        """
        from test_helpers import setup_adjudicating_claim
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        resp = api.approve_claim(ctx["claim"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        c = validate_success(api.get_prize_claim(ctx["claim"]["id"], OFF))
        assert c["status"] == "ADJUDICATING", c["status"]

    def test_licensing_admin_cannot_create_player(self, api):
        """PRD 2.1: "When a role attempts an operation it is not authorized to perform, the
        request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/licensing_admin_cannot_create_player
        """
        resp = api.create_player({"full_name": "Wrong Role",
                                  "government_id_number": "GID-RB2"}, LIC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD 2.1: "If either header is missing or malformed, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        resp = api._request("GET", "/games/00000000-0000-4000-8000-000000000009", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
