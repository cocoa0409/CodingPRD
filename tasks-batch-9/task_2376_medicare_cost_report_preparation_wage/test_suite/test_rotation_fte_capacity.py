"""The resident daily FTE cap over half-open rotation intervals."""

from test_helpers import (
    ApiErrorId,
    assert_fte_equals,
    assert_rotation_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import rotation_assignment_payload
from test_helpers.fixtures import (
    create_rotation,
    read_cost_report,
    setup_resident_with_rotation,
)


def test_a_rotation_starting_on_another_end_date_is_accepted(api):
    """Adjacency is not overlap: a rotation beginning exactly where the standing
    one ends shares no day and is admitted at 15.5000 FTE days.

    PRD 3.6: "The resident's aggregate `fte_fraction` across all `ACTIVE` assignments must not exceed 1.0000 on any single day of the half-open interval `[start_date, end_date)` — a resident cannot be more than fully deployed — and a violation is rejected with `ERR_RESIDENT_DAILY_FTE_EXCEEDED`; note that adjacency is not overlap, so an assignment whose `end_date` equals another's `start_date` contributes nothing on that shared date."

    Design: Difficulty/resource_temporal_overlap/resident_daily_fte_capacity_over_half_open_rotation_intervals
    """
    scenario = setup_resident_with_rotation(api)
    first = scenario["base_rotation"]
    assert first["end_date"] == "2026-01-01"

    adjacent = create_rotation(
        api,
        scenario,
        start_date="2026-01-01",
        end_date="2026-02-01",
        fte_fraction=0.5000,
    )

    assert_rotation_assignment(adjacent)
    assert adjacent["start_date"] == first["end_date"]
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["overlap_days"] == 31
    assert_fte_equals(adjacent["fte_days"], 15.5000, "adjacent fte_days")

    reread_first = validate_success(
        api.get_rotation_assignment(first["id"], scenario["analyst"])
    )
    assert reread_first["overlap_days"] == 184
    assert_fte_equals(reread_first["fte_days"], 110.4000, "first fte_days")


def test_sharing_interior_days_exceeds_the_daily_capacity(api):
    """A rotation overlapping 31 interior days at 0.5000 would put the resident at
    1.1000 on those days, so it is refused and nothing is stored.

    PRD 3.6: "Per resident, `assigned_fte_days` is the sum of `fte_days` over that resident's `ACTIVE` assignments, and the resident's own FTE figure is `assigned_fte_days` divided by the period day count, rounded half up to four decimal places, then capped at 1.0000 — no resident counts as more than one full-time equivalent in a period, whatever the arithmetic says."

    Design: Difficulty/resource_temporal_overlap/resident_daily_fte_capacity_over_half_open_rotation_intervals
    """
    scenario = setup_resident_with_rotation(api)
    create_rotation(
        api,
        scenario,
        start_date="2026-01-01",
        end_date="2026-02-01",
        fte_fraction=0.5000,
    )

    response = api.create_rotation_assignment(
        scenario["resident_id"],
        rotation_assignment_payload(
            scenario["cc_routine"],
            start_date="2025-12-01",
            end_date="2026-01-01",
            fte_fraction=0.5000,
        ),
        scenario["analyst"],
    )

    validate_error(response, ApiErrorId.ERR_RESIDENT_DAILY_FTE_EXCEEDED.value, 409)

    rotations, meta = validate_paginated(
        api.list_rotation_assignments(
            scenario["analyst"], {"resident_id": scenario["resident_id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rotations) == 2

    resident = validate_success(
        api.get_resident(scenario["resident_id"], scenario["analyst"])
    )
    assert_fte_equals(resident["assigned_fte_days"], 125.9000, "assigned_fte_days")

    report = read_cost_report(api, scenario)
    assert_fte_equals(
        report["unweighted_fte_days_total"], 125.9000, "unweighted_fte_days_total"
    )
    assert report["unweighted_fte_total"] == 0.34
