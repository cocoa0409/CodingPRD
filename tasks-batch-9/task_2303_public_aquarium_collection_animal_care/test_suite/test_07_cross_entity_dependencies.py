"""Gates that read state living on an entity other than the one being moved.

Every world in this module is assembled through the published endpoints, so the
state the far-away gate consults is genuine and observable through its own GET.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    CLEARANCE_OFFICER_ID,
    DIRECTOR_HEADERS,
    DIRECTOR_ID,
    Builder,
    factories,
    make_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_LIFE_SUPPORT_ALARM,
    ERR_PERMIT_NOT_ISSUED,
    ERR_PERMIT_TYPE_MISMATCH,
)


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating the optional fractional part."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def briefed_session_on_a_quiet_plant(build: Builder) -> Dict[str, Any]:
    """A COLD_MARINE plant, an OPEN exhibit running guest programmes, one booking.

    The session itself satisfies every condition the transition endpoint places
    on the session row: it is SCHEDULED, the safety briefing is confirmed and
    only 4 of 6 guest places are taken.
    """
    build.set_clock("2026-08-01T12:00:00Z")
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=True)
    session = build.book_session(
        exhibit["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T11:00:00Z",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    return {"plant": plant, "exhibit": exhibit, "session": session}


def wild_collection_request_pending_permit(build: Builder) -> Dict[str, Any]:
    """A submitted WILD_COLLECTION request parked on the permit road."""
    world = build.approved_line(
        species_overrides={
            "taxon_group": "TELEOST",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "bioload_units_per_specimen": 12.0,
            "base_quarantine_days": 30,
            "wild_take_quota_annual": 10,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    world["institution"] = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=80.00
    )
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=world["institution"]["id"],
    )
    world["request"] = build.submit_acquisition(request["id"])
    return world


def cites_specimen_offered_to_a_receiver(build: Builder) -> Dict[str, Any]:
    """A CITES_APPENDIX_II animal through quarantine, plus a SUBMITTED TRANSPORT permit.

    The species is protected, so the acquisition took the permit road under a
    POSSESSION permit and the transport dossier needs `CITES_PERMIT` on top of
    the TRANSPORT base set.
    """
    world = build.approved_line(
        species_overrides={
            "taxon_group": "TELEOST",
            "protection_status": "CITES_APPENDIX_II",
            "sustainability_rating": "GREEN",
            "bioload_units_per_specimen": 6.0,
            "base_quarantine_days": 30,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    world["institution"] = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=88.00
    )
    request = build.create_acquisition(world["entry"], source_type="CAPTIVE_BRED", requested_count=1)
    request = build.submit_acquisition(request["id"])
    world["possession_permit"] = build.issue_permit(
        request["id"],
        "POSSESSION",
        ["HEALTH_CERTIFICATE", "POSSESSION_AFFIDAVIT", "CITES_PERMIT"],
    )
    world["request"] = build.clear_acquisition(request["id"], world["species"]["id"])
    world = build.cleared_specimen(world=build.quarantined_specimen(world=world))
    transport = build.draft_permit(
        world["request"]["id"],
        "TRANSPORT",
        ["HEALTH_CERTIFICATE", "TRANSPORT_PLAN", "CITES_PERMIT"],
    )
    world["transport_permit"] = build.submit_permit(transport["id"])
    return world


# --------------------------------------------------------------------------
# Session activation reads the serving plant, not merely the exhibit posture
# --------------------------------------------------------------------------
def test_session_activation_is_refused_while_the_serving_plant_holds_a_warning_band(api, build):
    """A WARNING plant blocks activation even though the exhibit is only RESTRICTED.

    PRD §2.8: "The exhibit's serving plant has `alarm_state` equal to `NORMAL` and `redundancy_overdue` false — `ERR_LIFE_SUPPORT_ALARM` (409). Applies to session transitions. This is stricter than rule 15, because a plant in `WARNING` leaves the posture merely `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_session_activate_requires_quiet_plant_not_just_open_posture
    """
    world = briefed_session_on_a_quiet_plant(build)

    reading = build.append_graded_reading(world["plant"], "WARNING", taken_at="2026-08-01T10:00:00Z")
    assert reading["severity"] == "WARNING", reading

    plant = build.get_plant(world["plant"]["id"])
    assert plant["alarm_state"] == "WARNING", plant

    # The near condition — rule 15, "the target exhibit's posture is not CLOSED" — passes.
    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assert exhibit["posture"] == "RESTRICTED", exhibit
    assert exhibit["last_posture_reason"] == "LSS_WARNING", exhibit

    response = api.transition_interaction_session(
        world["session"]["id"], {"action": "ACTIVATE"}, AQUARIST_HEADERS
    )
    validate_error(response, ERR_LIFE_SUPPORT_ALARM, 409)

    session = build.get_session(world["session"]["id"])
    assert session["status"] == "SCHEDULED", session
    assert session["suspension_reason"] is None, session
    # A WARNING band never suspends a booking; only a CLOSED posture does.
    assert build.get_exhibit(world["exhibit"]["id"])["suspended_session_count"] == 0


def test_session_activation_is_still_refused_while_the_hysteresis_run_is_incomplete(api, build):
    """Two clean readings leave the plant in WARNING, so activation still fails.

    PRD §3.1: "A `NORMAL` reading is where the hysteresis lives: the plant returns to `NORMAL` only when this reading brings `consecutive_normal_readings` to 3 or more; while the incremented count is still below 3 the plant holds `WARNING` and merely records the progress."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_session_activate_requires_quiet_plant_not_just_open_posture
    """
    world = briefed_session_on_a_quiet_plant(build)
    build.append_graded_reading(world["plant"], "WARNING", taken_at="2026-08-01T10:00:00Z")
    build.append_graded_reading(world["plant"], "NORMAL", taken_at="2026-08-01T10:30:00Z")
    build.append_graded_reading(world["plant"], "NORMAL", taken_at="2026-08-01T11:00:00Z")

    plant = build.get_plant(world["plant"]["id"])
    assert plant["alarm_state"] == "WARNING", plant
    assert plant["consecutive_normal_readings"] == 2, plant

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assert exhibit["posture"] == "RESTRICTED", exhibit

    response = api.transition_interaction_session(
        world["session"]["id"], {"action": "ACTIVATE"}, AQUARIST_HEADERS
    )
    validate_error(response, ERR_LIFE_SUPPORT_ALARM, 409)
    assert build.get_session(world["session"]["id"])["status"] == "SCHEDULED"


def test_session_activation_succeeds_once_the_serving_plant_is_back_in_the_normal_band(api, build):
    """The third clean reading clears the plant and the same ACTIVATE goes through.

    PRD §3.9: "the serving plant's `alarm_state` must be exactly `NORMAL` and its `redundancy_overdue` must be false, else `ERR_LIFE_SUPPORT_ALARM` — which is stricter than the posture rule, since a plant in `WARNING` leaves the posture merely `RESTRICTED`"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_session_activate_requires_quiet_plant_not_just_open_posture
    """
    world = briefed_session_on_a_quiet_plant(build)
    build.append_graded_reading(world["plant"], "WARNING", taken_at="2026-08-01T10:00:00Z")
    build.append_graded_reading(world["plant"], "NORMAL", taken_at="2026-08-01T10:30:00Z")
    build.append_graded_reading(world["plant"], "NORMAL", taken_at="2026-08-01T11:00:00Z")
    build.append_graded_reading(world["plant"], "NORMAL", taken_at="2026-08-01T11:30:00Z")

    plant = build.get_plant(world["plant"]["id"])
    assert plant["alarm_state"] == "NORMAL", plant
    assert plant["redundancy_overdue"] is False, plant

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assert exhibit["posture"] == "OPEN", exhibit
    assert exhibit["last_posture_reason"] is None, exhibit

    response = api.transition_interaction_session(
        world["session"]["id"], {"action": "ACTIVATE"}, AQUARIST_HEADERS
    )
    session = validate_success(response, 200)
    assert session["status"] == "ACTIVE", session
    assert build.get_session(world["session"]["id"])["status"] == "ACTIVE"
    assert build.get_exhibit(world["exhibit"]["id"])["suspended_session_count"] == 0


# --------------------------------------------------------------------------
# Acquisition clearance reads the permit dossier of another entity
# --------------------------------------------------------------------------
def test_clearance_is_refused_while_the_import_permit_is_only_submitted(api, build):
    """A merely SUBMITTED IMPORT permit is not an issued one, so clearance fails.

    PRD §3.5: "On the `PENDING_PERMIT` road it additionally requires at least one permit of the request in `ISSUED` status whose `permit_type` is `IMPORT` when `source_type` is `WILD_COLLECTION` and `POSSESSION` for every other source — the wrong type is `ERR_PERMIT_TYPE_MISMATCH`, no issued permit at all is `ERR_PERMIT_NOT_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_clearance_blocked_until_import_permit_issued
    """
    world = wild_collection_request_pending_permit(build)
    request = world["request"]
    # The request itself is in exactly the right state to be cleared.
    assert request["status"] == "PENDING_PERMIT", request
    assert instant(request["permit_deadline_at"]) == instant("2026-08-31T00:00:00Z"), request
    assert request["sustainability_score"] == 70.00, request
    assert request["sustainability_score_variant"] == "PROVISIONAL", request

    permit = build.draft_permit(
        request["id"], "IMPORT", ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]
    )
    permit = build.submit_permit(permit["id"])
    assert permit["status"] == "SUBMITTED", permit

    response = api.clear_acquisition_request(
        request["id"],
        factories.clearance_payload(build.species_version(world["species"]["id"])),
        make_director_headers(CLEARANCE_OFFICER_ID),
    )
    validate_error(response, ERR_PERMIT_NOT_ISSUED, 409)

    # A rejected clearance recomputes and reserves nothing.
    stored = build.get_acquisition(request["id"])
    assert stored["status"] == "PENDING_PERMIT", stored
    assert stored["sustainability_score"] == 70.00, stored
    assert stored["sustainability_score_variant"] == "PROVISIONAL", stored
    assert stored["quota_units_reserved"] == 0, stored
    assert stored["cleared_by_user_id"] is None, stored
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0


def test_clearance_is_refused_when_the_only_issued_permit_is_of_the_wrong_type(api, build):
    """An ISSUED POSSESSION permit cannot authorise a wild take; only an IMPORT can.

    PRD §2.8: "The permit's `permit_type` matches the context — `ERR_PERMIT_TYPE_MISMATCH` (422). Applies to acquisition clearance and transfer-request creation. A `WILD_COLLECTION` acquisition requires an `IMPORT` permit and any other source requires a `POSSESSION` permit"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_clearance_blocked_until_import_permit_issued
    """
    world = wild_collection_request_pending_permit(build)
    request = world["request"]

    wrong = build.issue_permit(
        request["id"], "POSSESSION", ["HEALTH_CERTIFICATE", "POSSESSION_AFFIDAVIT"]
    )
    assert wrong["status"] == "ISSUED", wrong
    assert wrong["permit_type"] == "POSSESSION", wrong

    response = api.clear_acquisition_request(
        request["id"],
        factories.clearance_payload(build.species_version(world["species"]["id"])),
        make_director_headers(CLEARANCE_OFFICER_ID),
    )
    validate_error(response, ERR_PERMIT_TYPE_MISMATCH, 422)

    stored = build.get_acquisition(request["id"])
    assert stored["status"] == "PENDING_PERMIT", stored
    assert stored["quota_units_reserved"] == 0, stored
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 0


def test_clearance_succeeds_once_the_import_permit_reaches_issued(api, build):
    """Issuing the permit both opens the gate and adds the permit bonus to the score.

    PRD §3.5: "The `FINAL` variant, computed at clearance, adds a permit bonus of 5.0 when any permit of the request has `status` `ISSUED`, and — only when `source_type` is `WILD_COLLECTION` **and** the species' `wild_take_quota_annual` is greater than 0 — subtracts a quota pressure term of 20.0 multiplied by ((`wild_take_quota_reserved` plus `requested_count`) divided by `wild_take_quota_annual`)."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_clearance_blocked_until_import_permit_issued
    """
    world = wild_collection_request_pending_permit(build)
    request = world["request"]

    permit = build.issue_permit(
        request["id"],
        "IMPORT",
        ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"],
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2027-06-01T00:00:00Z",
    )
    assert permit["status"] == "ISSUED", permit

    response = api.clear_acquisition_request(
        request["id"],
        factories.clearance_payload(build.species_version(world["species"]["id"])),
        make_director_headers(CLEARANCE_OFFICER_ID),
    )
    cleared = validate_success(response, 200)
    assert cleared["status"] == "CLEARED", cleared
    # 40 (GREEN) + 10 (WILD_COLLECTION) + 0.25 * 80.00 + 5 (permit bonus) - 20 * (1 / 10).
    assert cleared["sustainability_score"] == 73.00, cleared
    assert cleared["sustainability_score_variant"] == "FINAL", cleared
    assert cleared["quota_units_reserved"] == 1, cleared
    assert cleared["cleared_by_user_id"] == CLEARANCE_OFFICER_ID, cleared

    stored = build.get_acquisition(request["id"])
    assert stored["status"] == "CLEARED", stored
    assert stored["sustainability_score"] == 73.00, stored
    assert build.get_species(world["species"]["id"])["wild_take_quota_reserved"] == 1


# --------------------------------------------------------------------------
# Transfer approval reads a permit owned by the acquisition request
# --------------------------------------------------------------------------
def test_transfer_approval_is_refused_while_the_transport_permit_is_only_submitted(api, build):
    """The transfer row is impeccable; the TRANSPORT permit three hops away is not.

    PRD §3.8: "When the specimen's species has `permit_required` true, `transport_permit_id` must be non-null and must reference a permit whose `permit_type` is `TRANSPORT` and whose `status` is `ISSUED`, else `ERR_PERMIT_NOT_ISSUED`; and the receiving institution must still be eligible at the moment of approval, not merely at submission."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_transfer_approval_requires_issued_transport_permit
    """
    world = cites_specimen_offered_to_a_receiver(build)
    assert build.get_species(world["species"]["id"])["permit_required"] is True
    assert world["transport_permit"]["status"] == "SUBMITTED", world["transport_permit"]

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        world["institution"]["id"],
        "2026-09-05T00:00:00Z",
        transport_permit_id=world["transport_permit"]["id"],
        welfare_conditions=[
            "WATER_CHEMISTRY_MATCH",
            "TRANSPORT_OXYGEN_PLAN",
            "CITES_TRANSPORT_CLEARANCE",
        ],
    )
    transfer = build.submit_transfer(transfer["id"])
    assert transfer["status"] == "SUBMITTED", transfer

    response = api.decide_transfer_request(transfer["id"], {"decision": "APPROVE"}, DIRECTOR_HEADERS)
    validate_error(response, ERR_PERMIT_NOT_ISSUED, 409)

    stored = validate_success(api.get_transfer_request(transfer["id"], DIRECTOR_HEADERS), 200)
    assert stored["status"] == "SUBMITTED", stored
    assert stored["decided_by_user_id"] is None, stored
    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["disposition_status"] == "TRANSFER_PENDING", specimen
    assert specimen["pre_transfer_disposition"] == "CLEARED", specimen


def test_transfer_approval_is_refused_when_no_transport_permit_is_named_at_all(api, build):
    """A protected species demands a non-null `transport_permit_id` before approval.

    PRD §3.8: "When the specimen's species has `permit_required` true, `transport_permit_id` must be non-null and must reference a permit whose `permit_type` is `TRANSPORT` and whose `status` is `ISSUED`, else `ERR_PERMIT_NOT_ISSUED`"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_transfer_approval_requires_issued_transport_permit
    """
    world = cites_specimen_offered_to_a_receiver(build)

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        world["institution"]["id"],
        "2026-09-05T00:00:00Z",
        welfare_conditions=[
            "WATER_CHEMISTRY_MATCH",
            "TRANSPORT_OXYGEN_PLAN",
            "CITES_TRANSPORT_CLEARANCE",
        ],
    )
    assert transfer["transport_permit_id"] is None, transfer
    transfer = build.submit_transfer(transfer["id"])
    assert transfer["status"] == "SUBMITTED", transfer

    response = api.decide_transfer_request(transfer["id"], {"decision": "APPROVE"}, DIRECTOR_HEADERS)
    validate_error(response, ERR_PERMIT_NOT_ISSUED, 409)

    stored = validate_success(api.get_transfer_request(transfer["id"], DIRECTOR_HEADERS), 200)
    assert stored["status"] == "SUBMITTED", stored
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "TRANSFER_PENDING"


def test_transfer_approval_succeeds_once_the_transport_permit_is_issued(api, build):
    """Issuing the TRANSPORT permit lets the identical APPROVE through.

    PRD §3.8: "`APPROVE` belongs to the compliance director. It moves a `SUBMITTED` request to `APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_transfer_approval_requires_issued_transport_permit
    """
    world = cites_specimen_offered_to_a_receiver(build)

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        world["institution"]["id"],
        "2026-09-05T00:00:00Z",
        transport_permit_id=world["transport_permit"]["id"],
        welfare_conditions=[
            "WATER_CHEMISTRY_MATCH",
            "TRANSPORT_OXYGEN_PLAN",
            "CITES_TRANSPORT_CLEARANCE",
        ],
    )
    transfer = build.submit_transfer(transfer["id"])

    issued = build.decide_permit(
        world["transport_permit"]["id"],
        "ISSUE",
        valid_from="2026-08-31T00:00:00Z",
        valid_until="2026-10-01T00:00:00Z",
    )
    assert issued["status"] == "ISSUED", issued
    assert issued["permit_type"] == "TRANSPORT", issued

    response = api.decide_transfer_request(transfer["id"], {"decision": "APPROVE"}, DIRECTOR_HEADERS)
    approved = validate_success(response, 200)
    assert approved["status"] == "APPROVED", approved
    assert approved["decided_by_user_id"] == DIRECTOR_ID, approved

    stored = validate_success(api.get_transfer_request(transfer["id"], DIRECTOR_HEADERS), 200)
    assert stored["status"] == "APPROVED", stored
    assert stored["transport_permit_id"] == world["transport_permit"]["id"], stored
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "TRANSFER_PENDING"
