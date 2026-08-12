"""Port dues, agency fee, late-cancel, variance, and exposure calculations."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_vendor, create_service_order, create_purchase_order,
    drive_call_to_alongside, send_da_and_fund, sail_call,
    make_agency_ops_headers, make_agency_admin_headers, make_agency_finance_headers,
    make_port_authority_headers, make_vendor_rep_headers,
)
from test_helpers.factories import create_tariff_payload
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / port_dues_tier_boundary_and_surcharges
# ---------------------------------------------------------------------------

def test_port_dues_gt_at_tier_boundary_inclusive(api):
    """PRD §3.8: "Because each `gt_up_to` is inclusive, a vessel whose gross
    tonnage equals a band's upper bound bills that tonnage entirely within that
    band."

    Design: Difficulty/combinatorial_formula/port_dues_tier_boundary_and_surcharges
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], vessel_name="MV Low", imo_number="9000010",
        vessel_gt=20000, port_code="SINGA",
        eta="2026-06-10T10:00:00Z", etd="2026-06-11T09:00:00Z")
    tariff = get_success_data(api_client.create_tariff(
        create_tariff_payload(gt_tiers=[
            {"gt_up_to": 20000, "rate_cents": 2.0},
            {"gt_up_to": None, "rate_cents": 1.5},
        ]), make_port_authority_headers()))
    da = create_da_for_call(pc)
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    assert len(lines) == 1
    line = lines[0]
    assert line["category"] == "PORT_DUES"
    # 20000 GT entirely inside tier 1: 20000 * 2.0 * 1 day = 40000
    assert line["estimated_cents"] == 40000, (
        f"GT 20000 at inclusive boundary must bill entirely within tier 1; got {line['estimated_cents']}")


def test_port_dues_gt_one_over_tier_boundary(api):
    """PRD §3.8: "for each band, the billable tonnage is the lesser of the
    vessel's `vessel_gt` and the band's upper bound, minus the accumulated
    upper bounds of all lower bands, and whenever that portion is positive it
    is multiplied by the band's `rate_cents`"; "The resulting line amount is
    rounded half-up to integer cents exactly once, at the line level."

    Design: Difficulty/combinatorial_formula/port_dues_tier_boundary_and_surcharges
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], vessel_name="MV High", imo_number="9000011",
        vessel_gt=20001, port_code="SINGA",
        eta="2026-06-10T10:00:00Z", etd="2026-06-11T09:00:00Z")
    get_success_data(api_client.create_tariff(
        create_tariff_payload(gt_tiers=[
            {"gt_up_to": 20000, "rate_cents": 2.0},
            {"gt_up_to": None, "rate_cents": 1.5},
        ]), make_port_authority_headers()))
    da = create_da_for_call(pc)
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    line = lines[0]
    # 20000 * 2.0 + 1 * 1.5 = 40001.5 -> round half-up once -> 40002
    assert line["estimated_cents"] == 40002, (
        f"GT 20001 must bill the extra ton at the marginal 1.5 rate; got {line['estimated_cents']}")


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / agency_fee_per_line_rounding_order
# ---------------------------------------------------------------------------

def test_agency_fee_per_line_rounding_order(api):
    """PRD §3.8: "each line's fee is rounded half-up to integer cents first,
    and the rounded per-line integers are then summed — summing first and
    rounding once is expressly not the rule, so two lines of 3333 cents each
    contribute 83 cents apiece for a 166-cent fee, never 167."

    Design: Difficulty/combinatorial_formula/agency_fee_per_line_rounding_order
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 3333, description="l1")
    add_manual_line(da["id"], 3333, description="l2")
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da["agency_fee_estimated_cents"] == 166, (
        f"per-line-then-sum rounding must yield 166, not 167; got {da['agency_fee_estimated_cents']}")
    assert da["total_estimated_cents"] == 6832


def test_agency_fee_feeds_advance_requirement_after_lines(api):
    """PRD §2.11: "The evaluation order inside a recompute is pinned: line
    amounts first, then the per-line agency fee, then the advance requirement
    derived from the fee-inclusive total."
    PRD §3.8: "`advance_required_cents` is eighty percent of that total,
    rounded half-up to integer cents."

    Design: Difficulty/combinatorial_formula/agency_fee_per_line_rounding_order
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 3333, description="l1")
    add_manual_line(da["id"], 3333, description="l2")
    da = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    # round_half_up(0.80 * 6832) = round_half_up(5465.6) = 5466
    assert da["advance_required_cents"] == 5466, (
        f"advance requirement derives from fee-inclusive total 6832; got {da['advance_required_cents']}")


# ---------------------------------------------------------------------------
# Queue B: calculations / port_dues_day_ceiling_boundary
# ---------------------------------------------------------------------------

def test_port_dues_day_ceiling_exactly_24h(api):
    """PRD §3.8: "The billable duration in days is the hours between the two
    bounding timestamps divided by twenty-four, rounded up to a whole number,
    with a minimum of one day."

    Design: Corner/calculations/port_dues_day_ceiling_boundary
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc_a = create_port_call(
        principal["id"], vessel_name="MV Day", imo_number="9000040",
        vessel_gt=5000, port_code="SINGA",
        eta="2026-06-10T10:00:00Z", etd="2026-06-11T10:00:00Z")
    pc_b = create_port_call(
        principal["id"], vessel_name="MV Plus", imo_number="9000041",
        vessel_gt=5000, port_code="SINGA",
        eta="2026-06-10T10:00:00Z", etd="2026-06-11T11:00:00Z")
    get_success_data(api_client.create_tariff(
        create_tariff_payload(gt_tiers=[{"gt_up_to": None, "rate_cents": 2.0}]),
        make_port_authority_headers()))
    da_a = create_da_for_call(pc_a)
    da_b = create_da_for_call(pc_b)
    lines_a, _ = validate_paginated(api_client.list_da_lines(da_a["id"], make_agency_ops_headers()))
    lines_b, _ = validate_paginated(api_client.list_da_lines(da_b["id"], make_agency_ops_headers()))
    pc_a_now = validate_success(api_client.get_port_call(pc_a["id"], make_agency_ops_headers()))
    pc_b_now = validate_success(api_client.get_port_call(pc_b["id"], make_agency_ops_headers()))
    assert pc_a_now["alongside_days_estimated"] == 1
    assert lines_a[0]["estimated_cents"] == 10000, "24h bills exactly 1 day: 5000 * 2.0 * 1"
    assert pc_b_now["alongside_days_estimated"] == 2
    assert lines_b[0]["estimated_cents"] == 20000, "25h rounds up to 2 days: 5000 * 2.0 * 2"


# ---------------------------------------------------------------------------
# Queue B: calculations / late_cancel_fee_cutoff_boundary
# ---------------------------------------------------------------------------

def _setup_two_confirmed_tug_orders():
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-05T08:00:00Z", etd="2026-06-06T08:00:00Z")
    da = create_da_for_call(pc)
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="t@x.example")
    vh = make_vendor_rep_headers(vendor["id"])
    so_a = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-1",
        window_start="2026-06-05T12:00:00Z", window_end="2026-06-05T13:00:00Z",
        estimated_cents=20000)
    so_b = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-2",
        window_start="2026-06-05T12:00:00Z", window_end="2026-06-05T13:00:00Z",
        estimated_cents=20000)
    get_success_data(api_client.confirm_service_order(so_a["id"], vh))
    get_success_data(api_client.confirm_service_order(so_b["id"], vh))
    return pc, da, so_a, so_b


def test_late_cancel_exactly_at_cutoff_not_late(api):
    """PRD §3.5: "a cancellation exactly two hours before the window is not
    late."

    Design: Corner/calculations/late_cancel_fee_cutoff_boundary
    """
    pc, da, so_a, so_b = _setup_two_confirmed_tug_orders()
    # window_start 12:00, cutoff = 10:00; cancel at exactly 10:00 -> fee 0
    set_clock("2026-06-05T10:00:00Z")
    so_a = validate_success(api_client.cancel_service_order(so_a["id"], make_agency_ops_headers()))
    assert so_a["status"] == "CANCELLED"
    assert so_a["cancellation_fee_cents"] == 0, (
        f"cancellation exactly two hours before window_start is not late; got fee {so_a['cancellation_fee_cents']}")


def test_late_cancel_one_second_inside_cutoff_charges_quarter(api):
    """PRD §3.5: "A direct cancellation made strictly later than two hours
    before `window_start` incurs a `cancellation_fee_cents` of one quarter of
    the order's `estimated_cents`, rounded half-up to integer cents"; "when a
    positive fee was charged and the account is in `PRO_FORMA`,
    `SENT_TO_PRINCIPAL`, or `FUNDED`, a `CANCELLATION_FEE` line is appended to
    the account with `actual_cents` equal to the fee and status `ACTUALIZED`."

    Design: Corner/calculations/late_cancel_fee_cutoff_boundary
    """
    pc, da, so_a, so_b = _setup_two_confirmed_tug_orders()
    set_clock("2026-06-05T10:00:01Z")
    so_b = validate_success(api_client.cancel_service_order(so_b["id"], make_agency_ops_headers()))
    assert so_b["cancellation_fee_cents"] == 5000, (
        f"one second inside the 2h cutoff charges 25% of 20000; got {so_b['cancellation_fee_cents']}")
    lines, _ = validate_paginated(api_client.list_da_lines(da["id"], make_agency_ops_headers()))
    fee_lines = [l for l in lines if l["category"] == "CANCELLATION_FEE"]
    assert len(fee_lines) == 1, "exactly one CANCELLATION_FEE line appended"
    assert fee_lines[0]["actual_cents"] == 5000
    assert fee_lines[0]["status"] == "ACTUALIZED"
    mirror = [l for l in lines if l.get("source_ref") == f"ServiceOrder:{so_b['id']}"]
    assert mirror and mirror[0]["estimated_cents"] == 0, "mirror line reversed to zero"


# ---------------------------------------------------------------------------
# Queue B: calculations / po_variance_exact_tolerance_boundary
# ---------------------------------------------------------------------------

def _setup_delivered_po(pc_id, vendor_id, estimated=10000):
    po = create_purchase_order(pc_id, vendor_id, estimated_cents=estimated)
    vh = make_vendor_rep_headers(vendor_id)
    get_success_data(api_client.send_purchase_order(po["id"], make_agency_ops_headers()))
    get_success_data(api_client.acknowledge_purchase_order(po["id"], vh))
    get_success_data(api_client.deliver_purchase_order(po["id"], vh))
    return po


def test_po_variance_exactly_ten_percent_within_tolerance(api):
    """PRD §3.4: "An absolute variance of at most 10.0 percent — a value of
    exactly 10.0 counts as within tolerance — routes the order to `INVOICED`."

    Design: Corner/calculations/po_variance_exact_tolerance_boundary
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"], contact_email="c@x.example")
    po = _setup_delivered_po(pc["id"], vendor["id"], estimated=10000)
    po = validate_success(api_client.invoice_purchase_order(
        po["id"], {"invoiced_cents": 11000}, make_vendor_rep_headers(vendor["id"])))
    assert po["status"] == "INVOICED"
    assert po["variance_pct"] == 10.0, f"11000 on 10000 is exactly 10.0; got {po['variance_pct']}"


def test_po_variance_one_cent_over_tolerance_forks_disputed(api):
    """PRD §3.4: "An absolute variance strictly greater than 10.0 percent
    routes the order to `DISPUTED` instead."

    Design: Corner/calculations/po_variance_exact_tolerance_boundary
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=0)
    pc = create_port_call(principal["id"])
    vendor = create_vendor(name="ChandlerCo", categories=["PROVISIONS"], contact_email="c@x.example")
    po = _setup_delivered_po(pc["id"], vendor["id"], estimated=10000)
    po = validate_success(api_client.invoice_purchase_order(
        po["id"], {"invoiced_cents": 11001}, make_vendor_rep_headers(vendor["id"])))
    assert po["status"] == "DISPUTED"
    assert po["variance_pct"] == 10.01, f"11001 on 10000 is 10.01; got {po['variance_pct']}"


# ---------------------------------------------------------------------------
# Queue B: calculations / exposure_input_set_filtering
# ---------------------------------------------------------------------------

def test_exposure_excludes_superseded_accounts(api):
    """PRD §3.1: "The exposure itself is computed in two variants, both
    restricted to the non-`SUPERSEDED` accounts of the principal's port calls
    whose `ops_status` is neither `CLOSED` nor `CANCELLED`."
    PRD §3.8: "creation supersedes any existing `PRO_FORMA` account of the
    same call, moving it to `SUPERSEDED` without carrying its lines over."

    Design: Corner/calculations/exposure_input_set_filtering
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex", credit_limit_cents=500000)
    pc = create_port_call(principal["id"])
    da1 = create_da_for_call(pc)
    add_manual_line(da1["id"], 50000, description="big")
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    da2 = create_da_for_call(pc_now)
    da1_now = validate_success(api_client.get_disbursement_account(da1["id"], make_agency_ops_headers()))
    assert da1_now["status"] == "SUPERSEDED"
    assert da2["status"] == "PRO_FORMA"
    exposure = validate_success(api_client.get_principal_exposure(
        principal["id"], make_agency_finance_headers()))
    assert exposure["forward_exposure_cents"] == 0, (
        f"SUPERSEDED account excluded and fresh account empty; got {exposure['forward_exposure_cents']}")
    assert exposure["cash_basis_exposure_cents"] == 0
