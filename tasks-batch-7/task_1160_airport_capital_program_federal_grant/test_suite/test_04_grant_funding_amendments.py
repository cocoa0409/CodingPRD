"""Grant funding split, entitlement purse, and grant amendments (PRD §2.7, §3.3, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_grant, assert_grant_amendment, assert_money, assert_grant_funds_conserved,
    create_sponsor, create_draft_program, add_project, submit_program, accept_program,
    apply_selection, create_application, certify_all_assurances, submit_application,
    offer_application, setup_active_grant, setup_certified_application,
    create_amendment, current_grant_version, request_closeout, set_clock,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestFundingSplitWaterfall:
    def test_funding_split_waterfall_small_hub(self):
        """PRD §3.4: "First, the federal share is the tier percentage of `total_budget`,
        rounded half-up to two decimal places — the same figure already obligated. Second,
        `state_share_estimated` is one half of the non-federal remainder — `total_budget`
        minus the federal share — rounded half-up to two decimal places. Third,
        `local_share_estimated` is whatever remains: `total_budget` minus the federal share
        minus the state estimate, an exact subtraction requiring no further rounding."
        PRD §3.4: "fixes its `federal_share_pct` from the sponsor's tier: seventy-five percent
        for `LARGE_HUB`, eighty percent for `MEDIUM_HUB`, ninety percent for `SMALL_HUB`, and
        ninety-five percent for `NONHUB`."
        SMALL_HUB, budget 1,000,000 -> federal 900,000.00; state (100,000 x 0.5) 50,000.00;
        local 50,000.00.

        Design: Difficulty/combinatorial_formula/funding_split_tiered_waterfall
        """
        ctx = setup_active_grant(sponsor_tier="SMALL_HUB")
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert_grant(grant)
        assert_money(grant["federal_share_pct"], 0.90, "federal_share_pct")
        assert_money(grant["federal_obligated"], 900_000.00, "federal_obligated")
        assert_money(grant["state_share_estimated"], 50_000.00, "state_share_estimated")
        assert_money(grant["local_share_estimated"], 50_000.00, "local_share_estimated")

    def test_funding_split_waterfall_large_hub(self):
        """PRD §3.4: "the federal share is the tier percentage of `total_budget`" and
        "`state_share_estimated` is one half of the non-federal remainder".
        LARGE_HUB (0.75), budget 1,000,000 -> federal 750,000.00; the remaining 250,000
        splits to state 125,000.00 and local 125,000.00 — a different remainder than the
        SMALL_HUB tier produces.

        Design: Difficulty/combinatorial_formula/funding_split_tiered_waterfall
        """
        ctx = setup_active_grant(sponsor_tier="LARGE_HUB")
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert_money(grant["federal_share_pct"], 0.75, "federal_share_pct")
        assert_money(grant["federal_obligated"], 750_000.00, "federal_obligated")
        assert_money(grant["state_share_estimated"], 125_000.00, "state_share_estimated")
        assert_money(grant["local_share_estimated"], 125_000.00, "local_share_estimated")


class TestAmendmentContingency:
    def test_amendment_contingency_new_total_and_amount(self):
        """PRD §3.4: "the `new_total_budget` is that base divided by nine-tenths — that is,
        one minus the ten-percent contingency rate, so that the contingency lands at exactly
        ten percent of the new total — rounded half-up to two decimal places; the
        `contingency_amount` is then the new total minus the base".
        Base 1,000,000 + 100,000 = 1,100,000 -> new total 1,222,222.22; contingency
        122,222.22.

        Design: Difficulty/combinatorial_formula/amendment_contingency_circular
        """
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        amendment = create_amendment(grant_id, 100_000, "added taxiway fillets",
                                     current_grant_version(grant_id))
        assert_grant_amendment(amendment)
        assert_money(amendment["new_total_budget"], 1_222_222.22, "new_total_budget")
        assert_money(amendment["contingency_amount"], 122_222.22, "contingency_amount")

    def test_amendment_contingency_federal_delta(self):
        """PRD §3.4: "the `federal_delta` is the grant's `federal_share_pct` applied to the
        increase of `new_total_budget` over the prior `total_budget`, rounded half-up to two
        decimal places."
        PRD §3.4: "The new amendment starts in `PENDING`".
        0.90 x (1,222,222.22 - 1,000,000) = 199,999.998 -> 200,000.00.

        Design: Difficulty/combinatorial_formula/amendment_contingency_circular
        """
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        amendment = create_amendment(grant_id, 100_000, "added taxiway fillets",
                                     current_grant_version(grant_id))
        assert_money(amendment["federal_delta"], 200_000.00, "federal_delta")
        assert amendment["status"] == "PENDING"


class TestAmendmentApprovalOrder:
    def _setup_grant_with_oversized_pending_amendment(self):
        """ACTIVE grant (obligated 900,000; NPE available 4,100,000) plus a PENDING
        amendment whose federal_delta (5,100,000.00) exceeds the NPE balance."""
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        amendment = create_amendment(grant_id, 5_000_000, "terminal expansion",
                                     current_grant_version(grant_id))
        assert_money(amendment["federal_delta"], 5_100_000.00, "federal_delta")
        return ctx, amendment

    def test_amendment_approve_state_check_masks_fiscal_check(self):
        """PRD §3.4: "Approval is guarded by two checks in order: the grant must be `ACTIVE`
        (otherwise `ERR_GRANT_NOT_ACTIVE`, HTTP 409), and the `federal_delta` must not exceed
        the sponsor's current `npe_entitlement_available` (otherwise
        `ERR_ENTITLEMENT_INSUFFICIENT`, HTTP 402)."
        With the grant already CLOSEOUT_REQUESTED and the delta unaffordable, the state
        check fires first.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_amendment_approve
        """
        ctx, amendment = self._setup_grant_with_oversized_pending_amendment()
        request_closeout(ctx["grant"]["id"])
        res = api_client.approve_amendment(amendment["id"], FAA)
        validate_error(res, ApiErrorId.ERR_GRANT_NOT_ACTIVE, expected_status=409)
        assert res.json()["data"]["error_id"] != "ERR_ENTITLEMENT_INSUFFICIENT"

    def test_amendment_approve_entitlement_insufficient_isolated(self):
        """PRD §3.4: "the `federal_delta` must not exceed the sponsor's current
        `npe_entitlement_available` (otherwise `ERR_ENTITLEMENT_INSUFFICIENT`, HTTP 402)".
        With the grant still ACTIVE, only the fiscal check can fail.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_amendment_approve
        """
        ctx, amendment = self._setup_grant_with_oversized_pending_amendment()
        res = api_client.approve_amendment(amendment["id"], FAA)
        validate_error(res, ApiErrorId.ERR_ENTITLEMENT_INSUFFICIENT, expected_status=402)
        after = validate_success(
            api_client.list_amendments(ctx["grant"]["id"], SPONSOR), 200)
        row = [a for a in after if a["id"] == amendment["id"]][0]
        assert row["status"] == "PENDING"
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"], SPONSOR), 200)
        assert grant["status"] == "ACTIVE"
        assert_money(grant["federal_obligated"], 900_000.00, "federal_obligated unchanged")


class TestOfferEntitlement:
    def test_entitlement_insufficient_on_offer_then_exact_fit(self):
        """PRD §3.3: "the obligation may not exceed `npe_entitlement_available` plus an
        optional `discretionary_amount` supplied with the offer, and a breach is rejected with
        `ERR_ENTITLEMENT_INSUFFICIENT` (HTTP 402)."
        PRD §3.3: "carrying `offered_federal_obligated` at the computed obligation and
        `offered_entitlement_portion` at the smaller of that obligation and the sponsor's
        current `npe_entitlement_available`".

        Design: Corner/validations/entitlement_insufficient_on_offer_then_exact_fit
        """
        set_clock("2026-05-01T00:00:00Z")
        # NPE 100,000 against a 1,000,000 project at SMALL_HUB: obligation 900,000.
        ctx = setup_certified_application(npe_total=100_000)
        app_id = ctx["application"]["id"]
        submit_application(app_id)

        res = api_client.offer_application(app_id, FAA)
        validate_error(res, ApiErrorId.ERR_ENTITLEMENT_INSUFFICIENT, expected_status=402)

        # Discretionary cover makes 900,000 <= 100,000 + 800,000 exactly.
        offered = validate_success(api_client.offer_application(
            app_id, FAA, {"discretionary_amount": 800_000}), 200)
        assert offered["status"] == "OFFERED"
        assert_money(offered["offered_federal_obligated"], 900_000.00,
                     "offered_federal_obligated")
        assert_money(offered["offered_entitlement_portion"], 100_000.00,
                     "offered_entitlement_portion")


class TestAmendmentOcc:
    def test_amendment_stale_version_occ(self):
        """PRD §2.7: "Creating a grant amendment against a grant requires the request to carry
        `expected_grant_version`, a non-optional field holding the `version` of the grant the
        client last observed; if that value does not equal the grant's current `version` —
        for instance because another writer has since created an amendment or otherwise
        advanced the grant — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "if a prior amendment of the same grant is still `PENDING`, it is
        immediately moved to `SUPERSEDED`, and creating the amendment increments the grant's
        `version` by one."

        Design: Corner/cross_cutting_layers/amendment_stale_version_occ
        """
        ctx = setup_active_grant()
        grant_id = ctx["grant"]["id"]
        observed = current_grant_version(grant_id)

        amd_a = create_amendment(grant_id, 100_000, "A", observed)
        assert current_grant_version(grant_id) == observed + 1, (
            "creating the amendment increments the grant's version by exactly one")

        res = api_client.create_amendment(grant_id, {
            "added_scope_cost": 200_000, "reason": "B stale",
            "expected_grant_version": observed,
        }, SPONSOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Retrying with the fresh version succeeds and supersedes amendment A.
        amd_b = create_amendment(grant_id, 200_000, "B fresh",
                                 current_grant_version(grant_id))
        assert amd_b["status"] == "PENDING"
        rows = validate_success(api_client.list_amendments(grant_id, SPONSOR), 200)
        by_id = {a["id"]: a for a in rows}
        assert by_id[amd_a["id"]]["status"] == "SUPERSEDED"
        assert by_id[amd_b["id"]]["status"] == "PENDING"
