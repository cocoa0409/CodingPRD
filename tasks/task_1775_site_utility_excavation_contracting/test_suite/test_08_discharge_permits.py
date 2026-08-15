"""Discharge permits and compliance readings: classification precedence,
the turbidity suspension cascade, permit lifecycle, and readings listing."""

from test_helpers import (
    FOREMAN,
    INSPECTOR,
    ApiErrorId,
    advance_clock,
    create_discharge_permit,
    create_project,
    get_owner,
    get_permit,
    get_segment,
    get_window,
    propose_shutdown_window,
    record_discharge_reading,
    setup_backfilling_segment,
    setup_installing_segment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_flow_at_max_stays_normal(api):
    """PRD §3.6: "Otherwise, if `flow_gpm` is strictly greater than
    `max_flow_gpm`, the classification is `EXCEEDS_FLOW`. Failing all three,
    the reading is `NORMAL`."
    PRD §3.6: "The computed `volume_gal` is the flow multiplied by the
    duration."

    Design: Difficulty/boundary_precision_check/discharge_flow_at_max_stays_normal
    """
    project = create_project(name="P-FLW", contract_ref="C-1200",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(project)
    assert permit["status"] == "ACTIVE"

    reading = record_discharge_reading(
        permit["id"], recorded_at="2026-08-01T06:00:00Z",
        flow_gpm=500, turbidity_ntu=10, duration_min=10,
    )
    # 500 > 500 is false — the flow boundary is exclusive.
    assert reading["classification"] == "NORMAL"
    assert reading["volume_gal"] == 5000

    permit = get_permit(permit["id"])
    assert permit["status"] == "ACTIVE"
    assert permit["exceedance_count"] == 0


def test_flow_above_max_exceeds_without_suspending(api):
    """PRD §3.6: "Otherwise, if `flow_gpm` is strictly greater than
    `max_flow_gpm`, the classification is `EXCEEDS_FLOW`. Failing all three,
    the reading is `NORMAL`. Any of the three exceedance classifications
    increments the permit's `exceedance_count` by one."
    PRD §3.6: "`EXCEEDS_TURBIDITY` suspends the permit, moving it `ACTIVE →
    SUSPENDED`"

    Design: Difficulty/boundary_precision_check/discharge_flow_at_max_stays_normal
    """
    project = create_project(name="P-FLW2", contract_ref="C-1201",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(project)

    reading = record_discharge_reading(
        permit["id"], recorded_at="2026-08-01T06:00:00Z",
        flow_gpm=501, turbidity_ntu=10, duration_min=10,
    )
    assert reading["classification"] == "EXCEEDS_FLOW"

    # A flow exceedance counts but does not suspend the permit.
    permit = get_permit(permit["id"])
    assert permit["exceedance_count"] == 1
    assert permit["status"] == "ACTIVE"


def test_daily_volume_crossing_flips_classification(api):
    """PRD §3.6: "Otherwise, if the day's cumulative volume — the sum of
    `volume_gal` across every reading of this permit whose `recorded_at` falls
    on the same UTC calendar date as the new reading, processed
    chronologically by `recorded_at` and then `created_at`, the new reading
    included — is strictly greater than `daily_volume_limit_gal`, the
    classification is `EXCEEDS_VOLUME`."

    Design: Corner/calculations/daily_volume_crossing_flips_classification
    """
    project = create_project(name="P-VOL", contract_ref="C-301",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(project)

    r1 = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T01:00:00Z",
        flow_gpm=100, turbidity_ntu=10, duration_min=400,
    )
    assert r1["volume_gal"] == 40_000
    assert r1["classification"] == "NORMAL"

    r2 = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T02:00:00Z",
        flow_gpm=100, turbidity_ntu=10, duration_min=400,
    )
    assert r2["classification"] == "NORMAL"  # cumulative 80000

    # Cumulative reaches exactly 100000 — the strictly-greater boundary holds.
    r3 = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T03:00:00Z",
        flow_gpm=100, turbidity_ntu=10, duration_min=200,
    )
    assert r3["classification"] == "NORMAL"

    # 101000 > 100000 crosses the limit.
    r4 = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T04:00:00Z",
        flow_gpm=100, turbidity_ntu=10, duration_min=10,
    )
    assert r4["classification"] == "EXCEEDS_VOLUME"

    permit = get_permit(permit["id"])
    assert permit["exceedance_count"] == 1
    assert permit["status"] == "ACTIVE"


def test_permit_expires_at_effective_to(api):
    """PRD §2.5: "Third, discharge permits move: `ISSUED` becomes `ACTIVE`
    when the current instant falls inside the permit's effective window, and a
    permit in `ISSUED` or `ACTIVE` becomes `EXPIRED` once its `effective_to`
    has been reached."
    PRD §3.6: "Readings are accepted only while the permit is `ACTIVE`
    (`ERR_PERMIT_NOT_ACTIVE`), and `recorded_at` must fall inside the permit's
    effective window (`ERR_READING_OUTSIDE_PERMIT_WINDOW`)."

    Design: Corner/state_machines/permit_expires_at_effective_to
    """
    project = create_project(name="P-EXP", contract_ref="C-209")
    permit = create_discharge_permit(
        project, permit_number="DP-9",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-10T00:00:00Z",
    )
    assert permit["status"] == "ACTIVE"

    advance_clock("2026-08-10T00:00:00Z")
    assert get_permit(permit["id"])["status"] == "EXPIRED"

    # recorded_at inside the old window still fails: the permit state gates.
    response = api.create_discharge_reading(
        {
            "discharge_permit_id": permit["id"],
            "recorded_at": "2026-08-05T00:00:00Z",
            "flow_gpm": 100, "turbidity_ntu": 10, "duration_min": 10,
        },
        FOREMAN,
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)


def test_reading_outside_permit_window_rejected(api):
    """PRD §3.6: "Readings are accepted only while the permit is `ACTIVE`
    (`ERR_PERMIT_NOT_ACTIVE`), and `recorded_at` must fall inside the permit's
    effective window (`ERR_READING_OUTSIDE_PERMIT_WINDOW`)."
    PRD §3.6: "the effective window bounded by `effective_from` and
    `effective_to`, treated as half-open — valid on or after `effective_from`
    and strictly before `effective_to`."

    Design: Corner/validations/reading_outside_permit_window
    """
    project = create_project(name="P-ROW", contract_ref="C-412",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(
        project, permit_number="DP-2",
        effective_from="2026-08-05T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    assert permit["status"] == "ISSUED"
    advance_clock("2026-08-06T00:00:00Z")
    assert get_permit(permit["id"])["status"] == "ACTIVE"

    response = api.create_discharge_reading(
        {
            "discharge_permit_id": permit["id"],
            "recorded_at": "2026-08-04T23:00:00Z",
            "flow_gpm": 100, "turbidity_ntu": 10, "duration_min": 10,
        },
        FOREMAN,
    )
    validate_error(response, ApiErrorId.ERR_READING_OUTSIDE_PERMIT_WINDOW, 422)


def test_reading_on_suspended_permit_rejected(api):
    """PRD §3.6: "Readings are accepted only while the permit is `ACTIVE`
    (`ERR_PERMIT_NOT_ACTIVE`)"
    PRD §3.6: "`EXCEEDS_TURBIDITY` suspends the permit, moving it `ACTIVE →
    SUSPENDED`"

    Design: Corner/validations/reading_on_suspended_permit_rejected
    """
    project = create_project(name="P-RSP", contract_ref="C-413",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(project, permit_number="DP-3")

    first = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T00:00:00Z",
        flow_gpm=100, turbidity_ntu=50, duration_min=10,
    )
    assert first["classification"] == "EXCEEDS_TURBIDITY"
    assert get_permit(permit["id"])["status"] == "SUSPENDED"

    response = api.create_discharge_reading(
        {
            "discharge_permit_id": permit["id"],
            "recorded_at": "2026-08-02T01:00:00Z",
            "flow_gpm": 100, "turbidity_ntu": 10, "duration_min": 10,
        },
        FOREMAN,
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

    _, meta = validate_paginated(
        api.list_discharge_readings(permit["id"], INSPECTOR)
    )
    assert meta["total_count"] == 1, "rejected reading must not persist"


def test_readings_listed_chronologically_and_filtered(api):
    """PRD §3.6: "A permit's readings are listed in chronological order — by
    `recorded_at`, then `created_at` — rather than the default ordering, and
    may be filtered by `classification`; permits themselves may be listed
    filtered by `project_id` or `status`."

    Design: Corner/endpoints/readings_subresource_listing
    """
    project = create_project(name="P-RDL", contract_ref="C-502",
                             soil_class_default="SOIL_A")
    permit = create_discharge_permit(project, permit_number="DP-4")

    normal = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T02:00:00Z",
        flow_gpm=100, turbidity_ntu=10, duration_min=10,
    )
    flow_exceed = record_discharge_reading(
        permit["id"], recorded_at="2026-08-02T01:00:00Z",
        flow_gpm=600, turbidity_ntu=10, duration_min=5,
    )
    assert flow_exceed["classification"] == "EXCEEDS_FLOW"

    readings, meta = validate_paginated(
        api.list_discharge_readings(permit["id"], INSPECTOR)
    )
    assert meta["total_count"] == 2
    # The later-created 01:00 reading sorts before the 02:00 reading.
    assert [r["id"] for r in readings] == [flow_exceed["id"], normal["id"]]

    filtered, meta_f = validate_paginated(
        api.list_discharge_readings(
            permit["id"], INSPECTOR, params={"classification": "EXCEEDS_FLOW"}
        )
    )
    assert meta_f["total_count"] == 1
    assert filtered[0]["id"] == flow_exceed["id"]

    permit = get_permit(permit["id"])
    assert permit["exceedance_count"] == 1
    assert permit["status"] == "ACTIVE"


def test_turbidity_suspension_depth3_cascade(api):
    """PRD §3.6: "`EXCEEDS_TURBIDITY` suspends the permit, moving it `ACTIVE →
    SUSPENDED`, and the `SUSPENDED` status cascades: every segment of the
    project that is `INSTALLING` with `requires_dewatering` true moves to
    `ON_HOLD` with `hold_reason` `DEWATERING` and `resume_status`
    `INSTALLING`, and every `PROPOSED` shutdown window of each held segment is
    cancelled with its committed minutes released."
    PRD §3.6: "If the reading's turbidity is at or above the permit's
    turbidity limit, the `classification` is `EXCEEDS_TURBIDITY` — the
    boundary is inclusive."

    Design: Difficulty/transitive_cascade/turbidity_suspend_depth3_cascade
    """
    ctx = setup_installing_segment(
        segment_overrides={"requires_dewatering": True},
        plan_overrides={"protective_system": "TRENCH_BOX", "slope_ratio": None},
        owner_overrides={"min_notice_hours": 24, "max_shutdown_hours": 12},
    )
    project, owner, segment = ctx["project"], ctx["owner"], ctx["segment"]
    assert segment["status"] == "INSTALLING"

    window = propose_shutdown_window(
        project, owner, segment,
        "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z",
    )
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 120

    permit = create_discharge_permit(project)
    assert permit["status"] == "ACTIVE"

    reading = record_discharge_reading(
        permit["id"], recorded_at="2026-08-03T12:00:00Z",
        flow_gpm=100, turbidity_ntu=50, duration_min=30,
    )
    assert reading["classification"] == "EXCEEDS_TURBIDITY"

    permit = get_permit(permit["id"])
    assert permit["status"] == "SUSPENDED"
    assert permit["exceedance_count"] == 1

    held = get_segment(segment["id"])
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "DEWATERING"
    assert held["resume_status"] == "INSTALLING"

    assert get_window(window["id"])["status"] == "CANCELLED"
    assert get_owner(owner["id"])["committed_shutdown_minutes"] == 0


def test_turbidity_suspension_does_not_hold_backfilling_segment(api):
    """PRD §3.6: "Segments already `BACKFILLING` are not held — the pipe is
    already in the ground and covering it cannot wait for a permit."
    PRD §2.6: "When a project's active discharge permit is suspended, segments
    that were `INSTALLING` and flagged `requires_dewatering` move to `ON_HOLD`
    with `hold_reason` `DEWATERING` and `resume_status` `INSTALLING`; segments
    already `BACKFILLING` are not held, because the pipe is already in the
    ground."

    Design: Difficulty/transitive_cascade/turbidity_suspend_depth3_cascade
    """
    ctx = setup_backfilling_segment(
        shallow=True, segment_overrides={"requires_dewatering": True}
    )
    project, segment = ctx["project"], ctx["segment"]
    assert segment["status"] == "BACKFILLING"

    permit = create_discharge_permit(project)
    reading = record_discharge_reading(
        permit["id"], recorded_at="2026-08-03T12:00:00Z",
        flow_gpm=100, turbidity_ntu=50, duration_min=30,
    )
    assert reading["classification"] == "EXCEEDS_TURBIDITY"
    assert get_permit(permit["id"])["status"] == "SUSPENDED"

    # BACKFILLING segments ride the suspension out.
    held = get_segment(segment["id"])
    assert held["status"] == "BACKFILLING"
    assert held["hold_reason"] == "NONE"
