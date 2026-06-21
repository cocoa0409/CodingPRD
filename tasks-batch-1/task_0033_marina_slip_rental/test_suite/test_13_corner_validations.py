"""Corner — validations section.

Individual validation rules surfaced as their canonical error_id.
"""
from test_helpers import (
    validate_error,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    create_lease_payload,
    create_transfer_waitlist_payload,
    reserve_lease,
    set_clock,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_tenant_headers,
)


class TestLeaseCreateInvalidDateRange:

    def test_create_lease_with_start_after_end_returns_invalid_date_range(self, api):
        """PRD §3.4: "`start_date` and `end_date` (each `YYYY-MM-DD`, with `end_date` strictly after `start_date`; an equal start and end yields `ERR_INVALID_DATE_RANGE` HTTP 422)"

        Design: Corner/validations/lease_create_with_invalid_date_range_returns_invalid_date_range
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="R-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tenant = create_tenant()
        vessel = create_vessel(tenant["id"], name="VIDR", loa_ft=40, beam_ft=12)
        res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                start_date="2026-09-10",
                end_date="2026-09-01",  # < start_date
                expected_slip_version=slip["version"],
            ),
            make_tenant_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestVesselTenantMismatchOnLeaseCreate:

    def test_create_lease_with_other_tenants_vessel_returns_vessel_tenant_mismatch(self, api):
        """PRD §3.4: "Finally, the lease's `vessel_id` must reference a vessel whose `tenant_id` equals the lease's `tenant_id`; a mismatch yields `ERR_VESSEL_TENANT_MISMATCH` HTTP 422."

        Design: Corner/validations/vessel_tenant_mismatch_on_lease_create
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="V-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tm1 = create_tenant(full_name="TM1")
        tm2 = create_tenant(full_name="TM2")
        # Vessel owned by tm1; lease attempts to use tm2.
        vessel = create_vessel(tm1["id"], name="VMT", loa_ft=40, beam_ft=12)
        res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=tm2["id"],
                vessel_id=vessel["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                expected_slip_version=slip["version"],
            ),
            make_tenant_headers(tm2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VESSEL_TENANT_MISMATCH)


class TestWaitlistIneligibleWhenNoActiveLease:

    def test_waitlist_create_without_active_lease_returns_waitlist_ineligible(self, api):
        """PRD §3.9: "The system enforces three referential conditions: the tenant must currently hold an `ACTIVE` lease at the named marina, the supplied `from_lease_id` must be that lease, and the `target_slip_id` must be a slip in the same marina; any failure yields `ERR_WAITLIST_INELIGIBLE` HTTP 422."

        Design: Corner/validations/waitlist_ineligible_when_tenant_has_no_active_lease_at_marina
        """
        marina = create_marina(liveaboard_cap=1)
        slip1 = create_slip(
            marina["id"], slip_number="WI-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        slip2 = create_slip(
            marina["id"], slip_number="WI-2",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tenant = create_tenant()
        vessel = create_vessel(tenant["id"], name="VWI", loa_ft=40, beam_ft=12)
        set_clock("2026-07-01T00:00:00Z")
        # Only a RESERVED lease (no check-in -> not ACTIVE).
        lease = reserve_lease(
            marina["id"], slip1["id"], tenant["id"], vessel["id"],
            "2026-09-01", "2026-09-05", slip1["version"],
        )
        res = api.create_transfer_waitlist_entry(
            create_transfer_waitlist_payload(
                marina_id=marina["id"],
                tenant_id=tenant["id"],
                from_lease_id=lease["id"],
                target_slip_id=slip2["id"],
            ),
            make_tenant_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_WAITLIST_INELIGIBLE)


class TestPriorityExistenceBeforeState:

    def test_check_in_on_nonexistent_lease_returns_not_found(self, api):
        """PRD §2.7: "Then existence is verified — every path and body identifier must resolve, or `ERR_NOT_FOUND` is returned. Only after authentication, authorisation, and existence have all passed does the server consult state — a transition that is impossible from the entity's current state yields `ERR_INVALID_STATE`."

        Design: Corner/validations/priority_existence_before_state
        """
        res = api.check_in_lease(NON_EXISTENT_UUID, TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestSlipSizeMismatchPureViaCreate:

    def test_create_lease_with_oversize_vessel_returns_slip_size_mismatch(self, api):
        """PRD §3.4: "The slip must be large enough for the vessel: `loa_ft` of the vessel must be less than or equal to `length_ft` of the slip AND `beam_ft` of the vessel must be less than or equal to `beam_ft` of the slip; either bound violated yields `ERR_SLIP_SIZE_MISMATCH` HTTP 422."

        Design: Corner/validations/error_slip_size_mismatch_pure_via_create
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="SZ-1",
            length_ft=20, beam_ft=8,
            power_amp="A30",
            base_daily_rate_cents=3000,
        )
        tenant = create_tenant()
        vessel = create_vessel(
            tenant["id"], name="VSZ",
            loa_ft=40, beam_ft=12,  # both exceed slip
        )
        res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                expected_slip_version=slip["version"],
            ),
            make_tenant_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SLIP_SIZE_MISMATCH)
