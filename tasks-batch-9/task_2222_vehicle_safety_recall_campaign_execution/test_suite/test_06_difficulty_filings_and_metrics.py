"""
Completion reporting: the two rate variants read off one population, and the
quarterly filing that forces a released remedy back into revision.
"""

from test_helpers import (
    AllocationStatus,
    CampaignStatus,
    ClaimStatus,
    OutreachChannel,
    OutreachOutcome,
    RemedyStatus,
    RevokedReason,
    VehicleRemedyStatus,
    assert_parts_conservation,
    factories as f,
    fixtures as fx,
    get_success_data,
    read_list,
    validate_success,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_1, OPERATIONS_MANAGER

FOUR_NE_BUILDS = [
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
    {
        "vin": "1HGCM82633A004355",
        "production_date": "2024-03-18",
        "suspect_part_number": 1503,
        "owner_name": "Dan Roe",
    },
]

TWO_NE_BUILDS = FOUR_NE_BUILDS[:2]


def _population_holding_one_row_of_each_status(api):
    """
    Four NE owners driven to four distinct remedy statuses: REMEDIED, UNREACHABLE,
    SCHEDULED and REMOVED_FROM_POPULATION.
    """
    state = fx.campaign_with_allocation(api, vehicles=FOUR_NE_BUILDS, requested_qty=4)
    campaign_id = state["campaign_id"]
    repaired, unreachable, scheduled, scrapped = state["vehicles"]

    repaired_row = fx.find_affected_vehicle(api, campaign_id, repaired["id"])
    claim = fx.submit_claim(
        api,
        repaired_row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    fx.audit_claim(api, claim["id"])

    unreachable_row = fx.find_affected_vehicle(api, campaign_id, unreachable["id"])
    fx.log_outreach(
        api,
        unreachable_row["id"],
        channel=OutreachChannel.MAIL,
        outcome=OutreachOutcome.BAD_ADDRESS,
        note="Notice returned undeliverable",
    )

    scheduled_row = fx.find_affected_vehicle(api, campaign_id, scheduled["id"])
    fx.book_appointment(
        api, scheduled_row["id"], state["dealer_id"], scheduled_repair_date="2026-08-20"
    )

    validate_success(
        api.update_vehicle(
            scrapped["id"], f.vehicle_update_payload(sale_status="SCRAPPED"), OPERATIONS_MANAGER
        )
    )

    state["rows"] = {
        "remedied": repaired_row["id"],
        "unreachable": unreachable_row["id"],
        "scheduled": scheduled_row["id"],
    }
    return state


def test_completion_metrics_report_both_variants_side_by_side(api):
    """
    One remedied, one scheduled, one unreachable and one removed row give a
    regulatory rate of 33.33 and an operational rate of 100.00, because the
    operational denominator drops the unreachable row and its numerator picks up
    the scheduled one.

    PRD §3.9: "Its denominator is the total minus the removed rows — the same
    figure the campaign carries as `recall_population_count` — and **unreachable
    rows stay in it**, because the regulator does not forgive an owner the
    automaker could not find. Its numerator is the `REMEDIED` rows only."

    PRD §3.9: "Its denominator is the total minus the removed rows *and also*
    minus the unreachable rows, and its numerator adds the `SCHEDULED` rows to the
    `REMEDIED` ones, so the same population always reports at or above the
    regulatory rate."

    Design: Difficulty/dual_variant_calc/completion_rate_regulatory_versus_operational_divergence
    """
    state = _population_holding_one_row_of_each_status(api)

    metrics = get_success_data(
        api.get_completion_metrics(state["campaign_id"], COMPLIANCE_OFFICER_1)
    )

    assert metrics["regulatory_completion_rate_pct"] == 33.33
    assert metrics["operational_completion_rate_pct"] == 100.00
    assert metrics["affected_vehicle_count"] == 4
    assert metrics["recall_population_count"] == 3
    assert metrics["remedied_count"] == 1
    assert metrics["scheduled_count"] == 1
    assert metrics["unreachable_count"] == 1
    assert metrics["removed_count"] == 1


def test_campaign_persists_the_regulatory_variant_only(api):
    """
    The stored `completion_rate_pct` carries the regulatory 33.33, and
    `recall_population_count` is the removed-excluding denominator that produced
    it, so the operational figure lives nowhere but the metrics reading.

    PRD §3.9: "The **regulatory** variant is the one persisted in
    `completion_rate_pct` and frozen onto every filing snapshot."

    PRD §3.9: "The **operational** variant is a read-only dashboard figure."

    Design: Difficulty/dual_variant_calc/completion_rate_regulatory_versus_operational_divergence
    """
    state = _population_holding_one_row_of_each_status(api)

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["completion_rate_pct"] == 33.33
    assert campaign["recall_population_count"] == 3
    assert campaign["affected_vehicle_count"] == 4
    assert campaign["remedied_count"] == 1

    rows = {
        row["id"]: row["remedy_status"]
        for row in fx.list_affected_vehicles_for(api, state["campaign_id"])
    }
    assert rows[state["rows"]["remedied"]] == VehicleRemedyStatus.REMEDIED
    assert rows[state["rows"]["unreachable"]] == VehicleRemedyStatus.UNREACHABLE
    assert rows[state["rows"]["scheduled"]] == VehicleRemedyStatus.SCHEDULED


def _campaign_with_a_repeat_repair_awaiting_its_quarterly(api):
    """
    Two NE owners, a mailed REMEDY wave, and one owner repaired twice under
    approved claims — a repeat-repair rate of 1.0000 waiting to be scored.
    """
    state = fx.campaign_with_allocation(api, vehicles=TWO_NE_BUILDS, requested_qty=2)
    state = fx.mailed_remedy_wave(api, state, scheduled_mail_date="2026-08-03")

    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    state["affected_vehicle_id"] = row["id"]

    first = fx.submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    state["claim_1"] = fx.audit_claim(api, first["id"], audit_note="First repair approved")

    second = fx.submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-04",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    state["claim_2"] = fx.audit_claim(
        api, second["id"], audit_note="Repeat repair on the same VIN approved"
    )
    return state


def test_quarterly_filing_freezes_the_pre_cascade_snapshot(api):
    """
    One surplus approved repair over one remedied row is a repeat rate of 1.0000,
    so the filing scores 40.00 and freezes the 50.00 completion rate that stood
    before the revision cascade rewrote it.

    PRD §3.9: "The deduction is 60.00 points multiplied by the repeat-repair
    rate."

    PRD §3.3: "Each accepted filing is created in status `SUBMITTED`, stamped with
    `filed_at` from the logical clock and `filed_by_user_id` from the caller's
    `X-User-ID`, and freezes four snapshot values that must never drift
    afterwards: `completion_rate_snapshot_pct`, `remedied_count_snapshot`,
    `recall_population_snapshot` and `effectiveness_score_snapshot`."

    Design: Difficulty/transitive_cascade/quarterly_filing_low_effectiveness_revises_remedy_and_reverts_remedied_vehicles
    """
    state = _campaign_with_a_repeat_repair_awaiting_its_quarterly(api)

    filing = fx.file_quarterly(
        api,
        state["campaign_id"],
        "2026Q3",
        narrative="Quarterly completion and effectiveness report",
    )

    assert filing["effectiveness_score_snapshot"] == 40.00
    assert filing["completion_rate_snapshot_pct"] == 50.00
    assert filing["remedied_count_snapshot"] == 1
    assert filing["recall_population_snapshot"] == 2
    assert filing["amendment_required"] is True


def test_low_effectiveness_revises_the_remedy_and_reverts_the_repaired_row(api):
    """
    A 40.00 score is below the 70.00 floor, so the remedy is forced to
    REMEDY_REVISED, the repaired row returns to UNREPAIRED flagged for
    renotification, and the dealer's holding is revoked — while the two approved
    claims and the money they booked stand untouched.

    PRD §3.4: "When the score is below the floor and `remedy_status` is
    `REMEDY_RELEASED`, the remedy is forced from `REMEDY_RELEASED` to
    `REMEDY_REVISED` and cascade B of §2.5 runs in full — `remedy_revision_count`
    increments by 1, every affected-vehicle row of the campaign standing at
    `REMEDIED` returns to `UNREPAIRED` with `requires_renotification` set true,
    `remedied_count`, `recall_population_count` and `completion_rate_pct` are
    recomputed, the just-created quarterly filing has `amendment_required` set
    true, and every `ALLOCATED` parts allocation of the campaign is revoked with
    `revoked_reason` `REMEDY_REVISED` with its uncommitted units returned to the
    pool."

    PRD §3.9: "only `APPROVED` claims count, so `REJECTED` and `REVERSED` claims
    never contribute."

    Design: Difficulty/transitive_cascade/quarterly_filing_low_effectiveness_revises_remedy_and_reverts_remedied_vehicles
    """
    state = _campaign_with_a_repeat_repair_awaiting_its_quarterly(api)
    fx.file_quarterly(
        api,
        state["campaign_id"],
        "2026Q3",
        narrative="Quarterly completion and effectiveness report",
    )

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["campaign_status"] == CampaignStatus.MONITORING
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_REVISED
    assert campaign["remedy_revision_count"] == 1
    assert campaign["remedy_effectiveness_score"] == 40.00
    assert campaign["remedied_count"] == 0
    assert campaign["completion_rate_pct"] == 0.00
    assert campaign["quarterly_filing_count"] == 1
    assert campaign["reimbursement_obligation_cents"] == 37960

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert row["requires_renotification"] is True
    assert row["approved_claim_count"] == 2

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["status"] == AllocationStatus.REVOKED
    assert allocation["revoked_reason"] == RevokedReason.REMEDY_REVISED

    part = fx.read_part(api, state["campaign_id"], state["part_number"])
    assert part["unallocated_qty"] == 98
    assert part["consumed_qty"] == 2
    assert_parts_conservation(part, fx.list_allocations_for_part(api, state["remedy_part_id"]))

    claims, _ = read_list(
        api.list_repair_claims(COMPLIANCE_OFFICER_1, {"campaign_id": state["campaign_id"]}),
        expected_total=2,
    )
    assert all(claim["status"] == ClaimStatus.APPROVED for claim in claims)
    repeat = next(claim for claim in claims if claim["id"] == state["claim_2"]["id"])
    assert repeat["is_repeat_repair"] is True
