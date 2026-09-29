"""Entity record contracts: creation defaults, derived fields, reads and shape rules.

Every test builds its own world through the published endpoints against an empty
database with the logical clock parked at 2026-08-01T00:00:00Z (PRD §2.5).
"""
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    VET_HEADERS,
    assertions,
    factories,
    is_iso8601_timestamp,
    reading_for,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ERR_SPECIMEN_NOT_FOUND, ERR_VALIDATION


def normalise_instant(value: str) -> str:
    """Drop the optional fractional part so two ISO-8601 UTC instants compare."""
    assert is_iso8601_timestamp(value), value
    if "." in value:
        return value.split(".")[0] + "Z"
    return value


def response_type_of(response: Any) -> str:
    """The `response_type` discriminator of the standard envelope (PRD §2.2)."""
    return response.json()["response_type"]


def test_life_support_plant_registration_derives_its_alarm_band_and_water_quality_index(api):
    """A plant registered with only its five declared inputs comes back with every derived field.

    PRD §3.1: "Everything else about a plant is derived. `alarm_state` is its alarm band and begins at `NORMAL`."
    PRD §3.1: "`water_quality_index` is the index of the plant's most recent reading, and is 100.00 while the plant has no readings at all."

    Design: Corner/entities/entity_life_support_system_creation_sets_defaults_and_system_fields
    """
    payload = factories.life_support_system_payload(
        system_code="LSS-COLD-1",
        system_type="RECIRCULATING_MARINE",
        design_habitat="COLD_MARINE",
        redundancy_class="N_PLUS_1",
        redundancy_test_interval_days=90,
    )

    response = api.create_life_support_system(payload, DIRECTOR_HEADERS)

    plant = validate_success(response, 201)
    assert response_type_of(response) == "object"
    assertions.assert_life_support_system(plant)
    # The five client-supplied fields are echoed exactly as registered.
    assert plant["system_code"] == "LSS-COLD-1"
    assert plant["system_type"] == "RECIRCULATING_MARINE"
    assert plant["design_habitat"] == "COLD_MARINE"
    assert plant["redundancy_class"] == "N_PLUS_1"
    assert plant["redundancy_test_interval_days"] == 90
    # Everything else is derived by the server, not supplied.
    assertions.assert_alarm(plant, "NORMAL", normals=0, breaches=0)
    assertions.assert_scaled_equal(plant["water_quality_index"], 100.00)
    # No test has ever been recorded, so the timestamp and the result are both null,
    # and the interval is measured from the plant's own `created_at` (PRD §3.1).
    assert plant["last_redundancy_test_at"] is None
    assert plant["last_redundancy_test_result"] is None
    assert plant["redundancy_overdue"] is False
    assert plant["version"] == 1


def test_exhibit_read_reports_an_empty_bioload_ledger_and_an_open_posture(api, build):
    """A freshly created exhibit reads back with a zero ledger and an OPEN posture.

    PRD §3.2: "`occupied_bioload_units` is the sum of `bioload_units` over every specimen whose `exhibit_id` is this exhibit and whose `disposition_status` is `ON_EXHIBIT` or `TRANSFER_PENDING`, rounded half up to two decimals."
    PRD §3.2: "and otherwise posture `OPEN` with `last_posture_reason` null."

    Design: Corner/entities/entity_exhibit_read_returns_zero_ledger_and_open_posture
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(
        plant,
        exhibit_code="EX-COLD-1",
        name="Cold Water Reef",
        display_volume_liters=120000.0,
        bioload_capacity_units=100.0,
    )

    response = api.get_exhibit(exhibit["id"], CURATOR_HEADERS)

    read = validate_success(response, 200)
    assert response_type_of(response) == "object"
    assertions.assert_exhibit(read)
    assert read["exhibit_code"] == "EX-COLD-1"
    assert read["habitat_type"] == "COLD_MARINE"
    assert read["life_support_system_id"] == plant["id"]
    assertions.assert_scaled_equal(read["bioload_capacity_units"], 100.00)
    # No specimen has been placed, so the ledger sums to nothing and the
    # utilisation of a 100-unit exhibit is 0.00 per cent.
    assertions.assert_scaled_equal(read["occupied_bioload_units"], 0.00)
    assertions.assert_scaled_equal(read["bioload_utilization_pct"], 0.00)
    # The serving plant is NORMAL and not overdue, and the utilisation is not
    # above 95.00, so none of the five posture conditions matches.
    assertions.assert_posture(read, "OPEN", None)
    assert read["suspended_session_count"] == 0
    assert read["version"] == 1


def test_species_listing_reports_total_count_and_has_more_across_pages(api, build):
    """Three species page two-at-a-time with an honest total_count and has_more.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope."
    PRD §2.3: "Unless a list is explicitly documented otherwise, rows are sorted by their creation timestamp in ascending order."

    Design: Corner/entities/entity_species_listing_reports_total_count_and_has_more
    """
    first = build.create_species(
        scientific_name="Sebastes ruberrimus",
        common_name="yelloweye rockfish",
        taxon_group="TELEOST",
        bioload_units_per_specimen=12.0,
        base_quarantine_days=30,
    )
    second = build.create_species(
        scientific_name="Hippocampus abdominalis",
        common_name="pot-bellied seahorse",
        taxon_group="TELEOST",
        bioload_units_per_specimen=2.0,
        base_quarantine_days=21,
    )
    third = build.create_species(
        scientific_name="Metridium senile",
        common_name="plumose anemone",
        taxon_group="INVERTEBRATE",
        bioload_units_per_specimen=1.0,
        base_quarantine_days=14,
    )

    page_one = api.list_species(CURATOR_HEADERS, params={"limit": 2, "offset": 0})
    page_two = api.list_species(CURATOR_HEADERS, params={"limit": 2, "offset": 2})

    first_rows, first_meta = validate_paginated(page_one)
    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    # Ascending creation order, so the first page is the two oldest rows.
    assert [row["id"] for row in first_rows] == [first["id"], second["id"]]
    for row in first_rows:
        assertions.assert_species(row)

    second_rows, second_meta = validate_paginated(page_two)
    assert len(second_rows) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert [row["id"] for row in second_rows] == [third["id"]]

    # A filter narrows the result set without changing the pagination contract.
    filtered_rows, filtered_meta = validate_paginated(
        api.list_species(CURATOR_HEADERS, params={"taxon_group": "INVERTEBRATE"})
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered_rows] == [third["id"]]


def test_reading_an_unknown_specimen_id_returns_specimen_not_found(api):
    """A well-formed but unknown specimen id is a 404 on the specimen, not a validation complaint.

    PRD §2.8: "Every identifier taken from the path resolves to an existing row of the expected entity, resolved left to right — the entity-specific not-found code, at 404. Every endpoint that takes a path identifier."
    PRD §5 publishes `ERR_SPECIMEN_NOT_FOUND` at 404 Not Found.

    Design: Corner/entities/entity_get_unknown_specimen_id_returns_specimen_not_found
    """
    response = api.get_specimen(NON_EXISTENT_UUID, CURATOR_HEADERS)

    error = validate_error(response, ERR_SPECIMEN_NOT_FOUND, 404)
    assert response_type_of(response) == "error"
    assert error["message"].strip()
    # PRD §2.2: the error envelope's meta carries exactly these two members.
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_exhibit_creation_without_bioload_capacity_units_is_rejected(api, build):
    """`bioload_capacity_units` is a declared creation input, so omitting it fails validation.

    PRD §3.2: "The curator creates one with a unique `exhibit_code`, a public `name`, a `habitat_type` drawn from the same four habitats as a plant's `design_habitat`, the `life_support_system_id` of the serving plant, a `display_volume_liters` greater than 0, a `bioload_capacity_units` greater than 0 and an optional `interaction_program_enabled` flag."
    PRD §2.8: "Required fields present; types, enum members and numeric ranges as specified — `ERR_VALIDATION` (422). Every endpoint."

    Design: Corner/entities/entity_exhibit_creation_without_bioload_capacity_units_is_rejected
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    payload = factories.exhibit_payload(
        plant["id"],
        exhibit_code="EX-COLD-2",
        name="Kelp Forest",
        habitat_type="COLD_MARINE",
        display_volume_liters=90000.0,
    )
    payload.pop("bioload_capacity_units")

    response = api.create_exhibit(payload, CURATOR_HEADERS)

    validate_error(response, ERR_VALIDATION, 422)
    # Nothing is persisted by a rejected create.
    rows, meta = validate_paginated(api.list_exhibits(CURATOR_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
    # The serving plant was not mutated either, so its version still reads 1 (PRD §2.4).
    assert build.get_plant(plant["id"])["version"] == 1


def test_specimen_accession_snapshots_bioload_units_and_opens_its_quarantine_case(api, build):
    """Accession copies the species' bioload figure onto the animal and opens an ACTIVE case.

    PRD §3.6: "Accession snapshots `bioload_units` from the species' current `bioload_units_per_specimen` and never re-reads it afterwards, derives `captive_bred` as true exactly when both `sire_specimen_id` and `dam_specimen_id` are present, computes `quarantine_required_days`, opens the quarantine case, and increments the acquisition request's `fulfilled_count`."
    PRD §3.6: "Its `protocol_days` is a snapshot of the specimen's `quarantine_required_days`; its `started_at` equals the specimen's `arrival_at`; its `projected_release_at` is `started_at` advanced by (`protocol_days` plus `total_extension_days`) days and is recomputed on every extension; its `status` begins at `ACTIVE`; and `extension_count`, `total_extension_days` and `clearance_exam_count` begin at 0."

    Design: Corner/entities/entity_specimen_bioload_units_snapshotted_from_species_at_creation
    """
    world = build.cleared_acquisition(
        source_type="CAPTIVE_BRED",
        requested_count=1,
        species_overrides={
            "scientific_name": "Sebastes ruberrimus",
            "common_name": "yelloweye rockfish",
            "taxon_group": "TELEOST",
            "bioload_units_per_specimen": 12.5,
            "base_quarantine_days": 30,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    arrival_at = build.now

    payload = factories.specimen_payload(
        world["species"]["id"],
        world["request"]["id"],
        arrival_at=arrival_at,
        accession_code="SPC-0001",
        holding_area="QT-BAY-1",
    )
    response = api.create_specimen(payload, CURATOR_HEADERS)

    specimen = validate_success(response, 201)
    assertions.assert_specimen(specimen)
    # 12.5 is the species' current `bioload_units_per_specimen`, snapshotted here.
    assertions.assert_scaled_equal(specimen["bioload_units"], 12.5)
    # A TELEOST multiplier of 1.0 on a base of 30 gives taxon days of 30; a
    # CAPTIVE_BRED source with no source institution adds no surcharge; and 30 is
    # below the high-tier threshold of 45, so no further 7 days are added (PRD §3.6).
    assert specimen["quarantine_required_days"] == 30
    assert specimen["disposition_status"] == "QUARANTINE"
    assert specimen["health_status"] == "HEALTHY"
    # No husbandry record exists yet, so the welfare window is empty (PRD §3.7).
    assert specimen["welfare_score"] is None
    assert specimen["welfare_score_variant"] is None
    # Neither parent id was supplied.
    assert specimen["captive_bred"] is False
    assert specimen["sire_specimen_id"] is None
    assert specimen["dam_specimen_id"] is None
    assert specimen["exhibit_id"] is None
    assert specimen["holding_area"] == "QT-BAY-1"
    assert normalise_instant(specimen["arrival_at"]) == arrival_at
    assert specimen["version"] == 1

    # The quarantine case is opened by the accession itself; no endpoint creates one.
    rows, meta = validate_paginated(api.list_specimen_quarantine_cases(specimen["id"], VET_HEADERS))
    assert meta["total_count"] == 1
    case = rows[0]
    assertions.assert_quarantine_case(case)
    assert case["specimen_id"] == specimen["id"]
    assert case["status"] == "ACTIVE"
    assert case["protocol_days"] == 30
    assert case["extension_count"] == 0
    assert case["total_extension_days"] == 0
    assert case["clearance_exam_count"] == 0
    assert normalise_instant(case["started_at"]) == arrival_at
    assert normalise_instant(case["projected_release_at"]) == shift(arrival_at, days=30)


def test_water_quality_reading_is_written_once_and_carries_no_version(api, build):
    """A recorded sample is an observation: id and created_at only, never a versioned resource.

    PRD §2.4: "Two record types are append-only observations rather than living resources, and they are deliberately narrower: a **water-quality reading** and a **husbandry log** carry only `id` and `created_at`. Neither has an `updated_at` and neither has a `version`; both fields are absent from their representations entirely, because these rows are never modified after they are written."
    PRD §3.1: "A reading is an observation, not a resource: it carries `id` and `created_at` and nothing else of the common set, and it is never edited or deleted."

    Design: Corner/entities/entity_water_quality_reading_is_immutable_and_carries_no_version
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)

    response = api.create_water_quality_reading(
        plant["id"], reading_for("COLD_MARINE", "NORMAL", build.now), AQUARIST_HEADERS
    )

    reading = validate_success(response, 201)
    # `id` and `created_at` are present and well-formed; `version` and
    # `updated_at` are absent from the representation entirely.
    assertions.assert_append_only_record(reading)
    assertions.assert_water_quality_reading(reading)
    assert reading["life_support_system_id"] == plant["id"]
    # Every parameter sits on its target, so every deviation ratio is 0.0.
    assert reading["severity"] == "NORMAL"
    assert reading["breach_parameters"] == []
    assertions.assert_scaled_equal(reading["water_quality_index_snapshot"], 100.00)

    # The same narrow shape is what the read side publishes.
    rows, meta = validate_paginated(api.list_water_quality_readings(plant["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 1
    listed = rows[0]
    assert listed["id"] == reading["id"]
    assertions.assert_append_only_record(listed)
    assertions.assert_scaled_equal(listed["water_quality_index_snapshot"], 100.00)


def test_husbandry_log_under_an_unknown_specimen_returns_specimen_not_found(api, build):
    """The parent specimen is resolved before the log body is looked at at all.

    PRD §2.10: "A request for the husbandry records of a specimen that does not exist returns `ERR_SPECIMEN_NOT_FOUND` (404); the system does not attempt to look for the records first."

    Design: Corner/entities/entity_husbandry_log_under_unknown_specimen_returns_specimen_not_found
    """
    well_formed_body: Dict[str, Any] = factories.husbandry_log_payload(
        "FEEDING", build.now, appetite_score=4, feed_grams=120.0
    )

    response = api.create_husbandry_log(NON_EXISTENT_UUID, well_formed_body, AQUARIST_HEADERS)

    validate_error(response, ERR_SPECIMEN_NOT_FOUND, 404)

    # Path resolution is rank 5 and field shape is rank 7 of PRD §2.8, so a body
    # that is itself invalid cannot displace the parent complaint.
    malformed_body = {"log_type": "FEEDING"}
    shape_response = api.create_husbandry_log(NON_EXISTENT_UUID, malformed_body, AQUARIST_HEADERS)
    validate_error(shape_response, ERR_SPECIMEN_NOT_FOUND, 404)


def test_accessioning_with_both_parents_recorded_derives_captive_bred(api, build):
    """captive_bred is true only for the animal that carries both a sire and a dam.

    PRD §2.9: "A specimen is captive-bred when both `sire_specimen_id` and `dam_specimen_id` are recorded."
    PRD §3.5: "Each specimen accessioned against a `CLEARED` request increments its `fulfilled_count`; when that count reaches `requested_count` the request moves to the terminal `FULFILLED`, and below that it simply stays `CLEARED`."

    Design: Corner/entities/entity_specimen_self_referential_parentage_sets_captive_bred_true
    """
    world = build.cleared_acquisition(source_type="CAPTIVE_BRED", requested_count=3)
    sire = build.accession_specimen(
        world["species"], world["request"], accession_code="SPC-0001", holding_area="QT-BAY-1"
    )
    dam = build.accession_specimen(
        world["species"], world["request"], accession_code="SPC-0002", holding_area="QT-BAY-1"
    )

    payload = factories.specimen_payload(
        world["species"]["id"],
        world["request"]["id"],
        arrival_at=build.now,
        accession_code="SPC-0003",
        holding_area="QT-BAY-2",
        sire_specimen_id=sire["id"],
        dam_specimen_id=dam["id"],
    )
    response = api.create_specimen(payload, CURATOR_HEADERS)

    calf = validate_success(response, 201)
    assertions.assert_specimen(calf)
    assert calf["captive_bred"] is True
    assert calf["sire_specimen_id"] == sire["id"]
    assert calf["dam_specimen_id"] == dam["id"]
    # The two founders carry neither parent, so the flag stays false for them.
    assert build.get_specimen(sire["id"])["captive_bred"] is False
    assert build.get_specimen(dam["id"])["captive_bred"] is False

    # The parentage edge is queryable through the documented filter (PRD §2.3).
    rows, meta = validate_paginated(
        api.list_specimens(CURATOR_HEADERS, params={"sire_specimen_id": sire["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [calf["id"]]

    # Three accessions against a request for three animals fulfil it.
    request = build.get_acquisition(world["request"]["id"])
    assert request["fulfilled_count"] == 3
    assert request["status"] == "FULFILLED"


def test_species_creation_with_an_unrecognised_taxon_group_is_rejected(api):
    """A taxon group outside the published enumeration is a validation failure.

    PRD §3.3: "The curator registers one with a `scientific_name` unique across all species, a `common_name`, a `taxon_group` of `ELASMOBRANCH`, `TELEOST`, `INVERTEBRATE`, `MARINE_MAMMAL`, `REPTILE` or `BIRD`, a `protection_status` of `UNLISTED`, `CITES_APPENDIX_II`, `CITES_APPENDIX_I` or `ESA_LISTED`, a `sustainability_rating` of `GREEN`, `YELLOW` or `RED`, a `bioload_units_per_specimen` greater than 0, a `base_quarantine_days` of at least 1 and no more than 180, and an optional `wild_take_quota_annual` of at least 0."
    PRD §2.8: "Required fields present; types, enum members and numeric ranges as specified — `ERR_VALIDATION` (422). Every endpoint."

    Design: Corner/entities/entity_species_creation_with_unknown_taxon_group_returns_invalid_enum
    """
    payload = factories.species_payload(
        scientific_name="Octopus rubescens",
        common_name="red octopus",
        taxon_group="MOLLUSC",
        protection_status="UNLISTED",
        sustainability_rating="GREEN",
        bioload_units_per_specimen=3.0,
        base_quarantine_days=21,
        wild_take_quota_annual=2,
    )

    response = api.create_species(payload, CURATOR_HEADERS)

    validate_error(response, ERR_VALIDATION, 422)
    # No species row is created, so no quarantine multiplier lookup is ever reached.
    rows, meta = validate_paginated(api.list_species(CURATOR_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []
