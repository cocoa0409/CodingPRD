"""Entity-level conventions: creation echoes, reads, listings, defaults, system fields."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_common_fields,
    assert_same_instant,
    create_employee_payload,
    create_jurisdiction_payload,
    create_legal_reviewer_payload,
    is_valid_uuid,
    make_admin_headers,
    make_author_headers,
    new_jurisdiction,
    set_clock,
    unique_state_code,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_jurisdiction_creation_echoes_every_declared_field():
    """PRD §3.1: "A jurisdiction is registered with a `state_code`, which is an
    uppercase two-character US state or territory code and must be globally unique,
    and a human-readable `display_name`." ... "`esign_permitted` defaults to true ...
    `proxy_ack_permitted` defaults to false ... `ack_window_buffer_days` defaults to
    3".  PRD §2.4: "`version`, a monotonic integer that starts at 1 when the row is
    created".

    Design: Corner/entities/corner_jurisdiction_creation_echoes_all_declared_fields
    """
    payload = create_jurisdiction_payload(
        display_name="California",
        min_legal_review_days=10,
        ack_deadline_days=30,
        retention_years=5,
        required_language_codes=["en", "es"],
        esign_permitted=True,
        proxy_ack_permitted=False,
        ack_window_buffer_days=3,
    )

    data = validate_success(
        api_client.create_jurisdiction(payload, make_admin_headers()), 201
    )

    assert data["state_code"] == payload["state_code"]
    assert data["display_name"] == "California"
    assert data["min_legal_review_days"] == 10
    assert data["ack_deadline_days"] == 30
    assert data["retention_years"] == 5
    assert data["required_language_codes"] == ["en", "es"]
    assert data["esign_permitted"] is True
    assert data["proxy_ack_permitted"] is False
    assert data["ack_window_buffer_days"] == 3
    assert_common_fields(data)
    assert data["version"] == 1, f"a fresh row starts at version 1, got {data['version']}"
    assert_same_instant(data["created_at"], "2026-08-01T00:00:00.000Z", "created_at")


def test_legal_reviewer_single_read_returns_the_stored_row_with_zero_open_reviews():
    """PRD §3.1: "`concurrent_review_limit` defaults to 2 and caps how many of the
    reviewer's review windows may overlap at once" ... "`open_review_count` is
    maintained by the system, starts at 0, and always tracks the number of that
    reviewer's reviews whose `status` is `REQUESTED` or `IN_PROGRESS`" ... "reading
    one reviewer surfaces both `open_review_count` and `concurrent_review_limit`".

    Design: Corner/entities/corner_legal_reviewer_single_resource_get_returns_stored_row
    """
    jurisdiction = new_jurisdiction()
    created = validate_success(
        api_client.create_legal_reviewer(
            create_legal_reviewer_payload(
                jurisdiction["id"],
                full_name="Ada Counsel",
                bar_number="CA-1",
                concurrent_review_limit=2,
                is_active=True,
            ),
            make_admin_headers(),
        ),
        201,
    )

    data = validate_success(
        api_client.get_legal_reviewer(created["id"], make_admin_headers())
    )
    assert data["id"] == created["id"]
    assert data["jurisdiction_id"] == jurisdiction["id"]
    assert data["bar_number"] == "CA-1"
    assert data["full_name"] == "Ada Counsel"
    assert data["concurrent_review_limit"] == 2
    assert data["is_active"] is True
    assert data["open_review_count"] == 0, (
        f"no review has been raised, so open_review_count is 0, got {data['open_review_count']}"
    )
    assert data["version"] == 1


def test_jurisdiction_listing_counts_the_whole_filtered_set_not_the_page():
    """PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows that
    satisfy the filters before the window is applied and `has_more` indicates whether
    any rows remain beyond the current window."  PRD §2.3: "collections are returned
    sorted by `created_at` in ascending order, so the oldest row appears first".

    Design: Corner/entities/corner_jurisdiction_listing_paginates_with_total_count_and_has_more
    """
    first = new_jurisdiction(display_name="California")
    second = new_jurisdiction(display_name="Texas")
    third = new_jurisdiction(display_name="New York")

    rows, meta = validate_paginated(
        api_client.list_jurisdictions(make_admin_headers(), params={"limit": 2, "offset": 0})
    )

    assert len(rows) == 2, f"a limit of 2 must return exactly 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"total_count counts the whole filtered set, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        "one row remains beyond the window, so has_more must be true"
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "rows must come back in created_at ascending order"
    )

    tail, tail_meta = validate_paginated(
        api_client.list_jurisdictions(make_admin_headers(), params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in tail] == [third["id"]]
    assert tail_meta["has_more"] is False, (
        "no rows remain past the third, so has_more must be false"
    )
    assert tail_meta["total_count"] == 3


def test_unknown_policy_version_path_id_answers_resource_not_found():
    """PRD §2.8: "Every path identifier is resolved **left to right in path order**,
    so on a nested path the outer resource is looked up before the inner one and the
    first unresolvable segment is the one reported; failure yields
    `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/entities/corner_unknown_policy_version_id_returns_resource_not_found
    """
    validate_error(
        api_client.get_policy_version(NON_EXISTENT_UUID, make_admin_headers()),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        404,
    )


def test_employee_creation_without_work_email_is_a_schema_failure():
    """PRD §3.1: "An employee record is created with a `jurisdiction_id` naming the
    work-location jurisdiction that governs their deadlines and retention, a globally
    unique `work_email` that must contain an `@` character, and a `full_name`."  PRD
    §2.8: "the request body must satisfy the endpoint's input schema — required
    fields present ... with any failure yielding `ERR_VALIDATION` (422)."

    Design: Corner/entities/corner_employee_creation_missing_work_email_rejected
    """
    jurisdiction = new_jurisdiction()

    validate_error(
        api_client.create_employee(
            {"jurisdiction_id": jurisdiction["id"], "full_name": "No Email"},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    rows, meta = validate_paginated(
        api_client.list_employees(
            make_admin_headers(),
            params={"jurisdiction_id": jurisdiction["id"], "limit": 100},
        )
    )
    assert rows == [], "a refused create must persist no Employee row"
    assert meta["total_count"] == 0


def test_omitted_optional_inputs_fall_back_to_the_declared_defaults():
    """PRD §3.1: "`manager_id` is an optional self-referential link to another
    employee and defaults to null for the top of the reporting chain.
    `preferred_language_code` defaults to `en` ... `needs_accessible_format` defaults
    to false ... `employment_status` defaults to `ACTIVE` ... A newly created employee
    starts with `open_ack_count` at 0 and `open_escalation_count` at 0." ...
    "`concurrent_review_limit` defaults to 2 ... `is_active` defaults to true ...
    `open_review_count` is maintained by the system, starts at 0".

    Design: Corner/entities/corner_employee_optional_fields_fall_back_to_declared_defaults
    """
    jurisdiction = new_jurisdiction()

    employee = validate_success(
        api_client.create_employee(
            {
                "jurisdiction_id": jurisdiction["id"],
                "work_email": "bare@ex.com",
                "full_name": "Bare Minimum",
            },
            make_admin_headers(),
        ),
        201,
    )
    assert employee["employment_status"] == "ACTIVE", (
        f"employment_status defaults to ACTIVE, got {employee['employment_status']}"
    )
    assert employee["needs_accessible_format"] is False
    assert employee["preferred_language_code"] == "en"
    assert employee["manager_id"] is None
    assert employee["open_ack_count"] == 0
    assert employee["open_escalation_count"] == 0

    reviewer = validate_success(
        api_client.create_legal_reviewer(
            {
                "jurisdiction_id": jurisdiction["id"],
                "full_name": "Bare Counsel",
                "bar_number": "BARE-1",
            },
            make_admin_headers(),
        ),
        201,
    )
    assert reviewer["is_active"] is True, (
        f"is_active defaults to true, got {reviewer['is_active']}"
    )
    assert reviewer["concurrent_review_limit"] == 2, (
        f"concurrent_review_limit defaults to 2, got {reviewer['concurrent_review_limit']}"
    )
    assert reviewer["open_review_count"] == 0


def test_version_numbers_are_computed_by_the_server_from_the_document_history():
    """PRD §3.2: "The minted version receives `version_no` equal to the document's
    `latest_version_no` plus 1 and enters status `DRAFT`; the document's
    `latest_version_no` is incremented by 1 and the document's own `version` is
    incremented by 1. A version's `effective_date`, `window_end_date` and
    `approved_at` all start null, `revision_round` starts at 0, and
    `pinned_addendum_ids` starts as an empty array."

    Design: Corner/entities/corner_policy_document_latest_version_no_is_computed_not_supplied
    """
    from test_helpers import mint_version, new_document, refresh_document

    jurisdiction = new_jurisdiction()
    document = new_document(title="Code of Conduct 2026", category="CODE_OF_CONDUCT")
    assert document["latest_version_no"] == 0, (
        f"a document with no versions starts at 0, got {document['latest_version_no']}"
    )

    v1 = mint_version(document, [jurisdiction["id"]])
    assert v1["version_no"] == 1, f"the first version is number 1, got {v1['version_no']}"

    v2 = mint_version(refresh_document(document["id"]), [jurisdiction["id"]])
    assert v2["version_no"] == 2, f"the second version is number 2, got {v2['version_no']}"
    assert v2["status"] == "DRAFT"
    assert v2["revision_round"] == 0
    assert v2["pinned_addendum_ids"] == []
    assert v2["effective_date"] is None
    assert v2["window_end_date"] is None
    assert v2["approved_at"] is None

    reread = refresh_document(document["id"])
    assert reread["latest_version_no"] == 2, (
        f"the document must track the mint count, got {reread['latest_version_no']}"
    )
    assert reread["current_published_version_id"] is None, (
        "nothing has been released, so current_published_version_id stays null"
    )


def test_system_fields_are_server_minted_from_the_logical_clock():
    """PRD §2.4: "Every resource in this system is addressed by an `id` that is a
    server-minted UUID carrying no type prefix — clients never supply an `id` ...
    Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits recording the instant the row was written." ... "`version`, a
    monotonic integer that starts at 1 when the row is created".  PRD §2.5: "All
    temporal reasoning in this service reads a server-held **logical clock** rather
    than wall-clock time."

    Design: Corner/entities/corner_system_fields_are_server_generated_and_client_values_ignored
    """
    set_clock("2026-08-04T00:00:00Z")

    data = validate_success(
        api_client.create_policy_document(
            {
                "title": "Data Privacy Handbook 2026",
                "category": "DATA_PRIVACY",
                "max_ack_deadline_days": 10,
            },
            make_author_headers(),
        ),
        201,
    )

    assert is_valid_uuid(data["id"]), (
        f"the id must be a server-minted UUID with no type prefix, got {data['id']!r}"
    )
    assert_same_instant(data["created_at"], "2026-08-04T00:00:00.000Z", "created_at")
    assert_same_instant(data["updated_at"], "2026-08-04T00:00:00.000Z", "updated_at")
    assert data["version"] == 1
    assert data["latest_version_no"] == 0
    assert data["max_ack_deadline_days"] == 10


def test_out_of_range_integers_and_unknown_enum_values_are_schema_failures():
    """PRD §3.1: "Its `min_legal_review_days` is the minimum number of whole days ...
    it is an integer of at least 0 and at most 120." ... "`employment_status` defaults
    to `ACTIVE` and is one of `ACTIVE`, `ON_LEAVE` or `TERMINATED`."  PRD §2.8: "enum
    values within range, arrays non-empty where a non-empty array is declared, and
    integers inside their declared bounds — with any failure yielding `ERR_VALIDATION`
    (422)."

    Design: Corner/entities/corner_out_of_range_and_invalid_enum_inputs_rejected
    """
    jurisdiction = new_jurisdiction()

    bad_state = unique_state_code()
    validate_error(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(state_code=bad_state, min_legal_review_days=-1),
            make_admin_headers(),
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    rows, _meta = validate_paginated(
        api_client.list_jurisdictions(
            make_admin_headers(), params={"state_code": bad_state, "limit": 100}
        )
    )
    assert rows == [], "a refused create must persist no Jurisdiction row"

    validate_error(
        api_client.create_employee(
            create_employee_payload(
                jurisdiction["id"], employment_status="FURLOUGHED"
            ),
            make_admin_headers(),
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    employees, _ = validate_paginated(
        api_client.list_employees(
            make_admin_headers(),
            params={"jurisdiction_id": jurisdiction["id"], "limit": 100},
        )
    )
    assert employees == [], "a refused create must persist no Employee row"


def test_release_item_representation_omits_updated_at_and_version():
    """PRD §2.4: "Three entities are deliberate exceptions because they are
    append-only evidence rather than mutable records: a **release item**, an
    **acknowledgment event**, and a **retention record** each carry only `id` and
    `created_at`. For those three, both `updated_at` and `version` are absent from the
    response payload entirely."  PRD §3.6: "An item's `supersedes_version_id` stays
    null until the release actually happens".

    Design: Corner/entities/corner_release_item_is_immutable_with_no_version_field
    """
    from test_helpers import add_item, assert_append_only_fields, mint_version, new_document, new_package

    jurisdiction = new_jurisdiction()
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    package = new_package([jurisdiction["id"]], "2026-09-19T00:00:00Z")
    item = add_item(package["id"], version["id"])

    data = validate_success(
        api_client.get_release_item(item["id"], make_admin_headers())
    )
    assert data["release_package_id"] == package["id"]
    assert data["policy_version_id"] == version["id"]
    assert data["supersedes_version_id"] is None
    assert_append_only_fields(data)


def test_unresolvable_path_parent_and_body_foreign_key_use_distinct_error_ids():
    """PRD §2.8: "Every path identifier is resolved **left to right in path order** ...
    failure yields `ERR_RESOURCE_NOT_FOUND` (404). Then every foreign-key identifier
    supplied in the request body is resolved against its referenced entity, with
    failure yielding `ERR_REFERENCED_ENTITY_NOT_FOUND` (404)."

    Design: Corner/entities/corner_parent_and_body_fk_integrity_use_distinct_error_ids
    """
    from test_helpers import create_policy_version_payload, new_document, refresh_document

    jurisdiction = new_jurisdiction()
    document = new_document()

    validate_error(
        api_client.create_policy_version(
            NON_EXISTENT_UUID,
            create_policy_version_payload([jurisdiction["id"]], document["version"]),
            make_author_headers(),
        ),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_employee(
            create_employee_payload(NON_EXISTENT_UUID), make_admin_headers()
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
        404,
    )

    untouched = refresh_document(document["id"])
    assert untouched["latest_version_no"] == 0, (
        "neither refusal may mint anything, got "
        f"{untouched['latest_version_no']}"
    )
    assert untouched["version"] == document["version"]


def test_release_items_form_a_junction_and_employees_self_reference_their_manager():
    """PRD §3.6: "Contents are added one **release item** at a time, each naming a
    `policy_version_id`" ... "items may be listed by `release_package_id`, by
    `policy_version_id`".  PRD §3.1: "`manager_id` is an optional self-referential link
    to another employee and defaults to null for the top of the reporting chain." ...
    "Employee listings may be filtered by `jurisdiction_id`, by `manager_id` — which is
    how a manager finds their direct reports".

    Design: Corner/entities/corner_graph_topology_junction_and_self_reference
    """
    from test_helpers import add_item, mint_version, new_document, new_employee, new_package

    jurisdiction = new_jurisdiction()
    manager = new_employee(jurisdiction["id"])
    first_report = new_employee(jurisdiction["id"], manager_id=manager["id"])
    second_report = new_employee(jurisdiction["id"], manager_id=manager["id"])
    assert manager["manager_id"] is None

    document = new_document()
    v1 = mint_version(document, [jurisdiction["id"]])
    v2 = mint_version(document, [jurisdiction["id"]])
    p1 = new_package([jurisdiction["id"]], "2026-09-19T00:00:00Z")
    p2 = new_package([jurisdiction["id"]], "2026-09-26T00:00:00Z")

    add_item(p1["id"], v1["id"])
    add_item(p1["id"], v2["id"])
    add_item(p2["id"], v1["id"])

    by_package, _ = validate_paginated(
        api_client.list_release_items(
            make_admin_headers(), params={"release_package_id": p1["id"], "limit": 100}
        )
    )
    assert len(by_package) == 2, (
        f"one package may hold two versions, got {len(by_package)} items"
    )
    by_version, _ = validate_paginated(
        api_client.list_release_items(
            make_admin_headers(), params={"policy_version_id": v1["id"], "limit": 100}
        )
    )
    assert len(by_version) == 2, (
        f"one version may sit in two packages, got {len(by_version)} items"
    )

    reports, meta = validate_paginated(
        api_client.list_employees(
            make_admin_headers(), params={"manager_id": manager["id"], "limit": 100}
        )
    )
    assert [row["id"] for row in reports] == [first_report["id"], second_report["id"]], (
        f"the manager filter must return exactly the two direct reports, got {reports}"
    )
    assert meta["total_count"] == 2
