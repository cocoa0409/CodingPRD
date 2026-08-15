"""The logical clock: startup default and PlatformAdmin-driven advancement."""
from test_helpers import (
    create_active_area,
    get_area,
    validate_success,
)


def test_logical_clock_default_and_set(api, cra_officer_headers, platform_admin_headers):
    """PRD §2.5: "At server startup, before any adjustment, the logical clock
    reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to
    wall-clock time."
    PRD §2.5: "A platform-admin-only capability advances the logical clock to a
    supplied `to_iso8601` instant; the response echoes the new value as
    `current_utc`."
    PRD §3.1: "Retiring moves an `ACTIVE` area to `RETIRED`, stamping
    `effective_end_date` with the logical-clock date as the exclusive end of its
    window".

    Design: Corner/cross_cutting_complexity_layers/logical_clock_default_and_set
    """
    area_a = create_active_area(
        area_code="AA-CC4A", census_tracts=["T1"], annual_cd_budget_cents=100000,
    )
    area_b = create_active_area(
        area_code="AA-CC4B", msa_code="12060", state_code="GA",
        census_tracts=["T2"], annual_cd_budget_cents=100000,
    )

    # Clock untouched: the retirement stamps the startup default date.
    retired_a = validate_success(
        api.retire_assessment_area(area_a["id"], cra_officer_headers)
    )
    assert retired_a["effective_end_date"] == "2026-08-01"

    echoed = validate_success(
        api.set_clock("2026-12-15T00:00:00Z", platform_admin_headers)
    )
    assert echoed["current_utc"] == "2026-12-15T00:00:00Z"

    retired_b = validate_success(
        api.retire_assessment_area(area_b["id"], cra_officer_headers)
    )
    assert retired_b["effective_end_date"] == "2026-12-15"
    assert get_area(area_b["id"])["effective_end_date"] == "2026-12-15"
