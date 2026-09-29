"""Calculation site_feasibility_assessment (PRD 3.4)."""

import constants as C
from services.numbers import D


def pad_admits(site, size_class):
    dims = C.UNIT_DIMS[size_class]
    required_length = D(dims["length_ft"]) + 2 * C.PAD_CLEARANCE_FT
    required_width = D(dims["width_ft"]) + 2 * C.PAD_CLEARANCE_FT
    return (
        D(site["pad_length_ft"]) >= required_length
        and D(site["pad_width_ft"]) >= required_width
    )


def fire_access_ok(site, school):
    return (
        D(site["distance_to_fire_lane_ft"]) <= C.FIRE_ACCESS_MAX_DISTANCE_FT
        and D(school["fire_lane_clear_width_ft"]) >= C.FIRE_LANE_MIN_CLEAR_WIDTH_FT
    )


def assess(site, school, size_class):
    """Three ordered steps; stops at the first hard failure."""
    # step 1 - geometry
    if not pad_admits(site, size_class):
        return {
            "feasibility_status": "INFEASIBLE",
            "infeasible_reason": "PAD_TOO_SMALL",
            "mitigation_flags": [],
            "assessed_for_size_class": size_class,
        }
    # step 2 - fire access (inclusive on the passing side)
    if not fire_access_ok(site, school):
        return {
            "feasibility_status": "INFEASIBLE",
            "infeasible_reason": "FIRE_ACCESS",
            "mitigation_flags": [],
            "assessed_for_size_class": size_class,
        }
    # step 3 - mitigations in fixed order
    dims = C.UNIT_DIMS[size_class]
    flags = []
    if D(site["electrical_drop_available_kw"]) < D(dims["service_kw"]):
        flags.append("ELECTRICAL_UPGRADE")
    if dims["needs_sewer"] and not site["sewer_connection_available"]:
        flags.append("SEWER_HOOKUP")
    if not site["ada_path_of_travel_compliant"]:
        flags.append("ADA_PATH_UPGRADE")
    return {
        "feasibility_status": "FEASIBLE" if not flags else "FEASIBLE_WITH_MITIGATION",
        "infeasible_reason": None,
        "mitigation_flags": flags,
        "assessed_for_size_class": size_class,
    }
