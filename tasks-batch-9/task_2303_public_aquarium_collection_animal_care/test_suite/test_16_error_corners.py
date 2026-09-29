"""Error-surface corners: which refusal wins, and with which id and status.

Every expectation here is taken from the ordered rejection ladder of PRD §2.8 and
the error-to-status catalogue of PRD §5.
"""
from datetime import datetime, timezone
from typing import Dict

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    PERMIT_OFFICER_HEADERS,
    assertions,
    factories,
    make_director_headers,
    make_headers,
    make_liaison_headers,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACCREDITATION_AUDIT_NOT_FOUND,
    ERR_ACQUISITION_REQUEST_NOT_FOUND,
    ERR_COLLECTION_PLAN_ENTRY_NOT_FOUND,
    ERR_DUPLICATE_CODE,
    ERR_EXHIBIT_NOT_FOUND,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INTERACTION_PROGRAM_DISABLED,
    ERR_INTERACTION_SESSION_NOT_FOUND,
    ERR_INVALID_ROLE,
    ERR_LIFE_SUPPORT_SYSTEM_NOT_FOUND,
    ERR_MISSING_USER_CONTEXT,
    ERR_PERMIT_NOT_FOUND,
    ERR_PERMIT_TYPE_MISMATCH,
    ERR_QUARANTINE_CASE_NOT_FOUND,
    ERR_QUOTA_EXCEEDED,
    ERR_RECEIVER_NOT_ELIGIBLE,
    ERR_SPECIES_NOT_FOUND,
    ERR_SPECIMEN_NOT_FOUND,
    ERR_TRANSFER_CONDITIONS_INCOMPLETE,
    ERR_TRANSFER_REQUEST_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_VETERINARY_CASE_NOT_FOUND,
)

# PRD §2.1 demands both identity headers on every request; these header sets omit
# or empty exactly one of them so the identity checks can be probed in isolation.
ROLE_ONLY_HEADERS: Dict[str, str] = {
    "X-User-Role": "CuratorOfCollections",
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": "CuratorOfCollections",
    "Content-Type": "application/json",
}
USER_ID_ONLY_HEADERS: Dict[str, str] = {
    "X-User-ID": "user-curator-01",
    "Content-Type": "application/json",
}


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def same_instant(actual: str, expected: str) -> bool:
    """Two ISO 8601 UTC instants denote the same moment."""
    return parse_utc(actual) == parse_utc(expected)


def test_a_request_without_the_user_id_header_is_rejected_before_anything_else(api, build):
    """An absent or empty X-User-ID is a 401 whatever else is wrong with the call.

    PRD §2.1: "If `X-User-ID` is absent or empty the request is rejected with `ERR_MISSING_USER_CONTEXT` (401)."

    Design: Corner/errors/error_request_missing_x_user_id_header_returns_401
    """
    plant = build.create_plant()
    exhibit = build.create_exhibit(plant)

    # A perfectly valid read of an existing exhibit still fails on identity.
    validate_error(api.get_exhibit(exhibit["id"], ROLE_ONLY_HEADERS), ERR_MISSING_USER_CONTEXT, 401)

    # Identity is checked at rank 1, so it outranks the pagination bounds of §2.3.
    validate_error(
        api.list_species(ROLE_ONLY_HEADERS, {"limit": 0}), ERR_MISSING_USER_CONTEXT, 401
    )

    # It also outranks path resolution, so an unknown id is not a 404 here.
    validate_error(
        api.get_exhibit(NON_EXISTENT_UUID, ROLE_ONLY_HEADERS), ERR_MISSING_USER_CONTEXT, 401
    )

    # And it outranks body validation on a write.
    validate_error(
        api.create_exhibit(factories.exhibit_payload(plant["id"]), ROLE_ONLY_HEADERS),
        ERR_MISSING_USER_CONTEXT,
        401,
    )

    # An empty header value is treated exactly like an absent one.
    validate_error(
        api.get_exhibit(exhibit["id"], EMPTY_USER_ID_HEADERS), ERR_MISSING_USER_CONTEXT, 401
    )
    validate_error(
        api.create_exhibit(factories.exhibit_payload(plant["id"]), EMPTY_USER_ID_HEADERS),
        ERR_MISSING_USER_CONTEXT,
        401,
    )

    # None of the refused writes may have left a row behind.
    _, meta = validate_paginated(api.list_exhibits(CURATOR_HEADERS))
    assert meta["total_count"] == 1


def test_an_unknown_role_name_is_an_invalid_role_while_a_known_one_is_merely_unauthorised(api, build):
    """The role-vocabulary check precedes authorization, so 401 and 403 never blur.

    PRD §2.1: "If `X-User-Role` is absent or is not one of the six recognised role names, the request is rejected with `ERR_INVALID_ROLE` (401) — this check runs before any authorization decision, so an unknown role never produces a permission error."

    Design: Corner/errors/error_unrecognised_role_header_is_invalid_role_not_unauthorized
    """
    plant = build.create_plant()
    exhibit = build.create_exhibit(plant)
    institution = build.create_institution()

    # A role name outside the six is 401, not 403 — even on a read the caller
    # would have been allowed to make under a recognised role.
    validate_error(
        api.get_exhibit(exhibit["id"], make_headers("MarineBiologistIntern", "user-intern-01")),
        ERR_INVALID_ROLE,
        401,
    )
    # The vocabulary is the exact role names; a differently-cased spelling is not
    # one of them.
    validate_error(
        api.get_exhibit(exhibit["id"], make_headers("compliancedirector", "user-director-01")),
        ERR_INVALID_ROLE,
        401,
    )
    # An absent role header lands on the same id.
    validate_error(api.get_exhibit(exhibit["id"], USER_ID_ONLY_HEADERS), ERR_INVALID_ROLE, 401)
    # An unknown role is refused even where the write itself is malformed.
    validate_error(
        api.create_species(
            factories.species_payload(), make_headers("MarineBiologistIntern", "user-intern-01")
        ),
        ERR_INVALID_ROLE,
        401,
    )

    # By contrast a recognised role that the endpoint does not admit is 403.
    # A liaison's X-User-ID is the id of the institution it speaks for (§2.1).
    liaison = make_liaison_headers(institution["id"])
    validate_error(api.get_exhibit(exhibit["id"], liaison), ERR_UNAUTHORIZED, 403)
    validate_error(api.create_species(factories.species_payload(), liaison), ERR_UNAUTHORIZED, 403)
    validate_error(api.list_species(liaison), ERR_UNAUTHORIZED, 403)

    # The liaison may read the institution registry, which proves the 403s above
    # are per-endpoint authorization and not a blanket rejection of the role.
    readable = validate_success(api.get_institution(institution["id"], liaison))
    assert readable["id"] == institution["id"]

    _, meta = validate_paginated(api.list_species(CURATOR_HEADERS))
    assert meta["total_count"] == 0


def test_each_unknown_identifier_answers_with_its_own_entity_not_found_code(api, build):
    """Every addressable entity family has its own 404 code, and the path segment names it.

    PRD §2.8: "For any such route the system resolves identifiers strictly left to right and rejects on the **first** one that does not exist, with the not-found code of that entity."

    Design: Corner/errors/error_every_unknown_id_returns_its_own_entity_not_found_code
    """
    validate_error(
        api.get_life_support_system(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_LIFE_SUPPORT_SYSTEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_exhibit(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_EXHIBIT_NOT_FOUND, 404
    )
    validate_error(
        api.get_species(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_SPECIES_NOT_FOUND, 404
    )
    validate_error(
        api.get_institution(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_INSTITUTION_NOT_FOUND, 404
    )
    validate_error(
        api.get_collection_plan_entry(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_COLLECTION_PLAN_ENTRY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_acquisition_request(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_ACQUISITION_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(api.get_permit(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_PERMIT_NOT_FOUND, 404)
    validate_error(
        api.get_specimen(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_SPECIMEN_NOT_FOUND, 404
    )
    validate_error(
        api.get_quarantine_case(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_QUARANTINE_CASE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_veterinary_case(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_VETERINARY_CASE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_transfer_request(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_TRANSFER_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_interaction_session(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_INTERACTION_SESSION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_accreditation_audit(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_ACCREDITATION_AUDIT_NOT_FOUND,
        404,
    )

    # A child route names the parent that failed to resolve, not the child.
    validate_error(
        api.list_husbandry_logs(NON_EXISTENT_UUID, DIRECTOR_HEADERS), ERR_SPECIMEN_NOT_FOUND, 404
    )
    validate_error(
        api.list_specimen_quarantine_cases(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_SPECIMEN_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_water_quality_readings(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_LIFE_SUPPORT_SYSTEM_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_exhibit_interaction_sessions(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_EXHIBIT_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_acquisition_request_permits(NON_EXISTENT_UUID, DIRECTOR_HEADERS),
        ERR_ACQUISITION_REQUEST_NOT_FOUND,
        404,
    )


def test_each_entity_family_polices_its_own_unique_code_and_no_other_field(api, build):
    """The duplicate-code refusal keys on the one field the family declares unique.

    PRD §2.8: "The entity's unique code is not already taken — `ERR_DUPLICATE_CODE` (409). Applies to the creation of life support plants (`system_code`), exhibits (`exhibit_code`), species (`scientific_name`), institutions (`institution_code`), specimens (`accession_code`) and accreditation audits (`audit_code`)."

    Design: Corner/errors/error_reused_unique_codes_return_duplicate_code_per_entity_family
    """
    plant = build.create_plant(system_code="LSS-COLD-1", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, exhibit_code="EX-COLD-1", name="Cold Water Reef")
    species = build.create_species(
        scientific_name="Sebastes ruberrimus", common_name="yelloweye rockfish"
    )
    institution = build.create_institution(institution_code="INST-PEER-1")

    # A reused system_code is refused even though every other field differs.
    validate_error(
        api.create_life_support_system(
            factories.life_support_system_payload(
                system_code="LSS-COLD-1",
                design_habitat="TROPICAL_MARINE",
                system_type="FLOW_THROUGH",
                redundancy_class="TWO_N",
                redundancy_test_interval_days=180,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    # A reused exhibit_code on a habitat-compatible plant is the duplicate rule.
    validate_error(
        api.create_exhibit(
            factories.exhibit_payload(
                plant["id"],
                exhibit_code="EX-COLD-1",
                name="A Quite Different Tank",
                habitat_type="COLD_MARINE",
                display_volume_liters=9000.0,
                bioload_capacity_units=40.0,
            ),
            CURATOR_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    # For species the unique field is the scientific name.
    validate_error(
        api.create_species(
            factories.species_payload(
                scientific_name="Sebastes ruberrimus", common_name="a different common name"
            ),
            CURATOR_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    validate_error(
        api.create_institution(
            factories.institution_payload(
                institution_code="INST-PEER-1", name="Some Other Aquarium"
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    # A repeated common_name is not policed, because the PRD declares only the
    # scientific name unique for a species.
    twin = validate_success(
        api.create_species(
            factories.species_payload(
                scientific_name="Sebastes miniatus", common_name="yelloweye rockfish"
            ),
            CURATOR_HEADERS,
        ),
        201,
    )
    assert twin["common_name"] == species["common_name"]
    assert twin["scientific_name"] == "Sebastes miniatus"

    _, species_meta = validate_paginated(api.list_species(CURATOR_HEADERS))
    assert species_meta["total_count"] == 2
    _, plant_meta = validate_paginated(api.list_life_support_systems(DIRECTOR_HEADERS))
    assert plant_meta["total_count"] == 1
    _, exhibit_meta = validate_paginated(api.list_exhibits(CURATOR_HEADERS))
    assert exhibit_meta["total_count"] == 1
    assert exhibit["exhibit_code"] == "EX-COLD-1"
    _, institution_meta = validate_paginated(api.list_institutions(DIRECTOR_HEADERS))
    assert institution_meta["total_count"] == 1
    assert institution["institution_code"] == "INST-PEER-1"


def test_a_possession_permit_cannot_clear_a_wild_collection_request(api, build):
    """A wild-collection clearance demands an IMPORT permit; a POSSESSION one is the wrong instrument.

    PRD §3.5: "On the `PENDING_PERMIT` road it additionally requires at least one permit of the request in `ISSUED` status whose `permit_type` is `IMPORT` when `source_type` is `WILD_COLLECTION` and `POSSESSION` for every other source — the wrong type is `ERR_PERMIT_TYPE_MISMATCH`, no issued permit at all is `ERR_PERMIT_NOT_ISSUED`."

    Design: Corner/errors/error_possession_permit_on_a_wild_collection_clearance_is_a_type_mismatch
    """
    world = build.approved_line(
        species_overrides={"wild_take_quota_annual": 4},
        entry_overrides={"sustainability_requirement": "GREEN_ONLY"},
    )
    institution = build.create_institution(welfare_audit_score=88.00)
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request = build.submit_acquisition(request["id"])
    assert request["status"] == "PENDING_PERMIT"
    assert request["permit_required"] is True

    possession = build.issue_permit(
        request["id"], "POSSESSION", ["HEALTH_CERTIFICATE", "POSSESSION_AFFIDAVIT"]
    )
    assert possession["status"] == "ISSUED"

    species_version = build.species_version(world["species"]["id"])
    mismatch = api.clear_acquisition_request(
        request["id"],
        factories.clearance_payload(species_version),
        make_director_headers("dir-clearance-officer-1"),
    )
    validate_error(mismatch, ERR_PERMIT_TYPE_MISMATCH, 422)

    # Nothing about the refused clearance may persist: no status move, no score
    # rewrite, no quota reservation, no species version bump.
    held = build.get_acquisition(request["id"])
    assert held["status"] == "PENDING_PERMIT"
    assert held["sustainability_score_variant"] == "PROVISIONAL"
    assert held["cleared_by_user_id"] is None
    assert held["quota_units_reserved"] == 0
    unmoved_species = build.get_species(world["species"]["id"])
    assert unmoved_species["version"] == species_version
    assert unmoved_species["wild_take_quota_reserved"] == 0

    # Filing the right instrument clears the very same request.
    imported = build.issue_permit(
        request["id"], "IMPORT", ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]
    )
    assert imported["status"] == "ISSUED"
    cleared = validate_success(
        api.clear_acquisition_request(
            request["id"],
            factories.clearance_payload(species_version),
            make_director_headers("dir-clearance-officer-1"),
        )
    )
    assertions.assert_acquisition_request(cleared)
    assert cleared["status"] == "CLEARED"
    assert cleared["sustainability_score_variant"] == "FINAL"
    # 40.0 GREEN + 10.0 WILD_COLLECTION + 0.25 x 88.00 institution = 72.00,
    # plus the 5.0 issued-permit bonus, less 20.0 x 1/4 of quota pressure.
    assertions.assert_scaled_equal(cleared["sustainability_score"], 72.00)
    assert cleared["quota_units_reserved"] == 1

    reserved_species = build.get_species(world["species"]["id"])
    assert reserved_species["wild_take_quota_reserved"] == 1
    assert reserved_species["version"] == species_version + 1

    rows, meta = validate_paginated(
        api.list_acquisition_request_permits(request["id"], PERMIT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {"ISSUED"}
    assert {row["permit_type"] for row in rows} == {"POSSESSION", "IMPORT"}


def test_a_transfer_to_an_ineligible_receiver_is_refused_until_the_receiver_qualifies(api, build):
    """Submission gates on the receiving institution's derived eligibility flag.

    PRD §3.8: "Submission requires the receiving institution's `is_receiving_eligible` to be true, else `ERR_RECEIVER_NOT_ELIGIBLE`"

    Design: Corner/errors/error_transfer_submission_to_a_non_accredited_receiver_is_receiver_not_eligible
    """
    world = build.specimen_on_exhibit()
    specimen = world["specimen"]
    assert specimen["disposition_status"] == "ON_EXHIBIT"
    assert specimen["health_status"] == "HEALTHY"

    # A perfect welfare audit score cannot rescue a NON_ACCREDITED status: §3.3
    # requires both halves of the eligibility test.
    receiver = build.create_institution(
        accreditation_status="NON_ACCREDITED", welfare_audit_score=100.00
    )
    assert receiver["is_receiving_eligible"] is False

    transfer = build.draft_transfer(
        specimen["id"],
        receiver["id"],
        shift(build.now, days=30),
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    assert transfer["status"] == "DRAFT"

    refused = api.submit_transfer_request(transfer["id"], {}, PERMIT_OFFICER_HEADERS)
    validate_error(refused, ERR_RECEIVER_NOT_ELIGIBLE, 409)

    held = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert held["status"] == "DRAFT"
    # The specimen must not have been moved towards the door. PRD §3.8 keeps
    # `pre_transfer_disposition` on the specimen, not on the request.
    unmoved = build.get_specimen(specimen["id"])
    assert unmoved["pre_transfer_disposition"] is None
    assert unmoved["disposition_status"] == "ON_EXHIBIT"
    assert unmoved["exhibit_id"] == world["exhibit"]["id"]

    upgraded = validate_success(
        api.update_institution(
            receiver["id"],
            factories.institution_patch_payload(accreditation_status="ACCREDITED"),
            DIRECTOR_HEADERS,
        )
    )
    assert upgraded["is_receiving_eligible"] is True

    accepted = validate_success(
        api.submit_transfer_request(transfer["id"], {}, PERMIT_OFFICER_HEADERS)
    )
    assertions.assert_transfer_request(accepted)
    assert accepted["status"] == "SUBMITTED"

    pending = build.get_specimen(specimen["id"])
    assert pending["pre_transfer_disposition"] == "ON_EXHIBIT"
    assert pending["disposition_status"] == "TRANSFER_PENDING"
    # A TRANSFER_PENDING animal still holds its tank and its bioload (§3.8).
    assert pending["exhibit_id"] == world["exhibit"]["id"]
    assertions.assert_scaled_equal(
        build.get_exhibit(world["exhibit"]["id"])["occupied_bioload_units"], 10.00
    )


def test_a_past_treatment_makes_the_diet_transition_plan_a_mandatory_condition(api, build):
    """A closed TREATMENT case still adds DIET_TRANSITION_PLAN to the required condition set.

    PRD §3.8: "`DIET_TRANSITION_PLAN` is added when the specimen has at least one veterinary case whose `case_type` is `TREATMENT`, of any `status` whatsoever — a long-closed treatment still obliges the sender to hand over a diet plan."

    Design: Corner/errors/error_transfer_submission_without_the_treatment_history_condition_is_incomplete
    """
    world = build.specimen_on_exhibit()
    specimen = world["specimen"]

    treatment = build.open_vet_case(
        specimen["id"], "TREATMENT", treatment_start_at=build.now, withdrawal_days=0
    )
    assert treatment["case_type"] == "TREATMENT"
    assert build.get_specimen(specimen["id"])["health_status"] == "UNDER_TREATMENT"
    closed = build.close_vet_case(treatment["id"], "RESOLVED", "NONE")
    assert closed["status"] == "CLOSED"
    # Submission also demands a HEALTHY animal, so the treatment must be behind us.
    recovered = build.get_specimen(specimen["id"])
    assert recovered["health_status"] == "HEALTHY"
    assert recovered["disposition_status"] == "ON_EXHIBIT"

    receiver = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=88.00
    )
    assert receiver["is_receiving_eligible"] is True

    # The two always-required codes are present, but the treatment history has
    # silently added a third.
    incomplete = build.draft_transfer(
        specimen["id"],
        receiver["id"],
        shift(build.now, days=30),
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    refused = api.submit_transfer_request(incomplete["id"], {}, PERMIT_OFFICER_HEADERS)
    validate_error(refused, ERR_TRANSFER_CONDITIONS_INCOMPLETE, 422)

    held = validate_success(api.get_transfer_request(incomplete["id"], PERMIT_OFFICER_HEADERS))
    assert held["status"] == "DRAFT"
    # PRD §3.8 keeps `pre_transfer_disposition` on the specimen, not on the
    # request, and the refused submission must not have stamped it.
    assert build.get_specimen(specimen["id"])["pre_transfer_disposition"] is None
    assert build.get_specimen(specimen["id"])["disposition_status"] == "ON_EXHIBIT"

    complete = build.draft_transfer(
        specimen["id"],
        receiver["id"],
        shift(build.now, days=30),
        welfare_conditions=[
            "WATER_CHEMISTRY_MATCH",
            "TRANSPORT_OXYGEN_PLAN",
            "DIET_TRANSITION_PLAN",
        ],
    )
    accepted = validate_success(
        api.submit_transfer_request(complete["id"], {}, PERMIT_OFFICER_HEADERS)
    )
    assert accepted["status"] == "SUBMITTED"
    moved = build.get_specimen(specimen["id"])
    assert moved["pre_transfer_disposition"] == "ON_EXHIBIT"
    assert moved["disposition_status"] == "TRANSFER_PENDING"


def test_no_session_may_be_booked_on_an_exhibit_whose_programme_is_disabled(api, build):
    """Session creation requires interaction_program_enabled, and a re-enable admits it.

    PRD §2.8: "The exhibit's `interaction_program_enabled` is `true` — `ERR_INTERACTION_PROGRAM_DISABLED` (409). Applies to session creation and session transitions."

    Design: Corner/errors/error_session_creation_on_a_programme_disabled_exhibit_is_refused
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=False)
    assert exhibit["interaction_program_enabled"] is False
    assert exhibit["posture"] == "OPEN"

    starts_at = shift(build.now, days=1, hours=10)
    ends_at = shift(build.now, days=1, hours=11)
    refused = api.create_interaction_session(
        factories.interaction_session_payload(
            exhibit["id"],
            starts_at,
            ends_at,
            program_type="TOUCH_POOL_CONTACT",
            max_guests=6,
            guest_count=4,
            safety_briefing_confirmed=True,
        ),
        AQUARIST_HEADERS,
    )
    validate_error(refused, ERR_INTERACTION_PROGRAM_DISABLED, 409)

    _, empty_meta = validate_paginated(
        api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS)
    )
    assert empty_meta["total_count"] == 0

    # The director toggles the programme on in a version-guarded edit (§3.2).
    reopened = validate_success(
        api.update_exhibit(
            exhibit["id"],
            factories.exhibit_patch_payload(exhibit["version"], interaction_program_enabled=True),
            DIRECTOR_HEADERS,
        )
    )
    assert reopened["interaction_program_enabled"] is True
    assert reopened["version"] == exhibit["version"] + 1
    assert reopened["suspended_session_count"] == 0

    session = validate_success(
        api.create_interaction_session(
            factories.interaction_session_payload(
                exhibit["id"],
                starts_at,
                ends_at,
                program_type="TOUCH_POOL_CONTACT",
                max_guests=6,
                guest_count=4,
                safety_briefing_confirmed=True,
            ),
            AQUARIST_HEADERS,
        ),
        201,
    )
    assertions.assert_interaction_session(session)
    assert session["status"] == "SCHEDULED"
    assert same_instant(session["starts_at"], starts_at)

    activated = validate_success(
        api.transition_interaction_session(
            session["id"], factories.session_transition_payload("ACTIVATE"), AQUARIST_HEADERS
        )
    )
    assert activated["status"] == "ACTIVE"

    _, booked_meta = validate_paginated(
        api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS)
    )
    assert booked_meta["total_count"] == 1


def test_a_wild_collection_clearance_stops_at_the_annual_take_quota(api, build):
    """Quota is checked as reserved plus requested against the annual allowance.

    PRD §3.5: "for a `WILD_COLLECTION` source, that `wild_take_quota_reserved` plus `requested_count` not exceed `wild_take_quota_annual`, else `ERR_QUOTA_EXCEEDED`"

    Design: Corner/errors/error_clearance_beyond_the_annual_wild_take_quota_is_refused
    """
    world = build.approved_line(
        species_overrides={"wild_take_quota_annual": 3},
        entry_overrides={"planned_count": 8, "sustainability_requirement": "GREEN_ONLY"},
    )
    species_id = world["species"]["id"]
    institution = build.create_institution(welfare_audit_score=88.00)
    import_documents = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]
    clearance_officer = make_director_headers("dir-clearance-officer-1")

    first = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=2,
        source_institution_id=institution["id"],
    )
    first = build.submit_acquisition(first["id"])
    build.issue_permit(first["id"], "IMPORT", import_documents)

    second = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=2,
        source_institution_id=institution["id"],
    )
    second = build.submit_acquisition(second["id"])
    second_permit = build.issue_permit(second["id"], "IMPORT", import_documents)

    captive = build.create_acquisition(
        world["entry"], source_type="CAPTIVE_BRED", requested_count=2
    )
    captive = build.submit_acquisition(captive["id"])
    assert captive["status"] == "READY_FOR_CLEARANCE"
    assert captive["permit_deadline_at"] is None

    # 0 reserved plus 2 requested does not exceed 3, so the first clearance stands.
    cleared_first = validate_success(
        api.clear_acquisition_request(
            first["id"],
            factories.clearance_payload(build.species_version(species_id)),
            clearance_officer,
        )
    )
    assert cleared_first["status"] == "CLEARED"
    assert cleared_first["quota_units_reserved"] == 2
    after_first = build.get_species(species_id)
    assert after_first["wild_take_quota_reserved"] == 2

    # 2 reserved plus 2 requested is 4, beyond the annual allowance of 3.
    version_before = after_first["version"]
    refused = api.clear_acquisition_request(
        second["id"], factories.clearance_payload(version_before), clearance_officer
    )
    validate_error(refused, ERR_QUOTA_EXCEEDED, 409)

    held = build.get_acquisition(second["id"])
    assert held["status"] == "PENDING_PERMIT"
    assert held["cleared_by_user_id"] is None
    assert held["quota_units_reserved"] == 0
    assert held["sustainability_score_variant"] == "PROVISIONAL"
    assert build.get_permit(second_permit["id"])["status"] == "ISSUED"
    unchanged = build.get_species(species_id)
    assert unchanged["wild_take_quota_reserved"] == 2
    assert unchanged["version"] == version_before

    # The quota rule is confined to wild collection: the captive-bred line of the
    # same species clears untouched and reserves nothing.
    cleared_captive = validate_success(
        api.clear_acquisition_request(
            captive["id"], factories.clearance_payload(version_before), clearance_officer
        )
    )
    assert cleared_captive["status"] == "CLEARED"
    assert cleared_captive["quota_units_reserved"] == 0
    assert cleared_captive["sustainability_score_variant"] == "FINAL"
    # 40.0 GREEN + 35.0 CAPTIVE_BRED + 20.0 for no source institution, with no
    # permit bonus on the READY_FOR_CLEARANCE road and no quota pressure.
    assertions.assert_scaled_equal(cleared_captive["sustainability_score"], 95.00)

    final_species = build.get_species(species_id)
    assert final_species["wild_take_quota_reserved"] == 2
    assert final_species["version"] == version_before
