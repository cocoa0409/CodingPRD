"""Entity-level corners: envelope shape, stored-row fidelity, listing pages,
required-field and value-domain refusals, lean reference records and the
derived counters a create or a clock move has to produce.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_CANDIDATE_NOT_FOUND,
    ERR_DIRECTOR_NOT_FOUND,
    ERR_DIRECTORSHIP_SUBJECT_INVALID,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_VALUE_OUT_OF_RANGE,
)
from test_helpers.assertions import (
    assert_audit_fields,
    assert_fields_equal,
    assert_lean_record_fields,
    assert_page,
)
from test_helpers.test_users import SECRETARY, STAFF

# The policy cycle year and effective instant used everywhere in this file; a slate
# may only be opened for a cycle at or after the governing policy's own cycle year.
CYCLE_YEAR = 2026
EFFECTIVE_FROM = "2026-01-01T00:00:00Z"

# A policy adoption carrying nothing but the two required inputs: every threshold
# field is optional, so this bare body must still create a row.
BARE_POLICY = {"cycle_year": CYCLE_YEAR, "effective_from": EFFECTIVE_FROM}

# A director create carrying nothing but the four declared source inputs.
BARE_DIRECTOR = {
    "full_name": "Read Back",
    "email": "readback@issuer.example",
    "birth_date": "1970-05-05",
    "appointed_on": "2026-07-01",
}

# Age and tenure at the default logical clock date 2026-08-01: 1975-01-01 lies
# 18840 days back and 18840 // 365 is 51; 2021-01-01 lies 2038 days back and
# 2038 // 365 is 5.
CLOCK_BIRTH_DATE = "1975-01-01"
CLOCK_APPOINTED_ON = "2021-01-01"
AGE_AT_DEFAULT_CLOCK = 51
TENURE_AT_DEFAULT_CLOCK = 5

# After the clock moves to 2027-02-01 the same two dates lie 19024 and 2222 days
# back, so 19024 // 365 is 52 and 2222 // 365 is 6.
MOVED_CLOCK = "2027-02-01T00:00:00Z"
AGE_AFTER_MOVE = 52
TENURE_AFTER_MOVE = 6

# One skill category, registered once and then attacked with a repeat code.
CATEGORY_CODE = "CYBER_RISK"
CATEGORY_NAME = "Cybersecurity Risk Oversight"
CATEGORY_WEIGHT = 0.8
CATEGORY_MIN_DIRECTORS = 2


def _adopt_policy(client):
    """The governing policy, with every threshold stated explicitly in the body."""
    return X.adopt_policy(client, cycle_year=CYCLE_YEAR, effective_from=EFFECTIVE_FROM)


def _meta_of(response):
    """The envelope's `meta` block, for the fields that never reach `data`."""
    return response.json()["meta"]


def test_policy_creation_returns_the_created_row_in_the_success_envelope(client):
    """A policy adopted with only its two required inputs comes back as a full object in
    the success envelope, minted ACTIVE at version 1 with its audit fields populated.

    PRD: "operations that create or modify a resource will return the created or updated resource object in the data field"

    Design: Corner/entities/policy_creation_returns_every_declared_field_in_the_success_envelope
    """
    response = client.adopt_policy(BARE_POLICY, SECRETARY)

    policy = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    meta = _meta_of(response)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]
    assert_fields_equal(policy, {"cycle_year": CYCLE_YEAR, "status": "ACTIVE", "version": 1})
    assert policy["effective_from"] is not None
    assert_audit_fields(policy)


def test_an_adopted_policy_reads_back_with_the_same_identity_and_state(client):
    """The adopted row is the governing policy and a read of it returns the identical
    identifier, cycle year, effective instant, ACTIVE status and untouched version.

    PRD: "every prior policy whose `status` is `ACTIVE` becomes `SUPERSEDED`, and the new row is created `ACTIVE`"

    Design: Corner/entities/policy_creation_returns_every_declared_field_in_the_success_envelope
    """
    created = validate_success(client.adopt_policy(BARE_POLICY, SECRETARY), 201)

    fetched = validate_success(client.get_policy(created["id"], STAFF), 200)

    assert fetched["id"] == created["id"]
    assert_fields_equal(fetched, {"cycle_year": CYCLE_YEAR, "status": "ACTIVE", "version": 1})
    assert fetched["effective_from"] == created["effective_from"]
    assert fetched["created_at"] == created["created_at"]


def test_director_read_returns_the_stored_row_with_its_initial_dimensions(client):
    """A director created from the four declared inputs reads back with those inputs
    unchanged, the three opening state dimensions and version 1.

    PRD: "every created director begins with `compliance_status` `COMPLIANT`, `onboarding_status` `NOT_STARTED`"

    Design: Corner/entities/director_retrieval_returns_the_stored_row
    """
    _adopt_policy(client)
    created = validate_success(client.create_director(BARE_DIRECTOR, SECRETARY), 201)

    response = client.get_director(created["id"], STAFF)

    director = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert director["id"] == created["id"]
    assert_fields_equal(director, BARE_DIRECTOR)
    assert_fields_equal(
        director,
        {
            "service_status": "ONBOARDING",
            "compliance_status": "COMPLIANT",
            "onboarding_status": "NOT_STARTED",
            "onboarding_completion_pct": 0.00,
            "is_independent": True,
            "version": 1,
        },
    )
    assert_audit_fields(director)


def _three_committees(client):
    """Three chartered committees, whose codes sort AUDIT, COMPENSATION, RISK."""
    _adopt_policy(client)
    return [
        X.new_committee(client, code=code, name=name, authorized_seats=3, min_seats=1)
        for code, name in [
            ("AUDIT", "Audit Committee"),
            ("COMPENSATION", "Compensation Committee"),
            ("RISK", "Risk Oversight Committee"),
        ]
    ]


def test_committee_listing_reports_total_count_and_has_more_per_page(client):
    """With three committees stored, a two-row window reports total_count 3 and has_more
    true, and the window starting at offset 2 returns the last row with has_more false.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/committee_listing_paginates_with_total_count_and_has_more
    """
    _three_committees(client)

    first_page, first_meta = assert_page(
        client.list_committees(STAFF, params={"limit": 2, "offset": 0}), expected_total=3
    )
    second_page, second_meta = assert_page(
        client.list_committees(STAFF, params={"limit": 2, "offset": 2}), expected_total=3
    )

    assert len(first_page) == 2
    assert_fields_equal(first_meta, {"limit": 2, "offset": 0, "has_more": True})
    assert [row["code"] for row in first_page] == ["AUDIT", "COMPENSATION"]
    assert len(second_page) == 1
    assert_fields_equal(second_meta, {"limit": 2, "offset": 2, "has_more": False})
    assert [row["code"] for row in second_page] == ["RISK"]
    for row in first_page + second_page:
        assert_fields_equal(row, {"filled_seats": 0, "status": "UNDER_STRENGTH"})


def test_committee_listing_defaults_to_a_limit_of_ten(client):
    """A committee list with no pagination parameters reports the declared default limit
    of 10, so all three rows fit on the first page and has_more is false.

    PRD: "it defaults to 10, may not be below 1, and may not exceed 100"

    Design: Corner/entities/committee_listing_paginates_with_total_count_and_has_more
    """
    _three_committees(client)

    rows, meta = assert_page(client.list_committees(STAFF), expected_total=3)

    assert len(rows) == 3
    assert_fields_equal(meta, {"limit": 10, "offset": 0, "has_more": False})
    assert [row["code"] for row in rows] == ["AUDIT", "COMPENSATION", "RISK"]


def test_unknown_candidate_id_is_refused_with_candidate_not_found(client):
    """A well-formed but unknown candidate identifier produces the 404 bound to the
    candidate type rather than an empty success body.

    PRD: "identifiers are resolved strictly left to right, and the first identifier that does not resolve produces the 404 for that identifier's own type"

    Design: Corner/entities/unknown_candidate_id_returns_candidate_not_found
    """
    _adopt_policy(client)

    response = client.get_candidate(NON_EXISTENT_UUID, STAFF)

    error = validate_error(response, ERR_CANDIDATE_NOT_FOUND, expected_status=404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip()
    rows, _ = assert_page(client.list_candidates(STAFF), expected_total=0)
    assert rows == []


def test_director_create_without_birth_date_is_refused_as_an_invalid_request(client):
    """birth_date is a declared input with no fallback, so a director create that omits it
    is rejected for payload shape and writes no row.

    PRD: "A missing or mistyped required field yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/director_create_missing_birth_date_returns_invalid_request
    """
    _adopt_policy(client)
    payload = {
        "full_name": "No Birthday",
        "email": "nobirthday@issuer.example",
        "appointed_on": "2026-07-01",
    }

    response = client.create_director(payload, SECRETARY)

    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)
    rows, _ = assert_page(client.list_directors(STAFF), expected_total=0)
    assert rows == []


def _clock_director(client):
    """One seated director whose birth and appointment dates key the age arithmetic."""
    _adopt_policy(client)
    return X.new_seated_director(
        client,
        full_name="Clara Clock",
        email="clara@issuer.example",
        birth_date=CLOCK_BIRTH_DATE,
        appointed_on=CLOCK_APPOINTED_ON,
    )


def test_age_and_tenure_are_derived_from_the_logical_clock_date(client):
    """At the default clock the stored birth and appointment dates yield age_years 51 and
    tenure_years 5, and the outside-board and education counters open at zero.

    PRD: "A director's `tenure_years` is the number of days from `appointed_on` to the logical clock's date divided by 365 with the fraction discarded, and their `age_years` is computed the same way from `birth_date`"

    Design: Corner/entities/director_age_and_tenure_are_computed_from_the_logical_clock
    """
    director = _clock_director(client)

    stored = X.get_director(client, director["id"])

    assert_fields_equal(
        stored,
        {
            "age_years": AGE_AT_DEFAULT_CLOCK,
            "tenure_years": TENURE_AT_DEFAULT_CLOCK,
            "external_public_board_count": 0,
            "education_hours_cycle": 0.0,
        },
    )


def test_advancing_the_clock_re_derives_age_and_tenure(client):
    """Moving the clock to 2027-02-01 refreshes the same director to age_years 52 and
    tenure_years 6 while leaving the two input dates exactly as stored.

    PRD: "both are refreshed for every director whenever the logical clock advances"

    Design: Corner/entities/director_age_and_tenure_are_computed_from_the_logical_clock
    """
    director = _clock_director(client)

    moved = validate_success(client.set_clock(F.clock_payload(MOVED_CLOCK), SECRETARY), 200)

    # The accepted instant is echoed back; only the instant itself is fixed by the PRD.
    assert moved["current_utc"].startswith("2027-02-01T00:00:00"), moved["current_utc"]
    assert moved["recomputed_director_count"] == 1
    refreshed = X.get_director(client, director["id"])
    assert_fields_equal(
        refreshed,
        {
            "age_years": AGE_AFTER_MOVE,
            "tenure_years": TENURE_AFTER_MOVE,
            "birth_date": CLOCK_BIRTH_DATE,
            "appointed_on": CLOCK_APPOINTED_ON,
        },
    )


def test_slate_creation_generates_every_system_field_itself(client):
    """A slate opened with only its cycle year and seat count is born DRAFT at version 1
    with every rollup, tally and timestamp set by the server rather than the client.

    PRD: "The slate is born `DRAFT` with `nominee_count`, `independent_nominee_count`, `committed_search_fee_cents`, `revision_count`, `votes_for`, `votes_against`, `votes_abstain` and `votes_recused` all 0, `independent_nominee_pct` and `approval_pct` 0.00, `independence_shortfall`, `contested`, `universal_proxy_applicable` and `quorum_met` all false, `filed_at` and `election_recorded_at` null, and `version` 1."

    Design: Corner/entities/slate_system_fields_are_server_generated_and_not_client_settable
    """
    _adopt_policy(client)

    slate = validate_success(
        client.create_slate({"cycle_year": CYCLE_YEAR, "seat_count": 9}, SECRETARY), 201
    )

    assert_fields_equal(
        slate,
        {
            "status": "DRAFT",
            "version": 1,
            "revision_count": 0,
            "nominee_count": 0,
            "independent_nominee_count": 0,
            "independent_nominee_pct": 0.00,
            "independence_shortfall": False,
            "committed_search_fee_cents": 0,
            "contested": False,
            "universal_proxy_applicable": False,
            "votes_for": 0,
            "votes_against": 0,
            "votes_abstain": 0,
            "votes_recused": 0,
            "approval_pct": 0.00,
            "quorum_met": False,
            "filed_at": None,
            "election_recorded_at": None,
        },
    )
    assert_audit_fields(slate)


def _director_and_category(client):
    """One seated director and one registered skill category to rate them on."""
    _adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Rita Rater",
        email="rita.rater@issuer.example",
        birth_date="1970-01-01",
        appointed_on="2022-01-01",
    )
    category = X.new_skill_category(
        client,
        code=CATEGORY_CODE,
        name=CATEGORY_NAME,
        strategic_weight=CATEGORY_WEIGHT,
        required_min_directors=CATEGORY_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )
    return director, category


def test_a_self_rating_above_five_is_refused_as_out_of_range(client):
    """A self_rating of 6 lies outside the declared 1 through 5 band, so the rating is
    refused for numeric range and no rating row survives the attempt.

    PRD: "skill ratings from 1 through 5 inclusive, interview scores from 1 through 5 inclusive"

    Design: Corner/entities/skill_rating_above_the_declared_maximum_returns_value_out_of_range
    """
    director, category = _director_and_category(client)

    response = client.create_skill_rating(
        director["id"], F.skill_rating_payload(category["id"], self_rating=6), STAFF
    )

    validate_error(response, ERR_VALUE_OUT_OF_RANGE, expected_status=422)
    rows, _ = assert_page(
        client.list_skill_ratings(STAFF, params={"director_id": director["id"]}),
        expected_total=0,
    )
    assert rows == []


def test_a_self_rating_of_exactly_five_is_accepted_and_born_unvalidated(client):
    """The upper bound of the band is inclusive, so a self_rating of 5 is stored, and the
    new rating opens UNVALIDATED with its effective rating equal to the self rating.

    PRD: "Each rating is born with `validation_status` `UNVALIDATED`, `validated_rating` null and `validated_at` null, and its `effective_rating` therefore equals the `self_rating`."

    Design: Corner/entities/skill_rating_above_the_declared_maximum_returns_value_out_of_range
    """
    director, category = _director_and_category(client)

    rating = validate_success(
        client.create_skill_rating(
            director["id"], F.skill_rating_payload(category["id"], self_rating=5), STAFF
        ),
        201,
    )

    assert_fields_equal(
        rating,
        {
            "self_rating": 5,
            "validation_status": "UNVALIDATED",
            "validated_rating": None,
            "validated_at": None,
            "effective_rating": 5,
        },
    )
    assert_audit_fields(rating)
    assert_page(
        client.list_skill_ratings(STAFF, params={"director_id": director["id"]}),
        expected_total=1,
    )


def test_an_unknown_source_channel_is_refused_as_an_invalid_enum_value(client):
    """A source_channel outside the four declared members is refused for enum membership,
    which is a distinct outcome from a missing required field, and no candidate is stored.

    PRD: "Every enum-typed input value is a member of its declared vocabulary, else `ERR_INVALID_ENUM_VALUE` (400)."

    Design: Corner/entities/candidate_unknown_source_channel_returns_invalid_enum_value
    """
    _adopt_policy(client)
    payload = {
        "full_name": "Enum Breaker",
        "email": "enum@cand.example",
        "birth_date": "1974-01-01",
        "source_channel": "HEADHUNTER",
    }

    response = client.create_candidate(payload, STAFF)

    validate_error(response, ERR_INVALID_ENUM_VALUE, expected_status=400)
    rows, _ = assert_page(client.list_candidates(STAFF), expected_total=0)
    assert rows == []


def test_reference_records_carry_no_version_or_updated_at(client):
    """A skill category and an external company expose only the lean common fields, on the
    create response and on the listing alike, unlike the audit-bearing record types.

    PRD: "A `SkillCategory` and an `ExternalCompany` are immutable reference data once created; they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from their representations entirely."

    Design: Corner/entities/skill_category_is_immutable_with_no_version_and_no_update_endpoint
    """
    _adopt_policy(client)

    category = X.new_skill_category(
        client,
        code=CATEGORY_CODE,
        name=CATEGORY_NAME,
        strategic_weight=CATEGORY_WEIGHT,
        required_min_directors=CATEGORY_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )
    company = X.new_external_company(client, name="Outside Holdings", ticker="OUTH")

    assert_lean_record_fields(category)
    assert_lean_record_fields(company)
    listed_categories, _ = assert_page(client.list_skill_categories(STAFF), expected_total=1)
    assert_lean_record_fields(listed_categories[0])


def test_a_repeat_skill_category_code_is_refused_and_the_stored_row_is_untouched(client):
    """Because a category is never edited, a second registration of the same code is a
    duplicate rather than an update, and the originally stored attributes survive intact.

    PRD: "once registered they are never edited, and duplicate `code` values are refused with `ERR_DUPLICATE_RESOURCE`"

    Design: Corner/entities/skill_category_is_immutable_with_no_version_and_no_update_endpoint
    """
    _adopt_policy(client)
    X.new_skill_category(
        client,
        code=CATEGORY_CODE,
        name=CATEGORY_NAME,
        strategic_weight=CATEGORY_WEIGHT,
        required_min_directors=CATEGORY_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )

    response = client.create_skill_category(
        F.skill_category_payload(
            code=CATEGORY_CODE,
            name="Renamed Behind Our Back",
            strategic_weight=0.2,
            required_min_directors=5,
            risk_oversight=False,
            criticality="EMERGING",
        ),
        SECRETARY,
    )

    validate_error(response, ERR_DUPLICATE_RESOURCE, expected_status=409)
    rows, _ = assert_page(client.list_skill_categories(STAFF), expected_total=1)
    assert_fields_equal(
        rows[0],
        {
            "code": CATEGORY_CODE,
            "name": CATEGORY_NAME,
            "strategic_weight": CATEGORY_WEIGHT,
            "required_min_directors": CATEGORY_MIN_DIRECTORS,
            "risk_oversight": True,
            "criticality": "CORE",
        },
    )


def test_onboarding_item_under_an_unknown_director_is_refused_with_director_not_found(client):
    """The parent identifier in the path is resolved before the body is considered, so an
    item posted under an unknown director yields the director 404 and no item is created.

    PRD: "A request for the onboarding items of a director that does not exist yields `ERR_DIRECTOR_NOT_FOUND`, never `ERR_ONBOARDING_ITEM_NOT_FOUND`."

    Design: Corner/entities/onboarding_item_under_an_unknown_director_returns_director_not_found
    """
    _adopt_policy(client)
    real_director = X.new_onboarding_director(
        client,
        full_name="Real Recipient",
        email="real.recipient@issuer.example",
        birth_date="1972-03-03",
        appointed_on="2026-06-01",
    )

    response = client.create_onboarding_item(
        NON_EXISTENT_UUID, F.onboarding_item_payload(module_code="ORIENT_1"), SECRETARY
    )

    validate_error(response, ERR_DIRECTOR_NOT_FOUND, expected_status=404)
    rows, _ = assert_page(
        client.list_director_onboarding_items(real_director["id"], SECRETARY), expected_total=0
    )
    assert rows == []
    assert_fields_equal(
        X.get_director(client, real_director["id"]),
        {"onboarding_status": "NOT_STARTED", "onboarding_completion_pct": 0.00},
    )


def _subjects_and_company(client):
    """One seated director, one candidate and one public outside company."""
    _adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Dora Subject",
        email="dora.subject@issuer.example",
        birth_date="1968-02-02",
        appointed_on="2021-06-01",
    )
    candidate = X.new_candidate(
        client,
        full_name="Cal Subject",
        email="cal.subject@people.example",
        source_channel="SHAREHOLDER_PROPOSAL",
        shareholder_proponent_name="Cedar Ridge Capital",
    )
    company = X.new_external_company(
        client, name="Public Outside Corp", ticker="POUT", is_public=True
    )
    return director, candidate, company


def test_an_external_directorship_naming_both_or_neither_subject_is_refused(client):
    """The seat has exactly one subject, so naming a director and a candidate together is
    refused, naming neither is refused the same way, and no directorship row is written.

    PRD: "Exactly one of `director_id` or `candidate_id` is supplied; supplying both, or neither, yields `ERR_DIRECTORSHIP_SUBJECT_INVALID` (422)."

    Design: Corner/entities/external_directorship_with_both_subjects_returns_subject_invalid
    """
    director, candidate, company = _subjects_and_company(client)

    both = client.create_external_directorship(
        F.external_directorship_payload(
            company["id"], director_id=director["id"], candidate_id=candidate["id"]
        ),
        SECRETARY,
    )
    neither = client.create_external_directorship(
        F.external_directorship_payload(company["id"]), SECRETARY
    )

    validate_error(both, ERR_DIRECTORSHIP_SUBJECT_INVALID, expected_status=422)
    validate_error(neither, ERR_DIRECTORSHIP_SUBJECT_INVALID, expected_status=422)
    rows, _ = assert_page(client.list_external_directorships(SECRETARY), expected_total=0)
    assert rows == []
    assert_fields_equal(
        X.get_director(client, director["id"]),
        {"external_public_board_count": 0, "compliance_status": "COMPLIANT"},
    )


def test_an_external_directorship_with_one_subject_is_recorded_and_counted(client):
    """A seat naming only the director is accepted, is born ACTIVE with no end date, and
    re-derives that director's outside public board count to one.

    PRD: "The subject's `external_public_board_count` is re-derived as the number of their `ACTIVE` directorships whose company has `is_public` true, and their `compliance_status` is recomputed."

    Design: Corner/entities/external_directorship_with_both_subjects_returns_subject_invalid
    """
    director, _candidate, company = _subjects_and_company(client)

    seat = validate_success(
        client.create_external_directorship(
            F.external_directorship_payload(company["id"], director_id=director["id"]),
            SECRETARY,
        ),
        201,
    )

    assert_fields_equal(
        seat,
        {
            "external_company_id": company["id"],
            "director_id": director["id"],
            "status": "ACTIVE",
            "end_on": None,
        },
    )
    assert seat.get("candidate_id") is None, seat.get("candidate_id")
    assert_audit_fields(seat)
    assert_page(
        client.list_external_directorships(
            SECRETARY, params={"external_company_id": company["id"]}
        ),
        expected_total=1,
    )
    # One outside public board plus this board is two, inside the limit the adopted
    # policy states for a director who is not a sitting chief executive.
    assert_fields_equal(
        X.get_director(client, director["id"]),
        {"external_public_board_count": 1, "compliance_status": "COMPLIANT"},
    )
