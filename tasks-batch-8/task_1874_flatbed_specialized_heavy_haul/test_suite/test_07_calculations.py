"""Calculation claims: flat width brackets, survey clearance boundary, credit
boundary equality, and the provisional estimate's input-set filtering
(PRD §3.1, §3.3, §3.5, §3.7)."""
from test_helpers import (
    BILLING,
    DISPATCHER,
    DRIVER,
    STATE_AUTHORITY,
    create_customer,
    create_load_for_customer,
    create_permit_for_load,
    deny_permit_payload,
    file_permit,
    issue_invoice,
    plan_load,
    set_clock,
    setup_standard_load_cleared,
    survey_load,
    validate_success,
)


def test_permit_width_bracket_is_flat(api):
    """PRD §3.5: "A **flat width surcharge**, which applies to `OVERSIZE` and
    `SUPERLOAD` permits only and is zero for `OVERWEIGHT`. Only the highest
    applicable bracket counts: width over 192 inches adds 10,000 cents; else
    over 168 inches adds 5,000; else over 144 inches adds 2,500; otherwise
    nothing."
    PRD §3.5: "A **marginal weight surcharge**, which applies to `OVERWEIGHT`
    and `SUPERLOAD` permits only and is zero for `OVERSIZE`."

    Design: Corner/calculations/permit_width_bracket_is_flat
    """
    customer = create_customer("Bracket Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide crate", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="E. Bo", driver_oversize_endorsed=True,
    )
    surveyed = survey_load(
        load["id"], route_miles=100, states_crossed=["AZ"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    permit = create_permit_for_load(
        load["id"], "AZ", "OVERSIZE",
        expected_load_version=surveyed["version"],
    )
    filed = file_permit(permit["id"])
    # AZ OVERSIZE base 8000 + highest applicable width bracket 2500 (>144);
    # weight surcharge is 0 for OVERSIZE.
    assert filed["fee_cents"] == 10500
    # Declared basis recorded even though unused for OVERSIZE.
    assert filed["weight_basis_lbs"] == 40000


def test_survey_clearance_boundary(api):
    """PRD §3.3: "The survey verdict is computed, not asserted. The survey
    passes when `overall_height_in` plus the 6-inch safety margin is less than
    or equal to `min_bridge_clearance_in`, **and** `gross_weight_lbs` is less
    than or equal to `max_bridge_weight_lbs`; otherwise it fails."
    PRD §3.3: "A failing survey leaves `survey_result` as `FAILED` and demotes
    the load for re-planning: a `SURVEYED` load drops back to `PLANNED`, while
    a `PLANNED` load that fails its survey simply stays `PLANNED` with the
    failed verdict stored."

    Design: Corner/calculations/survey_clearance_boundary
    """
    customer = create_customer("Clearance Co", 50_000_000)
    load_a = create_load_for_customer(
        customer["id"], cargo_description="Pass case", gross_weight_lbs=40000,
        width_in=100, height_in=100, length_in=400, origin="X", destination="Y",
    )
    plan_load(
        load_a["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="F. Ip", driver_oversize_endorsed=False,
    )
    load_b = create_load_for_customer(
        customer["id"], cargo_description="Fail case", gross_weight_lbs=40000,
        width_in=100, height_in=100, length_in=400, origin="X", destination="Y",
    )
    plan_load(
        load_b["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="F. Ip", driver_oversize_endorsed=False,
    )
    # overall_height 160 = 100 + FLATBED deck 60 on both loads.
    res_a = survey_load(
        load_a["id"], route_miles=100, states_crossed=["OR"],
        min_bridge_clearance_in=166, max_bridge_weight_lbs=80000,
    )
    # 160 + 6 == 166 meets <= exactly.
    assert res_a["survey_result"] == "PASSED"
    assert res_a["status"] == "SURVEYED"
    res_b = survey_load(
        load_b["id"], route_miles=100, states_crossed=["OR"],
        min_bridge_clearance_in=165, max_bridge_weight_lbs=80000,
    )
    # 165 is one inch short; a FAILED survey leaves the load PLANNED.
    assert res_b["survey_result"] == "FAILED"
    assert res_b["status"] == "PLANNED"


def test_credit_boundary_equality_passes(api):
    """PRD §3.7: "Finally, the provisional cost estimate's `total_cents` must
    not exceed the customer's remaining credit — `credit_limit_cents` minus
    `outstanding_balance_cents` — with equality passing and any excess rejected
    as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §3.1: "When an invoice is issued and the resulting
    `outstanding_balance_cents` is strictly greater than the customer's
    `credit_limit_cents`, the customer flips automatically to `SUSPENDED`;
    equality leaves the customer `ACTIVE`."

    Design: Corner/calculations/credit_boundary_equality_passes
    """
    # Credit limit exactly equals the 37800-cent estimate of a 100-mile
    # FLATBED STANDARD load (linehaul 35000 + fuel 2800).
    customer, load = setup_standard_load_cleared(
        company_name="Exact Credit Co", credit_limit_cents=37_800
    )
    set_clock("2026-08-12T10:00:00Z")
    departed = validate_success(api.depart_load(load["id"], DRIVER), 200)
    # 37800 <= 37800 passes the depart credit gate.
    assert departed["status"] == "IN_TRANSIT"
    validate_success(api.arrive_load(load["id"], DRIVER), 200)
    invoice = issue_invoice(load["id"])
    assert invoice["total_cents"] == 37800
    current = validate_success(api.get_customer(customer["id"], BILLING), 200)
    assert current["outstanding_balance_cents"] == 37800
    # Suspension requires strictly greater than the limit.
    assert current["status"] == "ACTIVE"


def test_estimate_input_set_excludes_denied(api):
    """PRD §3.7: "It mirrors the final invoice structure line for line but
    prices the future: linehaul is `route_miles` multiplied by the trailer's
    catalog cost per mile; permits are summed over `FILED` and `GRANTED`
    permits at their current `fee_cents`; escorts are summed over `CONFIRMED`
    bookings with each booking's charge rounded half-up individually before
    summing; `standby_cents` and `fines_cents` are both zero; and the subtotal,
    fuel surcharge, and total follow the same pinned rules as the invoice
    (§3.9)."

    Design: Corner/calculations/estimate_input_set_excludes_denied
    """
    customer = create_customer("Filter Co", 50_000_000)
    load = create_load_for_customer(
        customer["id"],
        cargo_description="Wide skid", gross_weight_lbs=40000,
        width_in=150, height_in=100, length_in=400,
        origin="X", destination="Y",
    )
    plan_load(
        load["id"], trailer_type="FLATBED", trailer_axle_count=2,
        driver_name="H. Su", driver_oversize_endorsed=True,
    )
    surveyed = survey_load(
        load["id"], route_miles=100, states_crossed=["NV"],
        min_bridge_clearance_in=200, max_bridge_weight_lbs=80000,
    )
    permit = create_permit_for_load(
        load["id"], "NV", "OVERSIZE",
        expected_load_version=surveyed["version"],
    )
    filed = file_permit(permit["id"])
    # NV OVERSIZE 7000 + width 150 bracket 2500.
    assert filed["fee_cents"] == 9500
    est1 = validate_success(api.get_cost_estimate(load["id"], DISPATCHER), 200)
    assert est1["permits_cents"] == 9500
    # subtotal 44500 = 35000 + 9500; fuel 8% = 3560.
    assert est1["total_cents"] == 48060
    validate_success(
        api.deny_permit(
            permit["id"],
            deny_permit_payload(denial_reason="route study required"),
            STATE_AUTHORITY,
        ),
        200,
    )
    est2 = validate_success(api.get_cost_estimate(load["id"], DISPATCHER), 200)
    # A DENIED permit leaves the provisional input set {FILED, GRANTED}.
    assert est2["permits_cents"] == 0
    assert est2["total_cents"] == 37800
