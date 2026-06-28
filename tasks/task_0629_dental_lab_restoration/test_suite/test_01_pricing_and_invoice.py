"""Pricing-engine tests: per-unit rounding order, the nested tier/rush/tax chain,
and the provisional-vs-final dual variant on a doctor volume-tier crossing.

All translate difficulty-design instances (queue A) and one calculations corner
instance (queue B).
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    assert_invoice_total_identity,
    create_doctor_payload, create_material_payload, create_case_payload,
    create_restoration_payload,
    TEST_USERS, make_doctor_headers,
    setup_submitted_case, get_invoice_for_case,
    create_doctor, create_material, deliver_n_cases_for_doctor,
)

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_per_unit_round_then_sum_bridge_subtotal(api):
    """PRD §3.3: "The rounding to whole cents happens per unit, before any
    quantity multiplication or cross-restoration summation - this ordering is
    mandatory." PRD §3.3: "for instance a base of 9999 cents at factor 1.25
    across three units yields 37497 cents under the required per-unit-rounded
    order versus 37496 cents under round-once."

    Design: Difficulty/dual_variant_calc/pricing_per_unit_round_vs_sum_then_round
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 3,
                            "requested_shade": "A1"}],
        material_overrides={"base_unit_price_cents": 9999,
                            "fabrication_process": "MILLED"},
    )
    rest = get_success_data(api.get_restoration(built["restorations"][0]["id"], ADMIN))
    assert rest["unit_price_cents"] == 12499, (
        f"per-unit price must round 9999*1.25=12498.75 half up to 12499, "
        f"got {rest['unit_price_cents']}"
    )
    invoice = get_invoice_for_case(built["case"]["id"])
    assert invoice["subtotal_cents"] == 37497, (
        f"subtotal must be 3*12499=37497 (per-unit-round then sum), not 37496; "
        f"got {invoice['subtotal_cents']}"
    )


def test_per_unit_round_order_pinned_combinatorial(api):
    """PRD §3.3: "The rounding to whole cents happens per unit, before any
    quantity multiplication or cross-restoration summation - this ordering is
    mandatory." PRD §3.3: "a base of 9999 cents at factor 1.25 across three
    units yields 37497 cents under the required per-unit-rounded order versus
    37496 cents under round-once."

    Design: Difficulty/combinatorial_formula/pricing_per_unit_round_order_pinned
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 3,
                            "requested_shade": "B1"}],
        material_overrides={"base_unit_price_cents": 9999,
                            "fabrication_process": "MILLED"},
    )
    rest = get_success_data(api.get_restoration(built["restorations"][0]["id"], ADMIN))
    assert rest["unit_price_cents"] == 12499
    invoice = get_invoice_for_case(built["case"]["id"])
    assert invoice["subtotal_cents"] == 37497


def test_invoice_nested_tier_rush_tax_chain(api):
    """PRD §3.3: "The rush_surcharge_cents is the subtotal multiplied by 0.50
    and rounded half up when the case is a rush, and 0 otherwise." PRD §3.3:
    "The pre-discount base is the subtotal plus the rush surcharge." PRD §3.3:
    "The discount_cents is that pre-discount base multiplied by the doctor's
    volume-tier percentage and rounded half up: a doctor with a
    completed_case_count of 0 through 4 earns 0%, one with 5 through 19 earns
    5%, and one with 20 or more earns 10%." PRD §3.3: "tax_cents is that taxable
    amount multiplied by 0.0825 and rounded half up." PRD §3.3: "total_cents is
    the taxable amount plus tax minus the SLA credit."

    Design: Difficulty/combinatorial_formula/invoice_total_nested_tier_rush_tax_chain
    """
    # base 15000 * BRIDGE 1.25 = 18750/unit; 3 units -> subtotal 56250.
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=15000, fabrication_process="MILLED")
    # Push the doctor to the 20+ tier (10%) via 20 delivered warm crown cases.
    deliver_n_cases_for_doctor(doctor["id"], 20, material)
    refreshed = get_success_data(api.get_doctor(doctor["id"], ADMIN))
    assert refreshed["completed_case_count"] == 20

    case = get_success_data(api.create_case(
        create_case_payload(doctor["id"], intake_method="INTRAORAL_SCAN", is_rush=True), TECH))
    get_success_data(api.create_restoration(
        case["id"], create_restoration_payload(material["id"], restoration_type="BRIDGE",
                                                unit_count=3, requested_shade="A2"), TECH))
    get_success_data(api.submit_case(case["id"], TECH))

    invoice = get_invoice_for_case(case["id"])
    assert invoice["subtotal_cents"] == 56250
    assert invoice["rush_surcharge_cents"] == 28125            # round(56250*0.50)
    assert invoice["discount_cents"] == 8438                   # round(84375*0.10)=8437.5 -> 8438
    assert invoice["tax_cents"] == 6265                        # round((84375-8438)*0.0825)
    assert invoice["total_cents"] == 82202                     # 75937 + 6265
    assert_invoice_total_identity(invoice)


def test_provisional_vs_final_diverge_on_tier_crossing(api):
    """PRD §3.6: "The final variant re-reads the doctor's completed_case_count
    at ship time, which may have crossed into a higher discount tier between
    submit and ship, so the discount can differ from the provisional figure even
    on identical line items." PRD §3.3: "a doctor with a completed_case_count of
    0 through 4 earns 0%, one with 5 through 19 earns 5%, and one with 20 or more
    earns 10%." PRD §3.6: "Acceptance also flips the case's invoice from
    PROVISIONAL to FINAL and reruns the total computation in its final variant."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_tier_crossing
    """
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    # Doctor delivered exactly 4 cases -> tier 0 (0%) at submit time.
    deliver_n_cases_for_doctor(doctor["id"], 4, material)
    assert get_success_data(api.get_doctor(doctor["id"], ADMIN))["completed_case_count"] == 4

    # Build + submit the SUT crown case while count == 4: provisional at tier 0.
    sut = get_success_data(api.create_case(
        create_case_payload(doctor["id"], intake_method="INTRAORAL_SCAN"), TECH))
    rest = get_success_data(api.create_restoration(
        sut["id"], create_restoration_payload(material["id"], restoration_type="CROWN",
                                               unit_count=1), TECH))
    get_success_data(api.submit_case(sut["id"], TECH))
    provisional = get_invoice_for_case(sut["id"])
    assert provisional["kind"] == "PROVISIONAL"
    assert provisional["discount_cents"] == 0
    assert provisional["total_cents"] == 12990  # 12000 + tax(990), no discount

    # Cross the doctor to 5 delivered cases (tier 1 = 5%) before shipping the SUT.
    deliver_n_cases_for_doctor(doctor["id"], 1, material)
    assert get_success_data(api.get_doctor(doctor["id"], ADMIN))["completed_case_count"] == 5

    # Drive the SUT case to TRY_IN and accept it -> FINAL recomputed at tier 1.
    from test_helpers import create_machine, create_route, create_route_stop_payload
    from test_helpers.fixtures import (
        list_units, _schedule_and_mill_units, accept_case,
    )
    units = list_units(rest["id"])
    machine = create_machine()
    _schedule_and_mill_units(sut["id"], units, machine)
    get_success_data(api.ready_tryin(sut["id"], TECH))
    route = create_route()
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], sut["id"]), TEST_USERS["scheduler_headers"]))
    accept_case(sut, doctor["id"])

    final = get_invoice_for_case(sut["id"])
    assert final["kind"] == "FINAL"
    assert final["discount_cents"] == 600, "5% of 12000 = 600 on the final variant"
    assert final["total_cents"] == 12341, (
        f"final total must be 12341 (tier crossed to 5%) vs provisional 12990; "
        f"got {final['total_cents']}"
    )
    assert_invoice_total_identity(final)


def test_per_unit_round_half_up_single_unit(api):
    """PRD §3.3: "Each restoration's unit_price_cents is the material's
    base_unit_price_cents multiplied by a type complexity factor and then rounded
    half up to a whole number of cents." PRD §3.3: "a base of 9999 cents at factor
    1.25 across three units yields 37497 cents under the required per-unit-rounded
    order".

    Design: Difficulty/dual_variant_calc/pricing_per_unit_round_vs_sum_then_round
    """
    # base 9999 * BRIDGE 1.25 = 12498.75 -> round half up to 12499 (per unit).
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 1,
                            "requested_shade": "A1"}],
        material_overrides={"base_unit_price_cents": 9999,
                            "fabrication_process": "MILLED"},
    )
    rest = get_success_data(api.get_restoration(built["restorations"][0]["id"], ADMIN))
    assert rest["unit_price_cents"] == 12499
    invoice = get_invoice_for_case(built["case"]["id"])
    # single unit -> subtotal equals the per-unit price exactly.
    assert invoice["subtotal_cents"] == 12499


def test_round_once_order_explicitly_not_used(api):
    """PRD §3.3: "The alternative of summing unrounded products and rounding once
    at the end is explicitly not used and can diverge by up to a cent per line;
    for instance a base of 9999 cents at factor 1.25 across three units yields
    37497 cents under the required per-unit-rounded order versus 37496 cents under
    round-once."

    Design: Difficulty/combinatorial_formula/pricing_per_unit_round_order_pinned
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "BRIDGE", "unit_count": 3,
                            "requested_shade": "B2"}],
        material_overrides={"base_unit_price_cents": 9999,
                            "fabrication_process": "MILLED"},
    )
    invoice = get_invoice_for_case(built["case"]["id"])
    assert invoice["subtotal_cents"] == 37497
    assert invoice["subtotal_cents"] != 37496, (
        "round-once (sum 37496.25 then round) is explicitly not used"
    )


def test_invoice_chain_rush_and_tier_fields(api):
    """PRD §3.3: "The rush_surcharge_cents is the subtotal multiplied by 0.50 and
    rounded half up when the case is a rush, and 0 otherwise." PRD §3.3: "The
    discount_cents is that pre-discount base multiplied by the doctor's volume-tier
    percentage and rounded half up: a doctor with a completed_case_count of 0
    through 4 earns 0%, one with 5 through 19 earns 5%, and one with 20 or more
    earns 10%."

    Design: Difficulty/combinatorial_formula/invoice_total_nested_tier_rush_tax_chain
    """
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=15000, fabrication_process="MILLED")
    deliver_n_cases_for_doctor(doctor["id"], 20, material)
    case = get_success_data(api.create_case(
        create_case_payload(doctor["id"], intake_method="INTRAORAL_SCAN", is_rush=True), TECH))
    get_success_data(api.create_restoration(
        case["id"], create_restoration_payload(material["id"], restoration_type="BRIDGE",
                                                unit_count=3, requested_shade="A2"), TECH))
    get_success_data(api.submit_case(case["id"], TECH))
    invoice = get_invoice_for_case(case["id"])
    # discount applies to subtotal+rush = 84375 at the 10% tier.
    assert invoice["discount_cents"] == 8438
    assert_invoice_total_identity(invoice)


def test_final_invoice_discount_reflects_crossed_tier(api):
    """PRD §3.6: "The final variant re-reads the doctor's completed_case_count at
    ship time, which may have crossed into a higher discount tier between submit
    and ship, so the discount can differ from the provisional figure even on
    identical line items."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_tier_crossing
    """
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    deliver_n_cases_for_doctor(doctor["id"], 4, material)

    sut = get_success_data(api.create_case(
        create_case_payload(doctor["id"], intake_method="INTRAORAL_SCAN"), TECH))
    rest = get_success_data(api.create_restoration(
        sut["id"], create_restoration_payload(material["id"], restoration_type="CROWN",
                                               unit_count=1), TECH))
    get_success_data(api.submit_case(sut["id"], TECH))
    assert get_invoice_for_case(sut["id"])["discount_cents"] == 0  # tier 0 at submit

    deliver_n_cases_for_doctor(doctor["id"], 1, material)  # cross to 5 -> 5% tier

    from test_helpers import create_machine, create_route, create_route_stop_payload
    from test_helpers.fixtures import list_units, _schedule_and_mill_units, accept_case
    units = list_units(rest["id"])
    machine = create_machine()
    _schedule_and_mill_units(sut["id"], units, machine)
    get_success_data(api.ready_tryin(sut["id"], TECH))
    route = create_route()
    get_success_data(api.create_route_stop(
        create_route_stop_payload(route["id"], sut["id"]), TEST_USERS["scheduler_headers"]))
    accept_case(sut, doctor["id"])

    final = get_invoice_for_case(sut["id"])
    assert final["kind"] == "FINAL"
    assert final["discount_cents"] == 600, "the final discount must reflect the crossed 5% tier"
