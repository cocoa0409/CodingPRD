"""
Cross-cutting layers: the two optimistic-concurrency guards, the write counter that
advances by exactly one per accepted write, and the effectiveness score sitting
exactly on the revision floor.
"""

from test_helpers import (
    ApiErrorId,
    AuditDecision,
    CampaignStatus,
    FilingStatus,
    RegionCode,
    RemedyStatus,
    RiskSeverity,
    VehicleRemedyStatus,
    WaveType,
    factories as f,
    fixtures as fx,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
    SAFETY_ENGINEER_2,
    SAFETY_ENGINEER_2_ID,
)

TEN_NE_BUILDS = [
    {
        "vin": f"1HGCM82633A0044{index:02d}",
        "production_date": f"2024-03-{index + 1:02d}",
        "suspect_part_number": 1500 + index,
        "owner_name": f"Owner {index + 1:02d}",
    }
    for index in range(10)
]

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


def test_remedy_release_with_a_stale_campaign_version_returns_conflict(api):
    """
    The token is read before a population run bumps the campaign version on nothing but
    derived counters, so the release arrives with a value that was correct when it was
    fetched: the guard refuses it, the remedy dimension does not move, and the refusal
    itself consumes no version, so the refreshed token is exactly one higher.

    PRD §2.8: "When the supplied value does not equal the campaign's current `version`,
    the release is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

    PRD §2.4: "and `version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that record — including mutations that only touch
    derived counters."

    Design: Corner/cross_cutting_layers/remedy_release_with_a_stale_campaign_version_returns_conflict
    """
    state = fx.draft_campaign(api, campaign_number="26V-342")
    campaign_id = state["campaign_id"]
    fx.create_vehicle(api)
    fx.add_population_rule(api, campaign_id)
    fx.determine_defect(api, campaign_id)
    fx.file_defect_notice(api, campaign_id)
    labor_operation = fx.add_labor_operation(
        api,
        campaign_id,
        labor_op_code="R342-01",
        flat_hours=1.10,
        effective_from="2026-08-01",
        effective_to="2027-12-31",
    )

    stale_version = fx.campaign_version(api, campaign_id, SAFETY_ENGINEER_2)
    fx.run_population(api, campaign_id)

    response = api.release_remedy(
        campaign_id,
        f.remedy_release_payload(labor_operation["id"], stale_version),
        SAFETY_ENGINEER_2,
    )
    validate_error(response, ApiErrorId.STALE_CAMPAIGN_VERSION, 412)

    refused = fx.read_campaign(api, campaign_id)
    assert refused["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT
    assert refused["remedy_released_at"] is None

    fresh_version = refused["version"]
    assert fresh_version == stale_version + 1

    released = validate_success(
        api.release_remedy(
            campaign_id,
            f.remedy_release_payload(labor_operation["id"], fresh_version),
            SAFETY_ENGINEER_2,
        ),
        200,
    )
    assert released["remedy_status"] == RemedyStatus.REMEDY_RELEASED
    assert released["remedy_released_by_user_id"] == SAFETY_ENGINEER_2_ID
    assert released["remedy_revision_count"] == 0


def test_parts_allocation_with_a_stale_part_version_returns_conflict(api):
    """
    Two allocations reach for the same inventory carrying the same token: the first
    succeeds and bumps the remedy part's version, so the second is refused and the pool
    stays exactly where the first allocation left it.

    PRD §2.8: "When the supplied value does not equal that remedy part's current
    `version`, the create is rejected with `ERR_STALE_PART_VERSION` (HTTP 412)."

    PRD §3.5: "The remedy part's `unallocated_qty` is reduced by the granted quantity
    and its `version` increments by 1."

    Design: Corner/cross_cutting_layers/parts_allocation_with_a_stale_part_version_returns_conflict
    """
    state = fx.filed_campaign(
        api, campaign={"campaign_number": "26V-343"}, vehicles=TEN_NE_BUILDS
    )
    campaign_id = state["campaign_id"]
    part = fx.add_remedy_part(
        api, campaign_id, part_number="P-88343", total_procured_qty=100
    )
    stale_part_version = part["version"]

    first_dealer = fx.create_dealer(api)
    second_dealer = fx.create_dealer(
        api, dealer_code="D-NE-02", name="Harbor Motors", labor_rate_per_hour=141.00
    )

    first_allocation = validate_success(
        api.create_parts_allocation(
            f.parts_allocation_payload(
                part["id"], first_dealer["id"], stale_part_version, requested_qty=10
            ),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert first_allocation["allocated_qty"] == 10

    response = api.create_parts_allocation(
        f.parts_allocation_payload(
            part["id"], second_dealer["id"], stale_part_version, requested_qty=5
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.STALE_PART_VERSION, 412)

    pool = fx.read_part(api, campaign_id, "P-88343")
    assert pool["unallocated_qty"] == 90
    assert pool["consumed_qty"] == 0

    rows = fx.list_allocations_for_part(api, part["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == first_allocation["id"]


def test_campaign_version_advances_by_one_on_each_accepted_write(api):
    """
    Version is a write counter, not a field counter: creation lands on 1, the defect
    determination takes it to 2 while stamping three fields at once, and the defect
    notice takes it to 3.

    PRD §2.4: "and `version`, an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of that record — including mutations that only touch
    derived counters."

    PRD §3.1: "The server stamps `determined_by_user_id` with the caller's `X-User-ID`,
    increments `version` by 1, and computes the statutory `filing_deadline_utc`."

    Design: Corner/cross_cutting_layers/campaign_version_advances_by_one_on_each_accepted_write
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    created = validate_success(
        api.create_campaign(
            f.campaign_payload(campaign_number="26V-344", risk_severity=None),
            SAFETY_ENGINEER_1,
        ),
        201,
    )
    assert created["version"] == 1

    determined = validate_success(
        api.record_defect_determination(
            created["id"],
            f.defect_determination_payload(
                defect_determination_date="2026-08-03T09:00:00Z"
            ),
            SAFETY_ENGINEER_1,
        ),
        200,
    )
    assert determined["version"] == created["version"] + 1
    assert determined["version"] == 2
    assert determined["defect_determination_date"] is not None
    assert determined["filing_deadline_utc"] is not None
    assert determined["determined_by_user_id"] is not None

    fx.file_defect_notice(
        api,
        created["id"],
        narrative="Part 573 defect information report for 26V-344",
    )

    filed = fx.read_campaign(api, created["id"])
    assert filed["version"] == 3
    assert filed["campaign_status"] == CampaignStatus.FILED


def test_effectiveness_score_exactly_at_the_minimum_does_not_revise_the_remedy(api):
    """
    One of the two remedied vehicles came back for a second approved repair, so the
    repeat-repair rate is 0.5000 and the score lands on exactly 100.00 - 60.00 * 0.5000.
    The revision comparison is strict, so the quarterly filing at the floor leaves the
    remedy released, the revision count at 0 and both remedied rows where they are.

    PRD §3.9: "The deduction is 60.00 points multiplied by the repeat-repair rate."

    PRD §3.4: "The comparison is **strict**: a score of exactly 70.00 does not revise,
    and only a score below it does."

    Design: Corner/cross_cutting_layers/effectiveness_score_exactly_at_the_minimum_does_not_revise_the_remedy
    """
    state = fx.campaign_with_allocation(
        api,
        requested_qty=3,
        vehicles=THREE_NE_BUILDS,
        campaign={"campaign_number": "26V-345", "risk_severity": RiskSeverity.LOW},
        labor_operation={"labor_op_code": "R345-01"},
        remedy_part={"part_number": "P-88345", "total_procured_qty": 100},
    )
    campaign_id = state["campaign_id"]
    first_row = fx.find_affected_vehicle(api, campaign_id, state["vehicles"][0]["id"])
    second_row = fx.find_affected_vehicle(api, campaign_id, state["vehicles"][1]["id"])

    first_repair = fx.submit_claim(
        api,
        first_row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    fx.audit_claim(api, first_repair["id"], decision=AuditDecision.APPROVE)

    fx.set_clock(api, "2026-08-04T09:00:00Z")
    repeat_repair = fx.submit_claim(
        api,
        first_row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-04",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    fx.audit_claim(
        api,
        repeat_repair["id"],
        decision=AuditDecision.APPROVE,
        audit_note="Second visit for the same defect",
    )
    second_repair = fx.submit_claim(
        api,
        second_row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-04",
        claimed_labor_hours=1.10,
        parts_used_qty=1,
    )
    fx.audit_claim(api, second_repair["id"], decision=AuditDecision.APPROVE)

    fx.allocate_parts(
        api,
        campaign_id,
        state["part_number"],
        state["remedy_part_id"],
        state["dealer_id"],
        requested_qty=1,
    )
    wave = fx.plan_wave(
        api,
        campaign_id,
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-04",
    )
    fx.release_wave(api, wave["id"])
    fx.mail_wave(api, wave["id"])
    assert fx.read_campaign(api, campaign_id)["campaign_status"] == (
        CampaignStatus.OWNER_NOTIFIED
    )

    filing = validate_success(
        api.create_filing(
            campaign_id,
            f.quarterly_filing_payload(
                report_period="2026Q3",
                narrative="Quarterly completion report at the effectiveness floor",
            ),
            COMPLIANCE_OFFICER_1,
        ),
        201,
    )

    assert filing["effectiveness_score_snapshot"] == 70.00
    assert filing["completion_rate_snapshot_pct"] == 66.67
    assert filing["remedied_count_snapshot"] == 2
    assert filing["recall_population_snapshot"] == 3
    assert filing["amendment_required"] is False
    assert filing["status"] == FilingStatus.SUBMITTED

    campaign = fx.read_campaign(api, campaign_id)
    assert campaign["campaign_status"] == CampaignStatus.MONITORING
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_RELEASED
    assert campaign["remedy_revision_count"] == 0

    metrics = validate_success(
        api.get_completion_metrics(campaign_id, COMPLIANCE_OFFICER_1), 200
    )
    assert metrics["remedy_effectiveness_score"] == 70.00
    assert metrics["repeat_claim_count"] == 1
    assert metrics["remedied_count"] == 2
    assert metrics["regulatory_completion_rate_pct"] == 66.67

    for vehicle in state["vehicles"][:2]:
        row = fx.find_affected_vehicle(api, campaign_id, vehicle["id"])
        assert row["remedy_status"] == VehicleRemedyStatus.REMEDIED
        assert row["requires_renotification"] is False

    read_list(
        api.list_affected_vehicles(
            OPERATIONS_MANAGER,
            {"campaign_id": campaign_id, "remedy_status": VehicleRemedyStatus.REMEDIED},
        ),
        expected_total=2,
    )
