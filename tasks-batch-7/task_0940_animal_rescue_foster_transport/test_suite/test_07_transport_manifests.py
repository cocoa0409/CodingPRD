"""Transport manifests: crate and weight axes, litter grouping and driver intervals."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_leg_crate_units_conserved,
    assert_manifest_entry,
    assert_same_instant,
    assert_transport_leg,
    add_leg,
    leg_version,
    manifest_animal,
    new_animal,
    new_driver,
    new_litter,
    new_organization,
    new_run,
    set_clock,
    setup_relay_run,
    setup_run_with_leg,
    take_into_custody,
    transport_leg_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


# --------------------------------------------------------------------------
# Driver interval occupancy with the trailing turnaround buffer
# --------------------------------------------------------------------------
def test_a_candidate_leg_inside_the_turnaround_buffer_is_rejected(api):
    """PRD 3.6: "Every existing leg of the same driver whose `status` is `SCHEDULED` or
    `DEPARTED` occupies the half-open interval from its own `scheduled_depart_at` up to
    but not including its `scheduled_arrive_at` **advanced by 60 minutes** — the buffer
    is appended to the end of the existing leg only, never to its start and never to
    the candidate."
    PRD 3.6: "Two intervals overlap when each one starts strictly before the other
    ends. A candidate that ends exactly when an existing leg begins is therefore
    accepted, and a candidate that begins exactly 60 minutes after an existing leg's
    scheduled arrival is accepted, while one beginning 59 minutes after is rejected
    with `ERR_DRIVER_LEG_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/driver_leg_exclusive_interval_with_trailing_turnaround_buffer
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    run = new_run(api, org["id"], run_type="RELAY", destination_hub_code="HUB-C")
    leg1 = add_leg(
        api, run["id"], driver["id"], sequence_no=1,
        scheduled_depart_at="2026-05-05T08:00:00Z",
        scheduled_arrive_at="2026-05-05T12:00:00Z",
        crate_capacity_units=8, weight_capacity_lb=400.0, species_policy="ANY",
    )

    validate_error(
        api.create_transport_leg(
            run["id"],
            transport_leg_payload(
                driver["id"], sequence_no=2, origin_hub_code="HUB-B",
                destination_hub_code="HUB-C",
                scheduled_depart_at="2026-05-05T12:59:00Z",
                scheduled_arrive_at="2026-05-05T16:00:00Z",
                crate_capacity_units=8, weight_capacity_lb=400.0, species_policy="ANY",
            ),
            DISPATCH,
        ),
        ApiErrorId.ERR_DRIVER_LEG_OVERLAP.value,
        409,
    )
    assert validate_success(api.get_transport_leg(leg1["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"


def test_a_candidate_leg_exactly_at_the_buffer_boundary_is_accepted(api):
    """PRD 3.6: "Two intervals overlap when each one starts strictly before the other
    ends. A candidate that ends exactly when an existing leg begins is therefore
    accepted, and a candidate that begins exactly 60 minutes after an existing leg's
    scheduled arrival is accepted, while one beginning 59 minutes after is rejected
    with `ERR_DRIVER_LEG_OVERLAP`."
    PRD 3.6: "A leg is created in `status` `SCHEDULED` with `used_crate_units` 0,
    `used_weight_lb` 0, and `departed_at` and `arrived_at` null, and adding it
    increments the parent run's `version` by one."

    Design: Difficulty/resource_temporal_overlap/driver_leg_exclusive_interval_with_trailing_turnaround_buffer
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    run = new_run(api, org["id"], run_type="RELAY", destination_hub_code="HUB-C")
    leg1 = add_leg(
        api, run["id"], driver["id"], sequence_no=1,
        scheduled_depart_at="2026-05-05T08:00:00Z",
        scheduled_arrive_at="2026-05-05T12:00:00Z",
        crate_capacity_units=8, weight_capacity_lb=400.0, species_policy="ANY",
    )

    leg2 = validate_success(
        api.create_transport_leg(
            run["id"],
            transport_leg_payload(
                driver["id"], sequence_no=2, origin_hub_code="HUB-B",
                destination_hub_code="HUB-C",
                scheduled_depart_at="2026-05-05T13:00:00Z",
                scheduled_arrive_at="2026-05-05T16:00:00Z",
                crate_capacity_units=8, weight_capacity_lb=400.0, species_policy="ANY",
            ),
            DISPATCH,
        ),
        201,
    )
    assert_transport_leg(leg2)
    assert leg2["status"] == "SCHEDULED"
    assert leg2["sequence_no"] == 2
    assert leg2["used_crate_units"] == 0
    assert leg2["departed_at"] is None
    assert_same_instant(
        leg2["scheduled_depart_at"], "2026-05-05T13:00:00Z", "scheduled_depart_at"
    )
    assert validate_success(api.get_transport_leg(leg1["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"


# --------------------------------------------------------------------------
# Litter grouping pre-empts the crate capacity constraint
# --------------------------------------------------------------------------
def _grouped_litter_versus_full_leg(api):
    """A GROUPED litter with two puppies, one anchored on leg A, plus a LARGE dog
    filling leg B's three crate units exactly."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    litter = new_litter(api, "Maple litter")
    pup1 = new_animal(api, org["id"], name="Pup1", size_class="SMALL", weight_lb=8.0,
                      date_of_birth="2026-03-01T00:00:00Z", litter_id=litter["id"])
    pup2 = new_animal(api, org["id"], name="Pup2", size_class="SMALL", weight_lb=8.0,
                      date_of_birth="2026-03-01T00:00:00Z", litter_id=litter["id"])
    big = new_animal(api, org["id"], name="BigDog", size_class="LARGE", weight_lb=70.0,
                     date_of_birth="2021-01-01T00:00:00Z")
    for animal in (pup1, pup2, big):
        take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    relay = setup_relay_run(
        api, org["id"], driver=driver,
        leg1_overrides={"crate_capacity_units": 5, "weight_capacity_lb": 500.0,
                        "species_policy": "DOGS_ONLY"},
        leg2_overrides={"crate_capacity_units": 3, "weight_capacity_lb": 500.0,
                        "species_policy": "DOGS_ONLY"},
    )
    anchor = manifest_animal(api, relay["leg1"]["id"], pup1["id"])
    manifest_animal(api, relay["leg2"]["id"], big["id"])
    return {
        "org": org, "litter": litter, "pup1": pup1, "pup2": pup2, "big": big,
        "leg_a": relay["leg1"], "leg_b": relay["leg2"], "anchor": anchor,
    }


def test_grouped_littermates_may_not_be_split_across_legs(api):
    """PRD 3.6: "Separately, **littermate grouping** is enforced across the whole
    network: when the candidate belongs to a litter whose `transport_basis` is still
    `GROUPED`, no littermate may already sit on a *different* leg of any run with
    `status` `ASSIGNED` or `LOADED`, and an attempt to split them that way is refused
    with `ERR_LITTER_SPLIT_NOT_APPROVED`."
    PRD 3.6: "An animal belonging to a `GROUPED` litter is billed differently: the
    first such littermate to land on a given leg — meaning no other entry for that
    litter already sits on that leg with `status` `ASSIGNED`, `LOADED` or `DELIVERED` —
    is the **anchor**, carrying `is_litter_anchor` true and a flat 2 crate units for
    the whole litter, and every subsequent littermate on the same leg carries
    `is_litter_anchor` false and **zero** crate units."

    Design: Difficulty/priority_pair_validation_conflict/litter_split_referential_preempts_crate_capacity_constraint
    """
    scenario = _grouped_litter_versus_full_leg(api)
    assert scenario["anchor"]["crate_units"] == 2
    assert scenario["anchor"]["is_litter_anchor"] is True

    leg_b = validate_success(api.get_transport_leg(scenario["leg_b"]["id"], DISPATCH))
    assert leg_b["used_crate_units"] == 3, "the LARGE dog fills leg B exactly"

    validate_error(
        api.create_manifest_entry(
            scenario["leg_b"]["id"],
            {"animal_id": scenario["pup2"]["id"], "expected_leg_version": leg_b["version"]},
            DISPATCH,
        ),
        ApiErrorId.ERR_LITTER_SPLIT_NOT_APPROVED.value,
        409,
    )


def test_after_split_approval_the_same_add_reports_the_crate_capacity(api):
    """PRD 3.1: "Under `GROUPED` the whole litter must travel together and is billed a
    flat crate cost; a `TransportDispatcher` or `PlatformAdmin` may grant split
    approval, supplying an `approved_reason`, which moves `transport_basis` to
    `SPLIT_APPROVED`, stamps `split_approved_at` with the current clock instant, and
    increments the litter's `version` by one."
    PRD 3.6: "A manifest add is accepted only when `used_crate_units` plus the
    candidate's crate units is at most `crate_capacity_units` — otherwise
    `ERR_LEG_CRATE_CAPACITY_EXCEEDED` — and only when `used_weight_lb` plus the
    candidate's `weight_lb` is at most `weight_capacity_lb` — otherwise
    `ERR_LEG_WEIGHT_CAPACITY_EXCEEDED`."
    PRD 3.6: "On the ladder the species check sits above the litter check, which sits
    above the two capacity checks."

    Once the litter is split-approved the puppy is billed by its own SMALL size class
    at 1 crate unit, which would take leg B from 3 to 4 against a capacity of 3.

    Design: Difficulty/priority_pair_validation_conflict/litter_split_referential_preempts_crate_capacity_constraint
    """
    scenario = _grouped_litter_versus_full_leg(api)

    approved = validate_success(
        api.approve_litter_split(
            scenario["litter"]["id"],
            {"approved_reason": "medical separation of littermates"},
            DISPATCH,
        )
    )
    assert approved["transport_basis"] == "SPLIT_APPROVED"

    validate_error(
        api.create_manifest_entry(
            scenario["leg_b"]["id"],
            {"animal_id": scenario["pup2"]["id"],
             "expected_leg_version": leg_version(api, scenario["leg_b"]["id"])},
            DISPATCH,
        ),
        ApiErrorId.ERR_LEG_CRATE_CAPACITY_EXCEEDED.value,
        409,
    )
    assert validate_success(api.get_transport_leg(scenario["leg_b"]["id"], DISPATCH))[
        "used_crate_units"
    ] == 3


# --------------------------------------------------------------------------
# Crate arithmetic, weight arithmetic and the species policy
# --------------------------------------------------------------------------
def test_grouped_littermates_cost_one_anchor_while_split_ones_pay_per_head(api):
    """PRD 3.6: "An animal with no `litter_id`, or one whose litter has been
    split-approved, is billed by its own `size_class`: 1 crate unit for `SMALL`, 2 for
    `MEDIUM`, 3 for `LARGE`, with `is_litter_anchor` false."
    PRD 3.6: "Four small littermates travelling grouped therefore cost 2 crate units in
    total, where the same four travelling split-approved would cost 4."

    Design: Corner/calculations/litter_grouped_versus_split_approved_crate_unit_cost
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    litter = new_litter(api, "Cedar litter")
    pups = []
    for name in ("C1", "C2", "C3", "C4"):
        pup = new_animal(api, org["id"], name=name, size_class="SMALL", weight_lb=6.0,
                         date_of_birth="2026-03-01T00:00:00Z", litter_id=litter["id"])
        take_into_custody(api, pup["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
        pups.append(pup)

    relay = setup_relay_run(
        api, org["id"], driver=driver,
        leg1_overrides={"crate_capacity_units": 10, "species_policy": "DOGS_ONLY"},
        leg2_overrides={"crate_capacity_units": 10, "species_policy": "DOGS_ONLY"},
    )

    first = manifest_animal(api, relay["leg1"]["id"], pups[0]["id"])
    second = manifest_animal(api, relay["leg1"]["id"], pups[1]["id"])
    assert_manifest_entry(first)
    assert first["crate_units"] == 2
    assert first["is_litter_anchor"] is True
    assert second["crate_units"] == 0
    assert second["is_litter_anchor"] is False

    leg_a = validate_success(api.get_transport_leg(relay["leg1"]["id"], DISPATCH))
    assert leg_a["used_crate_units"] == 2

    approved = validate_success(
        api.approve_litter_split(
            litter["id"], {"approved_reason": "two adopters in different states"}, DISPATCH
        )
    )
    assert approved["transport_basis"] == "SPLIT_APPROVED"

    third = manifest_animal(api, relay["leg2"]["id"], pups[2]["id"])
    fourth = manifest_animal(api, relay["leg2"]["id"], pups[3]["id"])
    assert third["crate_units"] == 1
    assert third["is_litter_anchor"] is False
    assert fourth["crate_units"] == 1

    leg_b = validate_success(api.get_transport_leg(relay["leg2"]["id"], DISPATCH))
    assert leg_b["used_crate_units"] == 2
    entries, _ = validate_paginated(
        api.list_manifest_entries(DISPATCH, {"transport_leg_id": relay["leg2"]["id"]})
    )
    assert_leg_crate_units_conserved(leg_b, entries)


def test_weight_capacity_rejects_while_crate_units_are_still_free(api):
    """PRD 3.6: "Weight is counted quite differently, and the difference is the point:
    `used_weight_lb` is the sum of the `weight_lb` of every animal on the leg with
    `status` `ASSIGNED`, `LOADED` or `DELIVERED`, **including** grouped littermates
    whose crate contribution is zero."
    PRD 3.6: "The crate axis and the weight axis therefore fail independently."
    PRD 3.6: "A manifest add is accepted only when `used_crate_units` plus the
    candidate's crate units is at most `crate_capacity_units` — otherwise
    `ERR_LEG_CRATE_CAPACITY_EXCEEDED` — and only when `used_weight_lb` plus the
    candidate's `weight_lb` is at most `weight_capacity_lb` — otherwise
    `ERR_LEG_WEIGHT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/leg_weight_capacity_rejects_independently_of_crate_capacity
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    heavy_one = new_animal(api, org["id"], name="Heavy1", size_class="LARGE", weight_lb=80.0,
                           date_of_birth="2021-01-01T00:00:00Z")
    heavy_two = new_animal(api, org["id"], name="Heavy2", size_class="LARGE", weight_lb=80.0,
                           date_of_birth="2021-01-01T00:00:00Z")
    take_into_custody(api, heavy_one["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, heavy_two["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    scenario = setup_run_with_leg(
        api, org["id"], driver=driver,
        leg_overrides={"crate_capacity_units": 20, "weight_capacity_lb": 150.0,
                       "species_policy": "DOGS_ONLY"},
    )
    first = manifest_animal(api, scenario["leg"]["id"], heavy_one["id"])
    assert first["crate_units"] == 3

    leg = validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))
    assert leg["used_crate_units"] == 3
    assert leg["used_weight_lb"] == 80.0

    validate_error(
        api.create_manifest_entry(
            scenario["leg"]["id"],
            {"animal_id": heavy_two["id"], "expected_leg_version": leg["version"]},
            DISPATCH,
        ),
        ApiErrorId.ERR_LEG_WEIGHT_CAPACITY_EXCEEDED.value,
        409,
    )
    assert validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))[
        "used_crate_units"
    ] == 3


def test_species_policy_refuses_a_cat_and_a_second_reactive_animal(api):
    """PRD 3.6: "Under `DOGS_ONLY` every animal in that set must be a `DOG`; under
    `CATS_ONLY` every animal must be a `CAT`; under `MIXED_SEGREGATED` the add is
    refused if any `REACTIVE` animal would share the leg with an animal of a different
    species; and under `ANY` the add is refused if the resulting manifest would carry
    two or more `REACTIVE` animals. Any refusal is `ERR_SPECIES_INCOMPATIBLE_LEG`."

    Design: Corner/validations/leg_species_policy_rejects_cat_and_second_reactive_animal
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    cat = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                     weight_lb=9.0, date_of_birth="2023-01-01T00:00:00Z")
    r1 = new_animal(api, org["id"], name="R1", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z", temperament="REACTIVE")
    r2 = new_animal(api, org["id"], name="R2", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z", temperament="REACTIVE")
    for animal in (cat, r1, r2):
        take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    relay = setup_relay_run(
        api, org["id"], driver=driver,
        leg1_overrides={"crate_capacity_units": 10, "species_policy": "DOGS_ONLY"},
        leg2_overrides={"crate_capacity_units": 10, "species_policy": "ANY"},
    )

    validate_error(
        api.create_manifest_entry(
            relay["leg1"]["id"],
            {"animal_id": cat["id"], "expected_leg_version": relay["leg1"]["version"]},
            DISPATCH,
        ),
        ApiErrorId.ERR_SPECIES_INCOMPATIBLE_LEG.value,
        422,
    )

    first_reactive = manifest_animal(api, relay["leg2"]["id"], r1["id"])
    assert first_reactive["status"] == "ASSIGNED"

    validate_error(
        api.create_manifest_entry(
            relay["leg2"]["id"],
            {"animal_id": r2["id"],
             "expected_leg_version": leg_version(api, relay["leg2"]["id"])},
            DISPATCH,
        ),
        ApiErrorId.ERR_SPECIES_INCOMPATIBLE_LEG.value,
        422,
    )
    assert validate_success(api.get_transport_leg(relay["leg2"]["id"], DISPATCH))[
        "used_crate_units"
    ] == 1


def test_bumping_an_assigned_entry_frees_the_leg_capacity(api):
    """PRD 3.6: "An assigned animal may be bumped back off a leg by a dispatcher, moving
    the entry `ASSIGNED → BUMPED`, lowering the leg's `used_crate_units` and
    `used_weight_lb` by that entry's contribution, and incrementing both the entry's
    `version` and the leg's `version` by one. `BUMPED` is terminal."
    PRD 2.10: "**Crate units.** For every transport leg, `used_crate_units` equals the
    sum of `crate_units` over that leg's manifest entries whose status is `ASSIGNED`,
    `LOADED` or `DELIVERED`; `BUMPED` and `STRANDED` entries are excluded."

    Design: Corner/state_machines/manifest_entry_delete_bumps_and_frees_leg_capacity
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    big = new_animal(api, org["id"], name="BigDog", size_class="LARGE", weight_lb=70.0,
                     date_of_birth="2021-01-01T00:00:00Z")
    take_into_custody(api, big["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    scenario = setup_run_with_leg(
        api, org["id"], driver=driver,
        leg_overrides={"crate_capacity_units": 6, "weight_capacity_lb": 400.0},
    )
    entry = manifest_animal(api, scenario["leg"]["id"], big["id"])
    assert entry["crate_units"] == 3

    before = validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))
    assert before["used_crate_units"] == 3
    assert before["used_weight_lb"] == 70.0

    bumped = validate_success(api.bump_manifest_entry(entry["id"], DISPATCH))
    assert bumped["status"] == "BUMPED"

    after = validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))
    assert after["used_crate_units"] == 0
    assert after["used_weight_lb"] == 0.0
    entries, _ = validate_paginated(
        api.list_manifest_entries(DISPATCH, {"transport_leg_id": scenario["leg"]["id"]})
    )
    assert_leg_crate_units_conserved(after, entries)


def test_a_stale_leg_version_is_rejected_on_a_manifest_add(api):
    """PRD 2.7: "Manifesting an animal onto a transport leg requires
    `expected_leg_version`, carrying the caller's last observed `version` of the
    `TransportLeg`."
    PRD 2.7: "If the value does not equal the parent's current `version` at the moment
    the request is evaluated, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)
    at rung 17, and nothing is mutated."
    PRD 3.6: "On success the entry is created in `status` `ASSIGNED` with
    `stranded_at_hub_code` null, both leg utilisation figures rise, and the leg's
    `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_stale_leg_version_rejected_on_manifest_add
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    d1 = new_animal(api, org["id"], name="D1", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z")
    d2 = new_animal(api, org["id"], name="D2", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, d1["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, d2["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    scenario = setup_run_with_leg(
        api, org["id"], driver=driver,
        leg_overrides={"crate_capacity_units": 10, "species_policy": "DOGS_ONLY"},
    )
    stale_version = scenario["leg"]["version"]

    first = validate_success(
        api.create_manifest_entry(
            scenario["leg"]["id"],
            {"animal_id": d1["id"], "expected_leg_version": stale_version}, DISPATCH,
        ),
        201,
    )
    assert first["status"] == "ASSIGNED"
    assert first["stranded_at_hub_code"] is None

    validate_error(
        api.create_manifest_entry(
            scenario["leg"]["id"],
            {"animal_id": d2["id"], "expected_leg_version": stale_version}, DISPATCH,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )
    assert validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))[
        "used_crate_units"
    ] == 1


def test_aborting_an_unstarted_run_cancels_it_and_bumps_its_manifest(api):
    """PRD 3.6: "A run still `PLANNED` moves to `CANCELLED`: every `SCHEDULED` leg moves
    to `INVALIDATED` and every `ASSIGNED` entry moves to `BUMPED`, and because the run
    never started, no partner slots were ever drawn and none are returned."
    PRD 3.6: "A new run starts in `status` `PLANNED` with `slots_drawn` 0, `started_at`
    null and `aborted_at` null."

    Design: Corner/state_machines/run_cancel_before_start_invalidates_legs_and_bumps_entries
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2023-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    scenario = setup_run_with_leg(
        api, org["id"], driver=driver,
        run_overrides={"purpose": "INTAKE_TRANSPORT"},
        leg_overrides={"crate_capacity_units": 6, "weight_capacity_lb": 400.0},
    )
    entry = manifest_animal(api, scenario["leg"]["id"], animal["id"])
    assert entry["crate_units"] == 2, "a MEDIUM animal is billed 2 crate units"

    cancelled = validate_success(
        api.abort_transport_run(scenario["run"]["id"], DISPATCH, {"reason": "donor pull-out"})
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["slots_drawn"] == 0

    assert validate_success(api.get_transport_leg(scenario["leg"]["id"], DISPATCH))[
        "status"
    ] == "INVALIDATED"
    assert validate_success(api.get_manifest_entry(entry["id"], DISPATCH))[
        "status"
    ] == "BUMPED"
    assert validate_success(api.get_animal(animal["id"], ADMIN))[
        "lifecycle_status"
    ] == "IN_CUSTODY"


def test_a_leg_cannot_leapfrog_a_lower_sequence_leg(api):
    """PRD 3.6: "And every leg of the same run with a lower `sequence_no` must already
    have reached `ARRIVED`, failing which the answer is `ERR_LEG_SEQUENCE_VIOLATION` —
    this is the relay handoff, and it means legs strictly cannot leapfrog one another."
    PRD 3.6: "**Starting** a run moves it `PLANNED → IN_PROGRESS`, stamps `started_at`
    with the current clock instant and increments the run's `version` by one."

    Design: Corner/state_machines/leg_departure_out_of_sequence_returns_sequence_violation
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    driver = new_driver(api)
    relay = setup_relay_run(
        api, org["id"], driver=driver,
        leg1_overrides={"crate_capacity_units": 6, "weight_capacity_lb": 400.0},
        leg2_overrides={"crate_capacity_units": 6, "weight_capacity_lb": 400.0},
    )
    started = validate_success(api.start_transport_run(relay["run"]["id"], DISPATCH))
    assert started["status"] == "IN_PROGRESS"

    set_clock(api, "2026-05-05T14:00:00Z")
    validate_error(
        api.depart_transport_leg(relay["leg2"]["id"], DISPATCH),
        ApiErrorId.ERR_LEG_SEQUENCE_VIOLATION.value,
        409,
    )
    assert validate_success(api.get_transport_leg(relay["leg2"]["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"
    assert validate_success(api.get_transport_leg(relay["leg1"]["id"], DISPATCH))[
        "status"
    ] == "SCHEDULED"
