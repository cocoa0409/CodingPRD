"""The release gate: furnace posture, empty loads, pipeline priority,
schedule overlap and quench purge gap, and run-state guards (PRD §2.8,
§3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_order,
    create_approved_recipe,
    create_customer,
    create_furnace,
    create_load,
    create_thermocouple_payload,
    create_work_order,
    get_furnace,
    get_load,
    qualify_furnace,
    record_pyrometry,
    release_load,
    setup_shop,
    start_run,
    validate_error,
    validate_success,
)

SCHED = TEST_USERS["shop_scheduler"]
OPERATOR = TEST_USERS["furnace_operator"]
QE = TEST_USERS["quality_engineer"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / release_gated_on_furnace_posture
# ---------------------------------------------------------------------------

def test_release_gated_on_furnace_posture(api):
    """PRD §3.5: "The load must be in `BUILDING` (`ERR_LOAD_NOT_BUILDING`,
    HTTP 409). The furnace's `qualification_status` must be `QUALIFIED`
    (`ERR_FURNACE_NOT_QUALIFIED`, HTTP 422) — posture is recomputed against
    the logical clock at this moment, so a survey that fell overdue since the
    last read blocks the release."
    PRD §2.7: "Only a `QUALIFIED` furnace may have loads released or started."

    Design: Difficulty/cross_entity_state_dependency/release_gated_on_furnace_posture
    """
    shop = setup_shop(qualified=False)  # no pyrometry records at all
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "UNQUALIFIED"

    res = api.release_load_batch(load["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_FURNACE_NOT_QUALIFIED.value)
    assert get_load(load["id"])["status"] == "BUILDING"


def test_start_run_rechecks_furnace_posture(api):
    """PRD §3.6: "Start-run requires the `RELEASED` status
    (`ERR_LOAD_NOT_RELEASED`, HTTP 409) and re-checks that the furnace is
    still `QUALIFIED` (`ERR_FURNACE_NOT_QUALIFIED`)."
    PRD §3.3: "Loads already released or running are not retroactively
    parked — the posture gate instead bites at release and start-run time
    (§3.5, §3.6)."

    Design: Difficulty/cross_entity_state_dependency/release_gated_on_furnace_posture
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])

    # A failing survey lands after release; the RELEASED load is not parked,
    # but the start-run gate re-checks posture.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-08-02T00:00:00Z",
        result="FAIL",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "UNQUALIFIED"
    assert get_load(load["id"])["status"] == "RELEASED"

    res = api.start_run_load_batch(load["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_FURNACE_NOT_QUALIFIED.value)
    assert get_load(load["id"])["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Corner: state_machines / release_empty_load_rejected
# ---------------------------------------------------------------------------

def test_release_empty_load_rejected(api):
    """PRD §3.5: "Finally, releasing an empty load — one with no `ACTIVE`
    assignment — is rejected with `ERR_EMPTY_LOAD` (HTTP 422)."

    Design: Corner/state_machines/release_empty_load_rejected
    """
    shop = setup_shop()
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    res = api.release_load_batch(load["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_EMPTY_LOAD.value)
    assert get_load(load["id"])["status"] == "BUILDING"


# ---------------------------------------------------------------------------
# Corner: state_machines / load_run_state_guards
# ---------------------------------------------------------------------------

def test_load_run_state_guards(api):
    """PRD §3.6: "Start-run requires the `RELEASED` status
    (`ERR_LOAD_NOT_RELEASED`, HTTP 409) and re-checks that the furnace is
    still `QUALIFIED` (`ERR_FURNACE_NOT_QUALIFIED`)."
    PRD §3.6: "Completing the run requires `RUNNING` (`ERR_LOAD_NOT_RUNNING`)."
    PRD §3.6: "Readings are accepted only while the load is `RUNNING`;
    appending against a load in any other status fails with
    `ERR_LOAD_NOT_RUNNING`."

    Design: Corner/state_machines/load_run_state_guards
    """
    shop = setup_shop()
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assert get_load(load["id"])["status"] == "BUILDING"

    res_start = api.start_run_load_batch(load["id"], OPERATOR)
    validate_error(res_start, ApiErrorId.ERR_LOAD_NOT_RELEASED.value)

    res_complete = api.complete_run_load_batch(load["id"], OPERATOR)
    validate_error(res_complete, ApiErrorId.ERR_LOAD_NOT_RUNNING.value)

    res_reading = api.create_thermocouple_reading(
        create_thermocouple_payload(load["id"]), OPERATOR
    )
    validate_error(res_reading, ApiErrorId.ERR_LOAD_NOT_RUNNING.value)
    assert get_load(load["id"])["status"] == "BUILDING"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# release_state_error_beats_furnace_safety_error
# ---------------------------------------------------------------------------

def test_release_state_error_beats_furnace_safety_error(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed pipeline and surfaces the first failure
    rather than an arbitrary one. The order is: (1) user-context headers
    present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`);
    (2) role permitted for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`);
    (3) customer-ownership scoping (`ERR_OWNERSHIP_MISMATCH`); (4) resource
    existence — path identifiers validated left to right, then request-body
    foreign keys (the `ERR_*_NOT_FOUND` family); (5) state-machine
    preconditions and optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Difficulty/priority_pair_validation_conflict/release_state_error_beats_furnace_safety_error
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])
    start_run(load["id"])  # load now RUNNING

    # Furnace flips to UNQUALIFIED while the load is RUNNING.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-08-02T00:00:00Z",
        result="FAIL",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "UNQUALIFIED"

    # Both the state gate (load not BUILDING) and the safety gate (furnace
    # not QUALIFIED) fail; the state error must surface first.
    res = api.release_load_batch(load["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BUILDING.value)


def test_release_from_hold_beats_furnace_safety_error(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed pipeline and surfaces the first failure
    rather than an arbitrary one."
    PRD §3.5: "The load must be in `BUILDING` (`ERR_LOAD_NOT_BUILDING`,
    HTTP 409). The furnace's `qualification_status` must be `QUALIFIED`
    (`ERR_FURNACE_NOT_QUALIFIED`, HTTP 422) — posture is recomputed against
    the logical clock at this moment, so a survey that fell overdue since the
    last read blocks the release."
    PRD §3.3: "The moment a posture recomputation moves a furnace out of
    `QUALIFIED`, whether from a failing record or simply from the logical
    clock passing a due date, every LoadBatch sitting in `BUILDING` on that
    furnace drops to `HOLD`; when the posture returns to `QUALIFIED`, each
    such `HOLD` load resumes `BUILDING`."

    Design: Difficulty/priority_pair_validation_conflict/release_state_error_beats_furnace_safety_error
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])

    # FAIL survey parks the BUILDING load into HOLD and flips the posture.
    record_pyrometry(
        shop["furnace"]["id"], "TUS", performed_at="2026-08-02T00:00:00Z",
        result="FAIL",
    )
    assert get_furnace(shop["furnace"]["id"])["qualification_status"] == "UNQUALIFIED"
    assert get_load(load["id"])["status"] == "HOLD"

    # State check (priority 5) precedes the furnace-safety check (6).
    res = api.release_load_batch(load["id"], SCHED)
    validate_error(res, ApiErrorId.ERR_LOAD_NOT_BUILDING.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / furnace_schedule_buffered_purge_gap
# ---------------------------------------------------------------------------

def _setup_oil_and_water_shop():
    """QUALIFIED furnace supporting OIL and WATER; APPROVED OIL and WATER
    recipes; one customer."""
    customer = create_customer(name="Gap Co")
    recipe_oil = create_approved_recipe()  # 4140 OIL
    recipe_water = create_approved_recipe(
        alloy_code="304SS", soak_temp_f=1900, soak_tolerance_f=15,
        min_soak_minutes=45, quench_media="WATER",
        fixture_distortion_allowance_in=0.01, hardness_min_hrc=20,
        hardness_max_hrc=30,
    )
    furnace = create_furnace(quench_media_supported=["OIL", "WATER"])
    qualify_furnace(furnace["id"])
    return customer, recipe_oil, recipe_water, furnace


def test_furnace_schedule_buffered_purge_gap(api):
    """PRD §3.5: "Creation also checks the furnace's committed schedule —
    meaning all of its loads in `RELEASED`, `RUNNING`, or `COMPLETED`: a
    window overlapping any of them is rejected with
    `ERR_FURNACE_SCHEDULE_OVERLAP` (HTTP 409), and when an adjacent load uses
    a different quench medium with less than 60 minutes between the earlier
    run's end and the later run's start, the request fails with
    `ERR_QUENCH_PURGE_GAP_VIOLATION` (HTTP 409). Adjacent loads sharing the
    same quench medium need no purge gap, though they still may not overlap."

    Design: Difficulty/resource_temporal_overlap/furnace_schedule_buffered_purge_gap
    """
    customer, recipe_oil, recipe_water, furnace = _setup_oil_and_water_shop()
    order = create_work_order(customer["id"], recipe_oil["id"])
    load1 = create_load(
        furnace["id"], recipe_oil["id"],
        scheduled_start_at="2026-08-02T08:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load1["id"], order["id"])
    release_load(load1["id"])  # OIL load committed to [08:00, 12:00]

    # WATER load starting 30 minutes after the OIL load ends: inside the
    # 60-minute purge buffer for a media change.
    gap_res = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe_water["id"],
            "scheduled_start_at": "2026-08-02T12:30:00Z",
            "scheduled_end_at": "2026-08-02T14:00:00Z",
        },
        SCHED,
    )
    validate_error(gap_res, ApiErrorId.ERR_QUENCH_PURGE_GAP_VIOLATION.value)

    # Same-medium adjacency at gap 0 needs no purge buffer.
    same_media = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe_oil["id"],
            "scheduled_start_at": "2026-08-02T12:00:00Z",
            "scheduled_end_at": "2026-08-02T14:00:00Z",
        },
        SCHED,
    )
    adjacent = validate_success(same_media, 201)
    assert adjacent["status"] == "BUILDING"

    # True overlap against the committed load is a distinct error.
    overlap_res = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe_oil["id"],
            "scheduled_start_at": "2026-08-02T11:00:00Z",
            "scheduled_end_at": "2026-08-02T13:00:00Z",
        },
        SCHED,
    )
    validate_error(overlap_res, ApiErrorId.ERR_FURNACE_SCHEDULE_OVERLAP.value)


def test_purge_gap_exactly_sixty_minutes_allowed(api):
    """PRD §3.5: "Creation also checks the furnace's committed schedule —
    meaning all of its loads in `RELEASED`, `RUNNING`, or `COMPLETED`: a
    window overlapping any of them is rejected with
    `ERR_FURNACE_SCHEDULE_OVERLAP` (HTTP 409), and when an adjacent load uses
    a different quench medium with less than 60 minutes between the earlier
    run's end and the later run's start, the request fails with
    `ERR_QUENCH_PURGE_GAP_VIOLATION` (HTTP 409). Adjacent loads sharing the
    same quench medium need no purge gap, though they still may not overlap."

    Design: Difficulty/resource_temporal_overlap/furnace_schedule_buffered_purge_gap
    """
    customer, recipe_oil, recipe_water, furnace = _setup_oil_and_water_shop()
    order = create_work_order(customer["id"], recipe_oil["id"])
    load1 = create_load(
        furnace["id"], recipe_oil["id"],
        scheduled_start_at="2026-08-02T08:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load1["id"], order["id"])
    release_load(load1["id"])

    # Exactly 60 minutes between runs: "less than 60 minutes" fails only
    # strictly below the buffer, so a full-hour gap is permitted.
    exact_gap = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe_water["id"],
            "scheduled_start_at": "2026-08-02T13:00:00Z",
            "scheduled_end_at": "2026-08-02T15:00:00Z",
        },
        SCHED,
    )
    assert validate_success(exact_gap, 201)["status"] == "BUILDING"

    # Same-media loads still may not overlap the committed window.
    overlap_res = api.create_load_batch(
        {
            "furnace_id": furnace["id"],
            "recipe_id": recipe_oil["id"],
            "scheduled_start_at": "2026-08-02T11:30:00Z",
            "scheduled_end_at": "2026-08-02T13:30:00Z",
        },
        SCHED,
    )
    validate_error(overlap_res, ApiErrorId.ERR_FURNACE_SCHEDULE_OVERLAP.value)
