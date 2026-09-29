"""
Endpoint shapes: true partial updates, an empty-population read, the two cancel
paths, a quota-bounded bulk mailing, and the link row that denormalizes its
campaign.
"""

from test_helpers import (
    AllocationStatus,
    CampaignStatus,
    RegionCode,
    RiskSeverity,
    SaleStatus,
    WaveStatus,
    WaveType,
    factories as f,
    fixtures as fx,
    read_list,
    validate_success,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_1, OPERATIONS_MANAGER

FIVE_NE_BUILDS = [
    {
        "vin": "1HGCM82633A004351",
        "production_date": "2024-03-11",
        "suspect_part_number": 1500,
        "owner_name": "Ann Vega",
    },
    {
        "vin": "1HGCM82633A004352",
        "production_date": "2024-03-12",
        "suspect_part_number": 1501,
        "owner_name": "Ben Ito",
    },
    {
        "vin": "1HGCM82633A004353",
        "production_date": "2024-03-13",
        "suspect_part_number": 1502,
        "owner_name": "Cara Lu",
    },
    {
        "vin": "1HGCM82633A004354",
        "production_date": "2024-03-14",
        "suspect_part_number": 1503,
        "owner_name": "Dan Roe",
    },
    {
        "vin": "1HGCM82633A004355",
        "production_date": "2024-03-15",
        "suspect_part_number": 1504,
        "owner_name": "Eve Sato",
    },
]


def test_patching_only_the_owner_name_leaves_every_other_field_alone(api):
    """
    Every updatable field is optional, so a body carrying `owner_name` alone rewrites
    the owner and nothing else: the disposition fields keep the values they were
    created with, the immutable build data is untouched, and the record advances one
    version.

    PRD §3.2: "A build record's disposition and owner data can later be updated,
    supplying any of `sale_status`, `owner_name`, `owner_address_valid` and
    `region_code`."

    PRD §2.4: "and `version`, an integer that starts at 1 on creation and increments
    by exactly 1 on every mutation of that record — including mutations that only
    touch derived counters."

    Design: Corner/endpoints/patching_only_the_owner_name_leaves_every_other_vehicle_field_alone
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    created = fx.create_vehicle(
        api,
        vin="1HGCM82633A004352",
        plant_code="PLT1",
        production_date="2024-03-15",
        suspect_part_number=1500,
        region_code=RegionCode.NE,
        sale_status=SaleStatus.SOLD,
        owner_name="A. Nolan",
        owner_address_valid=True,
    )
    assert created["version"] == 1

    updated = validate_success(
        api.update_vehicle(
            created["id"], f.vehicle_update_payload(owner_name="B. Okonkwo"), OPERATIONS_MANAGER
        ),
        200,
    )

    assert updated["owner_name"] == "B. Okonkwo"
    assert updated["sale_status"] == SaleStatus.SOLD
    assert updated["region_code"] == RegionCode.NE
    assert updated["owner_address_valid"] is True
    assert updated["vin"] == "1HGCM82633A004352"
    assert updated["plant_code"] == "PLT1"
    assert updated["production_date"] == "2024-03-15"
    assert updated["suspect_part_number"] == 1500
    assert updated["version"] == 2
    assert updated["updated_at"] >= updated["created_at"]


def test_completion_metrics_on_an_empty_population_reports_all_zeroes(api):
    """
    Nothing has been matched, so both completion denominators are zero and both rates
    fall back to 0.00 — while the effectiveness score, which starts from its ceiling
    and only ever loses points, reads 100.00.

    PRD §3.9: "The rate is one hundred times the numerator divided by the
    denominator, rounded half up to two decimal places, and is reported as 0.00
    whenever the denominator is zero."

    PRD §3.9: "`remedy_effectiveness_score` starts from 100.00 points, from which
    three deductions are taken."

    Design: Corner/endpoints/completion_metrics_on_an_empty_population_returns_all_zeroes
    """
    state = fx.draft_campaign(api, campaign_number="26V-326")

    metrics = validate_success(
        api.get_completion_metrics(state["campaign_id"], COMPLIANCE_OFFICER_1), 200
    )

    assert metrics["affected_vehicle_count"] == 0
    assert metrics["recall_population_count"] == 0
    assert metrics["remedied_count"] == 0
    assert metrics["scheduled_count"] == 0
    assert metrics["unreachable_count"] == 0
    assert metrics["removed_count"] == 0
    assert metrics["repeat_claim_count"] == 0
    assert metrics["regulatory_completion_rate_pct"] == 0.00
    assert metrics["operational_completion_rate_pct"] == 0.00
    assert metrics["remedy_effectiveness_score"] == 100.00


def test_cancelling_a_released_wave_retains_its_pinned_quota_fields(api):
    """
    Cancel is legal from both open states and the two behave differently: the wave
    cancelled out of RELEASE_APPROVED keeps the six figures pinned at release for
    audit, while the wave cancelled straight out of PLANNED still shows the zero
    defaults it was created with.

    PRD §3.6: "Cancellation from `RELEASE_APPROVED` retains the pinned quota fields
    for audit rather than clearing them."

    PRD §3.6: "A planned wave starts in status `PLANNED` with `auto_created` false,
    all its quota fields at their zero defaults, `mailed_vehicle_count` 0, and
    `actual_mail_date` and `cancel_reason` unset."

    Design: Corner/endpoints/cancelling_a_released_wave_keeps_its_pinned_quota_fields
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-327"})
    fx.issue_interim_advisory(
        api, state["campaign_id"], stop_sale=False, do_not_drive=False
    )

    first = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.INTERIM,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-20",
    )
    fx.release_wave(api, first["id"])
    second = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.INTERIM,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-09-05",
    )

    cancelled_after_release = validate_success(
        api.cancel_wave(
            first["id"],
            f.cancel_wave_payload(cancel_reason="Consolidated into a national drop"),
            OPERATIONS_MANAGER,
        ),
        200,
    )
    assert cancelled_after_release["status"] == WaveStatus.CANCELLED
    assert cancelled_after_release["cancel_reason"] == "Consolidated into a national drop"
    assert cancelled_after_release["eligible_vehicle_count"] == 1
    assert cancelled_after_release["parts_capacity_qty"] == 1
    assert cancelled_after_release["provisional_coverage_ratio"] == 1.0000
    assert cancelled_after_release["coverage_tier_factor"] == 1.00
    assert cancelled_after_release["planned_vehicle_count"] == 1
    assert cancelled_after_release["parts_coverage_ratio"] == 1.0000
    assert cancelled_after_release["mailed_vehicle_count"] == 0
    assert cancelled_after_release["actual_mail_date"] is None

    cancelled_from_planned = validate_success(
        api.cancel_wave(second["id"], {}, OPERATIONS_MANAGER), 200
    )
    assert cancelled_from_planned["status"] == WaveStatus.CANCELLED
    assert cancelled_from_planned["cancel_reason"] is None
    assert cancelled_from_planned["eligible_vehicle_count"] == 0
    assert cancelled_from_planned["planned_vehicle_count"] == 0
    assert cancelled_from_planned["provisional_coverage_ratio"] == 0.0000

    read_list(
        api.list_notification_waves(
            state["campaign_id"], OPERATIONS_MANAGER, {"status": WaveStatus.CANCELLED}
        ),
        expected_total=2,
    )


def test_mailing_stamps_only_the_planned_count_oldest_builds_first(api):
    """
    Four uncommitted kits against five eligible owners gives a 0.8000 ratio, the 0.75
    tier and a planned count of 3, so the single drop stamps exactly the three oldest
    builds by `production_date` and leaves the two newest owners un-mailed.

    PRD §3.6: "On the drop, the server re-derives the eligible rows and stamps the
    **first `planned_vehicle_count` of them, ordered by their build record's
    `production_date` ascending and then by the affected-vehicle row's own
    `created_at` ascending** — oldest builds first."

    PRD §3.6: "The wave records the number of rows actually stamped as
    `mailed_vehicle_count` and the clock instant as `actual_mail_date`, and its
    status advances to `MAILED`, which is terminal."

    Design: Corner/endpoints/mailing_a_wave_stamps_only_the_planned_count_in_production_date_order
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=4,
        vehicles=FIVE_NE_BUILDS,
        campaign={"campaign_number": "26V-328", "risk_severity": RiskSeverity.LOW},
        labor_operation={"labor_op_code": "R328-01"},
        remedy_part={"part_number": "P-88328", "total_procured_qty": 100},
    )
    wave = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-03",
    )
    fx.release_wave(api, wave["id"])

    mailed = validate_success(api.mail_wave(wave["id"], {}, OPERATIONS_MANAGER), 200)

    assert mailed["status"] == WaveStatus.MAILED
    assert mailed["eligible_vehicle_count"] == 5
    assert mailed["parts_capacity_qty"] == 4
    assert mailed["provisional_coverage_ratio"] == 0.8000
    assert mailed["coverage_tier_factor"] == 0.75
    assert mailed["planned_vehicle_count"] == 3
    assert mailed["parts_coverage_ratio"] == 1.3333
    assert mailed["mailed_vehicle_count"] == 3
    assert mailed["actual_mail_date"].startswith("2026-08-03")

    stamped, _ = read_list(
        api.list_affected_vehicles(
            OPERATIONS_MANAGER, {"notification_wave_id": wave["id"], "limit": 100}
        ),
        expected_total=3,
    )
    oldest_three = {vehicle["id"] for vehicle in state["vehicles"][:3]}
    assert {row["vehicle_id"] for row in stamped} == oldest_three

    for vehicle in state["vehicles"][3:]:
        untouched = fx.find_affected_vehicle(api, state["campaign_id"], vehicle["id"])
        assert untouched["notice_count"] == 0
        assert untouched["notification_wave_id"] is None
        assert untouched["last_notice_type"] is None

    assert fx.read_campaign(api, state["campaign_id"])["campaign_status"] == (
        CampaignStatus.OWNER_NOTIFIED
    )


def test_allocation_denormalizes_the_campaign_it_was_never_given(api):
    """
    The body names only a remedy part and a dealer, yet the row comes back carrying
    the part's parent campaign — and that copied key filters the collection just as
    the two supplied ids do.

    PRD §3.5: "Otherwise the new allocation records that quantity as
    `allocated_qty`, records `partially_granted` as true exactly when the granted
    quantity is less than the `requested_qty` and false when it equals it, starts
    `consumed_qty` at 0, and denormalizes `campaign_id` from the remedy part."

    PRD §3.5: "Allocation listings accept `remedy_part_id`, `dealer_id`,
    `campaign_id` and `status` filters."

    Design: Corner/endpoints/allocation_links_a_part_and_a_dealer_and_denormalizes_the_campaign
    """
    state = fx.filed_campaign(
        api,
        campaign={"campaign_number": "26V-329"},
        vehicles=FIVE_NE_BUILDS[:3],
    )
    campaign_id = state["campaign_id"]
    part = fx.add_remedy_part(
        api, campaign_id, part_number="P-88329", total_procured_qty=100
    )
    dealer = fx.create_dealer(api)

    allocation = validate_success(
        api.create_parts_allocation(
            f.parts_allocation_payload(
                part["id"], dealer["id"], part["version"], requested_qty=3
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )

    assert allocation["remedy_part_id"] == part["id"]
    assert allocation["dealer_id"] == dealer["id"]
    assert allocation["campaign_id"] == campaign_id
    assert allocation["requested_qty"] == 3
    assert allocation["allocated_qty"] == 3
    assert allocation["consumed_qty"] == 0
    assert allocation["partially_granted"] is False
    assert allocation["status"] == AllocationStatus.ALLOCATED

    for filters in (
        {"campaign_id": campaign_id},
        {"dealer_id": dealer["id"]},
        {"remedy_part_id": part["id"]},
    ):
        rows, _ = read_list(
            api.list_parts_allocations(OPERATIONS_MANAGER, filters), expected_total=1
        )
        assert rows[0]["id"] == allocation["id"]

    pool = fx.read_part(api, campaign_id, "P-88329")
    assert pool["unallocated_qty"] == 97
    assert pool["consumed_qty"] == 0
