"""Dealer credit ladder (thresholds, PATCH re-evaluation, payment-driven
recovery), exposure views, contract activation OCC, and contract cascades."""
from test_helpers import (
    CREDIT_MANAGER,
    DISPATCHER,
    ApiErrorId,
    activate_dealer_contract,
    api_client,
    assert_dealer,
    base_order_fixture,
    create_dealer,
    create_terminal,
    create_dealer_contract,
    create_order,
    drive_order_to_delivered,
    get_success_data,
    post_payment,
    publish_index,
    schedule_order,
    validate_error,
    validate_success,
)


class TestCreditThresholdBoundaries:

    def _dealer_with_fixed_order(self, name, dealer_name, credit_limit,
                                 requested_gal):
        ctx = base_order_fixture(name=name, truck_count=0,
                                 dealer_name=dealer_name,
                                 credit_limit_cents=credit_limit)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], requested_gal,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        return ctx, order

    def test_credit_watch_threshold_exact_80pct(self):
        """PRD section 3.3: "Otherwise, when five times the committed exposure
        reaches or exceeds four times the credit limit — an exposure of exactly
        eighty percent crosses the line — the dealer is `WATCH`."

        Design: Difficulty/boundary_precision_check/credit_watch_threshold_exact_80pct
        """
        ctx, _ = self._dealer_with_fixed_order("T-B1", "Dealer BA", 2_100_000,
                                               17_000)
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        assert_dealer(dealer)
        # 17000 gal FIXED 90000: 1530000 + 150000 = 1680000 committed;
        # 1680000 * 5 == 2100000 * 4 -> the >= comparison crosses.
        assert dealer["committed_exposure_cents"] == 1_680_000
        assert dealer["credit_status"] == "WATCH"

    def test_credit_watch_one_gallon_below_stays_good_standing(self):
        """PRD section 3.3: "Below that, the dealer is `GOOD_STANDING`."

        Design: Difficulty/boundary_precision_check/credit_watch_threshold_exact_80pct
        """
        ctx, _ = self._dealer_with_fixed_order("T-B1", "Dealer BB", 2_100_000,
                                               16_999)
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        # 1679910 * 5 = 8399550 < 2100000 * 4 = 8400000 -> below the line.
        assert dealer["committed_exposure_cents"] == 1_679_910
        assert dealer["credit_status"] == "GOOD_STANDING"


class TestCreditStatusCycle:

    def _setup_delivered_17000(self):
        """Dealer limit 2100000; a 17000-gal FIXED order (1680000) DELIVERED."""
        # 17000 gal must fit the truck's tank (PRD 3.6 capacity gate).
        ctx = base_order_fixture(name="T-S2", credit_limit_cents=2_100_000,
                                 truck_capacity_gal=20_000)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 17_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        return ctx, order

    def test_credit_status_watch_after_80pct_order(self):
        """PRD section 3.3: "Otherwise, when five times the committed exposure
        reaches or exceeds four times the credit limit — an exposure of exactly
        eighty percent crosses the line — the dealer is `WATCH`."

        Design: Difficulty/non_linear_state_machine/dealer_credit_status_full_cycle
        """
        ctx, _ = self._setup_delivered_17000()
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        assert dealer["credit_status"] == "WATCH", (
            "1680000 committed vs 2100000 limit is exactly 80%; got "
            f"{dealer['credit_status']}")

    def test_credit_status_full_cycle(self):
        """PRD section 3.3: "The credit limit may later be raised or lowered;
        the update bumps `Dealer.version` and immediately re-evaluates the
        dealer's credit posture, which may flip between `WATCH` and `SUSPENDED`
        or back to `GOOD_STANDING` as the numbers dictate."
        PRD section 3.3: "When `committed_exposure_cents` reaches or exceeds
        `credit_limit_cents`, the dealer is `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/dealer_credit_status_full_cycle
        """
        ctx, order = self._setup_delivered_17000()
        dealer_id = ctx["dealer"]["id"]
        drive_order_to_delivered(order["id"], ctx["trucks"][0]["id"])
        mid = get_success_data(api_client.get_dealer(dealer_id, CREDIT_MANAGER))
        assert mid["credit_status"] == "WATCH", \
            "setup check: 1680000 ledger exposure holds WATCH at 2100000"

        # Downward PATCH drops the limit below committed exposure.
        resp = api_client.update_dealer(dealer_id,
                                        {"credit_limit_cents": 1_600_000},
                                        CREDIT_MANAGER)
        patched = validate_success(resp, expected_status=200)
        assert patched["credit_limit_cents"] == 1_600_000
        suspended = get_success_data(api_client.get_dealer(dealer_id,
                                                           CREDIT_MANAGER))
        assert suspended["credit_status"] == "SUSPENDED", \
            "1680000 >= 1600000 crosses the suspension line"

        # Paying 1000000 down leaves 680000: 680000*5 < 1600000*4 -> GOOD.
        post_payment(dealer_id, 1_000_000, method="WIRE")
        recovered = get_success_data(api_client.get_dealer(dealer_id,
                                                           CREDIT_MANAGER))
        assert recovered["credit_status"] == "GOOD_STANDING", (
            "payment brings the dealer full cycle; got "
            f"{recovered['credit_status']}")


class TestExposureVariants:

    def _setup_ledger_and_pipeline(self):
        """Dealer with one DELIVERED FIXED order (invoice 1680000) plus one
        ALLOCATED INDEX order (provisional 625000) under a successor contract.
        """
        # 17000 gal must fit the truck's tank (PRD 3.6 capacity gate).
        ctx = base_order_fixture(name="T-D2", truck_capacity_gal=20_000)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer = ctx["dealer"]
        order1 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 17_000,
                              dealer_contract_id=ctx["dealer_contract"]["id"])
        drive_order_to_delivered(order1["id"], ctx["trucks"][0]["id"])
        # Successor INDEX contract supersedes the FIXED one; the DELIVERED
        # order and its open invoice are unaffected (PRD 3.3).
        contract2 = create_dealer_contract(dealer["id"], ctx["terminal"]["id"],
                                           pricing_mode="INDEX",
                                           volume_committed_gal=50_000)
        activate_dealer_contract(contract2["id"], dealer["id"])
        order2 = create_order(dealer["id"], ctx["terminal"]["id"],
                              ctx["zone"]["id"], 5_000,
                              dealer_contract_id=contract2["id"])
        assert order2["fulfillment_status"] == "ALLOCATED"
        return ctx, order1, order2

    def test_ledger_exposure_counts_open_invoices_only(self):
        """PRD section 3.3: "The `ledger_exposure_cents` is the backward-
        looking view: the sum of `open_balance_cents` over the dealer's orders
        whose `invoice_status` is `OPEN`."

        Design: Difficulty/dual_variant_calc/dealer_exposure_ledger_vs_committed_diverge
        """
        ctx, order1, _ = self._setup_ledger_and_pipeline()
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        assert_dealer(dealer)
        assert dealer["ledger_exposure_cents"] == 1_680_000, (
            "only the OPEN invoice on the DELIVERED order counts; got "
            f"{dealer['ledger_exposure_cents']}")

    def test_committed_exposure_adds_pipeline_provisionals(self):
        """PRD section 3.3: "The `committed_exposure_cents` is the forward-
        looking view used by credit decisions: the `fee_balance_cents`, plus
        the ledger exposure, plus the sum of `final_total_cents` over the
        dealer's `LOADED` orders, plus the sum of `provisional_total_cents`
        over the dealer's `ALLOCATED` and `SCHEDULED` orders."

        Design: Difficulty/dual_variant_calc/dealer_exposure_ledger_vs_committed_diverge
        """
        ctx, _, _ = self._setup_ledger_and_pipeline()
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        # 1680000 ledger + 625000 ALLOCATED provisional (5000*95000/1000 +
        # 150000 freight) = 2305000.
        assert dealer["committed_exposure_cents"] == 2_305_000, (
            f"ledger plus pipeline provisional; got "
            f"{dealer['committed_exposure_cents']}")
        assert dealer["committed_exposure_cents"] != dealer["ledger_exposure_cents"]


class TestContractActivationGates:

    def test_occ_contract_activate_stale_dealer_version(self):
        """PRD section 2.6: "Activating a dealer contract requires
        `expected_dealer_version` as a non-optional input, carrying the
        caller's last observed `version` of the contract's `Dealer`. Because
        activation supersedes the dealer's overlapping active contract and
        bumps `Dealer.version`, a mismatch is rejected with
        `ERR_STALE_DEALER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_contract_activate_stale_dealer_version
        """
        term = create_terminal(name="T-O2")
        dealer = create_dealer(legal_name="Dealer O2")
        stale_version = dealer["version"]
        c1 = create_dealer_contract(dealer["id"], term["id"])
        c2 = create_dealer_contract(dealer["id"], term["id"],
                                    fixed_price_mc_per_gal=91_000,
                                    volume_committed_gal=50_000)
        resp = api_client.activate_dealer_contract(
            c1["id"], {"expected_dealer_version": stale_version}, CREDIT_MANAGER)
        validate_success(resp, expected_status=200)

        # The first activation bumped Dealer.version; the stale view is dead.
        resp = api_client.activate_dealer_contract(
            c2["id"], {"expected_dealer_version": stale_version}, CREDIT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_DEALER_VERSION)

        c2_after = get_success_data(api_client.get_dealer_contract(c2["id"],
                                                                   CREDIT_MANAGER))
        assert c2_after["status"] == "DRAFT"
        c1_after = get_success_data(api_client.get_dealer_contract(c1["id"],
                                                                   CREDIT_MANAGER))
        assert c1_after["status"] == "ACTIVE"

    def _setup_suspended_dealer_with_draft_contract(self):
        """17000-gal order (committed 1680000, WATCH at 2100000), then PATCH
        the limit to 1600000 -> SUSPENDED, plus a fresh DRAFT contract."""
        ctx = base_order_fixture(name="T-X4", credit_limit_cents=2_100_000)
        create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                     ctx["zone"]["id"], 17_000,
                     dealer_contract_id=ctx["dealer_contract"]["id"])
        api_client.update_dealer(ctx["dealer"]["id"],
                                 {"credit_limit_cents": 1_600_000},
                                 CREDIT_MANAGER)
        contract2 = create_dealer_contract(ctx["dealer"]["id"],
                                           ctx["terminal"]["id"],
                                           pricing_mode="INDEX",
                                           volume_committed_gal=50_000)
        return ctx, contract2

    def test_contract_activate_requires_dealer_not_suspended(self):
        """PRD section 3.3: "Activation by a `CreditManager` is the guarded
        write of section 2.6: the request must carry `expected_dealer_version`
        matching the dealer's current `version`, failing with
        `ERR_STALE_DEALER_VERSION` on a mismatch, and the dealer must not be
        `SUSPENDED`, failing with `ERR_DEALER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_dealer_not_suspended
        """
        ctx, contract2 = self._setup_suspended_dealer_with_draft_contract()
        dealer = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        assert dealer["credit_status"] == "SUSPENDED", "setup check"
        resp = api_client.activate_dealer_contract(
            contract2["id"], {"expected_dealer_version": dealer["version"]},
            CREDIT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_DEALER_SUSPENDED)

        after = get_success_data(api_client.get_dealer_contract(
            contract2["id"], CREDIT_MANAGER))
        assert after["status"] == "DRAFT", \
            "a rejected activation leaves the contract in DRAFT"

    def test_contract_activate_succeeds_after_limit_restored(self):
        """PRD section 3.3: "On success the contract's `status` becomes
        `ACTIVE`, and any other `ACTIVE` contract for the same dealer at the
        same terminal whose window overlaps the new contract's window moves to
        `SUPERSEDED`." — only a `SUSPENDED` dealer is barred; `WATCH` is not.

        Design: Difficulty/cross_entity_state_dependency/contract_activate_requires_dealer_not_suspended
        """
        ctx, contract2 = self._setup_suspended_dealer_with_draft_contract()
        dealer_id = ctx["dealer"]["id"]
        api_client.update_dealer(dealer_id, {"credit_limit_cents": 2_100_000},
                                 CREDIT_MANAGER)
        dealer = get_success_data(api_client.get_dealer(dealer_id,
                                                        CREDIT_MANAGER))
        assert dealer["credit_status"] == "WATCH", \
            "setup check: back below the suspension line, still above 80%"

        resp = api_client.activate_dealer_contract(
            contract2["id"], {"expected_dealer_version": dealer["version"]},
            CREDIT_MANAGER)
        activated = validate_success(resp, expected_status=200)
        assert activated["status"] == "ACTIVE"

        superseded = get_success_data(api_client.get_dealer_contract(
            ctx["dealer_contract"]["id"], CREDIT_MANAGER))
        assert superseded["status"] == "SUPERSEDED", (
            "the overlapping ACTIVE contract at the same dealer+terminal is "
            f"superseded; got {superseded['status']}")


class TestContractCancelCascade:

    def test_dealer_contract_cancel_cascades_orders(self):
        """PRD section 3.3: "Supersession cascades: the superseded contract's
        orders in `REQUESTED` or `ALLOCATED` move to `CANCELLED` (releasing
        their reserved gallons), its `SCHEDULED` orders are first unscheduled —
        truck and hours released — and then cancelled."
        PRD section 3.3: "Cancelling a contract from `DRAFT` or `ACTIVE`
        performs the same order cascade; orders already `LOADED` or `DELIVERED`
        and any open invoices are unaffected."

        Design: Corner/state_machines/dealer_contract_cancel_cascades_orders
        """
        # Clock pinned to Monday so all windows share the current ISO week.
        ctx = base_order_fixture(name="T-M12", clock="2026-08-03T00:00:00Z")
        dealer, contract = ctx["dealer"], ctx["dealer_contract"]
        truck = ctx["trucks"][0]

        order_a = create_order(dealer["id"], ctx["terminal"]["id"],
                               ctx["zone"]["id"], 9_000,
                               dealer_contract_id=contract["id"])
        drive_order_to_delivered(order_a["id"], truck["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        order_b = create_order(dealer["id"], ctx["terminal"]["id"],
                               ctx["zone"]["id"], 5_000,
                               dealer_contract_id=contract["id"])
        order_c = create_order(dealer["id"], ctx["terminal"]["id"],
                               ctx["zone"]["id"], 5_000,
                               dealer_contract_id=contract["id"])
        schedule_order(order_c["id"], truck["id"], "2026-08-04T08:00:00Z",
                       "2026-08-04T10:00:00Z")

        resp = api_client.cancel_dealer_contract(contract["id"], CREDIT_MANAGER)
        cancelled = validate_success(resp, expected_status=200)
        assert cancelled["status"] == "CANCELLED"

        b = get_success_data(api_client.get_delivery_order(order_b["id"],
                                                           CREDIT_MANAGER))
        assert b["fulfillment_status"] == "CANCELLED", \
            "an ALLOCATED order is cancelled with its contract"

        c = get_success_data(api_client.get_delivery_order(order_c["id"],
                                                           CREDIT_MANAGER))
        assert c["fulfillment_status"] == "CANCELLED"
        assert c["truck_id"] is None, "the SCHEDULED order is unscheduled first"

        a = get_success_data(api_client.get_delivery_order(order_a["id"],
                                                           CREDIT_MANAGER))
        assert a["fulfillment_status"] == "DELIVERED", \
            "a DELIVERED order is unaffected by the contract cascade"
        assert a["invoice_status"] == "OPEN"
        assert a["open_balance_cents"] == 960_000

        truck_after = get_success_data(api_client.get_truck(truck["id"],
                                                            DISPATCHER))
        assert truck_after["weekly_committed_minutes"] == 330, (
            "only the DELIVERED order's completed trip (90 + 2*120) remains; "
            f"got {truck_after['weekly_committed_minutes']}")
