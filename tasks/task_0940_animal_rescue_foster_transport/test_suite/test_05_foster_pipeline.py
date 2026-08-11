"""The foster pipeline: two parallel axes, the home-check clock and capacity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_foster_application,
    assert_foster_home,
    assert_foster_placement,
    assert_same_instant,
    foster_home_version,
    foster_placement_payload,
    make_foster_parent_headers,
    new_animal,
    new_litter,
    new_organization,
    propose_placement,
    place_animal_in_home,
    set_clock,
    setup_foster_home,
    take_into_custody,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["foster_coordinator_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]


# --------------------------------------------------------------------------
# The two parallel axes on a foster application
# --------------------------------------------------------------------------
def test_suspend_resume_cycle_leaves_the_home_check_axis_untouched(api):
    """PRD 3.4: "Approving an application does not touch the home-check axis, and
    passing a home check does not touch the application axis."
    PRD 3.4: "`SUSPEND` moves `APPROVED → SUSPENDED`; `RESUME` moves `SUSPENDED →
    APPROVED`; the pair may cycle indefinitely, and each direction increments `version`
    by one."
    PRD 3.4: "An `APPROVED` application may sit at `LAPSED`, and a `SUSPENDED`
    application may sit at `PASSED`; both combinations are legitimate and both are
    queryable, since applications may be listed filtered by `person_id`,
    `foster_home_id`, `application_status` and `home_check_status` independently."

    Design: Difficulty/non_linear_state_machine/foster_application_parallel_axes_advance_independently
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    new_organization(api)
    scenario = setup_foster_home(
        api,
        home_overrides={"max_headcount": 6, "dog_slot_capacity": 4, "cat_slot_capacity": 0,
                        "accepts_cats": False},
        checked_at="2026-05-02T00:00:00Z",
        person_overrides={"housing_type": "HOUSE", "has_fenced_yard": True},
    )
    application = scenario["application"]

    set_clock(api, "2026-05-03T00:00:00Z")
    suspended = validate_success(
        api.change_foster_application_status(application["id"], {"action": "SUSPEND"}, COORD)
    )
    assert_foster_application(suspended)
    assert suspended["application_status"] == "SUSPENDED"
    assert suspended["home_check_status"] == "PASSED", (
        "suspending on the application axis must not disturb the home-check axis"
    )

    resumed = validate_success(
        api.change_foster_application_status(application["id"], {"action": "RESUME"}, COORD)
    )
    assert resumed["application_status"] == "APPROVED"
    assert resumed["home_check_status"] == "PASSED"


def test_home_check_lapse_leaves_the_application_axis_approved(api):
    """PRD 3.4: "A `PASS` is accepted from `NOT_SCHEDULED`, from `FAILED` and from
    `LAPSED`; it sets `home_check_passed_at` to the supplied `checked_at`, sets
    `home_check_expires_at` to that instant advanced by 180 days, and increments
    `version` by one."
    PRD 3.4: "A passed check lapses on its own: any read or write touching the
    application while the logical clock stands strictly later than
    `home_check_expires_at` moves it `PASSED → LAPSED`."

    A check passed on 2026-05-02 expires 180 days later on 2026-10-29, so a clock
    standing at 2026-10-30 is strictly later and the axis lapses.

    Design: Difficulty/non_linear_state_machine/foster_application_parallel_axes_advance_independently
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    new_organization(api)
    scenario = setup_foster_home(
        api,
        home_overrides={"max_headcount": 6, "dog_slot_capacity": 4, "cat_slot_capacity": 0,
                        "accepts_cats": False},
        checked_at="2026-05-02T00:00:00Z",
    )
    application = scenario["application"]

    before = validate_success(api.get_foster_application(application["id"], COORD))
    assert_same_instant(
        before["home_check_expires_at"], "2026-10-29T00:00:00Z", "home_check_expires_at"
    )
    assert before["home_check_status"] == "PASSED"

    set_clock(api, "2026-10-30T00:00:00Z")
    after = validate_success(api.get_foster_application(application["id"], COORD))
    assert after["home_check_status"] == "LAPSED"
    assert after["application_status"] == "APPROVED", (
        "the home-check lapse must not disturb the application axis"
    )


# --------------------------------------------------------------------------
# A placement depends on the other entity's second axis
# --------------------------------------------------------------------------
def _lapsed_home_check_scenario(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api,
        home_overrides={"max_headcount": 6, "dog_slot_capacity": 4, "cat_slot_capacity": 0,
                        "accepts_cats": False},
        checked_at="2026-05-02T00:00:00Z",
    )
    animal = new_animal(api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-02T00:00:00Z")
    set_clock(api, "2026-10-30T00:00:00Z")
    scenario["animal"] = animal
    scenario["org"] = org
    return scenario


def test_placement_is_refused_while_the_linked_home_check_has_lapsed(api):
    """PRD 3.4: "**Home-check currency.** The linked application's `home_check_status`
    must be `PASSED` with the clock at or before `home_check_expires_at`;
    `NOT_SCHEDULED`, `FAILED` and `LAPSED` all fail this and yield
    `ERR_HOME_CHECK_NOT_CURRENT`. This guards all three operations, which matters
    because a check can lapse between proposal and activation."

    Design: Difficulty/cross_entity_state_dependency/placement_depends_on_foster_application_home_check_state
    """
    scenario = _lapsed_home_check_scenario(api)

    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                scenario["animal"]["id"], scenario["home"]["id"],
                scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        ApiErrorId.ERR_HOME_CHECK_NOT_CURRENT.value,
        409,
    )

    home = validate_success(api.get_foster_home(scenario["home"]["id"], COORD))
    assert home["consumed_dog_slots"] == 0, "a refused proposal must consume nothing"


def test_a_fresh_home_check_restarts_the_window_and_unblocks_the_placement(api):
    """PRD 3.4: "A `LAPSED` check blocks new placements against that application but is
    fully recoverable — a fresh `PASS` moves it back to `PASSED` and restarts the
    180-day window from the new `checked_at`."
    PRD 3.4: "A proposal is created in `status` `PROPOSED` with `started_at`,
    `ended_at`, `end_reason` and `predecessor_placement_id` all null, computes and
    stores its `slot_consumption` and `headcount_consumption`, and increments the
    receiving home's `version` by one."
    PRD 3.4: "`slot_consumption` is 1 under `INDIVIDUAL` and a flat 2 under
    `NURSING_UNIT`, however many littermates the nursing unit actually contains.
    `headcount_consumption` is 1 under `INDIVIDUAL` and, under `NURSING_UNIT`, one for
    the dam plus the litter's `member_count`."

    A fresh pass at 2026-10-30 expires 180 days later on 2027-04-28.

    Design: Difficulty/cross_entity_state_dependency/placement_depends_on_foster_application_home_check_state
    """
    scenario = _lapsed_home_check_scenario(api)

    rechecked = validate_success(
        api.record_home_check(
            scenario["application"]["id"],
            {"result": "PASS", "checked_at": "2026-10-30T00:00:00Z"},
            COORD,
        )
    )
    assert rechecked["home_check_status"] == "PASSED"
    assert_same_instant(
        rechecked["home_check_expires_at"], "2027-04-28T00:00:00Z", "home_check_expires_at"
    )

    placement = validate_success(
        api.create_foster_placement(
            foster_placement_payload(
                scenario["animal"]["id"], scenario["home"]["id"],
                scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        201,
    )
    assert_foster_placement(placement)
    assert placement["status"] == "PROPOSED"
    assert placement["slot_consumption"] == 1
    assert placement["headcount_consumption"] == 1
    assert placement["started_at"] is None
    assert placement["predecessor_placement_id"] is None
    assert validate_success(
        api.get_foster_application(scenario["application"]["id"], COORD)
    )["application_status"] == "APPROVED"


# --------------------------------------------------------------------------
# Aggregate capacity over concurrently ACTIVE placements
# --------------------------------------------------------------------------
def _nursing_unit_scenario(api):
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api,
        home_overrides={"max_headcount": 6, "dog_slot_capacity": 4, "cat_slot_capacity": 0,
                        "accepts_cats": False},
        checked_at="2026-05-01T00:00:00Z",
    )
    litter = new_litter(api, "Maple litter")
    dam = new_animal(api, org["id"], name="Dam", weight_lb=40.0,
                     date_of_birth="2022-01-01T00:00:00Z")
    for name in ("P1", "P2", "P3", "P4", "P5"):
        new_animal(api, org["id"], name=name, size_class="SMALL", weight_lb=6.0,
                   date_of_birth="2026-04-01T00:00:00Z", litter_id=litter["id"])
    solo = new_animal(api, org["id"], name="Solo", weight_lb=35.0,
                      date_of_birth="2022-06-01T00:00:00Z")
    take_into_custody(api, dam["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, solo["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    scenario.update({"org": org, "litter": litter, "dam": dam, "solo": solo})
    return scenario


def test_nursing_unit_placement_consumes_two_slots_and_six_heads(api):
    """PRD 3.4: "The two consumption figures are deliberately **not** proportional to
    one another. `slot_consumption` is 1 under `INDIVIDUAL` and a flat 2 under
    `NURSING_UNIT`, however many littermates the nursing unit actually contains.
    `headcount_consumption` is 1 under `INDIVIDUAL` and, under `NURSING_UNIT`, one for
    the dam plus the litter's `member_count`."
    PRD 3.4: "The home's `capacity_status` is `OPEN` when at least one species bucket
    still has a free slot **and** at least one head remains free, and `FULL` otherwise
    — so exhausting either both species buckets or the head count alone flips it to
    `FULL`."

    Design: Difficulty/resource_temporal_overlap/foster_home_aggregate_capacity_over_concurrent_placements
    """
    scenario = _nursing_unit_scenario(api)

    placement = propose_placement(
        api, scenario["dam"]["id"], scenario["home"]["id"], scenario["application"]["id"],
        count_basis="NURSING_UNIT", litter_id=scenario["litter"]["id"],
    )
    assert placement["slot_consumption"] == 2
    assert placement["headcount_consumption"] == 6, (
        "one for the dam plus the litter's five members"
    )
    validate_success(api.activate_foster_placement(placement["id"], COORD))

    set_clock(api, "2026-05-03T00:00:00Z")
    home = validate_success(api.get_foster_home(scenario["home"]["id"], COORD))
    assert_foster_home(home)
    assert home["consumed_dog_slots"] == 2
    assert home["consumed_headcount"] == 6
    assert home["capacity_status"] == "FULL", "no head remains free"
    assert validate_success(api.get_litter(scenario["litter"]["id"], ADMIN))["member_count"] == 5


def test_head_count_rejects_a_placement_while_species_slots_are_still_free(api):
    """PRD 3.4: "Head count is tested second: `consumed_headcount` plus this
    placement's `headcount_consumption` must not exceed `max_headcount`, failing which
    the answer is `ERR_FOSTER_HEADCOUNT_EXCEEDED`."
    PRD 3.4: "A home can therefore be slot-open and head-full at the same time, which
    is exactly why the two capacity rejections are distinct codes."

    Two of the four dog slots are still free, so the species-slot rung passes and the
    head-count rung is what rejects the second placement.

    Design: Difficulty/resource_temporal_overlap/foster_home_aggregate_capacity_over_concurrent_placements
    """
    scenario = _nursing_unit_scenario(api)

    placement = propose_placement(
        api, scenario["dam"]["id"], scenario["home"]["id"], scenario["application"]["id"],
        count_basis="NURSING_UNIT", litter_id=scenario["litter"]["id"],
    )
    activated = validate_success(api.activate_foster_placement(placement["id"], COORD))
    assert activated["status"] == "ACTIVE"

    set_clock(api, "2026-05-03T00:00:00Z")
    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                scenario["solo"]["id"], scenario["home"]["id"],
                scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        ApiErrorId.ERR_FOSTER_HEADCOUNT_EXCEEDED.value,
        409,
    )


# --------------------------------------------------------------------------
# Corner coverage on placements
# --------------------------------------------------------------------------
def test_foster_transfer_creates_an_active_successor_and_moves_the_counters(api):
    """PRD 3.4: "On success the source placement moves `ACTIVE → TRANSFERRED` with
    `ended_at` stamped and `end_reason` set to `TRANSFERRED_OUT`, a **successor
    placement is created in `ACTIVE`** whose `predecessor_placement_id` points back at
    the source, both homes' counters and `capacity_status` are recomputed, and the
    source placement's `version` increments by one."
    PRD 3.4: "Activating a proposal moves it `PROPOSED → ACTIVE`, stamps `started_at`
    with the current clock instant, sets the animal's `current_foster_home_id` to the
    receiving home, recomputes that home's counters and `capacity_status`, and
    increments both the placement's `version` and the home's `version` by one."

    Design: Corner/state_machines/foster_placement_transfer_creates_successor_and_moves_counters
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    home_one = setup_foster_home(
        api, home_overrides={"max_headcount": 4, "dog_slot_capacity": 2},
        person_name="Rhea Voss", person_email="rhea@example.test", person_overrides={},
    )
    home_two = setup_foster_home(
        api, home_overrides={"label": "Otis Home", "max_headcount": 4, "dog_slot_capacity": 2},
        person_name="Sam Otis", person_email="sam@example.test", person_overrides={},
    )
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2023-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    source = place_animal_in_home(
        api, animal["id"], home_one["home"]["id"], home_one["application"]["id"]
    )
    assert source["status"] == "ACTIVE"

    successor = validate_success(
        api.transfer_foster_placement(
            source["id"],
            {"destination_foster_home_id": home_two["home"]["id"],
             "destination_foster_application_id": home_two["application"]["id"]},
            COORD,
        ),
        201,
    )
    assert successor["status"] == "ACTIVE"
    assert successor["predecessor_placement_id"] == source["id"]

    source_after = validate_success(api.get_foster_placement(source["id"], COORD))
    assert source_after["status"] == "TRANSFERRED"
    assert source_after["end_reason"] == "TRANSFERRED_OUT"

    h1 = validate_success(api.get_foster_home(home_one["home"]["id"], COORD))
    h2 = validate_success(api.get_foster_home(home_two["home"]["id"], COORD))
    assert h1["consumed_dog_slots"] == 0
    assert h1["consumed_headcount"] == 0
    assert h1["capacity_status"] == "OPEN"
    assert h2["consumed_dog_slots"] == 1
    assert h2["consumed_headcount"] == 1
    assert validate_success(api.get_animal(animal["id"], ADMIN))[
        "current_foster_home_id"
    ] == home_two["home"]["id"]


def test_species_slot_capacity_is_tested_before_the_head_count(api):
    """PRD 3.4: "**Capacity.** Species slots are tested first: the home's consumed slots
    in the animal's species bucket plus this placement's `slot_consumption` must not
    exceed that bucket's capacity, failing which the answer is
    `ERR_FOSTER_CAPACITY_EXCEEDED`."
    PRD 3.4: "Both comparisons are inclusive — filling the last slot or the last head
    exactly is permitted."

    Design: Corner/validations/foster_species_slot_capacity_exceeded_before_headcount
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api, home_overrides={"max_headcount": 10, "dog_slot_capacity": 2}
    )
    dogs = []
    for name in ("D1", "D2", "D3"):
        animal = new_animal(api, org["id"], name=name, size_class="SMALL", weight_lb=20.0,
                            date_of_birth="2022-01-01T00:00:00Z")
        take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
        dogs.append(animal)

    for animal in dogs[:2]:
        placed = place_animal_in_home(
            api, animal["id"], scenario["home"]["id"], scenario["application"]["id"]
        )
        assert placed["status"] == "ACTIVE"

    home = validate_success(api.get_foster_home(scenario["home"]["id"], COORD))
    assert home["consumed_dog_slots"] == 2
    assert home["consumed_headcount"] == 2
    assert home["capacity_status"] == "FULL", "the only species bucket with capacity is full"

    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                dogs[2]["id"], scenario["home"]["id"], scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        ApiErrorId.ERR_FOSTER_CAPACITY_EXCEEDED.value,
        409,
    )


def test_a_no_cats_home_refuses_a_cat_placement(api):
    """PRD 3.4: "**Foster restriction evaluation.** Its three criteria are tested in a
    pinned order with the first failure reported: first that the animal is not a `CAT`
    or else the home's `accepts_cats` is true; second that the home's
    `min_child_age_years` is at least the animal's `restriction_no_children_under_years`,
    an inclusive comparison so a home whose youngest child is exactly the restriction
    age qualifies; third that the animal does not require a fenced yard or else the
    home's `has_fenced_yard` is true. Any failure is
    `ERR_FOSTER_RESTRICTION_VIOLATION`."
    PRD 3.4: "Three home-check-derived restrictions are also recorded: `accepts_cats`,
    defaulting to true, where false marks a no-cats household; `min_child_age_years`,
    defaulting to 99 with the same convention as a person's household — 99 means no
    resident children; and `has_fenced_yard`, defaulting to false."

    Design: Corner/validations/foster_restriction_no_cats_household_rejects_cat_placement
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api, species_requested="CAT",
        home_overrides={"max_headcount": 4, "dog_slot_capacity": 0, "cat_slot_capacity": 2,
                        "accepts_cats": False},
    )
    cat = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                     weight_lb=9.0, date_of_birth="2023-01-01T00:00:00Z")
    take_into_custody(api, cat["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                cat["id"], scenario["home"]["id"], scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        ApiErrorId.ERR_FOSTER_RESTRICTION_VIOLATION.value,
        422,
    )

    home = validate_success(api.get_foster_home(scenario["home"]["id"], COORD))
    assert home["consumed_cat_slots"] == 0
    assert home["capacity_status"] == "OPEN"


def test_a_stale_foster_home_version_is_rejected_on_placement_create(api):
    """PRD 2.7: "Proposing a foster placement requires `expected_foster_home_version`,
    carrying the caller's last observed `version` of the receiving `FosterHome`."
    PRD 2.7: "If the value does not equal the parent's current `version` at the moment
    the request is evaluated, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)
    at rung 17, and nothing is mutated."

    Design: Corner/cross_cutting_layers/occ_stale_foster_home_version_rejected_on_placement_create
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api, home_overrides={"max_headcount": 4, "dog_slot_capacity": 4}
    )
    d1 = new_animal(api, org["id"], name="D1", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z")
    d2 = new_animal(api, org["id"], name="D2", size_class="SMALL", weight_lb=20.0,
                    date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, d1["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, d2["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    stale_version = foster_home_version(api, scenario["home"]["id"])
    first = validate_success(
        api.create_foster_placement(
            foster_placement_payload(
                d1["id"], scenario["home"]["id"], scenario["application"]["id"], stale_version
            ),
            COORD,
        ),
        201,
    )

    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                d2["id"], scenario["home"]["id"], scenario["application"]["id"], stale_version
            ),
            COORD,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )

    retried = validate_success(
        api.create_foster_placement(
            foster_placement_payload(
                d2["id"], scenario["home"]["id"], scenario["application"]["id"],
                foster_home_version(api, scenario["home"]["id"]),
            ),
            COORD,
        ),
        201,
    )
    assert retried["status"] == "PROPOSED"
    assert validate_success(api.get_foster_placement(first["id"], COORD))["status"] == "PROPOSED"
    assert validate_success(api.get_foster_home(scenario["home"]["id"], COORD))[
        "consumed_dog_slots"
    ] == 0


def test_foster_parent_may_not_create_a_placement(api):
    """PRD 2.1: "Only once the role is recognised does the system ask whether that role
    is listed as authorised for the endpoint being called; when it is not, the answer
    is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "`FosterCoordinator` owns the foster pipeline: homes, applications, home
    checks, placements, activations, endings and transfers."
    PRD 2.1: "`Driver`, `FosterParent`, `Adopter` and `PartnerRescue` are the
    outward-facing roles and are constrained to their own records."

    Design: Corner/rbac/foster_parent_cannot_create_a_foster_placement
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    scenario = setup_foster_home(
        api, home_overrides={"max_headcount": 4, "dog_slot_capacity": 2}
    )
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    parent_headers = make_foster_parent_headers(scenario["parent"]["id"])
    home_read = validate_success(api.get_foster_home(scenario["home"]["id"], parent_headers))

    validate_error(
        api.create_foster_placement(
            foster_placement_payload(
                animal["id"], scenario["home"]["id"], scenario["application"]["id"],
                home_read["version"],
            ),
            parent_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert validate_success(api.get_foster_home(scenario["home"]["id"], COORD))[
        "consumed_dog_slots"
    ] == 0
