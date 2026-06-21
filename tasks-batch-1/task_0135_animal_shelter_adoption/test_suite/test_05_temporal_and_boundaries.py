"""Temporal gates, boundary precision, and resource-interval overlap.

Queue A rule 6 (boundary precision) and rule 8 (resource temporal overlap). Time
is driven by the logical clock (PRD §2.10); release/cooldown gates are inclusive
of the boundary instant.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    bootstrap_shelter,
    set_clock,
    register_animal,
    intake_animal,
    create_intaken_animal,
    create_available_animal,
    create_kennel,
    create_foster_home,
    clear_medical,
    assign_kennel,
    place_foster,
    return_foster,
    make_animal_available,
    TEST_USERS,
)
from test_helpers.factories import create_kennel_assignment_payload, create_foster_placement_payload

ADMIN = TEST_USERS["shelter_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]
FOSTER = TEST_USERS["foster_coordinator_headers"]


# ===================================================================
# Rule 6 — boundary precision: stray-hold release instant
# ===================================================================

def test_make_available_at_exact_release_instant_succeeds(api):
    """PRD §3.5: "The stray-hold must have elapsed — the current clock instant must be
    at or after the animal's stray_hold_release_at — and if it has not, the request is
    rejected with ERR_STRAY_HOLD_ACTIVE."
    PRD §3.2: "Downstream gates that consult this instant treat it as inclusive — an
    action attempted at the very instant of release is permitted, while an action one
    moment before it is not."

    Design: Difficulty/boundary_precision_check/stray_hold_release_exact_instant_allows_make_available
    """
    bootstrap_shelter(stray_hold_days=5)
    animal = register_animal(name="Hold", species="DOG", age_months=40)
    intake_animal(animal["id"], source="STRAY")  # release_at = 2026-06-06T00:00:00Z
    clear_medical(animal["id"])
    set_clock("2026-06-06T00:00:00Z")  # EXACTLY at release

    resp = api_client.make_available(animal["id"], COUNSELOR)
    available = validate_success(resp, 200)
    assert available["lifecycle_status"] == "AVAILABLE", "make-available succeeds at the release instant"


def test_make_available_one_second_before_release_rejected(api):
    """PRD §3.2: "an action attempted at the very instant of release is permitted, while
    an action one moment before it is not."
    PRD §3.5: "if it has not, the request is rejected with ERR_STRAY_HOLD_ACTIVE."

    Design: Difficulty/boundary_precision_check/stray_hold_release_exact_instant_allows_make_available
    """
    bootstrap_shelter(stray_hold_days=5)
    animal = register_animal(name="Hold2", species="DOG", age_months=40)
    intake_animal(animal["id"], source="STRAY")  # release_at = 2026-06-06T00:00:00Z
    clear_medical(animal["id"])
    set_clock("2026-06-05T23:59:59Z")  # one second before release

    resp = api_client.make_available(animal["id"], COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_STRAY_HOLD_ACTIVE.value)


# ===================================================================
# Rule 6 — boundary precision: foster home capacity at equality
# ===================================================================

def test_foster_capacity_boundary_rejects_at_equality(api):
    """PRD §3.8: "The home must have aggregate room: its active_placement_count must be
    strictly less than its max_concurrent, and a placement attempted when the count
    already equals the maximum is rejected with ERR_FOSTER_HOME_FULL."

    Design: Difficulty/boundary_precision_check/foster_home_capacity_boundary_rejects_at_equality
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=1, cooldown_days=0, contact_name="Cap1")
    a1 = create_available_animal(species="CAT", age_months=20, name="An1")
    a2 = create_available_animal(species="CAT", age_months=22, name="An2", chip_number="CHIP-AN2")
    place_foster(home["id"], a1["id"])  # active_placement_count -> 1 == max_concurrent

    resp = api_client.create_foster_placement(create_foster_placement_payload(home["id"], a2["id"]), FOSTER)
    validate_error(resp, ApiErrorId.ERR_FOSTER_HOME_FULL.value)


def test_foster_placement_succeeds_below_capacity(api):
    """PRD §3.8: "its active_placement_count must be strictly less than its
    max_concurrent ... A successful placement creates a FosterPlacement in status ACTIVE
    with start_at stamped from the clock, increments the home's active_placement_count
    by one, and drives the animal from AVAILABLE to FOSTERED."

    Design: Difficulty/boundary_precision_check/foster_home_capacity_boundary_rejects_at_equality
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=1, cooldown_days=0, contact_name="Cap1b")
    a1 = create_available_animal(species="DOG", age_months=24, name="Below")

    fp = place_foster(home["id"], a1["id"])  # count 0 -> 1, strictly < 1 at placement time
    assert fp["status"] == "ACTIVE"
    home_after = validate_success(api_client.get_foster_home(home["id"], FOSTER))
    assert home_after["active_placement_count"] == 1


# ===================================================================
# Rule 8 — resource temporal overlap: kennel half-open single-occupancy
# ===================================================================

def test_kennel_half_open_single_occupancy_overlap_rejected(api):
    """PRD §3.4: "no other ACTIVE assignment on that kennel overlaps the requested
    occupancy interval. Occupancy intervals are half-open, spanning from start_at up to
    but not including end_at; two intervals overlap when one begins before the other ends
    under that half-open convention. A kennel that is not OPEN, or on which an existing
    ACTIVE assignment overlaps the interval, causes rejection with ERR_KENNEL_OCCUPIED."

    Design: Difficulty/resource_temporal_overlap/kennel_half_open_single_occupancy_overlap
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-5")
    a = create_intaken_animal(species="CAT", age_months=24, source="SURRENDER", name="A")
    assign_kennel(kennel["id"], a["id"], kennel["version"])  # ACTIVE, end_at open

    b = create_intaken_animal(species="CAT", age_months=26, source="SURRENDER", name="B")
    kennel_full = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    resp = api_client.create_kennel_assignment(
        create_kennel_assignment_payload(kennel["id"], b["id"], kennel_full["version"]), INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_KENNEL_OCCUPIED.value)


def test_kennel_reopens_after_release_allows_new_assignment(api):
    """PRD §3.4: "Releasing sets end_at to the current clock instant, transitions the
    assignment's status to RELEASED ... recomputes the kennel's status (back to OPEN if
    occupied_count is again below capacity)."
    PRD §3.4: "the target kennel's status is OPEN (its occupied_count strictly below its
    capacity)."

    Design: Difficulty/resource_temporal_overlap/kennel_half_open_single_occupancy_overlap
    """
    bootstrap_shelter()
    kennel = create_kennel(capacity=1, label="K-5b")
    a = create_intaken_animal(species="DOG", age_months=30, source="SURRENDER", name="First")
    ka = assign_kennel(kennel["id"], a["id"], kennel["version"])
    validate_success(api_client.release_kennel_assignment(ka["id"], INTAKE))  # frees the kennel

    b = create_intaken_animal(species="DOG", age_months=32, source="SURRENDER", name="Second")
    kennel_open = validate_success(api_client.get_kennel(kennel["id"], INTAKE))
    assert kennel_open["status"] == "OPEN"
    ka2 = validate_success(
        api_client.create_kennel_assignment(
            create_kennel_assignment_payload(kennel["id"], b["id"], kennel_open["version"]), INTAKE
        ),
        201,
    )
    assert ka2["status"] == "ACTIVE", "a fresh assignment succeeds once the kennel is OPEN again"


# ===================================================================
# Rule 8 — resource temporal overlap: foster cooldown buffer
# ===================================================================

def test_foster_cooldown_buffer_rejects_within_gap(api):
    """PRD §3.8: "the home's cooldown must have cleared: the new placement's start_at
    must fall at least cooldown_days whole days after the end_at of the most recent
    RETURNED placement at that home, otherwise the attempt is rejected with
    ERR_FOSTER_COOLDOWN."

    Design: Difficulty/resource_temporal_overlap/foster_cooldown_buffer_rejects_within_gap
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=2, cooldown_days=3, contact_name="Cool")
    a = create_available_animal(species="DOG", age_months=30, name="A")
    fp1 = place_foster(home["id"], a["id"])
    set_clock("2026-06-02T00:00:00Z")
    return_foster(fp1["id"])  # end_at = 2026-06-02

    b = create_available_animal(species="DOG", age_months=32, name="B", chip_number="CHIP-B")
    set_clock("2026-06-03T00:00:00Z")  # only 1 day after return, < 3-day cooldown

    resp = api_client.create_foster_placement(create_foster_placement_payload(home["id"], b["id"]), FOSTER)
    validate_error(resp, ApiErrorId.ERR_FOSTER_COOLDOWN.value)


def test_foster_placement_allowed_after_cooldown_elapses(api):
    """PRD §3.8: "the new placement's start_at must fall at least cooldown_days whole
    days after the end_at of the most recent RETURNED placement at that home."
    PRD §3.8: "A successful placement creates a FosterPlacement in status ACTIVE ... and
    drives the animal from AVAILABLE to FOSTERED."

    Design: Difficulty/resource_temporal_overlap/foster_cooldown_buffer_rejects_within_gap
    """
    bootstrap_shelter()
    home = create_foster_home(max_concurrent=2, cooldown_days=3, contact_name="CoolOK")
    a = create_available_animal(species="DOG", age_months=30, name="A")
    fp1 = place_foster(home["id"], a["id"])
    set_clock("2026-06-02T00:00:00Z")
    return_foster(fp1["id"])  # end_at = 2026-06-02

    b = create_available_animal(species="DOG", age_months=32, name="B", chip_number="CHIP-BB")
    set_clock("2026-06-05T00:00:00Z")  # exactly 3 days after return -> cooldown cleared

    fp2 = validate_success(
        api_client.create_foster_placement(create_foster_placement_payload(home["id"], b["id"]), FOSTER),
        201,
    )
    assert fp2["status"] == "ACTIVE", "placement allowed once the 3-day cooldown has cleared"
