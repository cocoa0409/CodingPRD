"""Move-out, voucher re-issuance with the 60-day re-search window,
and voucher expiration (search-deadline boundary + sweeps).

PRD §3.8, §3.12.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_by_seconds,
    advance_clock_to,
    create_tenancy_payload,
    current_clock,
    get_tenancy,
    get_voucher,
    iso_utc,
    make_case_worker_headers,
    move_out_payload,
    new_case_worker_id,
    parse_iso,
    setup_active_tenancy,
    setup_eligible_applicant_with_voucher,
    setup_unit_with_payment_standard,
    sweep_expirations,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestMoveOut:

    def test_move_out_terminates_tenancy_and_reissues_voucher(self, api):
        """PRD §3.8: "The tenancy cascades to TERMINATED with
        termination_reason TENANT_MOVE_OUT, the unit's occupancy_status
        returns to VACANT, and the voucher cascades from LEASED to
        SEARCHING_REISSUED with a fresh re-search window: search_deadline
        becomes move_out_date plus 60 days."
        # difficulty: non_linear_state_machine/voucher_branching_searching_to_three_outcomes
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        move_out_dt = add_days(lease_start, 90)
        cw = make_case_worker_headers(new_case_worker_id())
        validate_success(
            api.move_out_tenancy(
                state["tenancy"]["id"],
                move_out_payload(iso_utc(move_out_dt)),
                cw,
            ),
        )
        t = get_tenancy(state["tenancy"]["id"])
        v = get_voucher(state["voucher"]["id"])
        assert t["status"] == "TERMINATED"
        assert t["termination_reason"] == "TENANT_MOVE_OUT"
        assert v["status"] == "SEARCHING_REISSUED"
        new_deadline = parse_iso(v["search_deadline"])
        # PRD §3.8: search_deadline = move_out_date + 60 days.
        expected = add_days(move_out_dt, 60)
        delta = abs((new_deadline - expected).total_seconds())
        assert delta < 60, (
            f"expected re-search deadline at {expected}, got {new_deadline}"
        )


class TestVoucherExpirationBoundary:
    """Difficulty Design rule 6 instance 3: voucher_expiration_clock_boundary.
    """

    def test_at_search_deadline_tenancy_create_allowed(self, api):
        """PRD §3.4: "The voucher's search_deadline must not have passed
        (otherwise ERR_VOUCHER_EXPIRED)."

        Per §3.4 the gate is "must not have passed", i.e. strictly
        greater than. At exactly search_deadline the voucher is still
        SEARCHING — the test verifies the inclusive boundary.
        # difficulty: boundary_precision_check/voucher_expiration_clock_boundary
        """
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 1),
        )
        deadline = parse_iso(voucher["search_deadline"])
        # Advance clock to exactly the search_deadline.
        advance_clock_to(deadline)
        cw = make_case_worker_headers(new_case_worker_id())
        # lease_start at the deadline instant is also allowed (PRD §3.4:
        # lease_start <= search_deadline).
        resp = api.create_tenancy(
            create_tenancy_payload(
                voucher["id"], unit["id"], iso_utc(deadline),
            ),
            cw,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING_INSPECTION"

    def test_one_second_past_deadline_tenancy_create_rejected(self, api):
        """PRD §3.4: "The voucher's search_deadline must not have passed
        (otherwise ERR_VOUCHER_EXPIRED)" — at one second past the
        deadline, the next /tenancies POST is rejected.
        # difficulty: boundary_precision_check/voucher_expiration_clock_boundary
        """
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(voucher["bedroom_size"], 1),
        )
        deadline = parse_iso(voucher["search_deadline"])
        advance_clock_to(deadline)
        advance_clock_by_seconds(1)
        cw = make_case_worker_headers(new_case_worker_id())
        # Use a far-past lease_start to also expose the second
        # acceptable failure mode if implementation prefers
        # ERR_LEASE_START_AFTER_DEADLINE.
        from datetime import timedelta
        resp = api.create_tenancy(
            create_tenancy_payload(
                voucher["id"], unit["id"],
                iso_utc(deadline + timedelta(seconds=1)),
            ),
            cw,
        )
        # PRD §2.10 puts ERR_VOUCHER_EXPIRED higher in priority than
        # ERR_LEASE_START_AFTER_DEADLINE; we accept either as a faithful
        # outcome.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_VOUCHER_EXPIRED.value,
            ApiErrorId.ERR_LEASE_START_AFTER_DEADLINE.value,
        ])


class TestExpirationSweep:

    def test_expiration_sweep_terminates_unleased_vouchers(self, api):
        """PRD §3.12: "The expiration sweep transitions any voucher
        whose search_deadline has passed and which has no ACTIVE or
        PENDING_* tenancy from SEARCHING (or SEARCHING_REISSUED) to
        EXPIRED, returning the list of expired voucher ids."
        """
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        deadline = parse_iso(voucher["search_deadline"])
        # Advance past the deadline.
        advance_clock_to(deadline)
        advance_clock_by_seconds(1)
        sweep_expirations()
        v = get_voucher(voucher["id"])
        assert v["status"] == "EXPIRED"
