"""WIM screening bypass / pull-in sort: weight boundary and carrier-status gating.

Difficulty (depth) translations for the gross-weight boundary and the cross-entity
carrier-OOS gate, plus the corner bypass-clearance claim.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_domain,
    create_screening,
    create_inspection,
    add_violation,
    finalize,
    api_client,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
SCREENER = TEST_USERS["screener_headers"]


def _get_carrier(carrier_id):
    return validate_success(api_client.get_carrier(carrier_id, ADMIN))


def test_legal_weight_screening_bypasses_and_clears(api):
    """PRD §3.3: "If none of these holds, the screening bypasses — `decision` `BYPASS`,
    `status` `CLEARED`, `referral_reason` `NONE` — which additionally requires that the
    carrier be `ACTIVE` and its `certified_iss_score` be below the station's threshold
    (both already implied by the pull-in conditions)."

    Design: Corner/state_machines/screening_bypass_immediately_cleared
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-C4", "legal_name": "Corner Four"},
                     station_overrides={"name": "S4", "state_code": "OR"})
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-C4", gross_weight_lbs=79000,
                                 heaviest_axle_lbs=19000)
    assert screening["decision"] == "BYPASS"
    assert screening["status"] == "CLEARED"
    assert screening["referral_reason"] == "NONE"


def test_gross_weight_exactly_at_limit_is_legal(api):
    """PRD §3.3: "The computed `overweight` flag is set to true when the screening's
    `gross_weight_lbs` is strictly greater than the station's `gross_weight_limit_lbs`,
    or its `heaviest_axle_lbs` is strictly greater than the station's
    `single_axle_limit_lbs`; a vehicle exactly at either limit is legal."

    Design: Difficulty/boundary_precision_check/gross_weight_strict_over_limit
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-844-K", "legal_name": "Kilo Cartage"},
                     station_overrides={"name": "I-25", "state_code": "NM"})
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-11", gross_weight_lbs=80000,
                                 heaviest_axle_lbs=19000)
    assert screening["overweight"] is False
    assert screening["status"] == "CLEARED"


def test_gross_weight_one_pound_over_limit_is_overweight(api):
    """PRD §3.3: "The computed `overweight` flag is set to true when the screening's
    `gross_weight_lbs` is strictly greater than the station's `gross_weight_limit_lbs`,
    or its `heaviest_axle_lbs` is strictly greater than the station's
    `single_axle_limit_lbs`; a vehicle exactly at either limit is legal."
    PRD §3.3: "The screening is pulled in — `decision` `PULL_IN`, `status` `REFERRED` —
    when any one of the following holds: the carrier's `status` is not `ACTIVE`; the
    carrier's `certified_iss_score` is at least the station's `iss_bypass_threshold`;
    the screening is overweight; the `oversize` flag is set; `credentials_valid` is
    false; or the vehicle is `hazmat_placarded`."

    Design: Difficulty/boundary_precision_check/gross_weight_strict_over_limit
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-844-K2", "legal_name": "Kilo Cartage"},
                     station_overrides={"name": "I-25", "state_code": "NM"})
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-11", gross_weight_lbs=80001,
                                 heaviest_axle_lbs=19000)
    assert screening["overweight"] is True
    assert screening["status"] == "REFERRED"


def _drive_carrier_to_oos_ordered(usdot, name, station_name, state):
    """Finalize an inspection with two OOS violations summing 20 severity points, so the
    carrier crosses OOS_ORDER_THRESHOLD (20) and moves to OOS_ORDERED. Returns dict."""
    d = setup_domain(carrier_overrides={"usdot_number": usdot, "legal_name": name},
                     station_overrides={"name": station_name, "state_code": state})
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-13", gross_weight_lbs=86000,
                                 heaviest_axle_lbs=21000)
    inspection = create_inspection(screening["id"], d["bay"]["id"])
    add_violation(inspection["id"], code="393.75", category="WEIGHT", severity_weight=10, oos=True)
    add_violation(inspection["id"], code="393.9", category="VEHICLE", severity_weight=10, oos=True)
    finalize(inspection["id"], "OOS")
    return d


def test_oos_ordered_carrier_reaches_federal_out_of_service(api):
    """PRD §2.7: "When `oos_points` reaches at least `20`, a carrier (whether `ACTIVE`
    or `UNDER_REVIEW`) moves to `OOS_ORDERED`."

    Design: Difficulty/cross_entity_state_dependency/screening_decision_gated_by_carrier_oos
    """
    d = _drive_carrier_to_oos_ordered("DOT-844-M", "Mike Freight", "I-95", "VA")
    carrier = _get_carrier(d["carrier"]["id"])
    assert carrier["status"] == "OOS_ORDERED"
    assert carrier["oos_points"] == 20


def test_oos_ordered_carrier_cannot_bypass_even_when_legal(api):
    """PRD §3.3: "A bypassed screening records `referral_reason` `NONE`. A screening's
    `status` lives in `SCREENED` conceptually at the instant of computation and resolves
    immediately to `CLEARED` on bypass or `REFERRED` on pull-in; a referred screening
    later becomes `INSPECTED` when its inspection is finalized, and both `CLEARED` and
    `INSPECTED` are terminal."
    PRD §3.3: "`PRISM_TARGET` if the carrier's `status` is not `ACTIVE` or its
    `certified_iss_score` is at least the threshold; otherwise `OVERWEIGHT` if
    overweight; otherwise `OVERSIZE` if the `oversize` flag is set; otherwise
    `CREDENTIAL` if `credentials_valid` is false; otherwise `HAZMAT` if
    `hazmat_placarded`."

    Design: Difficulty/cross_entity_state_dependency/screening_decision_gated_by_carrier_oos
    """
    d = _drive_carrier_to_oos_ordered("DOT-844-M2", "Mike Freight", "I-95", "VA")
    # A legal-weight, non-hazmat screening that would otherwise bypass:
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-13", gross_weight_lbs=79000,
                                 heaviest_axle_lbs=19000)
    assert screening["decision"] == "PULL_IN"
    assert screening["status"] == "REFERRED"
    assert screening["referral_reason"] == "PRISM_TARGET"
