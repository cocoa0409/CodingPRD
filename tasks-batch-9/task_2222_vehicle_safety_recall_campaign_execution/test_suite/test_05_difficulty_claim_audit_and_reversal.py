"""
Claim audit and reversal: the two amount variants, cascade A in full, and the
two conservation invariants across a supersede-and-reverse sequence.
"""

from test_helpers import (
    AllocationStatus,
    ClaimStatus,
    CampaignStatus,
    RegionCode,
    ReimbursementStatus,
    RevokedReason,
    VehicleRemedyStatus,
    WaveStatus,
    WaveType,
    assert_obligation_conservation,
    assert_parts_conservation,
    fixtures as fx,
    get_success_data,
    read_list,
)
from test_helpers.test_users import CLAIMS_AUDITOR, OPERATIONS_MANAGER

TWO_NE_BUILDS = [
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
]

HISTORICAL_LABOR_OP = {
    "labor_op_code": "R101-00",
    "description": "Pre-recall inflator replacement performed at owner expense",
    "flat_hours": 1.30,
    "rate_type": "PREVAILING",
    "effective_from": "2025-01-01",
    "effective_to": "2026-07-31",
}


def _approved_over_billed_claim(api):
    """
    One claim billing 1.25 hours and three kits against a 1.10-hour operation, a
    138.74 dealer rate and a 21.90 kit, then approved.
    """
    return fx.campaign_with_approved_claim(
        api,
        claim={"claimed_labor_hours": 1.25, "parts_used_qty": 3, "repair_date": "2026-08-03"},
        requested_qty=5,
    )


def test_audited_amount_applies_the_flat_hours_and_single_kit_caps(api):
    """
    The dealer's provisional 26099 cents becomes an audited 18980: the hours drop
    to the 1.10 flat rate and the parts component pays for one kit rather than
    three, a divergence of 7119 cents.

    PRD §3.7: "The effective hours are the smaller of the `claimed_labor_hours`
    and the labor operation's published `flat_hours`."

    PRD §3.7: "The parts component pays for **at most one kit** regardless of what the
    dealer reported, so it is the smaller of `parts_used_qty` and one, multiplied
    by the remedy part's `unit_cost`, increased by the same fifteen percent
    handling markup, and rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/claim_provisional_versus_final_amount_divergence
    """
    state = _approved_over_billed_claim(api)
    claim = state["claim"]

    assert claim["provisional_amount_cents"] == 26099
    assert claim["final_amount_cents"] == 18980
    assert claim["provisional_amount_cents"] - claim["final_amount_cents"] == 7119
    assert claim["status"] == ClaimStatus.APPROVED


def test_approval_books_the_audited_amount_and_burns_one_kit(api):
    """
    The ledger takes the audited figure, the owner's row advances to REMEDIED, and
    exactly one unit is consumed on both the allocation and the part.

    PRD §2.10: "Approving a repair claim computes `final_amount_cents` exactly
    once and adds it to the obligation."

    PRD §2.9: "Approving a repair claim increments both the source allocation's
    `consumed_qty` and the remedy part's `consumed_qty` by one."

    Design: Difficulty/dual_variant_calc/claim_provisional_versus_final_amount_divergence
    """
    state = _approved_over_billed_claim(api)

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["reimbursement_obligation_cents"] == 18980

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.REMEDIED
    assert row["approved_claim_count"] == 1

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 1

    part = fx.read_part(api, state["campaign_id"], state["part_number"])
    assert part["consumed_qty"] == 1
    assert_parts_conservation(part, fx.list_allocations_for_part(api, state["remedy_part_id"]))


def _monitoring_campaign_with_one_repaired_owner(api):
    """
    Two NE owners, a mailed REMEDY wave, one approved claim and one quarterly
    report on file, which puts the campaign in MONITORING at 50.00 percent.
    """
    state = fx.campaign_with_allocation(api, vehicles=TWO_NE_BUILDS, requested_qty=2)
    state = fx.mailed_remedy_wave(api, state, scheduled_mail_date="2026-08-03")

    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    state["affected_vehicle_id"] = row["id"]
    state["claim"] = fx.submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    state["claim_id"] = state["claim"]["id"]
    state["claim"] = fx.audit_claim(api, state["claim_id"])
    state["quarterly_filing"] = fx.file_quarterly(api, state["campaign_id"], "2026Q3")
    state["campaign"] = fx.read_campaign(api, state["campaign_id"])
    return state


def test_claim_reversal_unwinds_the_row_the_counters_and_the_ledger(api):
    """
    Reversal retires the claim to REVERSED with its stored amount intact, returns
    the row to UNREPAIRED, and walks the campaign's remedied count, completion
    rate and obligation back to zero.

    PRD §2.5: "Link 1 decrements the affected-vehicle row's
    `approved_claim_count` and, when that count reaches 0, moves the row's
    `remedy_status` from `REMEDIED` back to `UNREPAIRED`."

    PRD §2.10: "Reversing that claim subtracts the **stored** `final_amount_cents` —
    never a recomputed one — so that a reversal restores the pre-approval
    obligation to the cent even if the dealer's posted rate, the labor operation's
    flat hours or the part's unit cost have changed in the interim."

    Design: Difficulty/transitive_cascade/claim_reversal_cascades_population_metrics_then_autoschedules_followup_wave
    """
    state = _monitoring_campaign_with_one_repaired_owner(api)

    claim = fx.reverse_claim(
        api,
        state["claim_id"],
        reversal_reason="Post-audit finding: repair not performed as documented",
    )
    assert claim["status"] == ClaimStatus.REVERSED
    assert claim["final_amount_cents"] == 18980

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert row["approved_claim_count"] == 0

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["remedied_count"] == 0
    assert campaign["completion_rate_pct"] == 0.00
    assert campaign["reimbursement_obligation_cents"] == 0
    assert campaign["campaign_status"] == CampaignStatus.MONITORING

    part = fx.read_part(api, state["campaign_id"], state["part_number"])
    assert part["consumed_qty"] == 0
    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0


def test_reversal_synthesizes_a_follow_up_wave_three_weeks_out(api):
    """
    Because the reversal drops completion below 85.00 while the campaign is in
    MONITORING and no follow-up is open in the region, the server plans one
    itself, 21 days after the clock date.

    PRD §3.8: "the server picks a drop date by taking the logical clock's current
    date and adding a three-week lead of 21 calendar days, then walking that
    candidate date forward one day at a time for as long as any wave of the same
    campaign and the same region in status `PLANNED`, `RELEASE_APPROVED` or
    `MAILED` has a `scheduled_mail_date` fewer than fourteen whole days from the
    candidate in absolute terms".

    PRD §3.8: "A `NotificationWave` is then created with `wave_type` `FOLLOW_UP`,
    `target_region_code` set to the vehicle's region, `scheduled_mail_date` set to
    the settled date, status `PLANNED`, and `auto_created` true, distinguishing it
    from an operator-planned wave."

    Design: Difficulty/transitive_cascade/claim_reversal_cascades_population_metrics_then_autoschedules_followup_wave
    """
    state = _monitoring_campaign_with_one_repaired_owner(api)

    fx.reverse_claim(
        api,
        state["claim_id"],
        reversal_reason="Post-audit finding: repair not performed as documented",
    )

    waves, _ = read_list(
        api.list_notification_waves(
            state["campaign_id"], OPERATIONS_MANAGER, {"wave_type": WaveType.FOLLOW_UP}
        ),
        expected_total=1,
    )
    follow_up = waves[0]
    assert follow_up["status"] == WaveStatus.PLANNED
    assert follow_up["auto_created"] is True
    assert follow_up["target_region_code"] == RegionCode.NE
    assert follow_up["scheduled_mail_date"] == "2026-08-24"

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["open_followup_wave_count"] == 1


def _superseded_holding_then_reversal(api):
    """
    A dealer's two-kit holding is consumed once, then superseded by a fresh
    request for the same part, leaving the consumed unit stranded on a REVOKED
    allocation.
    """
    state = fx.campaign_with_allocation(api, vehicles=TWO_NE_BUILDS, requested_qty=2)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    state["affected_vehicle_id"] = row["id"]
    state["claim"] = fx.submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    state["claim_id"] = state["claim"]["id"]
    state["claim"] = fx.audit_claim(api, state["claim_id"])

    state["allocation_2"] = fx.allocate_parts(
        api,
        state["campaign_id"],
        state["part_number"],
        state["remedy_part_id"],
        state["dealer_id"],
        requested_qty=2,
    )
    return state


def test_reversal_of_a_revoked_allocations_unit_credits_the_pool(api):
    """
    With the source allocation already superseded, the reversed unit cannot go
    back to it, so it lands in the part's `unallocated_qty` and the conservation
    equality still closes on 100 units.

    PRD §2.9: "when the source allocation has since been revoked, the freed unit
    is credited to the remedy part's `unallocated_qty` instead, because there is
    no live allocation to return it to."

    PRD §2.9: "`total_procured_qty` equals `unallocated_qty`, plus the sum over
    the part's allocations still in status `ALLOCATED` of that allocation's
    `allocated_qty` minus its `consumed_qty`, plus the part's own `consumed_qty`."

    Design: Difficulty/compensating_invariant/parts_units_conserved_across_supersede_and_reversal_of_consumed_allocation
    """
    state = _superseded_holding_then_reversal(api)

    claim = fx.reverse_claim(
        api, state["claim_id"], reversal_reason="Audit finding: kit not installed"
    )
    assert claim["status"] == ClaimStatus.REVERSED

    part = fx.read_part(api, state["campaign_id"], state["part_number"])
    allocations = fx.list_allocations_for_part(api, state["remedy_part_id"])

    assert part["unallocated_qty"] == 99
    assert part["consumed_qty"] == 0
    assert part["total_procured_qty"] == 100
    assert_parts_conservation(part, allocations)

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED


def test_superseded_allocation_keeps_its_consumed_unit_on_the_record(api):
    """
    The superseded holding is retired as REVOKED with reason SUPERSEDED and keeps
    the unit it burned; the replacement is capped by regional demand down to one
    unit and is therefore only partially granted.

    PRD §3.5: "At most one allocation exists for a given remedy part and dealer in
    status `ALLOCATED`; when one does, its `allocated_qty` minus its
    `consumed_qty` is returned to the remedy part's `unallocated_qty`, and the
    prior allocation moves to `REVOKED` with `revoked_reason` recorded as
    `SUPERSEDED`."

    PRD §3.5: "records `partially_granted` as true exactly when the granted
    quantity is less than the `requested_qty` and false when it equals it".

    Design: Difficulty/compensating_invariant/parts_units_conserved_across_supersede_and_reversal_of_consumed_allocation
    """
    state = _superseded_holding_then_reversal(api)
    fx.reverse_claim(api, state["claim_id"], reversal_reason="Audit finding: kit not installed")

    first = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert first["status"] == AllocationStatus.REVOKED
    assert first["revoked_reason"] == RevokedReason.SUPERSEDED
    assert first["allocated_qty"] == 2
    assert first["consumed_qty"] == 1

    second = get_success_data(
        api.get_parts_allocation(state["allocation_2"]["id"], OPERATIONS_MANAGER)
    )
    assert second["status"] == AllocationStatus.ALLOCATED
    assert second["allocated_qty"] == 1
    assert second["consumed_qty"] == 0
    assert second["partially_granted"] is True


def _claim_and_reimbursement_on_one_campaign(api):
    """
    A do-not-drive campaign carrying both an approved dealer claim and an
    approved owner reimbursement resolved against a pre-recall labor operation.
    """
    state = fx.filed_campaign(api)
    campaign_id = state["campaign_id"]
    fx.issue_interim_advisory(api, campaign_id, stop_sale=False, do_not_drive=True)

    state["labor_operation"] = fx.add_labor_operation(api, campaign_id)
    state["labor_operation_id"] = state["labor_operation"]["id"]
    state["historical_labor_operation"] = fx.add_labor_operation(
        api, campaign_id, **HISTORICAL_LABOR_OP
    )
    state["remedy_part"] = fx.add_remedy_part(api, campaign_id)
    state["remedy_part_id"] = state["remedy_part"]["id"]
    state["part_number"] = state["remedy_part"]["part_number"]
    state["campaign"] = fx.release_remedy(api, campaign_id, state["labor_operation_id"])

    state["dealer"] = fx.create_dealer(api)
    state["dealer_id"] = state["dealer"]["id"]
    state["allocation"] = fx.allocate_parts(
        api,
        campaign_id,
        state["part_number"],
        state["remedy_part_id"],
        state["dealer_id"],
        requested_qty=1,
    )
    state["allocation_id"] = state["allocation"]["id"]

    row = fx.find_affected_vehicle(api, campaign_id, state["vehicle_id"])
    state["affected_vehicle_id"] = row["id"]
    state["claim"] = fx.submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        repair_date="2026-08-03",
        claimed_labor_hours=1.25,
        parts_used_qty=3,
    )
    state["claim_id"] = state["claim"]["id"]
    state["claim"] = fx.audit_claim(api, state["claim_id"])

    request = fx.submit_reimbursement(
        api,
        campaign_id,
        state["vehicle_id"],
        invoice_date="2026-07-15",
        invoice_amount=412.75,
        labor_hours_claimed=1.30,
        parts_amount=62.00,
        towing_amount=120.00,
    )
    state["reimbursement"] = fx.adjudicate_reimbursement(api, request["id"], "APPROVE")
    state["reimbursement_id"] = request["id"]
    return state


def test_reversal_subtracts_only_the_claim_leaving_the_reimbursement_standing(api):
    """
    The ledger holds 46996 cents from a dealer claim plus an owner reimbursement;
    reversing the claim drops it by exactly the claim's stored 18980 and leaves
    the reimbursement's 28016 untouched.

    PRD §2.10: "For every campaign, `reimbursement_obligation_cents` equals the
    sum of `final_amount_cents` over that campaign's repair claims in status
    `APPROVED`, plus the sum of `approved_amount_cents` over that campaign's owner
    reimbursement requests in status `APPROVED`."

    PRD §3.7: "`final_amount_cents` is retained and never recomputed, precisely so
    that the ledger unwinds exactly: the campaign's
    `reimbursement_obligation_cents` decreases by that stored value."

    Design: Difficulty/compensating_invariant/obligation_cents_conserved_when_claim_reversal_leaves_owner_reimbursement_intact
    """
    state = _claim_and_reimbursement_on_one_campaign(api)

    before = fx.read_campaign(api, state["campaign_id"])
    assert before["reimbursement_obligation_cents"] == 46996

    claim = fx.reverse_claim(
        api,
        state["claim_id"],
        reversal_reason="Audit finding: dealer repair not substantiated",
    )
    assert claim["status"] == ClaimStatus.REVERSED
    assert claim["final_amount_cents"] == 18980

    after = fx.read_campaign(api, state["campaign_id"])
    assert after["reimbursement_obligation_cents"] == 28016
    assert before["reimbursement_obligation_cents"] - after["reimbursement_obligation_cents"] == 18980
    assert_obligation_conservation(
        after,
        fx.list_claims_for_campaign(api, state["campaign_id"]),
        fx.list_reimbursements_for_campaign(api, state["campaign_id"]),
    )


def test_owner_reimbursement_resolves_the_pre_recall_labor_operation(api):
    """
    The 2026-07-15 invoice resolves to the historical PREVAILING operation whose
    closed window contains it, capping the payment at 28016 cents, and the
    reversal of the dealer claim leaves that request and the parts pool alone.

    PRD §3.9: "The server first resolves the campaign labor operation whose closed
    effective window contains the `invoice_date` and records it as the request's
    `labor_operation_id`; when the campaign has no such labor operation the
    approval is rejected with `ERR_LABOR_OP_NOT_EFFECTIVE`."

    PRD §3.9: "The towing allowance is paid only when the campaign's
    `do_not_drive_flag` is true, in which case it is the smaller of the owner's
    `towing_amount` and a towing cap of 100.00 dollars, rounded to two decimal
    places".

    Design: Difficulty/compensating_invariant/obligation_cents_conserved_when_claim_reversal_leaves_owner_reimbursement_intact
    """
    state = _claim_and_reimbursement_on_one_campaign(api)
    fx.reverse_claim(
        api,
        state["claim_id"],
        reversal_reason="Audit finding: dealer repair not substantiated",
    )

    request = get_success_data(
        api.get_owner_reimbursement(state["reimbursement_id"], CLAIMS_AUDITOR)
    )
    assert request["approved_amount_cents"] == 28016
    assert request["labor_operation_id"] == state["historical_labor_operation"]["id"]
    assert request["status"] == ReimbursementStatus.APPROVED

    part = fx.read_part(api, state["campaign_id"], state["part_number"])
    assert part["consumed_qty"] == 0
    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["consumed_qty"] == 0

    row = get_success_data(
        api.get_affected_vehicle(state["affected_vehicle_id"], OPERATIONS_MANAGER)
    )
    assert row["remedy_status"] == VehicleRemedyStatus.UNREPAIRED
    assert row["approved_claim_count"] == 0
