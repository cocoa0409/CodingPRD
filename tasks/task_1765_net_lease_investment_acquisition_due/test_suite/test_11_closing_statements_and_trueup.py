"""Closing-statement workflow: the deal-closed gate on finalize, the
cash-to-close invariant across true-up, true-up RBAC, and reissue OCC."""
from test_helpers import (
    TRUEUP_AM_APPROVER,
    ApiErrorId,
    acknowledge_statement,
    create_true_up_payload,
    default_proration_inputs,
    get_deal,
    issue_statement,
    propose_true_up,
    reissue_statement_payload,
    setup_clear_to_close,
    setup_closed_deal,
    validate_error,
    validate_success,
)


def _setup_acknowledged(api):
    """Clear-to-close + ISSUED + ACKNOWLEDGED statement; deal NOT closed."""
    ctx = setup_clear_to_close(
        deal_name="CrossEntDeal2",
        target_close_date="2026-09-20T00:00:00Z",
        purchase_price_cents=25000000, earnest_money_cents=500000,
        lease_rent_cents=1500000, lease_type="ABSOLUTE_NET",
        lease_commencement="2019-01-01T00:00:00Z",
        lease_expiration="2036-06-01T00:00:00Z",
        property_overrides={"address": "33 Cross Ave",
                            "rentable_sqft": 18000, "year_built": 2013},
        tenant_overrides={"legal_name": "Cross2Tenant", "credit_score": 820,
                          "annual_revenue_cents": 150000000})
    deal_id = ctx["deal"]["id"]
    stmt_id = ctx["statement"]["id"]
    issue_statement(deal_id, stmt_id, lease_id=ctx["lease"]["id"])
    ctx["statement"] = acknowledge_statement(deal_id, stmt_id)
    return ctx


class TestFinalizeRequiresClosedDeal:
    def test_finalize_true_up_blocked_until_deal_closed(
            self, api, escrow_headers):
        """PRD §3.11: "It requires the deal `CLOSED` (else
        `ERR_DEAL_NOT_CLOSED`, HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/closing_statement_finalize_depends_on_deal_closed_state
        """
        ctx = _setup_acknowledged(api)
        deal_id = ctx["deal"]["id"]
        assert get_deal(deal_id)["status"] == "CLEAR_TO_CLOSE"

        resp = api.finalize_true_up(deal_id, ctx["statement"]["id"],
                                    escrow_headers)
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_CLOSED)

    def test_finalize_true_up_succeeds_after_close(self, api,
                                                   escrow_headers):
        """PRD §3.11: "It requires the deal `CLOSED` (else
        `ERR_DEAL_NOT_CLOSED`, HTTP 422)"
        PRD §3.11: "Finalization flips `provisional` to false, folds every
        fully-approved adjustment's `amount_cents` into a final-variant
        recompute of the prorations — the adjustments move to `APPLIED` in
        the same step — and recomputes `total_prorations_cents` and
        `cash_to_close_cents` under the same pinned rounding and layering
        rules."
        PRD §3.11: "The statement lands in `TRUED_UP`."

        Design: Difficulty/cross_entity_state_dependency/closing_statement_finalize_depends_on_deal_closed_state
        """
        ctx = _setup_acknowledged(api)
        deal_id = ctx["deal"]["id"]
        stmt_id = ctx["statement"]["id"]

        validate_success(api.close_deal(deal_id, escrow_headers))
        finalized = validate_success(api.finalize_true_up(deal_id, stmt_id,
                                                          escrow_headers))
        assert finalized["status"] == "TRUED_UP"
        assert finalized["provisional"] is False


class TestCashToCloseInvariant:
    def _closed_ctx(self):
        return setup_closed_deal(
            deal_name="InvariantDeal2",
            target_close_date="2026-09-20T00:00:00Z",
            purchase_price_cents=25000000, earnest_money_cents=500000,
            lease_rent_cents=1200000, lease_type="ABSOLUTE_NET",
            lease_commencement="2018-06-01T00:00:00Z",
            lease_expiration="2035-12-01T00:00:00Z")

    def test_provisional_cash_to_close_at_issue(self, api, escrow_headers):
        """PRD §3.11: "The `cash_to_close_cents` composes in a pinned layered
        order: start from the `psa_price_cents`; subtract the financing
        application's `loan_amount_cents` (zero when there is no financing);
        add the `total_prorations_cents`, which may be negative; add the
        `assumption_fee_cents` (zero for a new loan or no financing); and
        finally subtract the `earnest_money_cents`."
        PRD §3.11: "Issuance computes all of these on the provisional
        variant, and the statement's `provisional` flag stays true until the
        true-up is finalized."

        Design: Difficulty/compensating_invariant/cash_to_close_invariant_under_reissue_and_trueup
        """
        ctx = setup_clear_to_close(
            deal_name="InvariantDeal2a",
            target_close_date="2026-09-20T00:00:00Z",
            purchase_price_cents=25000000, earnest_money_cents=500000,
            lease_rent_cents=1200000, lease_type="ABSOLUTE_NET",
            lease_commencement="2018-06-01T00:00:00Z",
            lease_expiration="2035-12-01T00:00:00Z")
        issued = issue_statement(ctx["deal"]["id"], ctx["statement"]["id"],
                                 lease_id=ctx["lease"]["id"])
        # BASE_RENT 52,603 (buyer credit) - TAX 108,000 (seller credit).
        assert issued["total_prorations_cents"] == -55397
        # 25,000,000 - 0 + (-55,397) + 0 - 500,000 = 24,444,603.
        assert issued["cash_to_close_cents"] == 24444603
        assert issued["provisional"] is True

    def test_true_up_folds_adjustment_into_final_cash_to_close(
            self, api, escrow_headers):
        """PRD §3.11: "Finalization flips `provisional` to false, folds every
        fully-approved adjustment's `amount_cents` into a final-variant
        recompute of the prorations — the adjustments move to `APPLIED` in
        the same step — and recomputes `total_prorations_cents` and
        `cash_to_close_cents` under the same pinned rounding and layering
        rules."
        PRD §3.11: "a signed `amount_cents` where positive means the buyer
        receives a credit"

        Design: Difficulty/compensating_invariant/cash_to_close_invariant_under_reissue_and_trueup
        """
        ctx = self._closed_ctx()
        deal_id = ctx["deal"]["id"]
        stmt_id = ctx["statement"]["id"]
        assert ctx["statement"]["total_prorations_cents"] == -55397
        assert ctx["statement"]["cash_to_close_cents"] == 24444603

        # Buyer gives back 50,000 cents of credit post-closing.
        adj = propose_true_up(deal_id, stmt_id, line_type="REPAIR_CREDIT",
                              amount_cents=-50000,
                              reason="Post-closing roof repair cost share")
        assert adj["status"] == "PROPOSED"
        validate_success(api.escrow_approve_true_up(deal_id, stmt_id,
                                                    adj["id"],
                                                    escrow_headers))
        approved = validate_success(api.asset_manager_approve_true_up(
            deal_id, stmt_id, adj["id"], TRUEUP_AM_APPROVER))
        assert approved["status"] == "FULLY_APPROVED"
        assert approved["approved"] is True

        finalized = validate_success(api.finalize_true_up(deal_id, stmt_id,
                                                          escrow_headers))
        assert finalized["status"] == "TRUED_UP"
        assert finalized["provisional"] is False
        assert finalized["total_prorations_cents"] == -105397, (
            "-55,397 provisional + (-50,000) adjustment")
        # The economic identity holds across the true-up with zero drift.
        assert finalized["cash_to_close_cents"] == 24394603

        adj_after = validate_success(api.get_true_up(deal_id, stmt_id,
                                                     adj["id"],
                                                     escrow_headers))
        assert adj_after["status"] == "APPLIED"


class TestTrueUpRbac:
    def test_asset_manager_exclusive_trueup_propose(self, api,
                                                    escrow_headers,
                                                    asset_manager_headers):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups` | Propose a true-up adjustment | AssetManager |"
        PRD §3.11: "The adjustment starts `PROPOSED` with `approved` false."

        Design: Corner/rbac/asset_manager_exclusive_trueup_propose
        """
        ctx = setup_closed_deal(deal_name="RBACDeal3")
        deal_id = ctx["deal"]["id"]
        stmt_id = ctx["statement"]["id"]

        denied = api.create_true_up(
            deal_id, stmt_id,
            create_true_up_payload(reason="escrow-proposed"), escrow_headers)
        validate_error(denied, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        proposed = validate_success(api.create_true_up(
            deal_id, stmt_id,
            create_true_up_payload(reason="am-proposed"),
            asset_manager_headers), 201)
        assert proposed["status"] == "PROPOSED"
        assert proposed["approved"] is False


class TestReissueOcc:
    def test_occ_stale_deal_version_on_closing_statement_reissue(
            self, api, escrow_headers):
        """PRD §2.9: "Reissuing a closing statement requires the request body
        to carry `expected_deal_version` holding the `version` of the parent
        deal as the client last observed it; if the deal's current `version`
        has advanced beyond that value — because another writer changed
        deal-level state such as posture or price since the client computed
        the reissue basis — the reissue is rejected with
        `ERR_STALE_DEAL_VERSION` (HTTP 412)."
        PRD §3.11: "the old statement becomes `SUPERSEDED`, a new statement
        is created in `DRAFT` with `statement_version` incremented by one,
        and the deal's `version` increments."

        Design: Corner/cross_cutting_layers/occ_stale_deal_version_on_closing_statement_reissue
        """
        ctx = setup_clear_to_close(deal_name="OCCReissueDeal")
        deal_id = ctx["deal"]["id"]
        lease_id = ctx["lease"]["id"]
        stmt1 = issue_statement(deal_id, ctx["statement"]["id"],
                                lease_id=lease_id)
        dv_pre = get_deal(deal_id)["version"]

        # First reissue with the fresh deal version succeeds.
        reissued = validate_success(api.reissue_closing_statement(
            deal_id, stmt1["id"],
            reissue_statement_payload(dv_pre, "2026-09-16T00:00:00Z",
                                      default_proration_inputs(lease_id)),
            escrow_headers))
        assert reissued["status"] == "DRAFT"
        assert reissued["statement_version"] == stmt1["statement_version"] + 1
        old = validate_success(api.get_closing_statement(deal_id,
                                                         stmt1["id"],
                                                         escrow_headers))
        assert old["status"] == "SUPERSEDED"
        assert get_deal(deal_id)["version"] == dv_pre + 1, (
            "The reissue increments the deal's version")

        # Put the new statement into ISSUED (a valid reissue from-state).
        stmt2 = issue_statement(deal_id, reissued["id"],
                                closing_date="2026-09-16T00:00:00Z",
                                lease_id=lease_id)
        assert stmt2["status"] == "ISSUED"

        # Reusing the pre-reissue deal version is a stale write: the
        # statement is in a valid from-state, so only the OCC guard can fire.
        stale = api.reissue_closing_statement(
            deal_id, stmt2["id"],
            reissue_statement_payload(dv_pre, "2026-09-17T00:00:00Z",
                                      default_proration_inputs(lease_id)),
            escrow_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_DEAL_VERSION)
