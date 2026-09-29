"""Two contended resources, two opposite interval conventions: closed +/-30 days versus half-open."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_claim_payload,
    create_dealer,
    create_labor_operation,
    create_state_law_profile,
    create_vehicle,
    get_audit,
    get_claim,
    get_dealer,
    get_success_data,
    list_claim_edits,
    make_dealer_warranty_admin_headers,
    schedule_audit,
    set_clock,
    submit_claim,
    validate_error,
)

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

COVERED_TERMS = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

SUSPENSION_OPERATION = {
    "op_code": "OV-300",
    "description": "Front suspension strut replacement",
    "standard_time_hours": 2.0,
    "max_time_hours": 3.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "SUSP",
}

SUSPENSION_NARRATIVE = {
    "complaint_text": "Customer reports a knocking noise over bumps.",
    "cause_text": "Front strut assembly worn and leaking damper fluid.",
    "correction_text": "Replaced the front strut assembly and road tested.",
}


def build_vehicle_with_anchor_claim():
    """One vehicle carrying a live SUBMITTED claim in overlap group SUSP at 2026-03-11."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-OV",
        name="Overlap Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    world = {
        "profile": profile,
        "dealer": dealer,
        "vehicle": create_vehicle(**COVERED_TERMS),
        "operation": create_labor_operation(**SUSPENSION_OPERATION),
        "part": None,
        "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
    }
    world["anchor"] = submit_claim(
        world,
        repair_order_number="RO-OV-0",
        repair_date="2026-03-11",
        odometer_at_repair=18000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        **SUSPENSION_NARRATIVE,
    )
    assert world["anchor"]["status"] == "SUBMITTED"
    assert world["anchor"]["provisional_total_cents"] == 20000
    return world


def _second_claim_payload(world, repair_order_number, repair_date):
    return create_claim_payload(
        dealer_id=world["dealer"]["id"],
        vehicle_id=world["vehicle"]["id"],
        labor_operation_id=world["operation"]["id"],
        causal_part_id=None,
        repair_order_number=repair_order_number,
        repair_date=repair_date,
        odometer_at_repair=21000,
        claimed_labor_hours=2.0,
        claimed_parts_qty=0,
        **SUSPENSION_NARRATIVE,
    )


def _claims_for_vehicle(vehicle_id):
    return get_success_data(
        api_client.list_claims(
            TEST_USERS["warranty_admin_headers"], params={"vehicle_id": vehicle_id}
        )
    )


def build_dealer_with_scheduled_audit():
    """A claim-free dealer whose first audit occupies the half-open period [2026-01-01, 2026-07-01)."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-AP",
        name="Audit Period Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    audit = schedule_audit(
        dealer,
        period_start="2026-01-01",
        period_end="2026-07-01",
        sample_size=1,
        lead_auditor_user_id="auditor-lead-1",
    )
    assert audit["status"] == "SCHEDULED"
    return {"dealer": get_dealer(dealer["id"]), "audit": audit}


def _audits_for_dealer(dealer_id):
    return get_success_data(
        api_client.list_audits(
            TEST_USERS["audit_manager_headers"], params={"dealer_id": dealer_id}
        )
    )


class TestVehicleRepairOverlapClosedBuffer:
    def test_33_a_gap_of_exactly_thirty_days_collides_and_creates_nothing(self):
        """PRD §3.3: "Second, no other live claim on the same `vehicle_id` whose labor operation shares this operation's `overlap_group` may sit within thirty days of this `repair_date` in either direction."
        PRD §3.3: "That interval is closed on both ends: a gap of exactly thirty days collides, a gap of thirty-one days does not."
        PRD §2.11: "Overlapping repair on the same vehicle — `ERR_OVERLAPPING_REPAIR_CLAIM`."

        Design: Difficulty/resource_temporal_overlap/vehicle_repair_overlap_closed_buffer_thirty_versus_thirty_one_days
        """
        world = build_vehicle_with_anchor_claim()

        response = api_client.create_claim(
            _second_claim_payload(world, "RO-OV-30", "2026-04-10"),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_OVERLAPPING_REPAIR_CLAIM.value)

        assert len(_claims_for_vehicle(world["vehicle"]["id"])) == 1, (
            "the rejected submission must not leave a claim row behind"
        )
        anchor = get_claim(world["anchor"]["id"])
        assert anchor["status"] == "SUBMITTED"
        assert anchor["version"] == world["anchor"]["version"]

    def test_34_one_more_day_of_separation_is_accepted_with_a_repeat_repair_warning(self):
        """PRD §3.3: "That interval is closed on both ends: a gap of exactly thirty days collides, a gap of thirty-one days does not."
        PRD §3.4: "A `REPEAT_REPAIR` edit fires when a qualifying prior claim exists, and records that prior claim's identifier in `conflicting_claim_id`; on every other edit code `conflicting_claim_id` is null."
        PRD §3.4: "A candidate qualifies only when this claim's `repair_date` falls strictly more than thirty days and at most one hundred and eighty days after the candidate's `repair_date`; the lower bound is exclusive and the upper bound is inclusive, which dovetails with the closed thirty-day collision buffer of §3.3 so that a prior repair either blocks the claim outright or, being between thirty-one and one hundred and eighty days old, merely flags it."
        PRD §3.4: "`suspend_edit_count` is then set to the number of edits just appended whose `severity` is `SUSPEND`, and the claim's `status` follows directly: `SUSPENDED` when that count is greater than zero, `SUBMITTED` when it is zero."

        Design: Difficulty/resource_temporal_overlap/vehicle_repair_overlap_closed_buffer_thirty_versus_thirty_one_days
        """
        world = build_vehicle_with_anchor_claim()

        response = api_client.create_claim(
            _second_claim_payload(world, "RO-OV-31", "2026-04-11"),
            world["dealer_headers"],
        )
        claim = get_success_data(response)

        assert response.status_code == 201
        assert claim["status"] == "SUBMITTED", "a WARN edit never suspends the claim"
        assert claim["suspend_edit_count"] == 0
        assert claim["provisional_total_cents"] == 20000

        repeats = list_claim_edits(claim["id"], params={"edit_code": "REPEAT_REPAIR"})
        assert len(repeats) == 1
        assert repeats[0]["severity"] == "WARN"
        assert repeats[0]["conflicting_claim_id"] == world["anchor"]["id"]

        assert len(_claims_for_vehicle(world["vehicle"]["id"])) == 2
        assert get_claim(world["anchor"]["id"])["status"] == "SUBMITTED"


class TestAuditPeriodOverlapHalfOpen:
    def test_35_a_single_day_of_intersection_is_refused_and_schedules_no_audit(self):
        """PRD §3.8: "No other audit of the same dealer whose `status` is `SCHEDULED`, `IN_FIELD`, `FINDINGS_ISSUED` or `APPEALED` may have a period intersecting the requested one, and because the intervals are half-open with no buffer whatsoever, a new period whose `period_start` equals an existing period's `period_end` is adjacent rather than overlapping and is accepted."
        PRD §3.8: "A genuine intersection is refused with `ERR_AUDIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audit_period_overlap_half_open_no_buffer_touching_endpoints
        """
        world = build_dealer_with_scheduled_audit()

        response = api_client.create_audit(
            {
                "dealer_id": world["dealer"]["id"],
                "period_start": "2026-06-30",
                "period_end": "2026-12-31",
                "sample_size": 1,
                "lead_auditor_user_id": "auditor-lead-1",
                "expected_dealer_version": world["dealer"]["version"],
            },
            TEST_USERS["audit_manager_headers"],
        )

        validate_error(response, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP.value)

        assert len(_audits_for_dealer(world["dealer"]["id"])) == 1
        assert get_audit(world["audit"]["id"])["status"] == "SCHEDULED"

    def test_36_a_period_starting_exactly_on_the_existing_period_end_is_adjacent_not_overlapping(self):
        """PRD §3.8: "The window is half-open throughout the entire audit machinery: a claim belongs to the period when its `repair_date` is at or after `period_start` and strictly before `period_end`."
        PRD §3.8: "No other audit of the same dealer whose `status` is `SCHEDULED`, `IN_FIELD`, `FINDINGS_ISSUED` or `APPEALED` may have a period intersecting the requested one, and because the intervals are half-open with no buffer whatsoever, a new period whose `period_start` equals an existing period's `period_end` is adjacent rather than overlapping and is accepted."
        PRD §2.9: "Scheduling a dealer audit likewise requires `expected_dealer_version` matching the audited `Dealer`'s current `version`, and a mismatch is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412)."
        PRD §3.8: "A scheduled audit opens in `SCHEDULED` with `sample_paid_snapshot_cents`, `population_paid_snapshot_cents`, `sample_chargeback_cents`, `extrapolated_chargeback_cents` and `total_chargeback_cents` all at 0, with `error_rate` and `extrapolation_factor` at zero, and with `findings_issued_at` and `appeal_deadline` both null; the dealer's `version` advances by 1."

        Design: Difficulty/resource_temporal_overlap/audit_period_overlap_half_open_no_buffer_touching_endpoints
        """
        world = build_dealer_with_scheduled_audit()
        pinned_version = world["dealer"]["version"]

        rejected = api_client.create_audit(
            {
                "dealer_id": world["dealer"]["id"],
                "period_start": "2026-06-30",
                "period_end": "2026-12-31",
                "sample_size": 1,
                "lead_auditor_user_id": "auditor-lead-1",
                "expected_dealer_version": pinned_version,
            },
            TEST_USERS["audit_manager_headers"],
        )
        validate_error(rejected, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP.value)

        # The refused attempt did not advance the dealer's version, so the same
        # expected_dealer_version is still current for the accepted call.
        accepted = api_client.create_audit(
            {
                "dealer_id": world["dealer"]["id"],
                "period_start": "2026-07-01",
                "period_end": "2026-12-31",
                "sample_size": 1,
                "lead_auditor_user_id": "auditor-lead-1",
                "expected_dealer_version": pinned_version,
            },
            TEST_USERS["audit_manager_headers"],
        )
        second = get_success_data(accepted)

        assert accepted.status_code == 201
        assert second["status"] == "SCHEDULED"
        assert str(second["period_start"])[:10] == "2026-07-01"
        assert len(_audits_for_dealer(world["dealer"]["id"])) == 2
        assert get_audit(world["audit"]["id"])["status"] == "SCHEDULED"
        assert get_dealer(world["dealer"]["id"])["version"] == pinned_version + 1
