"""Which keys are unique everywhere, which only inside a cycle, and which as pairs."""

from test_helpers import (
    ADMIN_HEADERS,
    ERR_APPLICANT_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_DUPLICATE_ASSOCIATION,
    ERR_DUPLICATE_CODE,
    NON_EXISTENT_UUID,
    add_discipline,
    assign_panelist,
    create_applicant,
    create_application,
    create_housing_unit,
    create_panelist,
    create_studio,
    get_success_data,
    make_applicant_payload,
    make_application_payload,
    make_cycle_payload,
    make_discipline_payload,
    make_housing_unit_payload,
    make_panel_assignment_payload,
    make_panelist_payload,
    make_studio_payload,
    read_cycle,
    refresh_application,
    set_clock,
    setup_draft_cycle,
    setup_open_cycle,
    setup_panel_review_cycle,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-01T00:00:00Z"
SHARED_CODE = "SCULPT"


def _two_draft_cycles(api):
    """Two cycles, each already carrying a discipline under the same code."""
    first = setup_draft_cycle(api, clock=CLOCK, code="CY-2027")
    second = setup_draft_cycle(api, clock=CLOCK, code="CY-2028")
    for cycle in (first, second):
        added = add_discipline(api, cycle, code=SHARED_CODE)
        assert added["code"] == SHARED_CODE
    return first, second


def _rival_discipline(api, cycle_id):
    """A discipline sharing only the code, differing in every configurable rule."""
    return make_discipline_payload(
        cycle_id,
        code=SHARED_CODE,
        name="Sculpture Again",
        portfolio_min_items=2,
        portfolio_max_items=4,
        required_media_types=["VIDEO"],
        cohort_min_slots=1,
        cohort_max_slots=3,
        required_capability_tags=["KILN"],
        required_ventilation_class="NONE",
    )


def test_the_same_discipline_code_is_free_in_a_second_cycle(api):
    """Uniqueness is scoped to the cycle that configures the category.

    PRD: "Each carries a payload containing the `cycle_id` it configures, a `code`
    of 2 to 16 uppercase letters, digits or underscores that must be unique inside
    that cycle (`ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    first, second = _two_draft_cycles(api)

    for cycle in (first, second):
        rows, meta = validate_paginated(
            api.list_disciplines(ADMIN_HEADERS, {"cycle_id": cycle.cycle_id})
        )
        assert meta["total_count"] == 1
        assert [row["code"] for row in rows] == [SHARED_CODE]
    assert first.discipline_id(SHARED_CODE) != second.discipline_id(SHARED_CODE)


def test_the_repeat_inside_one_cycle_is_refused_on_the_code_alone(api):
    """Everything else about the payload differs, and the code still decides.

    PRD: "a `code` of 2 to 16 uppercase letters, digits or underscores that must be
    unique inside that cycle (`ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    first, _second = _two_draft_cycles(api)
    before = read_cycle(api, first.cycle_id)

    validate_error(
        api.create_discipline(_rival_discipline(api, first.cycle_id), ADMIN_HEADERS),
        ERR_DUPLICATE_CODE,
    )

    _rows, meta = validate_paginated(
        api.list_disciplines(ADMIN_HEADERS, {"cycle_id": first.cycle_id})
    )
    assert meta["total_count"] == 1
    assert read_cycle(api, first.cycle_id)["version"] == before["version"]


def test_a_cycle_code_is_unique_across_the_whole_system(api):
    """The cycle's own key has no enclosing scope to be relative to.

    PRD: "a human-readable `code` of 1 to 32 characters that must be unique across
    all cycles (a collision is `ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    first, _second = _two_draft_cycles(api)

    validate_error(
        api.create_cycle(make_cycle_payload(code=first.cycle_code), ADMIN_HEADERS),
        ERR_DUPLICATE_CODE,
    )

    listed, _meta = validate_paginated(
        api.list_cycles(ADMIN_HEADERS, {"limit": 100})
    )
    assert [row["code"] for row in listed].count(first.cycle_code) == 1


def test_the_other_global_keys_collide_the_same_way(api):
    """Artists, reviewers, studios and units are each keyed once for the programme.

    PRD: "a `code` unique across all studios (uppercase letters, digits,
    underscore or hyphen, two to sixteen characters; a repeat is
    `ERR_DUPLICATE_CODE`, HTTP 409)"

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    set_clock(api, CLOCK)
    artist = create_applicant(api)
    reviewer = create_panelist(api)
    studio = create_studio(api)
    unit = create_housing_unit(api)

    validate_error(
        api.create_applicant(
            make_applicant_payload(email=artist.email), ADMIN_HEADERS
        ),
        ERR_DUPLICATE_CODE,
    )
    validate_error(
        api.create_panelist(
            make_panelist_payload(email=reviewer.email), ADMIN_HEADERS
        ),
        ERR_DUPLICATE_CODE,
    )
    validate_error(
        api.create_studio(make_studio_payload(code=studio.code), ADMIN_HEADERS),
        ERR_DUPLICATE_CODE,
    )
    validate_error(
        api.create_housing_unit(
            make_housing_unit_payload(code=unit.code), ADMIN_HEADERS
        ),
        ERR_DUPLICATE_CODE,
    )


def test_the_parent_is_resolved_before_the_key_is_examined(api):
    """An unknown cycle answers 404 even when the code would also have collided.

    PRD: "Foreign-key resolution happens after path resolution and before any
    shape or range validation of the remaining body fields."

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    _first, _second = _two_draft_cycles(api)

    validate_error(
        api.create_discipline(_rival_discipline(api, NON_EXISTENT_UUID), ADMIN_HEADERS),
        ERR_CYCLE_NOT_FOUND,
    )


def test_nothing_partial_survives_the_refused_creation(api):
    """The rejected discipline leaves no row behind under either scope.

    PRD: "Disciplines are immutable once created and can be listed filtered by
    `cycle_id` or by `code`."

    Design: Corner/errors/business_key_uniqueness_is_global_for_some_keys_and_per_cycle_for_others
    """
    first, second = _two_draft_cycles(api)

    validate_error(
        api.create_discipline(_rival_discipline(api, first.cycle_id), ADMIN_HEADERS),
        ERR_DUPLICATE_CODE,
    )

    _rows, meta = validate_paginated(
        api.list_disciplines(ADMIN_HEADERS, {"code": SHARED_CODE, "limit": 100})
    )
    assert meta["total_count"] == 2
    assert read_cycle(api, second.cycle_id)["version"] == second.cycle["version"]


SECOND_DISCIPLINE = {
    "code": "PRINT",
    "name": "Printmaking",
    "required_capability_tags": ["PRINT_PRESS"],
    "required_ventilation_class": "NONE",
}


def _one_artist_two_open_cycles(api):
    """Two competitions running at once, and an artist already entered in the first."""
    first = setup_open_cycle(
        api, clock=CLOCK, code="CY-2027", discipline_specs=[{}, SECOND_DISCIPLINE]
    )
    second = setup_open_cycle(api, clock=CLOCK, code="CY-2028")
    artist = create_applicant(api)
    entered = create_application(api, first, artist)
    assert entered.application["status"] == "DRAFT"
    return first, second, artist, entered


def _enter(api, cycle, applicant_id, discipline_code="SCULPT", **overrides):
    """The intake call as the programme records it, returning the raw response."""
    return api.create_application(
        make_application_payload(
            cycle.cycle_id,
            applicant_id,
            cycle.discipline_id(discipline_code),
            **overrides,
        ),
        ADMIN_HEADERS,
    )


def test_a_second_entry_into_the_same_competition_is_refused(api):
    """One artist, one cycle, one application, whatever the second payload says.

    PRD: "At most one application may exist per cycle-and-applicant pair, and a
    second attempt is `ERR_DUPLICATE_ASSOCIATION` (HTTP 409)."

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    first, _second, artist, _entered = _one_artist_two_open_cycles(api)

    validate_error(
        _enter(
            api,
            first,
            artist.applicant_id,
            requested_session_length_weeks=5,
            project_statement="A second bite",
        ),
        ERR_DUPLICATE_ASSOCIATION,
    )

    _rows, meta = validate_paginated(
        api.list_applications(
            ADMIN_HEADERS,
            {"cycle_id": first.cycle_id, "applicant_id": artist.applicant_id},
        )
    )
    assert meta["total_count"] == 1


def test_the_pair_is_the_key_so_the_other_competition_stays_open(api):
    """The same artist is welcome in a cycle they have not yet entered.

    PRD: "At most one application may exist per cycle-and-applicant pair, and a
    second attempt is `ERR_DUPLICATE_ASSOCIATION` (HTTP 409)."

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    _first, second, artist, entered = _one_artist_two_open_cycles(api)

    elsewhere = get_success_data(_enter(api, second, artist.applicant_id), 201)

    assert elsewhere["cycle_id"] == second.cycle_id
    assert elsewhere["applicant_id"] == artist.applicant_id
    assert elsewhere["id"] != entered.application_id
    _rows, meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"applicant_id": artist.applicant_id})
    )
    assert meta["total_count"] == 2


def test_a_different_artist_in_the_same_competition_is_unaffected(api):
    """The key is the pair, so the cycle itself is not exhausted by one entry.

    PRD: "A new application begins with `status` set to `DRAFT` and `fee_status`
    set to `PENDING`."

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    first, _second, _artist, _entered = _one_artist_two_open_cycles(api)
    rival = create_applicant(api)

    theirs = get_success_data(_enter(api, first, rival.applicant_id), 201)

    assert theirs["status"] == "DRAFT"
    assert theirs["fee_status"] == "PENDING"
    _rows, meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"cycle_id": first.cycle_id})
    )
    assert meta["total_count"] == 2


def test_changing_category_is_an_edit_and_never_a_second_row(api):
    """Moving to the other discipline of the cycle revises the row that exists.

    PRD: "While it is in `DRAFT` or `REVISION_REQUESTED` the artist may revise its
    `discipline_id`, `requested_session_length_weeks`, `project_statement` or
    `fee_waiver_requested`, each advancing the application's `version` by 1"

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    first, _second, artist, entered = _one_artist_two_open_cycles(api)
    printmaking = first.discipline_id("PRINT")

    moved = get_success_data(
        api.update_application(
            entered.application_id, {"discipline_id": printmaking}, ADMIN_HEADERS
        )
    )

    assert moved["discipline_id"] == printmaking
    assert moved["version"] == entered.application["version"] + 1
    validate_error(
        _enter(api, first, artist.applicant_id, discipline_code="PRINT"),
        ERR_DUPLICATE_ASSOCIATION,
    )
    assert refresh_application(api, entered)["discipline_id"] == printmaking


def test_an_unknown_artist_is_reported_before_the_pair_is_examined(api):
    """Existence of the reference settles the answer ahead of the uniqueness rule.

    PRD: "Foreign keys supplied in a request body are resolved by the same rule,
    using the same catalogue of not-found codes, in the order in which this
    document declares the fields of that request."

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    first, _second, _artist, _entered = _one_artist_two_open_cycles(api)

    validate_error(_enter(api, first, NON_EXISTENT_UUID), ERR_APPLICANT_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_applications(ADMIN_HEADERS, {"cycle_id": first.cycle_id})
    )
    assert meta["total_count"] == 1


def _seated_panel(api):
    """Two applications under review and two reviewers available to take them."""
    cycle, apps = setup_panel_review_cycle(api, clock=CLOCK, applicant_count=2)
    reviewers = [create_panelist(api) for _ in range(2)]
    seated = assign_panelist(api, apps[0], reviewers[0])
    assert seated["status"] == "ASSIGNED"
    return cycle, apps, reviewers, seated


def _pair(api, application_id, panelist_id):
    """The pairing call as programme staff records it, returning the raw response."""
    return api.create_panel_assignment(
        make_panel_assignment_payload(application_id, panelist_id), ADMIN_HEADERS
    )


def test_the_reviewer_pairing_is_guarded_by_the_same_code(api):
    """The junction rejects its own repeat exactly as the intake does.

    PRD: "at most one assignment may exist per application-and-panelist pair, a
    second attempt being `ERR_DUPLICATE_ASSOCIATION` (HTTP 409)"

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    _cycle, apps, reviewers, _seated = _seated_panel(api)
    before = refresh_application(api, apps[0])

    validate_error(
        _pair(api, apps[0].application_id, reviewers[0].panelist_id),
        ERR_DUPLICATE_ASSOCIATION,
    )

    held = refresh_application(api, apps[0])
    assert held["assigned_panelist_count"] == 1
    assert held["version"] == before["version"]
    _rows, meta = validate_paginated(
        api.list_panel_assignments(
            ADMIN_HEADERS, {"application_id": apps[0].application_id}
        )
    )
    assert meta["total_count"] == 1


def test_the_two_neighbouring_pairings_are_both_allowed(api):
    """Only the exact pair is taken; each of its halves is free to pair elsewhere.

    PRD: "then recomputes the application's `assigned_panelist_count` (its
    assignments in status `ASSIGNED` or `SCORED`) and the reviewer's
    `assigned_count`, and advances the application's `version` by 1."

    Design: Corner/errors/one_application_per_artist_per_cycle_and_one_review_per_pair
    """
    _cycle, apps, reviewers, seated = _seated_panel(api)

    same_reviewer = get_success_data(
        _pair(api, apps[1].application_id, reviewers[0].panelist_id), 201
    )
    same_application = get_success_data(
        _pair(api, apps[0].application_id, reviewers[1].panelist_id), 201
    )

    assert same_reviewer["id"] != seated["id"]
    assert same_application["id"] != seated["id"]
    assert refresh_application(api, apps[0])["assigned_panelist_count"] == 2
    assert refresh_application(api, apps[1])["assigned_panelist_count"] == 1
    _rows, meta = validate_paginated(
        api.list_panel_assignments(
            ADMIN_HEADERS, {"panelist_id": reviewers[0].panelist_id}
        )
    )
    assert meta["total_count"] == 2
