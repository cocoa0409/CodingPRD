"""Adult trap surveillance chain of custody and the arbovirus laboratory."""

import test_helpers as fx
from test_helpers import (
    LAB,
    MANAGER,
    ApiErrorId,
    validate_error,
    validate_success,
)


def test_second_submit_on_submitted_collection_rejected(api):
    """PRD §3.3: "It enters the district's evidence base only when the logging
    technician submits it, advancing `LOGGED → SUBMITTED`."
    PRD §2.11: "**Transition existence** — the requested transition exists from
    the entity's current state, including terminal-state lockdown, under which no
    action whatsoever is accepted from a terminal state."

    Design: Corner/state_machines/corner_submit_trap_collection_twice_returns_invalid_transition
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=10
    )

    response = api.transition_trap_collection(
        collection["id"], {"action": "SUBMIT"}, fx.make_field_tech_headers(tech["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)
    assert fx.read_collection(collection["id"])["status"] == "SUBMITTED"


def test_collection_older_than_seven_days_cannot_be_submitted(api):
    """PRD §3.3: "And the collection must still be fresh: the difference between
    the logical clock's calendar date and `collection_date` may be at most 7 days,
    inclusive at the boundary, so a collection exactly 7 days old still submits
    while one older than that is refused with `ERR_COLLECTION_WINDOW_EXPIRED`
    (HTTP 422)."

    Design: Corner/state_machines/corner_collection_submit_after_seven_days_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    stale = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-24", trap_nights=1, female_count=10
    )
    edge = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-25", trap_nights=1, female_count=12
    )

    too_old = api.transition_trap_collection(
        stale["id"], {"action": "SUBMIT"}, fx.make_field_tech_headers(tech["id"])
    )
    validate_error(too_old, ApiErrorId.ERR_COLLECTION_WINDOW_EXPIRED.value, 422)

    accepted = validate_success(
        api.transition_trap_collection(
            edge["id"], {"action": "SUBMIT"}, fx.make_field_tech_headers(tech["id"])
        )
    )
    assert accepted["status"] == "SUBMITTED"
    assert fx.read_collection(stale["id"])["status"] == "LOGGED"


def test_void_of_submitted_collection_with_pool_rejected(api):
    """PRD §3.3: "Voiding is available from `LOGGED`, where it succeeds
    unconditionally and simply excludes the collection from the abundance index
    permanently, and from `SUBMITTED`, where it succeeds only if no laboratory
    pool has ever been created from the collection; a `SUBMITTED` collection that
    already has at least one pool is refused with `ERR_COLLECTION_HAS_POOLS`
    (HTTP 409), because voiding it would orphan laboratory work."

    Design: Corner/state_machines/corner_void_submitted_collection_with_pools_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    pooled = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=10
    )
    fx.create_pool(pooled["id"], 10)
    logged_only = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-29", trap_nights=1, female_count=8
    )

    blocked = api.transition_trap_collection(
        pooled["id"], {"action": "VOID", "void_reason": "Mislabelled tube"}, MANAGER
    )
    validate_error(blocked, ApiErrorId.ERR_COLLECTION_HAS_POOLS.value, 409)

    voided = validate_success(
        api.transition_trap_collection(
            logged_only["id"], {"action": "VOID", "void_reason": "Trap knocked over"}, MANAGER
        )
    )
    assert voided["status"] == "VOIDED"
    assert fx.read_collection(pooled["id"])["status"] == "POOLED"


def test_discarded_pool_rejects_further_actions(api):
    """PRD §3.4: "The alternative exit from `INVALID` is to discard the pool,
    advancing `INVALID → DISCARDED`, which is terminal. Discarding subtracts the
    pool's `pool_size` back out of the parent collection's
    `pooled_mosquito_count` and marks every `OPEN` assessment of the area stale
    with `LAB_RESULT`."
    PRD §2.11: "**Transition existence** — the requested transition exists from
    the entity's current state, including terminal-state lockdown, under which no
    action whatsoever is accepted from a terminal state."

    Design: Corner/state_machines/corner_discarded_lab_pool_rejects_all_further_actions
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=20
    )
    pool = fx.create_pool(collection["id"], 20)
    assert pool["status"] == "CREATED"
    fx.start_pool_test(pool["id"])
    fx.record_pool_result(pool["id"], "INVALID")
    fx.discard_pool(pool["id"])

    restart = api.transition_lab_pool(pool["id"], {"action": "START_TEST"}, LAB)
    validate_error(restart, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    rediscard = api.transition_lab_pool(pool["id"], {"action": "DISCARD"}, LAB)
    validate_error(rediscard, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    assert fx.read_pool(pool["id"])["status"] == "DISCARDED"
    assert fx.read_collection(collection["id"])["pooled_mosquito_count"] == 0


def test_duplicate_collection_for_same_site_and_day_rejected(api):
    """PRD §3.3: "A trap site may hold at most one non-voided collection per
    calendar day: a second collection for the same trap site and the same
    `collection_date`, while an earlier one is still alive, is
    `ERR_DUPLICATE_RESOURCE`. Voiding the earlier one frees the slot."

    Design: Corner/validations/corner_duplicate_collection_same_site_same_day_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    first = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=10
    )

    clash = api.create_trap_collection(
        site["id"],
        {"collection_date": "2026-05-28", "trap_nights": 1, "female_count": 11,
         "species": "CULEX_PIPIENS"},
        fx.make_field_tech_headers(tech["id"]),
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    fx.void_collection(first["id"], "Sample spoiled")
    replacement = validate_success(
        api.create_trap_collection(
            site["id"],
            {"collection_date": "2026-05-28", "trap_nights": 1, "female_count": 11,
             "species": "CULEX_PIPIENS"},
            fx.make_field_tech_headers(tech["id"]),
        ),
        201,
    )

    assert fx.read_collection(first["id"])["status"] == "VOIDED"
    assert replacement["status"] == "LOGGED"
    assert replacement["female_count"] == 11


def test_unknown_pool_action_returns_invalid_action(api):
    """PRD §2.11: "**Action validity** — on a transition-driving endpoint, the
    supplied `action` is one of that entity's declared actions; otherwise
    `ERR_INVALID_ACTION`."
    PRD §3.4: "The `INVALID` state is the hinge of the laboratory's revision loop."

    Design: Corner/validations/corner_unknown_transition_action_returns_invalid_action
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=15
    )
    pool = fx.create_pool(collection["id"], 15)

    unknown = api.transition_lab_pool(pool["id"], {"action": "PUBLISH"}, LAB)
    validate_error(unknown, ApiErrorId.ERR_INVALID_ACTION.value, 422)

    illegal = api.transition_lab_pool(pool["id"], {"action": "DISCARD"}, LAB)
    validate_error(illegal, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    assert fx.read_pool(pool["id"])["status"] == "CREATED"


def test_pool_creation_blocked_while_parent_collection_logged(api):
    """PRD §3.4: "A pool may only be built from a collection whose status is
    `SUBMITTED` or `POOLED`; a collection still `LOGGED`, or one that has been
    `VOIDED`, is refused with `ERR_COLLECTION_NOT_SUBMITTED` (HTTP 409)."
    PRD §3.3: "A `LOGGED` collection is a private field note — it counts toward
    nothing."

    Design: Difficulty/cross_entity_state_dependency/lab_pool_creation_requires_submitted_parent_collection
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="BG_SENTINEL", habitat="WETLAND")
    collection = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-30", trap_nights=1,
        female_count=30, species="AEDES_ALBOPICTUS",
    )

    response = api.create_lab_pool(collection["id"], {"pool_size": 30, "assay": "RT_PCR"}, LAB)
    validate_error(response, ApiErrorId.ERR_COLLECTION_NOT_SUBMITTED.value, 409)
    assert fx.read_collection(collection["id"])["status"] == "LOGGED"
    assert fx.read_collection(collection["id"])["pooled_mosquito_count"] == 0


def test_pool_creation_after_submit_pools_collection_and_starts_testing(api):
    """PRD §3.3: "The first pool created from a `SUBMITTED` collection advances it
    `SUBMITTED → POOLED` as a system transition, and adds that pool's `pool_size`
    to `pooled_mosquito_count`."
    PRD §3.4: "Testing advances `CREATED → IN_TESTING` when the analyst starts the
    assay, and the same cross-entity gate applies here: the parent collection must
    still be `SUBMITTED` or `POOLED`, otherwise `ERR_COLLECTION_NOT_SUBMITTED`."
    PRD §3.4: "Starting a first test leaves `retest_count` at whatever it was —
    this is the first test, not a retest."

    Design: Difficulty/cross_entity_state_dependency/lab_pool_creation_requires_submitted_parent_collection
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="BG_SENTINEL", habitat="WETLAND")
    collection = fx.log_collection(
        site["id"], tech["id"], collection_date="2026-05-30", trap_nights=1,
        female_count=30, species="AEDES_ALBOPICTUS",
    )
    fx.submit_collection(collection["id"], tech["id"])

    pool = validate_success(
        api.create_lab_pool(collection["id"], {"pool_size": 30, "assay": "RT_PCR"}, LAB), 201
    )
    started = validate_success(
        api.transition_lab_pool(pool["id"], {"action": "START_TEST"}, LAB)
    )

    assert started["status"] == "IN_TESTING"
    assert started["retest_count"] == 0
    refreshed = fx.read_collection(collection["id"])
    assert refreshed["status"] == "POOLED"
    assert refreshed["pooled_mosquito_count"] == 30


def test_invalid_pool_retested_twice_increments_retest_count(api):
    """PRD §3.4: "An analyst may re-enter an invalid pool into testing, advancing
    `INVALID → IN_TESTING` and incrementing `retest_count` by 1 — the loop
    `INVALID → IN_TESTING → INVALID` may therefore run repeatedly."
    PRD §3.4: "An inconclusive assay moves the pool to `INVALID`, leaves
    `retest_count` unchanged, likewise marks every `OPEN` assessment of the area
    stale with `LAB_RESULT`, and takes the pool out of *both* infection-rate
    variants until it is retested."

    Design: Difficulty/non_linear_state_machine/lab_pool_invalid_retest_cycle_capped_at_two_retests
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=25
    )
    pool = fx.pool_in_testing(collection["id"], 25)

    invalidated = validate_success(
        api.transition_lab_pool(pool["id"], {"action": "RESULT", "result": "INVALID"}, LAB)
    )
    assert invalidated["status"] == "INVALID"
    assert invalidated["retest_count"] == 0

    first_retest = validate_success(
        api.transition_lab_pool(pool["id"], {"action": "START_TEST"}, LAB)
    )
    assert first_retest["retest_count"] == 1
    assert first_retest["status"] == "IN_TESTING"

    fx.record_pool_result(pool["id"], "INVALID")
    second_retest = validate_success(
        api.transition_lab_pool(pool["id"], {"action": "START_TEST"}, LAB)
    )
    assert second_retest["retest_count"] == 2
    assert second_retest["status"] == "IN_TESTING"


def test_third_retest_refused_with_retest_limit_exceeded(api):
    """PRD §3.4: "It is not unbounded: a pool may be retested only while
    `retest_count` is below 2, so the first and second retests are permitted and a
    third attempt, when `retest_count` has already reached 2, is refused with
    `ERR_RETEST_LIMIT_EXCEEDED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/lab_pool_invalid_retest_cycle_capped_at_two_retests
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"], trap_type="GRAVID")
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=1, female_count=25
    )
    pool = fx.pool_in_testing(collection["id"], 25)
    for _ in range(2):
        fx.record_pool_result(pool["id"], "INVALID")
        fx.start_pool_test(pool["id"])
    fx.record_pool_result(pool["id"], "INVALID")

    response = api.transition_lab_pool(pool["id"], {"action": "START_TEST"}, LAB)
    validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED.value, 409)

    final = fx.read_pool(pool["id"])
    assert final["status"] == "INVALID"
    assert final["retest_count"] == 2
    assert fx.read_collection(collection["id"])["pooled_mosquito_count"] == 25
