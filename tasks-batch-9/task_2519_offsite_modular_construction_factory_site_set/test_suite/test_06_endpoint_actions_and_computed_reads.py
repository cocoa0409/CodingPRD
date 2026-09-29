"""Plant records, forecast observations, the logical clock and the money surfaces.

A plant is the one thing in this system with a full set of write-and-read
surfaces: it is registered with its takt geometry and shift window, read back
one row at a time, listed under a code filter, and re-postured through a narrow
line-state change. The other operations covered here look like reads or
book-keeping and are not: recording a site forecast quietly moves the crane
chart underneath a lift that was already planned, advancing the logical clock
expires a building permit that nobody touched, and the set-readiness view
recomputes a project's posture, phase and exposure clocks before it answers.
The financing and transport links close the file — a draw with no work behind
it cannot be certified, and a module may only join a load belonging to its own
project.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CRANE_CAPACITY_EXCEEDED,
    ERR_MODULE_NOT_FOUND,
    ERR_NO_CERTIFIABLE_WIP,
    ERR_SHIPMENT_PROJECT_MISMATCH,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_instant,
    assert_module_dimensions,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    AUTHORITY_HAVING_JURISDICTION,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    TRANSPORT_COORDINATOR,
    make_factory_manager_headers,
)


# ─── The plant record: register, read, list, re-posture ────────────────────────
SECOND_PLANT = {
    "name": "Columbia Modular Plant 2",
    "code": "PMP2",
    "takt_minutes": 120,
    "station_count": 4,
    "parallel_station_capacity": 1,
    "wip_unit_value_cents": 6000000,
}


def test_a_registered_plant_reads_back_the_takt_geometry_it_was_created_with(api):
    """PRD §3.1: "A `ProgramAdmin` registers a volumetric modular plant by supplying its display `name` and a short plant `code` that must be globally unique across all plants; a repeated code is rejected with `ERR_DUPLICATE_CODE`."
    PRD §3.1: "The plant's production geometry follows: `takt_minutes` is the base number of minutes a module occupies a single line station and must be at least 1; `station_count` is how many sequential stations the line has and must be at least 1; and `parallel_station_capacity` is how many modules may occupy the line concurrently, again at least 1."
    PRD §3.1: "A newly registered plant begins with `committed_line_minutes` at 0 and `version` at 1."

    Design: Corner/endpoints/factory_crud_create_read_list_and_line_state_update_round_trip
    """
    fx.set_clock(api)

    created = validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    read_back = validate_success(
        api.get_factory(created["id"], make_factory_manager_headers(created["id"]))
    )

    assert read_back["id"] == created["id"]
    assert read_back["code"] == "PMP1"
    assert read_back["takt_minutes"] == 90
    assert read_back["station_count"] == 6
    assert read_back["parallel_station_capacity"] == 2
    assert read_back["committed_line_minutes"] == 0
    assert_common_fields(read_back, expected_version=1)


def test_a_plant_may_declare_its_own_shift_window_and_starting_line_posture(api):
    """PRD §3.1: "`shift_start_minute_of_day` is the first minute of the production shift counted in UTC minutes past midnight, accepts any value from 0 through 1439, and defaults to 360 — six o'clock in the morning."
    PRD §3.1: "`shift_minutes_per_day` is how many productive minutes the shift makes available, accepts 1 through 1440, and defaults to 1080, which is an eighteen-hour working day."
    PRD §3.1: "`line_state` describes the line's posture, is one of `RUNNING`, `PAUSED` or `SHUTDOWN`, and defaults to `RUNNING`."

    Design: Corner/endpoints/factory_crud_create_read_list_and_line_state_update_round_trip
    """
    fx.set_clock(api)

    defaulted = validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    declared = validate_success(
        api.create_factory(
            f.factory_payload(
                **SECOND_PLANT,
                shift_start_minute_of_day=300,
                shift_minutes_per_day=600,
                line_state="PAUSED",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )

    assert defaulted["shift_start_minute_of_day"] == 360
    assert defaulted["shift_minutes_per_day"] == 1080
    assert defaulted["line_state"] == "RUNNING"
    assert declared["shift_start_minute_of_day"] == 300
    assert declared["shift_minutes_per_day"] == 600
    assert declared["line_state"] == "PAUSED"


def test_the_plant_code_filter_returns_only_the_plant_that_carries_it(api):
    """PRD §3.1: "Plants may be listed with the filters `code` and `line_state`."
    PRD §2.3: "For every list response the `meta` object carries `limit` (the effective page size actually applied), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before paging), and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/endpoints/factory_crud_create_read_list_and_line_state_update_round_trip
    """
    fx.set_clock(api)
    validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    second = validate_success(
        api.create_factory(f.factory_payload(**SECOND_PLANT), PROGRAM_ADMIN), 201
    )

    rows, meta = validate_paginated(
        api.list_factories({"code": "PMP2", "limit": 10, "offset": 0}, PROGRAM_ADMIN)
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [second["id"]]
    assert rows[0]["code"] == "PMP2"


def test_pausing_one_plant_leaves_the_other_plants_version_untouched(api):
    """PRD §3.1: "The plant's posture can be changed afterwards by either a `ProgramAdmin` or the plant's own `FactoryProductionManager`, who supply a replacement `line_state`. The change increments the plant's `version`."

    Design: Corner/endpoints/factory_crud_create_read_list_and_line_state_update_round_trip
    """
    fx.set_clock(api)
    first = validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    second = validate_success(
        api.create_factory(f.factory_payload(**SECOND_PLANT), PROGRAM_ADMIN), 201
    )
    assert first["version"] == 1

    paused = validate_success(
        api.update_factory_line_state(
            first["id"],
            f.line_state_payload("PAUSED"),
            make_factory_manager_headers(first["id"]),
        )
    )

    assert paused["line_state"] == "PAUSED"
    assert paused["version"] == 2
    untouched = validate_success(api.get_factory(second["id"], PROGRAM_ADMIN))
    assert untouched["version"] == 1
    assert untouched["line_state"] == "RUNNING"


# ─── The site forecast reaches forward into the lift ───────────────────────────
@pytest.fixture
def delivered_module_with_a_planned_lift(api):
    """A delivered module whose lift was planned in still air at exactly 85 percent.

    The 90 foot chart row carries 96,000 lb and the rigged weight is 81,600 lb,
    so the lift clears the gate by equality while the forecast reads 0 mph.
    """
    world = fx.world_delivered_module(api)
    fx.clear_the_site_for_setting(world)
    planned = fx.plan_pick(world, "M-01", pick_radius_ft=90, rigging_weight_lb=5000)
    assert_two_decimal_value(
        planned["crane_utilization_pct"], 85.00, "crane_utilization_pct"
    )
    return world


def test_a_recorded_observation_stores_both_forecast_numbers_on_the_project(
    delivered_module_with_a_planned_lift,
):
    """PRD §3.1: "The observation supplies `forecast_precip_probability_pct`, the latest precipitation probability from 0 through 100, and `forecast_wind_gust_mph`, the latest wind gust reading; both may also be seeded at project creation and both default to 0."
    PRD §3.1: "It may optionally supply `observed_at`, and the instant of the most recent observation is retained on the project as `last_weather_observed_at`, which is null until the first observation arrives. Recording an observation increments the project's `version`."

    Design: Corner/endpoints/weather_observation_action_re_derates_the_crane_at_execute_set
    """
    world = delivered_module_with_a_planned_lift
    before = world.refresh_project()
    assert before["last_weather_observed_at"] is None

    observed = validate_success(
        world.api.record_weather_observation(
            world.project_id,
            f.weather_payload(
                forecast_precip_probability_pct=35,
                forecast_wind_gust_mph=20,
                observed_at="2026-09-01T08:00:00Z",
            ),
            world.superintendent,
        )
    )

    assert observed["forecast_wind_gust_mph"] == 20
    assert observed["forecast_precip_probability_pct"] == 35
    assert_instant(
        observed["last_weather_observed_at"],
        "2026-09-01T08:00:00Z",
        "last_weather_observed_at",
    )
    assert observed["version"] == before["version"] + 1


def test_a_gust_recorded_after_the_lift_was_planned_stops_the_set(
    delivered_module_with_a_planned_lift,
):
    """PRD §3.1: "A gust of at least 20 miles per hour matters a great deal: from that reading onward, every crane feasibility evaluation in §3.7 works against a derated chart capacity rather than the published one."
    PRD §3.7: "Second, a wind derate may apply: when the project's `forecast_wind_gust_mph` is at least 20 miles per hour, the capacity is multiplied by 0.75 and truncated downwards to a whole pound, so the crane is treated as having only three quarters of its published capacity."
    PRD §3.7: "Crane feasibility is re-evaluated from scratch against the project's *current* `forecast_wind_gust_mph`, using the module's stored `pick_radius_ft`, so a lift that was feasible when it was planned in still air can fail here with `ERR_PICK_RADIUS_OFF_CHART` or `ERR_CRANE_CAPACITY_EXCEEDED` after a windy forecast arrives."

    Design: Corner/endpoints/weather_observation_action_re_derates_the_crane_at_execute_set
    """
    world = delivered_module_with_a_planned_lift
    validate_success(
        world.api.record_weather_observation(
            world.project_id,
            f.weather_payload(
                forecast_precip_probability_pct=35, forecast_wind_gust_mph=20
            ),
            world.superintendent,
        )
    )

    # 96,000 lb derates to 72,000 lb, and 8,160,000 exceeds 85 x 72,000.
    validate_error(
        world.api.execute_set(
            world.module_id(),
            {"set_note": "blocked by the gust derate"},
            world.superintendent,
        ),
        ERR_CRANE_CAPACITY_EXCEEDED,
    )

    assert_module_dimensions(world.refresh_module(), site_status="DELIVERED")
    assert world.refresh_project()["modules_set_count"] == 0


# ─── The logical clock expires a building permit nobody touched ────────────────
SET_PERMIT_EXPIRY = "2026-09-05T00:00:00Z"


@pytest.fixture
def dual_cleared_project_with_an_expiring_set_permit(api):
    """Both tracks delivered, but the local set permit expires on 5 September.

    State plan review and insignia are approved without an expiry, so only the
    local authority's set permit is on a clock.
    """
    world = fx.world_plan_review_approved(api)
    fx.approve_permit(api, world.project_id, "STATE_MODULAR_PROGRAM", "INSIGNIA")
    world.set_permit = fx.approve_permit(
        api, world.project_id, "LOCAL_AHJ", "SET", SET_PERMIT_EXPIRY
    )
    assert world.set_permit["status"] == "APPROVED"
    assert world.refresh_project()["permit_posture"] == "SET_CLEARED"
    return world


def test_an_approved_permit_expires_when_the_clock_reaches_its_expiry_instant(
    dual_cleared_project_with_an_expiring_set_permit,
):
    """PRD §2.10: "Every permit record in status `APPROVED` whose `expires_at` is not null and is less than or equal to the new instant transitions to `EXPIRED`, and every affected project's `permit_posture` is re-derived."
    PRD §3.3: "The second is clock-driven: when the logical clock is advanced to an instant at or beyond a non-null `expires_at`, an approval in `APPROVED` transitions to `EXPIRED`, which is terminal, the project's `permit_posture` is re-derived, and both records take `version` increments."

    Design: Corner/endpoints/clock_action_expires_an_approved_permit_and_re_derives_posture
    """
    world = dual_cleared_project_with_an_expiring_set_permit
    approved = world.set_permit

    fx.set_clock(world.api, SET_PERMIT_EXPIRY)

    expired = validate_success(
        world.api.get_permit(approved["id"], AUTHORITY_HAVING_JURISDICTION)
    )
    # The sweep is inclusive: expires_at equal to the new instant expires.
    assert expired["status"] == "EXPIRED"
    assert expired["version"] == approved["version"] + 1


def test_a_clock_advance_that_stops_short_of_the_expiry_leaves_the_permit_live(
    dual_cleared_project_with_an_expiring_set_permit,
):
    """PRD §2.10: "Every permit record in status `APPROVED` whose `expires_at` is not null and is less than or equal to the new instant transitions to `EXPIRED`, and every affected project's `permit_posture` is re-derived."
    PRD §3.3: "A track-and-scope pair counts as *live* when the project has a permit record with that `track` and that `scope` whose `status` is `APPROVED` and whose `expires_at` is either null or strictly later than the current clock instant."

    Design: Corner/endpoints/clock_action_expires_an_approved_permit_and_re_derives_posture
    """
    world = dual_cleared_project_with_an_expiring_set_permit

    fx.set_clock(world.api, "2026-09-04T23:59:00Z")

    still_live = validate_success(
        world.api.get_permit(world.set_permit["id"], AUTHORITY_HAVING_JURISDICTION)
    )
    assert still_live["status"] == "APPROVED"
    assert world.refresh_project()["permit_posture"] == "SET_CLEARED"


def test_the_posture_falls_back_to_the_state_track_when_the_set_permit_goes_dark(
    dual_cleared_project_with_an_expiring_set_permit,
):
    """PRD §3.3: "From those live pairs the derivation reads five facts — whether state plan review is live, whether state insignia is live, whether the local foundation permit is live, whether the local set permit is live, and whether local occupancy is live — plus one composite: the *site side* counts as cleared when either the local foundation permit or the local set permit is live."
    PRD §3.3: "Otherwise, if state plan review is live and the site side is not cleared, it is `STATE_CLEARED_ONLY`."

    Design: Corner/endpoints/clock_action_expires_an_approved_permit_and_re_derives_posture
    """
    world = dual_cleared_project_with_an_expiring_set_permit

    fx.set_clock(world.api, SET_PERMIT_EXPIRY)

    # Neither foundation nor set is live any more, so the site side goes dark
    # while the state track carries on.
    assert world.refresh_project()["permit_posture"] == "STATE_CLEARED_ONLY"


def test_an_approval_with_no_expiry_survives_the_clock_advance_with_its_pin(
    dual_cleared_project_with_an_expiring_set_permit,
):
    """PRD §3.3: "An `expires_at` of null means the approval, once granted, never expires."
    PRD §3.3: "On success, an approval whose `scope` is `PLAN_REVIEW` sets `pinned_package_id` to the `id` of the project's single frozen design package."

    Design: Corner/endpoints/clock_action_expires_an_approved_permit_and_re_derives_posture
    """
    world = dual_cleared_project_with_an_expiring_set_permit

    fx.set_clock(world.api, SET_PERMIT_EXPIRY)

    plan_review = validate_success(
        world.api.get_permit(world.plan_review_permit["id"], PROGRAM_ADMIN)
    )
    assert plan_review["status"] == "APPROVED"
    assert plan_review["expires_at"] is None
    assert plan_review["pinned_package_id"] == world.package_id


# ─── The set-readiness view recomputes before it answers ───────────────────────
@pytest.fixture
def one_module_standing_open_for_four_and_a_half_hours(api):
    """One module landed at 08:00 with the clock then pushed on to 12:30.

    Nothing else happens in between, so only a recomputation can show the
    exposure clock having moved.
    """
    world = fx.world_set_module(api)
    fx.set_clock(world.api, "2026-09-01T12:30:00Z")
    return world


def test_the_readiness_view_reports_the_cleared_posture_and_the_setting_phase(
    one_module_standing_open_for_four_and_a_half_hours,
):
    """PRD §3.1: "A heavier computed read — the set-readiness view, available to `ProgramAdmin`, `SiteSuperintendent` and `AuthorityHavingJurisdiction` — re-derives `permit_posture` and `phase`, refreshes the exposure clock on every module of the project, and refreshes the set counters before returning the project row; it is the view the field uses before deciding whether a lift may proceed."
    PRD §3.7: "Otherwise, if any module of the project has `site_status` `SET` or `CONNECTED`, `phase` is `SETTING`."
    PRD §2.9: "Two counters on `Project` — `modules_set_count` and `modules_connected_count` — are maintained as counts of the project's modules whose `site_status` is `SET` or `CONNECTED`, and whose `site_status` is `CONNECTED`, respectively."

    Design: Corner/endpoints/set_readiness_computed_read_refreshes_posture_phase_and_exposure
    """
    world = one_module_standing_open_for_four_and_a_half_hours

    readiness = validate_success(
        world.api.get_set_readiness(world.project_id, world.superintendent)
    )

    assert readiness["id"] == world.project_id
    assert readiness["permit_posture"] == "SET_CLEARED"
    assert readiness["phase"] == "SETTING"
    assert readiness["modules_set_count"] == 1
    assert readiness["modules_connected_count"] == 0


def test_the_readiness_view_shows_the_exposure_clock_aged_by_a_bare_clock_advance(
    one_module_standing_open_for_four_and_a_half_hours,
):
    """PRD §3.7: "While the module's `site_status` is `SET` and its `connected_at` is still null, `exposure_open_hours` is the difference between the current logical clock instant and `set_at`, taken in whole minutes, divided by 60, and rounded half up to two decimal places."
    PRD §3.7: "Because the elapsed time is measured against the logical clock, exposure only ages when an administrator advances the clock."
    PRD §3.4: "Reading one module returns all three status dimensions together with its line slot, its pick window and its work-in-progress value, and refreshes `exposure_open_hours` against the current clock as it does so."

    Design: Corner/endpoints/set_readiness_computed_read_refreshes_posture_phase_and_exposure
    """
    world = one_module_standing_open_for_four_and_a_half_hours

    validate_success(world.api.get_set_readiness(world.project_id, world.superintendent))

    module = validate_success(world.api.get_module(world.module_id(), world.superintendent))
    assert_module_dimensions(module, site_status="SET")
    assert_instant(module["set_at"], "2026-09-01T08:00:00Z", "set_at")
    # 270 whole minutes divided by 60 is 4.5 hours exactly.
    assert_two_decimal_value(module["exposure_open_hours"], 4.50, "exposure_open_hours")
    assert module["connected_at"] is None


def test_the_readiness_read_leaves_the_project_version_where_it_was(
    one_module_standing_open_for_four_and_a_half_hours,
):
    """PRD §2.4: "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, including mutations the caller did not request directly."
    PRD §3.1: "A heavier computed read — the set-readiness view, available to `ProgramAdmin`, `SiteSuperintendent` and `AuthorityHavingJurisdiction` — re-derives `permit_posture` and `phase`, refreshes the exposure clock on every module of the project, and refreshes the set counters before returning the project row; it is the view the field uses before deciding whether a lift may proceed."

    Design: Corner/endpoints/set_readiness_computed_read_refreshes_posture_phase_and_exposure
    """
    world = one_module_standing_open_for_four_and_a_half_hours
    before = world.refresh_project()["version"]

    readiness = validate_success(
        world.api.get_set_readiness(world.project_id, world.superintendent)
    )

    assert readiness["version"] == before
    assert world.refresh_project()["version"] == before


# ─── A draw with nothing behind it cannot be certified ─────────────────────────
@pytest.fixture
def draft_deposit_draw_with_nothing_on_the_line(api):
    """A first work-in-progress draw raised while the module is still PLANNED."""
    world = fx.world_with_module(api)
    world.draw = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    return world


def test_a_deposit_draw_raised_before_the_line_starts_carries_a_zero_basis(
    draft_deposit_draw_with_nothing_on_the_line,
):
    """PRD §3.9: "Under `WIP_DEPOSIT`, the basis is every module of the project whose `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` and whose `qc_status` is not `HOLD`; each such module contributes its station-progress earned value as defined in §3.4 — the plant's `wip_unit_value_cents` pro-rated by completed stations — and a module that has never left the plant contributes normally."
    PRD §3.9: "`basis_module_count` is the number of modules in the basis and `basis_earned_cents` is the sum of those already-rounded per-module terms."
    PRD §3.9: "A new draw is persisted with `status` `DRAFT`, `certified_at`, `funded_at` and `reject_reason` null, and `version` 1."

    Design: Corner/endpoints/certify_conditional_action_requires_a_non_zero_basis
    """
    world = draft_deposit_draw_with_nothing_on_the_line
    draw = world.draw

    # The only module of the project is still PLANNED, so it never qualifies.
    assert draw["basis_module_count"] == 0
    assert_cents(draw["basis_earned_cents"], 0, "basis_earned_cents")
    assert_cents(draw["requested_cents"], 0, "requested_cents")
    assert draw["status"] == "DRAFT"
    assert draw["certified_at"] is None
    assert_common_fields(draw, expected_version=1)


def test_certifying_a_draw_with_no_qualifying_work_is_refused(
    draft_deposit_draw_with_nothing_on_the_line,
):
    """PRD §3.9: "The **substance test** second: `certified_basis_cents` must be strictly greater than 0, because a draw with no qualifying module work cannot be certified; a zero basis is `ERR_NO_CERTIFIABLE_WIP`."
    PRD §3.9: "A successful certification moves `status` from `DRAFT` to `CERTIFIED`, stamps `certified_at` with the current clock instant, adds `certified_cents` to the project's `wip_certified_cents`, and increments both the draw's and the project's `version`."

    Design: Corner/endpoints/certify_conditional_action_requires_a_non_zero_basis
    """
    world = draft_deposit_draw_with_nothing_on_the_line

    validate_error(
        world.api.certify_draw(
            world.draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_NO_CERTIFIABLE_WIP,
    )

    refused = validate_success(
        world.api.get_draw_request(world.draw["id"], LENDER_DRAW_ADMINISTRATOR)
    )
    assert refused["status"] == "DRAFT"
    assert refused["certified_at"] is None
    assert_cents(
        world.refresh_project()["wip_certified_cents"], 0, "wip_certified_cents"
    )


def test_the_refused_draw_certifies_once_a_station_has_actually_been_earned(
    draft_deposit_draw_with_nothing_on_the_line,
):
    """PRD §3.9: "The whole basis computation is then **re-run from live module state and never copied** from the provisional figures."
    PRD §3.9: "`certified_cents` is `certified_basis_cents` multiplied by the project's `deposit_pct` and rounded half up to a whole cent under `WIP_DEPOSIT`, and is equal to `certified_basis_cents` under `MILESTONE_SET`."
    PRD §3.9: "`retainage_held_cents` is `certified_cents` multiplied by the project's `retainage_pct` — 5 percent by default — rounded half up to a whole cent."

    Design: Corner/endpoints/certify_conditional_action_requires_a_non_zero_basis
    """
    world = draft_deposit_draw_with_nothing_on_the_line
    validate_error(
        world.api.certify_draw(
            world.draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_NO_CERTIFIABLE_WIP,
    )
    fx.schedule_slot(world, "M-01")
    fx.advance_stations(world, "M-01", 1)

    certified = validate_success(
        world.api.certify_draw(
            world.draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        )
    )

    # One station of six against an 8,750,000 cent unit value is 1,458,333 cents.
    assert certified["status"] == "CERTIFIED"
    assert_cents(certified["certified_basis_cents"], 1458333, "certified_basis_cents")
    assert_cents(certified["certified_cents"], 291667, "certified_cents")
    assert_cents(certified["retainage_held_cents"], 14583, "retainage_held_cents")
    assert_instant(certified["certified_at"], "2026-09-01T08:00:00Z", "certified_at")


# ─── Loading a module links two independently created aggregates ───────────────
@pytest.fixture
def two_projects_one_released_module(api):
    """A released module of Rainier Flats, and a load belonging to Cascade Commons.

    Both projects run out of the same plant, so nothing but the project link
    distinguishes the two loads.
    """
    world = fx.world_qc_released_module(api)
    world.other_project = fx.create_project(
        api,
        world.factory_id,
        name="Cascade Commons",
        ahj_code="TAC",
        planned_module_count=2,
        contract_price_cents=1600000000,
    )
    world.other_shipment = fx.create_shipment(
        api, world.other_project["id"], carrier_code="SOUNDX"
    )
    world.shipment = fx.create_shipment(api, world.project_id)
    return world


def test_a_module_offered_to_another_projects_load_is_refused(
    two_projects_one_released_module,
):
    """PRD §3.6: "The module's `project_id` must equal the shipment's `project_id`, or the attempt is `ERR_SHIPMENT_PROJECT_MISMATCH`."
    PRD §3.6: "A new load begins with `status` `DRAFT`, `route_survey_state` `NOT_REQUIRED`, `max_envelope_class` `STANDARD`, `loaded_module_count` 0, `permit_fee_cents` 0, `escort_required` false, `escort_confirmed` false, `survey_completed_at`, `permit_expires_at`, `dispatched_at`, `delivered_at` and `cancel_reason` all null, and `version` 1."

    Design: Corner/endpoints/load_module_link_requires_both_rows_and_matching_projects
    """
    world = two_projects_one_released_module
    foreign_load = world.other_shipment

    validate_error(
        world.api.load_module(
            foreign_load["id"],
            f.load_module_payload(world.module_id(), foreign_load["version"]),
            TRANSPORT_COORDINATOR,
        ),
        ERR_SHIPMENT_PROJECT_MISMATCH,
    )

    untouched = validate_success(
        world.api.get_shipment(foreign_load["id"], TRANSPORT_COORDINATOR)
    )
    assert untouched["loaded_module_count"] == 0
    assert untouched["version"] == foreign_load["version"]
    assert world.refresh_module()["shipment_id"] is None


def test_a_load_offered_a_module_that_does_not_exist_reports_a_missing_module(
    two_projects_one_released_module,
):
    """PRD §2.5: "Foreign keys arriving in a request body are resolved next, after every path identifier has been confirmed, using the same catalogue of 404 codes."
    PRD §2.6: "Existence of every foreign key in the request body, reporting the matching `*_NOT_FOUND` code. Applies to the creation of projects, design packages, modules, permits, inspections, shipments, defect claims and draw requests, and to loading a module onto a shipment."

    Design: Corner/endpoints/load_module_link_requires_both_rows_and_matching_projects
    """
    world = two_projects_one_released_module

    validate_error(
        world.api.load_module(
            world.shipment_id,
            f.load_module_payload(NON_EXISTENT_UUID, world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        ),
        ERR_MODULE_NOT_FOUND,
    )

    assert world.refresh_shipment()["loaded_module_count"] == 0


def test_the_matching_link_is_visible_from_the_load_and_from_the_module(
    two_projects_one_released_module,
):
    """PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."
    PRD §3.4: "Modules may be listed filtered by `project_id`, `design_package_id`, `shipment_id`, `production_status`, `qc_status`, `site_status` or `envelope_class`."

    Design: Corner/endpoints/load_module_link_requires_both_rows_and_matching_projects
    """
    world = two_projects_one_released_module
    load = world.shipment

    loaded = validate_success(
        world.api.load_module(
            load["id"],
            f.load_module_payload(world.module_id(), load["version"]),
            TRANSPORT_COORDINATOR,
        )
    )

    assert loaded["loaded_module_count"] == 1
    assert loaded["version"] == load["version"] + 1
    module = world.refresh_module()
    assert module["shipment_id"] == load["id"]
    assert_module_dimensions(module, site_status="LOADED")
    rows, meta = validate_paginated(
        world.api.list_modules({"shipment_id": load["id"]}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [world.module_id()]
