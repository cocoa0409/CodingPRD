"""Multi-input formulas with pinned rounding order and worked constants
(PRD 3.5 dosing, PRD 3.9 invoice composition, PRD 3.8 damage surcharge)."""
from test_helpers import (
    add_active_subscription,
    assert_batch,
    assert_invoice,
    create_case,
    create_pause,
    generate_invoice,
    read_customer,
    set_clock,
    setup_active_subscription,
    setup_loaded_batch,
    start_wash,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import BILLING


class TestWashDosingMultifactor:
    def _setup_heavy_hard_batch(self):
        """A 12000 g HEAVY intake loaded into a HEAVY/HARD batch on the F-SANI
        formula (base 45 ml/kg, sanitizer 8 ml/kg)."""
        return setup_loaded_batch(
            clean_items=120, scale_weight_g=12000, intake_soil="HEAVY",
            batch_soil="HEAVY", water_hardness="HARD",
        )

    def test_detergent_dose_rounds_half_up_before_clamp(self, api):
        """PRD 3.5: "The raw detergent dose is the pinned formula's
        `base_detergent_ml_per_kg` times the load in kilograms times the soil
        multiplier times the hardness multiplier; `dosed_detergent_ml` is that raw
        figure rounded half-up to a whole millilitre and then clamped into the band
        from 60 ml to 900 ml"
        PRD 3.5: "a 12000-gram `HEAVY` load on `HARD` water with a base dose of 45
        yields a raw 776.25 ml, dosing 776 ml of detergent"

        Design: Difficulty/combinatorial_formula/wash_dosing_multifactor_with_clamp
        """
        ctx = self._setup_heavy_hard_batch()
        batch = start_wash(ctx["batch"]["id"])
        assert_batch(batch)
        assert batch["total_load_g"] == 12000
        assert batch["dosed_detergent_ml"] == 776, (
            f"45 x 12.0 kg x 1.25 x 1.15 = 776.25 -> round_half_up 776, clamp "
            f"[60, 900] not engaged; got {batch['dosed_detergent_ml']}"
        )

    def test_sanitizer_dose_scales_and_is_never_clamped(self, api):
        """PRD 3.5: "`dosed_sanitizer_ml` is the pinned `sanitizer_ml_per_kg` times
        the load in kilograms, rounded half-up to a whole millilitre, and is never
        clamped."
        PRD 3.5: "and at 8 ml per kilogram, 96 ml of sanitizer"

        Design: Difficulty/combinatorial_formula/wash_dosing_multifactor_with_clamp
        """
        ctx = self._setup_heavy_hard_batch()
        batch = start_wash(ctx["batch"]["id"])
        assert batch["dosed_sanitizer_ml"] == 96, (
            f"8 ml/kg x 12.0 kg = 96, got {batch['dosed_sanitizer_ml']}"
        )
        assert batch["wash_started_by"] == "op-1", (
            "the starting operator's X-User-ID is recorded in wash_started_by"
        )


class TestInvoiceRoundingOrder:
    def _setup_paused_invoice(self):
        """ACTIVE ESSENTIAL (3200/week) subscription in a MON/WED/FRI zone with a
        pause over [2026-08-05, 2026-08-10); clock parked mid-pause."""
        ctx = setup_active_subscription(
            plan_overrides={"tier_code": "ESSENTIAL", "weekly_fee_cents": 3200},
            zone_overrides={
                "zone_code": "Z-TRI",
                "service_weekdays": ["MON", "WED", "FRI"],
            },
        )
        create_pause(
            ctx["subscription"]["id"], "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )
        set_clock("2026-08-08T09:00:00Z")
        return ctx

    def test_pause_credit_rounds_per_line(self, api):
        """PRD 2.6: "One ordering rule is pinned and non-negotiable: every line is
        rounded to integer cents first, and totals are sums of those already-rounded
        lines. Sum-then-round is forbidden."
        PRD 3.7: "The two-service-day pause above finalizes at 1067 + 1067 = 2134
        cents — never the provisional 3200, and never the sum-then-round 2133, per the
        pinned rounding order of §2.6."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = self._setup_paused_invoice()
        invoice = generate_invoice(ctx["subscription"]["id"])
        assert_invoice(invoice)
        assert invoice["pause_credit_cents"] == 2134, (
            f"per-line round_half_up(3200/3) = 1067 twice = 2134 (sum-then-round "
            f"would give 2133); got {invoice['pause_credit_cents']}"
        )

    def test_total_is_sum_of_already_rounded_lines(self, api):
        """PRD 3.9: "`total_cents` is the base fee plus overage minus pause credit —
        a sum of already-rounded integer-cent lines, per §2.6 — floored at zero."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = self._setup_paused_invoice()
        invoice = generate_invoice(ctx["subscription"]["id"])
        assert invoice["base_fee_cents"] == 3200
        assert invoice["overage_cents"] == 0
        assert invoice["pause_credit_cents"] == 2134
        assert invoice["total_cents"] == 1066, (
            f"3200 + 0 - 2134 = 1066, got {invoice['total_cents']}"
        )


class TestDamageSurchargeOrder:
    def _setup_surcharge_pair(self):
        """Customer A with one LOST case already charged (40 MEDIUM items, age 61
        days -> 12000) plus a fresh DAMAGED case; customer B clean with a DAMAGED
        case. Both deposits are 18000."""
        ctx_a = setup_active_subscription(
            customer_overrides={"full_name": "Surcharge A"}
        )
        lost = create_case(
            ctx_a["subscription"]["id"], ctx_a["pool"]["id"],
            case_type="LOST", item_count=40, first_issued_date="2026-06-01",
        )
        charged_lost = validate_success(
            _client.case_event(lost["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged_lost["charge_cents"] == 12000  # 40 x 300 x 1.00 at age 61

        case_dmg = create_case(
            ctx_a["subscription"]["id"], ctx_a["pool"]["id"],
            case_type="DAMAGED", item_count=1, first_issued_date="2026-06-01",
            assessed_fee_cents=4000,
        )

        # Customer B joins the same zone/plan (the MEDIUM pool is shared —
        # PRD 3.1 makes size_code unique across pools, so a second full
        # setup_active_subscription() would 400 on the duplicate MEDIUM pool).
        member_b = add_active_subscription(
            ctx_a, customer_overrides={"full_name": "Low Utilization B"}
        )
        case_low = create_case(
            member_b["subscription"]["id"], ctx_a["pool"]["id"],
            case_type="DAMAGED", item_count=1, first_issued_date="2026-06-01",
            assessed_fee_cents=1000,
        )
        return ctx_a, case_dmg, member_b, case_low

    def test_surcharge_applies_above_half_utilization(self, api):
        """PRD 3.8: "For `DAMAGED`, the charge is `assessed_fee_cents` times
        `item_count`, with a surcharge multiplier applied before rounding: the
        customer's deposit utilization — `deposit_applied_cents` divided by
        `deposit_charged_cents`, taken before this charge is applied, and treated as
        zero when nothing has ever been charged — adds a 10 percent surcharge only
        when it is strictly greater than one half, otherwise the multiplier is one."
        PRD 3.8: "with 12000 of an 18000-cent deposit already applied, the ratio
        exceeds one half and a 4000-cent assessed fee for one item charges 4400"

        Design: Difficulty/combinatorial_formula/damage_surcharge_pinned_evaluation_order
        """
        ctx_a, case_dmg, _, _ = self._setup_surcharge_pair()
        charged = validate_success(
            _client.case_event(case_dmg["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged["charge_cents"] == 4400, (
            f"utilization 12000/18000 > 1/2 before this charge, so 4000 x 1.10 = "
            f"4400; got {charged['charge_cents']}"
        )
        customer = read_customer(ctx_a["customer"]["id"])
        assert customer["deposit_applied_cents"] == 16400
        assert customer["deposit_held_cents"] == 1600, (
            "the surcharge is keyed on the pre-charge ratio and never re-triggers "
            "itself within one charge"
        )

    def test_no_surcharge_below_half_utilization(self, api):
        """PRD 3.8: "with only 720 applied, the same fee would charge 1000 — that is,
        a 1000-cent fee times one item at no surcharge."

        Design: Difficulty/combinatorial_formula/damage_surcharge_pinned_evaluation_order
        """
        _, _, ctx_b, case_low = self._setup_surcharge_pair()
        charged = validate_success(
            _client.case_event(case_low["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged["charge_cents"] == 1000, (
            f"nothing applied yet -> utilization 0 -> no surcharge; got "
            f"{charged['charge_cents']}"
        )
        customer = read_customer(ctx_b["customer"]["id"])
        assert customer["deposit_applied_cents"] == 1000
        assert customer["deposit_held_cents"] == 17000
