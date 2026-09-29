"""Cross-cutting layers: optimistic concurrency, alarm counters and derived flags.

Each test drives one published rule end to end and re-reads every entity the rule
claims to touch, so a side effect is never asserted from the mutating response alone.
"""
from test_helpers import (
    CLEARANCE_OFFICER_ID,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    assertions,
    factories,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_STALE_EXHIBIT_VERSION,
    ERR_STALE_SPECIES_VERSION,
)

IMPORT_DOCUMENTS = ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]


def test_exhibit_recapacitation_is_refused_when_a_placement_moved_the_exhibit_version(build, api):
    """A placement bumps the exhibit version, so the director's pre-placement token is stale.

    PRD §2.6: "Re-capacitating an exhibit — the same call that renames it, reassigns its
    plant or re-enables its interaction programme — requires `expected_exhibit_version`.
    A stale value means the director's view of `occupied_bioload_units` and `posture`
    predates a placement or a posture cascade. A mismatch yields
    `ERR_STALE_EXHIBIT_VERSION` (412)."

    PRD §3.6: "Placement sets the specimen's `exhibit_id`, clears `holding_area` to null,
    recomputes the ledger and the posture, and increments both the specimen's and the
    exhibit's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_exhibit_patch_rejects_a_version_stale_by_one_placement
    """
    world = build.cleared_specimen(species_overrides={"bioload_units_per_specimen": 12.0})
    exhibit_id = world["exhibit"]["id"]
    original_capacity = world["exhibit"]["bioload_capacity_units"]

    # The director reads the exhibit; the technician then places an animal on it.
    director_view_version = build.exhibit_version(exhibit_id)
    build.place(world["specimen"]["id"], exhibit_id, expected_exhibit_version=director_view_version)

    after_placement = build.get_exhibit(exhibit_id)
    assert after_placement["version"] == director_view_version + 1, after_placement["version"]

    # The re-capacitation carries the version the director read before the placement.
    stale_response = api.update_exhibit(
        exhibit_id,
        factories.exhibit_patch_payload(director_view_version, bioload_capacity_units=60.0),
        DIRECTOR_HEADERS,
    )
    validate_error(stale_response, ERR_STALE_EXHIBIT_VERSION, 412)

    # Nothing is persisted by a rejected guarded write, not even a version bump (§2.6).
    unchanged = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(unchanged["bioload_capacity_units"], original_capacity)
    assert unchanged["version"] == after_placement["version"], unchanged["version"]

    # The very same call succeeds once the current version has been re-read.
    retry_response = api.update_exhibit(
        exhibit_id,
        factories.exhibit_patch_payload(unchanged["version"], bioload_capacity_units=60.0),
        DIRECTOR_HEADERS,
    )
    patched = validate_success(retry_response, 200)
    assertions.assert_scaled_equal(patched["bioload_capacity_units"], 60.0)

    final = build.get_exhibit(exhibit_id)
    assertions.assert_scaled_equal(final["bioload_capacity_units"], 60.0)
    assertions.assert_scaled_equal(final["occupied_bioload_units"], 12.00)
    assertions.assert_scaled_equal(final["bioload_utilization_pct"], 20.00)
    assertions.assert_posture(final, "OPEN", None)


def test_plan_line_creation_is_refused_when_the_exhibit_version_moved_on(build, api):
    """The plan-entry guard watches the exhibit, and a director's edit invalidates it.

    PRD §2.6: "Creating a collection plan entry requires `expected_exhibit_version`,
    matching the current `version` of the `Exhibit` named in the body. ... A mismatch
    yields `ERR_STALE_EXHIBIT_VERSION` (412)."

    PRD §3.2: "The edit recomputes the ledger and the posture, and increments the
    exhibit's `version`."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_plan_entry_create_and_clearance_guard_two_different_parents
    """
    plant = build.create_plant()
    exhibit = build.create_exhibit(plant)
    species = build.create_species()

    curator_view_version = build.exhibit_version(exhibit["id"])
    edited = validate_success(
        api.update_exhibit(
            exhibit["id"],
            factories.exhibit_patch_payload(curator_view_version, name="Cold Water Reef"),
            DIRECTOR_HEADERS,
        ),
        200,
    )
    assert edited["version"] == curator_view_version + 1, edited["version"]

    stale_response = api.create_collection_plan_entry(
        factories.collection_plan_entry_payload(
            exhibit["id"], species["id"], curator_view_version, planned_count=2
        ),
        CURATOR_HEADERS,
    )
    validate_error(stale_response, ERR_STALE_EXHIBIT_VERSION, 412)

    # Nothing is persisted: no line for this exhibit-and-species pair exists yet (§2.6).
    rows, meta = validate_paginated(
        api.list_collection_plan_entries(
            CURATOR_HEADERS, {"exhibit_id": exhibit["id"], "species_id": species["id"]}
        )
    )
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    # Re-reading the exhibit lets the identical create succeed.
    current_version = build.exhibit_version(exhibit["id"])
    created = validate_success(
        api.create_collection_plan_entry(
            factories.collection_plan_entry_payload(
                exhibit["id"], species["id"], current_version, planned_count=2
            ),
            CURATOR_HEADERS,
        ),
        201,
    )
    assertions.assert_collection_plan_entry(created)
    assert created["status"] == "DRAFT", created["status"]
    assert created["exhibit_id"] == exhibit["id"], created["exhibit_id"]
    assert created["species_id"] == species["id"], created["species_id"]


def test_acquisition_clearance_is_refused_when_the_species_quota_version_moved_on(build, api):
    """The clearance guard watches the species quota pool, not the exhibit.

    PRD §2.6: "Clearing an acquisition request requires `expected_species_version`,
    matching the current `version` of the `Species` whose wild-take quota pool the
    clearance draws on. If another writer has advanced that species' `version` since the
    director last read it, the pool the decision was sized against has already moved, and
    the clearance is rejected with `ERR_STALE_SPECIES_VERSION` (412)."

    PRD §3.5: "for a `WILD_COLLECTION` source only — sets `quota_units_reserved` to
    `requested_count`, adds `requested_count` to the species' `wild_take_quota_reserved`
    and increments the species' `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/layer_occ_plan_entry_create_and_clearance_guard_two_different_parents
    """
    world = build.approved_line(species_overrides={"wild_take_quota_annual": 4})
    species_id = world["species"]["id"]
    institution = build.create_institution(welfare_audit_score=88.00)

    requests = []
    for _ in range(2):
        request = build.create_acquisition(
            world["entry"],
            source_type="WILD_COLLECTION",
            requested_count=1,
            source_institution_id=institution["id"],
        )
        submitted = build.submit_acquisition(request["id"])
        assert submitted["status"] == "PENDING_PERMIT", submitted["status"]
        build.issue_permit(request["id"], "IMPORT", IMPORT_DOCUMENTS)
        requests.append(request)

    first, second = requests

    # The director's read of the quota pool, taken before any reservation exists.
    director_view_version = build.species_version(species_id)
    cleared_first = build.clear_acquisition(first["id"], species_id, user_id=CLEARANCE_OFFICER_ID)
    assert cleared_first["status"] == "CLEARED", cleared_first["status"]

    species_after_first = build.get_species(species_id)
    assert species_after_first["version"] == director_view_version + 1, species_after_first["version"]
    assert species_after_first["wild_take_quota_reserved"] == 1, species_after_first

    stale_response = api.clear_acquisition_request(
        second["id"],
        factories.clearance_payload(director_view_version),
        make_director_headers(CLEARANCE_OFFICER_ID),
    )
    validate_error(stale_response, ERR_STALE_SPECIES_VERSION, 412)

    # The refused clearance reserved nothing and left the request where it was.
    species_after_rejection = build.get_species(species_id)
    assert species_after_rejection["wild_take_quota_reserved"] == 1, species_after_rejection
    assert species_after_rejection["version"] == species_after_first["version"], species_after_rejection

    untouched = build.get_acquisition(second["id"])
    assert untouched["status"] == "PENDING_PERMIT", untouched["status"]
    assert untouched["cleared_by_user_id"] is None, untouched["cleared_by_user_id"]
    assert untouched["sustainability_score_variant"] == "PROVISIONAL", untouched
    assert untouched["quota_units_reserved"] == 0, untouched["quota_units_reserved"]

    # Re-reading the species version lets the identical clearance through.
    cleared_second = validate_success(
        api.clear_acquisition_request(
            second["id"],
            factories.clearance_payload(species_after_rejection["version"]),
            make_director_headers(CLEARANCE_OFFICER_ID),
        ),
        200,
    )
    assert cleared_second["status"] == "CLEARED", cleared_second["status"]
    assert cleared_second["quota_units_reserved"] == 1, cleared_second["quota_units_reserved"]
    assert build.get_species(species_id)["wild_take_quota_reserved"] == 2


def test_a_single_normal_sample_discards_the_accumulated_breach_run(build):
    """The two alarm counters are mutually exclusive, reading by reading.

    PRD §3.1: "From `NORMAL`, a `NORMAL` reading holds the band and increments
    `consecutive_normal_readings` while zeroing `consecutive_breach_readings`. A `WARNING`
    reading moves the plant to `WARNING`, increments `consecutive_breach_readings`, zeroes
    `consecutive_normal_readings`, updates `water_quality_index`, and drives every exhibit
    the plant serves to `RESTRICTED` with `last_posture_reason` set to `LSS_WARNING`."

    PRD §3.1: "A `NORMAL` reading is where the hysteresis lives: the plant returns to
    `NORMAL` only when this reading brings `consecutive_normal_readings` to 3 or more;
    while the incremented count is still below 3 the plant holds `WARNING` and merely
    records the progress."

    Design: Corner/cross_cutting_complexity_layers/layer_breach_counter_resets_on_a_single_normal_reading
    """
    build.advance_to("2026-08-05T00:00:00Z")
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant)
    assertions.assert_alarm(build.get_plant(plant["id"]), "NORMAL", normals=0, breaches=0)

    # First breach: NORMAL -> WARNING.
    build.append_graded_reading(plant, "WARNING", taken_at="2026-08-01T00:00:00Z")
    assertions.assert_alarm(build.get_plant(plant["id"]), "WARNING", normals=0, breaches=1)

    # Second breach: WARNING holds and the breach run grows.
    build.append_graded_reading(plant, "WARNING", taken_at="2026-08-02T00:00:00Z")
    assertions.assert_alarm(build.get_plant(plant["id"]), "WARNING", normals=0, breaches=2)
    assertions.assert_posture(build.get_exhibit(exhibit["id"]), "RESTRICTED", "LSS_WARNING")

    # One clean sample zeroes two accumulated breaches but cannot clear the band alone.
    build.append_graded_reading(plant, "NORMAL", taken_at="2026-08-03T00:00:00Z")
    assertions.assert_alarm(build.get_plant(plant["id"]), "WARNING", normals=1, breaches=0)

    # A fresh breach discards the recovery run in turn.
    build.append_graded_reading(plant, "WARNING", taken_at="2026-08-04T00:00:00Z")
    assertions.assert_alarm(build.get_plant(plant["id"]), "WARNING", normals=0, breaches=1)

    # The recovery has to start over from one.
    build.append_graded_reading(plant, "NORMAL", taken_at="2026-08-05T00:00:00Z")
    final_plant = build.get_plant(plant["id"])
    assertions.assert_alarm(final_plant, "WARNING", normals=1, breaches=0)
    assertions.assert_scaled_equal(final_plant["water_quality_index"], 100.00)

    # The exhibit never returned to OPEN, because the plant never left WARNING.
    assertions.assert_posture(build.get_exhibit(exhibit["id"]), "RESTRICTED", "LSS_WARNING")


def test_permit_requirement_follows_the_species_the_source_type_or_neither(build, api):
    """`permit_required` is a disjunction, so only the unprotected captive-bred line is exempt.

    PRD §3.3: "`permit_required` is true exactly when `protection_status` is anything
    other than `UNLISTED`."

    PRD §3.5: "Creation also stamps the request's `permit_required`, which is true when the
    species' own `permit_required` is true **or** `source_type` is `WILD_COLLECTION`."

    PRD §3.5: "When it is true the request moves from `DRAFT` to `PENDING_PERMIT` and
    `permit_deadline_at` is set to the logical clock advanced by 30 days. When it is false
    the request moves from `DRAFT` to `READY_FOR_CLEARANCE` and `permit_deadline_at` stays
    null."

    Design: Corner/cross_cutting_complexity_layers/layer_permit_required_is_derived_from_two_independent_sources
    """
    plant = build.create_plant()
    exhibit_unlisted = build.create_exhibit(plant)
    exhibit_protected = build.create_exhibit(plant)
    species_unlisted = build.create_species(
        protection_status="UNLISTED", sustainability_rating="GREEN"
    )
    species_protected = build.create_species(
        protection_status="CITES_APPENDIX_II", sustainability_rating="YELLOW"
    )

    # Source one, on its own: the species' protection standing.
    assert species_unlisted["permit_required"] is False, species_unlisted
    assert species_protected["permit_required"] is True, species_protected

    entry_unlisted = build.create_approved_plan_entry(
        exhibit_unlisted,
        species_unlisted,
        planned_count=4,
        sustainability_requirement="ANY_WITH_JUSTIFICATION",
    )
    entry_protected = build.create_approved_plan_entry(
        exhibit_protected,
        species_protected,
        planned_count=4,
        sustainability_requirement="ANY_WITH_JUSTIFICATION",
    )
    institution = build.create_institution(welfare_audit_score=88.00)

    # Neither source: an unlisted species obtained from captive stock.
    neither = build.create_acquisition(
        entry_unlisted,
        source_type="CAPTIVE_BRED",
        requested_count=1,
        justification="founder stock for the regional programme",
    )
    # Source type alone: wild collection of an unlisted species.
    source_only = build.create_acquisition(
        entry_unlisted,
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
        justification="range-state quota allocation",
    )
    # Species alone: captive-bred stock of a listed species.
    species_only = build.create_acquisition(
        entry_protected,
        source_type="CAPTIVE_BRED",
        requested_count=1,
        justification="F2 captive stock from a partner institution",
    )
    # Both sources at once.
    both = build.create_acquisition(
        entry_protected,
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
        justification="CITES-managed range-state collection",
    )

    assert neither["permit_required"] is False, neither
    assert source_only["permit_required"] is True, source_only
    assert species_only["permit_required"] is True, species_only
    assert both["permit_required"] is True, both

    # The submission target proves the derivation rather than echoing the flag.
    exempt = build.submit_acquisition(neither["id"])
    assert exempt["status"] == "READY_FOR_CLEARANCE", exempt["status"]
    assert exempt["permit_deadline_at"] is None, exempt["permit_deadline_at"]

    for request in (source_only, species_only, both):
        submitted = build.submit_acquisition(request["id"])
        assert submitted["status"] == "PENDING_PERMIT", (request["id"], submitted["status"])
        assert submitted["permit_deadline_at"] is not None, (request["id"], submitted)

    # Re-read every request through its own endpoint, then through the filtered list.
    assert build.get_acquisition(neither["id"])["status"] == "READY_FOR_CLEARANCE"
    for request in (source_only, species_only, both):
        assert build.get_acquisition(request["id"])["status"] == "PENDING_PERMIT", request["id"]

    rows, meta = validate_paginated(
        api.list_acquisition_requests(CURATOR_HEADERS, {"status": "PENDING_PERMIT", "limit": 10})
    )
    assert meta["total_count"] == 3, meta
    assert {row["id"] for row in rows} == {source_only["id"], species_only["id"], both["id"]}
