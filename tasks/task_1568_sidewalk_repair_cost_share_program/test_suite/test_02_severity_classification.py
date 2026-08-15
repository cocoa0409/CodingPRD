"""Defect severity classification: threshold boundaries and per-type rules."""
from test_helpers import TEST_USERS, make_owner, make_parcel, make_segment, \
    validate_success

COORD = TEST_USERS["coordinator_headers"]
INSP1 = TEST_USERS["inspector_headers"]


def _segment_for_classification():
    owner = make_owner("Pam Palm", "16 Palm St")
    parcel = make_parcel(owner["id"], "P-1400", "16 Palm St", "LOCAL")
    return make_segment(parcel["id"], "S-1400-1", length_ft=100)


def _vertical(api, segment_id, offset):
    return validate_success(api.create_defect(
        {"segment_id": segment_id, "defect_type": "VERTICAL_SEPARATION",
         "measured_offset_inches": offset, "area_sqft": 2}, INSP1), 201)


class TestTripThresholdBoundary:
    def test_upper_boundary_half_inch(self, api):
        """PRD §3.2: "For `VERTICAL_SEPARATION` and `TREE_ROOT_UPHEAVAL`, an
        offset of at least half an inch (0.50) is a `TRIP_HAZARD`, an offset of
        at least a quarter inch (0.25) but less than half an inch is `MAJOR`,
        and anything below a quarter inch is `MINOR`."

        Design: Difficulty/boundary_precision_check/severity_trip_threshold_boundary
        """
        segment = _segment_for_classification()
        assert _vertical(api, segment["id"], 0.5)["severity_class"] == \
            "TRIP_HAZARD", "0.50 hits the inclusive >= boundary"
        assert _vertical(api, segment["id"], 0.49)["severity_class"] == \
            "MAJOR", "0.49 falls just below the trip threshold"

    def test_lower_boundary_quarter_inch(self, api):
        """PRD §3.2: "For `VERTICAL_SEPARATION` and `TREE_ROOT_UPHEAVAL`, an
        offset of at least half an inch (0.50) is a `TRIP_HAZARD`, an offset of
        at least a quarter inch (0.25) but less than half an inch is `MAJOR`,
        and anything below a quarter inch is `MINOR`."

        Design: Difficulty/boundary_precision_check/severity_trip_threshold_boundary
        """
        segment = _segment_for_classification()
        assert _vertical(api, segment["id"], 0.25)["severity_class"] == \
            "MAJOR", "0.25 hits the lower inclusive boundary"
        assert _vertical(api, segment["id"], 0.24)["severity_class"] == \
            "MINOR", "0.24 falls just below the major threshold"


class TestNonVerticalTypeThresholds:
    def test_non_vertical_classification_rows(self, api):
        """PRD §3.2: "A `HORIZONTAL_OPENING` of at least half an inch is
        `MAJOR`, otherwise `MINOR`. `SETTLEMENT` covering at least 9 square feet
        is `MAJOR`, otherwise `MINOR`. `SPALLING` and `CRUMBLED_JOINT` covering
        at least 16 square feet are `MAJOR`, otherwise `MINOR`."
        PRD §3.8: "`OPEN` is the initial state only for non-forestry defects"

        Design: Corner/calculations/severity_classification_non_vertical_types
        """
        segment = _segment_for_classification()
        sid = segment["id"]

        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "HORIZONTAL_OPENING",
             "measured_offset_inches": 0.5, "area_sqft": 2}, INSP1), 201)
        assert sev["severity_class"] == "MAJOR"
        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "HORIZONTAL_OPENING",
             "measured_offset_inches": 0.49, "area_sqft": 2}, INSP1), 201)
        assert sev["severity_class"] == "MINOR"

        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "SETTLEMENT", "area_sqft": 9},
            INSP1), 201)
        assert sev["severity_class"] == "MAJOR"
        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "SETTLEMENT", "area_sqft": 8},
            INSP1), 201)
        assert sev["severity_class"] == "MINOR"

        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "SPALLING", "area_sqft": 16},
            INSP1), 201)
        assert sev["severity_class"] == "MAJOR"
        sev = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "CRUMBLED_JOINT",
             "area_sqft": 15}, INSP1), 201)
        assert sev["severity_class"] == "MINOR"

        tru = validate_success(api.create_defect(
            {"segment_id": sid, "defect_type": "TREE_ROOT_UPHEAVAL",
             "measured_offset_inches": 0.4, "area_sqft": 10}, INSP1), 201)
        assert tru["severity_class"] == "MAJOR"
        assert tru["status"] == "OPEN", \
            "no city tree -> no AWAITING_FORESTRY routing"
