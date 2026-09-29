"""
Derived figures: the licensing financial test, weigh-in quantity and grade,
storage accrual tiers, reconciliation deltas, collateral valuation and the
two-tier indemnity waterfall.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import REGULATOR_HEADERS, make_warehouse_operator_headers

FEDERAL_TERMINAL = {
    "name": "Federal Terminal",
    "operator_name": "River Terminal LLC",
    "state_code": "IA",
    "license_program": "FEDERAL",
    "licensed_capacity_bushels": 2_000_000,
    "loadout_lane_count": 4,
}

CLOCK_DAY_16 = "2026-08-20T09:00:00Z"
CLOCK_DAY_41 = "2026-09-14T09:00:00Z"
CLOCK_DAY_118 = "2026-11-30T09:00:00Z"
CLOCK_INSOLVENCY_DAY = "2026-09-01T08:00:00Z"


class TestLicensingFinancialTest:
    def test_a_federal_application_scales_both_requirements_with_capacity(
        self, new_warehouse
    ):
        """
        At 2000000 applied bushels the FEDERAL per-bushel scales beat both
        programme floors: net worth is required at 8 cents a bushel (16000000,
        not the 10000000 floor) with a quarter of that as tolerance, and the base
        bond is 6000000 either way, lifted to 12000000 by one and a half times
        the 4000000 net-worth shortfall — which the posted 12000000 bond exactly
        covers.

        PRD: "**Required net worth** is the greater of a programme floor and a
        per-bushel scale: the floor is 5,000,000 cents (fifty thousand dollars)
        under the `STATE` programme and 10,000,000 cents (one hundred thousand
        dollars) under `FEDERAL`, and the scale is 4 cents per applied bushel
        under `STATE` and 8 cents per applied bushel under `FEDERAL`."

        PRD: "**Base bond** is again the greater of a programme floor and a
        per-bushel scale: the floor is 2,500,000 cents (twenty-five thousand
        dollars) under `STATE` and 6,000,000 cents (sixty thousand dollars) under
        `FEDERAL`, while the scale runs the other way — 5 cents per applied bushel
        under `STATE` but only 3 cents per applied bushel under `FEDERAL`."

        Design: Corner/calculations/federal_program_requirements_scale_with_licensed_capacity
        """
        warehouse = new_warehouse(
            bond_amount_cents=12_000_000, net_worth_cents=12_000_000, **FEDERAL_TERMINAL
        )

        assert_fields_equal(
            warehouse,
            {
                "required_net_worth_cents": 16000000,
                "net_worth_shortfall_cents": 4000000,
                "net_worth_tolerance_cents": 4000000,
                "required_bond_cents": 12000000,
                "bond_deficiency_cents": 0,
            },
        )

    def test_a_shortfall_one_cent_past_tolerance_blocks_issuance(
        self, api, new_warehouse
    ):
        """
        Net worth of 11999999 leaves a shortfall of 4000001 against a tolerance
        of exactly 4000000 — one cent past what forgiveness covers. The bond side
        is spotless: the surcharge on the whole shortfall makes the requirement
        12000002, which the posted bond matches to the cent, so the only reason
        for the refusal is the net-worth test, and the licence stays APPLIED.

        PRD: "A licence may be issued only when the shortfall is **less than or
        equal to** the tolerance and the bond deficiency is **exactly** zero."

        PRD: "`required_bond_cents` is that base bond **plus** a shortfall
        surcharge of 15000 basis points, that is one and a half times, the
        net-worth shortfall, rounded half up to whole cents."

        Design: Corner/calculations/net_worth_shortfall_one_cent_over_tolerance_blocks_license
        """
        warehouse = new_warehouse(
            bond_amount_cents=12_000_002, net_worth_cents=11_999_999, **FEDERAL_TERMINAL
        )

        response = api.license_decision(
            warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
        )

        validate_error(response, E.ERR_NET_WORTH_INSUFFICIENT, 422)

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current,
            {
                "net_worth_shortfall_cents": 4000001,
                "net_worth_tolerance_cents": 4000000,
                "required_bond_cents": 12000002,
                "bond_deficiency_cents": 0,
                "license_state": "APPLIED",
            },
        )

    def test_a_bond_one_cent_short_surfaces_once_the_net_worth_test_is_forgiven(
        self, api, new_warehouse
    ):
        """
        A shortfall exactly equal to the tolerance is forgiven, so the net-worth
        test passes — but the bond top-up is not forgiven with it: the 4000000
        shortfall still lifts the requirement to 12000000 against a posted
        11999999, a deficiency of a single cent that is enough to refuse the
        licence.

        PRD: "The critical subtlety: the surcharge is levied on the *whole*
        shortfall whenever a shortfall exists, even when that shortfall is small
        enough to be forgiven by the tolerance."

        PRD: "A shortfall greater than the tolerance is reported as
        `ERR_NET_WORTH_INSUFFICIENT`; a bond deficiency greater than zero as
        `ERR_BOND_INSUFFICIENT`."

        Design: Corner/calculations/bond_one_cent_short_blocks_license_after_net_worth_passes
        """
        warehouse = new_warehouse(
            bond_amount_cents=11_999_999, net_worth_cents=12_000_000, **FEDERAL_TERMINAL
        )

        response = api.license_decision(
            warehouse["id"], f.license_issue_payload(), REGULATOR_HEADERS
        )

        validate_error(response, E.ERR_BOND_INSUFFICIENT, 422)

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current,
            {
                "net_worth_shortfall_cents": 4000000,
                "bond_deficiency_cents": 1,
                "license_state": "APPLIED",
            },
        )


class TestWeighInQuantityAndGrade:
    def test_the_identity_preserved_variant_suppresses_the_moisture_shrink(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        weighed_ticket,
    ):
        """
        Two loads with byte-identical readings, differing only in the storage
        kind of the agreement they arrive under. Both take the same 45-bushel
        dockage down to 960 clean bushels; the commingled lot then bears 11
        bushels of drying loss on its 1.0 point of excess moisture and nets 949,
        while the identity-preserved lot nets the full 960.

        PRD: "Under `IDENTITY_PRESERVED`, `shrink_bushels` is forced to exactly
        zero regardless of moisture, so `net_bushels` equals `clean_bushels`."

        PRD: "Under `COMMINGLED`, the moisture shrink is assessed exactly as
        written above."

        Design: Corner/calculations/identity_preserved_variant_suppresses_moisture_shrink
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        commingled = new_agreement(warehouse["id"], producer["id"])
        preserved = new_agreement(
            warehouse["id"], producer["id"], storage_kind="IDENTITY_PRESERVED"
        )
        commingling_bin = new_bin(warehouse["id"])
        dedicated_bin = new_bin(
            warehouse["id"], bin_code="B4", commingling_allowed=False
        )

        commingled_ticket = weighed_ticket(
            warehouse["id"], commingled["id"], commingling_bin["id"]
        )
        preserved_ticket = weighed_ticket(
            warehouse["id"], preserved["id"], dedicated_bin["id"]
        )

        assert_fields_equal(
            commingled_ticket,
            {
                "settlement_variant": "COMMINGLED",
                "dockage_bushels": 45,
                "clean_bushels": 960,
                "shrink_bushels": 11,
                "net_bushels": 949,
            },
        )
        assert_fields_equal(
            preserved_ticket,
            {
                "settlement_variant": "IDENTITY_PRESERVED",
                "dockage_bushels": 45,
                "clean_bushels": 960,
                "shrink_bushels": 0,
                "net_bushels": 960,
            },
        )

    def test_the_worst_failing_factor_governs_the_assigned_grade(
        self, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """
        Test weight 56.5 and foreign material 1.0 would both qualify for US_NO_1,
        but damage of 6.0 percent clears only the US_NO_3 ceiling of 7.0, so the
        load grades US_NO_3 — no averaging across the three factors.

        PRD: "The grade assigned is the **best** grade whose three thresholds are
        all satisfied at once — equivalently, the worst factor governs."

        PRD: "`US_NO_3` requires a test weight of at least 52.0 pounds per bushel,
        damage of at most 7.0 percent, and foreign material of at most 4.0
        percent."

        Design: Corner/calculations/grade_assignment_governed_by_worst_failing_factor
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])

        ticket = weighed_ticket(
            warehouse["id"], agreement["id"], storage_bin["id"], damage_pct=6.0
        )

        assert_fields_equal(
            ticket,
            {
                "assigned_grade": "US_NO_3",
                "net_bushels": 949,
                "ticket_state": "WEIGHED",
            },
        )

    def test_a_test_weight_below_every_tier_grades_sample_grade(
        self, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """
        At 51.0 pounds the load misses even the lowest tier's 52.0-pound
        threshold, so it grades SAMPLE_GRADE. The ticket is still written — the
        grade gate lives at acceptance, not at the scale.

        PRD: "Anything that fails all three tiers is `SAMPLE_GRADE`."

        Design: Corner/calculations/sample_grade_assigned_when_test_weight_below_every_limit
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])

        ticket = weighed_ticket(
            warehouse["id"],
            agreement["id"],
            storage_bin["id"],
            test_weight_lbs=51.0,
            moisture_pct=13.0,
        )

        assert_fields_equal(
            ticket, {"assigned_grade": "SAMPLE_GRADE", "ticket_state": "WEIGHED"}
        )

    def test_moisture_under_the_ceiling_leaves_the_clean_bushels_intact(
        self, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """
        The dockage step still runs — 4.5 percent of 1005 bushels is 45.225,
        rounded to 45, leaving 960 clean — but 13.0 percent moisture is under the
        agreement's 14.0 ceiling, so the excess floors at zero and the net
        bushels stay at the clean figure.

        PRD: "First, `dockage_bushels` is the `gross_bushels` multiplied by
        `dockage_pct` and divided by one hundred, rounded half up to a whole
        bushel; `clean_bushels` is `gross_bushels` less `dockage_bushels`."

        PRD: "Second, the excess moisture is the amount by which `moisture_pct`
        exceeds the agreement's `max_moisture_pct`, floored at zero, and
        `shrink_bushels` is the product of `clean_bushels`, that excess expressed
        in percentage points, and one hundred eighteen ten-thousandths, rounded
        half up to a whole bushel."

        Design: Corner/calculations/sample_grade_assigned_when_test_weight_below_every_limit
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])

        ticket = weighed_ticket(
            warehouse["id"],
            agreement["id"],
            storage_bin["id"],
            test_weight_lbs=51.0,
            moisture_pct=13.0,
        )

        assert_fields_equal(
            ticket,
            {"dockage_bushels": 45, "shrink_bushels": 0, "net_bushels": 960},
        )


class TestStorageAccrualTiers:
    def test_the_provisional_accrual_bills_days_past_ninety_at_the_surcharge_rate(
        self, api, base_full, set_clock
    ):
        """
        Read on 2026-11-30 the receipt has been in store 118 inclusive days: the
        first 90 accrue at 350 millicents a bushel-day (29893.5 rounded to 29894)
        and the remaining 28 at one and a quarter that rate (11625.25 rounded to
        11625). Rounding each tier before adding gives 41519; rounding once on a
        combined day count would not.

        PRD: "The day count is the number of calendar days from the date part of
        the receipt's `issued_at` to the evaluation date, counting **both**
        endpoints — a receipt evaluated on the day it was issued has a day count
        of one."

        PRD: "Base days are billed at the agreement's
        `storage_rate_millicents_per_bushel_day`; the base component in cents is
        the product of the outstanding bushels, that millicent rate and the base
        days, divided by one thousand to convert millicents to cents, then rounded
        half up to whole cents."

        PRD: "Surcharge days are billed at 12500 basis points of the same rate —
        one and a quarter times the base rate — so the surcharge component in
        cents is the product of the outstanding bushels, the millicent rate, the
        surcharge days and 12500, divided by ten million, again rounded half up to
        whole cents."

        Design: Corner/calculations/storage_charge_surcharge_tier_engages_past_ninety_chargeable_days
        """
        set_clock(CLOCK_DAY_118)

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )

        assert_fields_equal(
            receipt,
            {"provisional_storage_charge_cents": 41519, "quantity_bushels": 949},
        )

    def test_the_five_dollar_minimum_lifts_a_single_chargeable_day_at_settlement(
        self, api, base_full, set_clock, booked_delivery_order
    ):
        """
        Settling on 2026-08-20 counts 16 inclusive days less the 15 free days the
        agreement granted, so exactly one day is chargeable and the raw accrual is
        332 cents — non-zero, so the floor applies and the warehouse bills 500.
        The delivered 400 bushels at 8 cents add 3200, and with the grain
        delivered at the grade certified there is nothing to credit back, so the
        depositor owes 3700.

        PRD: "If the raw charge is exactly zero the storage charge is zero;
        otherwise the storage charge is the greater of the raw charge and a
        500-cent (five dollar) minimum."

        PRD: "Loadout grades the delivered grain through the same factor table of
        §2.9 that was used at weigh-in, writing `delivered_grade`; computes
        `grade_delta_bps`; sets `loaded_at`; computes `storage_charge_cents` using
        the **FINAL** storage variant of §2.10 evaluated on the receipt's
        outstanding `quantity_bushels` as of the loadout date; and computes
        `loadout_charge_cents` as `delivered_bushels` multiplied by the
        agreement's `loadout_charge_cents_per_bushel`, rounded half up to whole
        cents."

        PRD: "`net_settlement_cents` is that quality adjustment less
        `storage_charge_cents` less `loadout_charge_cents`, and it may well be
        negative — a negative net settlement means the depositor owes the
        warehouse."

        Design: Corner/calculations/storage_charge_minimum_floor_applied_to_single_chargeable_day
        """
        set_clock(CLOCK_DAY_16)
        order = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            CLOCK_DAY_16,
            "2026-08-20T11:00:00Z",
        )
        get_success_data(
            api.load_delivery_order(
                order["id"],
                f.load_payload(400, delivered_moisture_pct=15.0),
                base_full["operator_headers"],
            ),
            200,
        )

        settled = get_success_data(
            api.settle_delivery_order(
                order["id"], f.settle_payload(430), base_full["operator_headers"]
            ),
            200,
        )

        assert_fields_equal(
            settled,
            {
                "storage_charge_cents": 500,
                "loadout_charge_cents": 3200,
                "quality_adjustment_cents": 0,
                "net_settlement_cents": -3700,
                "delivery_state": "SETTLED_PARTIAL",
            },
        )


class TestPositionReconciliationInputs:
    def test_the_obligation_counts_neither_weighed_nor_rejected_loads(
        self, api, base_full, weighed_ticket
    ):
        """
        Three loads sit on the books: 949 bushels certified on a receipt, 500 on
        the scale awaiting a decision, and 600 turned away. Only the receipted
        949 is owed, and because that is also all the grain physically in the
        bins the position squares exactly.

        PRD: "The **obligation** is what the warehouse owes: the sum of
        `quantity_bushels` across receipts in `receipt_state` `ISSUED`, plus the
        sum of `net_bushels` across deposit tickets in `ticket_state` `ACCEPTED`."

        PRD: "Weighed, receipted and rejected tickets are excluded from that sum,
        as are cancelled and voided receipts."

        Design: Corner/calculations/obligation_excludes_weighed_and_rejected_tickets
        """
        headers = base_full["operator_headers"]
        still_weighed = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-06T09:00:00Z",
            fill_end_at="2026-08-06T11:00:00Z",
        )
        turned_away = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=600,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-07T09:00:00Z",
            fill_end_at="2026-08-07T11:00:00Z",
        )
        get_success_data(
            api.reject_deposit_ticket(
                turned_away["id"], f.reject_ticket_payload(), headers
            ),
            200,
        )

        get_success_data(
            api.get_position_summary(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            warehouse,
            {
                "obligation_bushels": 949,
                "receipted_obligation_bushels": 949,
                "system_physical_bushels": 949,
                "sound_physical_bushels": 949,
                "position_variance_bushels": 0,
            },
        )

        assert (
            get_success_data(api.get_deposit_ticket(still_weighed["id"], headers), 200)[
                "ticket_state"
            ]
            == "WEIGHED"
        )
        assert (
            get_success_data(api.get_deposit_ticket(turned_away["id"], headers), 200)[
                "ticket_state"
            ]
            == "REJECTED"
        )

    def test_at_two_hundred_thousand_bushels_the_bps_term_beats_the_floor(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
    ):
        """
        A single 200000-bushel receipt (no dockage, and moisture exactly at the
        14.0 ceiling so no shrink) makes 50 basis points of the obligation worth
        1000 bushels, which is what the tolerance becomes now that it clears the
        500-bushel floor. The receiving charge scales with the same quantity at 6
        cents a bushel.

        PRD: "The tolerance against which all three are judged is
        `examination_tolerance_bushels`: the greater of a 500-bushel floor and 50
        basis points — one half of one percent — of the obligation, rounded half up
        to a whole bushel."

        PRD: "`receiving_charge_cents` is the quantity at issuance multiplied by
        the agreement's `receiving_charge_cents_per_bushel`, rounded half up to
        whole cents, and becomes a fixed component of the warehouseman's lien for
        the life of the receipt."

        Design: Corner/calculations/examination_tolerance_uses_bps_when_it_exceeds_the_floor
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        big_bin = new_bin(
            warehouse["id"], bin_code="B5", capacity_bushels=400_000
        )
        ticket = accepted_ticket(
            warehouse["id"],
            agreement["id"],
            big_bin["id"],
            gross_bushels=200_000,
            moisture_pct=14.0,
            dockage_pct=0.0,
        )
        receipt = issue_receipt(
            warehouse["id"],
            ticket["id"],
            producer["id"],
            receipt_number="WR-2000",
            medium="PAPER",
        )

        assert ticket["net_bushels"] == 200000
        assert_fields_equal(
            receipt,
            {"quantity_bushels": 200000, "receiving_charge_cents": 1200000},
        )

        get_success_data(
            api.get_position_summary(warehouse["id"], REGULATOR_HEADERS), 200
        )

        current = get_success_data(
            api.get_warehouse(warehouse["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            current,
            {
                "obligation_bushels": 200000,
                "examination_tolerance_bushels": 1000,
                "position_variance_bushels": 0,
                "operational_posture": "OPEN",
            },
        )


class TestCollateralValuationOnADiscountedGrade:
    @pytest.fixture
    def lien_on_a_us_no_3_receipt(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_lender,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
        set_clock,
        request_lien,
    ):
        """
        A 949-bushel US_NO_3 receipt, marked to market at 450 cents fifteen days
        after issuance so the warehouseman's provisional accrual has grown to
        5314 cents.
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        lender = new_lender()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = accepted_ticket(
            warehouse["id"], agreement["id"], storage_bin["id"], damage_pct=6.0
        )
        receipt = issue_receipt(
            warehouse["id"], ticket["id"], producer["id"], receipt_number="WR-0003"
        )
        set_clock(CLOCK_DAY_16)
        lien = request_lien(receipt["id"], lender["id"])
        return {"receipt": receipt, "lien": lien}

    def test_a_us_no_3_receipt_carries_the_four_hundred_point_grade_discount(
        self, lien_on_a_us_no_3_receipt
    ):
        """
        949 bushels marked at 450 cents gross 427050, and because the certified
        grade is US_NO_3 the schedule takes 400 basis points off it: 96 percent of
        the gross is 409968 with nothing to round.

        PRD: "Grade drives money through a discount schedule quoted in basis
        points: `US_NO_1` attracts a discount of 0 basis points, `US_NO_2` 150
        basis points (one and a half percent), `US_NO_3` 400 basis points (four
        percent) and `SAMPLE_GRADE` 1200 basis points (twelve percent)."

        PRD: "`eligible_value_cents` is the gross value reduced by the discount —
        the gross value multiplied by the complement of `grade_discount_bps`
        within ten thousand, divided by ten thousand — rounded half up to whole
        cents."

        Design: Corner/calculations/lien_grade_discount_and_half_up_rounding_on_advance_limit
        """
        assert lien_on_a_us_no_3_receipt["receipt"]["grade"] == "US_NO_3"
        assert_fields_equal(
            lien_on_a_us_no_3_receipt["lien"],
            {
                "gross_value_cents": 427050,
                "grade_discount_bps": 400,
                "eligible_value_cents": 409968,
            },
        )

    def test_the_advance_limit_rounds_an_exact_half_cent_upward(
        self, lien_on_a_us_no_3_receipt
    ):
        """
        The 25-basis-point fee on the eligible value is 1024.92, rounded to 1025,
        and it joins the 5314 of provisional storage and the 5694 receiving charge
        in a 12033-cent prior lien, leaving 397935 of net collateral. That is
        below the hundred-thousand-dollar tier, so seventy percent of it lands on
        the exact half cent 278554.5 — and half up makes it 278555, not 278554.

        PRD: "`admin_fee_cents` is 25 basis points, one quarter of one percent, of
        the **eligible** value from step 3, rounded half up to whole cents."

        PRD: "`warehouseman_lien_cents` is the sum of the receipt's
        `provisional_storage_charge_cents`, its `receiving_charge_cents` and the
        `admin_fee_cents` from step 4."

        PRD: "`advance_limit_cents` is `net_collateral_cents` multiplied by
        `advance_rate_bps` and divided by ten thousand, rounded half up to whole
        cents."

        Design: Corner/calculations/lien_grade_discount_and_half_up_rounding_on_advance_limit
        """
        assert_fields_equal(
            lien_on_a_us_no_3_receipt["lien"],
            {
                "admin_fee_cents": 1025,
                "warehouseman_lien_cents": 12033,
                "net_collateral_cents": 397935,
                "advance_rate_bps": 7000,
                "advance_limit_cents": 278555,
                "margin_status": "SUFFICIENT",
            },
        )


class TestDeliveryQualityAdjustmentAsymmetry:
    def test_grain_delivered_better_than_certified_earns_the_warehouse_nothing(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
        set_clock,
        booked_delivery_order,
    ):
        """
        The receipt certifies US_NO_3 but the grain that actually goes out tests
        US_NO_1, so the delta is the 0-point discount less the 400-point one,
        floored to zero: the depositor is not compensated and the warehouse takes
        no credit either. The settlement is therefore pure charges — 8636 of final
        storage over 26 chargeable days plus 7592 of loadout on 949 bushels.

        PRD: "`grade_delta_bps` is **asymmetric**, and deliberately so."

        PRD: "When the warehouse delivers grain worse than it certified, the
        difference is positive and the depositor is compensated; when it delivers
        grain *better* than it certified, the delta is zero and the warehouse keeps
        no credit for the upgrade."

        PRD: "`quality_adjustment_cents` is the product of `delivered_bushels`,
        that settlement price and `grade_delta_bps`, divided by ten thousand and
        rounded half up to whole cents; it is a credit owed to the depositor."

        Design: Corner/calculations/delivery_quality_adjustment_gives_no_credit_for_better_grade
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = accepted_ticket(
            warehouse["id"], agreement["id"], storage_bin["id"], damage_pct=6.0
        )
        receipt = issue_receipt(
            warehouse["id"],
            ticket["id"],
            producer["id"],
            receipt_number="WR-0003",
            medium="PAPER",
        )
        headers = make_warehouse_operator_headers(warehouse["id"])

        set_clock(CLOCK_DAY_41)
        order = booked_delivery_order(
            producer["id"],
            receipt["id"],
            949,
            CLOCK_DAY_41,
            "2026-09-14T11:00:00Z",
        )
        get_success_data(
            api.load_delivery_order(
                order["id"], f.load_payload(949, delivered_moisture_pct=15.0), headers
            ),
            200,
        )

        settled = get_success_data(
            api.settle_delivery_order(order["id"], f.settle_payload(430), headers), 200
        )
        assert_fields_equal(
            settled,
            {
                "delivered_grade": "US_NO_1",
                "grade_delta_bps": 0,
                "quality_adjustment_cents": 0,
                "storage_charge_cents": 8636,
                "loadout_charge_cents": 7592,
                "net_settlement_cents": -16228,
                "delivery_state": "SETTLED_FULL",
            },
        )

        party = get_success_data(
            api.get_party(producer["id"], REGULATOR_HEADERS), 200
        )
        assert party["settlement_balance_cents"] == -16228


class TestIndemnityWaterfall:
    @staticmethod
    def _hundred_thousand_bushel_receipt(
        accepted_ticket,
        issue_receipt,
        warehouse_id,
        agreement_id,
        bin_id,
        holder_party_id,
        receipt_number,
        fill_start_at,
        fill_end_at,
    ):
        ticket = accepted_ticket(
            warehouse_id,
            agreement_id,
            bin_id,
            gross_bushels=100_000,
            moisture_pct=14.0,
            dockage_pct=0.0,
            fill_start_at=fill_start_at,
            fill_end_at=fill_end_at,
        )
        return issue_receipt(
            warehouse_id,
            ticket["id"],
            holder_party_id,
            receipt_number=receipt_number,
            medium="PAPER",
        )

    @pytest.fixture
    def allocated_two_producer_proceeding(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
        set_clock,
        claims_open_warehouse,
        filed_claim,
    ):
        """
        Two producers each holding a 100000-bushel receipt against a warehouse
        whose bond is 2,500,000 cents, declared insolvent on 2026-09-01 at 400
        cents a bushel, with both claims allowed and the waterfall run.
        """
        warehouse = licensed_warehouse()
        first = new_producer()
        second = new_producer(name="Bo Farms")
        first_agreement = new_agreement(warehouse["id"], first["id"])
        second_agreement = new_agreement(warehouse["id"], second["id"])
        waterfall_bin = new_bin(
            warehouse["id"], bin_code="B6", capacity_bushels=400_000
        )

        first_receipt = self._hundred_thousand_bushel_receipt(
            accepted_ticket,
            issue_receipt,
            warehouse["id"],
            first_agreement["id"],
            waterfall_bin["id"],
            first["id"],
            "WR-1001",
            "2026-08-05T09:00:00Z",
            "2026-08-05T11:00:00Z",
        )
        set_clock("2026-08-06T08:00:00Z")
        second_receipt = self._hundred_thousand_bushel_receipt(
            accepted_ticket,
            issue_receipt,
            warehouse["id"],
            second_agreement["id"],
            waterfall_bin["id"],
            second["id"],
            "WR-1002",
            "2026-08-06T09:00:00Z",
            "2026-08-06T11:00:00Z",
        )

        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(warehouse["id"])
        first_claim = filed_claim(
            warehouse["id"], first_receipt["id"], first["id"], 40_000_000
        )
        second_claim = filed_claim(
            warehouse["id"], second_receipt["id"], second["id"], 40_000_000
        )
        for claim in (first_claim, second_claim):
            get_success_data(
                api.adjudicate_indemnity_claim(
                    claim["id"],
                    f.adjudicate_payload("ALLOW", adjudication_note="verified"),
                    REGULATOR_HEADERS,
                ),
                200,
            )

        allocated = get_success_data(
            api.insolvency_action(
                warehouse["id"], f.insolvency_payload("ALLOCATE"), REGULATOR_HEADERS
            ),
            200,
        )
        return {
            "warehouse": allocated,
            "warehouse_id": warehouse["id"],
            "first_claim_id": first_claim["id"],
            "second_claim_id": second_claim["id"],
        }

    def test_the_bond_remainder_cent_goes_to_the_larger_allowed_claim(
        self, api, allocated_two_producer_proceeding
    ):
        """
        WR-1001 sat in store 28 days to the declaration and WR-1002 only 27, so
        their entitlements differ by the 35000 cents of storage that separates
        them: 38420000 and 38455000 against a bond pool of just 2500000. Flooring
        the pro-rata shares gives 1249430 and 1250569, one cent short of the pool,
        and that cent goes to the larger claim rather than the earlier one.

        PRD: "`entitlement_cents` is the receipt's outstanding `quantity_bushels`
        valued at the warehouse's `insolvency_price_cents_per_bushel`, less the
        warehouseman's prior claim — which here is the `PROVISIONAL` storage
        accrual of §2.10 computed on that same outstanding quantity as of the date
        of `insolvency_declared_at`, plus the receipt's `receiving_charge_cents` —
        with the whole result floored at zero."

        PRD: "Flooring leaves a remainder equal to the pool less the sum of the
        floored shares, and that remainder is distributed one cent at a time to
        claims taken in a fixed order: descending `allowed_cents` first, then
        ascending `created_at` as the tie-break, and never by `id`."

        Design: Corner/calculations/indemnity_bond_prorata_remainder_goes_to_largest_allowed_claim
        """
        scenario = allocated_two_producer_proceeding
        first = get_success_data(
            api.get_indemnity_claim(scenario["first_claim_id"], REGULATOR_HEADERS), 200
        )
        second = get_success_data(
            api.get_indemnity_claim(scenario["second_claim_id"], REGULATOR_HEADERS), 200
        )

        assert_fields_equal(
            first, {"entitlement_cents": 38420000, "bond_share_cents": 1249430}
        )
        assert_fields_equal(
            second, {"entitlement_cents": 38455000, "bond_share_cents": 1250570}
        )
        assert scenario["warehouse"]["bond_allocated_cents"] == 2500000

    def test_each_producer_then_draws_the_per_claimant_fund_cap(
        self, api, allocated_two_producer_proceeding
    ):
        """
        Both residuals exceed the 30000000-cent per-claimant ceiling, so each
        producer draws exactly that from the fund's 100000000 of capacity and the
        rest of each claim goes unpaid. The five roll-ups agree with the claims:
        76875000 allowed, 62500000 allocated and 14375000 left owing.

        PRD: "Otherwise its `fund_share_cents` is the smallest of the residual,
        the 30,000,000-cent per-claimant cap and the fund's remaining capacity,
        and the fund's remaining capacity is reduced by that share before the next
        claim is considered."

        PRD: "Each claim's `unpaid_cents` is then its `allowed_cents` less its
        `bond_share_cents` less its `fund_share_cents`, and each allowed claim
        moves from `ALLOWED` to `SETTLED`."

        Design: Corner/calculations/indemnity_bond_prorata_remainder_goes_to_largest_allowed_claim
        """
        scenario = allocated_two_producer_proceeding
        first = get_success_data(
            api.get_indemnity_claim(scenario["first_claim_id"], REGULATOR_HEADERS), 200
        )
        second = get_success_data(
            api.get_indemnity_claim(scenario["second_claim_id"], REGULATOR_HEADERS), 200
        )

        assert_fields_equal(
            first,
            {
                "fund_share_cents": 30000000,
                "unpaid_cents": 7170570,
                "claim_state": "SETTLED",
            },
        )
        assert_fields_equal(
            second,
            {
                "fund_share_cents": 30000000,
                "unpaid_cents": 7204430,
                "claim_state": "SETTLED",
            },
        )
        assert_fields_equal(
            scenario["warehouse"],
            {
                "insolvency_state": "ALLOCATED",
                "allowed_claim_total_cents": 76875000,
                "fund_allocated_cents": 60000000,
                "allocated_total_cents": 62500000,
                "unpaid_claim_total_cents": 14375000,
            },
        )

    def test_a_commercial_depositor_takes_the_bond_but_never_the_fund(
        self,
        api,
        licensed_warehouse,
        new_commercial_depositor,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
        set_clock,
        claims_open_warehouse,
        filed_claim,
    ):
        """
        The sole allowed claim is 38420000 against a 2500000 bond, so tier one
        pays out in full to it — but its claimant is a commercial depositor, not a
        producer, so tier two is closed and 35920000 goes unpaid with the fund
        untouched.

        PRD: "`fund_eligible` is set true only when the claimant party's
        `party_kind` is `PRODUCER_DEPOSITOR`; commercial depositors and lenders
        are not fund-eligible, which is the depositor-protection restriction at
        the heart of the scheme."

        PRD: "If the claim's `fund_eligible` is false, or the fund's remaining
        capacity has already reached zero, its `fund_share_cents` is zero."

        Design: Corner/calculations/indemnity_fund_denied_to_commercial_depositor
        """
        warehouse = licensed_warehouse()
        merchant = new_commercial_depositor()
        agreement = new_agreement(warehouse["id"], merchant["id"])
        commercial_bin = new_bin(
            warehouse["id"], bin_code="B7", capacity_bushels=400_000
        )
        receipt = self._hundred_thousand_bushel_receipt(
            accepted_ticket,
            issue_receipt,
            warehouse["id"],
            agreement["id"],
            commercial_bin["id"],
            merchant["id"],
            "WR-1003",
            "2026-08-05T09:00:00Z",
            "2026-08-05T11:00:00Z",
        )

        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(warehouse["id"])
        claim = filed_claim(
            warehouse["id"], receipt["id"], merchant["id"], 40_000_000
        )
        get_success_data(
            api.adjudicate_indemnity_claim(
                claim["id"],
                f.adjudicate_payload("ALLOW", adjudication_note="verified"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        allocated = get_success_data(
            api.insolvency_action(
                warehouse["id"], f.insolvency_payload("ALLOCATE"), REGULATOR_HEADERS
            ),
            200,
        )

        settled_claim = get_success_data(
            api.get_indemnity_claim(claim["id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            settled_claim,
            {
                "fund_eligible": False,
                "entitlement_cents": 38420000,
                "allowed_cents": 38420000,
                "bond_share_cents": 2500000,
                "fund_share_cents": 0,
                "unpaid_cents": 35920000,
                "claim_state": "SETTLED",
            },
        )
        assert_fields_equal(
            allocated,
            {
                "fund_allocated_cents": 0,
                "allocated_total_cents": 2500000,
                "unpaid_claim_total_cents": 35920000,
            },
        )
