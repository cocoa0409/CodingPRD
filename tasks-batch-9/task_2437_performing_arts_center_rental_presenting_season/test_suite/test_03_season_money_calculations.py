"""Money arithmetic: facility fees, deposits, labor tiering, capability
thresholds, dynamic ticket pricing, education allowances, the rental
settlement waterfall and the risk score at its band edge.

Each case pins the exact integer the formula produces, including the rounding
moment the specification declares normative.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    append_reserve_entry,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    clear_rider,
    confirm,
    create_education_program_payload,
    create_rental_engagement_payload,
    engagement_version,
    make_rental_client_contact_headers,
    negotiate_and_accept_fee,
    open_reserve_balance,
    put_on_sale,
    read_engagement,
    read_price_tier,
    record_deposit,
    register_artist,
    register_hall,
    register_rental_client,
    register_union_department,
    report_hours,
    review_rider,
    set_clock,
    submit_rider,
    clear_presented_rider,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestFacilityFeeAndDeposit:

    def test_combined_discount_is_capped_before_the_capacity_surcharge(self):
        """A five-day nonprofit booking earns 15 + 20 percent of discount but is
        held to the 30 percent cap, and the per-seat surcharge is added after
        the discounted base has been rounded.

        A 1,500-seat house at 500,000 per performance day and 200,000 per
        load-in day gives a base of 2,900,000 over five performance days and two
        load-in days; 70 percent of that is 2,030,000 and the surcharge is
        (1500 - 1200) * 25 = 7,500, so the fee is 2,037,500. The grade-B client
        owes 50 percent of it, 1,018,750, rounded up to the next whole multiple
        of 100 cents.

        PRD: "The two are added together and then capped at a combined maximum
        of 30 percent — a five-day nonprofit booking is discounted 30 percent,
        not 35."

        Design: Corner/calculations/facility_fee_combined_discount_is_capped_before_the_capacity_surcharge
        """
        space = register_hall(name="Opera House", seat_capacity=1500,
                             base_facility_fee_cents=500_000,
                             load_in_day_fee_cents=200_000)
        client = register_rental_client(org_name="Riverbend Youth Chorus",
                                        credit_rating="B", is_nonprofit=True)

        created = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(
                space["id"], client["id"],
                title="Riverbend Winter Festival",
                load_in_start_utc="2026-11-01T08:00:00Z",
                performance_start_utc="2026-11-03T19:00:00Z",
                performance_end_utc="2026-11-07T22:00:00Z",
                load_out_end_utc="2026-11-08T02:00:00Z",
                performance_day_count=5,
                load_in_day_count=2),
            RENTAL_MANAGER), expected_status=201)

        assert created["facility_fee_cents"] == 2_037_500
        assert created["deposit_required_cents"] == 1_018_800
        assert created["deposit_paid_cents"] == 0
        assert created["additional_equipment_cost_cents"] == 0

    def test_multi_day_discount_starts_at_three_performance_days(self):
        """Two performance days earn no multi-day discount; three earn 10
        percent. The same hall and the same grade-A client are used for both so
        only the day count differs.

        PRD: "The multi-day discount is 15 percent when
        `performance_day_count` is 5 or more, 10 percent when it is 3 or 4, and
        nothing otherwise."

        Design: Corner/calculations/facility_fee_at_the_exact_three_performance_day_discount_boundary
        """
        space = register_hall(name="Grand Hall", seat_capacity=1200,
                             base_facility_fee_cents=500_000,
                             load_in_day_fee_cents=250_000)
        client = register_rental_client(org_name="Northside Ballet Academy",
                                        credit_rating="A", is_nonprofit=False)

        two_day = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(
                space["id"], client["id"],
                title="Two Day Recital",
                load_in_start_utc="2026-10-02T08:00:00Z",
                performance_start_utc="2026-10-02T19:00:00Z",
                performance_end_utc="2026-10-03T22:00:00Z",
                load_out_end_utc="2026-10-04T02:00:00Z",
                performance_day_count=2,
                load_in_day_count=0),
            RENTAL_MANAGER), expected_status=201)

        assert two_day["facility_fee_cents"] == 1_000_000
        assert two_day["deposit_required_cents"] == 250_000

        three_day = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(
                space["id"], client["id"],
                title="Three Day Recital",
                load_in_start_utc="2026-10-11T08:00:00Z",
                performance_start_utc="2026-10-11T19:00:00Z",
                performance_end_utc="2026-10-13T22:00:00Z",
                load_out_end_utc="2026-10-14T02:00:00Z",
                performance_day_count=3,
                load_in_day_count=0),
            RENTAL_MANAGER), expected_status=201)

        assert three_day["facility_fee_cents"] == 1_350_000
        assert three_day["deposit_required_cents"] == 337_500

    def test_half_cent_results_round_half_up_then_the_deposit_rounds_up_to_100(self):
        """A base of 1,000,010 discounted 15 percent lands on exactly 850,008.5
        cents, which rounds half up to 850,009; the one surcharged seat then
        adds an unrounded 25 cents. The 25 percent deposit on 850,034 is
        exactly 212,508.5, rounds half up to 212,509 and is then raised to the
        next whole multiple of 100 cents.

        PRD: "The base is multiplied by one minus that combined percentage and
        the result is rounded half up to a whole cent; this is the only
        rounding step in the whole calculation."

        Design: Corner/calculations/facility_fee_and_deposit_use_round_half_up_at_the_exact_half_cent
        """
        space = register_hall(name="Half-Cent Hall", seat_capacity=1201,
                             base_facility_fee_cents=200_002,
                             load_in_day_fee_cents=0)
        client = register_rental_client(org_name="Odd Cent Productions",
                                        credit_rating="A", is_nonprofit=False)

        created = validate_success(api_client.create_engagement(
            create_rental_engagement_payload(
                space["id"], client["id"],
                title="Five Night Residency",
                load_in_start_utc="2026-10-01T08:00:00Z",
                performance_start_utc="2026-10-01T19:00:00Z",
                performance_end_utc="2026-10-05T22:00:00Z",
                load_out_end_utc="2026-10-06T02:00:00Z",
                performance_day_count=5,
                load_in_day_count=0),
            RENTAL_MANAGER), expected_status=201)

        assert created["facility_fee_cents"] == 850_034
        assert created["deposit_required_cents"] == 212_600


class TestLaborEstimateTiering:

    def test_estimate_at_the_call_minimum_and_at_both_rate_thresholds(self):
        """Three calls on the same rate card exercise the guaranteed minimum,
        the exact overtime threshold and the doubletime threshold. At 5,000
        cents an hour and a crew of two: a three-hour call bills the four-hour
        minimum (4 * 5,000 = 20,000 per member, 40,000 for the call); an
        eight-hour call is all straight time (40,000 per member, 80,000); a
        twelve-hour call is eight straight hours plus four at 1.5x
        (40,000 + 30,000 = 70,000 per member, 140,000). The engagement's
        estimate totals 260,000.

        PRD: "straight time is the billable hours capped at 8 hours; overtime
        is the billable hours in excess of 8 hours, itself capped at the 4-hour
        span between the 8-hour overtime threshold and the 12-hour doubletime
        threshold"

        Design: Corner/calculations/labor_estimate_at_call_minimum_and_at_exact_overtime_and_doubletime_thresholds
        """
        space = register_hall()
        artist = register_artist()
        department = register_union_department(department="ELECTRICS",
                                              roster_size=10,
                                              straight_hourly_rate_cents=5_000)
        engagement = book_presented_engagement(
            space["id"], artist["id"],
            load_in_start_utc="2026-10-01T00:00:00Z",
            performance_start_utc="2026-10-02T19:00:00Z",
            performance_end_utc="2026-10-02T22:00:00Z",
            load_out_end_utc="2026-10-03T00:00:00Z")

        minimum_call = validate_success(api_client.create_labor_call(
            engagement["id"],
            {"union_department_id": department["id"], "crew_size": 2,
             "call_start_utc": "2026-10-01T08:00:00Z",
             "call_end_utc": "2026-10-01T11:00:00Z"},
            TECH_DIRECTOR), expected_status=201)
        assert minimum_call["scheduled_hours"] == pytest.approx(3.0, abs=0.01)
        assert minimum_call["estimated_cost_cents"] == 40_000

        straight_call = validate_success(api_client.create_labor_call(
            engagement["id"],
            {"union_department_id": department["id"], "crew_size": 2,
             "call_start_utc": "2026-10-02T00:00:00Z",
             "call_end_utc": "2026-10-02T08:00:00Z"},
            TECH_DIRECTOR), expected_status=201)
        assert straight_call["estimated_cost_cents"] == 80_000

        overtime_call = validate_success(api_client.create_labor_call(
            engagement["id"],
            {"union_department_id": department["id"], "crew_size": 2,
             "call_start_utc": "2026-10-02T08:00:00Z",
             "call_end_utc": "2026-10-02T20:00:00Z"},
            TECH_DIRECTOR), expected_status=201)
        assert overtime_call["estimated_cost_cents"] == 140_000

        after = read_engagement(engagement["id"])
        assert after["labor_estimate_total_cents"] == 260_000
        assert after["facility_fee_cents"] == 0
        assert after["deposit_required_cents"] == 0


class TestCapabilityThresholds:

    def test_rigging_at_exactly_ninety_percent_of_the_grid_is_a_near_limit_gap(self):
        """The near-limit threshold on a 5,000 kg grid is 4,500 kg. A rider
        hanging 4,499 kg reviews to CAPABLE with no gaps; one hanging exactly
        4,500 kg reviews to GAP_IDENTIFIED carrying only RIGGING_NEAR_LIMIT,
        and because a near-limit flag needs no equipment line it clears with an
        equipment cost of zero, leaving the deposit requirement where the
        facility fee put it.

        PRD: "a near-limit threshold in whole kilograms is derived as 90
        percent of the hall's `rigging_capacity_kg`, rounded half up; if
        `submitted_rigging_kg` is greater than or equal to that threshold,
        `RIGGING_NEAR_LIMIT` is appended"

        Design: Corner/calculations/rigging_near_limit_at_exactly_ninety_percent_clears_without_equipment
        """
        space = register_hall(rigging_capacity_kg=5_000)
        client = register_rental_client(credit_rating="A")
        owner = make_rental_client_contact_headers(client["id"])

        below = book_rental_engagement(space["id"], client["id"],
                                       title="Under The Threshold")
        below_rider = submit_rider(below["id"], owner,
                                   submitted_rigging_kg=4_499)
        below_reviewed = validate_success(
            api_client.review_tech_rider(below_rider["id"], TECH_DIRECTOR))
        assert below_reviewed["review_status"] == "CAPABLE"
        assert below_reviewed["capability_gaps"] == []

        at_threshold = book_rental_engagement(
            space["id"], client["id"],
            title="Right On The Threshold",
            load_in_start_utc="2026-10-10T08:00:00Z",
            performance_start_utc="2026-10-11T19:00:00Z",
            performance_end_utc="2026-10-11T22:00:00Z",
            load_out_end_utc="2026-10-12T02:00:00Z")
        at_rider = submit_rider(at_threshold["id"], owner,
                                submitted_rigging_kg=4_500)
        at_reviewed = validate_success(
            api_client.review_tech_rider(at_rider["id"], TECH_DIRECTOR))
        assert at_reviewed["review_status"] == "GAP_IDENTIFIED"
        assert at_reviewed["capability_gaps"] == ["RIGGING_NEAR_LIMIT"]

        cleared = validate_success(
            api_client.clear_tech_rider(at_rider["id"], TECH_DIRECTOR))
        assert cleared["review_status"] == "CLEARED"
        assert cleared["additional_equipment_cost_cents"] == 0

        lines, lines_meta = validate_paginated(
            api_client.list_rider_equipment_lines(at_rider["id"], TECH_DIRECTOR))
        assert lines_meta["total_count"] == 0
        assert lines == []

        after = read_engagement(at_threshold["id"])
        assert after["additional_equipment_cost_cents"] == 0
        assert after["deposit_required_cents"] == 175_000


class TestDynamicTicketPricing:

    def test_high_band_multiplier_is_clamped_by_the_tier_ceiling(self):
        """On a 100-seat tier priced at 10,000 with a 12,000 ceiling, the sale
        that lands at a sell-through of exactly 0.85 selects the 1.30
        multiplier. 10,000 * 1.30 rounds to 13,000, above the ceiling, so the
        unit price is the ceiling itself.

        PRD: "`unit_price_cents` is the tier's `base_price_cents` multiplied by
        the selected multiplier, rounded half up to a whole cent, and then
        capped at the tier's `price_ceiling_cents` — the cap is applied after
        the rounding, and a ceiling below the multiplied price simply wins."

        Design: Corner/calculations/dynamic_ticket_price_in_the_high_band_is_clamped_by_the_tier_ceiling
        """
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])
        negotiate_and_accept_fee(engagement["id"], artist["id"], 300_000, 0.10)
        clear_presented_rider(engagement["id"], artist["id"])
        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=100, base_price_cents=10_000,
                              price_ceiling_cents=12_000,
                              dynamic_pricing_enabled=True)
        assessed = assess_risk(engagement["id"])
        assert assessed["risk_score"] == 27
        assert assessed["financial_clearance"] == "CLEARED"
        confirm(engagement["id"])
        put_on_sale(engagement["id"])
        version_on_sale = engagement_version(engagement["id"])

        first_sale = validate_success(api_client.create_ticket_sale(
            tier["id"], {"qty": 85, "channel": "WEB"}, BOX_OFFICE),
            expected_status=201)
        assert first_sale["sell_through_pct_at_sale"] == pytest.approx(0.0,
                                                                      abs=0.0001)
        assert first_sale["dynamic_multiplier_applied"] == pytest.approx(1.00,
                                                                        abs=0.01)
        assert first_sale["unit_price_cents"] == 10_000

        clamped_sale = validate_success(api_client.create_ticket_sale(
            tier["id"], {"qty": 1, "channel": "WEB"}, BOX_OFFICE),
            expected_status=201)
        assert clamped_sale["sell_through_pct_at_sale"] == pytest.approx(
            0.85, abs=0.0001)
        assert clamped_sale["dynamic_multiplier_applied"] == pytest.approx(
            1.30, abs=0.01)
        assert clamped_sale["unit_price_cents"] == 12_000
        assert clamped_sale["gross_cents"] == 12_000
        assert clamped_sale["restoration_fee_cents"] == 200

        after_tier = read_price_tier(tier["id"])
        assert after_tier["sold_qty"] == 86
        assert after_tier["gross_cents"] == 862_000
        assert after_tier["available_qty"] == 14
        assert after_tier["status"] == "ACTIVE"

        after = read_engagement(engagement["id"])
        assert after["realized_gross_cents"] == 862_000
        assert after["version"] == version_on_sale


class TestEducationSubsidyAllowance:

    def test_subsidy_is_trimmed_to_the_family_base_plus_per_participant_allowance(self):
        """A masterclass for 100 participants is allowed 150,000 + 100 * 1,500
        = 300,000, so a 500,000 request is trimmed to the allowance; a student
        matinee for 50 is allowed 400,000 + 75,000 = 475,000, so a 100,000
        request is granted in full. Each draw debits the reserve by the
        approved figure.

        PRD: "The program's `subsidy_approved_cents` is then the smaller of
        `subsidy_requested_cents` and that allowance — a modest request is
        granted in full, an ambitious one is trimmed to the allowance."

        Design: Corner/calculations/education_subsidy_is_capped_by_the_per_participant_allowance
        """
        open_reserve_balance(10_000_000)
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])

        trimmed = validate_success(api_client.create_education_program(
            engagement["id"],
            create_education_program_payload(program_type="MASTERCLASS",
                                             participant_capacity=100,
                                             subsidy_requested_cents=500_000),
            DIRECTOR), expected_status=201)
        assert trimmed["subsidy_approved_cents"] == 300_000
        assert trimmed["status"] == "FUNDED"

        granted = validate_success(api_client.create_education_program(
            engagement["id"],
            create_education_program_payload(program_type="STUDENT_MATINEE",
                                             participant_capacity=50,
                                             subsidy_requested_cents=100_000),
            DIRECTOR), expected_status=201)
        assert granted["subsidy_approved_cents"] == 100_000

        entries, meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement["id"],
                                                              ADMIN))
        assert meta["total_count"] == 2
        assert [entry["entry_type"] for entry in entries] == [
            "EDUCATION_SUBSIDY_DRAW", "EDUCATION_SUBSIDY_DRAW"]
        assert [entry["amount_cents"] for entry in entries] == [-300_000,
                                                                -100_000]
        assert [entry["balance_after_cents"] for entry in entries] == [
            9_700_000, 9_600_000]

    def test_reserve_floor_is_tested_against_the_latest_running_balance(self):
        """After an opening balance of 6,000,000 and a manual debit of 700,000
        the reserve stands at 5,300,000. A community workshop for 200
        participants is allowed 250,000 + 300,000 = 550,000, and drawing that
        would leave 4,750,000 — under the 5,000,000 floor — so the request is
        refused and no program is created. A 300,000 request lands the reserve
        on exactly the floor and is funded.

        PRD: "That balance less the approved subsidy must be greater than or
        equal to $50,000; a draw that would push the reserve beneath that floor
        is refused with `ERR_RESERVE_INSUFFICIENT` (HTTP 402) and no program is
        created."

        Design: Corner/calculations/education_subsidy_guard_reads_the_latest_ledger_balance
        """
        open_reserve_balance(6_000_000)
        append_reserve_entry("MANUAL_ADJUSTMENT", -700_000,
                             memo="Grid inspection overrun")
        space = register_hall()
        artist = register_artist()
        engagement = book_presented_engagement(space["id"], artist["id"])

        validate_error(api_client.create_education_program(
            engagement["id"],
            create_education_program_payload(
                program_type="COMMUNITY_WORKSHOP",
                participant_capacity=200,
                subsidy_requested_cents=600_000),
            DIRECTOR), "ERR_RESERVE_INSUFFICIENT")

        funded = validate_success(api_client.create_education_program(
            engagement["id"],
            create_education_program_payload(
                program_type="COMMUNITY_WORKSHOP",
                participant_capacity=200,
                subsidy_requested_cents=300_000),
            DIRECTOR), expected_status=201)
        assert funded["subsidy_approved_cents"] == 300_000

        entries, meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement["id"],
                                                              ADMIN))
        assert meta["total_count"] == 1
        assert entries[0]["balance_after_cents"] == 5_000_000

        programs, programs_meta = validate_paginated(
            api_client.list_engagement_education_programs(engagement["id"],
                                                          DIRECTOR))
        assert programs_meta["total_count"] == 1


class TestRentalSettlementWaterfall:

    def test_rental_settlement_marks_up_services_and_splits_nothing(self):
        """A four-wall night bills the facility fee, the crew and the marketing
        spend with a 15 percent markup on services and no artist split at all.
        40,000 of labor marks up to 46,000, total charges are
        700,000 + 46,000 + 100,000 = 846,000, the client owes that less its
        185,000 deposit, and the center's net is the charges less the raw
        service cost — 806,000, of which 5 percent sweeps to the reserve.

        PRD: "Step five writes `net_to_center_cents` as the total charges less
        `actual_labor_cents` less `actual_equipment_cents` — the markup, in
        other words, is the center's margin on services."

        Design: Corner/calculations/rental_settlement_bills_marked_up_services_and_no_artist_split
        """
        open_reserve_balance(10_000_000)
        space = register_hall()
        client = register_rental_client(credit_rating="A")
        department = register_union_department(department="STAGEHANDS",
                                              roster_size=10,
                                              straight_hourly_rate_cents=5_000)
        engagement = book_rental_engagement(space["id"], client["id"])
        assert engagement["facility_fee_cents"] == 700_000

        crew_call = call_crew(engagement["id"], department["id"], crew_size=2,
                              call_start_utc="2026-10-01T08:00:00Z",
                              call_end_utc="2026-10-01T12:00:00Z")
        assert crew_call["estimated_cost_cents"] == 40_000

        owner = make_rental_client_contact_headers(client["id"])
        rider = submit_rider(engagement["id"], owner)
        review_rider(rider["id"])
        clear_rider(rider["id"])

        assessed = assess_risk(engagement["id"])
        assert assessed["deposit_required_cents"] == 185_000
        record_deposit(engagement["id"], 185_000)
        confirm(engagement["id"], RENTAL_MANAGER)
        worked = report_hours(crew_call["id"], 4.0, True)
        assert worked["actual_cost_cents"] == 40_000

        set_clock("2026-10-03T00:00:00Z")
        settlement = validate_success(
            api_client.open_settlement(engagement["id"], FINANCE),
            expected_status=201)

        reconciled = validate_success(api_client.reconcile_settlement_expenses(
            settlement["id"], {"actual_marketing_cents": 100_000}, FINANCE))
        assert reconciled["actual_labor_cents"] == 40_000
        assert reconciled["actual_equipment_cents"] == 0
        assert reconciled["adjusted_gross_cents"] == 0
        assert reconciled["guarantee_cents"] == 0
        assert reconciled["reimbursable_expense_cap_cents"] == 0
        assert reconciled["reimbursable_expenses_cents"] == 0
        assert reconciled["artist_share_cents"] == 0
        assert reconciled["amount_payable_to_artist_cents"] == 0
        assert reconciled["balance_due_from_client_cents"] == 661_000
        assert reconciled["net_to_center_cents"] == 806_000
        assert reconciled["reserve_contribution_cents"] == 40_300

        finalized = validate_success(
            api_client.finalize_settlement(settlement["id"], FINANCE))
        assert finalized["status"] == "FINALIZED"

        after = read_engagement(engagement["id"])
        assert after["lifecycle_status"] == "SETTLED"
        assert after["realized_margin_cents"] == -140_000

        client_after = validate_success(
            api_client.get_rental_client(client["id"], RENTAL_MANAGER))
        assert client_after["outstanding_balance_cents"] == 661_000

        entries, meta = validate_paginated(
            api_client.list_reserve_ledger_entries(ADMIN, {"limit": 100}))
        contributions = [entry for entry in entries
                         if entry["entry_type"] == "SETTLEMENT_CONTRIBUTION"]
        assert len(contributions) == 1
        assert contributions[0]["amount_cents"] == 40_300
        assert contributions[0]["balance_after_cents"] == 10_040_300

        calls, _ = validate_paginated(
            api_client.list_engagement_labor_calls(engagement["id"],
                                                   TECH_DIRECTOR))
        assert calls[0]["status"] == "RECONCILED"


class TestRiskBandBoundary:

    def test_score_of_exactly_fifty_five_escalates_then_the_override_approves_it(self):
        """A grade-B client whose arrears exactly equal the deposit
        requirement, booked 122 days out so the lead-time term contributes
        nothing, scores 0.50 * 0.50 + 1 * 0.30 = 0.55 — exactly the HIGH lower
        bound. The first assessment escalates; a re-assessment carrying the
        override moves the clearance to ESCALATED_APPROVED without changing the
        score.

        PRD: "a score of 75 or more is `PROHIBITIVE`, a score of 55 or more is
        `HIGH`, a score of 35 or more is `MODERATE`, and anything below 35 is
        `LOW`."

        Design: Corner/calculations/risk_score_at_the_exact_high_band_boundary_then_override_approves_escalation
        """
        space = register_hall()
        client = register_rental_client(credit_rating="B",
                                        outstanding_balance_cents=250_000)
        engagement = book_rental_engagement(
            space["id"], client["id"],
            title="December Corporate Showcase",
            load_in_start_utc="2026-12-01T00:00:00Z",
            performance_start_utc="2026-12-01T00:00:00Z",
            performance_end_utc="2026-12-01T03:00:00Z",
            load_out_end_utc="2026-12-01T06:00:00Z",
            performance_day_count=1,
            load_in_day_count=0)
        assert engagement["facility_fee_cents"] == 500_000
        assert engagement["deposit_required_cents"] == 250_000
        version_before = engagement["version"]

        escalated = validate_success(api_client.assess_risk(
            engagement["id"],
            {"expected_engagement_version": version_before},
            FINANCE))
        assert escalated["risk_score"] == 55
        assert escalated["risk_tier"] == "HIGH"
        assert escalated["financial_clearance"] == "ESCALATED"

        approved = validate_success(api_client.assess_risk(
            engagement["id"],
            {"expected_engagement_version": escalated["version"],
             "override_escalation": True},
            FINANCE))
        assert approved["risk_score"] == 55
        assert approved["risk_tier"] == "HIGH"
        assert approved["financial_clearance"] == "ESCALATED_APPROVED"
        assert approved["version"] == escalated["version"] + 1
        assert approved["lifecycle_status"] == "DRAFT"
