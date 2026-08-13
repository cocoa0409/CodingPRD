"""Policy binding gates and commission-entry booking (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    bind_policy,
    create_carrier,
    create_policy,
    create_producer,
    create_product,
    create_schedule,
    deliver_policy_disclosure,
    get_single_entry,
    list_entries,
    setup_bound_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBindRequiresEffectiveSchedule:
    """Difficulty instance: binding is gated on an ACTIVE schedule covering
    (product, tier, effective_date)."""

    def _setup_policy_without_schedule(self):
        producer = create_producer(
            name="Writer X", license_number="LIC-X1", tax_form_on_file=True
        )
        carrier = create_carrier(name="Carrier X", carrier_code="CX")
        product = create_product(carrier["id"], product_code="PX")
        policy = create_policy(
            product["id"],
            producer["id"],
            policy_number="P-X1",
            billing_type="DIRECT_BILL",
            premium_annual_cents=2400000,
            effective_date="2026-08-01",
        )
        deliver_policy_disclosure(policy["id"])
        return producer, carrier, product, policy

    def test_bind_without_schedule_rejected(self):
        """PRD §3.3: "Three preconditions must hold: the writing producer's
        `status` is `ACTIVE`, else `ERR_PRODUCER_NOT_ACTIVE`; an `ACTIVE`
        schedule exists for the policy's product and the writing producer's
        tier whose half-open window covers the policy's `effective_date`,
        else `ERR_NO_EFFECTIVE_SCHEDULE`; and the policy's disclosure has
        reached `DELIVERED` or `ACKNOWLEDGED`, else
        `ERR_DISCLOSURE_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/bind_requires_effective_schedule
        """
        _, _, _, policy = self._setup_policy_without_schedule()
        res = api_client.bind_policy(policy["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_NO_EFFECTIVE_SCHEDULE, expected_status=409)
        after = validate_success(api_client.get_policy(policy["id"], ADMIN), 200)
        assert after["status"] == "QUOTED"

    def test_bind_succeeds_after_schedule_created(self):
        """PRD §3.3: "an `ACTIVE` schedule exists for the policy's product and
        the writing producer's tier whose half-open window covers the policy's
        `effective_date`, else `ERR_NO_EFFECTIVE_SCHEDULE`"
        PRD §3.3: "Binding moves a `QUOTED` policy to `ACTIVE` and is where
        the compliance gates of §2.9 bite."

        Design: Difficulty/cross_entity_state_dependency/bind_requires_effective_schedule
        """
        _, _, product, policy = self._setup_policy_without_schedule()
        validate_error(
            api_client.bind_policy(policy["id"], ADMIN),
            ApiErrorId.ERR_NO_EFFECTIVE_SCHEDULE,
            expected_status=409,
        )
        create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5000,
            override_rate_bps=0,
            advance_months=12,
            effective_from="2026-01-01",
        )
        bound = validate_success(api_client.bind_policy(policy["id"], ADMIN), 200)
        assert bound["status"] == "ACTIVE"
        # 2400000 premium * 5000 bps / 10000 = 1200000 BASE.
        base = get_single_entry(policy["id"], "BASE")
        assert base["amount_cents"] == 1200000
        assert base["status"] == "EXPECTED"


class TestBindComplianceGates:
    def test_bind_with_undelivered_disclosure_rejected(self):
        """PRD §3.3: "the policy's disclosure has reached `DELIVERED` or
        `ACKNOWLEDGED`, else `ERR_DISCLOSURE_REQUIRED`."

        Design: Corner/validations/bind_with_undelivered_disclosure_returns_409
        """
        producer = create_producer(name="Disc U", license_number="LIC-V6V")
        carrier = create_carrier(name="Carrier V6V", carrier_code="CV6V")
        product = create_product(carrier["id"], product_code="PV6V")
        create_schedule(product["id"], commission_rate_bps=5000)
        policy = create_policy(
            product["id"],
            producer["id"],
            policy_number="P-V6V",
            premium_annual_cents=2400000,
        )
        res = api_client.bind_policy(policy["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DISCLOSURE_REQUIRED, expected_status=409)
        after = validate_success(api_client.get_policy(policy["id"], ADMIN), 200)
        assert after["status"] == "QUOTED"

    def test_bind_by_terminated_producer_rejected(self):
        """PRD §3.3: "Three preconditions must hold: the writing producer's
        `status` is `ACTIVE`, else `ERR_PRODUCER_NOT_ACTIVE`".

        Design: Corner/validations/bind_by_terminated_producer_returns_409
        """
        producer = create_producer(name="Term W", license_number="LIC-V7V")
        validate_success(api_client.terminate_producer(producer["id"], ADMIN), 200)
        carrier = create_carrier(name="Carrier V7V", carrier_code="CV7V")
        product = create_product(carrier["id"], product_code="PV7V")
        create_schedule(product["id"], commission_rate_bps=5000)
        policy = create_policy(
            product["id"],
            producer["id"],
            policy_number="P-V7V",
            premium_annual_cents=2400000,
        )
        deliver_policy_disclosure(policy["id"])
        res = api_client.bind_policy(policy["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_PRODUCER_NOT_ACTIVE, expected_status=409)
        after = validate_success(api_client.get_policy(policy["id"], ADMIN), 200)
        assert after["status"] == "QUOTED"

    def test_second_bind_rejected(self):
        """PRD §3.3: "Binding moves a `QUOTED` policy to `ACTIVE` and is where
        the compliance gates of §2.9 bite."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`."

        Design: Corner/state_machines/second_bind_returns_409
        """
        bundle = setup_bound_policy(policy_number="P-S2C")
        res = api_client.bind_policy(bundle["policy"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestBookingVariants:
    """Difficulty instance: identical premium and rate book differently purely
    from the schedule's advance_months variant selection."""

    def _setup_dual_variant(self):
        producer = create_producer(
            name="Writer A",
            license_number="LIC-A1",
            tier="GOLD",
            tax_form_on_file=True,
        )
        carrier = create_carrier(name="Carrier One", carrier_code="C1")
        product_a = create_product(carrier["id"], product_code="PA")
        product_b = create_product(carrier["id"], product_code="PB")
        create_schedule(
            product_a["id"],
            tier="GOLD",
            commission_rate_bps=5500,
            override_rate_bps=0,
            advance_months=12,
            effective_from="2026-01-01",
        )
        create_schedule(
            product_b["id"],
            tier="GOLD",
            commission_rate_bps=5500,
            override_rate_bps=0,
            advance_months=6,
            effective_from="2026-01-01",
        )
        policy_a = create_policy(
            product_a["id"],
            producer["id"],
            policy_number="P-A1",
            billing_type="DIRECT_BILL",
            premium_annual_cents=12000000,
            effective_date="2026-08-01",
        )
        policy_b = create_policy(
            product_b["id"],
            producer["id"],
            policy_number="P-B1",
            billing_type="DIRECT_BILL",
            premium_annual_cents=12000000,
            effective_date="2026-08-01",
        )
        deliver_policy_disclosure(policy_a["id"])
        deliver_policy_disclosure(policy_b["id"])
        bind_policy(policy_a["id"])
        bind_policy(policy_b["id"])
        return policy_a, policy_b

    def test_annualized_full_books_entire_first_year(self):
        """PRD §3.3: "With the `ANNUALIZED_FULL` variant (the schedule's
        `advance_months` is exactly 12), the entry books that full amount at
        bind."
        PRD §3.3: "In both variants the entry's
        `annualized_full_amount_cents` records the full first-year amount;
        under `ANNUALIZED_FULL` it equals the booked `amount_cents`, and
        under `ADVANCE_LIMITED` it is the informational un-discounted figure
        used later by the cancellation math of §3.6."

        Design: Difficulty/dual_variant_calc/advance_limited_vs_annualized_booking
        """
        policy_a, _ = self._setup_dual_variant()
        entry = get_single_entry(policy_a["id"], "BASE")
        # 12000000 * 5500 bps / 10000 = 6600000 full first-year amount.
        assert entry["amount_cents"] == 6600000
        assert entry["variant"] == "ANNUALIZED_FULL"
        assert entry["annualized_full_amount_cents"] == 6600000
        assert entry["status"] == "EXPECTED"

    def test_advance_limited_books_partial_first_year(self):
        """PRD §3.3: "With the `ADVANCE_LIMITED` variant (`advance_months`
        below 12), the entry books the full first-year amount multiplied by
        `advance_months` and divided by twelve, rounded half-up — so
        identical policy data yields a smaller booked amount."
        PRD §3.3: "In both variants the entry's
        `annualized_full_amount_cents` records the full first-year amount;
        under `ANNUALIZED_FULL` it equals the booked `amount_cents`, and
        under `ADVANCE_LIMITED` it is the informational un-discounted figure
        used later by the cancellation math of §3.6."

        Design: Difficulty/dual_variant_calc/advance_limited_vs_annualized_booking
        """
        policy_a, policy_b = self._setup_dual_variant()
        entry_a = get_single_entry(policy_a["id"], "BASE")
        entry_b = get_single_entry(policy_b["id"], "BASE")
        # Identical premium and rate: 6600000 full; 6/12 advance = 3300000.
        assert entry_b["amount_cents"] == 3300000
        assert entry_b["variant"] == "ADVANCE_LIMITED"
        assert entry_b["annualized_full_amount_cents"] == 6600000
        assert entry_a["amount_cents"] != entry_b["amount_cents"]


class TestOverrideEntries:
    def _setup_override_book(self, *, override_rate_bps, terminate_mid=False):
        grand = create_producer(name="Grand G", license_number="LIC-C5G")
        mid = create_producer(
            name="Mid M", license_number="LIC-C5M", upline_producer_id=grand["id"]
        )
        writer = create_producer(
            name="Writer W",
            license_number="LIC-C5W",
            tier="GOLD",
            upline_producer_id=mid["id"],
        )
        if terminate_mid:
            validate_success(api_client.terminate_producer(mid["id"], ADMIN), 200)
        carrier = create_carrier(name="Carrier O", carrier_code="CO")
        product = create_product(carrier["id"], product_code="PO")
        create_schedule(
            product["id"],
            tier="GOLD",
            commission_rate_bps=5500,
            override_rate_bps=override_rate_bps,
            advance_months=12,
            effective_from="2026-01-01",
        )
        policy = create_policy(
            product["id"],
            writer["id"],
            billing_type="DIRECT_BILL",
            premium_annual_cents=12000000,
            effective_date="2026-08-01",
        )
        deliver_policy_disclosure(policy["id"])
        bind_policy(policy["id"])
        return {
            "grand": grand,
            "mid": mid,
            "writer": writer,
            "carrier": carrier,
            "product": product,
            "policy": policy,
        }

    def test_override_cap_binds_over_raw_amount(self):
        """PRD §3.3: "Otherwise the raw override is the policy's
        `premium_annual_cents` multiplied by `override_rate_bps` and divided
        by 10000, rounded half-up, and the booked override is the smaller of
        that raw figure and a cap equal to twenty-five percent of the base
        entry's booked `amount_cents`, the cap itself rounded half-up."

        Design: Difficulty/combinatorial_formula/override_cap_binding
        """
        bundle = self._setup_override_book(override_rate_bps=1500)
        override = get_single_entry(bundle["policy"]["id"], "OVERRIDE")
        # raw = 12000000 * 1500 / 10000 = 1800000; cap = 25% of 6600000 =
        # 1650000; the cap binds.
        assert override["amount_cents"] == 1650000

    def test_override_paid_to_nearest_active_upline(self):
        """PRD §3.3: "Walking the writing producer's upline chain via
        `upline_producer_id`, the recipient is the first ancestor whose
        `status` is `ACTIVE` at bind time; ancestors in `SUSPENDED` or
        `TERMINATED` are skipped, and when no active ancestor exists — or the
        schedule's `override_rate_bps` is 0 — no override entry is created at
        all."

        Design: Difficulty/combinatorial_formula/override_cap_binding
        """
        bundle = self._setup_override_book(override_rate_bps=1500)
        base = get_single_entry(bundle["policy"]["id"], "BASE")
        override = get_single_entry(bundle["policy"]["id"], "OVERRIDE")
        assert base["amount_cents"] == 6600000
        assert override["producer_id"] == bundle["mid"]["id"], (
            "the immediate upline is ACTIVE, so it receives the override"
        )
        assert override["status"] == "EXPECTED"

    def test_override_skips_terminated_ancestor(self):
        """PRD §3.3: "Walking the writing producer's upline chain via
        `upline_producer_id`, the recipient is the first ancestor whose
        `status` is `ACTIVE` at bind time; ancestors in `SUSPENDED` or
        `TERMINATED` are skipped, and when no active ancestor exists — or the
        schedule's `override_rate_bps` is 0 — no override entry is created at
        all."

        Design: Corner/calculations/override_skips_terminated_ancestor
        """
        bundle = self._setup_override_book(
            override_rate_bps=1000, terminate_mid=True
        )
        overrides = list_entries(
            policy_id=bundle["policy"]["id"], entry_type="OVERRIDE"
        )
        assert len(overrides) == 1
        # raw = 12000000 * 1000 / 10000 = 1200000, below the 1650000 cap.
        assert overrides[0]["amount_cents"] == 1200000
        assert overrides[0]["producer_id"] == bundle["grand"]["id"], (
            "the TERMINATED mid-level upline is skipped in favor of the "
            "nearest ACTIVE ancestor"
        )


class TestDirectBillBind:
    def test_direct_bill_creates_no_invoice(self):
        """PRD §3.3: "Binding an `AGENCY_BILL` policy creates its
        **PremiumInvoice** in `OPEN` status, with `amount_cents` equal to the
        policy's `premium_annual_cents` and a `due_date` exactly thirty
        calendar days after the policy's `effective_date`. Binding a
        `DIRECT_BILL` policy creates no invoice at all."
        PRD §2.8: "A `DIRECT_BILL` policy is billed by the carrier directly
        to the insured; its money never enters the agency's trust, no premium
        invoice is ever created for it, and it never participates in the
        delinquency sweep."

        Design: Corner/calculations/direct_bill_bind_creates_no_invoice
        """
        bundle = setup_bound_policy(billing_type="DIRECT_BILL")
        data, meta = validate_paginated(
            api_client.list_policy_invoices(bundle["policy"]["id"], ADMIN)
        )
        assert data == []
        assert meta["total_count"] == 0
        carrier = validate_success(
            api_client.get_carrier(bundle["carrier"]["id"], ADMIN), 200
        )
        assert carrier["trust_balance_cents"] == 0
