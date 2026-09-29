"""The storage yard: admission, occupancy recomputation, restack and stale slots."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exact_sum,
    assert_piece_dimensions_status,
    assert_slot_occupancy,
    assert_yard_placement,
    create_yard_placement_payload,
    create_yard_slot,
    list_piece_placements,
    place_piece,
    read_piece,
    read_yard_placement,
    read_yard_slot,
    setup_production_line,
    validate_error,
    validate_paginated,
    validate_success,
)

FOREMAN = TEST_USERS["yard_foreman_headers"]


def test_placement_and_restack_pull_conserve_the_slot_weight(api):
    """PRD §2.11: "pulling a placement with a restack reason must return the
    slot's `occupied_weight_lb` and `stacked_count` to precisely their
    pre-placement values"
    PRD §3.7: "The slot is then recomputed from its active placements alone:
    `occupied_weight_lb` becomes the exact sum of `weight_lb` over the pieces of
    the slot's `ACTIVE` placements, with no rounding whatsoever; `stacked_count`
    becomes the number of those active placements; and the slot's `status`
    becomes `EMPTY` when `stacked_count` is 0, `FULL` when `stacked_count`
    equals `max_stack_count` or `occupied_weight_lb` equals
    `capacity_weight_lb`, and `PARTIAL` in every other case — except that a slot
    seeded `BLOCKED` stays `BLOCKED` forever and is never recomputed into
    another value."

    Design: Difficulty/compensating_invariant/yard_stored_weight_returns_to_baseline_after_restack_pull
    """
    ctx = setup_production_line(stage="stripped", with_slot=True)
    slot_id = ctx["slot"]["id"]
    piece = ctx["pieces"][0]
    baseline = read_yard_slot(slot_id)
    assert baseline["occupied_weight_lb"] == 0

    placement = place_piece(piece["id"], slot_id, stack_level=1)
    midpoint = read_yard_slot(slot_id)
    assert_slot_occupancy(midpoint, 48200, 1, "PARTIAL")
    assert read_piece(piece["id"])["production_status"] == "YARDED"

    validate_success(
        api.pull_yard_placement(placement["id"], {"release_reason": "RESTACK"}, FOREMAN)
    )

    restored = read_yard_slot(slot_id)
    assert_exact_sum(
        restored["occupied_weight_lb"],
        baseline["occupied_weight_lb"],
        "yard_slot.occupied_weight_lb",
    )
    assert_slot_occupancy(restored, 0, 0, "EMPTY")


def test_restack_pull_returns_the_piece_to_stripped_without_touching_qc(api):
    """PRD §3.7: "With a `RESTACK` reason the piece moves `production_status`
    `YARDED → STRIPPED`, returning the slot's occupancy to exactly its
    pre-placement value and making `STRIPPED → YARDED → STRIPPED` the yard's
    restack loop; the piece may then be placed again, in the same slot or
    another."
    PRD §3.7: "The `YardForeman` supplies a `release_reason` of `LOAD`, `SCRAP`
    or `RESTACK`; the placement's `released_at` is stamped from the logical clock
    and the `release_reason` recorded."

    Design: Difficulty/compensating_invariant/yard_stored_weight_returns_to_baseline_after_restack_pull
    """
    ctx = setup_production_line(stage="stripped", with_slot=True)
    piece = ctx["pieces"][0]
    placement = place_piece(piece["id"], ctx["slot"]["id"], stack_level=1)

    pulled = validate_success(
        api.pull_yard_placement(placement["id"], {"release_reason": "RESTACK"}, FOREMAN)
    )

    assert_yard_placement(pulled)
    assert pulled["status"] == "RELEASED"
    assert pulled["release_reason"] == "RESTACK"
    assert pulled["released_at"].startswith("2026-08-03T06:00:00"), (
        f"released_at is stamped from the logical clock, got {pulled['released_at']}"
    )
    assert_piece_dimensions_status(read_piece(piece["id"]), "STRIPPED", "CLEARED", None)


def test_slot_admission_boundaries_and_status_recompute(api):
    """PRD §3.7: "If the slot's current `occupied_weight_lb` plus the piece's
    `weight_lb` would exceed `capacity_weight_lb`, the placement is rejected with
    `ERR_YARD_SLOT_CAPACITY_EXCEEDED`. If the slot's current `stacked_count` plus
    one would exceed `max_stack_count`, the placement is rejected with
    `ERR_YARD_STACK_LIMIT_EXCEEDED`. Both comparisons are strictly greater, so a
    placement that exactly fills a slot by weight or by count is admitted and
    simply leaves the slot full."
    PRD §3.7: "`BLOCKED` is absorbing: it never changes afterwards, and a
    placement targeting a blocked slot is refused with
    `ERR_PLANT_RESOURCE_UNAVAILABLE`."
    PRD §3.7: "A pull issued against a placement that is already `RELEASED` is
    refused with `ERR_YARD_PLACEMENT_INVALID_STATE`."

    Design: Corner/calculations/yard_slot_occupancy_boundaries_and_status_recompute
    """
    ctx = setup_production_line(
        stage="stripped",
        piece_specs=[{}, {}, {}],
        with_slot=True,
        slot_overrides={"slot_code": "S1", "capacity_weight_lb": 48200, "max_stack_count": 3},
    )
    exact_fit_slot = ctx["slot"]
    one_deep_slot = create_yard_slot(
        slot_code="S2", capacity_weight_lb=200000, max_stack_count=1
    )
    blocked_slot = create_yard_slot(
        slot_code="S3", bay_code="B", capacity_weight_lb=200000, max_stack_count=5,
        status="BLOCKED",
    )
    first, second, third = ctx["pieces"]

    place_piece(first["id"], exact_fit_slot["id"], stack_level=1)
    filled = read_yard_slot(exact_fit_slot["id"])
    assert_slot_occupancy(filled, 48200, 1, "FULL")

    over_weight = api.create_yard_placement(
        create_yard_placement_payload(
            second["id"], exact_fit_slot["id"], filled["version"], stack_level=2
        ),
        FOREMAN,
    )
    validate_error(over_weight, ApiErrorId.ERR_YARD_SLOT_CAPACITY_EXCEEDED.value, 422)

    stacked = place_piece(second["id"], one_deep_slot["id"], stack_level=1)
    one_deep = read_yard_slot(one_deep_slot["id"])
    over_stack = api.create_yard_placement(
        create_yard_placement_payload(
            third["id"], one_deep_slot["id"], one_deep["version"], stack_level=2
        ),
        FOREMAN,
    )
    validate_error(over_stack, ApiErrorId.ERR_YARD_STACK_LIMIT_EXCEEDED.value, 422)

    blocked = read_yard_slot(blocked_slot["id"])
    into_blocked = api.create_yard_placement(
        create_yard_placement_payload(third["id"], blocked_slot["id"], blocked["version"]),
        FOREMAN,
    )
    validate_error(into_blocked, ApiErrorId.ERR_PLANT_RESOURCE_UNAVAILABLE.value, 409)

    validate_success(
        api.pull_yard_placement(stacked["id"], {"release_reason": "RESTACK"}, FOREMAN)
    )
    pull_again = api.pull_yard_placement(stacked["id"], {"release_reason": "RESTACK"}, FOREMAN)
    validate_error(pull_again, ApiErrorId.ERR_YARD_PLACEMENT_INVALID_STATE.value, 409)

    assert_slot_occupancy(read_yard_slot(one_deep_slot["id"]), 0, 0, "EMPTY")
    assert_slot_occupancy(read_yard_slot(blocked_slot["id"]), 0, 0, "BLOCKED")
    assert read_piece(second["id"])["production_status"] == "STRIPPED"
    assert read_piece(third["id"])["production_status"] == "STRIPPED"

    active, active_meta = validate_paginated(
        api.list_yard_slot_placements(exact_fit_slot["id"], FOREMAN, {"status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 1
    assert active[0]["status"] == "ACTIVE"

    history, history_meta = validate_paginated(
        api.list_piece_yard_placements(second["id"], FOREMAN)
    )
    assert history_meta["total_count"] == 1
    assert history[0]["status"] == "RELEASED"
    assert history[0]["release_reason"] == "RESTACK"


def test_stale_slot_version_rejects_the_second_placement(api):
    """PRD §2.9: "A `POST /yard-placements` request must carry
    `expected_yard_slot_version`, a required field, holding the client's last
    observed `version` of the `YardSlot` named by `yard_slot_id`."
    PRD §2.9: "If `expected_yard_slot_version` does not equal the slot's current
    `version`, the request is rejected with `ERR_STALE_YARD_SLOT_VERSION` and
    HTTP 412 Precondition Failed. On success the operation increments the slot's
    `version` by 1."

    Design: Corner/cross_cutting_layers/stale_yard_slot_version_rejects_a_second_placement
    """
    ctx = setup_production_line(
        stage="stripped",
        piece_specs=[{}, {}],
        with_slot=True,
        slot_overrides={"capacity_weight_lb": 200000, "max_stack_count": 3},
    )
    slot_id = ctx["slot"]["id"]
    first, second = ctx["pieces"]
    version_before = read_yard_slot(slot_id)["version"]

    first_placement = validate_success(
        api.create_yard_placement(
            create_yard_placement_payload(first["id"], slot_id, version_before, stack_level=1),
            FOREMAN,
        ),
        201,
    )

    stale = api.create_yard_placement(
        create_yard_placement_payload(second["id"], slot_id, version_before, stack_level=2),
        FOREMAN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_YARD_SLOT_VERSION.value, 412)

    after_reject = read_yard_slot(slot_id)
    assert after_reject["version"] == version_before + 1, (
        "the first placement incremented the slot version by exactly 1"
    )
    assert_slot_occupancy(after_reject, 48200, 1, "PARTIAL")

    second_placement = validate_success(
        api.create_yard_placement(
            create_yard_placement_payload(
                second["id"], slot_id, after_reject["version"], stack_level=2
            ),
            FOREMAN,
        ),
        201,
    )

    assert_slot_occupancy(read_yard_slot(slot_id), 96400, 2, "PARTIAL")
    assert read_yard_placement(first["id"], first_placement["id"])["status"] == "ACTIVE"
    assert read_yard_placement(second["id"], second_placement["id"])["status"] == "ACTIVE"
    assert read_piece(second["id"])["production_status"] == "YARDED"
    assert len(list_piece_placements(second["id"])) == 1
