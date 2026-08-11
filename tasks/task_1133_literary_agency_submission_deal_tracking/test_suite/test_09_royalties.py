"""Royalty statements: tiered reconciliation, basis variants, the audit loop,
variance gates, earn-out accounting, and the royalties desk's RBAC boundary."""
from test_helpers import (
    ApiErrorId,
    close_period_as_accountant,
    create_royalty_statement_payload,
    create_statement,
    get_deal,
    get_statement,
    make_contracts_manager_headers,
    reconcile_statement,
    resolve_audit_payload,
    setup_active_deal,
    setup_executed_deal,
    setup_negotiating_deal,
    validate_error,
    validate_success,
)

# Statement shape used by the PRD's own worked example.
UNITS = (6000, 8000, 10000)
RECEIPTS = (6000000, 3200000, 1000000)


class TestRoyaltyReconciliation:
    def test_tiered_formula_full_compute(self, api):
        """PRD 3.8: "To see how basis moves money: at 6,000 hardcover, 8,000 trade, and 10,000 ebook units with receipts of 6,000,000, 3,200,000, and 1,000,000 cents and fractions 0.10, 0.08, and 0.25, the gross comes to 1,136,000 cents under `NET` but 1,120,500 cents under `RETAIL`."
        PRD 3.8: "The statement's `agency_commission_cents` is the gross multiplied by that fraction, floored; `author_net_cents` is the gross minus the commission."
        PRD 3.8: "Finally, `variance_cents` is the `publisher_reported_royalty_cents` minus the freshly computed `gross_royalty_cents`"

        Design: Difficulty/combinatorial_formula/royalty_reconciliation_tiered_formula_full_compute
        """
        ctx = setup_executed_deal(advance_cents=1000000, agency_name="Agency RR")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1136000,
        )
        reconciled = reconcile_statement(statement["id"])
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["gross_royalty_cents"] == 1136000, (
            "625,000 hardcover + 261,000 trade + 250,000 ebook"
        )
        assert reconciled["agency_commission_cents"] == 170400, "floor(1136000 * 0.15)"
        assert reconciled["author_net_cents"] == 965600, "gross minus commission"
        assert reconciled["variance_cents"] == 0

    def test_reconcile_grows_deal_earnout_by_author_net(self, api):
        """PRD 3.8: "the deal's `advance_earned_out_cents` grows by the statement's `author_net_cents`, capped so it can never exceed the deal's `advance_cents`"

        Design: Difficulty/combinatorial_formula/royalty_reconciliation_tiered_formula_full_compute
        """
        ctx = setup_executed_deal(advance_cents=1000000, agency_name="Agency RR")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1136000,
        )
        reconcile_statement(statement["id"])

        deal = get_deal(ctx["deal"]["id"])
        assert deal["advance_earned_out_cents"] == 965600, (
            "min(1000000, 0 + 965600): earn-out grows by the statement's author_net_cents"
        )

    def test_tier_boundary_5000_vs_5001_units(self, api):
        """PRD 3.8: "For hardcover, the average unit receipt is the hardcover receipts divided by `units_hardcover`, floored; the first 5,000 units (or all of them, if fewer sold) earn that floored average multiplied by the hardcover fraction, floored again, and every unit beyond 5,000 earns the floored average multiplied by the hardcover fraction plus the escalator, floored."

        Design: Corner/calculations/royalty_tier_boundary_5000_vs_5001_units
        """
        ctx = setup_active_deal(advance_cents=2000000, agency_name="Agency RT")
        deal_id = ctx["deal"]["id"]

        at_threshold = create_statement(
            deal_id, period_index=0, units=(5000, 0, 0), receipts=(5000000, 0, 0),
            publisher_reported_royalty_cents=500000,
        )
        reconciled_a = reconcile_statement(at_threshold["id"])
        assert reconciled_a["gross_royalty_cents"] == 500000, (
            "5000 units all at base rate: 5000 * floor(1000 * 0.10)"
        )

        close_period_as_accountant(ctx["agency"]["id"])
        above_threshold = create_statement(
            deal_id, period_index=1, units=(5001, 0, 0), receipts=(5001000, 0, 0),
            publisher_reported_royalty_cents=500125,
        )
        reconciled_b = reconcile_statement(above_threshold["id"])
        assert reconciled_b["gross_royalty_cents"] == 500125, (
            "5000 * 100 + 1 escalated unit * floor(1000 * 0.125) = 500125"
        )

    def test_earnout_clamps_at_advance_cap(self, api):
        """PRD 3.8: "the deal's `advance_earned_out_cents` grows by the statement's `author_net_cents`, capped so it can never exceed the deal's `advance_cents` — earnings beyond the advance belong to the author but do not move the earn-out field past its cap."

        Design: Corner/calculations/earnout_clamps_at_advance_cap
        """
        ctx = setup_executed_deal(advance_cents=500000, agency_name="Agency EC")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1136000,
        )
        reconcile_statement(statement["id"])

        deal = get_deal(ctx["deal"]["id"])
        assert deal["advance_earned_out_cents"] == 500000, (
            "min(500000, 0 + 965600): clamped exactly at the advance cap"
        )

    def test_retail_basis_variant_produces_different_gross(self, api):
        """PRD 3.8: "the gross comes to 1,136,000 cents under `NET` but 1,120,500 cents under `RETAIL`."
        PRD 3.8: "The escalator depends on the deal's basis — 0.025 when the basis is `NET`, 0.0125 when it is `RETAIL`"
        PRD 3.7: "The deal's `royalty_basis` — `NET` or `RETAIL`, copied from the winning offer — is immutable from creation onward"

        Design: Corner/calculations/royalty_retail_basis_variant_produces_different_gross
        """
        ctx = setup_executed_deal(advance_cents=2000000, royalty_basis="RETAIL",
                                  agency_name="Agency RB")
        assert ctx["deal"]["royalty_basis"] == "RETAIL"

        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1120500,
        )
        reconciled = reconcile_statement(statement["id"])
        assert reconciled["gross_royalty_cents"] == 1120500, (
            "612,000 hardcover + 258,500 trade + 250,000 ebook under the 0.0125 escalator"
        )
        assert reconciled["agency_commission_cents"] == 168075, "floor(1120500 * 0.15)"
        assert reconciled["author_net_cents"] == 952425


def _setup_reconciled_statement(agency_name, publisher_reported=1138000):
    """Executed deal + reconciled statement on the PRD's worked-example inputs."""
    ctx = setup_executed_deal(advance_cents=2000000, agency_name=agency_name)
    statement = create_statement(
        ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
        publisher_reported_royalty_cents=publisher_reported,
    )
    reconciled = reconcile_statement(statement["id"])
    return ctx, reconciled


class TestAuditLoop:
    def test_audit_reopen_loop_edge(self, api, royalties_accountant_headers):
        """PRD 3.8: "If the variance still exceeds tolerance after resolution, the accountant may re-open the audit (`AUDIT_RESOLVED` → `AUDIT_OPEN`) under the same two gates as the original opening"
        PRD 3.8: "A resolution that re-submits identical receipts produces a zero difference and leaves the earn-out untouched."

        Design: Difficulty/non_linear_state_machine/royalty_statement_audit_loop_reopen_and_clear
        """
        _ctx, reconciled = _setup_reconciled_statement("Agency AL")
        assert reconciled["variance_cents"] == 2000, "1138000 - 1136000"
        sid = reconciled["id"]

        opened = validate_success(api.open_audit(sid, royalties_accountant_headers), 200)
        assert opened["status"] == "AUDIT_OPEN"

        resolved = validate_success(
            api.resolve_audit(sid, resolve_audit_payload(6000000, 3200000, 1000000),
                              royalties_accountant_headers),
            200,
        )
        assert resolved["status"] == "AUDIT_RESOLVED"
        assert resolved["variance_cents"] == 2000, "identical receipts leave the variance at 2000"

        reopened = validate_success(api.open_audit(sid, royalties_accountant_headers), 200)
        assert reopened["status"] == "AUDIT_OPEN", (
            "AUDIT_RESOLVED must loop back to AUDIT_OPEN while variance stays out of tolerance"
        )

    def test_audit_resolve_adjusted_receipts_then_clear(self, api, royalties_accountant_headers):
        """PRD 3.8: "the receipts are overwritten and all four computed fields recomputed exactly as at reconciliation, and the deal's `advance_earned_out_cents` is adjusted by the difference between the new and old `author_net_cents`, clamped to stay between 0 and `advance_cents`."
        PRD 3.8: "once the variance is at or under 500 cents, the statement may be cleared — from either `RECONCILED` or `AUDIT_RESOLVED` — into the terminal `CLEARED` state"

        Design: Difficulty/non_linear_state_machine/royalty_statement_audit_loop_reopen_and_clear
        """
        ctx, reconciled = _setup_reconciled_statement("Agency AL")
        sid = reconciled["id"]
        validate_success(api.open_audit(sid, royalties_accountant_headers), 200)

        resolved = validate_success(
            api.resolve_audit(sid, resolve_audit_payload(6000000, 3200000, 1008000),
                              royalties_accountant_headers),
            200,
        )
        assert resolved["gross_royalty_cents"] == 1138000, (
            "ebook 1008000 -> floor(1008000 * 0.25) = 252000; 625000 + 261000 + 252000"
        )
        assert resolved["variance_cents"] == 0

        cleared = validate_success(api.clear_statement(sid, royalties_accountant_headers), 200)
        assert cleared["status"] == "CLEARED"

        deal = get_deal(ctx["deal"]["id"])
        assert deal["advance_earned_out_cents"] == 967300, (
            "965600 + (967300 - 965600): adjusted by the author_net delta"
        )

    def test_earnout_forward_action_adds_author_net(self, api):
        """PRD 3.8: "the deal's `advance_earned_out_cents` grows by the statement's `author_net_cents`, capped so it can never exceed the deal's `advance_cents`"

        Design: Difficulty/compensating_invariant/earnout_unchanged_by_identical_receipts_resolve
        """
        ctx = setup_executed_deal(advance_cents=2000000, agency_name="Agency C1")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1137000,
        )
        reconciled = reconcile_statement(statement["id"])
        assert reconciled["variance_cents"] == 1000, "1137000 - 1136000"

        deal = get_deal(ctx["deal"]["id"])
        assert deal["advance_earned_out_cents"] == 965600, (
            "the forward action adds author_net to the earn-out"
        )

    def test_identical_receipts_resolve_leaves_earnout_unchanged(self, api, royalties_accountant_headers):
        """PRD 3.8: "A resolution that re-submits identical receipts produces a zero difference and leaves the earn-out untouched."

        Design: Difficulty/compensating_invariant/earnout_unchanged_by_identical_receipts_resolve
        """
        ctx = setup_executed_deal(advance_cents=2000000, agency_name="Agency C1")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=UNITS, receipts=RECEIPTS,
            publisher_reported_royalty_cents=1137000,
        )
        reconcile_statement(statement["id"])
        earnout_after_forward = get_deal(ctx["deal"]["id"])["advance_earned_out_cents"]
        assert earnout_after_forward == 965600

        validate_success(api.open_audit(statement["id"], royalties_accountant_headers), 200)
        resolved = validate_success(
            api.resolve_audit(statement["id"],
                              resolve_audit_payload(6000000, 3200000, 1000000),
                              royalties_accountant_headers),
            200,
        )
        assert resolved["variance_cents"] == 1000, "variance itself is also unchanged"

        deal = get_deal(ctx["deal"]["id"])
        assert deal["advance_earned_out_cents"] == earnout_after_forward, (
            "a compensating resolve with identical receipts must not move the earn-out"
        )


class TestVarianceAndStateGates:
    def test_clear_audit_open_state_beats_fiscal_variance(self, api, royalties_accountant_headers):
        """PRD 2.9: "Every request is validated against an ordered pipeline; the first failing check determines the error response, so an earlier failure masks later ones."
        PRD 3.8: "once the variance is at or under 500 cents, the statement may be cleared — from either `RECONCILED` or `AUDIT_RESOLVED` — into the terminal `CLEARED` state, with an out-of-tolerance clear rejected as `ERR_VARIANCE_UNRESOLVED`."

        Design: Difficulty/priority_pair_validation_conflict/clear_audit_open_state_beats_fiscal_variance
        """
        _ctx, reconciled = _setup_reconciled_statement("Agency P1")
        sid = reconciled["id"]
        validate_success(api.open_audit(sid, royalties_accountant_headers), 200)

        resp = api.clear_statement(sid, royalties_accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_clear_audit_open_leaves_statement_unchanged(self, api, royalties_accountant_headers):
        """PRD 2.9: "State admissibility — the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`, 409)."
        PRD 3.8: "once the variance is at or under 500 cents, the statement may be cleared — from either `RECONCILED` or `AUDIT_RESOLVED` — into the terminal `CLEARED` state"

        Design: Difficulty/priority_pair_validation_conflict/clear_audit_open_state_beats_fiscal_variance
        """
        _ctx, reconciled = _setup_reconciled_statement("Agency P1")
        sid = reconciled["id"]
        validate_success(api.open_audit(sid, royalties_accountant_headers), 200)

        resp = api.clear_statement(sid, royalties_accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        current = get_statement(sid)
        assert current["status"] == "AUDIT_OPEN", (
            "the failed clear must leave the statement in AUDIT_OPEN"
        )
        assert current["variance_cents"] == 2000

    def test_open_audit_within_tolerance_rejected(self, api, royalties_accountant_headers):
        """PRD 3.8: "Opening an audit (`RECONCILED` → `AUDIT_OPEN`) requires the absolute value of `variance_cents` to exceed 500 cents — the audit tolerance — with anything at or under tolerance rejected as `ERR_VARIANCE_WITHIN_TOLERANCE`"

        Design: Corner/validations/open_audit_within_tolerance_rejected
        """
        _ctx, reconciled = _setup_reconciled_statement("Agency WT", publisher_reported=1136400)
        assert reconciled["variance_cents"] == 400, "1136400 - 1136000"

        resp = api.open_audit(reconciled["id"], royalties_accountant_headers)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_WITHIN_TOLERANCE.value)

        current = get_statement(reconciled["id"])
        assert current["status"] == "RECONCILED"

    def test_clear_reconciled_with_large_variance_rejected(self, api, royalties_accountant_headers):
        """PRD 3.8: "once the variance is at or under 500 cents, the statement may be cleared — from either `RECONCILED` or `AUDIT_RESOLVED` — into the terminal `CLEARED` state, with an out-of-tolerance clear rejected as `ERR_VARIANCE_UNRESOLVED`."

        Design: Corner/validations/clear_reconciled_with_large_variance_rejected
        """
        _ctx, reconciled = _setup_reconciled_statement("Agency VU", publisher_reported=1137000)
        assert reconciled["variance_cents"] == 1000

        resp = api.clear_statement(reconciled["id"], royalties_accountant_headers)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_UNRESOLVED.value)

        current = get_statement(reconciled["id"])
        assert current["status"] == "RECONCILED"


class TestStatementIntakeAndDealLiveness:
    def test_future_statement_rejected_at_intake(self, api, royalties_accountant_headers):
        """PRD 3.8: "Two period gates apply at intake: a `period_index` beyond the agency's current `period_index` is a future statement and fails with `ERR_FUTURE_STATEMENT`, while a `period_index` at or before `books_closed_through_period_index` falls inside closed books and fails with `ERR_BOOKS_CLOSED`."

        Design: Corner/validations/future_statement_rejected_at_intake
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency FS")
        assert ctx["agency"]["period_index"] == 0

        resp = api.create_royalty_statement(
            create_royalty_statement_payload(
                ctx["deal"]["id"], period_index=1,
                units=(100, 0, 0), receipts=(100000, 0, 0),
                publisher_reported_royalty_cents=10000,
            ),
            royalties_accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FUTURE_STATEMENT.value)

    def test_reconcile_statement_on_negotiating_deal_rejected(self, api, royalties_accountant_headers):
        """PRD 3.8: "Reconciliation (`RECEIVED` → `RECONCILED`) requires the deal to be `EXECUTED` or `ACTIVE` (`ERR_DEAL_NOT_LIVE`)"

        Design: Corner/validations/reconcile_statement_on_negotiating_deal_rejected
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency NL")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=(100, 0, 0), receipts=(100000, 0, 0),
            publisher_reported_royalty_cents=10000,
        )
        assert statement["status"] == "RECEIVED"

        resp = api.reconcile_statement(statement["id"], royalties_accountant_headers)
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_LIVE.value)

        current = get_statement(statement["id"])
        assert current["status"] == "RECEIVED"

    def test_contracts_manager_cannot_reconcile_forbidden(self, api):
        """PRD 2.1: "Each endpoint admits a defined subset of these roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/contracts_manager_cannot_reconcile_forbidden
        """
        ctx = setup_executed_deal(advance_cents=500000, agency_name="Agency RB2")
        statement = create_statement(
            ctx["deal"]["id"], period_index=0, units=(100, 0, 0), receipts=(100000, 0, 0),
            publisher_reported_royalty_cents=10000,
        )

        resp = api.reconcile_statement(statement["id"], make_contracts_manager_headers("cm-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

        current = get_statement(statement["id"])
        assert current["status"] == "RECEIVED"
