"""Run eligibility, temporal overlap, pen capacity, grouping, and OCC on assignment create.

Translates difficulty (A) resource_temporal_overlap and boundary_precision_check
(capacity) instances, plus corner (B) run-eligibility / grouping / stale-version
instances.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_assignment_payload, create_reservation_payload,
    setup_facility_owner_pet,
    create_facility, create_owner, create_pet, create_run, create_assignment,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def _facility_with_pet(weight_kg=6, temperament="CALM"):
    facility = create_facility(deposit_policy="NONE")
    owner = create_owner(facility["id"])
    pet = create_pet(owner["id"], weight_kg=weight_kg, temperament=temperament)
    return facility, owner, pet


def _reservation(facility_id, pet_id, service_type, start_date, end_date):
    return get_success_data(api_client.create_reservation(
        facility_id,
        create_reservation_payload(pet_id, service_type, start_date, end_date),
        MGR,
    ))


# --------------------------------------------------------------- suite overlap (half-open)
def test_suite_overlapping_interval_rejected(api):
    """PRD §3.6: "For an `OVERNIGHT_SUITE`, the assignment interval must not overlap any
    non-`RELEASED` assignment already on that same suite, using half-open intervals so
    that adjacent intervals sharing an endpoint do not conflict; a clash is rejected with
    `ERR_RUN_OVERLAP`."

    A suite held [02-01,02-04) blocks an overlapping [02-03,02-05).

    Design: Difficulty/resource_temporal_overlap/suite_interval_overlap_half_open
    """
    facility, owner, _ = _facility_with_pet()
    petW = create_pet(owner["id"], weight_kg=6)
    petZ = create_pet(owner["id"], weight_kg=6)
    run = create_run(facility["id"], label="Suite-O1", kind="OVERNIGHT_SUITE", size_class="LARGE")
    res1 = _reservation(facility["id"], petW["id"], "OVERNIGHT", "2026-02-01", "2026-02-04")
    create_assignment(res1["id"], run["id"], res1["version"])
    res2 = _reservation(facility["id"], petZ["id"], "OVERNIGHT", "2026-02-03", "2026-02-05")
    out = api.create_assignment(
        res2["id"], create_assignment_payload(run["id"], res2["version"]), MGR)
    validate_error(out, "ERR_RUN_OVERLAP")


def test_suite_adjacent_interval_allowed(api):
    """PRD §3.6: "using half-open intervals so that adjacent intervals sharing an endpoint
    do not conflict".

    A suite held [02-01,02-04) does NOT block an adjacent [02-04,02-06) — the shared
    endpoint 02-04 is touching, not overlapping.

    Design: Difficulty/resource_temporal_overlap/suite_interval_overlap_half_open
    """
    facility, owner, _ = _facility_with_pet()
    petW = create_pet(owner["id"], weight_kg=6)
    petZ = create_pet(owner["id"], weight_kg=6)
    run = create_run(facility["id"], label="Suite-O2", kind="OVERNIGHT_SUITE", size_class="LARGE")
    res1 = _reservation(facility["id"], petW["id"], "OVERNIGHT", "2026-02-01", "2026-02-04")
    create_assignment(res1["id"], run["id"], res1["version"])
    res2 = _reservation(facility["id"], petZ["id"], "OVERNIGHT", "2026-02-04", "2026-02-06")
    out = validate_success(api.create_assignment(
        res2["id"], create_assignment_payload(run["id"], res2["version"]), MGR), 201)
    assert out["status"] == "HELD", "adjacent (touching) suite interval is admitted"


# --------------------------------------------------------------- pet double-booking (closed)
def test_pet_double_booked_same_date_rejected(api):
    """PRD §3.6: "A new assignment is rejected with `ERR_PET_DOUBLE_BOOKED` if its
    interval overlaps the window of any other non-`RELEASED` assignment for the same pet,
    because a pet cannot be in two places at once; this self-exclusion uses closed,
    inclusive semantics, so two daycare days on the same calendar date collide even though
    the half-open suite rule would treat touching endpoints as merely adjacent."

    Same pet already held on Pen-P1 for 2026-02-20 cannot take a second 2026-02-20
    assignment in a different pen.

    Design: Difficulty/resource_temporal_overlap/pet_double_booking_closed_interval
    """
    facility, owner, pet = _facility_with_pet()
    run1 = create_run(facility["id"], label="Pen-P1", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    run2 = create_run(facility["id"], label="Pen-P2", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    res1 = _reservation(facility["id"], pet["id"], "DAYCARE", "2026-02-20", "2026-02-20")
    create_assignment(res1["id"], run1["id"], res1["version"])
    res2 = _reservation(facility["id"], pet["id"], "DAYCARE", "2026-02-20", "2026-02-20")
    out = api.create_assignment(
        res2["id"], create_assignment_payload(run2["id"], res2["version"]), MGR)
    validate_error(out, "ERR_PET_DOUBLE_BOOKED")


def test_pet_different_date_not_double_booked(api):
    """PRD §3.6: "A new assignment is rejected with `ERR_PET_DOUBLE_BOOKED` if its interval
    overlaps the window of any other non-`RELEASED` assignment for the same pet, because a
    pet cannot be in two places at once; this self-exclusion uses closed, inclusive
    semantics, so two daycare days on the same calendar date collide even though the
    half-open suite rule would treat touching endpoints as merely adjacent."

    The same pet on a DIFFERENT calendar date does NOT collide — the windows do not
    overlap, so the second assignment is admitted.

    Design: Difficulty/resource_temporal_overlap/pet_double_booking_closed_interval
    """
    facility, owner, pet = _facility_with_pet()
    run1 = create_run(facility["id"], label="Pen-Q1", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    run2 = create_run(facility["id"], label="Pen-Q2", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    res1 = _reservation(facility["id"], pet["id"], "DAYCARE", "2026-02-20", "2026-02-20")
    create_assignment(res1["id"], run1["id"], res1["version"])
    res2 = _reservation(facility["id"], pet["id"], "DAYCARE", "2026-02-22", "2026-02-22")
    out = validate_success(api.create_assignment(
        res2["id"], create_assignment_payload(run2["id"], res2["version"]), MGR), 201)
    assert out["status"] == "HELD", "same pet, non-overlapping date is admitted"


# --------------------------------------------------------------- daycare capacity boundary
def test_daycare_capacity_first_admitted_second_rejected(api):
    """PRD §3.6: "For a `DAYCARE_PEN`, the new assignment on a given date must not push
    the count of non-`RELEASED` assignments on that date above the run's
    `daycare_capacity` plus the facility's `overbook_grace`; exceeding it is rejected with
    `ERR_RUN_CAPACITY_EXCEEDED`, and the rule compares only the same calendar date —
    different dates never collide."

    Capacity 1, overbook 0: the first same-date assignment (count 0->1) succeeds, a second
    distinct-pet assignment on that date is rejected.

    Design: Difficulty/boundary_precision_check/daycare_capacity_count_boundary_empty_and_full
    """
    facility = create_facility(deposit_policy="NONE", overbook_grace=0)
    owner = create_owner(facility["id"])
    petA = create_pet(owner["id"], name="A", weight_kg=6)
    petB = create_pet(owner["id"], name="B", weight_kg=6)
    run = create_run(facility["id"], label="Pen-L1", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=1)
    resA = _reservation(facility["id"], petA["id"], "DAYCARE", "2026-01-20", "2026-01-20")
    first = validate_success(api.create_assignment(
        resA["id"], create_assignment_payload(run["id"], resA["version"]), MGR), 201)
    assert first["status"] == "HELD", "first assignment fills capacity 1"
    resB = _reservation(facility["id"], petB["id"], "DAYCARE", "2026-01-20", "2026-01-20")
    out = api.create_assignment(
        resB["id"], create_assignment_payload(run["id"], resB["version"]), MGR)
    validate_error(out, "ERR_RUN_CAPACITY_EXCEEDED")


def test_daycare_capacity_different_dates_both_admitted(api):
    """PRD §3.6: "For a `DAYCARE_PEN`, the new assignment on a given date must not push the
    count of non-`RELEASED` assignments on that date above the run's `daycare_capacity`
    plus the facility's `overbook_grace`; exceeding it is rejected with
    `ERR_RUN_CAPACITY_EXCEEDED`, and the rule compares only the same calendar date —
    different dates never collide."

    Capacity 1: two distinct-date assignments on the same pen both succeed because the
    count rule is scoped to a single calendar date.

    Design: Difficulty/boundary_precision_check/daycare_capacity_count_boundary_empty_and_full
    """
    facility = create_facility(deposit_policy="NONE", overbook_grace=0)
    owner = create_owner(facility["id"])
    petA = create_pet(owner["id"], name="A", weight_kg=6)
    petB = create_pet(owner["id"], name="B", weight_kg=6)
    run = create_run(facility["id"], label="Pen-L2", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=1)
    resA = _reservation(facility["id"], petA["id"], "DAYCARE", "2026-01-20", "2026-01-20")
    validate_success(api.create_assignment(
        resA["id"], create_assignment_payload(run["id"], resA["version"]), MGR), 201)
    resB = _reservation(facility["id"], petB["id"], "DAYCARE", "2026-01-21", "2026-01-21")
    out = validate_success(api.create_assignment(
        resB["id"], create_assignment_payload(run["id"], resB["version"]), MGR), 201)
    assert out["status"] == "HELD", "a different-date assignment on the same pen is admitted at capacity 1"


# --------------------------------------------------------------- corner: grouping
def test_group_incompatible_reactive_rejected(api):
    """PRD §3.6: "a size component equal to 2 times the absolute difference between the
    candidate's and the existing pet's size ranks (where `TOY` ranks 0, `SMALL` ranks 1,
    `MEDIUM` ranks 2, and `LARGE` ranks 3), plus a temperament component equal to 3 times
    a pairing penalty."
    PRD §3.6: "a candidate whose `temperament` is `REACTIVE` is held to the strict ceiling
    and its group score must be at most 4".
    PRD §3.6: "A candidate that breaches its applicable ceiling is rejected with
    `ERR_GROUP_INCOMPATIBLE`".

    REACTIVE MEDIUM joining a pen holding a CALM SMALL scores 2*1 + 3*1 = 5 > 4.

    Design: Corner/calculations/group_incompatible_reactive_rejected
    """
    facility = create_facility(deposit_policy="NONE")
    owner = create_owner(facility["id"])
    petCalm = create_pet(owner["id"], name="Calm", weight_kg=6, temperament="CALM")
    petReac = create_pet(owner["id"], name="Reac", weight_kg=18, temperament="REACTIVE")
    run = create_run(facility["id"], label="Pen-C4", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    resCalm = _reservation(facility["id"], petCalm["id"], "DAYCARE", "2026-02-25", "2026-02-25")
    create_assignment(resCalm["id"], run["id"], resCalm["version"])
    resReac = _reservation(facility["id"], petReac["id"], "DAYCARE", "2026-02-25", "2026-02-25")
    out = api.create_assignment(
        resReac["id"], create_assignment_payload(run["id"], resReac["version"]), MGR)
    validate_error(out, "ERR_GROUP_INCOMPATIBLE")


# --------------------------------------------------------------- corner: run eligibility
def test_run_size_mismatch_rejected(api):
    """PRD §3.6: "The target run must be eligible: its `status` must be `AVAILABLE`, its
    `size_class` must be at least the pet's `size_class` on the ordering where `TOY` is
    smallest, then `SMALL`, then `MEDIUM`, then `LARGE` is largest, and its `kind` must
    match the service — an `OVERNIGHT` reservation requires an `OVERNIGHT_SUITE` and a
    `DAYCARE` reservation requires a `DAYCARE_PEN`."
    PRD §3.6: "A run that fails any of these is rejected with `ERR_RUN_NOT_ELIGIBLE`."

    Design: Corner/validations/run_size_mismatch_rejected
    """
    facility, owner, pet = _facility_with_pet(weight_kg=35)  # LARGE
    run = create_run(facility["id"], label="Tiny-V1", kind="OVERNIGHT_SUITE", size_class="TOY")
    res = _reservation(facility["id"], pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03")
    out = api.create_assignment(
        res["id"], create_assignment_payload(run["id"], res["version"]), MGR)
    validate_error(out, "ERR_RUN_NOT_ELIGIBLE")


def test_run_kind_mismatch_rejected(api):
    """PRD §3.6: "its `kind` must match the service — an `OVERNIGHT` reservation requires
    an `OVERNIGHT_SUITE` and a `DAYCARE` reservation requires a `DAYCARE_PEN`. A run that
    fails any of these is rejected with `ERR_RUN_NOT_ELIGIBLE`."

    Design: Corner/validations/run_kind_mismatch_rejected
    """
    facility, owner, pet = _facility_with_pet(weight_kg=6)
    run = create_run(facility["id"], label="Pen-V2", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=5)
    res = _reservation(facility["id"], pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03")
    out = api.create_assignment(
        res["id"], create_assignment_payload(run["id"], res["version"]), MGR)
    validate_error(out, "ERR_RUN_NOT_ELIGIBLE")
