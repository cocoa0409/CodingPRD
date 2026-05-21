"""Unit registration, payment standards, and the freezing of
gross_rent_cents + applicable_payment_standard_cents on Tenancy.

PRD §3.3 (units, payment standards), §3.4 (RFTA / Tenancy create).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_to,
    assert_payment_standard,
    assert_tenancy,
    assert_unit,
    create_unit,
    create_unit_payload,
    current_clock,
    ensure_payment_standard,
    iso_utc,
    issue_voucher,
    make_landlord_headers,
    new_landlord_id,
    parse_iso,
    setup_eligible_applicant_with_voucher,
    setup_unit_with_payment_standard,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
    create_pending_tenancy,
    create_tenancy_payload,
    make_case_worker_headers,
    new_case_worker_id,
)


class TestUnitCreate:

    def test_landlord_can_register_unit(self, api):
        """PRD §3.3: "A Landlord registers a unit by supplying its
        street_address, zone, bedroom_count ... the proposed monthly
        contract rent (asking_rent_cents, strictly greater than zero),
        and an optional PHA-supplied utility allowance."

        Claim: POST /units returns 201 with the registered unit.
        """
        unit, landlord_id = create_unit(
            zone="ZONE_A", bedroom_count=2, asking_rent_cents=110_000,
        )
        assert_unit(unit)
        assert unit["zone"] == "ZONE_A"
        assert unit["bedroom_count"] == 2
        assert unit["asking_rent_cents"] == 110_000
        assert unit["landlord_id"] == landlord_id

    def test_asking_rent_must_be_strictly_positive(self, api):
        """PRD §3.3: "the proposed monthly contract rent
        (asking_rent_cents, strictly greater than zero)".
        """
        headers = make_landlord_headers(new_landlord_id())
        payload = create_unit_payload(
            zone="ZONE_A", bedroom_count=2, asking_rent_cents=0,
        )
        resp = api.create_unit(payload, headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("bedroom_count", [-1, 7])
    def test_bedroom_count_range(self, api, bedroom_count):
        """PRD §3.3: "bedroom_count (the unit's physical bedrooms,
        between 0 and 6 inclusive)".
        """
        headers = make_landlord_headers(new_landlord_id())
        payload = create_unit_payload(
            zone="ZONE_A",
            bedroom_count=bedroom_count,
            asking_rent_cents=100_000,
        )
        resp = api.create_unit(payload, headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_initial_occupancy_status_is_vacant(self, api):
        """PRD §3.3: "VACANT when no tenancy occupies the unit".

        Claim: a newly created Unit is VACANT.
        """
        unit, _ = create_unit()
        assert unit["occupancy_status"] == "VACANT"


class TestPaymentStandardConfig:

    def test_phaadmin_creates_payment_standard(self, api):
        """PRD §3.3: "PHAAdmin configures these rows".
        """
        ps = ensure_payment_standard(
            zone="ZONE_B", bedroom_size=2,
            standard_amount_cents=130_000,
            mobility_amount_cents=143_000,
        )
        assert_payment_standard(ps)
        assert ps["standard_amount_cents"] == 130_000
        assert ps["mobility_amount_cents"] == 143_000

    def test_mobility_must_be_at_least_standard(
        self, api, pha_admin_headers,
    ):
        """PRD §3.3: "The mobility amount is constrained to be at least
        equal to the standard amount".
        """
        resp = api.create_payment_standard(
            {
                "zone": "ZONE_A",
                "bedroom_size": 1,
                "standard_amount_cents": 100_000,
                "mobility_amount_cents": 90_000,
                "effective_from": "2020-01-01T00:00:00.000Z",
            },
            pha_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestRFTAGates:

    def test_tenancy_create_freezes_gross_rent_and_payment_standard(
        self, api,
    ):
        """PRD §3.4: "Two financial fields are frozen onto the tenancy
        at this moment and never recomputed for the life of the
        tenancy: gross_rent_cents, the sum of the unit's
        asking_rent_cents and tenant_paid_utilities_cents; and
        applicable_payment_standard_cents, looked up from the Payment
        Standard table".

        Claim: a newly created Tenancy carries gross_rent_cents =
        asking_rent + utilities and applicable_payment_standard_cents
        equal to the active PS for the cell.
        """
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=3, dependents_count=1,
            gross_annual_income_cents=3_000_000,
            zone="ZONE_A",
        )
        unit, landlord_id, ps = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000,
            tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            voucher_bedroom_size_for_ps=min(
                voucher["bedroom_size"], 2,
            ),
        )
        lease_start = iso_utc(add_days(current_clock(), 30))
        tenancy = create_pending_tenancy(
            voucher_id=voucher["id"], unit_id=unit["id"],
            lease_start=lease_start,
        )
        assert_tenancy(tenancy)
        assert tenancy["gross_rent_cents"] == 135_000
        assert tenancy["applicable_payment_standard_cents"] == 120_000

    def test_tenancy_create_on_non_searching_voucher_rejected(self, api):
        """PRD §3.4: "The voucher must be in SEARCHING or
        SEARCHING_REISSUED; otherwise the request is rejected with
        ERR_INVALID_STATE."
        """
        # Build an ACTIVE tenancy so its Voucher is LEASED, then try to
        # create another Tenancy on the same voucher.
        from test_helpers import setup_active_tenancy
        active = setup_active_tenancy()
        # Make a second unit (VACANT, same zone/bedroom_count).
        unit2, _ = create_unit(
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=110_000,
            tenant_paid_utilities_cents=10_000,
        )
        cw = make_case_worker_headers(new_case_worker_id())
        lease_start = iso_utc(add_days(current_clock(), 30))
        resp = api.create_tenancy(
            create_tenancy_payload(
                active["voucher"]["id"], unit2["id"], lease_start,
            ),
            cw,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_under_housing_blocks_zero_bedroom_for_larger_voucher(self, api):
        """PRD §3.4: "when the voucher's authorized bedroom_size is at
        least 1, the unit's bedroom_count must also be at least 1 (the
        system refuses to lease a 0-bedroom unit to a household entitled
        to a 1-or-larger bedroom voucher), or the request is rejected
        with ERR_UNIT_TOO_SMALL."
        """
        applicant, voucher = setup_eligible_applicant_with_voucher(
            household_size=3, dependents_count=1,
            gross_annual_income_cents=3_000_000,
        )
        # Voucher br for 3-person household is 2; create a 0br unit.
        ensure_payment_standard(
            zone="ZONE_A", bedroom_size=0,
            standard_amount_cents=60_000,
        )
        unit, _ = create_unit(
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=60_000, tenant_paid_utilities_cents=0,
        )
        cw = make_case_worker_headers(new_case_worker_id())
        lease_start = iso_utc(add_days(current_clock(), 30))
        resp = api.create_tenancy(
            create_tenancy_payload(voucher["id"], unit["id"], lease_start),
            cw,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_TOO_SMALL.value)

    def test_lease_start_after_search_deadline_rejected(self, api):
        """PRD §3.4: "The proposed lease_start must be no later than
        the voucher's search_deadline (otherwise
        ERR_LEASE_START_AFTER_DEADLINE)."
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
        # search_deadline is issued_at + 120 days; pick one day past.
        deadline = parse_iso(voucher["search_deadline"])
        lease_start = iso_utc(add_days(deadline, 1))
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_tenancy(
            create_tenancy_payload(voucher["id"], unit["id"], lease_start),
            cw,
        )
        validate_error(
            resp, ApiErrorId.ERR_LEASE_START_AFTER_DEADLINE.value,
        )

    def test_unit_not_vacant_rejected(self, api):
        """PRD §3.4: "the unit must be VACANT (otherwise
        ERR_UNIT_NOT_VACANT)".
        """
        # Active tenancy → unit is OCCUPIED_ACTIVE.
        from test_helpers import setup_active_tenancy
        state = setup_active_tenancy()
        applicant2, voucher2 = setup_eligible_applicant_with_voucher(
            household_size=3, dependents_count=1,
            gross_annual_income_cents=3_000_000,
            zone="ZONE_A",
        )
        cw = make_case_worker_headers(new_case_worker_id())
        lease_start = iso_utc(add_days(current_clock(), 30))
        resp = api.create_tenancy(
            create_tenancy_payload(
                voucher2["id"], state["unit"]["id"], lease_start,
            ),
            cw,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_VACANT.value)


class TestUnitOccupancyOverlap:
    """PRD §3.4: 'no prior non-terminated tenancy on this unit may have
    a [requested_at, terminated_at) interval that overlaps the proposed
    tenancy — a unit's previous tenancy must have its terminated_at
    strictly before the next tenancy's requested_at (no same-day
    occupancy; the interval is closed at start and open at end). A
    violation here returns ERR_UNIT_OCCUPANCY_OVERLAP.'
    """

    def test_same_instant_handoff_rejected(self, api):
        """PRD §3.4: "no same-day occupancy; the interval is closed at
        start and open at end". After move-out at T0+30d, a request at
        the same instant must be rejected.
        # difficulty: resource_temporal_overlap/unit_tenancy_no_same_day_overlap_strict_separation
        """
        from test_helpers import (
            move_out_payload, setup_active_tenancy,
        )
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        # Move out at lease_start + 30 days.
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        move_out_dt = add_days(lease_start, 30)
        cw = make_case_worker_headers(new_case_worker_id())
        validate_success(
            api.move_out_tenancy(
                state["tenancy"]["id"],
                move_out_payload(iso_utc(move_out_dt)),
                cw,
            ),
        )
        # Advance clock past move_out to ensure server side observes
        # VACANT before our second POST.
        advance_clock_to(add_days(move_out_dt, 0))
        # Issue a new voucher for a second tenant.
        applicant2, voucher2 = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            zone="ZONE_A",
        )
        cw2 = make_case_worker_headers(new_case_worker_id())
        # Same-instant handoff: lease_start exactly == prior terminated_at.
        resp = api.create_tenancy(
            create_tenancy_payload(
                voucher2["id"], state["unit"]["id"], iso_utc(move_out_dt),
            ),
            cw2,
        )
        validate_error(
            resp, ApiErrorId.ERR_UNIT_OCCUPANCY_OVERLAP.value,
        )

    def test_one_second_later_succeeds(self, api):
        """PRD §3.4: "a unit's previous tenancy must have its
        terminated_at strictly before the next tenancy's requested_at".
        # difficulty: resource_temporal_overlap/unit_tenancy_no_same_day_overlap_strict_separation
        """
        from test_helpers import (
            advance_clock_by_seconds, move_out_payload,
            setup_active_tenancy,
        )
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        move_out_dt = add_days(lease_start, 30)
        cw = make_case_worker_headers(new_case_worker_id())
        validate_success(
            api.move_out_tenancy(
                state["tenancy"]["id"],
                move_out_payload(iso_utc(move_out_dt)),
                cw,
            ),
        )
        # Now schedule a second tenancy 1 second later.
        advance_clock_to(add_days(move_out_dt, 0))
        advance_clock_by_seconds(1)
        applicant2, voucher2 = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            zone="ZONE_A",
        )
        cw2 = make_case_worker_headers(new_case_worker_id())
        from datetime import timedelta
        lease_start2 = iso_utc(move_out_dt + timedelta(seconds=1))
        resp = api.create_tenancy(
            create_tenancy_payload(
                voucher2["id"], state["unit"]["id"], lease_start2,
            ),
            cw2,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING_INSPECTION"
