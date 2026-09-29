"""Two derivations that read the camp's own configuration: the four applicability gates
frozen onto every evaluation at pin time, and the five-component required staffing level."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import find_by
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    CampType,
    CompliancePosture,
    HealthStaffingLevel,
    PopulationServed,
    ProgramElement,
    StandardDomain,
    StateLicenseStatus,
)
from prd_bench_local_runner.testing import validate_paginated

GATE_STANDARDS = [
    {
        "code": "G1",
        "title": "Applies to every camp",
        "domain": StandardDomain.SUPERVISION,
        "mandatory": True,
        "scoring_weight": 1,
    },
    {
        "code": "G2",
        "title": "Day camps only",
        "domain": StandardDomain.OPERATIONS,
        "mandatory": False,
        "scoring_weight": 1,
        "applies_to_camp_types": [CampType.DAY],
    },
    {
        "code": "G3",
        "title": "Open water only",
        "domain": StandardDomain.AQUATICS,
        "mandatory": False,
        "scoring_weight": 1,
        "requires_program_elements_any": [ProgramElement.AQUATICS_OPEN_WATER],
    },
    {
        "code": "G4",
        "title": "Any aquatics element",
        "domain": StandardDomain.AQUATICS,
        "mandatory": False,
        "scoring_weight": 1,
        "requires_program_elements_any": [
            ProgramElement.AQUATICS_POOL,
            ProgramElement.AQUATICS_OPEN_WATER,
        ],
    },
    {
        "code": "G5",
        "title": "Medically fragile populations",
        "domain": StandardDomain.HEALTH_WELLNESS,
        "mandatory": False,
        "scoring_weight": 1,
        "applies_to_populations": [PopulationServed.MEDICALLY_FRAGILE],
    },
    {
        "code": "G6",
        "title": "State licensed camps only",
        "domain": StandardDomain.OPERATIONS,
        "mandatory": False,
        "scoring_weight": 1,
        "requires_state_licensed": True,
    },
]


def _two_camps_sharing_one_gated_edition(api):
    """A licensed RESIDENT pool camp and an unlicensed DAY camp pin the same edition."""
    resident = fx.register_camp(
        api,
        name="Gate Camp Resident",
        camp_type=CampType.RESIDENT,
        program_elements=[ProgramElement.AQUATICS_POOL],
        health_staffing_level=HealthStaffingLevel.RN_ONSITE,
    )
    fx.move_state_license(api, resident["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-20001")
    day = fx.register_camp(api, name="Gate Camp Day")

    edition, standards = fx.publish_edition_with_standards(
        api, "ACA-2026-GATE", GATE_STANDARDS
    )
    resident_cycle = fx.open_cycle(api, resident["id"], edition["id"])
    day_cycle = fx.open_cycle(api, day["id"], edition["id"])
    return {
        "resident": resident,
        "day": day,
        "standards": standards,
        "resident_cycle": resident_cycle,
        "day_cycle": day_cycle,
    }


def _rows_for(api, cycle_id):
    rows, meta = validate_paginated(
        api.list_evaluations({"cycle_id": cycle_id, "limit": 100}, OFFICER_ONE_HEADERS)
    )
    return rows, meta


def _applicable_codes(api, cycle_id, standards):
    """The codes of the rows the cycle marked applicable, read through the filter."""
    rows, _meta = validate_paginated(
        api.list_evaluations(
            {"cycle_id": cycle_id, "applicable": True, "limit": 100}, OFFICER_ONE_HEADERS
        )
    )
    by_id = {standard["id"]: code for code, standard in standards.items()}
    return sorted(by_id[row["standard_id"]] for row in rows)


def test_the_four_gates_are_independent_and_the_any_of_gate_intersects(api):
    """PRD §3.3: "Opening the cycle materialises exactly one standard evaluation row for
    every standard belonging to the pinned edition, regardless of the order in which those
    standards were created."

    Design: Corner/calculations/standard_applicability_gates_are_independent_and_the_verdict_is_frozen_at_pin_time
    """
    world = _two_camps_sharing_one_gated_edition(api)
    standards = world["standards"]

    for cycle_id in (world["resident_cycle"]["id"], world["day_cycle"]["id"]):
        rows, meta = _rows_for(api, cycle_id)
        # Inapplicable rows are persisted with applicable false, not skipped.
        assert meta["total_count"] == 6
        assert len(rows) == 6

    assert _applicable_codes(api, world["resident_cycle"]["id"], standards) == [
        "G1",
        "G4",
        "G6",
    ]
    assert world["resident_cycle"]["applicable_standard_count"] == 3
    assert world["resident_cycle"]["applicable_mandatory_count"] == 1

    assert _applicable_codes(api, world["day_cycle"]["id"], standards) == ["G1", "G2"]
    assert world["day_cycle"]["applicable_standard_count"] == 2
    assert world["day_cycle"]["applicable_mandatory_count"] == 1

    rows, _meta = _rows_for(api, world["resident_cycle"]["id"])
    for code, standard in standards.items():
        row = find_by(rows, standard_id=standard["id"])
        assert row["mandatory"] is (code == "G1")
        assert row["scoring_weight"] == 1


def test_a_later_licence_never_reopens_a_frozen_applicability_verdict(api):
    """PRD §3.3: "Neither copy nor the applicability verdict is ever recomputed — a camp that
    later adds a programme element, gains a state licence or edits its census does not change
    the shape of an open cycle."

    Design: Corner/calculations/standard_applicability_gates_are_independent_and_the_verdict_is_frozen_at_pin_time
    """
    world = _two_camps_sharing_one_gated_edition(api)
    standards = world["standards"]
    day_cycle_id = world["day_cycle"]["id"]
    assert _applicable_codes(api, day_cycle_id, standards) == ["G1", "G2"]

    licensed = fx.move_state_license(
        api, world["day"]["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-20002"
    )
    assert licensed["state_license_status"] == StateLicenseStatus.ACTIVE

    # G6's licensure gate was decided at pin time and is not re-derived on read.
    assert _applicable_codes(api, day_cycle_id, standards) == ["G1", "G2"]
    rows, _meta = _rows_for(api, day_cycle_id)
    assert find_by(rows, standard_id=standards["G6"]["id"])["applicable"] is False
    assert fx.read_cycle(api, day_cycle_id)["applicable_standard_count"] == 2


def test_the_census_and_distance_breaks_promote_on_the_lower_edge_of_each_tier(api):
    """PRD §3.1: "The census component is 1 when `resident_census` is 50 or fewer, 2 when it
    is more than 50 but 120 or fewer, and 3 above 120. The distance component is 3 when
    `distance_to_hospital_km` is 40 or more, 2 when it is at least 20 but below 40, and 1
    below 20."

    Design: Corner/calculations/required_health_staffing_level_walks_the_census_and_distance_break_boundaries
    """
    breaks = {
        "A": {"resident_census": 50, "distance_to_hospital_km": 19.5},
        "B": {"resident_census": 51, "distance_to_hospital_km": 19.5},
        "C": {"resident_census": 120, "distance_to_hospital_km": 20},
        "D": {"resident_census": 121, "distance_to_hospital_km": 40},
        "E": {
            "resident_census": 121,
            "distance_to_hospital_km": 40,
            "program_elements": [ProgramElement.AQUATICS_OPEN_WATER],
        },
    }
    camps = {
        key: fx.register_camp(
            api, name=f"Break Camp {key}", health_staffing_level=None, **payload
        )
        for key, payload in breaks.items()
    }

    # Components [1,1,1,1,1]: nothing crosses a break, so the requirement stays at rank 1.
    assert camps["A"]["required_health_staffing_level"] == HealthStaffingLevel.FIRST_AIDER_ONLY
    # Census 51 crosses the first census break on its own; one component at 2 earns no bump.
    assert camps["B"]["required_health_staffing_level"] == HealthStaffingLevel.LPN_ONSITE
    # Census exactly 120 stays at 2 and distance exactly 20 reaches 2: still only two.
    assert camps["C"]["required_health_staffing_level"] == HealthStaffingLevel.LPN_ONSITE
    # Census 121 and distance 40 both reach rank 3, and two components is short of the bump.
    assert camps["D"]["required_health_staffing_level"] == HealthStaffingLevel.RN_ONSITE
    # The open-water programme is the third component at 2 or more: min(4, 3 + 1).
    assert camps["E"]["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE

    for camp in camps.values():
        assert camp["health_staffing_level"] == HealthStaffingLevel.NONE
        assert camp["compliance_posture"] == CompliancePosture.RESTRICTED
