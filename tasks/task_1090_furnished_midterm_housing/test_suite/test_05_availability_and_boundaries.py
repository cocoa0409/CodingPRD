"""Temporal availability (unit half-open + buffer, tenant closed interval) and
numeric boundary precision (tax exemption at 30 days, buffer adjacency).

Queue A (Difficulty): boundary_precision_check, resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    register_host, register_tenant, create_unit, request_booking, confirm_booking,
    get_tax_for_booking,
    make_tenant_headers, TEST_USERS,
    create_booking_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# boundary_precision_check / tax_exempt_30_day_boundary
# --------------------------------------------------------------------------

def _confirm_and_get_tax(api, *, start, end):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       min_term_days=7, deposit_cents=0, monthly_rate_cents=300000)
    booking = request_booking(api, unit["id"], tenant["id"], start, end)
    confirm_booking(api, booking["id"], host["id"])
    return get_tax_for_booking(api, booking["id"])


def test_tax_taxable_just_below_30_day_boundary(api):
    """PRD §3.4: "Otherwise the stay is taxable: `taxable` is true,
    `occupancy_tax_cents` is `gross_rent_cents` multiplied by the fourteen-percent
    occupancy-tax rate and rounded half up to whole cents, and `exempt_reason` is
    `NONE`."

    Design: Difficulty/boundary_precision_check/tax_exempt_30_day_boundary
    """
    tax = _confirm_and_get_tax(api, start="2026-06-01", end="2026-06-30")  # term 29
    assert tax["taxable"] is True, "a 29-day stay must be taxable"
    assert tax["occupancy_tax_cents"] == 40600, f"tax must be round(290000*0.14)=40600, got {tax['occupancy_tax_cents']}"
    assert tax["exempt_reason"] == "NONE"


def test_tax_exempt_at_30_day_boundary(api):
    """PRD §3.4: "If the `assessed_term_days` is 30 or more, the stay qualifies as
    mid-term: `taxable` is false, `occupancy_tax_cents` is zero, and
    `exempt_reason` is `MID_TERM_30_DAY`."

    Design: Difficulty/boundary_precision_check/tax_exempt_30_day_boundary
    """
    tax = _confirm_and_get_tax(api, start="2026-06-01", end="2026-07-01")  # term 30
    assert tax["taxable"] is False, "a 30-day stay must be exempt"
    assert tax["occupancy_tax_cents"] == 0
    assert tax["exempt_reason"] == "MID_TERM_30_DAY"


# --------------------------------------------------------------------------
# boundary_precision_check / unit_availability_buffer_boundary
# --------------------------------------------------------------------------

def _unit_with_first_booking(api, *, buffer=2):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True,
                       turnover_buffer_days=buffer, deposit_cents=0)
    request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    return host, tenant, unit


def test_booking_rejected_inside_turnover_buffer(api):
    """PRD §3.3: "the requested window, extended by the unit's
    `turnover_buffer_days` cleaning buffer and evaluated on the half-open
    convention, must not overlap any existing booking on the same unit that is in
    `REQUESTED`, `CONFIRMED`, or `ACTIVE`, else the request is rejected with
    `ERR_UNIT_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/unit_availability_buffer_boundary
    """
    host, tenant, unit = _unit_with_first_booking(api, buffer=2)
    # Buffered window of the first booking is [2026-06-01, 2026-07-03); start
    # 2026-07-02 falls inside it.
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-07-02", "2026-08-01"),
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_UNAVAILABLE)


def test_booking_allowed_at_buffer_boundary(api):
    """PRD §3.2: "`turnover_buffer_days` (the cleaning gap appended after each
    stay, defaulting to 2)".
    PRD §3.3: "the requested window, extended by the unit's `turnover_buffer_days`
    cleaning buffer and evaluated on the half-open convention, must not overlap
    any existing booking on the same unit".

    Design: Difficulty/boundary_precision_check/unit_availability_buffer_boundary
    """
    host, tenant, unit = _unit_with_first_booking(api, buffer=2)
    # Start 2026-07-03 == end (2026-07-01) + 2-day buffer; half-open, no overlap.
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-07-03", "2026-08-02"),
        make_tenant_headers(tenant["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED", f"booking at the buffer boundary must be accepted, got {data['status']}"


# --------------------------------------------------------------------------
# resource_temporal_overlap / unit_overlap_halfopen_with_buffer
# --------------------------------------------------------------------------

def test_unit_overlap_within_buffered_window_rejected(api):
    """PRD §3.3: "the requested window, extended by the unit's
    `turnover_buffer_days` cleaning buffer and evaluated on the half-open
    convention, must not overlap any existing booking on the same unit that is in
    `REQUESTED`, `CONFIRMED`, or `ACTIVE`, else the request is rejected with
    `ERR_UNIT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/unit_overlap_halfopen_with_buffer
    """
    host, tenant, unit = _unit_with_first_booking(api, buffer=2)
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-06-15", "2026-07-15"),
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_UNAVAILABLE)


def test_unit_overlap_rejected_for_a_different_tenant(api):
    """PRD §3.3: "must not overlap any existing booking on the same unit that is in
    `REQUESTED`, `CONFIRMED`, or `ACTIVE`, else the request is rejected with
    `ERR_UNIT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/unit_overlap_halfopen_with_buffer
    """
    host, tenant, unit = _unit_with_first_booking(api, buffer=2)
    other_tenant = register_tenant(api, verified=True, tenant_type="RELOCATION")
    # Unit-level availability is independent of who books; the overlap is rejected.
    resp = api.create_booking(
        create_booking_payload(unit["id"], other_tenant["id"], "2026-06-20", "2026-07-20"),
        make_tenant_headers(other_tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_UNAVAILABLE)


# --------------------------------------------------------------------------
# resource_temporal_overlap / tenant_overlap_closed_interval
# --------------------------------------------------------------------------

def _tenant_with_confirmed_booking(api):
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True, tenant_type="RELOCATION")
    unit1 = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    unit2 = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    b1 = request_booking(api, unit1["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, b1["id"], host["id"])
    return host, tenant, unit2


def test_tenant_double_booked_at_shared_endpoint_rejected(api):
    """PRD §3.3: "if the requested window, evaluated as a closed interval,
    intersects another booking of the same tenant that is `CONFIRMED` or `ACTIVE`,
    the request is rejected with `ERR_TENANT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/tenant_overlap_closed_interval
    """
    host, tenant, unit2 = _tenant_with_confirmed_booking(api)
    # Closed [2026-06-01,2026-07-01] intersects [2026-07-01,2026-08-01] at 2026-07-01.
    resp = api.create_booking(
        create_booking_payload(unit2["id"], tenant["id"], "2026-07-01", "2026-08-01"),
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_TENANT_DOUBLE_BOOKED)


def test_tenant_booking_after_gap_accepted(api):
    """PRD §3.3: "if the requested window, evaluated as a closed interval,
    intersects another booking of the same tenant that is `CONFIRMED` or `ACTIVE`,
    the request is rejected with `ERR_TENANT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/tenant_overlap_closed_interval
    """
    host, tenant, unit2 = _tenant_with_confirmed_booking(api)
    # Closed [2026-07-02,2026-08-02] does not intersect [2026-06-01,2026-07-01].
    resp = api.create_booking(
        create_booking_payload(unit2["id"], tenant["id"], "2026-07-02", "2026-08-02"),
        make_tenant_headers(tenant["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED", f"a non-intersecting tenant booking must be accepted, got {data['status']}"
