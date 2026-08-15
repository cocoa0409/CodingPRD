"""BER and TAT boundary precision (difficulty queue A rule 6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    approve_quote,
    book_cell,
    complete_repair,
    create_customer,
    create_part,
    create_test_cell,
    create_unit,
    create_work_order,
    generate_invoice,
    get_work_order,
    make_customer_headers,
    record_test_results,
    release_work_order,
    set_clock,
    setup_work_order_in_teardown,
    submit_quote,
    validate_success,
)


def test_ber_estimate_exactly_at_threshold_is_ber(api):
    """PRD §3.3: "the BER threshold in cents is `ber_threshold_pct` percent
    of the part's `replacement_value_cents`, rounded half up to whole cents,
    and `ber_flag` is true when the sum of the two estimates is at least
    that threshold — the boundary is inclusive, so an estimate exactly equal
    to the threshold is beyond economic repair."

    Design: Difficulty/boundary_precision_check/ber_estimate_exactly_at_threshold_is_ber
    """
    customer = create_customer()
    part = create_part()  # replacement 10_000_000, ber_threshold_pct default 65
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api.teardown_complete(wo["id"], TECHNICIAN)

    # 5_500_000 + 1_000_000 == 6_500_000 == 65% of 10_000_000 — exactly the threshold.
    res = api.submit_quote(
        wo["id"],
        {"labor_estimate_cents": 5500000, "parts_estimate_cents": 1000000,
         "scrap_option_ack": True},
        CSR)
    quoted = validate_success(res, 200)
    assert quoted["ber_flag"] is True


def test_ber_estimate_one_cent_below_threshold_not_ber(api):
    """PRD §3.3: "`ber_flag` is true when the sum of the two estimates is at
    least that threshold" — one cent below (6_499_999) is NOT at least the
    threshold, so `ber_flag` is false. PRD §3.3: "Re-quoting is a self-loop
    from `QUOTE_SUBMITTED` back to `QUOTE_SUBMITTED`: the same checks apply,
    and the new submission supersedes the prior quote".

    Design: Difficulty/boundary_precision_check/ber_estimate_exactly_at_threshold_is_ber
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api.teardown_complete(wo["id"], TECHNICIAN)

    # First quote at exactly the threshold — BER.
    validate_success(api.submit_quote(
        wo["id"],
        {"labor_estimate_cents": 5500000, "parts_estimate_cents": 1000000,
         "scrap_option_ack": True},
        CSR), 200)

    # Re-quote one cent below the threshold — superseding quote clears ber_flag.
    res = api.submit_quote(
        wo["id"],
        {"labor_estimate_cents": 5499999, "parts_estimate_cents": 1000000,
         "scrap_option_ack": False},
        CSR)
    requoted = validate_success(res, 200)
    assert requoted["ber_flag"] is False


def _drive_to_released_at(approve_delay_iso: str, test_clock: str,
                          booking_window, labor_estimate_cents=2000000,
                          parts_estimate_cents=1000000,
                          customer_overrides=None,
                          requisition_specs=None):
    """Drive an OVERHAUL work order to RELEASED with controlled timestamps."""
    from test_helpers import issue_received_requisition, create_parts_requisition
    customer = create_customer(**(customer_overrides or {}))
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(
        wo["id"], labor_estimate_cents=labor_estimate_cents,
        parts_estimate_cents=parts_estimate_cents, scrap_option_ack=False)
    if approve_delay_iso is not None:
        set_clock(approve_delay_iso)
    approve_quote(wo["id"], customer["id"], quoted["version"])
    for spec in (requisition_specs or []):
        spec = dict(spec)
        unit_cost = spec.pop("unit_cost_cents")
        req = create_parts_requisition(wo["id"], **spec)
        issue_received_requisition(req["id"], unit_cost)
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time=booking_window[0], end_time=booking_window[1])
    set_clock(test_clock)
    record_test_results(wo["id"], result="PASS", inspector_user_id="insp-9")
    return customer, part, unit, release_work_order(wo["id"], inspector_user_id="insp-9")


def test_tat_adjusted_hours_exactly_at_guarantee_zero_penalty(api):
    """PRD §3.6: "The excess is the amount by which the basis exceeds the
    customer's `contract_tat_hours`, floored at zero" — adjusted hours
    exactly equal to the guarantee produce zero excess, so the penalty
    credit is 0 (boundary: excess must be strictly greater than zero to
    bill).

    Design: Difficulty/boundary_precision_check/tat_adjusted_hours_exactly_at_guarantee_zero_penalty
    """
    # ADJUSTED: received 2026-08-01T00:00:00Z; approve at 2026-08-03T12:00:00Z
    # (delay 60h); release at 2026-08-07T16:00:00Z -> elapsed 160h, adjusted
    # exactly 100h == contract_tat_hours.
    customer, part, unit, released = _drive_to_released_at(
        approve_delay_iso="2026-08-03T12:00:00Z",
        test_clock="2026-08-07T16:00:00Z",
        booking_window=("2026-08-07T14:00:00Z", "2026-08-07T18:00:00Z"),
        customer_overrides={"penalty_delay_rule": "ADJUSTED"},
        requisition_specs=[{"part_number": "BRG-32-99", "quantity": 2,
                             "requested_source": "OEM", "unit_cost_cents": 250000}],
    )
    invoice = generate_invoice(released["id"])
    assert invoice["penalty_credit_cents"] == 0
    # labor 2000000 + parts 575000 (2 * 250000 * 1.15 tier-2 markup) + fee 400000 (4h * 100000)
    assert invoice["total_cents"] == 2975000


def test_tat_adjusted_hours_one_hour_over_bills_one_hour(api):
    """PRD §3.6: "The excess is the amount by which the basis exceeds the
    customer's `contract_tat_hours`, floored at zero; the raw penalty is the
    excess multiplied by `tat_penalty_rate_cents_per_hour`" — at 101h
    adjusted vs 100h guarantee, excess is exactly 1h, so the penalty credit
    is 5000 cents.

    Design: Difficulty/boundary_precision_check/tat_adjusted_hours_exactly_at_guarantee_zero_penalty
    """
    # Same setup but release one hour later: elapsed 161h, adjusted 101h,
    # excess 1h.
    customer, part, unit, released = _drive_to_released_at(
        approve_delay_iso="2026-08-03T12:00:00Z",
        test_clock="2026-08-07T17:00:00Z",
        booking_window=("2026-08-07T14:00:00Z", "2026-08-07T18:00:00Z"),
        customer_overrides={"penalty_delay_rule": "ADJUSTED"},
        requisition_specs=[{"part_number": "BRG-32-99", "quantity": 2,
                             "requested_source": "OEM", "unit_cost_cents": 250000}],
    )
    invoice = generate_invoice(released["id"])
    assert invoice["penalty_credit_cents"] == 5000
    assert invoice["total_cents"] == 2975000 - 5000


def test_warranty_cycle_claim_exactly_at_limit_eligible(api):
    """PRD §3.9: "the claim must lie within both coverage ceilings,
    inclusive — `claim_cycles_used` at most the part's `warranty_cycle_limit`
    and `claim_months_used` at most its `warranty_month_limit` — otherwise
    `ERR_WARRANTY_LIMIT_EXCEEDED` (HTTP 422). A filed claim starts
    `SUBMITTED`."

    Design: Difficulty/boundary_precision_check/warranty_cycle_claim_exactly_at_limit_eligible
    """
    from test_helpers import setup_work_order_closed, create_warranty_claim
    customer, part, unit, wo, invoice = setup_work_order_closed()
    # 500 == warranty_cycle_limit AND 24 == warranty_month_limit (both inclusive).
    claim = create_warranty_claim(
        wo["id"], customer["id"],
        claim_cycles_used=500, claim_months_used=24,
        failure_description="At-limit claim")
    assert claim["status"] == "SUBMITTED"


def test_warranty_cycle_claim_below_limit_also_eligible(api):
    """PRD §3.9: "`claim_cycles_used` at most the part's
    `warranty_cycle_limit`" — the inclusive gate accepts values strictly
    below the ceiling too, and the filed claim starts `SUBMITTED`.

    Design: Difficulty/boundary_precision_check/warranty_cycle_claim_exactly_at_limit_eligible
    """
    from test_helpers import setup_work_order_closed, create_warranty_claim
    customer, part, unit, wo, invoice = setup_work_order_closed()
    claim = create_warranty_claim(
        wo["id"], customer["id"],
        claim_cycles_used=499, claim_months_used=23,
        failure_description="Just-below-limit claim")
    assert claim["status"] == "SUBMITTED"
