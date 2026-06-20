"""Temporal-interval semantics (UCC half-open windows, serial-reuse closed buffer)
and remarketing / depreciation.

Difficulty queue: resource_temporal_overlap.
Corner queue: calculations (remarketing gain/loss, property depreciation year one).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_lessor,
    create_approved_lessee,
    create_lease,
    set_clock,
    setup_active_lease,
    setup_end_of_term_lease,
    setup_listed_unit,
    elect,
    exercise,
    TEST_USERS,
)

OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]
ASSET_MGR = TEST_USERS["asset_manager_headers"]


# ─── resource_temporal_overlap / ucc_half_open_coverage_overlap ───────
def test_ucc_continuation_inside_coverage_window_rejected(api):
    """PRD §3.7: "A new filing for the same lease and jurisdiction is rejected with
    `ERR_UCC_OVERLAP` if the lessor's current clock falls inside the half-open
    coverage window of an existing `FILED` filing for that same lease and
    jurisdiction — that is, at or after that filing's filed instant and strictly
    before its coverage end."

    Funding auto-files a UCC covering [2026-01-01, 2031-01-01). With the clock at
    2027-06-01 (inside the window), a manual continuation is rejected
    ERR_UCC_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/ucc_half_open_coverage_overlap_rejected
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_active_lease(
        lessor_id=lessor_id, equipment_cost_cents=500_000, term_months=60,
        monthly_rate_factor_bps=200, serial_number="SN-1100")
    set_clock(lessor_id, "2027-06-01T00:00:00.000Z")
    res = api.create_ucc_filing(
        lessor_id, ctx["lease"]["id"], {"jurisdiction_state_code": "NY"}, OFFICER)
    validate_error(res, ApiErrorId.ERR_UCC_OVERLAP.value)


def test_ucc_continuation_at_filed_instant_lower_boundary_rejected(api):
    """PRD §3.7: "A new filing for the same lease and jurisdiction is rejected with
    `ERR_UCC_OVERLAP` if the lessor's current clock falls inside the half-open
    coverage window of an existing `FILED` filing for that same lease and
    jurisdiction — that is, at or after that filing's filed instant and strictly
    before its coverage end."

    Lower (inclusive) boundary of the half-open window: with the clock still at
    the funding instant 2026-01-01 (== the auto-filing's filed instant), a manual
    continuation is rejected ERR_UCC_OVERLAP, since the window covers its start.

    Design: Difficulty/resource_temporal_overlap/ucc_half_open_coverage_overlap_rejected
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_active_lease(
        lessor_id=lessor_id, equipment_cost_cents=500_000, term_months=60,
        monthly_rate_factor_bps=200, serial_number="SN-1101")
    # Clock unchanged: equals the auto-filing's filed_clock_utc (window start).
    res = api.create_ucc_filing(
        lessor_id, ctx["lease"]["id"], {"jurisdiction_state_code": "NY"}, OFFICER)
    validate_error(res, ApiErrorId.ERR_UCC_OVERLAP.value)


# ─── resource_temporal_overlap / serial_reuse_closed_buffer ───────────
def test_serial_reuse_within_buffer_window_rejected(api):
    """PRD §3.5: "if some unit bearing the same serial was disposed at clock instant
    D, reuse is blocked while the lessor's current `clock_utc` is less than or equal
    to D plus the buffer of 30 days — the buffer window is closed at both ends, so
    reuse is permitted only strictly after D plus 30 days."

    A unit with serial DUP-1 disposed at clock 2026-03-01; with the clock at
    2026-03-15 (inside [D, D+30d]), re-attaching the same serial returns
    ERR_SERIAL_REUSE_TOO_SOON.

    Design: Difficulty/resource_temporal_overlap/serial_reuse_closed_buffer_blocks_within_30_days
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    # First lease: attach DUP-1, take to end-of-term/return, then dispose at D.
    ctx = setup_end_of_term_lease(
        lessor_id=lessor_id, serial_number="DUP-1", original_cost_cents=500_000,
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000)
    lease1_id, unit1_id = ctx["lease"]["id"], ctx["unit"]["id"]
    election = elect(lessor_id, lease1_id, "RETURN")
    exercise(lessor_id, lease1_id, election["id"])
    set_clock(lessor_id, "2026-03-01T00:00:00.000Z")
    get_success_data(api.return_equipment(lessor_id, unit1_id, ASSET_MGR))
    get_success_data(api.dispose_equipment(lessor_id, unit1_id, ASSET_MGR))
    # Second lease, clock inside buffer, reuse DUP-1.
    vendor_id = ctx["vendor_id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease2 = create_lease(lessor_id, lessee_id, vendor_id,
                          equipment_cost_cents=400_000, term_months=12,
                          monthly_rate_factor_bps=2000)
    set_clock(lessor_id, "2026-03-15T00:00:00.000Z")
    res = api.attach_equipment(
        lessor_id, lease2["id"],
        {"serial_number": "DUP-1", "description": "Press v2", "original_cost_cents": 400_000},
        OFFICER)
    validate_error(res, ApiErrorId.ERR_SERIAL_REUSE_TOO_SOON.value)


def test_serial_reuse_at_buffer_end_boundary_still_blocked(api):
    """PRD §3.5: "reuse is blocked while the lessor's current `clock_utc` is less
    than or equal to D plus the buffer of 30 days — the buffer window is closed at
    both ends, so reuse is permitted only strictly after D plus 30 days."

    Inclusive closed-buffer end: a serial DISPOSED at D=2026-03-01 has a buffer
    through 2026-03-31 (D+30 days) inclusive; re-attaching the serial at exactly
    2026-03-31 is still blocked with ERR_SERIAL_REUSE_TOO_SOON.

    Design: Difficulty/resource_temporal_overlap/serial_reuse_closed_buffer_blocks_within_30_days
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_end_of_term_lease(
        lessor_id=lessor_id, serial_number="DUP-2", original_cost_cents=500_000,
        equipment_cost_cents=500_000, term_months=1, monthly_rate_factor_bps=2000)
    lease1_id, unit1_id = ctx["lease"]["id"], ctx["unit"]["id"]
    election = elect(lessor_id, lease1_id, "RETURN")
    exercise(lessor_id, lease1_id, election["id"])
    set_clock(lessor_id, "2026-03-01T00:00:00.000Z")
    get_success_data(api.return_equipment(lessor_id, unit1_id, ASSET_MGR))
    get_success_data(api.dispose_equipment(lessor_id, unit1_id, ASSET_MGR))
    vendor_id = ctx["vendor_id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease2 = create_lease(lessor_id, lessee_id, vendor_id,
                          equipment_cost_cents=400_000, term_months=12,
                          monthly_rate_factor_bps=2000)
    set_clock(lessor_id, "2026-03-31T00:00:00.000Z")  # exactly D+30 days, inclusive
    res = api.attach_equipment(
        lessor_id, lease2["id"],
        {"serial_number": "DUP-2", "description": "Press v2", "original_cost_cents": 400_000},
        OFFICER)
    validate_error(res, ApiErrorId.ERR_SERIAL_REUSE_TOO_SOON.value)


# ─── Corner: calculations / remarketing_gain_loss_against_residual ────
def test_record_sale_records_proceeds_on_listed_unit(api):
    """PRD §3.12: "Selling a listed unit — a `record-sale` action — moves it from
    `LISTED` to `SOLD`. The request carries `sale_proceeds_cents`, which must be at
    least zero (otherwise `ERR_INVALID_REQUEST`); the system records those proceeds
    on the unit and computes the remarketing gain or loss as `sale_proceeds_cents`
    minus the owning lease's `residual_value_cents`".

    Recording a sale of 120000 on a LISTED unit (FMV term-1 lease, residual 100000)
    sets status SOLD and sale_proceeds_cents 120000 (a 20000 gain against residual).

    Design: Corner/calculations/remarketing_gain_loss_against_residual
    """
    ctx = setup_listed_unit(serial_number="I-SN-1", original_cost_cents=500_000,
                            equipment_cost_cents=500_000)
    lessor_id, unit_id = ctx["lessor_id"], ctx["unit"]["id"]
    sold = get_success_data(api.record_sale(
        lessor_id, unit_id, {"sale_proceeds_cents": 120_000}, ASSET_MGR))
    assert sold["status"] == "SOLD", f"got {sold['status']}"
    assert sold["sale_proceeds_cents"] == 120_000, f"got {sold['sale_proceeds_cents']}"


# ─── Corner: calculations / property_assessed_value_depreciation_year_one ─
def test_property_assessment_depreciates_after_one_year(api):
    """PRD §3.8: "The depreciated value is the unit's `original_cost_cents` minus
    the result of multiplying that original cost by ten percent per year in service,
    that product being rounded half up."
    PRD §3.8: "For a `PROPERTY` assessment ... the tax amount is that base
    multiplied by the lessor's `property_tax_rate_bps`, divided by 10,000, rounded
    half up."

    A 500000-cost unit booked at 2026-01-01, assessed at 2027-01-01 (one year in
    service), depreciates to 450000; PROPERTY tax at 120 bps = 5400.

    Design: Corner/calculations/property_assessed_value_depreciation_year_one
    """
    lessor_id = create_lessor(home_state_code="NY")["id"]
    set_clock(lessor_id, "2026-01-01T00:00:00.000Z")
    ctx = setup_active_lease(
        lessor_id=lessor_id, equipment_cost_cents=500_000, term_months=36,
        monthly_rate_factor_bps=250, serial_number="K-SN-1", original_cost_cents=500_000)
    set_clock(lessor_id, "2027-01-01T00:00:00.000Z")
    res = api.create_tax_assessment(
        lessor_id, ctx["lease"]["id"], {"tax_type": "PROPERTY"}, SERVICER)
    prop = validate_success(res, 201)
    assert prop["taxable_base_cents"] == 450_000, f"got {prop['taxable_base_cents']}"
    assert prop["tax_amount_cents"] == 5400, f"got {prop['tax_amount_cents']}"
