"""What a freshly written row looks like, and what the server refuses to be told."""

from datetime import datetime

from test_helpers import (
    ADMIN_HEADERS,
    ERR_APPLICANT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_DISBURSEMENT_NOT_FOUND,
    ERR_DISCIPLINE_CYCLE_MISMATCH,
    ERR_DISCIPLINE_NOT_FOUND,
    ERR_HOUSING_UNIT_NOT_FOUND,
    ERR_OBLIGATION_NOT_FOUND,
    ERR_PORTFOLIO_ITEM_NOT_FOUND,
    ERR_RESIDENCY_NOT_FOUND,
    ERR_STUDIO_NOT_FOUND,
    ERR_VALIDATION,
    ERR_VISA_CASE_NOT_FOUND,
    FACILITIES_HEADERS,
    NON_EXISTENT_UUID,
    VENTILATION_RANK,
    add_discipline,
    add_portfolio_item,
    assert_ascending_by_created_at,
    assert_immutable_common_fields,
    assert_money_equals,
    assert_mutable_common_fields,
    create_applicant,
    create_application,
    create_international_applicant,
    create_residency,
    get_success_data,
    ids_of,
    make_application_payload,
    make_cycle_payload,
    make_discipline_payload,
    make_lifecycle_payload,
    make_portfolio_item_payload,
    make_studio_assignment_payload,
    refresh_application,
    setup_draft_cycle,
    setup_open_cycle,
    validate_error,
    validate_paginated,
)

INSTANT_FIELDS = ("open_at", "close_at")


def _instant(value: str) -> datetime:
    """The moment an ISO 8601 UTC string names, independent of its rendering."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ")


CYCLE_INPUTS = {
    "code": "CY-2027",
    "open_at": "2026-08-01T00:00:00Z",
    "close_at": "2026-09-30T00:00:00Z",
    "application_fee_cents": 5000,
    "panel_quorum": 2,
    "cohort_target_size": 10,
    "alumni_reserve_pct": 0.25,
    "stipend_pool_cents": 20000000,
    "slate_min_score": 60.0,
    "stipend_weekly_rate_cents": 70000,
    "session_length_options_weeks": [4, 5, 8, 9],
}


def test_a_new_cycle_stores_every_configuration_value_verbatim(api):
    """All eleven inputs come back unchanged, with the ledger opened alongside.

    PRD: "On creation the cycle's ledger fields are initialised so that
    `stipend_committed_cents` is 0 and `stipend_uncommitted_cents` equals
    `stipend_pool_cents`."

    Design: Corner/entities/cycle_creation_persists_every_declared_input_field
    """
    created = get_success_data(api.create_cycle(dict(CYCLE_INPUTS), ADMIN_HEADERS), 201)

    for field, value in CYCLE_INPUTS.items():
        if field in INSTANT_FIELDS:
            # `open_at` and `close_at` are declared only as "ISO 8601 UTC
            # instants"; the PRD fixes a three-fractional-digit rendering for
            # `created_at`/`updated_at` alone, so the window bounds are
            # compared as instants rather than byte for byte.
            assert _instant(created[field]) == _instant(value), (
                f"{field} was not stored verbatim"
            )
        else:
            assert created[field] == value, f"{field} was not stored verbatim"
    assert_money_equals(created["stipend_committed_cents"], 0, "committed")
    assert_money_equals(created["stipend_uncommitted_cents"], 20000000, "uncommitted")
    assert created["status"] == "DRAFT"
    assert created["slots_filled_count"] == 0
    assert created["slots_open_count"] == 10
    assert created["slate_ready_count"] == 0
    assert created["alumni_reserved_slots"] == 0
    assert created["panel_review_complete"] is False
    assert_mutable_common_fields(created, "cycle")


def test_the_stored_cycle_reads_back_field_for_field(api):
    """The write is immediately visible, and the row has not been mutated since.

    PRD: "`updated_at` is the ISO 8601 UTC instant of the row's most recent
    mutation, in the same format; on a freshly created row it equals
    `created_at`."

    Design: Corner/entities/cycle_creation_persists_every_declared_input_field
    """
    created = get_success_data(api.create_cycle(dict(CYCLE_INPUTS), ADMIN_HEADERS), 201)

    read_back = get_success_data(api.get_cycle(created["id"], ADMIN_HEADERS))

    assert read_back == created
    assert read_back["version"] == 1
    assert read_back["updated_at"] == read_back["created_at"]
    rows, meta = validate_paginated(api.list_cycles(ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [created["id"]]


REQUIRED_CYCLE_INPUTS = [
    "code",
    "open_at",
    "close_at",
    "application_fee_cents",
    "panel_quorum",
    "cohort_target_size",
    "alumni_reserve_pct",
    "stipend_pool_cents",
    "slate_min_score",
    "stipend_weekly_rate_cents",
    "session_length_options_weeks",
]


def test_a_cycle_missing_any_required_input_is_a_shape_error(api):
    """Omitting the quorum — or any other no-default input — is one 400 code.

    PRD: "**Request shape and declared ranges** — required fields present with
    the declared JSON type, enum members recognised, dates well-formed, numeric
    and string ranges respected, pagination bounds respected, then business-key
    uniqueness, then the cross-entity referential check that a named discipline
    belongs to the named cycle."

    Design: Corner/entities/cycle_creation_missing_panel_quorum_rejected
    """
    validate_error(
        api.create_cycle(make_cycle_payload(panel_quorum=None), ADMIN_HEADERS),
        ERR_VALIDATION,
    )
    _rows, meta = validate_paginated(api.list_cycles(ADMIN_HEADERS))
    assert meta["total_count"] == 0

    for field in REQUIRED_CYCLE_INPUTS:
        validate_error(
            api.create_cycle(make_cycle_payload(**{field: None}), ADMIN_HEADERS),
            ERR_VALIDATION,
        )

    _still_empty, after = validate_paginated(api.list_cycles(ADMIN_HEADERS))
    assert after["total_count"] == 0


OUT_OF_RANGE_CYCLE_INPUTS = [
    {"panel_quorum": 1},
    {"cohort_target_size": 0},
    {"alumni_reserve_pct": 1.5},
    {"slate_min_score": 100.01},
    {"application_fee_cents": -1},
    {"session_length_options_weeks": []},
    {"session_length_options_weeks": [3]},
    {"session_length_options_weeks": [17]},
    {"close_at": "2026-07-01T00:00:00Z"},
]


def test_every_range_violation_maps_to_the_same_validation_code(api):
    """A quorum of one and a reserve of 1.5 are shape errors, not business ones.

    PRD: "Any of these ranges being violated is `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/cycle_creation_missing_panel_quorum_rejected
    """
    for override in OUT_OF_RANGE_CYCLE_INPUTS:
        validate_error(
            api.create_cycle(make_cycle_payload(**override), ADMIN_HEADERS),
            ERR_VALIDATION,
        )

    _rows, meta = validate_paginated(api.list_cycles(ADMIN_HEADERS))
    assert meta["total_count"] == 0
    accepted = get_success_data(api.create_cycle(make_cycle_payload(), ADMIN_HEADERS), 201)
    assert accepted["panel_quorum"] == 2


TEXTILE = {
    "code": "TEXTILE",
    "name": "Textile",
    "required_capability_tags": ["CLEAN_ONLY"],
    "cohort_min_slots": 1,
    "cohort_max_slots": 4,
}


def test_a_discipline_takes_the_declared_ventilation_and_hazmat_defaults(api):
    """Two omitted flags are filled in by the server rather than left null.

    PRD: "Facility matching is `required_capability_tags`, a possibly-empty
    subset of `WELDING`, `KILN`, `DARKROOM`, `WET_LAB`, `PRINT_PRESS` and
    `CLEAN_ONLY`, together with `required_ventilation_class`, one of `NONE`,
    `LOCAL` or `FUME_HOOD` and defaulting to `NONE`. Finally,
    `requires_hazmat_review` defaults to false; when true, residents in this
    discipline who declared hazardous materials will additionally owe
    hazardous-material handling training."

    Design: Corner/entities/discipline_optional_fields_take_declared_defaults
    """
    cycle = setup_draft_cycle(api)
    payload = make_discipline_payload(
        cycle.cycle_id,
        required_ventilation_class=None,
        requires_hazmat_review=None,
        **TEXTILE,
    )

    created = get_success_data(api.create_discipline(payload, ADMIN_HEADERS), 201)

    assert created["required_ventilation_class"] == "NONE"
    assert created["requires_hazmat_review"] is False
    assert VENTILATION_RANK[created["required_ventilation_class"]] == 0
    assert created["required_capability_tags"] == ["CLEAN_ONLY"]
    assert created["cycle_id"] == cycle.cycle_id
    assert created["code"] == "TEXTILE"


def test_the_supplied_facility_rules_override_the_defaults_and_stay_frozen(api):
    """The same payload with both values named stores exactly those values.

    PRD: "Two resources are deliberately immutable and therefore carry neither
    counter: a `Discipline` row and a `PortfolioItem` row expose only `id` and
    `created_at`."

    Design: Corner/entities/discipline_optional_fields_take_declared_defaults
    """
    cycle = setup_draft_cycle(api)
    payload = make_discipline_payload(
        cycle.cycle_id,
        required_ventilation_class="FUME_HOOD",
        requires_hazmat_review=True,
        **TEXTILE,
    )

    created = get_success_data(api.create_discipline(payload, ADMIN_HEADERS), 201)

    assert created["required_ventilation_class"] == "FUME_HOOD"
    assert created["requires_hazmat_review"] is True
    assert VENTILATION_RANK[created["required_ventilation_class"]] == 2
    assert_immutable_common_fields(created, "discipline")
    read_back = get_success_data(api.get_discipline(created["id"], ADMIN_HEADERS))
    assert read_back == created


def test_internationality_is_derived_from_the_citizenship_country(api):
    """The host country decides the flag; the treaty flag is a separate input.

    PRD: "The host country is the United States, written `US`; from
    `citizenship_country` the server derives `is_international`, which is true
    exactly when the applicant's citizenship country is anything other than
    `US`."

    Design: Corner/entities/applicant_is_international_computed_and_client_value_ignored
    """
    domestic = create_applicant(api)
    overseas = create_international_applicant(api)

    assert domestic.applicant["citizenship_country"] == "US"
    assert domestic.applicant["is_international"] is False
    assert overseas.applicant["citizenship_country"] == "FR"
    assert overseas.applicant["is_international"] is True
    # The treaty flag is stored as sent and is not inferred from the country.
    assert domestic.applicant["treaty_country"] is False
    assert overseas.applicant["treaty_country"] is True
    assert domestic.applicant["completed_residency_count"] == 0
    assert overseas.applicant["completed_residency_count"] == 0
    assert_mutable_common_fields(overseas.applicant, "applicant")


def test_the_derived_flag_decides_whether_a_visa_case_exists_at_all(api):
    """The flag is load-bearing: one residency is sponsored and the other is not.

    PRD: "The server derives `visa_required` from the artist's
    `is_international` and `tax_form_type` from the same flag — `W9` for a
    domestic artist, `1042S` for an international one — and, when the artist is
    international, opens a visa case in `INITIATED`."

    Design: Corner/entities/applicant_is_international_computed_and_client_value_ignored
    """
    cycle = setup_open_cycle(api)
    sponsored = create_residency(api, cycle, create_international_applicant(api))
    unsponsored = create_residency(api, cycle, create_applicant(api))

    assert sponsored.residency["visa_required"] is True
    assert sponsored.residency["tax_form_type"] == "1042S"
    assert unsponsored.residency["visa_required"] is False
    assert unsponsored.residency["tax_form_type"] == "W9"

    cases, meta = validate_paginated(
        api.list_visa_cases(ADMIN_HEADERS, {"residency_id": sponsored.residency_id})
    )
    assert meta["total_count"] == 1
    assert cases[0]["status"] == "INITIATED"
    assert cases[0]["case_type"] == "B1_SHORT_TERM"
    none_at_all, empty_meta = validate_paginated(
        api.list_visa_cases(ADMIN_HEADERS, {"residency_id": unsponsored.residency_id})
    )
    assert none_at_all == []
    assert empty_meta["total_count"] == 0


def test_the_cycle_system_fields_are_minted_by_the_server(api):
    """The identifier, the timestamps and the counter are all server-owned.

    PRD: "`version` is a positive integer that starts at 1 on creation and
    advances by exactly 1 on every mutation of the row, and it is the value a
    client echoes back when a write requires optimistic concurrency control."

    Design: Corner/entities/cycle_system_fields_are_server_generated_and_client_values_ignored
    """
    created = get_success_data(api.create_cycle(make_cycle_payload(), ADMIN_HEADERS), 201)

    assert_mutable_common_fields(created, "cycle")
    assert created["version"] == 1
    assert created["updated_at"] == created["created_at"]
    assert created["status"] == "DRAFT"
    second = get_success_data(api.create_cycle(make_cycle_payload(), ADMIN_HEADERS), 201)
    assert second["id"] != created["id"]
    assert second["version"] == 1


def test_a_draft_edit_recomputes_both_mirrors_and_advances_the_version(api):
    """A configuration change is honoured, but the system fields stay the server's.

    PRD: "While the cycle is still `DRAFT` its configuration remains editable —
    the same eleven values minus the `code`, each optionally supplied — and every
    such edit recomputes `stipend_uncommitted_cents` and `slots_open_count` and
    advances the cycle's `version` by 1."

    Design: Corner/entities/cycle_system_fields_are_server_generated_and_client_values_ignored
    """
    created = get_success_data(api.create_cycle(dict(CYCLE_INPUTS), ADMIN_HEADERS), 201)

    edited = get_success_data(
        api.update_cycle(
            created["id"],
            {"cohort_target_size": 12, "stipend_pool_cents": 24000000},
            ADMIN_HEADERS,
        )
    )

    assert edited["version"] == created["version"] + 1
    assert edited["created_at"] == created["created_at"]
    assert edited["id"] == created["id"]
    assert edited["cohort_target_size"] == 12
    assert_money_equals(edited["stipend_pool_cents"], 24000000, "pool")
    assert_money_equals(edited["stipend_uncommitted_cents"], 24000000, "uncommitted")
    assert_money_equals(edited["stipend_committed_cents"], 0, "committed")
    assert edited["slots_open_count"] == 12
    assert edited["code"] == CYCLE_INPUTS["code"]


def test_each_entity_answers_a_missing_row_with_its_own_not_found_code(api):
    """Eight reads of the same unknown identifier give eight different codes.

    PRD: "Reading, updating or acting on a row that does not exist is that row's
    own not-found error with HTTP 404: `ERR_CYCLE_NOT_FOUND`,
    `ERR_DISCIPLINE_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_PORTFOLIO_ITEM_NOT_FOUND`,
    `ERR_PANELIST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_RESIDENCY_NOT_FOUND`, `ERR_STUDIO_NOT_FOUND`,
    `ERR_STUDIO_ASSIGNMENT_NOT_FOUND`, `ERR_HOUSING_UNIT_NOT_FOUND`,
    `ERR_HOUSING_ASSIGNMENT_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
    `ERR_OBLIGATION_NOT_FOUND` and `ERR_VISA_CASE_NOT_FOUND`."

    Design: Corner/entities/get_residency_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_residency(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_RESIDENCY_NOT_FOUND
    )
    validate_error(api.get_cycle(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_CYCLE_NOT_FOUND)
    validate_error(
        api.get_discipline(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_DISCIPLINE_NOT_FOUND
    )
    validate_error(
        api.get_applicant(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_APPLICANT_NOT_FOUND
    )
    validate_error(
        api.get_application(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_APPLICATION_NOT_FOUND
    )
    validate_error(
        api.get_studio(NON_EXISTENT_UUID, FACILITIES_HEADERS), ERR_STUDIO_NOT_FOUND
    )
    validate_error(
        api.get_housing_unit(NON_EXISTENT_UUID, ADMIN_HEADERS),
        ERR_HOUSING_UNIT_NOT_FOUND,
    )
    validate_error(
        api.get_visa_case(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_VISA_CASE_NOT_FOUND
    )
    validate_error(
        api.get_disbursement(NON_EXISTENT_UUID, ADMIN_HEADERS),
        ERR_DISBURSEMENT_NOT_FOUND,
    )
    validate_error(
        api.get_obligation(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_OBLIGATION_NOT_FOUND
    )


def test_existence_outranks_state_and_an_unmatched_filter_is_not_a_missing_row(api):
    """A write against a phantom parent is a 404; a filter that matches nothing is not.

    PRD: "Foreign keys supplied in a request body are resolved by the same rule,
    using the same catalogue of not-found codes, in the order in which this
    document declares the fields of that request."

    Design: Corner/entities/get_residency_with_unknown_id_returns_not_found
    """
    validate_error(
        api.residency_lifecycle(
            NON_EXISTENT_UUID, make_lifecycle_payload("CHECK_IN"), ADMIN_HEADERS
        ),
        ERR_RESIDENCY_NOT_FOUND,
    )
    validate_error(
        api.create_studio_assignment(
            make_studio_assignment_payload(
                NON_EXISTENT_UUID, "2026-11-02", "2026-11-10", 1
            ),
            FACILITIES_HEADERS,
        ),
        ERR_RESIDENCY_NOT_FOUND,
    )

    rows, meta = validate_paginated(
        api.list_residencies(ADMIN_HEADERS, {"cycle_id": NON_EXISTENT_UUID})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def _draft_application(api):
    """An unsubmitted application, so its work samples can still be edited."""
    cycle = setup_open_cycle(api)
    applicant = create_applicant(api)
    app = create_application(api, cycle, applicant, fee_waiver_requested=True)
    assert app.application["status"] == "DRAFT"
    assert app.application["portfolio_item_count"] == 0
    assert app.application["portfolio_media_types"] == []
    assert app.application["hazardous_materials_declared"] is False
    return app


def test_attaching_a_work_sample_moves_the_parent_and_carries_no_version(api):
    """The sample itself is bare; the three derived fields live on the parent.

    PRD: "Both attaching and removing an item recompute three derived fields on
    the parent application and advance the application's `version` by 1:
    `portfolio_item_count`, the number of items currently attached;
    `portfolio_media_types`, the distinct media types present sorted in ascending
    order; and `hazardous_materials_declared`, true when any attached item
    declares hazardous materials."

    Design: Corner/entities/portfolio_item_is_immutable_with_no_version_and_no_update_endpoint
    """
    app = _draft_application(api)
    before = app.application

    item = get_success_data(
        api.create_portfolio_item(
            make_portfolio_item_payload(
                app.application_id,
                title="Plate I",
                media_type="IMAGE",
                file_size_mb=12.5,
                hazardous_materials_declared=None,
            ),
            app.applicant.headers,
        ),
        201,
    )

    assert item["application_id"] == app.application_id
    assert item["title"] == "Plate I"
    assert item["media_type"] == "IMAGE"
    assert item["hazardous_materials_declared"] is False
    assert_immutable_common_fields(item, "portfolio item")
    parent = refresh_application(api, app)
    assert parent["portfolio_item_count"] == 1
    assert parent["portfolio_media_types"] == ["IMAGE"]
    assert parent["hazardous_materials_declared"] is False
    assert parent["version"] == before["version"] + 1


def test_removing_the_sample_reverses_the_derived_fields_and_is_not_idempotent(api):
    """The only mutation a sample supports is its own removal, and only once.

    PRD: "Work samples are immutable — there is no edit — but they can be removed
    from an application that has not yet been submitted, and that removal returns
    no body."

    Design: Corner/entities/portfolio_item_is_immutable_with_no_version_and_no_update_endpoint
    """
    app = _draft_application(api)
    baseline = app.application["version"]
    item = add_portfolio_item(api, app)
    assert refresh_application(api, app)["portfolio_item_count"] == 1

    removed = api.delete_portfolio_item(item["id"], app.applicant.headers)

    assert removed.status_code == 204
    emptied = refresh_application(api, app)
    assert emptied["portfolio_item_count"] == 0
    assert emptied["portfolio_media_types"] == []
    assert emptied["version"] == baseline + 2
    validate_error(
        api.delete_portfolio_item(item["id"], app.applicant.headers),
        ERR_PORTFOLIO_ITEM_NOT_FOUND,
    )
    rows, meta = validate_paginated(
        api.list_portfolio_items(
            app.applicant.headers, {"application_id": app.application_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


PRINT_SPEC = {
    "code": "PRINT",
    "name": "Printmaking",
    "required_capability_tags": ["PRINT_PRESS"],
    "required_ventilation_class": "NONE",
    "cohort_min_slots": 1,
    "cohort_max_slots": 4,
}


def _three_applications(api):
    """Three drafts in one cycle: two in sculpture and one in printmaking."""
    cycle = setup_open_cycle(api, discipline_specs=[{}, PRINT_SPEC])
    first = create_application(api, cycle, create_applicant(api))
    second = create_application(api, cycle, create_applicant(api))
    third = create_application(
        api, cycle, create_applicant(api), "PRINT", requested_session_length_weeks=4
    )
    return cycle, [first, second, third]


def test_the_unfiltered_page_reports_the_whole_population(api):
    """Three rows fit inside the default window, so the page is the population.

    PRD: "List responses populate four fields in the `meta` object: the effective
    `limit`, the effective `offset`, `total_count` (the number of rows matching
    the filter before the page window is applied) and `has_more` (true when rows
    matching the filter remain beyond the current page)."

    Design: Corner/entities/applications_list_paginates_with_total_count_and_has_more
    """
    _cycle, apps = _three_applications(api)

    rows, meta = validate_paginated(api.list_applications(ADMIN_HEADERS))

    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3
    assert ids_of(rows) == [app.application_id for app in apps]
    assert_ascending_by_created_at(rows)


def test_the_last_page_reports_no_more_even_when_the_limit_is_not_exhausted(api):
    """Two windows of two cover three rows, and the second is short but final.

    PRD: "Unless a resource says otherwise, list results are ordered by
    `created_at` ascending, with the row's `id` breaking ties so that paging is
    deterministic."

    Design: Corner/entities/applications_list_paginates_with_total_count_and_has_more
    """
    _cycle, apps = _three_applications(api)

    head, head_meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert head_meta["limit"] == 2
    assert head_meta["offset"] == 0
    assert head_meta["total_count"] == 3
    assert head_meta["has_more"] is True
    assert ids_of(head) == [apps[0].application_id, apps[1].application_id]

    tail, tail_meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(tail) == 1
    assert tail_meta["has_more"] is False
    assert tail_meta["total_count"] == 3
    assert ids_of(tail) == [apps[2].application_id]

    past_the_end, empty_meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"limit": 2, "offset": 99})
    )
    assert past_the_end == []
    assert empty_meta["total_count"] == 3
    assert empty_meta["has_more"] is False


def test_filters_narrow_the_total_count_and_compose_conjunctively(api):
    """The census is taken over the filtered set, not over the table.

    PRD: "Filters offered by a list endpoint narrow `total_count` as well as the
    returned page. All filters combine conjunctively: a request carrying two
    filters matches only the rows satisfying both."

    Design: Corner/entities/applications_list_paginates_with_total_count_and_has_more
    """
    cycle, apps = _three_applications(api)
    print_id = cycle.discipline_id("PRINT")

    only_print, print_meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"discipline_id": print_id})
    )
    assert print_meta["total_count"] == 1
    assert ids_of(only_print) == [apps[2].application_id]

    submitted, submitted_meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"status": "SUBMITTED"})
    )
    assert submitted == []
    assert submitted_meta["total_count"] == 0

    both, both_meta = validate_paginated(
        api.list_applications(
            ADMIN_HEADERS,
            {
                "cycle_id": cycle.cycle_id,
                "discipline_id": cycle.discipline_id("SCULPT"),
                "limit": 1,
            },
        )
    )
    assert both_meta["total_count"] == 2
    assert both_meta["has_more"] is True
    assert ids_of(both) == [apps[0].application_id]


def _two_cycles(api):
    """Two cycles, each carrying its own sculpture discipline under the same code."""
    open_cycle_ctx = setup_open_cycle(api)
    other = setup_draft_cycle(api)
    add_discipline(api, other)
    assert other.discipline_id("SCULPT") != open_cycle_ctx.discipline_id("SCULPT")
    return open_cycle_ctx, other


def test_a_discipline_from_another_cycle_is_a_referential_mismatch(api):
    """Both references resolve; it is the relationship between them that fails.

    PRD: "The discipline named must belong to the cycle named: a discipline
    configured under a different cycle is `ERR_DISCIPLINE_CYCLE_MISMATCH` (HTTP
    422)."

    Design: Corner/entities/application_naming_a_discipline_from_another_cycle_rejected
    """
    host, other = _two_cycles(api)
    applicant = create_applicant(api)

    validate_error(
        api.create_application(
            make_application_payload(
                host.cycle_id, applicant.applicant_id, other.discipline_id("SCULPT")
            ),
            ADMIN_HEADERS,
        ),
        ERR_DISCIPLINE_CYCLE_MISMATCH,
    )

    _rows, meta = validate_paginated(api.list_applications(ADMIN_HEADERS))
    assert meta["total_count"] == 0
    accepted = get_success_data(
        api.create_application(
            make_application_payload(
                host.cycle_id, applicant.applicant_id, host.discipline_id("SCULPT")
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    # An application carries the `discipline_id` it named; `discipline_code` is
    # a residency field, so the accepted row is checked by reference.
    assert accepted["discipline_id"] == host.discipline_id("SCULPT")
    assert accepted["status"] == "DRAFT"
    assert accepted["fee_status"] == "PENDING"


def test_absence_outranks_the_cross_reference_check_in_declaration_order(api):
    """With two bad references the earlier declared field decides the answer.

    PRD: "Creating a discipline, an application, a portfolio item, a panel
    assignment, a residency, a studio assignment, a housing assignment or a visa
    case therefore fails on the *first* unresolvable reference in declaration
    order, not on some arbitrary one."

    Design: Corner/entities/application_naming_a_discipline_from_another_cycle_rejected
    """
    host, _other = _two_cycles(api)
    applicant = create_applicant(api)

    validate_error(
        api.create_application(
            make_application_payload(
                host.cycle_id, applicant.applicant_id, NON_EXISTENT_UUID
            ),
            ADMIN_HEADERS,
        ),
        ERR_DISCIPLINE_NOT_FOUND,
    )
    validate_error(
        api.create_application(
            make_application_payload(
                host.cycle_id, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            ADMIN_HEADERS,
        ),
        ERR_APPLICANT_NOT_FOUND,
    )
    validate_error(
        api.create_application(
            make_application_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            ADMIN_HEADERS,
        ),
        ERR_CYCLE_NOT_FOUND,
    )

    _rows, meta = validate_paginated(api.list_applications(ADMIN_HEADERS))
    assert meta["total_count"] == 0
