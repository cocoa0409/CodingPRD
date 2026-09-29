"""Durability rig reservations and the two cycle-count variants."""
from test_helpers import (
    expected_listing_order,
    abort_run_payload,
    accumulate_cycle_evidence,
    new_equipment_model,
    new_model_revision,
    new_test_rig,
    read_model_revision,
    read_qualification_report,
    read_test_rig,
    read_test_run,
    submit_for_testing,
    run_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

RIG_A = {"name": "RIG-A", "parallel_station_count": 2,
         "supported_duty_classes": ["FULL_COMMERCIAL", "INSTITUTIONAL"]}


def _in_testing_revision(preset="T900", revision_code="T900-R1", target=600_000,
                         rig_overrides=None):
    """Model + IN_TESTING revision + one free rig."""
    model = new_equipment_model(preset)
    revision = new_model_revision(model, preset, revision_code=revision_code,
                                 target_cycle_count=target)
    submit_for_testing(revision["id"])
    rig = new_test_rig(**(rig_overrides or RIG_A))
    return {"model": model, "revision": read_model_revision(revision["id"]), "rig": rig}


FOUR_RUN_HISTORY = [
    {"window_start": "2026-08-02T00:00:00Z", "window_end": "2026-08-06T12:00:00Z",
     "target_cycles": 300_000, "outcome": "PASSED", "achieved_cycles": 180_000},
    {"window_start": "2026-08-06T00:00:00Z", "window_end": "2026-08-10T12:00:00Z",
     "target_cycles": 300_000, "outcome": "PASSED", "achieved_cycles": 240_000},
    {"window_start": "2026-08-10T00:00:00Z", "window_end": "2026-08-14T12:00:00Z",
     "target_cycles": 300_000, "outcome": "FAILED", "failure_cycle_count": 140_000},
    {"window_start": "2026-08-14T00:00:00Z", "window_end": "2026-08-18T12:00:00Z",
     "target_cycles": 300_000, "outcome": "PASSED", "achieved_cycles": 260_000},
]


def test_qualification_report_diverges_by_one_hundred_ninety_thousand_cycles(api):
    """The same four runs give 560,000 verified against 750,000 projected.

    The PRD states that in the verified walk "a run whose `outcome` is `FAILED`
    contributes its `failure_cycle_count` and then **halts the walk entirely**",
    while the projected variant "walks the same ordered list without any early
    stop" and there "a `FAILED` run contributes half of its
    `failure_cycle_count`, likewise truncated to a whole cycle."

    Design: Difficulty/dual_variant_calc/revision_cycle_verified_vs_projected_variant_divergence
    """
    ctx = _in_testing_revision()
    accumulate_cycle_evidence(ctx["revision"], rig=ctx["rig"], run_specs=FOUR_RUN_HISTORY)

    response = api.get_qualification_report(ctx["revision"]["id"],
                                            {"X-User-ID": "pe-01",
                                             "X-User-Role": "ProductEngineer"})

    report = validate_success(response)
    assert report["verified_cycle_count"] == 560_000
    assert report["projected_cycle_count"] == 750_000
    assert report["projected_cycle_count"] - report["verified_cycle_count"] == 190_000
    assert report["min_required_cycles"] == 500_000
    assert report["qualifies"] is True
    assert report["completed_run_count"] == 4
    assert report["running_run_count"] == 0


def test_late_passing_run_is_excluded_from_verified_but_not_from_projected(api):
    """A pass after the first failure is never re-admitted to the verified figure.

    The PRD states that "Evidence recorded after the first chronological failure
    is not verified evidence: later passing runs are ignored until a rework loop
    clears the history."

    Design: Difficulty/dual_variant_calc/revision_cycle_verified_vs_projected_variant_divergence
    """
    ctx = _in_testing_revision()
    evidence = accumulate_cycle_evidence(ctx["revision"], rig=ctx["rig"],
                                         run_specs=FOUR_RUN_HISTORY)

    revision = read_model_revision(ctx["revision"]["id"])

    assert revision["verified_cycle_count"] == 560_000
    assert revision["projected_cycle_count"] == 750_000
    assert revision["status"] == "IN_TESTING", (
        "the FAILED run did not force TEST_FAILED because 560000 >= 500000"
    )
    last = read_test_run(evidence["runs"][3]["id"])
    assert last["status"] == "COMPLETED"
    assert last["outcome"] == "PASSED"
    assert last["achieved_cycles"] == 260_000
    assert revision["verified_cycle_count"] != 820_000


def test_failed_run_forces_test_failed_when_the_recount_is_below_the_gate(api):
    """A failure that leaves the revision short of its gate flips it to TEST_FAILED.

    The PRD states that "Then — and only after that recount — the failure branch
    is evaluated: if the `outcome` was `FAILED`, the recomputed
    `verified_cycle_count` is still below `min_required_cycles`, and the revision
    is currently `IN_TESTING`, the revision moves `IN_TESTING → TEST_FAILED`."

    Design: Difficulty/cross_entity_state_dependency/failed_run_forces_test_failed_only_when_verified_below_gate
    """
    ctx = _in_testing_revision(revision_code="T900-RB")
    accumulate_cycle_evidence(
        ctx["revision"], rig=ctx["rig"],
        run_specs=[{"window_start": "2026-08-14T00:00:00Z",
                    "window_end": "2026-08-18T12:00:00Z", "target_cycles": 300_000,
                    "outcome": "PASSED", "achieved_cycles": 100_000}],
    )
    outstanding = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-18T00:00:00Z", "2026-08-22T12:00:00Z", 300_000),
            {"X-User-ID": "pe-01", "X-User-Role": "ProductEngineer"},
        ),
        201,
    )
    validate_success(api.start_test_run(
        outstanding["id"], {"X-User-ID": "pe-01", "X-User-Role": "ProductEngineer"}))

    response = api.complete_test_run(
        outstanding["id"], {"outcome": "FAILED", "failure_cycle_count": 90_000},
        {"X-User-ID": "pe-01", "X-User-Role": "ProductEngineer"},
    )

    run = validate_success(response)
    assert run["status"] == "COMPLETED"
    assert run["outcome"] == "FAILED"
    assert run["failure_cycle_count"] == 90_000
    revision = read_model_revision(ctx["revision"]["id"])
    assert revision["verified_cycle_count"] == 190_000
    assert revision["projected_cycle_count"] == 145_000
    assert revision["status"] == "TEST_FAILED"
    assert revision["min_required_cycles"] == 500_000
    assert revision["rework_count"] == 0


def test_failed_run_leaves_the_revision_in_testing_when_it_stays_above_the_gate(api):
    """The same failure branch does nothing when the recount still clears the gate.

    The PRD states that "The ordering matters: a failure late in a long evidence
    chain that nonetheless leaves the revision above its gate does not fail the
    revision."

    Design: Difficulty/cross_entity_state_dependency/failed_run_forces_test_failed_only_when_verified_below_gate
    """
    ctx = _in_testing_revision(revision_code="T900-RA")
    accumulate_cycle_evidence(ctx["revision"], rig=ctx["rig"],
                             run_specs=FOUR_RUN_HISTORY[:3])

    revision = read_model_revision(ctx["revision"]["id"])

    assert revision["verified_cycle_count"] == 560_000
    assert revision["projected_cycle_count"] == 490_000
    assert revision["status"] == "IN_TESTING"
    assert revision["min_required_cycles"] == 500_000
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 0


def test_touching_rig_windows_collide_and_exhaust_both_stations(
    api, product_engineer_headers
):
    """A window that starts exactly when another ends still occupies a station.

    The PRD states that a run's reservation window "is **closed and inclusive at
    both ends**" and that the server "refuses the booking with
    `ERR_RIG_CAPACITY_EXCEEDED` when that count has already reached the rig's
    `parallel_station_count`. A new window that starts exactly when an existing
    window ends therefore *does* collide".

    Design: Difficulty/resource_temporal_overlap/test_rig_inclusive_touch_capacity_two_stations
    """
    ctx = _in_testing_revision()
    first = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-02T00:00:00Z", "2026-08-06T00:00:00Z", 300_000),
            product_engineer_headers,
        ),
        201,
    )
    validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z", 300_000),
            product_engineer_headers,
        ),
        201,
    )
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 2
    assert first["window_end"] == "2026-08-06T00:00:00Z"

    response = api.create_test_run(
        run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                         "2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z", 300_000),
        product_engineer_headers,
    )

    validate_error(response, "ERR_RIG_CAPACITY_EXCEEDED", 409)
    rig = read_test_rig(ctx["rig"]["id"])
    assert rig["occupied_station_count"] == 2
    assert rig["parallel_station_count"] == 2


def test_aborting_a_reservation_frees_the_station_for_the_touching_window(
    api, product_engineer_headers
):
    """Once the touching reservation is aborted the identical booking is accepted.

    The PRD states that both abort branches "lower the rig's
    `occupied_station_count`, so the reservation stops blocking overlapping
    windows", and that "an aborted run contributes nothing to either variant".

    Design: Difficulty/resource_temporal_overlap/test_rig_inclusive_touch_capacity_two_stations
    """
    ctx = _in_testing_revision()
    first = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-02T00:00:00Z", "2026-08-06T00:00:00Z", 300_000),
            product_engineer_headers,
        ),
        201,
    )
    validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z", 300_000),
            product_engineer_headers,
        ),
        201,
    )
    validate_error(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z", 300_000),
            product_engineer_headers,
        ),
        "ERR_RIG_CAPACITY_EXCEEDED", 409,
    )
    aborted = validate_success(
        api.abort_test_run(first["id"],
                           abort_run_payload(abort_reason="specimen fixture reallocated"),
                           product_engineer_headers)
    )
    assert aborted["status"] == "ABORTED"

    response = api.create_test_run(
        run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                         "2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z", 300_000),
        product_engineer_headers,
    )

    accepted = validate_success(response, 201)
    assert accepted["status"] == "RESERVED"
    assert accepted["window_start"] == "2026-08-06T00:00:00Z"
    assert accepted["window_end"] == "2026-08-10T00:00:00Z"
    rig = read_test_rig(ctx["rig"]["id"])
    assert rig["occupied_station_count"] == 2
    assert rig["parallel_station_count"] == 2
    revision = read_model_revision(ctx["revision"]["id"])
    assert revision["verified_cycle_count"] == 0
    assert revision["projected_cycle_count"] == 0


def test_cycle_variants_exclude_reserved_and_aborted_runs(api, product_engineer_headers):
    """Reserved and aborted runs feed neither variant; only RUNNING lifts the projection.

    The PRD states that both variants read "the revision's durability runs whose
    `status` is `COMPLETED` or `RUNNING` **and** whose `superseded_by_rework`
    flag is false. Runs still in `RESERVED`, runs that were `ABORTED`, and runs
    superseded by a rework loop are excluded from both variants."

    Design: Corner/calculations/cycle_variants_exclude_reserved_and_aborted_runs
    """
    ctx = _in_testing_revision()
    accumulate_cycle_evidence(ctx["revision"], rig=ctx["rig"])
    baseline = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert baseline["verified_cycle_count"] == 500_000
    assert baseline["projected_cycle_count"] == 500_000
    assert baseline["min_required_cycles"] == 500_000
    assert baseline["completed_run_count"] == 2
    assert baseline["running_run_count"] == 0
    assert baseline["qualifies"] is True

    third = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-10T00:00:00Z", "2026-08-14T12:00:00Z", 100_000),
            product_engineer_headers,
        ),
        201,
    )
    reserved = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert reserved["verified_cycle_count"] == 500_000
    assert reserved["projected_cycle_count"] == 500_000

    validate_success(api.start_test_run(third["id"], product_engineer_headers))
    running = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert running["verified_cycle_count"] == 500_000
    assert running["projected_cycle_count"] == 580_000
    assert running["completed_run_count"] == 2
    assert running["running_run_count"] == 1

    validate_success(
        api.abort_test_run(third["id"],
                           abort_run_payload(abort_reason="specimen fixture reallocated"),
                           product_engineer_headers)
    )
    after_abort = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert after_abort["verified_cycle_count"] == 500_000
    assert after_abort["projected_cycle_count"] == 500_000
    assert after_abort["running_run_count"] == 0
    assert read_test_run(third["id"], product_engineer_headers)["status"] == "ABORTED"
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 0
    qualified = validate_success(
        api.qualify_revision(ctx["revision"]["id"], product_engineer_headers)
    )
    assert qualified["status"] == "QUALIFIED"
    assert qualified["verified_cycle_count"] == 500_000


def test_chronological_walk_orders_by_window_end_not_by_creation(
    api, product_engineer_headers
):
    """The failure created first is processed second because its window ends later.

    The PRD states that both variants "walk that set in the same chronological
    order — by `window_end` ascending, with `created_at` ascending as the
    deterministic tie-break — and both start an accumulator at zero."

    Design: Corner/calculations/chronological_walk_orders_by_window_end_not_by_creation
    """
    ctx = _in_testing_revision()
    failure = accumulate_cycle_evidence(
        ctx["revision"], rig=ctx["rig"],
        run_specs=[{"window_start": "2026-08-18T00:00:00Z",
                    "window_end": "2026-08-22T12:00:00Z", "target_cycles": 600_000,
                    "outcome": "FAILED", "failure_cycle_count": 550_000}],
    )["runs"][0]
    early = accumulate_cycle_evidence(
        ctx["revision"], rig=ctx["rig"],
        run_specs=[{"window_start": "2026-08-02T00:00:00Z",
                    "window_end": "2026-08-06T12:00:00Z", "target_cycles": 300_000,
                    "outcome": "PASSED", "achieved_cycles": 300_000}],
    )["runs"][0]

    report = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)

    assert report["verified_cycle_count"] == 850_000
    assert report["projected_cycle_count"] == 575_000
    assert report["completed_run_count"] == 2
    assert report["running_run_count"] == 0
    assert report["min_required_cycles"] == 500_000
    assert report["qualifies"] is True
    assert read_model_revision(ctx["revision"]["id"])["status"] == "IN_TESTING"
    rows, _ = validate_paginated(
        api.list_test_runs(product_engineer_headers,
                           params={"model_revision_id": ctx["revision"]["id"]})
    )
    assert [row["id"] for row in rows] == expected_listing_order([failure, early]), (
        "the listing follows the §2.3 order, not the §3.2 window_end walk order"
    )
    assert early["window_end"] < failure["window_end"], (
        "the run created second is the chronologically earlier one, so the walk "
        "order and the creation order genuinely differ"
    )
    assert read_test_run(failure["id"], product_engineer_headers)[
        "failure_cycle_count"
    ] == 550_000


def test_rig_duty_class_must_cover_the_revision_model_duty_class(
    api, product_engineer_headers
):
    """An INSTITUTIONAL revision cannot be booked onto a LIGHT_COMMERCIAL-only rig.

    The PRD states that "the rig's `supported_duty_classes` must contain the
    revision's model `duty_class` — a mismatch there is
    `ERR_RIG_DUTY_CLASS_UNSUPPORTED`."

    Design: Corner/validations/rig_duty_class_must_cover_the_revision_model_duty_class
    """
    ctx = _in_testing_revision(
        preset="S500", revision_code="S500-R1", target=950_000,
        rig_overrides={"name": "RIG-LIGHT", "parallel_station_count": 2,
                       "supported_duty_classes": ["LIGHT_COMMERCIAL"]},
    )
    institutional_rig = new_test_rig(
        name="RIG-INST", parallel_station_count=2,
        supported_duty_classes=["FULL_COMMERCIAL", "INSTITUTIONAL"],
    )
    booking = run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                               "2026-08-02T00:00:00Z", "2026-08-06T12:00:00Z", 500_000)

    response = api.create_test_run(booking, product_engineer_headers)

    validate_error(response, "ERR_RIG_DUTY_CLASS_UNSUPPORTED", 422)
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 0
    _, meta = validate_paginated(
        api.list_test_runs(product_engineer_headers,
                           params={"test_rig_id": ctx["rig"]["id"]})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], institutional_rig["id"],
                             "2026-08-02T00:00:00Z", "2026-08-06T12:00:00Z", 500_000),
            product_engineer_headers,
        ),
        201,
    )
    assert accepted["status"] == "RESERVED"
    assert read_test_rig(institutional_rig["id"])["occupied_station_count"] == 1
    revision = read_model_revision(ctx["revision"]["id"])
    assert revision["min_required_cycles"] == 900_000
    assert revision["status"] == "IN_TESTING"


def test_qualification_report_is_a_read_only_projection(api, product_engineer_headers):
    """The report exposes six figures and never mutates the revision it reads.

    The PRD states that the report "returns `verified_cycle_count`,
    `projected_cycle_count`, `min_required_cycles`, a `completed_run_count` and a
    `running_run_count` over the same non-superseded input set, and a boolean
    `qualifies` stating whether the verified figure has reached the gate. The
    report computes, but never persists a different answer from, the values
    stored on the revision."

    Design: Corner/endpoints/qualification_report_projects_both_cycle_variants_side_by_side
    """
    ctx = _in_testing_revision()
    accumulate_cycle_evidence(ctx["revision"], rig=ctx["rig"])
    version_before = read_model_revision(ctx["revision"]["id"])["version"]

    first_response = api.get_qualification_report(ctx["revision"]["id"],
                                                  product_engineer_headers)

    first = validate_success(first_response)
    assert first_response.json()["response_type"] == "object"
    assert first_response.json()["meta"]["api_request_id"].startswith("req_")
    assert first["verified_cycle_count"] == 500_000
    assert first["projected_cycle_count"] == 500_000
    assert first["min_required_cycles"] == 500_000
    assert first["completed_run_count"] == 2
    assert first["running_run_count"] == 0
    assert first["qualifies"] is True
    assert read_model_revision(ctx["revision"]["id"])["version"] == version_before

    third = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-10T00:00:00Z", "2026-08-14T12:00:00Z", 100_000),
            product_engineer_headers,
        ),
        201,
    )
    validate_success(api.start_test_run(third["id"], product_engineer_headers))

    before_second_read = read_model_revision(ctx["revision"]["id"])
    second = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert second["verified_cycle_count"] == 500_000
    assert second["projected_cycle_count"] == 580_000
    assert second["completed_run_count"] == 2
    assert second["running_run_count"] == 1
    revision = read_model_revision(ctx["revision"]["id"])
    assert revision["status"] == "IN_TESTING"
    assert revision["version"] == before_second_read["version"], (
        "reading the report leaves the revision row untouched"
    )
    assert revision["projected_cycle_count"] == second["projected_cycle_count"]


def test_cycle_target_not_met_fires_below_the_gate_and_on_an_outstanding_run(
    api, product_engineer_headers
):
    """One error code covers a short evidence total and an unfinished reservation.

    The PRD states that qualification "requires `verified_cycle_count` to be
    greater than or equal to `min_required_cycles` — the projected figure is
    explicitly *not* a substitute — and requires no run of the revision to be
    outstanding in `RESERVED` or `RUNNING`. Either failure is
    `ERR_CYCLE_TARGET_NOT_MET`."

    Design: Corner/errors/cycle_target_not_met_fires_below_the_gate_and_on_an_outstanding_run
    """
    ctx = _in_testing_revision()
    accumulate_cycle_evidence(
        ctx["revision"], rig=ctx["rig"],
        run_specs=[{"window_start": "2026-08-02T00:00:00Z",
                    "window_end": "2026-08-06T12:00:00Z", "target_cycles": 300_000,
                    "outcome": "PASSED", "achieved_cycles": 300_000}],
    )

    validate_error(api.qualify_revision(ctx["revision"]["id"], product_engineer_headers),
                   "ERR_CYCLE_TARGET_NOT_MET", 422)

    accumulate_cycle_evidence(
        ctx["revision"], rig=ctx["rig"],
        run_specs=[{"window_start": "2026-08-06T00:00:00Z",
                    "window_end": "2026-08-10T12:00:00Z", "target_cycles": 300_000,
                    "outcome": "PASSED", "achieved_cycles": 200_000}],
    )
    outstanding = validate_success(
        api.create_test_run(
            run_payload(ctx["revision"]["id"], ctx["rig"]["id"],
                             "2026-08-10T00:00:00Z", "2026-08-14T12:00:00Z", 100_000),
            product_engineer_headers,
        ),
        201,
    )
    report = read_qualification_report(ctx["revision"]["id"], product_engineer_headers)
    assert report["verified_cycle_count"] == 500_000
    assert report["completed_run_count"] == 2
    assert report["running_run_count"] == 0

    validate_error(api.qualify_revision(ctx["revision"]["id"], product_engineer_headers),
                   "ERR_CYCLE_TARGET_NOT_MET", 422)

    aborted = validate_success(
        api.abort_test_run(
            outstanding["id"],
            abort_run_payload(abort_reason="station released for another programme"),
            product_engineer_headers,
        )
    )
    assert aborted["status"] == "ABORTED"
    qualified = validate_success(
        api.qualify_revision(ctx["revision"]["id"], product_engineer_headers)
    )
    assert qualified["status"] == "QUALIFIED"
    assert qualified["verified_cycle_count"] == 500_000
    assert read_test_rig(ctx["rig"]["id"])["occupied_station_count"] == 0
