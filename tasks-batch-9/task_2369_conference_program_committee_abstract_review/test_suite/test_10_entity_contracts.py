"""The shape of the rows this platform mints, and how they are read back.

Setting up a meeting is a chain of freshly minted rows, and each one arrives with
a documented starting shape. A conference is born in draft with every acceptance
counter, cycle counter and blind-label sequence at zero and its continuing-
education pool untouched, and reading it back returns the calendar and the hard
slot capacities exactly as operations staff declared them. A submission category
carries a policy bundle whose review count, dispute threshold and
continuing-education eligibility fall back to declared values when the
administrator stays silent. An abstract is stamped by the server rather than the
client: it takes the next blind label of its conference, advancing that
conference's sequence, and it starts unreviewed with no scores and no decision.
An author record is not the same thing as an event registration, so a fresh
author is unregistered and unsanctioned until registration is recorded, and
clearing that registration erases its instant again. A conflict-of-interest
declaration is the one filing nobody can revise, so it carries no revision
counter at all.

The remaining tests cover the reading side: looking up an abstract that was never
submitted, paging through a conference's submissions, and the rejections that
must leave no row behind — a rubric axis scored out of range, a conference
calendar missing its program freeze, and a submission pointed at a category that
belongs to somebody else's meeting.
"""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    api_client,
    assert_author,
    assert_category,
    assert_cme_pool_conserved,
    assert_conference,
    assert_conflict_declaration,
    assert_two_decimal_places,
    create_abstract_payload,
    create_author,
    create_author_payload,
    create_category,
    create_category_payload,
    create_committee_member_payload,
    create_conference,
    create_conference_payload,
    create_conflict_declaration_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_author_headers,
    make_reviewer_headers,
    member_of,
    register_author_payload,
    set_clock,
    setup_abstract_under_review,
    submit_review_payload,
    transition_conference,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-01-05T00:00:00Z"


def _to_the_second(value: str) -> str:
    """An instant truncated to whole seconds, so a fractional tail cannot mask a
    correct comparison of the instant itself."""
    assert is_iso8601_timestamp(value), f"{value} must be an ISO 8601 timestamp"
    return value[:19]


# ─── A freshly created conference ────────────────────────────────────────


def test_conference_creation_starts_the_meeting_in_draft():
    """Operations staff create it with a public `name` of between 1 and 200 characters and a short `code` of between 2 and 12 uppercase alphanumeric characters — the `code` later prefixes every blind label the conference mints.
    A newly created conference starts in `DRAFT`, with `accepted_oral_count`, `accepted_poster_count`, `accepted_workshop_count`, `waitlisted_count`, `cme_minutes_allocated`, `cfa_extension_count`, `review_reopen_count` and `abstract_sequence` all at zero, and `cme_minutes_available` equal to `cme_minutes_pool_total`.
    Operations that bring a new resource into existence return `201 Created`.

    Design: Corner/entities/conference_creation_returns_draft_status_and_zeroed_ledgers
    """
    set_clock(CLOCK)
    res = api_client.create_conference(create_conference_payload(), ADMIN)
    conference = validate_success(res, 201)

    assert_conference(conference)
    assert conference["status"] == "DRAFT"
    assert conference["name"] == TEST_DEFAULTS["CONFERENCE_NAME"]
    assert conference["code"] == TEST_DEFAULTS["CONFERENCE_CODE"]
    assert conference["version"] == 1


def test_conference_creation_zeroes_every_ledger_and_seeds_the_credit_pool():
    """Capacity is declared up front and is deliberately hard: `oral_slot_capacity`, `poster_slot_capacity` and `workshop_slot_capacity` are each a non-negative integer count of presentation slots the program can physically hold. An optional `cme_minutes_pool_total`, also non-negative and defaulting to 0, records how many accreditable content minutes the accrediting body has granted. A newly created conference starts in `DRAFT`, with `accepted_oral_count`, `accepted_poster_count`, `accepted_workshop_count`, `waitlisted_count`, `cme_minutes_allocated`, `cfa_extension_count`, `review_reopen_count` and `abstract_sequence` all at zero, and `cme_minutes_available` equal to `cme_minutes_pool_total`.

    Design: Corner/entities/conference_creation_returns_draft_status_and_zeroed_ledgers
    """
    set_clock(CLOCK)
    res = api_client.create_conference(
        create_conference_payload(cme_minutes_pool_total=600), ADMIN
    )
    conference = validate_success(res, 201)

    assert conference["accepted_oral_count"] == 0
    assert conference["accepted_poster_count"] == 0
    assert conference["accepted_workshop_count"] == 0
    assert conference["waitlisted_count"] == 0
    assert conference["cfa_extension_count"] == 0
    assert conference["review_reopen_count"] == 0
    assert conference["abstract_sequence"] == 0
    assert conference["cme_minutes_allocated"] == 0
    assert conference["cme_minutes_pool_total"] == 600
    assert conference["cme_minutes_available"] == 600
    assert_cme_pool_conserved(conference)


def test_conference_read_returns_the_declared_calendar_and_capacities():
    """Five instants define the calendar: `event_start_utc` and `event_end_utc` bound the live event, `abstract_deadline_utc` is the submission cut-off, `review_deadline_utc` is the default due date stamped onto new review assignments, and `program_freeze_utc` is the instant after which the running order may only change through an approved change request.
    Capacity is declared up front and is deliberately hard: `oral_slot_capacity`, `poster_slot_capacity` and `workshop_slot_capacity` are each a non-negative integer count of presentation slots the program can physically hold.
    Read operations return `200 OK`.

    Design: Corner/entities/conference_retrieval_returns_the_stored_row_unchanged
    """
    set_clock(CLOCK)
    payload = create_conference_payload(
        oral_slot_capacity=3, poster_slot_capacity=2, workshop_slot_capacity=1
    )
    created = create_conference(**payload)

    res = api_client.get_conference(created["id"], ADMIN)
    conference = validate_success(res)

    assert_conference(conference)
    assert conference["id"] == created["id"]
    assert conference["code"] == payload["code"]
    assert conference["name"] == payload["name"]
    assert conference["status"] == "DRAFT"
    for field in (
        "event_start_utc",
        "event_end_utc",
        "abstract_deadline_utc",
        "review_deadline_utc",
        "program_freeze_utc",
    ):
        assert _to_the_second(conference[field]) == _to_the_second(payload[field]), (
            f"{field} must round-trip unchanged"
        )
    assert conference["oral_slot_capacity"] == 3
    assert conference["poster_slot_capacity"] == 2
    assert conference["workshop_slot_capacity"] == 1
    assert conference["accepted_oral_count"] == 0
    assert conference["waitlisted_count"] == 0


# ─── A freshly declared submission category ──────────────────────────────


def test_category_omitted_policy_inputs_fall_back_to_declared_defaults():
    """A category is declared with a `conference_id`, a `code` of 2 to 16 characters that is unique within the conference, a human-readable `name`, and its policy bundle: `max_word_count` between 100 and 600 caps the declared body length; `requires_structured_body`, a boolean, demands the Background/Methods/Results/Conclusion layout; `allowed_formats` is a non-empty subset of `ORAL`, `POSTER` and `WORKSHOP` and constrains both what authors may request and what the committee may decide; `min_reviews_required`, defaulting to 3 and constrained to between 2 and 5, is how many submitted reviews an abstract needs before it is considered scored; `discrepancy_threshold`, defaulting to 2.50 and constrained to between 0.50 and 4.00 at two decimals, is the score spread at which a dispute is opened; and `cme_eligible`, defaulting to false, decides whether abstracts in the category may carry a continuing-education accreditation.

    Design: Corner/entities/category_omitted_optionals_fall_back_to_declared_defaults
    """
    set_clock(CLOCK)
    conference = create_conference()

    payload = create_category_payload(
        conference["id"], code="GEN", name="General Oncology", max_word_count=300
    )
    for optional in ("min_reviews_required", "discrepancy_threshold", "cme_eligible"):
        payload.pop(optional)

    res = api_client.create_category(payload, ADMIN)
    category = validate_success(res, 201)

    assert_category(category)
    assert category["min_reviews_required"] == 3
    assert_two_decimal_places(category["discrepancy_threshold"])
    assert float(category["discrepancy_threshold"]) == 2.50
    assert category["cme_eligible"] is False
    assert category["allowed_formats"] == ["ORAL", "POSTER"]


# ─── A freshly submitted abstract ────────────────────────────────────────


def test_abstract_blind_code_is_minted_from_the_conference_code_and_sequence():
    """On acceptance of the submission the conference's `abstract_sequence` counter is incremented and the abstract's `blind_code` is minted deterministically as the conference `code`, a hyphen, the letter `B`, and the post-increment sequence value zero-padded to four digits — the first abstract of a conference whose `code` is `NEURO26` therefore carries the blind code `NEURO26-B0001`.
    Every resource in the system carries a server-minted `id`: a UUID string with no type prefix and no embedded semantics. Clients never supply it.

    Design: Corner/entities/abstract_blind_code_and_sequence_are_minted_by_the_server
    """
    set_clock(CLOCK)
    conference = create_conference()
    category = create_category(conference["id"])
    ada = create_author("Ada Rivera", "ada@lab.example", "Northline University")
    ben = create_author("Ben Ohara", "ben@lab.example", "Seaboard Institute")
    transition_conference(conference["id"], "CFA_OPEN")

    first = validate_success(
        api_client.create_abstract(
            create_abstract_payload(
                conference["id"],
                category["id"],
                ada["id"],
                title="Immunotherapy response imaging",
                body_word_count=280,
                requested_format="ORAL",
            ),
            make_author_headers(ada["id"]),
        ),
        201,
    )
    second = validate_success(
        api_client.create_abstract(
            create_abstract_payload(
                conference["id"],
                category["id"],
                ben["id"],
                title="Adjuvant sequencing in early disease",
                body_word_count=260,
                requested_format="POSTER",
            ),
            make_author_headers(ben["id"]),
        ),
        201,
    )

    assert first["blind_code"] == f"{conference['code']}-B0001"
    assert second["blind_code"] == f"{conference['code']}-B0002"

    live = validate_success(api_client.get_conference(conference["id"], ADMIN))
    assert live["abstract_sequence"] == 2


def test_abstract_starts_submitted_with_no_scores_and_no_decision():
    """The new abstract starts with `status` `SUBMITTED`, `embargo_status` `NONE`, `revision_round` zero, `submitted_review_count` zero, and `provisional_score`, `final_score`, `score_spread`, `decision`, `decided_by_member_id`, `embargo_until_utc` and `press_outlet_name` all null, with `decision_downgraded` false.

    Design: Corner/entities/abstract_blind_code_and_sequence_are_minted_by_the_server
    """
    set_clock(CLOCK)
    conference = create_conference()
    category = create_category(conference["id"])
    ada = create_author("Ada Rivera", "ada@lab.example", "Northline University")
    transition_conference(conference["id"], "CFA_OPEN")

    abstract = validate_success(
        api_client.create_abstract(
            create_abstract_payload(
                conference["id"], category["id"], ada["id"], body_word_count=280
            ),
            make_author_headers(ada["id"]),
        ),
        201,
    )

    assert abstract["status"] == "SUBMITTED"
    assert abstract["embargo_status"] == "NONE"
    assert abstract["revision_round"] == 0
    assert abstract["submitted_review_count"] == 0
    assert abstract["provisional_score"] is None
    assert abstract["final_score"] is None
    assert abstract["score_spread"] is None
    assert abstract["decision"] is None
    assert abstract["decided_by_member_id"] is None
    assert abstract["embargo_until_utc"] is None
    assert abstract["press_outlet_name"] is None
    assert abstract["decision_downgraded"] is False


# ─── Author records and event registration ───────────────────────────────


def test_fresh_author_is_unregistered_and_carries_a_clean_sanction_ladder():
    """Creating an author record is not the same as registering for the event: a fresh author has `is_registered` false, `registered_at` null, `no_show_strikes` and `embargo_breach_count` at zero, and `sanction_status` at `NONE`.

    Design: Corner/entities/author_registration_stamps_the_computed_registration_fields
    """
    set_clock(CLOCK)
    res = api_client.create_author(
        create_author_payload(
            full_name="Ada Rivera",
            email="ada@lab.example",
            affiliation="Northline University",
        ),
        ADMIN,
    )
    author = validate_success(res, 201)

    assert_author(author)
    assert author["is_registered"] is False
    assert author["registered_at"] is None
    assert author["no_show_strikes"] == 0
    assert author["embargo_breach_count"] == 0
    assert author["sanction_status"] == "NONE"


def test_author_registration_stamps_the_clock_and_clearing_it_erases_the_stamp():
    """Event registration is recorded separately, by the author or by operations staff, through a boolean `is_registered`; when it becomes true the author's `registered_at` is stamped with the logical-clock instant, and when it is set back to false `registered_at` returns to null.
    Nothing in this system reads wall-clock time.

    Design: Corner/entities/author_registration_stamps_the_computed_registration_fields
    """
    set_clock(CLOCK)
    author = create_author("Ada Rivera", "ada@lab.example", "Northline University")

    registered = validate_success(
        api_client.register_author(
            author["id"],
            register_author_payload(True),
            make_author_headers(author["id"]),
        )
    )
    assert registered["is_registered"] is True
    assert _to_the_second(registered["registered_at"]) == _to_the_second(CLOCK)

    cleared = validate_success(
        api_client.register_author(
            author["id"], register_author_payload(False), ADMIN
        )
    )
    assert cleared["is_registered"] is False
    assert cleared["registered_at"] is None
    assert cleared["sanction_status"] == "NONE"


# ─── The one filing nobody may revise ────────────────────────────────────


def test_conflict_declaration_carries_no_version_and_no_updated_at():
    """`ConflictDeclaration` is the one exception. It is immutable once filed and has no update endpoint, so it carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Its own `declared_at` field records the logical-clock instant of filing.
    The row's `declared_at` is stamped from the logical clock.

    Design: Corner/entities/conflict_declaration_is_immutable_and_carries_no_version
    """
    set_clock(CLOCK)
    conference = create_conference()
    member = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                conference["id"],
                member_role="REVIEWER",
                full_name="Rui Alvarez",
                email="rui@panel.example",
                expertise_keywords=["oncology", "imaging"],
            ),
            ADMIN,
        )
    )

    res = api_client.create_conflict_declaration(
        create_conflict_declaration_payload(
            member["id"],
            conflict_subject_type="AFFILIATION",
            conflict_subject_value="Northline University",
            conflict_type="INSTITUTIONAL",
        ),
        make_reviewer_headers(member["id"]),
    )
    declaration = validate_success(res, 201)

    assert_conflict_declaration(declaration)
    assert "version" not in declaration, "a conflict declaration carries no version"
    assert "updated_at" not in declaration, "a conflict declaration has no updated_at"
    assert _to_the_second(declaration["declared_at"]) == _to_the_second(CLOCK)


def test_conflict_declaration_reads_back_with_the_subject_it_was_filed_against():
    """A declaration names the `member_id`, a `conflict_subject_type` of `AUTHOR_EMAIL`, `AFFILIATION` or `NONE`, a `conflict_type` of `COAUTHOR`, `INSTITUTIONAL`, `FINANCIAL`, `ADVISORY` or `NONE`, and, unless the subject type is `NONE`, a `conflict_subject_value` holding either a lowercase email or an exact affiliation string; when the subject type is `NONE` that value must be null.
    Read operations return `200 OK`.

    Design: Corner/entities/conflict_declaration_is_immutable_and_carries_no_version
    """
    set_clock(CLOCK)
    conference = create_conference()
    member = get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(
                conference["id"],
                member_role="REVIEWER",
                full_name="Rui Alvarez",
                email="rui@panel.example",
                expertise_keywords=["oncology", "imaging"],
            ),
            ADMIN,
        )
    )
    filed = get_success_data(
        api_client.create_conflict_declaration(
            create_conflict_declaration_payload(
                member["id"],
                conflict_subject_type="AFFILIATION",
                conflict_subject_value="Northline University",
                conflict_type="INSTITUTIONAL",
            ),
            make_reviewer_headers(member["id"]),
        )
    )

    res = api_client.get_conflict_declaration(
        filed["id"], make_reviewer_headers(member["id"])
    )
    declaration = validate_success(res)

    assert declaration["id"] == filed["id"]
    assert declaration["member_id"] == member["id"]
    assert declaration["conflict_subject_type"] == "AFFILIATION"
    assert declaration["conflict_subject_value"] == "Northline University"
    assert declaration["conflict_type"] == "INSTITUTIONAL"
    assert "version" not in declaration
    assert "updated_at" not in declaration


# ─── Looking up work that was never submitted ────────────────────────────


def test_unknown_abstract_lookup_reports_the_abstract_not_found_identifier():
    """The 404 vocabulary is per resource type: `ERR_CONFERENCE_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_ABSTRACT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_DISCREPANCY_CASE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ACCREDITATION_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND` and `ERR_CHANGE_REQUEST_NOT_FOUND`.
    Requests are resolved outside-in. When a path contains an identifier, that identifier is checked first, and when a path contains more than one, they are checked strictly left to right; the first identifier that does not resolve decides the 404.

    Design: Corner/entities/unknown_abstract_id_on_get_returns_abstract_not_found
    """
    set_clock(CLOCK)

    res = api_client.get_abstract(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_ABSTRACT_NOT_FOUND")


# ─── Paging through a conference's submissions ───────────────────────────


def _three_submitted_abstracts() -> dict:
    """Clock, conference at CFA_OPEN, one category, one author, three abstracts."""
    set_clock(CLOCK)
    conference = create_conference()
    category = create_category(conference["id"])
    ada = create_author("Ada Rivera", "ada@lab.example", "Northline University")
    transition_conference(conference["id"], "CFA_OPEN")
    abstracts = []
    for title, words, fmt in (
        ("Paper one", 210, "ORAL"),
        ("Paper two", 220, "ORAL"),
        ("Paper three", 230, "POSTER"),
    ):
        abstracts.append(
            get_success_data(
                api_client.create_abstract(
                    create_abstract_payload(
                        conference["id"],
                        category["id"],
                        ada["id"],
                        title=title,
                        body_word_count=words,
                        requested_format=fmt,
                    ),
                    make_author_headers(ada["id"]),
                )
            )
        )
    return {"conference": conference, "author": ada, "abstracts": abstracts}


def test_abstract_listing_first_page_caps_rows_and_counts_the_whole_set():
    """Collection reads are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100. `offset` is the number of rows to skip and defaults to 0; negative values are rejected.
    Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`.

    Design: Corner/entities/abstract_listing_paginates_with_total_count_and_has_more
    """
    state = _three_submitted_abstracts()
    expected = [abstract["id"] for abstract in state["abstracts"]]

    res = api_client.list_abstracts(
        make_author_headers(state["author"]["id"]),
        params={"conference_id": state["conference"]["id"], "limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(res)

    assert len(data) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in data] == expected[:2]


def test_abstract_listing_second_page_returns_the_remainder_with_no_more_rows():
    """Collection reads are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100. `offset` is the number of rows to skip and defaults to 0; negative values are rejected.
    Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`.

    Design: Corner/entities/abstract_listing_paginates_with_total_count_and_has_more
    """
    state = _three_submitted_abstracts()
    expected = [abstract["id"] for abstract in state["abstracts"]]

    res = api_client.list_abstracts(
        ADMIN,
        params={"conference_id": state["conference"]["id"], "limit": 2, "offset": 2},
    )
    data, meta = validate_paginated(res)

    assert len(data) == 1
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in data] == expected[2:]


# ─── Rejections that must leave no row behind ────────────────────────────


def test_rubric_score_above_five_is_rejected_and_writes_nothing():
    """A reviewer submits by supplying four rubric integers between 1 and 5 — `score_originality`, `score_methodology`, `score_relevance` and `score_clarity` — plus a `confidence` of `LOW`, `MEDIUM` or `HIGH`, a `recommended_format` of `ORAL`, `POSTER` or `WORKSHOP` which is advisory only and drives nothing, and optional blinded `comments_to_authors`.
    7. **Schema** — required fields present; correct types; enum members recognized; string lengths, numeric ranges and ISO 8601 datetime syntax valid; unknown fields ignored. Otherwise `ERR_VALIDATION` (400). This band covers rubric scores within 1 to 5, `confidence` being one of `LOW`, `MEDIUM` or `HIGH`, a `duration_minutes` of at least 1, and the pagination bounds of §2.3.
    Later violations are never reported, and no partial write ever survives a rejection.
    A successful assignment creates a review row with `status` `ASSIGNED`, an `assigned_round` frozen to the abstract's current `revision_round`, `is_third_review` false, a computed `expertise_match_score`, and null values for every rubric field, `confidence`, `recommended_format`, `comments_to_authors`, `weighted_score`, `submitted_at` and `decline_reason`. The reviewer's `current_review_load` rises by one. When this is the first non-terminal review of the current round, the abstract moves from `SUBMITTED` to `UNDER_REVIEW`.

    Design: Corner/entities/rubric_score_above_five_is_rejected_by_schema_validation
    """
    world = setup_abstract_under_review()
    abstract = world["abstracts"][0]
    review = world["reviews"][abstract["id"]][0]
    rui = world["members"]["rui"]

    res = api_client.submit_review(
        review["id"],
        submit_review_payload(score_originality=6),
        make_reviewer_headers(rui["id"]),
    )
    validate_error(res, "ERR_VALIDATION")

    stored = validate_success(
        api_client.get_review(review["id"], world["chair_headers"])
    )
    assert stored["status"] == "ASSIGNED"
    assert stored["weighted_score"] is None
    assert stored["score_originality"] is None
    assert stored["submitted_at"] is None

    assert member_of(world, "rui")["current_review_load"] == 1

    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live["submitted_review_count"] == 0
    assert live["status"] == "UNDER_REVIEW"


def test_conference_creation_without_a_program_freeze_instant_is_rejected():
    """Five instants define the calendar: `event_start_utc` and `event_end_utc` bound the live event, `abstract_deadline_utc` is the submission cut-off, `review_deadline_utc` is the default due date stamped onto new review assignments, and `program_freeze_utc` is the instant after which the running order may only change through an approved change request.
    7. **Schema** — required fields present; correct types; enum members recognized; string lengths, numeric ranges and ISO 8601 datetime syntax valid; unknown fields ignored. Otherwise `ERR_VALIDATION` (400).
    Later violations are never reported, and no partial write ever survives a rejection.

    Design: Corner/entities/conference_creation_without_program_freeze_is_rejected
    """
    set_clock(CLOCK)
    payload = create_conference_payload()
    payload.pop("program_freeze_utc")
    payload.pop("cme_minutes_pool_total")

    res = api_client.create_conference(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")

    data, meta = validate_paginated(
        api_client.list_conferences(ADMIN, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, "a rejected creation must persist nothing"
    assert data == []


def test_abstract_naming_a_category_of_another_conference_is_a_mismatch():
    """The named category must belong to the same conference as the `conference_id` in the payload, or the request fails with `ERR_CATEGORY_CONFERENCE_MISMATCH`.
    14. **Referential coherence** — all parties exist and are in legal states but do not belong together, yielding `ERR_CATEGORY_CONFERENCE_MISMATCH`, `ERR_DISCLOSURE_ABSTRACT_MISMATCH`, `ERR_FORMAT_NOT_ALLOWED`, `ERR_SESSION_THEME_MISMATCH`, `ERR_SESSION_FORMAT_MISMATCH`, `ERR_PRESENTER_NOT_ON_ABSTRACT` or `ERR_CATEGORY_NOT_CME_ELIGIBLE` (422).

    Design: Corner/entities/category_belonging_to_another_conference_is_a_mismatch
    """
    set_clock(CLOCK)
    oncology = create_conference()
    create_category(oncology["id"], code="GEN", name="General Oncology")
    haematology = create_conference(
        name="Haematology Days 2026",
        code="HEM26",
        event_start_utc="2026-10-01T08:00:00Z",
        event_end_utc="2026-10-02T18:00:00Z",
        abstract_deadline_utc="2026-04-01T23:59:00Z",
        review_deadline_utc="2026-06-01T23:59:00Z",
        program_freeze_utc="2026-09-15T00:00:00Z",
        oral_slot_capacity=2,
        poster_slot_capacity=2,
        workshop_slot_capacity=0,
        cme_minutes_pool_total=300,
    )
    foreign_category = create_category(
        haematology["id"], code="HEM", name="Haematology"
    )
    ada = create_author("Ada Rivera", "ada@lab.example", "Northline University")
    transition_conference(oncology["id"], "CFA_OPEN")
    transition_conference(haematology["id"], "CFA_OPEN")

    res = api_client.create_abstract(
        create_abstract_payload(
            oncology["id"],
            foreign_category["id"],
            ada["id"],
            body_word_count=280,
            requested_format="ORAL",
        ),
        make_author_headers(ada["id"]),
    )
    validate_error(res, "ERR_CATEGORY_CONFERENCE_MISMATCH")

    _, meta = validate_paginated(
        api_client.list_abstracts(
            ADMIN, params={"conference_id": oncology["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, "a rejected submission must persist nothing"

    live = validate_success(api_client.get_conference(oncology["id"], ADMIN))
    assert live["abstract_sequence"] == 0, "no blind label may be burned by a rejection"
