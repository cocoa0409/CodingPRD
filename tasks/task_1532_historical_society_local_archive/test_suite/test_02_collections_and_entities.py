"""Entity surfaces: creation defaults, server-controlled fields, the
collection hierarchy, catalog shape validation, and holdings rollups."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_accession,
    assert_deed,
    assert_item,
    assert_project,
    assert_researcher,
    assert_storage_zone,
    catalog_item,
    create_accession,
    create_accessioned,
    create_collection,
    create_deed,
    create_item,
    create_project,
    create_zone,
    get_collection,
    register_researcher,
    submit_accession,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = {"X-User-ID": "reg-1", "X-User-Role": "Registrar", "Content-Type": "application/json"}
ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
COORD = {"X-User-ID": "coord-1", "X-User-Role": "VolunteerCoordinator", "Content-Type": "application/json"}


class TestCreationDefaults:

    def test_entity_creation_defaults_applied(self):
        """PRD §2.6: "Each storage zone is defined by a unique `zone_code` (a
        duplicate code is rejected with `ERR_ZONE_CODE_EXISTS`), a
        human-readable `name`, and four configurable thresholds that govern
        breach detection: `temp_high_c` (default 24.0), `temp_low_c` (default
        14.0), `humidity_high_pct` (default 60.0), and `humidity_low_pct`
        (default 30.0). A newly created zone begins with `posture` `OPEN`, a
        `breach_streak` of zero, and an empty `recent_readings` log."
        PRD §3.1: "The deed captures four donor terms: `reproduction_restricted`
        (default false), which when true on the executed deed bars reproduction
        orders covering the accession's items; `publication_license_required`
        (default false), which bars personal-class reproduction orders"
        PRD §3.5: "an optional `max_hours_per_volunteer` — the lifetime
        per-volunteer hour cap for the project, defaulting to 40 hours. A
        project begins `PLANNED` with `volunteer_hours` an empty map,
        `hours_logged_total` zero, and `active_ticket_count` zero."

        Design: Corner/entities/entity_creation_defaults_applied
        """
        accession = create_accession()
        submit_accession(accession["id"])

        zone_data = validate_success(
            api_client.create_storage_zone({"zone_code": "Z1", "name": "Vault A"},
                                           REG),
            expected_status=201)
        assert_storage_zone(zone_data)
        assert zone_data["temp_high_c"] == 24.0
        assert zone_data["temp_low_c"] == 14.0
        assert zone_data["humidity_high_pct"] == 60.0
        assert zone_data["humidity_low_pct"] == 30.0
        assert zone_data["posture"] == "OPEN"
        assert zone_data["breach_streak"] == 0

        deed_data = validate_success(
            api_client.create_deed(accession["id"], {}, REG),
            expected_status=201)
        assert_deed(deed_data)
        assert deed_data["reproduction_restricted"] is False
        assert deed_data["publication_license_required"] is False
        assert deed_data["deed_version"] == 1

        project_data = validate_success(
            api_client.create_volunteer_project({"name": "P1"}, COORD),
            expected_status=201)
        assert_project(project_data)
        assert project_data["max_hours_per_volunteer"] == 40
        assert project_data["status"] == "PLANNED"


class TestServerControlledFields:

    def test_computed_and_system_fields_server_controlled(self):
        """PRD §3.1: "At creation the accession enters `DRAFT` status and is
        assigned its `accession_number`: the four-digit year of its
        `created_at`, a hyphen, and the 1-based count of accessions created in
        that calendar year, zero-padded to three digits."
        PRD §3.2: "The new item enters `PENDING_CATALOG` and the collection's
        `item_count` increases by 1."
        PRD §3.6: "The record begins `ACTIVE` with `no_show_strikes` at zero and
        `total_charged_cents` at zero"

        Design: Corner/entities/computed_and_system_fields_server_controlled
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        assert_accession(accession)
        # Server clock starts 2026-08-01 (PRD §2.5); this is the first
        # accession created in that calendar year.
        assert accession["accession_number"] == "2026-001", (
            f"expected '2026-001', got {accession['accession_number']}")

        item1 = create_item(accession["id"], collection["id"], title="I1")
        create_item(accession["id"], collection["id"], title="I2")
        assert_item(item1)
        assert item1["status"] == "PENDING_CATALOG"

        coll = get_collection(collection["id"])
        assert coll["item_count"] == 2
        assert coll["published_finding_aid_present"] is False

        researcher = register_researcher()
        assert_researcher(researcher)
        assert researcher["no_show_strikes"] == 0
        assert researcher["total_charged_cents"] == 0
        assert researcher["status"] == "ACTIVE"

    def test_system_fields_input_ignored(self):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix. An `id` serves identity only and is never
        itself a decision input."
        PRD §2.4: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource, including mutations
        caused by cascades originating elsewhere."

        Design: Corner/entities/system_fields_input_ignored
        """
        supplied_id = "11111111-2222-3333-4444-555555555555"
        data = validate_success(
            api_client.create_storage_zone(
                {"zone_code": "Z1", "name": "Vault A",
                 "id": supplied_id, "version": 99,
                 "created_at": "1999-01-01T00:00:00Z"},
                REG),
            expected_status=201)
        assert data["id"] != supplied_id, (
            "server must mint its own id, ignoring the client-supplied one")
        assert data["version"] == 1, (
            f"client-supplied version 99 must be ignored; got {data['version']}")
        assert_storage_zone(data)


class TestCollectionHierarchy:

    def test_collection_hierarchy_reverse_view(self):
        """PRD §2.3: "Collections filter by `parent_collection_id`,
        `storage_zone_id`, and `status`."
        PRD §3.2: "Holdings are organized into **collections**, created by a
        `Registrar` with a `title`, a unique `collection_code` (a duplicate is
        rejected with `ERR_COLLECTION_CODE_EXISTS`), the `storage_zone_id` of
        the zone where the collection's physical items sit, and an optional
        `parent_collection_id` for fonds-and-series hierarchy."

        Design: Corner/entities/collection_hierarchy_reverse_view
        """
        zone = create_zone()
        parent = create_collection(zone["id"], collection_code="P",
                                   title="Parent")
        child1 = create_collection(zone["id"], collection_code="C1",
                                   title="Child1",
                                   parent_collection_id=parent["id"])
        child2 = create_collection(zone["id"], collection_code="C2",
                                   title="Child2",
                                   parent_collection_id=parent["id"])
        create_collection(zone["id"], collection_code="U", title="Unrelated")

        data, meta = validate_paginated(api_client.list_collections(
            REG, params={"parent_collection_id": parent["id"]}))
        ids = [row["id"] for row in data]
        assert meta["total_count"] == 2
        assert sorted(ids) == sorted([child1["id"], child2["id"]]), (
            f"expected exactly the two children, got {ids}")

    def test_collection_parent_cycle_rejected(self):
        """PRD §3.2: "Hierarchy maintenance is possible afterward by
        reparenting: the new parent must exist (`ERR_NOT_FOUND`), must be
        neither the collection itself nor one of its descendants
        (`ERR_COLLECTION_CYCLE`), and the collection being moved must be
        `ACTIVE` (`ERR_INVALID_STATE`)."

        Design: Corner/entities/collection_parent_cycle_rejected
        """
        zone = create_zone()
        p = create_collection(zone["id"], collection_code="P", title="P")
        c1 = create_collection(zone["id"], collection_code="C1", title="C1",
                               parent_collection_id=p["id"])
        c2 = create_collection(zone["id"], collection_code="C2", title="C2",
                               parent_collection_id=c1["id"])
        r = create_collection(zone["id"], collection_code="R", title="R")

        resp1 = api_client.patch_collection(
            c1["id"], {"parent_collection_id": c2["id"]}, REG)
        validate_error(resp1, ApiErrorId.ERR_COLLECTION_CYCLE)

        resp2 = api_client.patch_collection(
            c1["id"], {"parent_collection_id": c1["id"]}, REG)
        validate_error(resp2, ApiErrorId.ERR_COLLECTION_CYCLE)

        moved = validate_success(
            api_client.patch_collection(
                c1["id"], {"parent_collection_id": r["id"]}, REG))
        assert moved["parent_collection_id"] == r["id"]


class TestCatalogShapeValidation:

    def test_enum_rejection_on_catalog(self):
        """PRD §2.8: "3. **Request body shape**, validated before any resource
        lookup — required fields are present; enum values fall in their declared
        sets; time ranges are coherent (an appointment's `start_time` strictly
        precedes its `end_time`, and a recording's `session_start` strictly
        precedes its `session_end`); logged hours are a positive multiple of
        0.25; item-id arrays are duplicate-free; a research request carries at
        least one and no more than ten item ids (more than ten yields
        `ERR_TOO_MANY_ITEMS`); a reproduction order's item array is non-empty
        (`ERR_ITEM_NOT_IN_REQUEST`); and pagination parameters on list endpoints
        obey their ranges (`ERR_INVALID_PAGINATION_PARAMETERS`). All other shape
        failures yield `ERR_INVALID_REQUEST`."
        PRD §3.2: "cataloging moves the item `PENDING_CATALOG → CATALOGED` and
        stores the `description`, the `condition_grade` (one of `EXCELLENT`,
        `GOOD`, `FAIR`, `POOR`, `FRAGILE`), the item-level
        `appraised_value_cents` (non-negative), and the `format` (one of
        `MANUSCRIPT`, `PHOTOGRAPH`, `MAP`, `ARTIFACT`, `AUDIOVISUAL`,
        `BOUND_VOLUME`)."

        Design: Corner/entities/enum_rejection_on_catalog
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        item = create_item(accession["id"], collection["id"])

        resp = api_client.catalog_item(
            item["id"],
            {"description": "x", "condition_grade": "TERRIBLE",
             "appraised_value_cents": 100, "format": "MAP"},
            ARCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        after = validate_success(api_client.get_item(item["id"], ARCH))
        assert after["status"] == "PENDING_CATALOG", (
            f"failed catalog must not change state; got {after['status']}")
