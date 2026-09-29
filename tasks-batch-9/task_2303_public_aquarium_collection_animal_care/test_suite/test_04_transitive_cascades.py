"""Transitive cascades: one write that propagates two and three entities deep.

Every world is assembled through the published endpoints, so each test starts
from the empty database with the logical clock parked at the epoch. Each cascade
link is checked by re-reading the affected entity through its own GET endpoint.
"""
from typing import Any, Dict, List

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    NECROPSY_OPENER_ID,
    VET_HEADERS,
    assertions,
    factories,
    get_success_data,
    validate_error,
)
from test_helpers.api_errors import (
    ERR_ENTITY_TERMINAL,
    ERR_EXHIBIT_CLOSED,
    ERR_INTERACTION_PROGRAM_DISABLED,
)

IMPORT_DOCUMENTS = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]

SPECIES_OVERRIDES = {
    "taxon_group": "TELEOST",
    "protection_status": "UNLISTED",
    "sustainability_rating": "GREEN",
    "bioload_units_per_specimen": 12.0,
    "base_quarantine_days": 30,
    "wild_take_quota_annual": 4,
}
ENTRY_OVERRIDES = {"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"}
PLANT_OVERRIDES = {"redundancy_test_interval_days": 90}


def _instant_seconds(value: str) -> str:
    """An ISO-8601 UTC instant reduced to whole seconds for comparison.

    PRD §2.4 fixes the fractional precision of `created_at` only; the precision
    used to render other instants such as a permit's `valid_until` is left open,
    so comparisons here pin the instant and not its rendering.
    """
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return text + "Z"



# --------------------------------------------------------------------------
# Shared helpers (setup only; every call here must succeed)
# --------------------------------------------------------------------------
def _read_plan_entry(build, entry_id: str) -> Dict[str, Any]:
    """Read one collection plan entry back through its own endpoint."""
    return get_success_data(build.api.get_collection_plan_entry(entry_id, CURATOR_HEADERS))


def _read_necropsy_cases(build, specimen_id: str) -> List[Dict[str, Any]]:
    """Read a specimen's necropsy investigations through its own case listing."""
    return get_success_data(
        build.api.list_specimen_veterinary_cases(
            specimen_id, VET_HEADERS, {"case_type": "NECROPSY"}
        )
    )


def _clear_quarantine_for_all(build, specimen_ids: List[str]) -> List[Dict[str, Any]]:
    """Walk every specimen out of quarantine: two clean exams, then a CLEAR review."""
    cases = [build.quarantine_case_of(specimen_id) for specimen_id in specimen_ids]
    exams = {
        specimen_id: build.record_clean_exams(specimen_id, 2) for specimen_id in specimen_ids
    }
    build.advance_to(max(case["projected_release_at"] for case in cases))
    for specimen_id in specimen_ids:
        build.close_clean_exams(exams[specimen_id])
    return [build.review_quarantine(case["id"], "CLEAR") for case in cases]


def _exhibit_with_two_scheduled_sessions(build) -> Dict[str, Any]:
    """An OPEN exhibit whose interaction programme carries two SCHEDULED sessions."""
    build.advance_to("2026-08-01T12:00:00Z")
    plant = build.create_plant(design_habitat="COLD_MARINE", **PLANT_OVERRIDES)
    exhibit = build.create_exhibit(
        plant, bioload_capacity_units=100.0, interaction_program_enabled=True
    )
    first = build.book_session(
        exhibit["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T11:00:00Z",
        program_type="FEEDING_ENCOUNTER",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    # A gap of exactly 30 minutes clears the turnover buffer, so both bookings
    # stand and both are in scope for the cascade.
    second = build.book_session(
        exhibit["id"],
        "2026-08-02T11:30:00Z",
        "2026-08-02T12:30:00Z",
        program_type="FEEDING_ENCOUNTER",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    assert first["status"] == "SCHEDULED"
    assert second["status"] == "SCHEDULED"
    assertions.assert_posture(build.get_exhibit(exhibit["id"]), "OPEN", None)
    return {"plant": plant, "exhibit": exhibit, "first": first, "second": second}


def _collection_with_downstream_wild_request(build, held_count: int) -> Dict[str, Any]:
    """`held_count` specimens on exhibit, plus a CLEARED wild-collection request behind them.

    The second request holds one unit of the species' annual wild-take
    allowance and carries an `ISSUED` import permit, so the plan line above it
    has a live pipeline two entities deep.
    """
    world = build.approved_line(
        plant_overrides=dict(PLANT_OVERRIDES),
        species_overrides=dict(SPECIES_OVERRIDES),
        entry_overrides=dict(ENTRY_OVERRIDES),
    )
    species_id = world["species"]["id"]

    # The animals in the building come from a captive-bred request, which needs
    # no permit and reserves no wild-take quota.
    held = build.create_acquisition(
        world["entry"], source_type="CAPTIVE_BRED", requested_count=held_count
    )
    held = build.submit_acquisition(held["id"])
    held = build.clear_acquisition(held["id"], species_id)
    specimens = [
        build.accession_specimen(world["species"], held) for _ in range(held_count)
    ]
    specimen_ids = [specimen["id"] for specimen in specimens]
    _clear_quarantine_for_all(build, specimen_ids)
    for specimen_id in specimen_ids:
        build.place(specimen_id, world["exhibit"]["id"])

    # The pipeline still in flight: a cleared wild-collection request with an
    # issued import permit beneath the same plan line.
    institution = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=80.0
    )
    pending = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    pending = build.submit_acquisition(pending["id"])
    permit = build.issue_permit(pending["id"], "IMPORT", IMPORT_DOCUMENTS)
    pending = build.clear_acquisition(pending["id"], species_id)

    world.update(
        {
            "held_request": build.get_acquisition(held["id"]),
            "specimen_ids": specimen_ids,
            "institution": institution,
            "pending_request": pending,
            "permit": build.get_permit(permit["id"]),
        }
    )
    return world


def _cleared_wild_request_on_a_permit_expiring_on(build, valid_until: str) -> Dict[str, Any]:
    """A CLEARED wild-collection request holding quota on a permit that expires at `valid_until`."""
    world = build.approved_line(
        plant_overrides=dict(PLANT_OVERRIDES),
        species_overrides=dict(SPECIES_OVERRIDES),
        entry_overrides=dict(ENTRY_OVERRIDES),
    )
    institution = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=80.0
    )
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request = build.submit_acquisition(request["id"])
    permit = build.issue_permit(
        request["id"],
        "IMPORT",
        IMPORT_DOCUMENTS,
        valid_from="2026-08-01T00:00:00Z",
        valid_until=valid_until,
    )
    request = build.clear_acquisition(request["id"], world["species"]["id"])

    assert permit["status"] == "ISSUED"
    assert _instant_seconds(permit["valid_until"]) == _instant_seconds(valid_until)
    assert request["status"] == "CLEARED"
    assert request["quota_units_reserved"] == 1
    # 40.0 for GREEN plus 10.0 for WILD_COLLECTION plus a quarter of the
    # partner's welfare audit, then the issued-permit bonus less the quota
    # pressure of one unit against an annual allowance of four.
    assertions.assert_scaled_equal(request["sustainability_score"], 70.00)
    assert request["sustainability_score_variant"] == "FINAL"
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 1

    world.update({"institution": institution, "request": request, "permit": permit})
    return world


# --------------------------------------------------------------------------
# Cascade A: a critical reading closes the exhibit and disables the programme
# --------------------------------------------------------------------------
def test_critical_reading_closes_the_exhibit_suspends_its_sessions_and_disables_the_programme(
    build, api
):
    """One reading walks plant, exhibit, sessions and the programme flag in a single call.

    PRD §3.1: "When a reading drives a plant into `CRITICAL`, five things happen
    in order: the reading is scored and stored; the plant's band, counters and
    `water_quality_index` are updated; every exhibit the plant serves recomputes
    its posture and lands on `CLOSED` with `last_posture_reason` set to
    `LSS_CRITICAL`; every interaction session on each of those exhibits whose
    `status` is `SCHEDULED` or `ACTIVE` moves to `SUSPENDED` with
    `suspension_reason` set to `EXHIBIT_CLOSED`, processed in ascending
    `created_at` order, each incrementing the exhibit's
    `suspended_session_count`; and any exhibit whose `suspended_session_count`
    has thereby reached 2 has `interaction_program_enabled` set to false."

    Design: Difficulty/transitive_cascade/cascade_a_critical_reading_closes_exhibit_and_auto_disables_programme
    """
    world = _exhibit_with_two_scheduled_sessions(build)
    exhibit_id = world["exhibit"]["id"]

    reading = build.append_graded_reading(world["plant"], "CRITICAL")
    assertions.assert_water_quality_reading(reading)
    assert reading["severity"] == "CRITICAL"
    assert reading["breach_parameters"] == ["temperature_c"]
    # One parameter at exactly twice its tolerance: 100 - 6.0*2.0 - 15.0*2.0.
    assertions.assert_scaled_equal(reading["water_quality_index_snapshot"], 58.00)

    plant = build.get_plant(world["plant"]["id"])
    assertions.assert_alarm(plant, "CRITICAL", normals=0, breaches=1)
    assertions.assert_scaled_equal(plant["water_quality_index"], 58.00)

    exhibit = build.get_exhibit(exhibit_id)
    assertions.assert_posture(exhibit, "CLOSED", "LSS_CRITICAL")
    assert exhibit["suspended_session_count"] == 2
    assert exhibit["interaction_program_enabled"] is False

    for session in (world["first"], world["second"]):
        suspended = build.get_session(session["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "EXHIBIT_CLOSED"

    # A fresh booking now faces both a closed exhibit and a disabled programme;
    # the closure is the higher-ranked complaint.
    refused = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit_id, "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", max_guests=6
        ),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_EXHIBIT_CLOSED, 409)


def test_warning_reading_restricts_the_exhibit_without_touching_its_sessions(build):
    """The session and programme links belong to the critical band alone.

    PRD §3.1: "A `WARNING` reading moves the plant to `WARNING`, increments
    `consecutive_breach_readings`, zeroes `consecutive_normal_readings`, updates
    `water_quality_index`, and drives every exhibit the plant serves to
    `RESTRICTED` with `last_posture_reason` set to `LSS_WARNING`."

    Design: Difficulty/transitive_cascade/cascade_a_critical_reading_closes_exhibit_and_auto_disables_programme
    """
    world = _exhibit_with_two_scheduled_sessions(build)

    reading = build.append_graded_reading(world["plant"], "WARNING")
    assert reading["severity"] == "WARNING"
    # One parameter at exactly its tolerance: 100 - 6.0*1.0 - 15.0*1.0.
    assertions.assert_scaled_equal(reading["water_quality_index_snapshot"], 79.00)

    plant = build.get_plant(world["plant"]["id"])
    assertions.assert_alarm(plant, "WARNING", normals=0, breaches=1)

    # The posture link fires and stops there: the chain that suspends sessions
    # and disables the programme is not part of the warning transition.
    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_posture(exhibit, "RESTRICTED", "LSS_WARNING")
    assert exhibit["suspended_session_count"] == 0
    assert exhibit["interaction_program_enabled"] is True

    for session in (world["first"], world["second"]):
        untouched = build.get_session(session["id"])
        assert untouched["status"] == "SCHEDULED"
        assert untouched["suspension_reason"] is None


def test_water_quality_recovery_reopens_the_exhibit_but_leaves_the_programme_disabled(
    build, api
):
    """Clean readings restore the posture; the suspensions and the flag survive.

    PRD §3.1: "sessions that were suspended while the plant was in trouble are
    **not** automatically reinstated; a director must reinstate them explicitly."

    Design: Difficulty/transitive_cascade/cascade_a_critical_reading_closes_exhibit_and_auto_disables_programme
    """
    world = _exhibit_with_two_scheduled_sessions(build)
    exhibit_id = world["exhibit"]["id"]
    build.append_graded_reading(world["plant"], "CRITICAL")

    # Three clean readings, each sampled an hour after the last: the second
    # lifts the plant to WARNING without resetting the run, and the third clears
    # it back to NORMAL.
    for _ in range(3):
        build.advance(hours=1)
        build.append_graded_reading(world["plant"], "NORMAL")

    plant = build.get_plant(world["plant"]["id"])
    assertions.assert_alarm(plant, "NORMAL", normals=3, breaches=0)
    assertions.assert_scaled_equal(plant["water_quality_index"], 100.00)

    exhibit = build.get_exhibit(exhibit_id)
    assertions.assert_posture(exhibit, "OPEN", None)
    # The counter is a matter of record and the programme stays off until a
    # director re-enables it.
    assert exhibit["suspended_session_count"] == 2
    assert exhibit["interaction_program_enabled"] is False

    for session in (world["first"], world["second"]):
        still_suspended = build.get_session(session["id"])
        assert still_suspended["status"] == "SUSPENDED"
        assert still_suspended["suspension_reason"] == "EXHIBIT_CLOSED"

    # With the exhibit OPEN again the closure complaint is gone, so the disabled
    # programme is now the reason a new booking is refused.
    refused = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit_id, "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", max_guests=6
        ),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_INTERACTION_PROGRAM_DISABLED, 409)


# --------------------------------------------------------------------------
# Cascade B: a death suspends the plan line and revokes the permit behind it
# --------------------------------------------------------------------------
def test_last_specimen_mortality_suspends_the_plan_line_and_revokes_the_permit_beneath_it(
    build,
):
    """A death reaches three entities deep: exhibit, plan line, request, permit and quota.

    PRD §3.7: "If that exhibit now holds no specimen of the dead animal's
    species, the `APPROVED` collection plan entry for that exhibit-and-species
    pair moves to `SUSPENDED` with `suspension_reason` set to
    `LAST_SPECIMEN_LOST`. Every acquisition request beneath that plan line whose
    `status` is `DRAFT`, `PENDING_PERMIT`, `READY_FOR_CLEARANCE` or `CLEARED`
    moves to `CANCELLED` with `closure_reason` set to `PLAN_SUSPENDED`,
    releasing its `quota_units_reserved` into the species' `wild_take_quota_reserved`.
    And every permit of those requests in `DRAFT`, `SUBMITTED`, `INFO_REQUESTED`
    or `ISSUED` moves to `REVOKED` with `decision_reason` set to
    `ACQUISITION_CANCELLED`."

    Design: Difficulty/transitive_cascade/cascade_b_mortality_suspends_plan_and_revokes_downstream_permit
    """
    world = _collection_with_downstream_wild_request(build, held_count=1)
    specimen_id = world["specimen_ids"][0]

    build.declare_mortality(specimen_id, cause_note="found on the substrate at dawn")

    specimen = build.get_specimen(specimen_id)
    assert specimen["disposition_status"] == "DECEASED"
    assert specimen["health_status"] == "DECEASED_PENDING_NECROPSY"

    necropsies = _read_necropsy_cases(build, specimen_id)
    assert len(necropsies) == 1
    assert necropsies[0]["status"] == "OPEN"
    assert necropsies[0]["case_type"] == "NECROPSY"
    assert necropsies[0]["opened_by_user_id"] == NECROPSY_OPENER_ID

    # A dead animal contributes nothing to the ledger, so the exhibit empties
    # and reopens.
    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_scaled_equal(exhibit["occupied_bioload_units"], 0.00)
    assertions.assert_scaled_equal(exhibit["bioload_utilization_pct"], 0.00)
    assertions.assert_posture(exhibit, "OPEN", None)

    entry = _read_plan_entry(build, world["entry"]["id"])
    assert entry["status"] == "SUSPENDED"
    assert entry["suspension_reason"] == "LAST_SPECIMEN_LOST"

    pending = build.get_acquisition(world["pending_request"]["id"])
    assert pending["status"] == "CANCELLED"
    assert pending["closure_reason"] == "PLAN_SUSPENDED"
    assert pending["quota_units_reserved"] == 0

    permit = build.get_permit(world["permit"]["id"])
    assert permit["status"] == "REVOKED"
    assert permit["decision_reason"] == "ACQUISITION_CANCELLED"

    # The released reservation goes back into the species' annual allowance.
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0

    # Left alone: the terminal request that put the animal in the building keeps
    # its fulfilment, and the already-CLEARED quarantine case is not failed.
    held = build.get_acquisition(world["held_request"]["id"])
    assert held["status"] == "FULFILLED"
    assert held["fulfilled_count"] == 1
    assert held["closure_reason"] is None

    quarantine_case = build.quarantine_case_of(specimen_id)
    assert quarantine_case["status"] == "CLEARED"
    assert quarantine_case["failure_reason"] is None


def test_mortality_leaves_the_plan_line_alone_while_another_specimen_of_the_species_remains(
    build,
):
    """The plan-line link is conditional, so the requests and permits beneath it survive.

    PRD §3.7: "If that exhibit now holds no specimen of the dead animal's
    species, the `APPROVED` collection plan entry for that exhibit-and-species
    pair moves to `SUSPENDED` with `suspension_reason` set to
    `LAST_SPECIMEN_LOST`."

    Design: Difficulty/transitive_cascade/cascade_b_mortality_suspends_plan_and_revokes_downstream_permit
    """
    world = _collection_with_downstream_wild_request(build, held_count=2)
    dead_id, survivor_id = world["specimen_ids"]

    build.declare_mortality(dead_id, cause_note="found on the substrate at dawn")

    assert build.get_specimen(dead_id)["disposition_status"] == "DECEASED"

    survivor = build.get_specimen(survivor_id)
    assert survivor["disposition_status"] == "ON_EXHIBIT"
    assert survivor["health_status"] == "HEALTHY"
    assert survivor["exhibit_id"] == world["exhibit"]["id"]

    # The ledger drops by exactly the dead animal's units.
    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_scaled_equal(exhibit["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(exhibit["bioload_utilization_pct"], 12.00)

    # The exhibit still holds a specimen of the species, so the conditional link
    # does not fire and nothing beneath the plan line is dismantled.
    entry = _read_plan_entry(build, world["entry"]["id"])
    assert entry["status"] == "APPROVED"
    assert entry["suspension_reason"] is None

    pending = build.get_acquisition(world["pending_request"]["id"])
    assert pending["status"] == "CLEARED"
    assert pending["closure_reason"] is None
    assert pending["quota_units_reserved"] == 1

    permit = build.get_permit(world["permit"]["id"])
    assert permit["status"] == "ISSUED"
    assert permit["decision_reason"] is None

    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 1


def test_second_mortality_declaration_against_a_dead_specimen_is_terminal(build, api):
    """The cascade cannot be run twice: the second declaration is refused as terminal.

    PRD §3.7: "A second declaration against an already-`DECEASED` specimen is
    `ERR_ENTITY_TERMINAL`, not `ERR_INVALID_STATE`."

    Design: Difficulty/transitive_cascade/cascade_b_mortality_suspends_plan_and_revokes_downstream_permit
    """
    world = _collection_with_downstream_wild_request(build, held_count=1)
    specimen_id = world["specimen_ids"][0]
    build.declare_mortality(specimen_id, cause_note="found on the substrate at dawn")

    refused = api.declare_mortality(
        specimen_id, factories.mortality_payload(build.now), VET_HEADERS
    )
    validate_error(refused, ERR_ENTITY_TERMINAL, 409)

    # The refusal changes nothing: one necropsy investigation, and the released
    # quota is not released a second time.
    assert len(_read_necropsy_cases(build, specimen_id)) == 1
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0
    assert build.get_acquisition(world["pending_request"]["id"])["quota_units_reserved"] == 0


# --------------------------------------------------------------------------
# Cascade D: a clock advance expires the permit and releases the wild quota
# --------------------------------------------------------------------------
def test_clock_advance_to_permit_expiry_rejects_the_request_and_releases_the_quota(build):
    """Setting the clock to `valid_until` runs all three observable expiry links.

    PRD §3.5: "When the logical clock advances to or past an `ISSUED` permit's
    `valid_until`, four links run for that permit. The permit moves to the
    terminal `EXPIRED`. Its acquisition request, if `PENDING_PERMIT` or
    `CLEARED`, moves to the terminal `REJECTED` with `closure_reason` set to
    `PERMIT_EXPIRED` ... That request's `quota_units_reserved` is released back
    into the species' `wild_take_quota_reserved` and set to 0."

    Design: Difficulty/transitive_cascade/cascade_d_clock_advance_expires_permit_and_releases_wild_quota
    """
    world = _cleared_wild_request_on_a_permit_expiring_on(build, "2026-09-01T00:00:00Z")

    # The boundary is inclusive: the instant the permit's validity names is
    # already too late.
    build.advance_to("2026-09-01T00:00:00Z")

    permit = build.get_permit(world["permit"]["id"])
    assert permit["status"] == "EXPIRED"

    request = build.get_acquisition(world["request"]["id"])
    assert request["status"] == "REJECTED"
    assert request["closure_reason"] == "PERMIT_EXPIRED"
    assert request["quota_units_reserved"] == 0
    # The rejection is not a re-scoring: the score stored at clearance stands.
    assertions.assert_scaled_equal(request["sustainability_score"], 70.00)
    assert request["sustainability_score_variant"] == "FINAL"

    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0

    # The plan line above the request is not part of the chain.
    entry = _read_plan_entry(build, world["entry"]["id"])
    assert entry["status"] == "APPROVED"
    assert entry["suspension_reason"] is None


def test_clock_advance_one_second_short_of_expiry_leaves_the_whole_chain_intact(build):
    """A permit whose `valid_until` the clock has not yet reached expires nothing.

    PRD §3.5: "When the logical clock advances to or past an `ISSUED` permit's
    `valid_until`, four links run for that permit."

    Design: Difficulty/transitive_cascade/cascade_d_clock_advance_expires_permit_and_releases_wild_quota
    """
    world = _cleared_wild_request_on_a_permit_expiring_on(build, "2026-09-01T00:00:00Z")

    build.advance_to("2026-08-31T23:59:59Z")

    assert build.get_permit(world["permit"]["id"])["status"] == "ISSUED"

    request = build.get_acquisition(world["request"]["id"])
    assert request["status"] == "CLEARED"
    assert request["closure_reason"] is None
    assert request["quota_units_reserved"] == 1

    # The allowance is still held, so a competing wild request would still face
    # the reservation.
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 1


def test_a_later_clock_advance_does_not_run_the_expiry_cascade_a_second_time(build):
    """Only `ISSUED` permits expire, so the released quota is not released twice.

    PRD §3.5: "When the logical clock advances to or past an `ISSUED` permit's
    `valid_until`, four links run for that permit. The permit moves to the
    terminal `EXPIRED`."

    Design: Difficulty/transitive_cascade/cascade_d_clock_advance_expires_permit_and_releases_wild_quota
    """
    world = _cleared_wild_request_on_a_permit_expiring_on(build, "2026-09-01T00:00:00Z")
    build.advance_to("2026-09-01T00:00:00Z")
    assert build.get_permit(world["permit"]["id"])["status"] == "EXPIRED"

    build.advance_to("2026-09-02T00:00:00Z")

    assert build.get_permit(world["permit"]["id"])["status"] == "EXPIRED"

    request = build.get_acquisition(world["request"]["id"])
    assert request["status"] == "REJECTED"
    assert request["closure_reason"] == "PERMIT_EXPIRED"
    assert request["quota_units_reserved"] == 0

    # A second release would drive the species' running total below zero.
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0
