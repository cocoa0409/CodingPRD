"""
The arithmetic the contract pins: the business-day filing deadline, the
idempotent population match, the three-cap allocation nest, the six-step wave
quota, the oldest-holding parts pick, the regional rate ceiling and the
effectiveness deductions.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    CampaignStatus,
    ClaimStatus,
    InclusionMode,
    OutreachChannel,
    OutreachOutcome,
    RegionCode,
    VehicleRemedyStatus,
    WaveStatus,
    WaveType,
    factories as f,
    fixtures as fx,
    get_success_data,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
)

THREE_NE_BUILDS = [
    {
        "vin": "1HGCM82633A004352",
        "production_date": "2024-03-15",
        "suspect_part_number": 1500,
        "owner_name": "Ann Vega",
    },
    {
        "vin": "1HGCM82633A004353",
        "production_date": "2024-03-16",
        "suspect_part_number": 1501,
        "owner_name": "Ben Ito",
    },
    {
        "vin": "1HGCM82633A004354",
        "production_date": "2024-03-17",
        "suspect_part_number": 1502,
        "owner_name": "Cara Lu",
    },
]

TWO_NE_BUILDS = THREE_NE_BUILDS[:2]


def test_filing_deadline_counts_five_business_days_over_a_weekend(api):
    """
    A Monday determination counts Tuesday through Friday as four, skips the
    weekend entirely, and lands on the following Monday as the fifth, so the
    deadline is 2026-08-10 and not the 2026-08-08 a calendar count would give.

    PRD §3.1: "Starting from the UTC calendar date of `defect_determination_date`,
    the server steps forward one calendar day at a time, counting a day only when
    it falls Monday through Friday and is not a federal holiday, until five such
    days have been counted; `filing_deadline_utc` is that fifth counted date
    pinned to 23:59:59Z."

    PRD §3.1: "The determination date's own day is never counted, since counting
    begins after the first step forward."

    Design: Corner/calculations/filing_deadline_is_five_business_days_after_determination
    """
    state = fx.draft_campaign(api, clock="2026-08-03T09:00:00Z", campaign_number="26V-300")

    campaign = validate_success(
        api.record_defect_determination(
            state["campaign_id"],
            f.defect_determination_payload(defect_determination_date="2026-08-03T09:00:00Z"),
            SAFETY_ENGINEER_1,
        ),
        200,
    )

    assert campaign["filing_deadline_utc"] == "2026-08-10T23:59:59Z"
    assert campaign["days_late"] == 0
    assert campaign["late_filing_flag"] is False
    assert campaign["filed_at"] is None


def test_filing_deadline_steps_over_the_declared_federal_holiday(api):
    """
    Counting from Tuesday 2026-09-01 reaches three by Friday, then Monday
    2026-09-07 is on the honoured holiday calendar and is not counted, so the fifth
    business day is Wednesday 2026-09-09 rather than the 2026-09-08 a
    weekend-only calendar would produce.

    PRD §3.1: "The federal holiday calendar the system honours consists of exactly
    these dates: 2026-01-01, 2026-07-03, 2026-09-07, 2026-11-26, 2026-12-25, and
    2027-01-01."

    PRD §3.1: "Starting from the UTC calendar date of `defect_determination_date`,
    the server steps forward one calendar day at a time, counting a day only when
    it falls Monday through Friday and is not a federal holiday, until five such
    days have been counted; `filing_deadline_utc` is that fifth counted date
    pinned to 23:59:59Z."

    Design: Corner/calculations/filing_deadline_skips_the_declared_federal_holiday
    """
    state = fx.draft_campaign(api, clock="2026-09-01T09:00:00Z", campaign_number="26V-301")

    campaign = validate_success(
        api.record_defect_determination(
            state["campaign_id"],
            f.defect_determination_payload(defect_determination_date="2026-09-01T09:00:00Z"),
            SAFETY_ENGINEER_1,
        ),
        200,
    )

    assert campaign["filing_deadline_utc"] == "2026-09-09T23:59:59Z"
    assert campaign["days_late"] == 0
    assert campaign["late_filing_flag"] is False


def test_lateness_is_strict_and_partial_days_round_up(api):
    """
    Two campaigns share the deadline instant 2026-08-10T23:59:59Z. Filing exactly
    at it is timely; filing 86401 seconds later is 1.0000116 days over, and
    because the count rounds up it records two days late, not one.

    PRD §3.3: "`late_filing_flag` becomes true when `filed_at` is **strictly
    after** `filing_deadline_utc`, and false when `filed_at` falls on or before
    it."

    PRD §3.3: "When the flag is true, `days_late` is the number of whole days
    between the deadline and the filing, computed by dividing the elapsed time by
    86400 seconds and rounding **up** to the next whole day, so that even a filing
    one minute past the deadline records one day late; when the flag is false
    `days_late` stays 0."

    Design: Corner/calculations/filing_exactly_at_the_deadline_instant_is_timely_but_one_day_later_is_late
    """
    timely = fx.determined_campaign(api, campaign_number="26V-302")
    late = fx.determined_campaign(
        api,
        clock=None,
        campaign_number="26V-303",
        defect_description="Inflator may rupture in the second lot",
    )
    assert timely["campaign"]["filing_deadline_utc"] == "2026-08-10T23:59:59Z"
    assert late["campaign"]["filing_deadline_utc"] == "2026-08-10T23:59:59Z"

    fx.set_clock(api, "2026-08-10T23:59:59Z")
    on_time = fx.file_defect_notice(
        api, timely["campaign_id"], narrative="Part 573 defect information report for 26V-302"
    )
    assert on_time["filed_at"].startswith("2026-08-10T23:59:59")
    assert on_time["days_late"] == 0

    first = fx.read_campaign(api, timely["campaign_id"])
    assert first["late_filing_flag"] is False
    assert first["days_late"] == 0
    assert first["campaign_status"] == CampaignStatus.FILED

    fx.set_clock(api, "2026-08-12T00:00:00Z")
    overdue = fx.file_defect_notice(
        api, late["campaign_id"], narrative="Part 573 defect information report for 26V-303"
    )
    assert overdue["filed_at"].startswith("2026-08-12T00:00:00")
    assert overdue["days_late"] == 2

    second = fx.read_campaign(api, late["campaign_id"])
    assert second["late_filing_flag"] is True
    assert second["days_late"] == 2


def test_population_rerun_over_an_unchanged_fleet_matches_nothing(api):
    """
    The matcher skips build records that already carry a row, so the second pass
    reports every counter at zero while the campaign's own totals stay where the
    first pass left them — and the rule still claims its one vehicle.

    PRD §3.2: "A vehicle that already has an affected-vehicle row for this
    campaign is skipped without change."

    PRD §3.2: "Matching is a separate, explicitly triggered pass that either a
    `SafetyEngineer` or a `RecallOperationsManager` may run, and it is idempotent:
    running it repeatedly never disturbs rows it already created."

    Design: Corner/calculations/population_rerun_matches_nothing_new_and_leaves_counters_unchanged
    """
    state = fx.campaign_with_population(
        api, campaign={"campaign_number": "26V-304", "defect_description": "Inflator may rupture"}
    )

    rerun = validate_success(
        api.run_population(state["campaign_id"], {}, OPERATIONS_MANAGER), 201
    )

    assert rerun["matched_count"] == 0
    assert rerun["excluded_count"] == 0
    assert rerun["removed_count"] == 0
    assert rerun["affected_vehicle_count"] == 1
    assert rerun["recall_population_count"] == 1

    read_list(
        api.list_affected_vehicles(OPERATIONS_MANAGER, {"campaign_id": state["campaign_id"]}),
        expected_total=1,
    )

    rules, _ = read_list(
        api.list_population_rules(state["campaign_id"], SAFETY_ENGINEER_1), expected_total=1
    )
    assert rules[0]["matched_vehicle_count"] == 1


def test_exclude_rule_carves_one_build_out_of_a_two_car_match(api):
    """
    The broad INCLUDE rule reaches both cars; the narrow EXCLUDE rule covers only
    the March build window, so the May car keeps the same suspect part number and
    survives — one matched, one excluded.

    PRD §3.2: "A vehicle that did match an `INCLUDE` rule but also matches any of
    the campaign's `EXCLUDE` rules is carved out, and the run counts it in
    `excluded_count`."

    PRD §3.2: "`EXCLUDE` rules are exempt from the overlap rule entirely."

    Design: Corner/calculations/exclude_rule_carves_a_matched_build_back_out_of_the_population
    """
    state = fx.draft_campaign(api, campaign_number="26V-305")
    campaign_id = state["campaign_id"]

    march = fx.create_vehicle(
        api, vin="1HGCM82633A004352", production_date="2024-03-15", suspect_part_number=1500
    )
    may = fx.create_vehicle(
        api, vin="1HGCM82633A004353", production_date="2024-05-15", suspect_part_number=1500
    )

    fx.add_population_rule(api, campaign_id)
    fx.add_population_rule(
        api,
        campaign_id,
        inclusion_mode=InclusionMode.EXCLUDE,
        production_start_date="2024-03-01",
        production_end_date="2024-04-01",
        part_number_low=1500,
        part_number_high=1500,
    )
    fx.determine_defect(api, campaign_id)

    run = validate_success(api.run_population(campaign_id, {}, OPERATIONS_MANAGER), 201)

    assert run["matched_count"] == 1
    assert run["excluded_count"] == 1
    assert run["affected_vehicle_count"] == 1
    assert run["recall_population_count"] == 1

    read_list(
        api.list_affected_vehicles(
            OPERATIONS_MANAGER, {"campaign_id": campaign_id, "vehicle_id": march["id"]}
        ),
        expected_total=0,
    )
    survivors, _ = read_list(
        api.list_affected_vehicles(
            OPERATIONS_MANAGER, {"campaign_id": campaign_id, "vehicle_id": may["id"]}
        ),
        expected_total=1,
    )
    assert survivors[0]["remedy_status"] == VehicleRemedyStatus.UNREPAIRED

    read_list(
        api.list_population_rules(
            campaign_id, SAFETY_ENGINEER_1, {"inclusion_mode": InclusionMode.EXCLUDE}
        ),
        expected_total=1,
    )


def test_allocation_grant_binds_on_the_dealers_monthly_capacity(api):
    """
    Three constraints compete over one request for five kits: regional demand
    allows three and the pool holds a hundred, but the dealer's capacity of two is
    the tightest, so two are granted and the pool falls to 98.

    PRD §3.5: "The dealer-side cap is the smallest of the `requested_qty`, the
    dealer's `monthly_repair_capacity`, and the regional demand count multiplied
    by the one kit each repair consumes."

    PRD §3.5: "records `partially_granted` as true exactly when the granted
    quantity is less than the `requested_qty` and false when it equals it, starts
    `consumed_qty` at 0, and denormalizes `campaign_id` from the remedy part."

    Design: Corner/calculations/allocation_grant_is_capped_by_the_dealers_monthly_repair_capacity
    """
    state = fx.campaign_with_remedy(
        api,
        vehicles=THREE_NE_BUILDS,
        campaign={"campaign_number": "26V-306"},
        labor_operation={"labor_op_code": "R306-01"},
        remedy_part={"part_number": "P-88306"},
    )
    dealer = fx.create_dealer(
        api,
        dealer_code="D-NE-02",
        name="Harbor Auto",
        region_code=RegionCode.NE,
        labor_rate_per_hour=138.74,
        monthly_repair_capacity=2,
    )

    allocation = validate_success(
        api.create_parts_allocation(
            f.parts_allocation_payload(
                state["remedy_part_id"],
                dealer["id"],
                fx.part_version(api, state["campaign_id"], "P-88306"),
                requested_qty=5,
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )

    assert allocation["requested_qty"] == 5
    assert allocation["allocated_qty"] == 2
    assert allocation["partially_granted"] is True
    assert allocation["status"] == AllocationStatus.ALLOCATED
    assert allocation["consumed_qty"] == 0
    assert allocation["campaign_id"] == state["campaign_id"]

    part = fx.read_part(api, state["campaign_id"], "P-88306")
    assert part["unallocated_qty"] == 98
    assert part["consumed_qty"] == 0


def test_wave_quota_carries_four_decimal_ratios_through_the_tier(api):
    """
    One kit against three eligible owners is 0.3333 at four decimals, which clears
    the LOW floor exactly, selects the 0.40 tier and floors the mailing to one
    owner — whereupon the reported ratio flips to 1.0000, because its denominator
    is the planned count and not the eligible one.

    PRD §3.6: "*Step 3 — the coverage gate.* `provisional_coverage_ratio` is the
    `parts_capacity_qty` divided by the `eligible_vehicle_count`, rounded half up
    to four decimal places."

    PRD §3.6: "*Step 6 — the reported coverage.* `parts_coverage_ratio` is the
    `parts_capacity_qty` divided by the `planned_vehicle_count`, rounded half up
    to four decimal places."

    Design: Corner/calculations/wave_release_ratios_are_rounded_to_four_decimal_places
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        vehicles=THREE_NE_BUILDS,
        campaign={
            "campaign_number": "26V-307",
            "defect_type": "NONCOMPLIANCE",
            "defect_description": "Label print quality below standard",
            "risk_severity": "LOW",
        },
        labor_operation={
            "labor_op_code": "R307-01",
            "description": "Apply corrected certification label",
        },
        remedy_part={"part_number": "P-88307"},
        narrative="Part 573 noncompliance information report for 26V-307",
    )
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-03",
    )

    released = validate_success(api.release_wave(wave["id"], {}, OPERATIONS_MANAGER), 200)

    assert released["status"] == WaveStatus.RELEASE_APPROVED
    assert released["eligible_vehicle_count"] == 3
    assert released["parts_capacity_qty"] == 1
    assert released["provisional_coverage_ratio"] == 0.3333
    assert released["coverage_tier_factor"] == 0.40
    assert released["planned_vehicle_count"] == 1
    assert released["parts_coverage_ratio"] == 1.0000


def test_high_severity_release_below_full_coverage_is_refused(api):
    """
    A ratio of 0.5000 would have cleared a LOW campaign and even earned the 0.40
    tier, but HIGH severity demands 1.0000, so the release is refused at the gate
    and nothing is pinned onto the wave.

    PRD §3.6: "The required minimum is selected by the campaign's `risk_severity`:
    a `HIGH`-severity campaign requires a ratio of at least 1.0000 — one kit
    reachable per eligible owner — a `MODERATE` campaign at least 0.6000, and a
    `LOW` campaign at least 0.3000."

    PRD §3.6: "A ratio exactly equal to the requirement passes; a ratio below it
    is rejected with `ERR_INSUFFICIENT_PARTS_COVERAGE`."

    Design: Corner/calculations/high_severity_wave_release_below_full_coverage_is_rejected
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        vehicles=TWO_NE_BUILDS,
        campaign={"campaign_number": "26V-308", "risk_severity": "HIGH"},
        labor_operation={"labor_op_code": "R308-01"},
        remedy_part={"part_number": "P-88308"},
    )
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-03",
    )

    validate_error(
        api.release_wave(wave["id"], {}, OPERATIONS_MANAGER),
        ApiErrorId.INSUFFICIENT_PARTS_COVERAGE,
        409,
    )

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER), expected_total=1
    )
    untouched = waves[0]
    assert untouched["status"] == WaveStatus.PLANNED
    assert untouched["eligible_vehicle_count"] == 0
    assert untouched["parts_capacity_qty"] == 0
    assert untouched["provisional_coverage_ratio"] == 0.0000
    assert untouched["coverage_tier_factor"] == 0.00
    assert untouched["planned_vehicle_count"] == 0


def test_claim_reserves_the_oldest_of_two_holdings(api):
    """
    The dealer holds one kit of each of two parts; the picker is strictly oldest
    first, so the claim attaches to the earlier allocation and, on approval, burns
    a unit from that part alone.

    PRD §3.7: "the server ranks candidates by `created_at` ascending so the oldest
    holding drains first, breaking a tie on identical `created_at` by preferring
    the larger `allocated_qty`, and records the first candidate as the claim's
    `parts_allocation_id`."

    PRD §2.9: "Approving a repair claim increments both the source allocation's
    `consumed_qty` and the remedy part's `consumed_qty` by one."

    Design: Corner/calculations/claim_draws_from_the_oldest_allocated_holding_first
    """
    state = fx.campaign_with_remedy(
        api,
        campaign={"campaign_number": "26V-309"},
        labor_operation={"labor_op_code": "R309-01"},
        remedy_part={"part_number": "P-88309A"},
    )
    second_part = fx.add_remedy_part(api, state["campaign_id"], part_number="P-88309B")
    dealer = fx.create_dealer(api)

    first_allocation = fx.allocate_parts(
        api,
        state["campaign_id"],
        "P-88309A",
        state["remedy_part_id"],
        dealer["id"],
        requested_qty=1,
    )
    second_allocation = fx.allocate_parts(
        api,
        state["campaign_id"],
        "P-88309B",
        second_part["id"],
        dealer["id"],
        requested_qty=1,
    )

    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    claim = fx.submit_claim(
        api,
        row["id"],
        dealer["id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    assert claim["parts_allocation_id"] == first_allocation["id"]
    assert claim["provisional_amount_cents"] == 18980

    audited = validate_success(
        api.audit_repair_claim(
            claim["id"],
            f.audit_payload(decision="APPROVE", audit_note="Repair order verified"),
            CLAIMS_AUDITOR,
        ),
        200,
    )
    assert audited["status"] == ClaimStatus.APPROVED
    assert audited["final_amount_cents"] == 18980

    drained = get_success_data(
        api.get_parts_allocation(first_allocation["id"], OPERATIONS_MANAGER)
    )
    assert drained["consumed_qty"] == 1
    assert drained["status"] == AllocationStatus.ALLOCATED

    spared = get_success_data(
        api.get_parts_allocation(second_allocation["id"], OPERATIONS_MANAGER)
    )
    assert spared["consumed_qty"] == 0
    assert spared["status"] == AllocationStatus.ALLOCATED

    part_a = fx.read_part(api, state["campaign_id"], "P-88309A")
    assert part_a["consumed_qty"] == 1
    assert part_a["unallocated_qty"] == 99

    part_b = fx.read_part(api, state["campaign_id"], "P-88309B")
    assert part_b["consumed_qty"] == 0
    assert part_b["unallocated_qty"] == 99


def test_audited_amount_caps_the_dealer_rate_at_the_northeast_ceiling(api):
    """
    The dealer's posted 152.30 sits thirty cents above the NE ceiling, and the cap
    bites only on the audited variant: 32363 cents provisional at the full rate
    for 1.55 hours and three kits becomes 20439 at 1.10 capped hours and one kit,
    and only the audited figure reaches the ledger.

    PRD §3.7: "The effective rate is the smaller of the dealer's
    `labor_rate_per_hour` and the regional rate ceiling for the dealer's
    `region_code`, which is 152.00 dollars per hour in `NE`, 128.50 in `SE`,
    121.75 in `MW`, and 165.25 in `WE`."

    PRD §3.7: "The labor component is the `claimed_labor_hours` multiplied by the
    dealer's `labor_rate_per_hour`, rounded to two decimal places."

    Design: Corner/calculations/final_claim_amount_caps_the_dealer_rate_at_the_regional_maximum
    """
    state = fx.campaign_with_submitted_claim(
        api,
        requested_qty=1,
        dealer={
            "dealer_code": "D-NE-03",
            "name": "Summit Motors",
            "region_code": RegionCode.NE,
            "labor_rate_per_hour": 152.30,
            "monthly_repair_capacity": 40,
        },
        claim={"repair_date": "2026-08-03", "claimed_labor_hours": 1.55, "parts_used_qty": 3},
        campaign={"campaign_number": "26V-310"},
        labor_operation={"labor_op_code": "R310-01"},
        remedy_part={"part_number": "P-88310"},
    )

    audited = validate_success(
        api.audit_repair_claim(
            state["claim_id"],
            f.audit_payload(decision="APPROVE", audit_note="Rate capped to the regional maximum"),
            CLAIMS_AUDITOR,
        ),
        200,
    )

    assert audited["status"] == ClaimStatus.APPROVED
    assert audited["provisional_amount_cents"] == 32363
    assert audited["final_amount_cents"] == 20439

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 20439

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 1

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.REMEDIED
    assert row["approved_claim_count"] == 1


def test_effectiveness_score_takes_only_the_unreachable_deduction(api):
    """
    Half the population is unreachable and the other half is repaired once, so the
    repeat term contributes nothing and the score is 100.00 less 20.00 times
    0.5000 — while the same population reads 50.00 regulatory against 100.00
    operational.

    PRD §3.9: "The **unreachable rate** is the number of `UNREACHABLE` rows
    divided by the campaign's `recall_population_count`, rounded half up to four
    decimal places, and 0.0000 when `recall_population_count` is zero; the
    deduction is 20.00 points multiplied by that rate."

    PRD §3.9: "A campaign's completion-metrics reading returns both side by side
    as `regulatory_completion_rate_pct` and `operational_completion_rate_pct`,
    together with `remedied_count`, `scheduled_count`, `unreachable_count`,
    `removed_count`, `recall_population_count`, `affected_vehicle_count`,
    `remedy_effectiveness_score` and `repeat_claim_count`."

    Design: Corner/calculations/effectiveness_score_drops_by_the_unreachable_weight
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        vehicles=TWO_NE_BUILDS,
        campaign={"campaign_number": "26V-311"},
        labor_operation={"labor_op_code": "R311-01"},
        remedy_part={"part_number": "P-88311"},
    )
    repaired_row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    lost_row = fx.find_affected_vehicle(
        api, state["campaign_id"], state["vehicles"][1]["id"]
    )

    fx.log_outreach(
        api,
        lost_row["id"],
        channel=OutreachChannel.MAIL,
        outcome=OutreachOutcome.BAD_ADDRESS,
        note="Notice returned undeliverable",
    )
    claim = fx.submit_claim(
        api,
        repaired_row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    fx.audit_claim(api, claim["id"], audit_note="Repair order verified")

    metrics = validate_success(
        api.get_completion_metrics(state["campaign_id"], COMPLIANCE_OFFICER_1), 200
    )

    assert metrics["recall_population_count"] == 2
    assert metrics["affected_vehicle_count"] == 2
    assert metrics["remedied_count"] == 1
    assert metrics["unreachable_count"] == 1
    assert metrics["scheduled_count"] == 0
    assert metrics["removed_count"] == 0
    assert metrics["repeat_claim_count"] == 0
    assert metrics["regulatory_completion_rate_pct"] == 50.00
    assert metrics["operational_completion_rate_pct"] == 100.00
    assert metrics["remedy_effectiveness_score"] == 90.00

    lost = get_success_data(api.get_affected_vehicle(lost_row["id"], OPERATIONS_MANAGER))
    assert lost["remedy_status"] == VehicleRemedyStatus.UNREACHABLE
    assert lost["outreach_attempt_count"] == 1
