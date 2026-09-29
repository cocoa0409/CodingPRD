"""Entity contracts for the Solar Reroof Coordination API.

Creation echo, declared defaults, retrieval of stored plus derived fields,
paginated and filtered listing, required-field and enum rejection, the
immutability of an authority having jurisdiction, and the two distinct failures
that a body-borne foreign key can produce.
"""

from test_helpers import (
    COORD,
    CLOCK_EPOCH,
    add_circuit,
    api_client,
    assert_jurisdiction,
    assert_party,
    assert_project,
    create_core_parties,
    create_jurisdiction,
    create_project,
    is_valid_uuid,
    make_ahj_inspector_headers,
    make_solar_contractor_headers,
    make_solar_owner_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The logical clock reading before any clock-setting call, rendered with the
# three fractional digits the envelope mandates.
EPOCH_RENDERED = "2026-08-01T00:00:00.000Z"

UNKNOWN_CIRCUIT_ID = "00000000-0000-0000-0000-0000000000aa"


# --------------------------------------------------------------------------
# Private setup helpers
# --------------------------------------------------------------------------
def _host_owned_overrides(site_address: str) -> dict:
    return {
        "site_address": site_address,
        "system_dc_kw": 6.0,
        "baseline_daily_kwh": 30.0,
        "downtime_days_estimated": 4,
        "upgrade_budget_cents": 2_000_000,
    }


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------
def test_party_creation_returns_201_with_every_declared_field():
    """A party create echoes every supplied attribute and mints its own identity.

    PRD §3.1: "A coordinator registers each participant as a **Party** carrying a
    legal or trade `name` (non-empty, at most 200 characters), a `party_type`, and
    a `contact_email` that must contain an at-sign."
    PRD §2.4: "Each persisted resource receives a server-minted `id` formatted as a
    UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601
    UTC instant with three fractional digits."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that starts at 1 on creation and increments
    by one on every mutation of that resource — including mutations that only
    rewrite derived fields such as a project's counters, posture or credit
    accounts."

    Design: Corner/entities/corner_party_creation_returns_201_with_every_declared_field
    """
    set_clock(CLOCK_EPOCH)

    payload = {
        "name": "Ridgeline Roofing",
        "party_type": "ROOFER",
        "contact_email": "ops@ridgeline.example",
        "mobilization_buffer_minutes": 90,
        "daily_crew_capacity": 2,
        "license_number": "ROC-338211",
    }
    response = api_client.create_party(payload, COORD)
    party = validate_success(response, 201)
    assert_party(party)

    assert party["name"] == "Ridgeline Roofing", party["name"]
    assert party["party_type"] == "ROOFER", party["party_type"]
    assert party["contact_email"] == "ops@ridgeline.example", party["contact_email"]
    assert party["mobilization_buffer_minutes"] == 90, (
        f"supplied mobilization_buffer_minutes must be echoed, got "
        f"{party['mobilization_buffer_minutes']}"
    )
    assert party["daily_crew_capacity"] == 2, party["daily_crew_capacity"]
    assert party["license_number"] == "ROC-338211", party["license_number"]
    assert party["version"] == 1, f"version starts at 1 on creation, got {party['version']}"
    assert is_valid_uuid(party["id"]), f"id must be a bare UUID, got {party['id']}"
    assert party["created_at"] == EPOCH_RENDERED, (
        f"created_at must be the logical clock reading, got {party['created_at']}"
    )

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource carries response_type 'object', got {body['response_type']}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}"
    )


def test_party_and_jurisdiction_defaults_applied_when_optional_inputs_omitted():
    """Omitted optional inputs land on the published defaults, not on null or zero.

    PRD §3.1: "Two scheduling attributes come with the party rather than with each
    job: `mobilization_buffer_minutes`, the mobilization and demobilization time
    the party needs on either side of any crew window, which defaults to two hours
    and must be between 0 and 480 minutes inclusive; and `daily_crew_capacity`, an
    informational crew-count-per-day figure that defaults to 1 and must be at least
    1."
    PRD §3.1: "Contractor parties also carry a `license_number`; it defaults to
    absent, and it is legitimately absent for solar-owner and system-owner parties,
    who hold no licence."
    PRD §3.1: "Finally `expedite_fee_cents`, defaulting to zero and never negative,
    is the surcharge the authority charges for expedited handling."

    Design: Corner/entities/corner_party_and_jurisdiction_defaults_applied_when_optional_inputs_omitted
    """
    set_clock(CLOCK_EPOCH)

    party = validate_success(
        api_client.create_party(
            {
                "name": "Ridgeline Roofing",
                "party_type": "ROOFER",
                "contact_email": "ops@ridgeline.example",
            },
            COORD,
        ),
        201,
    )
    assert party["mobilization_buffer_minutes"] == 120, (
        f"the buffer defaults to two hours, got {party['mobilization_buffer_minutes']}"
    )
    assert party["daily_crew_capacity"] == 1, (
        f"daily_crew_capacity defaults to 1, got {party['daily_crew_capacity']}"
    )
    assert party.get("license_number") is None, (
        f"license_number defaults to absent, got {party.get('license_number')!r}"
    )

    jurisdiction = create_jurisdiction(
        name="Flatrock AHJ",
        code="FLATROCK",
        repermit_required_for_reinstall=False,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=5,
        permit_review_days=7,
    )
    assert jurisdiction["expedite_fee_cents"] == 0, (
        f"expedite_fee_cents defaults to zero, got {jurisdiction['expedite_fee_cents']}"
    )
    assert jurisdiction["backlog_days"] == 5, jurisdiction["backlog_days"]


# --------------------------------------------------------------------------
# Retrieval and listing
# --------------------------------------------------------------------------
def test_project_retrieval_returns_stored_and_derived_fields():
    """A freshly opened LEASE project reads back its inputs and its derived opening state.

    PRD §3.2: "On creation the project's `phase` is `INTAKE` and its `posture` is
    `OPEN`."
    PRD §3.2: "Its `negotiation_round` starts at 1 and its `version` at 1."
    PRD §3.2: "`required_approval_party_count` is derived immediately: 3 when a
    system owner was named, otherwise 2 — this is the consent quorum."
    PRD §3.2: "`warranty_notice_status` is derived from the ownership model:
    `NOT_REQUIRED` on a `HOST_OWNED` project, `PENDING` on a `LEASE` or `PPA`
    project."
    PRD §3.2: "All four credit accounts and every derived counter start at zero,
    `warranty_preserved` starts true, and `authorized_at`, `deenergized_at` and
    `reenergized_at` all start absent."

    Design: Corner/entities/corner_project_retrieval_returns_stored_and_derived_fields
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    project = create_project(
        parties,
        ownership_model="LEASE",
        site_address="418 Mesquite Way, Tempe AZ",
        system_dc_kw=8.4,
        baseline_daily_kwh=41.75,
        downtime_days_estimated=9,
        upgrade_budget_cents=5_000_000,
    )

    read = validate_success(
        api_client.get_project(
            project["id"], make_solar_owner_headers(parties["owner"]["id"])
        ),
        200,
    )
    assert_project(read)

    assert read["phase"] == "INTAKE", read["phase"]
    assert read["posture"] == "OPEN", read["posture"]
    assert read["negotiation_round"] == 1, read["negotiation_round"]
    assert read["required_approval_party_count"] == 3, (
        f"a named system owner makes the quorum 3, got "
        f"{read['required_approval_party_count']}"
    )
    assert read["warranty_notice_status"] == "PENDING", read["warranty_notice_status"]
    assert read["system_dc_kw"] == 8.4, read["system_dc_kw"]
    assert read["version"] == 1, read["version"]
    assert read["registered_unit_count"] == 0, read["registered_unit_count"]
    assert read["credit_authorized_cents"] == 0, read["credit_authorized_cents"]
    assert read["warranty_preserved"] is True, read["warranty_preserved"]


def test_project_listing_is_paginated_and_filterable_by_phase():
    """The envelope's pagination fields are live, and the phase filter narrows the set.

    PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may be
    no smaller than 1 and no larger than 100."
    PRD §2.3: "`offset` is the number of rows to skip and defaults to 0."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/corner_project_listing_is_paginated_and_filterable_by_phase
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    for address in ("1 First St, Tempe AZ", "2 Second St, Tempe AZ", "3 Third St, Tempe AZ"):
        create_project(
            parties, ownership_model="HOST_OWNED", **_host_owned_overrides(address)
        )

    first_response = api_client.list_projects(COORD, {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_response)
    assert len(rows) == 2, f"limit 2 must return exactly 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert first_response.json()["response_type"] == "array", (
        first_response.json()["response_type"]
    )

    second_response = api_client.list_projects(COORD, {"limit": 2, "offset": 2})
    rows, meta = validate_paginated(second_response)
    assert len(rows) == 1, f"offset 2 must return the remaining row, got {len(rows)}"
    assert meta["total_count"] == 3, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert second_response.json()["response_type"] == "array", (
        second_response.json()["response_type"]
    )

    filtered_response = api_client.list_projects(COORD, {"phase": "AUTHORIZED"})
    rows, meta = validate_paginated(filtered_response)
    assert rows == [], f"no project is AUTHORIZED yet, got {len(rows)} rows"
    assert meta["total_count"] == 0, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert filtered_response.json()["response_type"] == "array", (
        filtered_response.json()["response_type"]
    )


# --------------------------------------------------------------------------
# Schema rejection
# --------------------------------------------------------------------------
def test_project_create_missing_required_ownership_model_is_invalid_request():
    """A project create without ownership_model is a schema violation and persists nothing.

    PRD §3.2: "A coordinator opens a **ReroofProject** by naming the
    `site_address`, the `ownership_model` — one of `HOST_OWNED`, `LEASE` or `PPA` —
    the array's nameplate `system_dc_kw` (strictly positive), and the four party
    references: `roofer_party_id`, `solar_owner_party_id`,
    `solar_contractor_party_id` and, conditionally, `system_owner_party_id`."
    PRD §2.11: "5. Request-body schema: required fields present, enum members
    legal, numeric ranges respected, ISO 8601 timestamps parseable,
    `accepts_unit_types` a non-empty subset of `PANEL` and `OPTIMIZER`, pagination
    `limit` between 1 and 100 inclusive — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_project_create_missing_required_ownership_model_is_invalid_request
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()

    response = api_client.create_project(
        {
            "site_address": "77 Ocotillo Ln, Chandler AZ",
            "system_dc_kw": 6.0,
            "roofer_party_id": parties["roofer"]["id"],
            "solar_owner_party_id": parties["owner"]["id"],
            "solar_contractor_party_id": parties["crew"]["id"],
            "baseline_daily_kwh": 30.0,
            "downtime_days_estimated": 4,
            "upgrade_budget_cents": 2_000_000,
        },
        COORD,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 422)

    rows, meta = validate_paginated(api_client.list_projects(COORD))
    assert rows == [], f"a rejected create must persist no project, got {len(rows)} rows"
    assert meta["total_count"] == 0, meta["total_count"]


def test_party_create_with_invalid_enum_party_type_is_rejected():
    """party_type is closed over four members, so an out-of-domain value never persists.

    PRD §3.1: "The `party_type` is one of `ROOFER`, `SOLAR_OWNER`, `SYSTEM_OWNER`
    or `SOLAR_CONTRACTOR`, and it decides where in the triangle that party sits."
    PRD §2.11: "5. Request-body schema: required fields present, enum members
    legal, numeric ranges respected, ISO 8601 timestamps parseable,
    `accepts_unit_types` a non-empty subset of `PANEL` and `OPTIMIZER`, pagination
    `limit` between 1 and 100 inclusive — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_party_create_with_invalid_enum_party_type_is_rejected
    """
    set_clock(CLOCK_EPOCH)

    response = api_client.create_party(
        {
            "name": "Bogus Inspector Co",
            "party_type": "INSPECTOR",
            "contact_email": "nobody@example.com",
        },
        COORD,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 422)

    rows, meta = validate_paginated(api_client.list_parties(COORD))
    assert rows == [], f"a rejected create must persist no party, got {len(rows)} rows"
    assert meta["total_count"] == 0, meta["total_count"]


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------
def test_jurisdiction_is_immutable_and_exposes_no_version_field():
    """An authority having jurisdiction reads back with no version and no updated_at.

    PRD §2.4: "`Jurisdiction` is the sole exception: an authority-having-jurisdiction
    record is immutable once created, has no update endpoint, and carries
    **neither** `updated_at` **nor** `version`."
    PRD §2.4: "It has only `id` and `created_at` alongside its own attributes."

    Design: Corner/entities/corner_jurisdiction_is_immutable_and_exposes_no_version_field
    """
    set_clock(CLOCK_EPOCH)
    jurisdiction = create_jurisdiction(
        name="Westvale AHJ",
        code="WESTVALE",
        repermit_required_for_reinstall=True,
        reinspection_required=True,
        inspection_slots_per_day=2,
        backlog_days=2,
        permit_review_days=10,
        expedite_fee_cents=12_000,
    )

    read = validate_success(
        api_client.get_jurisdiction(
            jurisdiction["id"], make_ahj_inspector_headers(jurisdiction["id"])
        ),
        200,
    )
    assert_jurisdiction(read)

    assert read["code"] == "WESTVALE", read["code"]
    assert read["expedite_fee_cents"] == 12_000, read["expedite_fee_cents"]
    assert read["created_at"] == EPOCH_RENDERED, read["created_at"]
    assert "version" not in read, "a jurisdiction must expose no version field"
    assert "updated_at" not in read, "a jurisdiction must expose no updated_at field"


def test_project_system_and_computed_fields_are_server_derived():
    """A HOST_OWNED create derives phase, posture, version, counters and the quorum itself.

    PRD §3.2: "On creation the project's `phase` is `INTAKE` and its `posture` is
    `OPEN`."
    PRD §3.2: "`required_approval_party_count` is derived immediately: 3 when a
    system owner was named, otherwise 2 — this is the consent quorum."
    PRD §3.2: "`warranty_notice_status` is derived from the ownership model:
    `NOT_REQUIRED` on a `HOST_OWNED` project, `PENDING` on a `LEASE` or `PPA`
    project."
    PRD §3.2: "All four credit accounts and every derived counter start at zero,
    `warranty_preserved` starts true, and `authorized_at`, `deenergized_at` and
    `reenergized_at` all start absent."

    Design: Corner/entities/corner_project_system_and_computed_fields_ignore_extra_field_input
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()

    project = validate_success(
        api_client.create_project(
            {
                "site_address": "77 Ocotillo Ln, Chandler AZ",
                "ownership_model": "HOST_OWNED",
                "system_dc_kw": 6.0,
                "roofer_party_id": parties["roofer"]["id"],
                "solar_owner_party_id": parties["owner"]["id"],
                "solar_contractor_party_id": parties["crew"]["id"],
                "baseline_daily_kwh": 30.0,
                "downtime_days_estimated": 4,
                "upgrade_budget_cents": 2_000_000,
            },
            COORD,
        ),
        201,
    )
    assert_project(project)

    assert project["phase"] == "INTAKE", project["phase"]
    assert project["posture"] == "OPEN", project["posture"]
    assert project["version"] == 1, project["version"]
    assert project["credit_authorized_cents"] == 0, project["credit_authorized_cents"]
    assert project["registered_unit_count"] == 0, project["registered_unit_count"]
    assert project["warranty_notice_status"] == "NOT_REQUIRED", (
        f"a HOST_OWNED project needs no manufacturer notice, got "
        f"{project['warranty_notice_status']}"
    )
    assert project["required_approval_party_count"] == 2, (
        f"with no system owner the quorum is 2, got "
        f"{project['required_approval_party_count']}"
    )
    assert project["created_at"] == EPOCH_RENDERED, project["created_at"]


# --------------------------------------------------------------------------
# Referential integrity
# --------------------------------------------------------------------------
def test_hardware_unit_body_foreign_keys_must_exist_and_stay_within_the_project():
    """An unknown circuit is a 404; a circuit owned by another project is a 422.

    PRD §2.5: "Foreign keys arriving in a request body are resolved the same way,
    before any business rule runs, and an unresolvable reference produces the
    corresponding 404: `ERR_PROJECT_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_BIN_NOT_FOUND` or
    `ERR_UNIT_NOT_FOUND`."
    PRD §2.5: "Three places must refuse it with `ERR_CROSS_PROJECT_REFERENCE`
    (HTTP 422): registering a hardware unit whose `array_circuit_id` belongs to a
    different project than the one in the path, placing a unit into a storage bin
    whose owning project differs from the unit's, and creating a sourcing order
    whose `hardware_unit_id` does not belong to the `project_id` supplied on the
    same order."

    Design: Corner/entities/corner_hardware_unit_body_foreign_keys_must_exist_and_stay_within_the_project
    """
    set_clock(CLOCK_EPOCH)
    parties = create_core_parties()
    crew_headers = make_solar_contractor_headers(parties["crew"]["id"])

    p1 = create_project(
        parties,
        ownership_model="HOST_OWNED",
        **_host_owned_overrides("77 Ocotillo Ln, Chandler AZ"),
    )
    p2 = create_project(
        parties,
        ownership_model="HOST_OWNED",
        site_address="912 Saguaro Rd, Mesa AZ",
        system_dc_kw=5.2,
        baseline_daily_kwh=26.0,
        downtime_days_estimated=3,
        upgrade_budget_cents=1_500_000,
    )
    foreign_circuit = add_circuit(p2["id"], circuit_label="S2", module_count=1, dc_kw=0.41)

    unit_payload = {
        "unit_type": "PANEL",
        "manufacturer": "Meridian Solar",
        "model_code": "MS-410",
        "serial_number": "SN-0001",
        "rated_watts": 410,
    }

    missing = api_client.create_hardware_unit(
        p1["id"], {"array_circuit_id": UNKNOWN_CIRCUIT_ID, **unit_payload}, crew_headers
    )
    validate_error(missing, "ERR_CIRCUIT_NOT_FOUND", 404)

    cross = api_client.create_hardware_unit(
        p1["id"], {"array_circuit_id": foreign_circuit["id"], **unit_payload}, crew_headers
    )
    validate_error(cross, "ERR_CROSS_PROJECT_REFERENCE", 422)

    p1_read = validate_success(api_client.get_project(p1["id"], COORD), 200)
    p2_read = validate_success(api_client.get_project(p2["id"], COORD), 200)
    assert p1_read["registered_unit_count"] == 0, p1_read["registered_unit_count"]
    assert p2_read["registered_unit_count"] == 0, p2_read["registered_unit_count"]


def test_path_ids_that_do_not_exist_return_the_resource_specific_not_found():
    """Each unknown path identifier answers with its own family's 404, not a generic one.

    PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    identifier that does not resolve determines the 404 that comes back:
    `ERR_PROJECT_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND` or
    `ERR_SOURCING_ORDER_NOT_FOUND`."
    PRD §2.11: "3. Existence of every path resource, left to right — the family of
    404s in §2.5."

    Design: Corner/entities/corner_path_ids_that_do_not_exist_return_the_resource_specific_not_found
    """
    set_clock(CLOCK_EPOCH)

    probes = [
        (
            "GET /reroof/projects/{id}",
            api_client.get_project("00000000-0000-0000-0000-000000000001", COORD),
            "ERR_PROJECT_NOT_FOUND",
        ),
        (
            "GET /reroof/parties/{id}",
            api_client.get_party("00000000-0000-0000-0000-000000000002", COORD),
            "ERR_PARTY_NOT_FOUND",
        ),
        (
            "GET /reroof/party-approvals/{id}",
            api_client.get_party_approval("00000000-0000-0000-0000-000000000003", COORD),
            "ERR_APPROVAL_NOT_FOUND",
        ),
        (
            "GET /reroof/array-circuits/{id}",
            api_client.get_array_circuit("00000000-0000-0000-0000-000000000004", COORD),
            "ERR_CIRCUIT_NOT_FOUND",
        ),
        (
            "GET /reroof/hardware-units/{id}",
            api_client.get_hardware_unit("00000000-0000-0000-0000-000000000005", COORD),
            "ERR_UNIT_NOT_FOUND",
        ),
        (
            "GET /reroof/deck-findings/{id}",
            api_client.get_deck_finding("00000000-0000-0000-0000-000000000006", COORD),
            "ERR_FINDING_NOT_FOUND",
        ),
        (
            "GET /reroof/permit-applications/{id}",
            api_client.get_permit_application(
                "00000000-0000-0000-0000-000000000007", COORD
            ),
            "ERR_PERMIT_NOT_FOUND",
        ),
        (
            "GET /reroof/inspections/{id}",
            api_client.get_inspection("00000000-0000-0000-0000-000000000008", COORD),
            "ERR_INSPECTION_NOT_FOUND",
        ),
        (
            "GET /reroof/work-windows/{id}",
            api_client.get_work_window("00000000-0000-0000-0000-000000000009", COORD),
            "ERR_WINDOW_NOT_FOUND",
        ),
        (
            "GET /reroof/sourcing-orders/{id}",
            api_client.get_sourcing_order("00000000-0000-0000-0000-00000000000a", COORD),
            "ERR_SOURCING_ORDER_NOT_FOUND",
        ),
    ]

    for label, response, expected_error_id in probes:
        assert response.status_code == 404, (
            f"{label} on an unknown id must answer HTTP 404, got {response.status_code}"
        )
        validate_error(response, expected_error_id, 404)
