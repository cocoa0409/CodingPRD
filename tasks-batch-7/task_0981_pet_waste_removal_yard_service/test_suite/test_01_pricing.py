"""Pricing engine tests: monthly fee, per-visit charge, addon bundle, vacation credit rounding.

Covers design instances from queue A (difficulty) and queue B (corner/calculations).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    create_customer_payload,
    create_yard_payload,
    create_access_profile_payload,
    create_subscription_plan_payload,
    create_service_addon_payload,
    create_subscription_payload,
    create_visit_payload,
    create_vacation_window_payload,
    create_invoice_payload,
    setup_active_subscription,
    create_customer,
    create_yard,
    create_verified_access_profile,
    create_subscription_plan,
    create_service_addon,
    create_invoice,
    create_scheduled_visit,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Difficulty / dual_variant_calc / monthly_fee_forward_looking_vs_reconciled_divergence
# =========================================================================

class TestMonthlyFeeForwardLookingVsReconciled:
    """FORWARD_LOOKING snapshot is pinned at activate; RECONCILED at invoice finalize."""

    def _setup(self):
        """Mirror the design: yard sqft 4000, pet_count 2 -> fee 25000; then pet_count -> 5."""
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer(full_name="A", email="a@x.com")
        yard = create_yard(
            customer["id"],
            address_line1="1 Main",
            yard_size_sqft=4000,
            pet_count=2,
        )
        create_verified_access_profile(yard["id"])
        plan = create_subscription_plan(
            plan_code="W1",
            visit_frequency="WEEKLY",
            base_monthly_fee_cents=20000,
            yard_tier_thresholds=[2000, 5000],
            yard_tier_surcharges_cents=[0, 3000, 6000],
            pet_tier_thresholds=[1, 3],
            pet_tier_surcharges_cents=[0, 2000, 5000],
        )
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        act = api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        subscription = get_success_data(act)
        # Mutate the yard: pet_count 2 -> 5. Under FORWARD_LOOKING, the
        # snapshot should recompute to 20000+3000+5000=28000. Under a pinned
        # snapshot interpretation it would remain 25000. The PRD says the
        # FORWARD_LOOKING variant runs "on any yard change while the
        # subscription is ACTIVE", so the recompute happens and the snapshot
        # becomes 28000. The RECONCILED variant would also re-read at finalize.
        api_client.update_yard(yard["id"], {"pet_count": 5}, OPS)
        return customer, yard, plan, subscription

    def test_forward_looking_snapshot_recomputed_on_yard_change(self, api):
        """PRD §3.4: "The FORWARD_LOOKING variant runs at activation, at resume,
        on any yard change while the subscription is `ACTIVE`, and whenever a
        staged plan change becomes effective. It uses the yard's current
        `yard_size_sqft` and `pet_count` at computation time and stores the
        result on `monthly_fee_cents_snapshot`."

        Design: Difficulty/dual_variant_calc/monthly_fee_forward_looking_vs_reconciled_divergence
        """
        customer, yard, plan, subscription = self._setup()
        resp = api.get_subscription(subscription["id"], make_customer_headers(customer["id"]))
        data = validate_success(resp)
        # After pet_count 2->5 with plan tiers [1,3]->[0,2000,5000]:
        # subtotal = 20000 + 3000 + 5000 = 28000
        assert data["monthly_fee_cents_snapshot"] == 28000, (
            f"Expected FORWARD_LOOKING recompute to 28000, got {data['monthly_fee_cents_snapshot']}"
        )

    def test_yard_state_after_update_reflects_new_pet_count(self, api):
        """PRD §3.1: "Yard attributes are not frozen at creation. An
        `OperationsManager` or the owning `Customer` may update `yard_size_sqft`,
        `pet_count`, `is_multifamily_common_area`, `hoa_account_code`, or
        `service_region_code`."

        Design: Difficulty/dual_variant_calc/monthly_fee_forward_looking_vs_reconciled_divergence
        """
        customer, yard, plan, subscription = self._setup()
        resp = api.get_yard(yard["id"], OPS)
        data = validate_success(resp)
        assert data["pet_count"] == 5
        # The subscription snapshot must have been refreshed via FORWARD_LOOKING
        sub_resp = api.get_subscription(subscription["id"], OPS)
        sub_data = validate_success(sub_resp)
        assert sub_data["monthly_fee_cents_snapshot"] == 28000


# =========================================================================
# Difficulty / dual_variant_calc / per_visit_charge_provisional_vs_final_divergence
# =========================================================================

class TestPerVisitChargeProvisionalVsFinal:
    """PROVISIONAL at schedule time; FINAL at completion (recomputed on current addons)
    or zero on SKIPPED/MISSED."""

    def _setup_completed_visit(self):
        """Customer B path: plan base=17320 WEEKLY no tiers, no addons; visit completes.

        expected base_per_visit = round_half_up(17320 / 4.33) = round_half_up(4000.0) = 4000
        (17320/4.33 = 3999.999... actually 4000.00, rounds to 4000)
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            plan_overrides={
                "plan_code": "W_BASE",
                "visit_frequency": "WEEKLY",
                "base_monthly_fee_cents": 17320,
                "yard_tier_thresholds": [2000],
                "yard_tier_surcharges_cents": [0, 3000],
                "pet_tier_thresholds": [2],
                "pet_tier_surcharges_cents": [0, 2000],
            },
            yard_overrides={"yard_size_sqft": 1500, "pet_count": 1},
            clock_iso="2026-05-01T00:00:00Z",
        )
        # The yard is below both tier thresholds, so snapshot = 17320.
        assert subscription["monthly_fee_cents_snapshot"] == 17320
        technician_resp = api_client.create_technician(
            {"full_name": "Tech1", "employee_code": "T001"}, OPS
        )
        technician = get_success_data(technician_resp)
        route_resp = api_client.create_service_route(
            {
                "route_code": "R-2026-05-04",
                "service_date": "2026-05-04T00:00:00Z",
                "service_region_code": "R1",
                "assigned_technician_id": technician["id"],
                "max_visit_capacity": 10,
            },
            OPS,
        )
        route = get_success_data(route_resp)
        visit_resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-04T00:00:00Z",
                "scheduled_window_start": "2026-05-04T09:00:00Z",
                "scheduled_window_end": "2026-05-04T12:00:00Z",
                "service_route_id": route["id"],
                "addon_ids": [],
            },
            OPS,
        )
        visit = get_success_data(visit_resp)
        return customer, subscription, technician, route, visit

    def test_provisional_charge_computed_at_schedule(self, api):
        """PRD §3.4: "the base per-visit amount is the subscription's
        `monthly_fee_cents_snapshot` divided by that average, rounded half-up
        to whole cents."

        Design: Difficulty/dual_variant_calc/per_visit_charge_provisional_vs_final_divergence
        """
        customer, subscription, technician, route, visit = self._setup_completed_visit()
        # 17320 / 4.33 = 3999.9999... rounds half-up to 4000
        assert visit["provisional_visit_charge_cents"] == 4000, (
            f"Expected provisional 4000, got {visit['provisional_visit_charge_cents']}"
        )
        assert visit["status"] == "SCHEDULED"

    def test_final_charge_computed_on_completion(self, api):
        """PRD §3.4: "For a `COMPLETED` visit, the charge is recomputed using
        the add-ons currently attached to the visit, so add-ons added after
        scheduling are included."

        Design: Difficulty/dual_variant_calc/per_visit_charge_provisional_vs_final_divergence
        """
        from test_helpers import make_technician_headers

        customer, subscription, technician, route, visit = self._setup_completed_visit()
        api_client.publish_service_route(route["id"], OPS)
        api_client.set_current_utc("2026-05-04T08:00:00Z", OPS)
        api_client.start_service_route(route["id"], make_technician_headers(technician["id"]))
        api_client.depart_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        complete_resp = api_client.complete_visit(
            visit["id"], make_technician_headers(technician["id"])
        )
        completed = validate_success(complete_resp)
        assert completed["status"] == "COMPLETED"
        # No addons attached, so FINAL == PROVISIONAL == 4000
        assert completed["final_visit_charge_cents"] == 4000


# =========================================================================
# Difficulty / combinatorial_formula / monthly_fee_tiered_mode_a_multi_input_nonlinear
# =========================================================================

class TestMonthlyFeeTieredMultifamily:
    """4-input nonlinear formula: base + yard tier + pet tier, then multifamily bp multiplier."""

    def _setup(self):
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer(full_name="MM", email="mm@x.com")
        yard = create_yard(
            customer["id"],
            address_line1="100 Park",
            yard_size_sqft=9000,
            pet_count=6,
            is_multifamily_common_area=True,
            hoa_account_code="HOA-X",
            service_region_code="R2",
        )
        create_verified_access_profile(
            yard["id"], gate_access_code="0000", pet_on_premises=False
        )
        plan = create_subscription_plan(
            plan_code="MM1",
            visit_frequency="DAILY",
            applies_to_multifamily=True,
            base_monthly_fee_cents=50000,
            yard_tier_thresholds=[3000, 8000],
            yard_tier_surcharges_cents=[0, 8000, 15000],
            pet_tier_thresholds=[2, 5],
            pet_tier_surcharges_cents=[0, 5000, 12000],
            multifamily_multiplier_bp=12500,
        )
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        return customer, yard, plan, subscription

    def test_multifamily_tiered_fee_at_activate(self, api):
        """PRD §3.4: "If the yard's `is_multifamily_common_area` is true, the fee
        is the subtotal multiplied by the plan's `multifamily_multiplier_bp` and
        divided by 10000 — where 10000 basis points represents a 1.00×
        multiplier — rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/monthly_fee_tiered_mode_a_multi_input_nonlinear
        """
        customer, yard, plan, subscription = self._setup()
        act = api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        data = validate_success(act)
        # sqft=9000 -> yard tier idx 2 -> surcharge 15000
        # pet_count=6 -> pet tier idx 2 -> surcharge 12000
        # subtotal = 50000+15000+12000 = 77000
        # fee = round_half_up(77000 * 12500 / 10000) = 96250
        assert data["monthly_fee_cents_snapshot"] == 96250, (
            f"Expected 96250, got {data['monthly_fee_cents_snapshot']}"
        )

    def test_multifamily_fee_visible_on_get_after_activate(self, api):
        """PRD §3.4: "The subtotal is the base plus the yard surcharge plus the
        pet surcharge."

        Design: Difficulty/combinatorial_formula/monthly_fee_tiered_mode_a_multi_input_nonlinear
        """
        customer, yard, plan, subscription = self._setup()
        api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        get_resp = api_client.get_subscription(subscription["id"], OPS)
        data = validate_success(get_resp)
        assert data["status"] == "ACTIVE"
        assert data["monthly_fee_cents_snapshot"] == 96250


# =========================================================================
# Difficulty / combinatorial_formula / vacation_credit_rounding_mode_b_per_line_not_aggregate
# =========================================================================

class TestVacationCreditRoundPerLine:
    """Per-line rounding: round_half_up(10000/4.33) = 2309 per visit, 3 visits total 6927."""

    def _setup(self):
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer(full_name="C", email="c@x.com")
        yard = create_yard(customer["id"], yard_size_sqft=1500, pet_count=1)
        create_verified_access_profile(yard["id"], gate_access_code="1")
        plan = create_subscription_plan(
            plan_code="WC",
            visit_frequency="WEEKLY",
            base_monthly_fee_cents=10000,
        )
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        act = api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        subscription = get_success_data(act)
        visits = []
        for day in ("2026-05-05", "2026-05-06", "2026-05-07"):
            v_resp = api_client.create_visit(
                {
                    "subscription_id": subscription["id"],
                    "scheduled_date": f"{day}T00:00:00Z",
                    "scheduled_window_start": f"{day}T09:00:00Z",
                    "scheduled_window_end": f"{day}T12:00:00Z",
                },
                OPS,
            )
            visits.append(get_success_data(v_resp))
        invoice = create_invoice(customer["id"])
        vw_resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-05T00:00:00Z",
                "end_date": "2026-05-07T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        window = get_success_data(vw_resp)
        return customer, subscription, visits, invoice, window

    def test_per_line_credit_value_and_aggregate_sum(self, api):
        """PRD §3.6: "The credit per visit is the subscription's
        `monthly_fee_cents_snapshot` divided by the average visits per month
        for the plan's `visit_frequency` (the same 4.33 / 2.17 / 8.67 / 30
        mapping as the per-visit charge), rounded half-up to whole cents per
        line — this per-line rounding happens before any aggregation, never
        as a sum-then-round."

        Design: Difficulty/combinatorial_formula/vacation_credit_rounding_mode_b_per_line_not_aggregate
        """
        customer, subscription, visits, invoice, window = self._setup()
        api_client.set_current_utc("2026-05-05T00:00:01Z", OPS)
        api_client.run_vacation_window_applier(OPS)
        items_resp = api_client.get_invoice_line_items(invoice["id"], BILLING)
        items = validate_success(items_resp)
        credit_lines = [li for li in items if li["line_type"] == "VACATION_CREDIT"]
        assert len(credit_lines) == 3, f"Expected 3 VACATION_CREDIT lines, got {len(credit_lines)}"
        for line in credit_lines:
            assert line["unit_price_cents"] == -2309, (
                f"Expected per-line -2309 (round_half_up(10000/4.33)), got {line['unit_price_cents']}"
            )
            assert line["quantity"] == 1
            assert line["line_total_cents"] == -2309
        total = sum(line["line_total_cents"] for line in credit_lines)
        assert total == -6927, f"Per-line sum must be -6927; got {total}"

    def test_each_covered_visit_skipped_with_vacation_source(self, api):
        """PRD §3.6: "every visit on the subscription whose `scheduled_date`
        falls within the closed interval `[start_date, end_date]` and whose
        status is currently `SCHEDULED` transitions to `SKIPPED` with
        `skip_source` set to `VACATION`"

        Design: Difficulty/combinatorial_formula/vacation_credit_rounding_mode_b_per_line_not_aggregate
        """
        customer, subscription, visits, invoice, window = self._setup()
        api_client.set_current_utc("2026-05-05T00:00:01Z", OPS)
        api_client.run_vacation_window_applier(OPS)
        for v in visits:
            resp = api_client.get_visit(v["id"], OPS)
            data = validate_success(resp)
            assert data["status"] == "SKIPPED"
            assert data["skip_source"] == "VACATION"


# =========================================================================
# Corner / calculations / addon_bundle_discount_applied_when_both_present
# Corner / calculations / addon_no_bundle_when_only_one_present
# =========================================================================

class TestAddonBundlePricing:
    def _setup_with_addons(self, include_deodorize: bool):
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer()
        yard = create_yard(customer["id"])
        create_verified_access_profile(yard["id"])
        plan = create_subscription_plan(
            plan_code=f"BD-{_rand()}",
            visit_frequency="WEEKLY",
            base_monthly_fee_cents=10000,
        )
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        act = api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        subscription = get_success_data(act)
        sanitize = create_service_addon(
            addon_code="SANITIZE", display_name="San", price_cents_per_visit=1500
        )
        addon_ids = [sanitize["id"]]
        if include_deodorize:
            deodorize = create_service_addon(
                addon_code="DEODORIZE", display_name="Deo", price_cents_per_visit=1200
            )
            addon_ids.append(deodorize["id"])
        return subscription, addon_ids

    def test_bundle_discount_applied_when_both_present(self, api):
        """PRD §3.4: "when both `SANITIZE` and `DEODORIZE` are present on the
        same visit, the sum of those two add-on prices is discounted by 1500
        basis points — that is, multiplied by 8500 and divided by 10000,
        rounded half-up once on the bundle pair — before being added to any
        other add-on prices."

        Design: Corner/calculations/addon_bundle_discount_applied_when_both_present
        """
        subscription, addon_ids = self._setup_with_addons(include_deodorize=True)
        visit_resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T09:00:00Z",
                "scheduled_window_end": "2026-05-08T10:00:00Z",
                "addon_ids": addon_ids,
            },
            OPS,
        )
        visit = validate_success(visit_resp, expected_status=201)
        # base = round_half_up(10000/4.33) = 2309
        # bundle_pair = round_half_up((1500+1200) * 8500 / 10000) = round_half_up(2295) = 2295
        # provisional = 2309 + 2295 = 4604
        assert visit["provisional_visit_charge_cents"] == 4604, (
            f"Expected 4604 (2309 base + 2295 bundled), got {visit['provisional_visit_charge_cents']}"
        )

    def test_no_bundle_when_only_one_addon(self, api):
        """PRD §3.4: "the add-on total is computed by resolving each entry of
        `addon_ids` against `ServiceAddon` rows whose `addon_status` is
        `ACTIVE` and summing their `price_cents_per_visit`, with one bundle
        rule: when both `SANITIZE` and `DEODORIZE` are present on the same
        visit, the sum of those two add-on prices is discounted"

        Design: Corner/calculations/addon_no_bundle_when_only_one_present
        """
        subscription, addon_ids = self._setup_with_addons(include_deodorize=False)
        visit_resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T09:00:00Z",
                "scheduled_window_end": "2026-05-08T10:00:00Z",
                "addon_ids": addon_ids,
            },
            OPS,
        )
        visit = validate_success(visit_resp, expected_status=201)
        # base 2309 + addon 1500 = 3809 (no bundle discount with only one of the pair)
        assert visit["provisional_visit_charge_cents"] == 3809


def _rand():
    """Generate a short unique suffix for plan_code collisions."""
    import uuid

    return uuid.uuid4().hex[:6].upper()
