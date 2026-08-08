"""Advancement at the chair: the three side-effect branches, the two rungs, plateau."""

from test_helpers import (
    ApiErrorId,
    approx_mm,
    assert_calendar_date,
    assert_is_null,
    assert_protrusive_conservation,
    assert_titration_visit,
    build_scenario,
    read_appliance_version,
    schedule_and_apply_visit,
    schedule_visit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_titration_request_is_bounded_at_the_per_visit_ceiling(api):
    """PRD §3.6: "The requested advancement is first bounded at the per-visit ceiling of 1.00 mm,
    so a request for 1.50 mm becomes a bounded 1.00 mm."
    PRD §3.6: "On success, `applied_increment_mm` is set to the bounded value, `applied_on` is
    stamped from the clock date, `days_since_prior_applied` records the whole days from the prior
    applied or reduced visit's `applied_on` to this one (null for the first such visit on the
    device), and the appliance's `current_advancement_mm` and `applied_visit_count` are
    recomputed."

    Design: Difficulty/combinatorial_formula/titration_increment_nested_min_with_side_effect_branch
    """
    scenario = build_scenario("delivered")
    _created, applied = schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-01", requested_increment_mm=2.00
    )
    assert_titration_visit(applied)
    assert applied["applied_increment_mm"] == approx_mm(1.00), (
        "a 2.00 mm request advances the device by exactly the 1.00 mm per-visit ceiling"
    )
    assert applied["status"] == "APPLIED"
    assert_is_null(applied["days_since_prior_applied"], "TitrationVisit.days_since_prior_applied")


def test_first_applied_visit_moves_the_device_into_titration(api):
    """PRD §3.6: "The first visit ever to resolve to `APPLIED` or `REDUCED` also moves the device
    `DELIVERED → IN_TITRATION`."
    PRD §3.5: "A custom device on a measured range of 8.00 mm therefore starts at 4.75 mm (0.60
    of 8.00 is 4.80; 4.80 divided by 0.25 is 19.2; rounded to 19 grains; 19 times 0.25 is 4.75),
    while a prefabricated device on the identical records starts at 4.00 mm (the smaller of 4.00
    and half of 8.00 is 4.00, which is already 16 whole grains)."

    Design: Difficulty/combinatorial_formula/titration_increment_nested_min_with_side_effect_branch
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-01", requested_increment_mm=2.00
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["starting_advancement_mm"] == approx_mm(4.75)
    assert appliance["current_advancement_mm"] == approx_mm(5.75)
    assert appliance["applied_visit_count"] == 1
    assert appliance["lifecycle_status"] == "IN_TITRATION"


def test_moderate_side_effects_hold_the_visit_without_advancing(api):
    """PRD §3.6: "When the report is `MODERATE`, the visit resolves to `HELD` — a deferral, not
    an advancement. `applied_increment_mm` is set to 0.00 and, crucially, `applied_on` **stays
    null**, so a held visit never starts the titration interval clock and the next visit is
    measured from whatever applied or reduced visit came before."
    PRD §3.6: "`scheduled_for` is pushed forward by 14 days, and `applied_visit_count` is
    **not** incremented — a held visit does not count toward the plateau requirement."

    Design: Difficulty/non_linear_state_machine/titration_visit_held_self_loop_then_applied
    """
    scenario = build_scenario("delivered")
    visit = schedule_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    held = validate_success(
        api.apply_titration_visit(
            visit["id"], {"side_effect_severity": "MODERATE"}, scenario["dent_headers"]
        )
    )
    assert held["status"] == "HELD"
    assert held["applied_increment_mm"] == approx_mm(0.00)
    assert_is_null(held["applied_on"], "TitrationVisit.applied_on")

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(4.75)
    assert appliance["applied_visit_count"] == 0


def test_held_visit_holds_again_and_only_then_applies(api):
    """PRD §3.6: "A held visit may be applied again later, and if the symptoms persist it simply
    holds again: the same visit moves `HELD → HELD`, pushing `scheduled_for` forward by a further
    14 days each time, indefinitely, without ever consuming protrusive range."
    PRD §3.6: "From `HELD` the other two answers behave exactly as they do from `SCHEDULED`:
    `NONE` or `MILD` resolves it to `APPLIED` under both guarding rungs, and `SEVERE` resolves it
    to `REDUCED`."

    Design: Difficulty/non_linear_state_machine/titration_visit_held_self_loop_then_applied
    """
    scenario = build_scenario("delivered")
    visit = schedule_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    first_hold = validate_success(
        api.apply_titration_visit(
            visit["id"], {"side_effect_severity": "MODERATE"}, scenario["dent_headers"]
        )
    )
    second_hold = validate_success(
        api.apply_titration_visit(
            visit["id"], {"side_effect_severity": "MODERATE"}, scenario["dent_headers"]
        )
    )
    resolved = validate_success(
        api.apply_titration_visit(
            visit["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        )
    )
    assert first_hold["status"] == "HELD"
    assert first_hold["applied_increment_mm"] == approx_mm(0.00)
    assert second_hold["status"] == "HELD"
    assert resolved["status"] == "APPLIED"
    assert resolved["applied_increment_mm"] == approx_mm(1.00)

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(5.75)
    assert appliance["applied_visit_count"] == 1
    assert appliance["lifecycle_status"] == "IN_TITRATION"


def test_held_leg_moves_no_millimetres_at_all(api):
    """PRD §2.10: "An appliance's `current_advancement_mm` always equals its
    `starting_advancement_mm` plus the sum of `applied_increment_mm` over exactly those
    `TitrationVisit` rows on that appliance whose `status` is `APPLIED` or `REDUCED`; and it
    always lies between 0.00 and the appliance's `max_protrusive_mm` inclusive."
    PRD §2.10: "Visits in `SCHEDULED`, `HELD`, `SUPERSEDED` or `VOIDED_BY_HOLD` contribute
    exactly 0.00. A visit that is held and later applied must leave the sum untouched by its held
    leg alone."

    Design: Difficulty/compensating_invariant/advancement_conservation_across_held_and_reduced
    """
    scenario = build_scenario("delivered")
    _created, first = schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00
    )
    assert first["status"] == "APPLIED"

    second = schedule_visit(scenario, scheduled_for="2026-06-02", requested_increment_mm=1.00)
    held = validate_success(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "MODERATE"}, scenario["dent_headers"]
        )
    )
    assert held["status"] == "HELD"
    assert held["applied_increment_mm"] == approx_mm(0.00)

    midway = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert midway["current_advancement_mm"] == approx_mm(5.75), (
        "the held leg moved nothing"
    )


def test_severe_side_effects_back_the_device_off_and_conserve_the_range(api):
    """PRD §3.6: "When the report is `SEVERE`, the visit resolves to `REDUCED` — the device is
    backed off. `applied_increment_mm` is set to the negative of the smaller of 0.50 mm and the
    appliance's current `current_advancement_mm`, which floors the result so that advancement can
    never drop below 0.00: a device at 4.75 mm falls to 4.25 mm, while a device at only 0.25 mm
    falls to 0.00 and no further."
    PRD §3.6: "`applied_on` is stamped and the visit counts toward `applied_visit_count` exactly
    as an applied visit does."
    PRD §3.6: "From `HELD` the other two answers behave exactly as they do from `SCHEDULED`:
    `NONE` or `MILD` resolves it to `APPLIED` under both guarding rungs, and `SEVERE` resolves it
    to `REDUCED`."

    Design: Difficulty/compensating_invariant/advancement_conservation_across_held_and_reduced
    """
    scenario = build_scenario("delivered")
    _created, first = schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00
    )
    second = schedule_visit(scenario, scheduled_for="2026-06-02", requested_increment_mm=1.00)
    validate_success(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "MODERATE"}, scenario["dent_headers"]
        )
    )
    reduced = validate_success(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "SEVERE"}, scenario["dent_headers"]
        )
    )
    assert reduced["status"] == "REDUCED"
    assert reduced["applied_increment_mm"] == approx_mm(-0.50)

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(5.25)
    assert appliance["applied_visit_count"] == 2
    visits, _meta = validate_paginated(
        api.list_titration_visits(
            scenario["dent_headers"], {"appliance_id": scenario["app_id"]}
        )
    )
    assert_protrusive_conservation(appliance, visits)
    assert appliance["current_advancement_mm"] == approx_mm(
        appliance["starting_advancement_mm"] + 1.00 - 0.50
    )


def test_titration_interval_refuses_an_advance_thirteen_days_later(api):
    """PRD §2.6 rung 21: "At least 14 whole days separate this application from the appliance's
    most recent applied or reduced visit — otherwise `ERR_TITRATION_INTERVAL` (422). Evaluated
    only when `side_effect_severity` is `NONE` or `MILD`."
    PRD §3.6: "at least 14 whole days must separate this application from the appliance's most
    recent `APPLIED` or `REDUCED` visit, measured from that visit's `applied_on` to the current
    clock date, with the boundary inclusive — exactly 14 days passes, 13 does not, and where
    there is no prior applied or reduced visit the interval does not apply — failing which the
    answer is `ERR_TITRATION_INTERVAL`"

    Design: Difficulty/resource_temporal_overlap/titration_minimum_gap_boundary_on_appliance
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-14T00:00:00Z")
    second = schedule_visit(scenario, scheduled_for="2026-06-14", requested_increment_mm=1.00)
    validate_error(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_TITRATION_INTERVAL.value,
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(5.75)
    assert appliance["applied_visit_count"] == 1


def test_titration_interval_admits_the_advance_on_day_fourteen(api):
    """PRD §3.6: "at least 14 whole days must separate this application from the appliance's most
    recent `APPLIED` or `REDUCED` visit, measured from that visit's `applied_on` to the current
    clock date, with the boundary inclusive — exactly 14 days passes, 13 does not, and where
    there is no prior applied or reduced visit the interval does not apply — failing which the
    answer is `ERR_TITRATION_INTERVAL`"
    PRD §3.6: "On success, `applied_increment_mm` is set to the bounded value, `applied_on` is
    stamped from the clock date, `days_since_prior_applied` records the whole days from the prior
    applied or reduced visit's `applied_on` to this one (null for the first such visit on the
    device), and the appliance's `current_advancement_mm` and `applied_visit_count` are
    recomputed."

    Design: Difficulty/resource_temporal_overlap/titration_minimum_gap_boundary_on_appliance
    """
    scenario = build_scenario("delivered")
    schedule_and_apply_visit(scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00)
    set_clock("2026-06-14T00:00:00Z")
    second = schedule_visit(scenario, scheduled_for="2026-06-14", requested_increment_mm=1.00)
    validate_error(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_TITRATION_INTERVAL.value,
    )
    set_clock("2026-06-15T00:00:00Z")
    applied = validate_success(
        api.apply_titration_visit(
            second["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        )
    )
    assert applied["status"] == "APPLIED"
    assert applied["days_since_prior_applied"] == 14
    assert applied["applied_increment_mm"] == approx_mm(1.00)
    assert_calendar_date(applied["applied_on"], "2026-06-15", "TitrationVisit.applied_on")

    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(6.75)
    assert appliance["applied_visit_count"] == 2


def test_titration_interval_is_reported_before_the_protrusive_ceiling(api):
    """PRD §2.6: "**The rungs are evaluated in ascending order and evaluation stops at the first
    rung that fails**; that rung's error identifier and HTTP status are the response, and no
    later rung is consulted."
    PRD §2.6 rung 21: "At least 14 whole days separate this application from the appliance's most
    recent applied or reduced visit — otherwise `ERR_TITRATION_INTERVAL` (422). Evaluated only
    when `side_effect_severity` is `NONE` or `MILD`."
    PRD §2.6 rung 22: "The bounded increment must not carry `current_advancement_mm` past the
    appliance's `max_protrusive_mm` — otherwise `ERR_PROTRUSION_LIMIT_EXCEEDED` (422). Evaluated
    only when `side_effect_severity` is `NONE` or `MILD`."

    Design: Difficulty/priority_pair_validation_conflict/titration_interval_beats_protrusion_ceiling
    """
    scenario = build_scenario("titrated")
    fourth = schedule_visit(
        scenario, scheduled_for="2026-06-29", requested_increment_mm=0.50
    )
    error = validate_error(
        api.apply_titration_visit(
            fourth["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_TITRATION_INTERVAL.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROTRUSION_LIMIT_EXCEEDED.value, (
        "7.75 + 0.50 exceeds the 8.00 mm ceiling, yet the temporal rung answers first"
    )


def test_blocked_apply_leaves_the_appliance_and_visit_untouched(api):
    """PRD §2.6: "A request that would fail several rungs therefore reports only the
    lowest-numbered one, and no test of a later rung's behaviour is meaningful on a request that
    already fails an earlier one."
    PRD §2.10: "An appliance's `current_advancement_mm` always equals its
    `starting_advancement_mm` plus the sum of `applied_increment_mm` over exactly those
    `TitrationVisit` rows on that appliance whose `status` is `APPLIED` or `REDUCED`; and it
    always lies between 0.00 and the appliance's `max_protrusive_mm` inclusive."

    Design: Difficulty/priority_pair_validation_conflict/titration_interval_beats_protrusion_ceiling
    """
    scenario = build_scenario("titrated")
    fourth = schedule_visit(
        scenario, scheduled_for="2026-06-29", requested_increment_mm=0.50
    )
    validate_error(
        api.apply_titration_visit(
            fourth["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_TITRATION_INTERVAL.value,
    )
    visit = validate_success(
        api.get_titration_visit(fourth["id"], scenario["dent_headers"])
    )
    assert visit["status"] == "SCHEDULED"
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(7.75)
    assert appliance["applied_visit_count"] == 3


def test_protrusive_ceiling_refuses_the_overshoot_and_admits_the_exact_fit(api):
    """PRD §3.6: "The ceiling is a hard stop and never a silent clamp: a device sitting at 7.50
    mm against an 8.00 mm ceiling refuses a bounded 1.00 mm outright rather than applying 0.50
    mm, though it accepts a request of exactly 0.50 mm and lands on 8.00 mm."
    PRD §3.6: "Creating a visit assigns `visit_seq`, the one-based ordinal of this visit among
    all visits on that appliance ordered by `created_at` ascending, and it **supersedes** any
    visit on the same appliance still in `SCHEDULED` or `HELD`, moving each to `SUPERSEDED`."

    Design: Corner/validations/protrusion_ceiling_rejects_the_overshoot_and_accepts_the_exact_fit
    """
    scenario = build_scenario("titrated")
    set_clock("2026-07-13T00:00:00Z")
    fourth = schedule_visit(
        scenario, scheduled_for="2026-07-13", requested_increment_mm=0.50
    )
    validate_error(
        api.apply_titration_visit(
            fourth["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_PROTRUSION_LIMIT_EXCEEDED.value,
    )
    fifth = schedule_visit(
        scenario, scheduled_for="2026-07-13", requested_increment_mm=0.25
    )
    superseded = validate_success(
        api.get_titration_visit(fourth["id"], scenario["dent_headers"])
    )
    assert superseded["status"] == "SUPERSEDED"

    applied = validate_success(
        api.apply_titration_visit(
            fifth["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        )
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_increment_mm"] == approx_mm(0.25)
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(8.00)
    assert appliance["current_advancement_mm"] == approx_mm(appliance["max_protrusive_mm"])


def test_applied_visit_is_terminal_and_cannot_be_reapplied(api):
    """PRD §3.6: "`APPLIED`, `REDUCED`, `SUPERSEDED` and `VOIDED_BY_HOLD` are all terminal for a
    visit."
    PRD §2.6 rung 12: "First the path resource's own `status` must admit the transition being
    requested; then the governing parent's status must admit it."

    Design: Corner/state_machines/applied_titration_visit_is_terminal
    """
    scenario = build_scenario("delivered")
    _created, applied = schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-01", requested_increment_mm=1.00
    )
    assert applied["status"] == "APPLIED"
    validate_error(
        api.apply_titration_visit(
            applied["id"], {"side_effect_severity": "NONE"}, scenario["dent_headers"]
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["current_advancement_mm"] == approx_mm(5.75)
    assert appliance["applied_visit_count"] == 1


def test_plateau_needs_three_applied_visits(api):
    """PRD §3.6: "the device must be `IN_TITRATION`, must not be on a recall hold, and must have
    at least 3 applied visits behind it — `applied_visit_count` of 3 is enough and 2 is not, and
    a shortfall answers `ERR_PLATEAU_REQUIRED`. Declaring moves the device `IN_TITRATION →
    TITRATION_PLATEAU`, stamps `plateau_declared_on` from the clock date, and moves every visit
    on that appliance still `SCHEDULED` or `HELD` to `SUPERSEDED`."

    Design: Corner/validations/plateau_needs_three_applied_visits
    """
    scenario = build_scenario("delivered")
    for day in ("2026-06-01", "2026-06-15"):
        set_clock(f"{day}T00:00:00Z")
        schedule_and_apply_visit(scenario, scheduled_for=day, requested_increment_mm=1.00)

    validate_error(
        api.declare_plateau(scenario["app_id"], {}, scenario["dent_headers"]),
        ApiErrorId.ERR_PLATEAU_REQUIRED.value,
    )
    set_clock("2026-06-29T00:00:00Z")
    schedule_and_apply_visit(
        scenario, scheduled_for="2026-06-29", requested_increment_mm=1.00
    )
    plateaued = validate_success(
        api.declare_plateau(scenario["app_id"], {}, scenario["dent_headers"])
    )
    assert plateaued["lifecycle_status"] == "TITRATION_PLATEAU"
    assert_calendar_date(
        plateaued["plateau_declared_on"], "2026-06-29", "Appliance.plateau_declared_on"
    )
    assert plateaued["applied_visit_count"] == 3
    assert plateaued["current_advancement_mm"] == approx_mm(7.75)


def test_titration_visit_is_accepted_once_the_device_is_delivered(api):
    """PRD §3.6: "Creating a visit assigns `visit_seq`, the one-based ordinal of this visit among
    all visits on that appliance ordered by `created_at` ascending, and it **supersedes** any
    visit on the same appliance still in `SCHEDULED` or `HELD`, moving each to `SUPERSEDED`."
    PRD §3.6: "A visit begins in `SCHEDULED` with `applied_increment_mm`, `applied_on` and
    `days_since_prior_applied` all null."

    Design: Difficulty/cross_entity_state_dependency/titration_visit_create_requires_delivered_appliance
    """
    scenario = build_scenario("written_order_signed")
    set_clock("2026-06-01T00:00:00Z")
    delivered = validate_success(
        api.deliver_appliance(
            scenario["app_id"],
            {"delivered_on": "2026-06-01", "written_order_id": scenario["wo_id"]},
            scenario["dent_headers"],
        )
    )
    assert delivered["lifecycle_status"] == "DELIVERED"

    visit = validate_success(
        api.create_titration_visit(
            {
                "appliance_id": scenario["app_id"],
                "performed_by_dentist_id": scenario["dent_id"],
                "scheduled_for": "2026-06-01",
                "requested_increment_mm": 1.00,
                "expected_appliance_version": delivered["version"],
            },
            scenario["dent_headers"],
        ),
        201,
    )
    assert visit["status"] == "SCHEDULED"
    assert visit["visit_seq"] == 1
    assert delivered["starting_advancement_mm"] == approx_mm(4.75)


def test_titration_visit_list_honours_limit_and_offset(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` —
    the number of rows matching the filters *before* the page window is applied — and `has_more`,
    which is true exactly when `offset` plus the number of returned rows is less than
    `total_count`."
    PRD §2.3: "**Every list endpoint sorts by `created_at` ascending.**"

    Design: Corner/endpoints/titration_visit_list_honours_limit_and_offset
    """
    scenario = build_scenario("titrated")
    rows, meta = validate_paginated(
        api.list_titration_visits(
            scenario["dent_headers"],
            {"appliance_id": scenario["app_id"], "limit": 1, "offset": 1},
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert len(rows) == 1
    assert rows[0]["visit_seq"] == 2


def test_stale_appliance_version_blocks_titration_visit_creation(api):
    """PRD §2.7: "**Creating a `TitrationVisit`** requires `expected_appliance_version` carrying
    the client's last observed `version` of the target `Appliance`. If the appliance's `version`
    has advanced since the client read it, the create is rejected with `ERR_STALE_VERSION` (412).
    The guard exists because visit creation supersedes any visit still `SCHEDULED` or `HELD` on
    that appliance: a writer holding a stale view of the appliance would silently discard a
    colleague's open visit."

    Design: Corner/cross_cutting_complexity_layers/stale_appliance_version_blocks_titration_visit_creation
    """
    scenario = build_scenario("delivered")
    stale_version = read_appliance_version(scenario["app_id"], scenario["dent_headers"])
    first = validate_success(
        api.create_titration_visit(
            {
                "appliance_id": scenario["app_id"],
                "performed_by_dentist_id": scenario["dent_id"],
                "scheduled_for": "2026-06-01",
                "requested_increment_mm": 1.00,
                "expected_appliance_version": stale_version,
            },
            scenario["dent_headers"],
        ),
        201,
    )
    validate_error(
        api.create_titration_visit(
            {
                "appliance_id": scenario["app_id"],
                "performed_by_dentist_id": scenario["dent_id"],
                "scheduled_for": "2026-06-02",
                "requested_increment_mm": 1.00,
                "expected_appliance_version": stale_version,
            },
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )
    untouched = validate_success(
        api.get_titration_visit(first["id"], scenario["dent_headers"])
    )
    assert untouched["status"] == "SCHEDULED", "the stale request must not supersede it"
    rows, meta = validate_paginated(
        api.list_titration_visits(
            scenario["dent_headers"], {"appliance_id": scenario["app_id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1
