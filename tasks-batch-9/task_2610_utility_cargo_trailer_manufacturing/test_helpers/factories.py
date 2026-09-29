"""Request-payload builders.

Every builder returns a fresh dict carrying the fields PRD section 3 says
the endpoint requires, and accepts `**overrides` so a test can vary exactly
the one field it is exercising.
"""

from . import constants as K


def _merge(base, overrides):
    payload = dict(base)
    payload.update(overrides)
    return payload


# --- PRD 3.1 trailer models ---------------------------------------------
def model_payload(**overrides):
    return _merge(K.MODEL_TA, overrides)


def sa_heavy_model_payload(**overrides):
    return _merge(K.MODEL_SA_HEAVY, overrides)


def sa_light_model_payload(**overrides):
    return _merge(K.MODEL_SA_LIGHT, overrides)


def sc_model_payload(**overrides):
    return _merge(K.MODEL_SC, overrides)


def submission_payload(**overrides):
    return _merge({"engineering_note": "initial GVWR package"}, overrides)


def decision_payload(decision="CERTIFIED", **overrides):
    return _merge({"decision": decision, "decision_note": "capacities verified"}, overrides)


# --- PRD 3.8 dealers -----------------------------------------------------
def dealer_payload(**overrides):
    return _merge(K.DEALER_001, overrides)


def dealer_two_payload(**overrides):
    return _merge(K.DEALER_002, overrides)


def adjustment_payload(adjustment_type, amount_cents=0, **overrides):
    return _merge(
        {
            "adjustment_type": adjustment_type,
            "amount_cents": amount_cents,
            "note": "floor plan administration",
        },
        overrides,
    )


# --- PRD 3.2 and 3.6 plant assets ---------------------------------------
def jig_payload(**overrides):
    return _merge(K.JIG_TA, overrides)


def sa_jig_payload(**overrides):
    return _merge(K.JIG_SA, overrides)


def sc_jig_payload(**overrides):
    return _merge(K.JIG_SC, overrides)


def lane_payload(**overrides):
    return _merge(K.LANE_01, overrides)


# --- PRD 3.2 build records and reservations -----------------------------
def unit_payload(model_id, serial_number="SN-000101", **overrides):
    return _merge(
        {
            "serial_number": serial_number,
            "model_id": model_id,
            "planned_start_date": "2026-08-03T07:00:00Z",
        },
        overrides,
    )


def reservation_payload(unit_id, expected_weld_jig_version, window=None, **overrides):
    window = window or K.JIG_WINDOW_1
    return _merge(
        {
            "unit_id": unit_id,
            "window_start_at": window[0],
            "window_end_at": window[1],
            "expected_weld_jig_version": expected_weld_jig_version,
        },
        overrides,
    )


# --- PRD 3.3 frame inspections ------------------------------------------
def inspection_payload(**overrides):
    """A dead-on TA-7X14 reading: zero deviation, zero squareness, no defects."""
    return _merge(
        {
            "measured_length_mm": K.TA_NOMINAL_LENGTH_MM,
            "measured_width_mm": K.TA_NOMINAL_WIDTH_MM,
            "diagonal_a_mm": K.TA_DIAGONAL_MM,
            "diagonal_b_mm": K.TA_DIAGONAL_MM,
            "critical_weld_defect_count": 0,
            "non_critical_weld_defect_count": 0,
        },
        overrides,
    )


def sa_inspection_payload(**overrides):
    return _merge(
        {
            "measured_length_mm": K.SA_NOMINAL_LENGTH_MM,
            "measured_width_mm": K.SA_NOMINAL_WIDTH_MM,
            "diagonal_a_mm": K.SA_DIAGONAL_MM,
            "diagonal_b_mm": K.SA_DIAGONAL_MM,
            "critical_weld_defect_count": 0,
            "non_critical_weld_defect_count": 0,
        },
        overrides,
    )


# --- PRD 3.4 systems stages ---------------------------------------------
def lighting_payload(**overrides):
    """Satisfies all four lamp conditions for a narrow-body trailer."""
    return _merge(
        {
            "stage": "LIGHTING",
            "stop_tail_turn_lamp_count": 2,
            "clearance_lamp_count": 0,
            "side_marker_lamp_count": 2,
            "license_plate_lamp_count": 1,
            "reflex_reflector_count": 4,
        },
        overrides,
    )


def brake_payload(installed_braked_axle_count=1, breakaway_kit_installed=True, **overrides):
    return _merge(
        {
            "stage": "BRAKE_AND_AXLE",
            "installed_braked_axle_count": installed_braked_axle_count,
            "breakaway_kit_installed": breakaway_kit_installed,
        },
        overrides,
    )


# --- PRD 3.5 option installs --------------------------------------------
def option_payload(
    option_code="E_TRACK_KIT",
    quantity=1,
    unit_weight_lbs=20,
    unit_price_cents=6650,
    labor_hours=0.5,
    **overrides
):
    return _merge(
        {
            "option_code": option_code,
            "quantity": quantity,
            "unit_weight_lbs": unit_weight_lbs,
            "unit_price_cents": unit_price_cents,
            "labor_hours": labor_hours,
        },
        overrides,
    )


def signoff_payload(**overrides):
    return _merge({"signoff_note": "install complete"}, overrides)


def removal_payload(**overrides):
    return _merge({"removal_reason": "customer changed the order"}, overrides)


# --- PRD 3.6 road tests --------------------------------------------------
def road_test_payload(lane_id, window=None, protocol_code="STANDARD_20MI", **overrides):
    window = window or K.LANE_WINDOW_1
    return _merge(
        {
            "lane_id": lane_id,
            "window_start_at": window[0],
            "window_end_at": window[1],
            "protocol_code": protocol_code,
        },
        overrides,
    )


def road_test_result_payload(
    brake_stop_distance_ft=32.5, lighting_check_passed=True, **overrides
):
    return _merge(
        {
            "brake_stop_distance_ft": brake_stop_distance_ft,
            "lighting_check_passed": lighting_check_passed,
            "result_notes": "brake and lamp walkaround recorded",
        },
        overrides,
    )


# --- PRD 3.7 certification labels ---------------------------------------
def label_payload(**overrides):
    return _merge({"tire_size_code": "ST205/75R15"}, overrides)


# --- PRD 3.8 dealer orders ----------------------------------------------
def order_payload(dealer_id, model_id, po_ref="PO-10001", stocking_program="STOCK", **overrides):
    return _merge(
        {
            "dealer_id": dealer_id,
            "model_id": model_id,
            "po_ref": po_ref,
            "stocking_program": stocking_program,
        },
        overrides,
    )


def allocation_payload(expected_dealer_version, **overrides):
    return _merge({"expected_dealer_version": expected_dealer_version}, overrides)


def cancellation_payload(**overrides):
    return _merge({"cancellation_reason": "dealer withdrew the purchase order"}, overrides)


def delivery_payload(**overrides):
    return _merge({"delivery_note": "trailer picked up by the dealer"}, overrides)


# --- PRD 3.9 warranty claims --------------------------------------------
def claim_payload(unit_id, dealer_id, **overrides):
    return _merge(
        {
            "claim_ref": K.CLAIM_REF_1,
            "unit_id": unit_id,
            "dealer_id": dealer_id,
            "complaint_code": "BRAKE",
            "labor_hours": K.CLAIM_LABOR_HOURS,
            "part_lines": [dict(line) for line in K.CLAIM_PART_LINES],
            "failure_date": K.CLAIM_FAILURE_DATE_IN_WARRANTY,
        },
        overrides,
    )


def review_payload(decision="APPROVE", **overrides):
    return _merge({"decision": decision, "review_note": "adjudicated"}, overrides)


def resubmission_payload(**overrides):
    return _merge({"response_note": "photographs attached"}, overrides)


def shipment_payload(tracking_number="TRK-0001", **overrides):
    return _merge({"tracking_number": tracking_number}, overrides)
