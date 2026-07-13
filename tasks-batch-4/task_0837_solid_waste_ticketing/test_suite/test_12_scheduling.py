"""Scale-reservation half-open interval semantics and posture gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_gate_operator_headers, scale_reservation_payload,
    create_facility, create_gas_reading,
)

OP = "op1"


def _reserve(api, facility_id, lane, truck, start, end):
    return api.create_scale_reservation(
        facility_id, scale_reservation_payload(lane, truck, start, end),
        make_gate_operator_headers(OP),
    )


def test_overlapping_reservation_same_lane_rejected(api):
    """PRD §3.8: "A reservation is rejected with `ERR_LANE_OCCUPIED` if its window overlaps
    another `RESERVED` window on the same facility and the same `lane_number`, and is rejected
    with `ERR_FACILITY_CLOSED` if the facility's posture is `CLOSED`."

    Design: Difficulty/resource_temporal_overlap/scale_reservation_lane_halfopen_overlap
    """
    facility = create_facility(1000)
    validate_success(_reserve(api, facility["id"], 1, "T-1",
                              "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"), 201)
    resp = _reserve(api, facility["id"], 1, "T-2",
                    "2026-03-02T10:30:00Z", "2026-03-02T11:30:00Z")
    validate_error(resp, ApiErrorId.ERR_LANE_OCCUPIED)


def test_overlapping_window_on_different_lane_allowed(api):
    """PRD §3.8: "A reservation is rejected with `ERR_LANE_OCCUPIED` if its window overlaps
    another `RESERVED` window on the same facility and the same `lane_number`, and is rejected
    with `ERR_FACILITY_CLOSED` if the facility's posture is `CLOSED`."

    Design: Difficulty/resource_temporal_overlap/scale_reservation_lane_halfopen_overlap
    """
    facility = create_facility(1000)
    validate_success(_reserve(api, facility["id"], 1, "T-1",
                              "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"), 201)
    resp = _reserve(api, facility["id"], 2, "T-2",
                    "2026-03-02T10:30:00Z", "2026-03-02T11:30:00Z")
    data = validate_success(resp, 201)
    assert data["status"] == "RESERVED"


def test_adjacent_touching_reservation_allowed(api):
    """PRD §3.8: "The reserved window is treated as a half-open interval — inclusive of
    `window_start` and exclusive of `window_end` — so two reservations that merely abut (one
    ending exactly when the next begins) do not conflict."

    Design: Corner/cross_cutting/adjacent_scale_reservation_touching_allowed
    """
    facility = create_facility(500)
    validate_success(_reserve(api, facility["id"], 1, "T-1",
                              "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"), 201)
    resp = _reserve(api, facility["id"], 1, "T-2",
                    "2026-03-02T11:00:00Z", "2026-03-02T12:00:00Z")
    data = validate_success(resp, 201)
    assert data["status"] == "RESERVED"


def test_scale_reservation_rejected_when_facility_closed_by_gas(api):
    """PRD §3.8: "A reservation is rejected with `ERR_LANE_OCCUPIED` if its window overlaps
    another `RESERVED` window on the same facility and the same `lane_number`, and is rejected
    with `ERR_FACILITY_CLOSED` if the facility's posture is `CLOSED`."
    PRD §2.9: "if `gas_status` is `EXCEEDANCE`, the posture is `CLOSED`".

    Design: Corner/consistency_model/facility_closed_via_gas_restricts_scale_reservation
    """
    facility = create_facility(500)
    create_gas_reading(facility["id"], 500, "2026-03-01T12:00:00Z")
    resp = _reserve(api, facility["id"], 1, "T-9",
                    "2026-03-04T10:00:00Z", "2026-03-04T11:00:00Z")
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)
