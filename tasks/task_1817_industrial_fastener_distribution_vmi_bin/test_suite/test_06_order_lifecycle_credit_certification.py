"""Replenishment order lifecycle: the dispute loop, cancellation compensation,
certification cascade and gates, credit boundary, terminal lockdown, and the
site balance rollup."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_agreement,
    create_part,
    create_route,
    create_site,
    create_stop,
    get_success_data,
    set_clock,
    setup_confirmed_order,
    setup_delivered_order,
    setup_draft_order,
    setup_site_part_agreement,
    start_route,
    submit_stop,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]


def _agr(api, agr_id):
    return get_success_data(api.get_bin_agreement(agr_id, ADMIN))


def _site(api, site_id):
    return get_success_data(api.get_site(site_id, ADMIN))


def _order(api, order_id):
    return get_success_data(api.get_replenishment_order(order_id, ADMIN))


class TestDisputeLoop:
    def test_dispute_pulls_delivered_quantity_back(self, api):
        """PRD §3.4: "Disputing moves `DELIVERED` to `DISPUTED` and pulls the
        delivered quantity back out of `on_hand_qty`, treating the stock
        backing the bin as unverified pending resolution; the posture is
        recomputed, and both the order's and the agreement's versions
        increment."

        Design: Difficulty/non_linear_state_machine/replenishment_order_delivered_disputed_delivered_cycle
        """
        ctx = setup_delivered_order(api, counted_qty=5, min_qty=10,
                                    max_qty=200)
        agr_id, order_id = ctx["agreement"]["id"], ctx["order_id"]
        assert _agr(api, agr_id)["on_hand_qty"] == 200, "5 scanned + 195 landed"

        disputed = validate_success(api.dispute_order(order_id, DRIVER))
        assert disputed["status"] == "DISPUTED"
        agr = _agr(api, agr_id)
        assert agr["on_hand_qty"] == 5, "the disputed 195 is pulled back out"
        assert agr["open_order_qty"] == 0

    def test_resolve_dispute_restores_bin_to_pre_dispute_quantity(self, api):
        """PRD §3.4: "A `DistributorAdmin` who upholds the delivery resolves
        the dispute, moving `DISPUTED` back to `DELIVERED` and restoring the
        quantity into `on_hand_qty`, with the posture recomputed and both
        versions incrementing again."

        Design: Difficulty/non_linear_state_machine/replenishment_order_delivered_disputed_delivered_cycle
        """
        ctx = setup_delivered_order(api, counted_qty=5, min_qty=10,
                                    max_qty=200)
        agr_id, order_id = ctx["agreement"]["id"], ctx["order_id"]
        get_success_data(api.dispute_order(order_id, DRIVER))
        resolved = validate_success(api.resolve_dispute(order_id, ADMIN))
        assert resolved["status"] == "DELIVERED", (
            "the cycle returns the order to DELIVERED"
        )
        agr = _agr(api, agr_id)
        assert agr["on_hand_qty"] == 200, (
            "dispute then resolve returns the bin to its exact pre-dispute "
            "quantity (5 + 195 - 195 + 195)"
        )
        assert agr["open_order_qty"] == 0


class TestCancelFromHoldCompensation:
    """Critical part with a certificate expiring 2026-08-05; the order is
    confirmed on 2026-08-03 and the expiry sweep then drops it to ON_HOLD."""

    def _setup_held_order(self, api):
        ctx = setup_confirmed_order(
            api, counted_qty=5, min_qty=10, max_qty=100,
            is_critical=True, with_cert=True,
            cert_expires_at="2026-08-05T00:00:00Z",
            route_date="2026-08-03T00:00:00Z",
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            clock_at="2026-08-03T09:00:00Z")
        set_clock(api, "2026-08-06T00:00:00Z")
        get_success_data(api.sweep_cert_expiry(ADMIN))
        return ctx

    def test_confirm_then_hold_cancel_restores_open_qty_and_balance(self, api):
        """PRD §3.4: "Cancelling from `ON_HOLD` marks the order `CANCELLED`,
        subtracts `ordered_qty` from the agreement's `open_order_qty`,
        subtracts `total_price_cents` from the site's
        `outstanding_balance_cents`, recomputes the posture (which may reopen
        an `AT_CAPACITY` agreement to `ACTIVE`), and increments the `version`
        of the order, the agreement, and the site."
        PRD §2.9: "Orders in `DRAFT`, `ON_HOLD`, `DISPUTED`, `DELIVERED`, or
        `CANCELLED` status contribute nothing to the balance."

        Design: Difficulty/compensating_invariant/order_confirm_then_cancel_restores_open_qty_and_balance
        """
        ctx = self._setup_held_order(api)
        agr_id, site_id, order_id = (
            ctx["agreement"]["id"], ctx["site"]["id"], ctx["order_id"])
        assert _order(api, order_id)["status"] == "ON_HOLD"

        cancelled = validate_success(api.cancel_order(order_id, ADMIN))
        assert cancelled["status"] == "CANCELLED"
        order = _order(api, order_id)
        assert order["total_price_cents"] == 96500, (
            "95 x 1000 undiscounted + 1500 cert fee, fixed at creation"
        )
        agr = _agr(api, agr_id)
        assert agr["open_order_qty"] == 0, "the hold-cancel credits the pipeline"
        assert agr["status"] == "ACTIVE", "5 + 0 < 100 reopens the posture"
        site = _site(api, site_id)
        assert site["outstanding_balance_cents"] == 0, (
            "no drift in the balance conserved quantity"
        )

    def test_confirmation_debits_pipeline_and_balance(self, api):
        """PRD §3.4: "A successful confirmation pins `delivery_mode` from the
        site, adds `ordered_qty` to the agreement's `open_order_qty`, adds
        `total_price_cents` to the site's `outstanding_balance_cents`,
        recomputes the agreement posture (which may flip it to `AT_CAPACITY`),
        and increments the `version` of the order, the agreement, and the site
        by one each."

        Design: Difficulty/compensating_invariant/order_confirm_then_cancel_restores_open_qty_and_balance
        """
        ctx = setup_confirmed_order(
            api, counted_qty=5, min_qty=10, max_qty=100,
            is_critical=True, with_cert=True,
            cert_expires_at="2026-08-05T00:00:00Z",
            route_date="2026-08-03T00:00:00Z",
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            clock_at="2026-08-03T09:00:00Z")
        agr = _agr(api, ctx["agreement"]["id"])
        assert agr["open_order_qty"] == 95
        assert agr["status"] == "AT_CAPACITY", "5 + 95 = 100 >= max 100"
        site = _site(api, ctx["site"]["id"])
        assert site["outstanding_balance_cents"] == 96500


class TestCertificationCascade:
    def _setup_confirmed_critical(self, api):
        ctx = setup_confirmed_order(
            api, counted_qty=5, min_qty=10, max_qty=100,
            is_critical=True, with_cert=True,
            cert_expires_at="2026-08-05T00:00:00Z",
            route_date="2026-08-03T00:00:00Z",
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            clock_at="2026-08-03T09:00:00Z")
        return ctx

    def test_cert_expiry_blocks_compliance_and_holds_order(self, api):
        """PRD §3.5: "every certificate in `VALID` status whose
        `cert_expires_at` the logical clock has reached or passed transitions
        to `EXPIRED`, and the sweep reports the affected ids as
        `expired_cert_ids`."
        PRD §3.5: "First, every agreement for that part in `ACTIVE` or
        `AT_CAPACITY` status has its `compliance_flag` set to `BLOCKED`,
        freezing new confirmations — confirmation against a `BLOCKED` agreement
        is rejected with `ERR_CERTIFICATION_BLOCKED`. Second, every order for
        that part sitting in `CONFIRMED` status drops to `ON_HOLD`: certificate
        expiry triggers the compliance block, and the compliance block holds
        the orders."

        Design: Difficulty/transitive_cascade/cert_expiry_to_compliance_block_to_order_hold_depth2
        """
        ctx = self._setup_confirmed_critical(api)
        cert_id = ctx["cert"]["id"]
        set_clock(api, "2026-08-06T00:00:00Z")
        sweep = validate_success(api.sweep_cert_expiry(ADMIN))
        assert cert_id in sweep["expired_cert_ids"]

        cert = get_success_data(api.get_lot_certificate(cert_id, ADMIN))
        assert cert["status"] == "EXPIRED"
        agr = _agr(api, ctx["agreement"]["id"])
        assert agr["compliance_flag"] == "BLOCKED"
        order = _order(api, ctx["order_id"])
        assert order["status"] == "ON_HOLD", (
            "the confirmed order is held by the cascade without ever being "
            "addressed directly"
        )

    def test_release_hold_without_valid_cert_rejected(self, api):
        """PRD §3.5: "The certification gate therefore guards two moments with
        the same rejection, `ERR_CERTIFICATION_BLOCKED` (HTTP 422): order
        confirmation, and the release of a held order."
        PRD §3.5: "Releasing a hold — `ON_HOLD` back to `CONFIRMED`, performed
        by a `DistributorAdmin` — requires at least one `VALID` lot certificate
        to exist for the order's part again, with the flag requirement enforced
        as at confirmation."

        Design: Difficulty/transitive_cascade/cert_expiry_to_compliance_block_to_order_hold_depth2
        """
        ctx = self._setup_confirmed_critical(api)
        set_clock(api, "2026-08-06T00:00:00Z")
        get_success_data(api.sweep_cert_expiry(ADMIN))
        order_id = ctx["order_id"]
        assert _order(api, order_id)["status"] == "ON_HOLD"
        resp = api.release_hold_order(order_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_BLOCKED, 422)
        assert _order(api, order_id)["status"] == "ON_HOLD"


class TestConfirmGatePriority:
    def test_confirm_cancelled_order_reports_state_not_credit(self, api):
        """PRD §2.8: "A request that would fail several stages receives the
        error from the earliest stage in this ordering."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`, which also covers terminal-state lockdown and
        idempotent re-triggers".
        PRD §2.8: "the credit gate, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`".

        The order is CANCELLED (stage 5 fails) on a site whose credit limit of
        0 would also fail the credit gate (stage 14); the earlier stage wins.

        Design: Difficulty/priority_pair_validation_conflict/confirm_order_state_beats_fiscal
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100,
                                credit_limit_cents=0)
        get_success_data(api.cancel_order(ctx["order_id"], ADMIN))
        resp = api.confirm_order(ctx["order_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_confirm_cancelled_order_reports_state_not_certification(self, api):
        """PRD §2.8: "A request that would fail several stages receives the
        error from the earliest stage in this ordering."
        PRD §2.8: "(5) transition legality — the target resource must be in a
        state from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        The critical part has no VALID certificate (stage 11 would fail), but
        the order is already CANCELLED, so transition legality fires first.

        Design: Difficulty/priority_pair_validation_conflict/confirm_order_state_beats_fiscal
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100,
                                is_critical=True)
        get_success_data(api.cancel_order(ctx["order_id"], ADMIN))
        resp = api.confirm_order(ctx["order_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestTerminalLockdown:
    @pytest.mark.parametrize("action", ["ship", "deliver", "dispute"])
    def test_cancelled_order_rejects_all_further_actions(self, api, action):
        """PRD §3.7: "once any resource in this programme reaches a terminal
        state — `RETIRED`, `OBSOLETE`, `CLOSED`, `CANCELLED`, `DELIVERED`,
        `EXPIRED`, `COMPLETED`, or `SCRAPPED` — every further transition
        attempt against it is rejected with `ERR_INVALID_STATE`, including
        idempotent re-triggers of the transition that already fired."

        Design: Corner/state_machines/terminal_state_lockdown_on_cancelled_order
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100)
        get_success_data(api.cancel_order(ctx["order_id"], ADMIN))
        order_id = ctx["order_id"]
        if action == "ship":
            resp = api.ship_order(order_id, ADMIN)
        elif action == "deliver":
            resp = api.deliver_order(order_id, DRIVER)
        else:
            resp = api.dispute_order(order_id, DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert _order(api, order_id)["status"] == "CANCELLED"


class TestParentPreconditionEnforcement:
    def test_retire_site_with_live_agreement_rejected(self, api):
        """PRD §3.7: "The system refuses while any bin agreement at the site
        remains `ACTIVE` or `AT_CAPACITY`, or while any route for the site
        remains `SCHEDULED` or `IN_PROGRESS`; a successful retirement
        increments the site's `version`."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/retire_site_with_live_agreement_rejected
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=1, max_qty=10)
        resp = api.retire_site(ctx["site"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert _site(api, ctx["site"]["id"])["status"] == "ACTIVE"

    def test_obsolete_part_with_open_confirmed_order_rejected(self, api):
        """PRD §3.7: "A `DistributorAdmin` marks a part obsolete, moving it
        from `ACTIVE` to `OBSOLETE` — a transition the system refuses while any
        replenishment order for the part remains `CONFIRMED` or `IN_TRANSIT`,
        or while any kit job listing the part is in `PICKING` or `ON_HOLD`."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/obsolete_part_with_open_confirmed_order_rejected
        """
        ctx = setup_confirmed_order(api, counted_qty=5, min_qty=10,
                                    max_qty=100)
        resp = api.obsolete_part(ctx["part"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        part = get_success_data(api.get_part(ctx["part"]["id"], ADMIN))
        assert part["status"] == "ACTIVE"


class TestCreditAndCertificationGates:
    def test_credit_limit_boundary_exactly_at_limit_allowed(self, api):
        """PRD §3.4: "Finally the credit gate: the site's
        `outstanding_balance_cents` plus the order's `total_price_cents` must
        not exceed the site's `credit_limit_cents`, or the confirmation is
        rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Credit 95000: the 95000-cent order confirms (0 + 95000 <= 95000); the
        96000-cent order then exceeds the limit and stays DRAFT.

        Design: Corner/validations/credit_limit_boundary_exactly_at_limit_allowed
        """
        site = create_site(api, ship_to_code="CL-1", credit_limit_cents=95000)
        part = create_part(api, sku="CL-P", unit_price_cents=1000,
                           total_stock_qty=100000)
        agr_eq = create_agreement(api, site["id"], part["id"],
                                  bin_location="CL1", min_qty=10, max_qty=100)
        agr_over = create_agreement(api, site["id"], part["id"],
                                    bin_location="CL2", min_qty=10,
                                    max_qty=101)
        route = create_route(api, site["id"])
        start_route(api, route["id"])
        stop_eq = create_stop(api, route["id"], agr_eq["id"])
        stop_over = create_stop(api, route["id"], agr_over["id"])
        order_eq = submit_stop(api, stop_eq["id"], 5)["generated_order_id"]
        order_over = submit_stop(api, stop_over["id"], 5)["generated_order_id"]
        assert _order(api, order_eq)["total_price_cents"] == 95000
        assert _order(api, order_over)["total_price_cents"] == 96000

        ok = validate_success(api.confirm_order(order_eq, ADMIN))
        assert ok["status"] == "CONFIRMED", "boundary is inclusive (<=)"

        resp = api.confirm_order(order_over, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 422)
        assert _order(api, order_over)["status"] == "DRAFT"

    def test_confirm_critical_part_without_valid_cert_blocked(self, api):
        """PRD §3.4: "The certification gate of §3.5 applies: the agreement's
        `compliance_flag` must be `CLEAR`, and when the part is critical at
        least one `VALID` lot certificate must exist for it, otherwise the
        confirmation is rejected with `ERR_CERTIFICATION_BLOCKED`."

        Design: Corner/validations/confirm_critical_part_without_valid_cert_blocked
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100,
                                is_critical=True)
        resp = api.confirm_order(ctx["order_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_BLOCKED, 422)
        assert _order(api, ctx["order_id"])["status"] == "DRAFT"


class TestSiteBalanceRollup:
    def test_balance_rollup_excludes_non_open_statuses(self, api):
        """PRD §2.9: "A parallel rollup keeps each site's
        `outstanding_balance_cents` exact: it is the integer-cent sum of
        `total_price_cents` over every replenishment order belonging to the
        site whose status is `CONFIRMED` or `IN_TRANSIT`, recomputed from
        source rows on every contributing transition — confirmation debits,
        hold-cancellation credits, and delivery settlements."
        PRD §2.9: "Orders in `DRAFT`, `ON_HOLD`, `DISPUTED`, `DELIVERED`, or
        `CANCELLED` status contribute nothing to the balance."

        Design: Corner/calculations/site_balance_rollup_excludes_non_open_statuses
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100,
                                unit_price_cents=1000)
        site_id, order_id = ctx["site"]["id"], ctx["order_id"]
        assert _site(api, site_id)["outstanding_balance_cents"] == 0, (
            "a DRAFT order contributes nothing"
        )
        get_success_data(api.confirm_order(order_id, ADMIN))
        assert _site(api, site_id)["outstanding_balance_cents"] == 95000, (
            "confirmation debits 95 x 1000"
        )
        get_success_data(api.ship_order(order_id, ADMIN))
        get_success_data(api.deliver_order(order_id, DRIVER))
        assert _site(api, site_id)["outstanding_balance_cents"] == 0, (
            "delivery settles the balance"
        )
