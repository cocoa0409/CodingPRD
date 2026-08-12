"""Resource creation, defaults, required fields, and listing (PRD §2.3, §2.4, §3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_batch_intake,
    assert_season,
    collect_confirmed_run,
    create_crew_member_payload,
    create_filling_batch,
    create_sap_run_payload,
    create_season_payload,
    create_sugarbush_payload,
    draw_from_run,
    make_fieldcrew_headers,
    setup_live_operation,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_season_create_initial_state(api, manager_headers):
    """PRD §3.1: "A new season begins in `PLANNED`, with `taps_live`,
    `total_sap_gallons`, and `total_syrup_gallons` all zeroed."

    Design: Corner/entities/season_create_initial_state
    """
    res = api.create_season(create_season_payload(), manager_headers)
    created = validate_success(res, 201)
    assert_season(created)
    assert created["status"] == "PLANNED"
    assert created["taps_live"] == 0
    assert created["total_sap_gallons"] == 0
    assert created["total_syrup_gallons"] == 0
    assert isinstance(created["version"], int)

    fetched = validate_success(api.get_season(created["id"], manager_headers), 200)
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "PLANNED"


def test_crew_cert_default_false(api, manager_headers):
    """PRD §3.5: "A **CrewMember** is hired per season: creation takes the
    `season_id`, a `name`, a `crew_role` of `TAPPER`, `BOILER`, or `GRADER`,
    and an optional `cert_organic_handler` flag (default false). A new hire
    begins in `HIRED`."

    Design: Corner/entities/crew_cert_default_false
    """
    season = validate_success(
        api.create_season(create_season_payload(), manager_headers), 201)
    payload = create_crew_member_payload(season["id"], name="Tammy Tapper",
                                         crew_role="TAPPER")
    assert "cert_organic_handler" not in payload
    crew = validate_success(api.create_crew_member(payload, manager_headers), 201)
    assert crew["cert_organic_handler"] is False
    assert crew["status"] == "HIRED"


def test_season_missing_year_rejected(api, manager_headers):
    """PRD §3.1: "A manager creates one with a `year` (for example 2027), an
    `opens_on` and `closes_on` calendar date bounding the production window,
    and a `planned_taps` count that must be greater than zero."
    PRD §2.7: "11. **Malformed input** — missing, unknown, or malformed fields;
    enum and range violations; conditional requiredness; `term_end` not after
    `term_start`; `closes_at` not after `opens_at` (`ERR_VALIDATION`)."

    Design: Corner/entities/season_missing_year_rejected
    """
    payload = create_season_payload()
    del payload["year"]
    res = api.create_season(payload, manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_sugarbush_get_not_found(api, manager_headers):
    """PRD §2.7: "3. **Existence** — a path id or body foreign-key reference
    (`season_id`, `sugarbush_id`, `weather_window_id`, `collected_by`,
    `boiled_by`, `syrup_lot_id`, `sap_run_id`, `evaluator_id`) does not
    resolve; ids are validated left to right (`ERR_NOT_FOUND`)."

    Design: Corner/entities/sugarbush_get_not_found
    """
    res = api.get_sugarbush(NON_EXISTENT_UUID, manager_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_computed_field_in_create_rejected(api, manager_headers):
    """PRD §3.2: "Creating one takes the `season_id`, a `name`, and a
    `tap_capacity` (greater than zero)" — `taps_set` is not a create input but
    a derived counter (PRD §2.8).
    PRD §2.7: "11. **Malformed input** — missing, unknown, or malformed fields;
    enum and range violations; conditional requiredness; `term_end` not after
    `term_start`; `closes_at` not after `opens_at` (`ERR_VALIDATION`)."

    Design: Corner/entities/computed_field_in_create_rejected
    """
    season = validate_success(
        api.create_season(create_season_payload(), manager_headers), 201)
    payload = create_sugarbush_payload(season["id"])
    payload["taps_set"] = 999
    res = api.create_sugarbush(payload, manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)

    data, meta = validate_paginated(api.list_sugarbushes(manager_headers))
    assert all(b.get("taps_set") != 999 for b in data)


def test_crew_invalid_enum_rejected(api, manager_headers):
    """PRD §3.5: "a `crew_role` of `TAPPER`, `BOILER`, or `GRADER`"
    PRD §2.7: "11. **Malformed input** — missing, unknown, or malformed fields;
    enum and range violations; conditional requiredness; `term_end` not after
    `term_start`; `closes_at` not after `opens_at` (`ERR_VALIDATION`)."

    Design: Corner/entities/crew_invalid_enum_rejected
    """
    season = validate_success(
        api.create_season(create_season_payload(), manager_headers), 201)
    payload = create_crew_member_payload(season["id"], name="Bad Role",
                                         crew_role="MANAGER")
    res = api.create_crew_member(payload, manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_batch_intake_immutable_shape(api, manager_headers):
    """PRD §2.4: "`VacuumReading`, `BatchIntake`, and `FlavorEvaluation` are
    append-only fact records and carry only `id` and `created_at`; both
    `updated_at` and `version` are absent on these three."
    PRD §3.6: "Each intake decrements the run's `gallons_remaining` by
    `gallons_drawn`, increments the batch's `sap_gallons_in` by the same
    amount, and is stamped with a per-batch monotone `draw_sequence` assigned
    at creation."

    Design: Corner/entities/batch_intake_immutable_shape
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 50.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    intake = draw_from_run(ctx, batch["id"], run["id"], 50.0)
    assert_batch_intake(intake)
    assert intake["gallons_drawn"] == pytest.approx(50.0, abs=0.004)

    rows, meta = validate_paginated(api.list_batch_intakes(batch["id"], manager_headers))
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == intake["id"]
    assert "version" not in row, "append-only intake must not expose version"
    assert "updated_at" not in row, "append-only intake must not expose updated_at"
    assert isinstance(row["draw_sequence"], int)
    assert row["gallons_drawn"] == pytest.approx(50.0, abs=0.004)


def test_sap_run_list_pagination(api, manager_headers):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, must be at least 1, and may not exceed 100.
    `offset` defaults to 0. Every list response returns rows ordered by
    `created_at` ascending (stable chronological order). The `meta` block of a
    list response includes the four pagination fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/sap_run_list_pagination
    """
    ctx = setup_live_operation()
    headers = make_fieldcrew_headers(ctx["tapper"]["id"])
    for gallons in (10.0, 20.0):
        res = api.create_sap_run(
            create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                                   ctx["tapper"]["id"], gallons_collected=gallons),
            headers)
        validate_success(res, 201)

    page1, meta1 = validate_paginated(
        api.list_sap_runs(manager_headers, params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_sap_runs(manager_headers, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]
