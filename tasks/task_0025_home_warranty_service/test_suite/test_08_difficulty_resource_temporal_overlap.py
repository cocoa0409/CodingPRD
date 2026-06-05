"""Difficulty Rule 8 — resource_temporal_overlap.

Two interval semantics PRD pins differently: the Contract coverage window is a
half-open interval [start, end) for /claims membership; the technician dispatch
buffer is a ±60-minute symmetric exclusion around any existing SCHEDULED/IN_PROGRESS
dispatch on the same technician_id, with strict less-than rejection.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    set_clock,
    tick_clock,
    setup_active_contract_with_item,
    setup_expired_contract_with_item,
    file_claim,
    assess_claim,
    dispatch_claim,
    make_customer_headers,
    make_dispatcher_headers,
    create_claim_payload,
    dispatch_claim_payload,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    create_covered_item_payload,
)


_DISPATCHER = make_dispatcher_headers()


class TestContractCoverageWindowHalfOpenMembership:
    """Right endpoint EXCLUSIVE: clock == coverage_end_utc ⇒ ERR_OUT_OF_COVERAGE. PRD §3.4."""

    def test_claim_at_exact_coverage_end_returns_out_of_coverage(self, api):
        """PRD §3.4: "the request is rejected with `ERR_OUT_OF_COVERAGE` unless the
        server clock is in the half-open interval from `coverage_start_utc` (inclusive)
        to `coverage_end_utc` (exclusive) and the contract's `status` is one of
        `ACTIVE` or `EXPIRING_SOON`."

        Design: Difficulty/resource_temporal_overlap/contract_coverage_window_half_open_membership
        """
        # Activate at 2026-01-01 → coverage_end_utc = 2027-01-01.
        # At clock == coverage_end_utc, contract becomes EXPIRED after /_clock/tick.
        package, customer, expired, item = setup_expired_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            tick_at="2027-01-01T00:00:00Z",  # exact end
            category="HVAC",
        )
        cust_h = make_customer_headers(customer["id"])
        res = api.create_claim(
            create_claim_payload(expired["id"], item["id"],
                                  issue_summary="At the exact boundary"),
            cust_h,
        )
        validate_error(res, "ERR_OUT_OF_COVERAGE")

    def test_claim_one_day_before_coverage_end_succeeds(self, api):
        """PRD §3.4: "the server clock is in the half-open interval from
        `coverage_start_utc` (inclusive) to `coverage_end_utc` (exclusive) and
        the contract's `status` is one of `ACTIVE` or `EXPIRING_SOON`."

        Design: Difficulty/resource_temporal_overlap/contract_coverage_window_half_open_membership
        """
        # Strictly inside the window → claim succeeds.
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        # Advance to one day before end, but stay in ACTIVE/EXPIRING_SOON.
        set_clock("2026-12-31T00:00:00Z")
        tick_clock()  # may transition into EXPIRING_SOON; either is fine for claim filing.
        cust_h = make_customer_headers(customer["id"])
        from test_helpers import validate_success
        res = api.create_claim(
            create_claim_payload(contract["id"], item["id"],
                                  issue_summary="Last day"),
            cust_h,
        )
        body = validate_success(res, 201)
        assert body["contract_id"] == contract["id"]


class TestTechnicianDispatchBufferCollisionWithin60Min:
    """|new - existing| < 3600 s on the SAME technician_id → ERR_TECHNICIAN_DOUBLE_BOOKED.
    PRD §3.5."""

    def test_dispatch_30_minutes_after_existing_rejected(self, api):
        """PRD §3.5: "a new dispatch is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`
        when there already exists another `Dispatch` row carrying the same
        `technician_id` whose `status` is `SCHEDULED` or `IN_PROGRESS` and whose
        `scheduled_utc` falls within a ±60-minute window of the new one."

        Design: Difficulty/resource_temporal_overlap/technician_dispatch_buffer_collision_within_60min
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSQ")
        # Two contracts, two ASSESSED claims, same technician.
        cust_q = register_customer(email="q-tb@example.com")
        cust_r = register_customer(email="r-tb@example.com")
        c_q = activate_contract(create_pending_contract(cust_q, package))
        c_r = activate_contract(create_pending_contract(cust_r, package))
        cust_q_h = make_customer_headers(cust_q["id"])
        cust_r_h = make_customer_headers(cust_r["id"])
        itm_q = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_q["id"], category="HVAC"), cust_q_h
        ))
        itm_r = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_r["id"], category="HVAC"), cust_r_h
        ))
        cl_q = file_claim(c_q, cust_q, itm_q, issue="First")
        cl_r = file_claim(c_r, cust_r, itm_r, issue="Second")
        assess_claim(cl_q, 10_000)
        assess_claim(cl_r, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(cl_q, "tech-X", "2026-02-01T10:00:00Z")
        # Second dispatch 30 min later → |delta| = 1800 s < 3600 → rejected.
        res = api.dispatch_claim(
            cl_r["id"],
            dispatch_claim_payload("tech-X", "2026-02-01T10:30:00Z"),
            _DISPATCHER,
        )
        validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED")

    def test_dispatch_exactly_60_minutes_after_existing_permitted(self, api):
        """PRD §3.5: "The window comparison is strict: the existing visit conflicts
        only when the absolute difference between its `scheduled_utc` and the new
        `scheduled_utc` is less than 3600 seconds; an exact 3600-second gap is permitted."

        Design: Difficulty/resource_temporal_overlap/technician_dispatch_buffer_collision_within_60min
        """
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSR")
        cust_q = register_customer(email="q-tbX@example.com")
        cust_r = register_customer(email="r-tbY@example.com")
        c_q = activate_contract(create_pending_contract(cust_q, package))
        c_r = activate_contract(create_pending_contract(cust_r, package))
        cust_q_h = make_customer_headers(cust_q["id"])
        cust_r_h = make_customer_headers(cust_r["id"])
        itm_q = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_q["id"], category="WATER_HEATER"), cust_q_h
        ))
        itm_r = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_r["id"], category="WATER_HEATER"), cust_r_h
        ))
        cl_q = file_claim(c_q, cust_q, itm_q)
        cl_r = file_claim(c_r, cust_r, itm_r)
        assess_claim(cl_q, 10_000)
        assess_claim(cl_r, 10_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(cl_q, "tech-Y", "2026-02-01T10:00:00Z")
        # Exact 3600 s gap — permitted.
        from test_helpers import validate_success
        res = api.dispatch_claim(
            cl_r["id"],
            dispatch_claim_payload("tech-Y", "2026-02-01T11:00:00Z"),
            _DISPATCHER,
        )
        body = validate_success(res, 200)
        assert body["status"] == "DISPATCHED"
