"""Renewal loop and cap, optimistic concurrency, and PREPAY payment gating."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    check_in_order,
    create_account,
    create_order,
    create_publisher,
    create_rental_set,
    confirm_order,
    create_work,
    fetch_order,
    record_prepayment,
    renew_order,
    reserve_order,
    setup_order_on_loan,
    validate_error,
    validate_success,
)

from test_helpers import BILLING, CLERK


class TestRenewalCycleAndCap:
    def _ws_on_loan(self):
        return setup_order_on_loan(
            order_copies=5, publisher_name="Pub Five", work_title="Octet",
            catalog_number="P5-001", set_code="SET-301",
            account_overrides={"account_name": "Westfield Academy",
                               "credit_tier": "STANDARD", "credit_limit_cents": 0},
        )

    def test_first_and_second_renewal_extend_due_and_fee(self, api):
        """PRD §3.5: "A successful renewal extends `due_date` by exactly 30 days,
        recomputes `loan_periods`, increments `renewal_count`, re-estimates the
        fee by the provisional formula".

        Design: Difficulty/non_linear_state_machine/rental_order_renewal_cycle_and_cap
        """
        ws = self._ws_on_loan()
        order = ws["order"]

        first = renew_order(order["id"], order["version"])
        # due 2026-09-04 + 30d -> 2026-10-04; [08-05, 10-04) is 2 periods.
        assert str(first["due_date"]).startswith("2026-10-04")
        assert first["renewal_count"] == 1
        assert first["estimated_fee_cents"] == 100000

        second = renew_order(order["id"], first["version"])
        # 2026-10-04 + 30d -> 2026-11-03; 3 periods at 5 copies x 10000.
        assert str(second["due_date"]).startswith("2026-11-03")
        assert second["renewal_count"] == 2
        assert second["estimated_fee_cents"] == 150000

    def test_third_renewal_rejected_at_cap(self, api):
        """PRD §3.5: "the renewal cap admits at most two renewals per order, so a
        `renewal_count` already at 2 is rejected with `ERR_RENEWAL_CAP_REACHED`".

        Design: Difficulty/non_linear_state_machine/rental_order_renewal_cycle_and_cap
        """
        ws = self._ws_on_loan()
        order = ws["order"]
        first = renew_order(order["id"], order["version"])
        second = renew_order(order["id"], first["version"])

        resp = api.renew_rental_order(order["id"], second["version"], CLERK)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_CAP_REACHED)
        assert fetch_order(order["id"])["renewal_count"] == 2


class TestRenewalOverlap:
    def test_renewal_overlap_conflict_with_other_order(self, api):
        """PRD §3.5: "the extended window is re-checked for overlap against other
        orders' live lines on the same set — an order's own lines are excluded
        from the blocker set, since an order never blocks itself — and a collision
        is `ERR_RENEWAL_CONFLICT`".

        Design: Corner/validations/renewal_overlap_conflict_with_other_order
        """
        publisher = create_publisher("RC Pub")
        work = create_work(publisher["id"], title="RC Work", catalog_number="RC-1")
        rental_set = create_rental_set(work["id"], set_code="RC-SET", copy_count=1,
                                       replacement_value_cents=8000)
        account = create_account("RC Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(order["id"])
        validate_success(api.dispatch_rental_order(order["id"], CLERK))
        on_loan = confirm_order(order["id"], account["id"])
        # A different reservation holds the single copy later in the season.
        other = create_order(account["id"], rental_set["id"], copies=1,
                             checkout_date="2026-09-15", due_date="2026-10-15")
        reserve_order(other["id"])

        # Extending to 2026-10-04 would collide with the other order's window.
        resp = api.renew_rental_order(order["id"], on_loan["version"], CLERK)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_CONFLICT)
        after = fetch_order(order["id"])
        assert str(after["due_date"]).startswith("2026-09-04")
        assert after["renewal_count"] == 0


class TestRenewalOcc:
    def test_error_stale_version_on_renew(self, api):
        """PRD §2.7: "Renewing a rental order requires a non-optional
        `expected_rental_order_version` carrying the client's last observed
        `version` of that order; if the order's current `version` has advanced
        since that observation — because another writer renewed, checked in,
        disputed, or otherwise mutated the same order — the renewal is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_renew
        """
        ws = setup_order_on_loan(
            order_copies=5, publisher_name="SV Pub", work_title="SV Work",
            catalog_number="SV-1", set_code="SV-SET",
            account_overrides={"account_name": "SV Acct", "credit_tier": "STANDARD",
                               "credit_limit_cents": 0},
        )
        order = ws["order"]
        observed = order["version"]

        # One version behind the client's view of the order.
        resp = api.renew_rental_order(order["id"], observed - 1, CLERK)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        renewed = renew_order(order["id"], observed)
        assert renewed["version"] == observed + 1
        assert renewed["renewal_count"] == 1


class TestPrepayFlows:
    def test_prepay_dispatch_without_prepayment_rejected_then_succeeds(self, api):
        """PRD §3.5: "For `PREPAY` accounts, dispatch additionally requires
        `prepayment_cents` to cover the full `estimated_fee_cents`, else
        `ERR_PREPAYMENT_REQUIRED` (HTTP 402)."
        PRD §3.5: "A `BillingManager` records prepayments against an order: each
        adds its `amount_cents` to `prepayment_cents` and increments the order's
        `version`."

        Design: Corner/validations/prepay_dispatch_without_prepayment_rejected_then_succeeds
        """
        publisher = create_publisher("PP Pub")
        work = create_work(publisher["id"], title="PP Work", catalog_number="PP-1")
        rental_set = create_rental_set(work["id"], set_code="PP-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("PP Player", account_kind="INDIVIDUAL",
                                 credit_tier="PREPAY")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1)
        reserve_order(order["id"])

        resp = api.dispatch_rental_order(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PREPAYMENT_REQUIRED)

        prepaid = record_prepayment(order["id"], 10000)
        assert prepaid["prepayment_cents"] == 10000
        dispatched = validate_success(api.dispatch_rental_order(order["id"], CLERK))
        assert dispatched["status"] == "DISPATCHED"

    def test_prepay_settle_shortfall_then_topup(self, api):
        """PRD §3.6: "For `PREPAY` accounts, `final_fee_cents` must be covered by
        `prepayment_cents` plus whatever damage has been collected, or the settle
        request must carry a top-up via `topup_cents`; otherwise the settle is
        rejected with `ERR_PREPAYMENT_SHORTFALL` (HTTP 402)."

        Design: Corner/validations/prepay_settle_shortfall_then_topup
        """
        publisher = create_publisher("PS Pub")
        work = create_work(publisher["id"], title="PS Work", catalog_number="PS-1")
        rental_set = create_rental_set(work["id"], set_code="PS-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("PS Player", account_kind="INDIVIDUAL",
                                 credit_tier="PREPAY")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1)
        reserve_order(order["id"])
        record_prepayment(order["id"], 10000)
        dispatched = validate_success(api.dispatch_rental_order(order["id"], CLERK))
        assert dispatched["status"] == "DISPATCHED"
        confirm_order(order["id"], account["id"])

        # Five days late: daily_base rhu(10000/30)=333; 5 x 33 x 1 = 165 late.
        advance_clock("2026-09-09T00:00:00Z")
        returned = check_in_order(order["id"], "A")
        assert returned["final_fee_cents"] == 10165

        # 10165 > 10000 prepaid: the shortfall blocks settlement.
        resp = api.settle_rental_order(order["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_PREPAYMENT_SHORTFALL)

        settled = validate_success(
            api.settle_rental_order(order["id"], BILLING, topup_cents=200)
        )
        assert settled["status"] == "SETTLED"


class TestStateVersusFiscalPrecedence:
    def _setup_draft_prepay_order(self, api):
        publisher = create_publisher("Pub Nine")
        work = create_work(publisher["id"], title="Airs", catalog_number="P9-001")
        rental_set = create_rental_set(work["id"], set_code="SET-701", copy_count=10,
                                       replacement_value_cents=80000)
        account = create_account("Indie Player", account_kind="INDIVIDUAL",
                                 credit_tier="PREPAY")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=2)
        return account, order

    def test_dispatch_draft_prepay_order_surfaces_invalid_state(self, api):
        """PRD §2.9: "Every write request is evaluated against a fixed pipeline of
        validation tiers, and an earlier tier's failure masks every later tier —
        the surfaced error is always the earliest applicable one. The order is:
        (1) the user-context header check of §2.1; (2) role authorization; (3)
        path-resource existence per §2.8; (4) state-transition admissibility,
        where the target must sit in a from-state permitting the requested
        transition, else `ERR_INVALID_STATE`; (5) segregation of duties ...".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_dispatch
        """
        _account, order = self._setup_draft_prepay_order(api)
        # The order violates tier (4) state admissibility — it is DRAFT, not
        # RESERVED — AND tier (15) prepayment sufficiency: tier (4) must win.
        resp = api.dispatch_rental_order(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_dispatch_leaves_order_in_draft(self, api):
        """PRD §3.5: "Dispatch — a `LibraryClerk` moving `RESERVED` →
        `DISPATCHED` — re-verifies the gates: the order must currently be
        `RESERVED` (`ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_dispatch
        """
        _account, order = self._setup_draft_prepay_order(api)
        validate_error(
            api.dispatch_rental_order(order["id"], CLERK),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = fetch_order(order["id"])
        assert after["status"] == "DRAFT", "a rejected dispatch must not move the order"
        assert after["version"] == order["version"], (
            "a rejected dispatch must not mutate the order's version"
        )
