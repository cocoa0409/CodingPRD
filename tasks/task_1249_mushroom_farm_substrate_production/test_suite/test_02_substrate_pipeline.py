"""Substrate production: pasteurization cycle lifecycle, capacity, spawn."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_substrate_batch,
    create_batch,
    create_conditioned_batch,
    create_pasteurization_cycle_payload,
    create_spawned_batch,
    create_substrate_batch_payload,
    create_tunnel,
    create_tunnel_payload,
    create_variety,
    get_success_data,
    validate_error,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
COMPOST = TEST_USERS["compost_supervisor_headers"]
ANY = TEST_USERS["any_headers"]


def test_batch_spawn_before_conditioned_rejected(api):
    """PRD §3.1: "Spawning requires the batch to be `CONDITIONED` (otherwise
    `ERR_BATCH_NOT_CONDITIONED`)."

    Design: Corner/state_machines/batch_spawn_before_conditioned_rejected
    """
    variety = create_variety()
    batch = create_batch(tonnage=40.0)
    resp = api.spawn_batch(batch["id"], {"variety_id": variety["id"], "spawn_kg": 280.0}, COMPOST)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_CONDITIONED)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["status"] == "MIXED"
    assert after["variety_id"] is None


def test_batch_spawn_on_mixed_batch_keeps_state(api):
    """PRD §3.1: "Spawning requires the batch to be `CONDITIONED` (otherwise
    `ERR_BATCH_NOT_CONDITIONED`)." A failed spawn leaves the batch MIXED.

    Design: Corner/state_machines/batch_spawn_before_conditioned_rejected
    """
    variety = create_variety()
    batch = create_batch(tonnage=10.0)
    assert batch["status"] == "MIXED"
    resp = api.spawn_batch(batch["id"], {"variety_id": variety["id"], "spawn_kg": 100.0}, COMPOST)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_CONDITIONED)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["status"] == "MIXED"


def test_pasteurization_threshold_and_state_edges(api):
    """PRD §3.1: "The supervisor reports `hours_at_target_temp`, and the cycle
    may complete only when that figure is at least 6.0 hours — the boundary is
    inclusive, so exactly 6.0 completes. Below 6.0 hours the completion is
    rejected with `ERR_PASTEURIZATION_INCOMPLETE` and the cycle stays
    `RUNNING`."
    PRD §3.1: "failing requires `RUNNING` (otherwise `ERR_CYCLE_INVALID_STATE`)";
    completing similarly requires RUNNING.

    Design: Corner/state_machines/pasteurization_threshold_and_state_edges
    """
    tunnel = create_tunnel()
    batch = create_batch(tonnage=40.0)
    pcycle = get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    # Complete on SCHEDULED fails state.
    r1 = api.complete_pasteurization_cycle(pcycle["id"], {"hours_at_target_temp": 8.0}, COMPOST)
    validate_error(r1, ApiErrorId.ERR_CYCLE_INVALID_STATE)

    get_success_data(api.start_pasteurization_cycle(pcycle["id"], COMPOST))

    # 5.9 h fails the inclusive >= 6.0 threshold; cycle stays RUNNING.
    r2 = api.complete_pasteurization_cycle(pcycle["id"], {"hours_at_target_temp": 5.9}, COMPOST)
    validate_error(r2, ApiErrorId.ERR_PASTEURIZATION_INCOMPLETE)
    mid = get_success_data(api.get_pasteurization_cycle(pcycle["id"], ANY))
    assert mid["status"] == "RUNNING"

    # Exactly 6.0 completes (boundary inclusive).
    r3 = api.complete_pasteurization_cycle(pcycle["id"], {"hours_at_target_temp": 6.0}, COMPOST)
    done = validate_success(r3, expected_status=200)
    assert done["status"] == "COMPLETED"
    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert batch_after["status"] == "CONDITIONED"


def test_pasteurization_complete_at_exact_threshold_updates_batch(api):
    """PRD §3.1: "A successful completion moves the cycle to `COMPLETED` and
    advances the batch from `PASTEURIZING` to `CONDITIONED`, bumping the
    batch's `version`."

    Design: Corner/state_machines/pasteurization_threshold_and_state_edges
    """
    batch, _tunnel, pcycle = create_conditioned_batch(tonnage=25.0, complete_hours=6.0)
    assert batch["status"] == "CONDITIONED"
    pc = get_success_data(api.get_pasteurization_cycle(pcycle["id"], ANY))
    assert pc["status"] == "COMPLETED"


def test_batch_pasteurization_retry_cycle(api):
    """PRD §3.1: "A cycle that suffers contamination or a temperature
    excursion is instead failed: failing requires `RUNNING` (otherwise
    `ERR_CYCLE_INVALID_STATE`), moves the cycle to `FAILED`, drops the batch
    back from `PASTEURIZING` to `MIXED` so it can be rebooked, and — because
    the tunnel itself is now suspect — forces the tunnel from `AVAILABLE` to
    `OUT_OF_SERVICE`."
    PRD §3.1: "Only an `OUT_OF_SERVICE` tunnel can be sanitized; sanitizing
    returns it to `AVAILABLE`."

    Design: Difficulty/non_linear_state_machine/batch_pasteurization_retry_cycle
    """
    tunnel = create_tunnel()
    batch = create_batch(tonnage=40.0)
    pc1 = get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    get_success_data(api.start_pasteurization_cycle(pc1["id"], COMPOST))
    get_success_data(api.fail_pasteurization_cycle(pc1["id"], COMPOST))

    batch_mid = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    tunnel_mid = get_success_data(api.get_tunnel(tunnel["id"], ANY))
    assert batch_mid["status"] == "MIXED", "fail must loop batch back to MIXED"
    assert tunnel_mid["status"] == "OUT_OF_SERVICE"

    # Sanitize and retry the SAME batch in a new cycle.
    get_success_data(api.sanitize_tunnel(tunnel["id"], COMPOST))
    pc2 = get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(
            batch_id=batch["id"], tunnel_id=tunnel["id"],
            planned_start="2026-05-03T00:00:00Z", planned_end="2026-05-04T00:00:00Z",
        ),
        COMPOST,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-03T00:00:00Z"}, FARM))
    get_success_data(api.start_pasteurization_cycle(pc2["id"], COMPOST))
    get_success_data(api.complete_pasteurization_cycle(pc2["id"], {"hours_at_target_temp": 8.0}, COMPOST))

    pc1_after = get_success_data(api.get_pasteurization_cycle(pc1["id"], ANY))
    pc2_after = get_success_data(api.get_pasteurization_cycle(pc2["id"], ANY))
    batch_after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert pc1_after["status"] == "FAILED"
    assert pc2_after["status"] == "COMPLETED"
    assert batch_after["status"] == "CONDITIONED"


def test_batch_pasteurization_retry_blocked_while_tunnel_out_of_service(api):
    """PRD §3.1: a failed cycle "forces the tunnel from `AVAILABLE` to
    `OUT_OF_SERVICE`" and "Only an `OUT_OF_SERVICE` tunnel can be sanitized;
    sanitizing returns it to `AVAILABLE`."

    After the fail, the batch must be MIXED (rebookable) and the tunnel must
    be OUT_OF_SERVICE until sanitized.

    Design: Difficulty/non_linear_state_machine/batch_pasteurization_retry_cycle
    """
    tunnel = create_tunnel()
    batch = create_batch(tonnage=40.0)
    pc1 = get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    get_success_data(api.start_pasteurization_cycle(pc1["id"], COMPOST))
    get_success_data(api.fail_pasteurization_cycle(pc1["id"], COMPOST))

    tunnel_state = get_success_data(api.get_tunnel(tunnel["id"], ANY))
    batch_state = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert tunnel_state["status"] == "OUT_OF_SERVICE"
    assert batch_state["status"] == "MIXED"

    get_success_data(api.sanitize_tunnel(tunnel["id"], COMPOST))
    tunnel_after = get_success_data(api.get_tunnel(tunnel["id"], ANY))
    assert tunnel_after["status"] == "AVAILABLE"


def test_tunnel_capacity_exceeded_rejected(api):
    """PRD §3.1: "the batch's `tonnage` must not exceed the tunnel's
    `capacity_tonnes`, a violation rejected with `ERR_TUNNEL_CAPACITY_EXCEEDED`."

    Design: Corner/validations/tunnel_capacity_exceeded_rejected
    """
    tunnel = create_tunnel(capacity_tonnes=100.0)
    batch = create_batch(tonnage=120.0)
    resp = api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    )
    validate_error(resp, ApiErrorId.ERR_TUNNEL_CAPACITY_EXCEEDED)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["status"] == "MIXED", "rejected create must not change batch state"


def test_spawn_recipe_mismatch_rejected(api):
    """PRD §3.1: "Spawning requires the batch to be `CONDITIONED` ... and
    requires the variety's `substrate_recipe` to equal the batch's `recipe`,
    a mismatch rejected with `ERR_RECIPE_MISMATCH`."

    Design: Corner/validations/spawn_recipe_mismatch_rejected
    """
    sh1 = create_variety(
        variety_code="SH1", display_name="Shiitake", substrate_recipe="STRAW_SAWDUST",
        target_bioefficiency_pct=18.0, shelf_life_days=7, spawn_run_days=4,
        casing_days=2, max_flushes=2, flush_yield_distribution=[0.6, 0.4],
    )
    tunnel = create_tunnel()
    batch = create_batch(recipe="PHASE_II_COMPOST", tonnage=40.0)
    pcycle = get_success_data(api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(batch_id=batch["id"], tunnel_id=tunnel["id"]),
        COMPOST,
    ))
    get_success_data(api.start_pasteurization_cycle(pcycle["id"], COMPOST))
    get_success_data(api.complete_pasteurization_cycle(pcycle["id"], {"hours_at_target_temp": 8.0}, COMPOST))

    resp = api.spawn_batch(batch["id"], {"variety_id": sh1["id"], "spawn_kg": 280.0}, COMPOST)
    validate_error(resp, ApiErrorId.ERR_RECIPE_MISMATCH)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["status"] == "CONDITIONED"
    assert after["variety_id"] is None


def test_cycle_create_body_fk_not_found(api):
    """PRD §2.8: "foreign-key references in the request body — `batch_id`,
    `tunnel_id`, `room_id`, `variety_id`, `worker_id`, `buyer_id` — must
    exist (priority 5)." A missing batch surfaces `ERR_BATCH_NOT_FOUND`.

    Design: Corner/validations/cycle_create_body_fk_not_found
    """
    tunnel = create_tunnel()
    resp = api.create_pasteurization_cycle(
        create_pasteurization_cycle_payload(
            batch_id="55555555-5555-5555-5555-555555555555",
            tunnel_id=tunnel["id"],
        ),
        COMPOST,
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_FOUND)


def test_exact_tonnage_allocation_exhausts_batch(api):
    """PRD §3.2: "the `allocated_tonnage` must be ... not exceed the batch's
    `remaining_tonnage` (otherwise `ERR_INSUFFICIENT_SUBSTRATE`)" — the
    boundary is `<=`, so exactly-equal allocation succeeds.
    PRD §3.1: "If a reservation draws `remaining_tonnage` down to exactly
    zero while the batch is `SPAWNED`, the batch automatically transitions
    `SPAWNED → EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/exact_tonnage_allocation_exhausts_batch
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = get_success_data(api.create_room(
        {"room_code": "R1", "capacity_tonnes": 50.0}, FARM,
    ))
    create_resp = api.create_room_cycle(
        {
            "room_id": room["id"], "batch_id": batch["id"],
            "allocated_tonnage": 40.0,
            "planned_start": "2026-05-03T00:00:00Z",
            "planned_end": "2026-06-14T00:00:00Z",
            "expected_room_version": room["version"],
        },
        FARM,
    )
    validate_success(create_resp, expected_status=201)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["remaining_tonnage"] == 0.0
    assert after["status"] == "EXHAUSTED"


def test_exact_tonnage_allocation_leaves_zero_remaining(api):
    """PRD §3.1: "`remaining_tonnage` ... equals the batch's `tonnage` minus
    the sum of `allocated_tonnage` over every room cycle of the batch whose
    status is anything other than `CANCELLED`."
    PRD §3.1: "If a reservation draws `remaining_tonnage` down to exactly
    zero while the batch is `SPAWNED`, the batch automatically transitions
    `SPAWNED → EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/exact_tonnage_allocation_exhausts_batch
    """
    batch, _variety = create_spawned_batch(tonnage=40.0)
    room = get_success_data(api.create_room(
        {"room_code": "R1", "capacity_tonnes": 50.0}, FARM,
    ))
    assert batch["remaining_tonnage"] == 40.0
    assert batch["status"] == "SPAWNED"

    create_resp = api.create_room_cycle(
        {
            "room_id": room["id"], "batch_id": batch["id"],
            "allocated_tonnage": 40.0,
            "planned_start": "2026-05-03T00:00:00Z",
            "planned_end": "2026-06-14T00:00:00Z",
            "expected_room_version": room["version"],
        },
        FARM,
    )
    validate_success(create_resp, expected_status=201)
    after = get_success_data(api.get_substrate_batch(batch["id"], ANY))
    assert after["remaining_tonnage"] == 0.0, "exact allocation must zero remaining_tonnage"
    assert after["status"] == "EXHAUSTED", "exact-zero reservation auto-exhausts the batch"
