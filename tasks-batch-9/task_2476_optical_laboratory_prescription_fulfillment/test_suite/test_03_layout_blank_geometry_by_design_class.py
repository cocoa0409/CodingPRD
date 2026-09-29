"""One trace, two optical classes, two different blank requirements."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.test_users import MANAGER_A_HEADERS, OPTICIAN_A_HEADERS

TRACE = {"a_mm": 52.0, "b_mm": 32.0, "ed_mm": 55.0, "dbl_mm": 18.0}
ORDER_MEASUREMENTS = {
    "frame_sku": "FRM-A22",
    "frame_retail_cents": 21995,
    "requested_coatings": ["HARDCOAT"],
    "monocular_pd_od_mm": 31.0,
    "monocular_pd_os_mm": 30.0,
    "fitting_height_mm": 22.0,
    "expedite_requested": False,
}


def _two_orders_sharing_one_trace(api):
    """Two orders whose only material difference is the design's optical class."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    plan = fixtures.create_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    progressive = fixtures.create_progressive_design(api)
    single_vision = fixtures.create_sv_design(
        api,
        allowed_coatings=["AR_PREMIUM", "HARDCOAT"],
        stock_sku_available=False,
    )

    multifocal = validate_success(
        api.create_prescription(
            f.create_multifocal_prescription_payload(patient["id"], prescriber["id"]),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.verify_prescription(
            multifocal["id"],
            f.create_verification_payload(verification_note="multifocal Rx verified"),
            OPTICIAN_A_HEADERS,
        )
    )
    distance_only = validate_success(
        api.create_prescription(
            f.create_prescription_payload(
                patient["id"],
                prescriber["id"],
                sphere_od=-3.0,
                cylinder_od=-1.25,
                axis_od=90,
                sphere_os=-2.75,
                cylinder_os=-1.0,
                axis_os=85,
                pd_distance_mm=61.0,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.verify_prescription(
            distance_only["id"],
            f.create_verification_payload(
                verification_note="distance-only Rx verified"
            ),
            OPTICIAN_A_HEADERS,
        )
    )

    progressive_order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                patient["id"],
                multifocal["id"],
                progressive["id"],
                **ORDER_MEASUREMENTS,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    single_vision_order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                patient["id"],
                distance_only["id"],
                single_vision["id"],
                **ORDER_MEASUREMENTS,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    return progressive_order, single_vision_order


def _trace(api, order):
    return validate_success(
        api.create_frame_layout(
            f.create_frame_layout_payload(order["id"], order["version"], **TRACE),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )


def test_both_optical_classes_record_the_same_decentration_figures(api):
    """The three decentrations are pure frame-and-PD geometry, class-independent.

    PRD 3.4: "The vertical decentration, `decentration_v_mm`, is the absolute
    difference between `effective_fitting_height_mm` and half of `b_mm`, and it is
    a single figure shared by both eyes."

    Design: Difficulty/combinatorial_formula/layout_blank_diameter_branches_nonlinearly_on_design_type
    """
    progressive_order, single_vision_order = _two_orders_sharing_one_trace(api)

    progressive_layout = _trace(api, progressive_order)
    single_vision_layout = _trace(api, single_vision_order)

    # Frame PD is 52.0 + 18.0, so half of it is 35.0 for both layouts.
    for layout in (progressive_layout, single_vision_layout):
        assert layout["decentration_h_od_mm"] == 4.0
        assert layout["decentration_h_os_mm"] == 5.0
        assert layout["decentration_v_mm"] == 6.0
        assert layout["layout_status"] == "COMPUTED"


def test_progressive_class_adds_the_fitting_cross_allowance_to_the_greater_decentration(
    api,
):
    """max(5.0, 6.0) plus 4.0 doubled onto a 55.0 ed and 2.0 chuck gives 77.0.

    PRD 3.4: "For a `PROGRESSIVE` design it is the greater of that eye's horizontal
    decentration and the shared vertical decentration, plus a fitting-cross
    allowance of 4.0 millimetres."

    Design: Difficulty/combinatorial_formula/layout_blank_diameter_branches_nonlinearly_on_design_type
    """
    progressive_order, _ = _two_orders_sharing_one_trace(api)

    layout = _trace(api, progressive_order)

    assert layout["required_blank_diameter_mm"] == 77.0


def test_single_vision_class_ignores_the_vertical_decentration_entirely(api):
    """The identical trace needs only 67.0 mm once the fitting height drops out.

    PRD 3.4: "For a `SINGLE_VISION` design the total decentration for an eye is its
    horizontal decentration alone — which is why a single-vision layout is
    completely insensitive to fitting height."

    Design: Difficulty/combinatorial_formula/layout_blank_diameter_branches_nonlinearly_on_design_type
    """
    progressive_order, single_vision_order = _two_orders_sharing_one_trace(api)

    progressive_layout = _trace(api, progressive_order)
    single_vision_layout = _trace(api, single_vision_order)

    assert single_vision_layout["required_blank_diameter_mm"] == 67.0
    assert progressive_layout["required_blank_diameter_mm"] == 77.0
    assert (
        progressive_layout["required_blank_diameter_mm"]
        - single_vision_layout["required_blank_diameter_mm"]
        == 10.0
    )
