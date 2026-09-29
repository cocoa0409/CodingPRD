"""Validation corners: pagination, temporal bounds, habitat consistency and the
session activation gates of the Public Aquarium Collection & Animal Care API.

Every test builds its own world through the published endpoints; the logical clock
starts at 2026-08-01T00:00:00Z (PRD §2.5) and the database is empty.
"""
from datetime import datetime

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    PLAN_APPROVER_ID,
    VET_HEADERS,
    assertions,
    factories,
    make_director_headers,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_DIVE_ENCOUNTER_BLOCKED,
    ERR_DUPLICATE_ACTIVE_PLAN_ENTRY,
    ERR_HABITAT_MISMATCH,
    ERR_INTERVAL_INVALID,
    ERR_INVALID_PAGINATION,
    ERR_PERMIT_VALIDITY_TOO_LONG,
    ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED,
    ERR_SAFETY_BRIEFING_REQUIRED,
    ERR_SESSION_IN_PAST,
    ERR_TIMESTAMP_IN_FUTURE,
)


def assert_same_instant(actual, expected):
    """Two API instants denote the same moment, whatever the fractional style."""
    assert actual is not None, f"expected instant {expected}, got null"
    parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    wanted = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed == wanted, f"expected instant {expected}, got {actual}"


def test_species_list_rejects_a_zero_limit_an_oversized_limit_and_a_negative_offset(api, build):
    """Pagination bounds are enforced, and the inclusive upper bound of 100 is legal.

    PRD §2.3: "A `limit` outside the inclusive range 1 to 100, or a negative `offset`,
    is rejected with `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/validations/validation_pagination_limit_zero_and_negative_offset_are_rejected
    """
    build.create_species(common_name="Yelloweye Rockfish")
    build.create_species(common_name="Plumose Anemone", taxon_group="INVERTEBRATE")

    zero_limit = api.list_species(CURATOR_HEADERS, {"limit": 0})
    validate_error(zero_limit, ERR_INVALID_PAGINATION, 400)

    oversized_limit = api.list_species(CURATOR_HEADERS, {"limit": 101})
    validate_error(oversized_limit, ERR_INVALID_PAGINATION, 400)

    negative_offset = api.list_species(CURATOR_HEADERS, {"offset": -1})
    validate_error(negative_offset, ERR_INVALID_PAGINATION, 400)

    # 100 is the inclusive upper bound of the published range, so it must succeed.
    accepted = api.list_species(CURATOR_HEADERS, {"limit": 100})
    rows, meta = validate_paginated(accepted)
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2


def test_water_quality_reading_and_redundancy_test_dated_after_the_clock_are_rejected(api, build):
    """An event instant past the logical clock is refused; exactly the clock is accepted.

    PRD §3.1: "`taken_at` must not be later than the logical clock, on pain of
    `ERR_TIMESTAMP_IN_FUTURE`, and an instant exactly equal to the clock is accepted."

    Design: Corner/validations/validation_event_instant_after_the_clock_is_rejected
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)

    future_reading = api.create_water_quality_reading(
        plant["id"],
        factories.water_quality_reading_payload(taken_at=shift(build.now, seconds=1)),
        AQUARIST_HEADERS,
    )
    validate_error(future_reading, ERR_TIMESTAMP_IN_FUTURE, 422)

    # PRD §3.1: a redundancy test's `performed_at` obeys the same bound.
    future_test = api.create_redundancy_test(
        plant["id"],
        factories.redundancy_test_payload(performed_at=shift(build.now, days=1), result="PASS"),
        AQUARIST_HEADERS,
    )
    validate_error(future_test, ERR_TIMESTAMP_IN_FUTURE, 422)

    on_the_clock = api.create_water_quality_reading(
        plant["id"],
        factories.water_quality_reading_payload(taken_at=build.now),
        AQUARIST_HEADERS,
    )
    reading = validate_success(on_the_clock, 201)
    assert reading["severity"] == "NORMAL"
    assert reading["breach_parameters"] == []
    assertions.assert_scaled_equal(reading["water_quality_index_snapshot"], 100.00)

    # The refused test left no trace on the plant it was aimed at.
    stored = build.get_plant(plant["id"])
    assert stored["last_redundancy_test_at"] is None
    assert stored["last_redundancy_test_result"] is None
    assert stored["alarm_state"] == "NORMAL"
    assertions.assert_scaled_equal(stored["water_quality_index"], 100.00)

    _, meta = validate_paginated(api.list_water_quality_readings(plant["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 1


def test_session_in_the_past_with_equal_bounds_reports_the_past_start_not_the_interval(api, build):
    """The past-start check outranks the interval check on the same booking.

    PRD §2.8: "Rules are evaluated in the fixed ascending order below and the **first**
    failing rule short-circuits the request; no later rule may mask an earlier one, and
    no earlier rule may be skipped in order to report a later one."

    Design: Corner/validations/validation_session_with_equal_bounds_is_rejected_after_the_past_check
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=True)
    build.set_clock("2026-08-01T12:00:00Z")

    # Both in the past (rank 32) and zero-length (rank 33): rank 32 must answer.
    past_and_zero_length = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit["id"],
            "2026-08-01T09:00:00Z",
            "2026-08-01T09:00:00Z",
            max_guests=6,
            guest_count=4,
            safety_briefing_confirmed=True,
        ),
        AQUARIST_HEADERS,
    )
    validate_error(past_and_zero_length, ERR_SESSION_IN_PAST, 422)

    # Moving only the date forward leaves the interval rule as the first failure.
    future_zero_length = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit["id"],
            "2026-08-02T10:00:00Z",
            "2026-08-02T10:00:00Z",
            max_guests=6,
            guest_count=4,
            safety_briefing_confirmed=True,
        ),
        AQUARIST_HEADERS,
    )
    validate_error(future_zero_length, ERR_INTERVAL_INVALID, 422)

    widened = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit["id"],
            "2026-08-02T10:00:00Z",
            "2026-08-02T10:01:00Z",
            max_guests=6,
            guest_count=4,
            safety_briefing_confirmed=True,
        ),
        AQUARIST_HEADERS,
    )
    session = validate_success(widened, 201)
    assert session["status"] == "SCHEDULED"
    assert session["suspension_reason"] is None

    _, meta = validate_paginated(api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 1

    stored_exhibit = build.get_exhibit(exhibit["id"])
    assert stored_exhibit["suspended_session_count"] == 0
    assert stored_exhibit["interaction_program_enabled"] is True


def test_permit_issued_over_a_731_day_window_is_rejected_while_730_days_is_accepted(api, build):
    """An issued permit may span at most 730 days, and exactly 730 days is legal.

    PRD §3.5: "the span between them must be no more than 730 days
    (`ERR_PERMIT_VALIDITY_TOO_LONG`); exactly 730 days is accepted."

    Design: Corner/validations/validation_permit_validity_window_longer_than_730_days_is_rejected
    """
    world = build.approved_line(
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"}
    )
    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=88.00)
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request = build.submit_acquisition(request["id"])
    assert request["status"] == "PENDING_PERMIT"
    permit = build.draft_permit(
        request["id"],
        "IMPORT",
        ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"],
    )
    permit = build.submit_permit(permit["id"])

    valid_from = build.now
    too_long = api.decide_permit(
        permit["id"],
        factories.permit_decision_payload(
            "ISSUE", valid_from=valid_from, valid_until=shift(valid_from, days=731)
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(too_long, ERR_PERMIT_VALIDITY_TOO_LONG, 422)

    # Nothing is persisted by the refused decision.
    refused = build.get_permit(permit["id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["valid_from"] is None
    assert refused["valid_until"] is None
    assert refused["issued_at"] is None
    assert refused["submission_round"] == 1

    accepted = api.decide_permit(
        permit["id"],
        factories.permit_decision_payload(
            "ISSUE", valid_from=valid_from, valid_until=shift(valid_from, days=730)
        ),
        DIRECTOR_HEADERS,
    )
    issued = validate_success(accepted)
    assert issued["status"] == "ISSUED"
    assert_same_instant(issued["valid_from"], valid_from)
    assert_same_instant(issued["valid_until"], shift(valid_from, days=730))
    assert_same_instant(issued["issued_at"], build.now)

    # PRD §3.5: issuance moves the permit only; the request awaits its clearance.
    assert build.get_acquisition(request["id"])["status"] == "PENDING_PERMIT"


def test_habitat_mismatch_refuses_exhibit_creation_and_resurfaces_at_plan_approval(api, build):
    """The habitat rule guards exhibit creation and plan approval, but not the edit.

    PRD §3.2: "the habitat consistency rule is enforced at exhibit creation and again at
    plan-line status actions, but not by this edit — so reassigning an exhibit to a plant
    of a different `design_habitat` succeeds here and surfaces later, when a plan line for
    that exhibit is next approved, suspended, reinstated or retired."

    Design: Corner/validations/validation_habitat_mismatch_blocks_creation_and_later_approval
    """
    cold_plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    tropical_plant = build.create_plant(design_habitat="TROPICAL_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(cold_plant, name="Cold Water Reef")
    species = build.create_species()
    entry = build.create_plan_entry(
        exhibit, species, planned_count=2, sustainability_requirement="GREEN_ONLY"
    )
    assert entry["status"] == "DRAFT"

    mismatched = api.create_exhibit(
        factories.exhibit_payload(
            cold_plant["id"],
            name="Coral Lagoon",
            habitat_type="TROPICAL_MARINE",
            display_volume_liters=60000.0,
            bioload_capacity_units=40.0,
        ),
        CURATOR_HEADERS,
    )
    validate_error(mismatched, ERR_HABITAT_MISMATCH, 422)
    _, meta = validate_paginated(api.list_exhibits(CURATOR_HEADERS, {"limit": 100}))
    assert meta["total_count"] == 1, "the refused creation must not persist an exhibit"

    # The edit deliberately does not enforce the habitat rule.
    repointed = api.update_exhibit(
        exhibit["id"],
        factories.exhibit_patch_payload(
            build.exhibit_version(exhibit["id"]), life_support_system_id=tropical_plant["id"]
        ),
        DIRECTOR_HEADERS,
    )
    edited = validate_success(repointed)
    assert edited["life_support_system_id"] == tropical_plant["id"]
    assert edited["habitat_type"] == "COLD_MARINE"

    # PRD §3.4: approval re-checks the exhibit against its *current* serving plant.
    approval = api.plan_entry_status_action(
        entry["id"],
        factories.plan_status_action_payload("APPROVE"),
        make_director_headers(PLAN_APPROVER_ID),
    )
    validate_error(approval, ERR_HABITAT_MISMATCH, 422)

    unmoved = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert unmoved["status"] == "DRAFT"
    assert unmoved["approved_by_user_id"] is None
    assert unmoved["approved_at"] is None

    stored_exhibit = build.get_exhibit(exhibit["id"])
    assert stored_exhibit["life_support_system_id"] == tropical_plant["id"]
    assert stored_exhibit["habitat_type"] == "COLD_MARINE"


def test_reinstating_a_suspended_plan_line_is_blocked_by_a_newer_approved_line(api, build):
    """Reinstatement collides with the live line created after the suspension.

    PRD §3.4: "**Reinstate** takes a `SUSPENDED` entry back to `APPROVED`, but only when
    no other entry for the same exhibit-and-species pair is currently in `DRAFT` or
    `APPROVED` — otherwise `ERR_DUPLICATE_ACTIVE_PLAN_ENTRY`."

    Design: Corner/validations/validation_reinstate_blocked_by_a_newer_approved_entry_for_the_same_pair
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant)
    species = build.create_species()

    entry_a = build.create_plan_entry(
        exhibit, species, planned_count=2, sustainability_requirement="GREEN_ONLY"
    )
    build.plan_action(entry_a["id"], "APPROVE")
    build.plan_action(entry_a["id"], "SUSPEND")

    # Entry A is SUSPENDED, so the create-time supersede path does not retire it.
    entry_b = build.create_plan_entry(
        exhibit, species, planned_count=3, sustainability_requirement="GREEN_ONLY"
    )
    build.plan_action(entry_b["id"], "APPROVE")

    reinstate = api.plan_entry_status_action(
        entry_a["id"],
        factories.plan_status_action_payload("REINSTATE"),
        make_director_headers(PLAN_APPROVER_ID),
    )
    validate_error(reinstate, ERR_DUPLICATE_ACTIVE_PLAN_ENTRY, 409)

    stored_a = validate_success(api.get_collection_plan_entry(entry_a["id"], CURATOR_HEADERS))
    assert stored_a["status"] == "SUSPENDED"
    assert stored_a["suspension_reason"] == "DIRECTOR_ACTION"
    assert stored_a["superseded_by_entry_id"] is None

    stored_b = validate_success(api.get_collection_plan_entry(entry_b["id"], CURATOR_HEADERS))
    assert stored_b["status"] == "APPROVED"
    assert stored_b["planned_count"] == 3

    rows, meta = validate_paginated(
        api.list_collection_plan_entries(
            CURATOR_HEADERS, {"exhibit_id": exhibit["id"], "status": "APPROVED", "limit": 10}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == entry_b["id"]


def test_placement_onto_a_restricted_exhibit_needs_the_explicit_override_flag(api, build):
    """A RESTRICTED exhibit admits a placement only with the override set true.

    PRD §3.6: "if the exhibit is `RESTRICTED`, `restricted_posture_override` must be
    explicitly true, and if the exhibit is `OPEN` the flag is ignored"

    Design: Corner/validations/validation_restricted_posture_placement_requires_the_override_flag
    """
    world = build.cleared_specimen(
        species_overrides={"bioload_units_per_specimen": 12.0},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    specimen, exhibit, plant = world["specimen"], world["exhibit"], world["plant"]
    assert specimen["disposition_status"] == "CLEARED"
    assert specimen["health_status"] == "HEALTHY"

    # A WARNING reading holds the plant in WARNING, which restricts every served exhibit.
    build.append_graded_reading(plant, "WARNING")
    assertions.assert_alarm(build.get_plant(plant["id"]), "WARNING")
    assertions.assert_posture(build.get_exhibit(exhibit["id"]), "RESTRICTED", "LSS_WARNING")

    version = build.exhibit_version(exhibit["id"])
    refused = api.place_specimen(
        specimen["id"],
        factories.placement_payload(exhibit["id"], version),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_RESTRICTED_POSTURE_OVERRIDE_REQUIRED, 409)

    unmoved = build.get_specimen(specimen["id"])
    assert unmoved["disposition_status"] == "CLEARED"
    assert unmoved["exhibit_id"] is None
    untouched_exhibit = build.get_exhibit(exhibit["id"])
    assert untouched_exhibit["version"] == version, "a refused placement is not a mutation"
    assertions.assert_scaled_equal(untouched_exhibit["occupied_bioload_units"], 0.00)

    accepted = api.place_specimen(
        specimen["id"],
        factories.placement_payload(exhibit["id"], version, restricted_posture_override=True),
        AQUARIST_HEADERS,
    )
    placed = validate_success(accepted)
    assert placed["disposition_status"] == "ON_EXHIBIT"
    assert placed["exhibit_id"] == exhibit["id"]

    loaded = build.get_exhibit(exhibit["id"])
    assertions.assert_scaled_equal(loaded["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(loaded["bioload_utilization_pct"], 12.00)
    # The override authorises the placement; it does not clear the posture.
    assertions.assert_posture(loaded, "RESTRICTED", "LSS_WARNING")


def test_dive_encounter_activation_is_blocked_by_a_critical_care_animal_on_the_exhibit(api, build):
    """A critical-care animal still assigned to the exhibit blocks only the dive programme.

    PRD §3.9: "for a `DIVE_ENCOUNTER` no specimen assigned to the exhibit may be in
    `CRITICAL_CARE` or `DECEASED_PENDING_NECROPSY`, else `ERR_DIVE_ENCOUNTER_BLOCKED`,
    because divers do not share water with an animal in crisis."

    Design: Corner/validations/validation_dive_encounter_activation_blocked_by_a_critical_care_animal
    """
    world = build.specimen_on_exhibit(
        species_overrides={"bioload_units_per_specimen": 12.0},
        exhibit_overrides={"interaction_program_enabled": True},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    specimen, exhibit = world["specimen"], world["exhibit"]
    build.set_clock("2026-09-01T00:00:00Z")

    # PRD §3.8: a TRANSFER_PENDING animal keeps its exhibit_id and its bioload.
    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=88.00)
    transfer = build.draft_transfer(
        specimen["id"],
        institution["id"],
        "2026-10-01T00:00:00Z",
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    build.submit_transfer(transfer["id"])

    treatment = build.open_vet_case(
        specimen["id"],
        "TREATMENT",
        headers=VET_HEADERS,
        opened_at=build.now,
        treatment_start_at=build.now,
        withdrawal_days=10,
        diagnosis_code="BACT-DERM-02",
    )
    build.close_vet_case(treatment["id"], "MORTALITY_REFERRED", "CRITICAL", headers=VET_HEADERS)

    escalated = build.get_specimen(specimen["id"])
    assert escalated["health_status"] == "CRITICAL_CARE"
    assert escalated["disposition_status"] == "TRANSFER_PENDING"
    assert escalated["exhibit_id"] == exhibit["id"]
    assertions.assert_posture(build.get_exhibit(exhibit["id"]), "OPEN", None)

    dive = build.book_session(
        exhibit["id"],
        "2026-09-02T10:00:00Z",
        "2026-09-02T11:00:00Z",
        program_type="DIVE_ENCOUNTER",
        max_guests=4,
        guest_count=2,
        safety_briefing_confirmed=True,
    )
    feeding = build.book_session(
        exhibit["id"],
        "2026-09-02T11:30:00Z",
        "2026-09-02T12:30:00Z",
        program_type="FEEDING_ENCOUNTER",
        max_guests=8,
        guest_count=6,
        safety_briefing_confirmed=True,
    )

    blocked = api.transition_interaction_session(
        dive["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
    )
    validate_error(blocked, ERR_DIVE_ENCOUNTER_BLOCKED, 409)
    unmoved = build.get_session(dive["id"])
    assert unmoved["status"] == "SCHEDULED"
    assert unmoved["suspension_reason"] is None

    # The gate is programme-specific, not a blanket lockout of the exhibit.
    allowed = api.transition_interaction_session(
        feeding["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
    )
    assert validate_success(allowed)["status"] == "ACTIVE"

    assertions.assert_scaled_equal(
        build.get_exhibit(exhibit["id"])["occupied_bioload_units"], 12.00
    )


def test_session_activation_without_a_confirmed_safety_briefing_is_rejected(api, build):
    """Activation demands the safety briefing even though creation does not.

    PRD §3.9: "`safety_briefing_confirmed` must be true, else
    `ERR_SAFETY_BRIEFING_REQUIRED`"

    Design: Corner/validations/validation_activation_without_the_safety_briefing_is_rejected
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=True)

    # PRD §2.8: "a session may be **created** with the flag false, and only activation
    # demands it."
    unbriefed = build.book_session(
        exhibit["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T11:00:00Z",
        program_type="TOUCH_POOL_CONTACT",
        max_guests=12,
        guest_count=8,
        safety_briefing_confirmed=False,
    )
    assert unbriefed["safety_briefing_confirmed"] is False
    assert unbriefed["status"] == "SCHEDULED"

    briefed = build.book_session(
        exhibit["id"],
        "2026-08-02T11:30:00Z",
        "2026-08-02T12:30:00Z",
        program_type="TOUCH_POOL_CONTACT",
        max_guests=12,
        guest_count=8,
        safety_briefing_confirmed=True,
    )

    refused = api.transition_interaction_session(
        unbriefed["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
    )
    validate_error(refused, ERR_SAFETY_BRIEFING_REQUIRED, 422)
    stored = build.get_session(unbriefed["id"])
    assert stored["status"] == "SCHEDULED"
    assert stored["version"] == 1, "a refused activation is not a mutation"

    activated = api.transition_interaction_session(
        briefed["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
    )
    live = validate_success(activated)
    assert live["status"] == "ACTIVE"
    assert live["version"] == 2
