"""The entity surface of the eleven collections, exercised through their edges.

Creation applies every declared default and discards client-supplied system
fields; required, enum and range rejections keep their own status codes and leave
no row behind; each collection answers a dangling identifier with its own 404
identifier; and parent, self-referential and junction foreign keys are resolvable
in both directions through the filtered list forms.
"""

from test_helpers import (
    DEFAULT_FEATURES,
    LAB_PROVISIONAL,
    PARTICIPATION_REGISTERED,
    SPEC_DRAFT,
    SPEC_RATIFIED,
    SUB_DRAFT,
    UNKNOWN_UUID,
    build_program,
    build_specification,
    feature,
    new_plugfest,
    new_submission,
    ratify_specification,
    read_laboratory,
    read_plugfest,
    read_specification,
    read_submission,
    same_instant,
    set_clock,
    submit_submission,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_FEATURE_DEPENDENCY_CYCLE,
    ERR_FEATURE_SET_NOT_FOUND,
    ERR_DUPLICATE_NAME,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SPECIFICATION_STATE,
    ERR_PLUGFEST_NOT_FOUND,
    ERR_SPECIFICATION_NOT_FOUND,
    ERR_SUBMISSION_NOT_FOUND,
    NOT_FOUND_ERROR_BY_PATH_VARIABLE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_freshly_created,
    assert_states,
    expected_certification_fee,
)
from test_helpers.factories import (
    laboratory_payload,
    member_payload,
    participation_payload,
    submission_payload,
)
from test_helpers.test_users import ADMIN_HEADERS, PUBLIC_HEADERS, make_member_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant every chain below starts from.
PROGRAMME_START = "2026-09-01T00:00:00Z"

#: A single mandatory lighting feature set, the smallest ratifiable graph.
ONE_LIGHTING_MANDATORY = [feature("CORE_ONOFF", "MANDATORY", 20)]


def _minimal_specification_payload(**overrides):
    """Only the three inputs §3.1 declares as required; every optional input is
    absent so the server's own defaults are what the response reports."""
    payload = {
        "version_label": "SHIC-1.0",
        "security_baseline_level": "SB1",
        "effective_date": PROGRAMME_START,
    }
    payload.update(overrides)
    return payload


def _minimal_feature_set_payload(specification_id, feature_code, **overrides):
    """A feature-set create carrying no `security_relevant` and no
    `depends_on_feature_set_id`, so both defaults are observable."""
    payload = {
        "specification_id": specification_id,
        "device_type": "LIGHTING",
        "feature_code": feature_code,
        "obligation": "MANDATORY",
        "test_case_count": 10,
    }
    payload.update(overrides)
    return payload


class TestSpecificationCreationDefaults:
    """A create carrying only the required inputs materialises every default."""

    def test_01_every_defaulted_and_system_field_comes_back_on_the_create(self):
        """Creating a version with only version_label, security_baseline_level and
        effective_date answers 201 with status DRAFT, both demotion stamps null,
        sunset_date and supersedes_specification_id null, min_plugfest_credits 0,
        feature_set_count 0 and version 1.

        PRD (§3.1): "A new version is stored with `status` `DRAFT`,
        `feature_set_count` 0, and both `ratified_at` and `deprecated_at` null."

        Design: Corner/entities/specification_creation_applies_every_declared_default
        """
        set_clock(PROGRAMME_START)

        response = api_client.create_specification(
            _minimal_specification_payload(), ADMIN_HEADERS
        )

        specification = validate_success(response, 201)
        assert_freshly_created(specification, "specification")
        assert_states(
            specification,
            status=SPEC_DRAFT,
            ratified_at=None,
            deprecated_at=None,
            sunset_date=None,
            supersedes_specification_id=None,
            min_plugfest_credits=0,
            feature_set_count=0,
        )
        assert specification["version"] == 1, (
            "a freshly created version starts at version 1, got {!r}".format(
                specification["version"]
            )
        )

    def test_02_the_stored_row_reads_back_with_the_same_values(self):
        """A public read of the new version reports the same identifiers and the
        same status, baseline, effective_date and version the create returned.

        PRD (§2.4): "`id` — a server-minted UUID string. It carries no type prefix
        and no embedded meaning; clients never supply it."

        Design: Corner/entities/specification_creation_applies_every_declared_default
        """
        set_clock(PROGRAMME_START)
        created = validate_success(
            api_client.create_specification(
                _minimal_specification_payload(), ADMIN_HEADERS
            ),
            201,
        )

        fetched = validate_success(
            api_client.get_specification(created["id"], PUBLIC_HEADERS)
        )

        assert_common_fields(fetched, "specification")
        for field in (
            "id",
            "version_label",
            "status",
            "security_baseline_level",
            "effective_date",
            "version",
            "created_at",
            "updated_at",
        ):
            assert fetched[field] == created[field], (
                "the read of {} must report the created value, expected {!r}, "
                "got {!r}".format(field, created[field], fetched[field])
            )


#: Every GET-by-id surface, in the order §2.6 lists its path variables.
_NOT_FOUND_PROBES = [
    ("specification_id", "get_specification"),
    ("feature_set_id", "get_feature_set"),
    ("member_id", "get_member"),
    ("laboratory_id", "get_test_laboratory"),
    ("submission_id", "get_submission"),
    ("test_plan_id", "get_test_plan"),
    ("test_session_id", "get_test_session"),
    ("plugfest_id", "get_plugfest"),
    ("participation_id", "get_participation"),
    ("listing_id", "get_listing"),
    ("case_id", "get_noncompliance_case"),
]


class TestPerCollectionNotFoundIdentifiers:
    """Eleven collections, eleven distinct 404 identifiers."""

    def test_03_each_collection_answers_a_dangling_id_with_its_own_error(self):
        """Against an empty database the same syntactically valid UUID addressed at
        each of the eleven collections returns that collection's own 404
        identifier, and the error envelope carries only error_id and message.

        PRD (§2.6): "The path variables in use are `specification_id`,
        `feature_set_id`, `member_id`, `laboratory_id`, `submission_id`,
        `test_plan_id`, `test_session_id`, `plugfest_id`, `participation_id`,
        `listing_id` and `case_id`, and they map to `ERR_SPECIFICATION_NOT_FOUND`,
        `ERR_FEATURE_SET_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_LABORATORY_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`,
        `ERR_TEST_PLAN_NOT_FOUND`, `ERR_TEST_SESSION_NOT_FOUND`,
        `ERR_PLUGFEST_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
        `ERR_LISTING_NOT_FOUND` and `ERR_CASE_NOT_FOUND` respectively."

        Design: Corner/entities/every_collection_has_its_own_not_found_error_id
        """
        set_clock(PROGRAMME_START)

        seen = []
        for path_variable, method_name in _NOT_FOUND_PROBES:
            expected = NOT_FOUND_ERROR_BY_PATH_VARIABLE[path_variable]
            response = getattr(api_client, method_name)(UNKNOWN_UUID, ADMIN_HEADERS)
            assert response.status_code == 404, (
                "an unstored {} must answer HTTP 404, got {}".format(
                    path_variable, response.status_code
                )
            )
            error = validate_error(response, expected)
            assert "id" not in error, (
                "the error body for {} carries no resource id, got {!r}".format(
                    path_variable, error
                )
            )
            meta = response.json()["meta"]
            assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
                "an error meta block holds only api_request_id and "
                "api_request_timestamp, got {}".format(sorted(meta))
            )
            seen.append(error["error_id"])

        expected_ids = [
            NOT_FOUND_ERROR_BY_PATH_VARIABLE[variable]
            for variable, _ in _NOT_FOUND_PROBES
        ]
        assert seen == expected_ids, (
            "the eleven collections must report eleven distinct identifiers, "
            "expected {}, got {}".format(expected_ids, seen)
        )
        assert len(set(seen)) == 11, (
            "a single shared not-found identifier is wrong, expected 11 distinct "
            "ids, got {}".format(len(set(seen)))
        )


class TestMemberCreationRequiredAndEnumInputs:
    """`tier` is a required input with no default, and its value is checked after
    its presence."""

    def test_04_omitting_tier_is_a_shape_failure_that_stores_nothing(self):
        """A member create carrying only legal_name and contact_email is rejected
        with 400 ERR_INVALID_REQUEST rather than silently defaulting the tier, and
        the collection stays empty.

        PRD (§2.8): "Every field the endpoint declares as required is present and
        of the declared JSON type, and every numeric field lies inside its declared
        range — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/member_creation_missing_required_field_is_rejected
        """
        set_clock(PROGRAMME_START)
        payload = member_payload(legal_name="Acme Devices", contact_email="ops@acme.test")
        payload.pop("tier")

        response = api_client.create_member(payload, ADMIN_HEADERS)

        validate_error(response, ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api_client.list_members(ADMIN_HEADERS, limit=10, offset=0)
        )
        assert meta["total_count"] == 0, (
            "the rejected create must be total, expected total_count 0, got "
            "{}".format(meta["total_count"])
        )
        assert rows == [], (
            "no member row may survive a rejected create, got {} rows".format(len(rows))
        )
        assert meta["has_more"] is False, (
            "an empty collection reports has_more false, got {!r}".format(
                meta["has_more"]
            )
        )

    def test_05_a_tier_outside_the_declared_set_is_an_enum_failure(self):
        """A member create naming the tier PLATINUM is rejected with 422
        ERR_INVALID_ENUM_VALUE — a different status and identifier from the
        shape failure — and again stores nothing.

        PRD (§3.2): "The `ProgramAdmin` registers one with a `legal_name` — the
        registered legal name of the company, between 1 and 120 characters and
        unique across all members, with a repeat rejected as `ERR_DUPLICATE_NAME` —
        a `contact_email` for programme correspondence, and a `tier` of `ADOPTER`,
        `PARTICIPANT` or `PROMOTER`, which drives the certification fee discount
        described later in this section."

        Design: Corner/entities/member_creation_missing_required_field_is_rejected
        """
        set_clock(PROGRAMME_START)

        response = api_client.create_member(
            member_payload(
                legal_name="Acme Devices",
                contact_email="ops@acme.test",
                tier="PLATINUM",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_ENUM_VALUE)
        assert response.status_code == 422, (
            "an enum violation answers HTTP 422 while a shape violation answers "
            "400, got {}".format(response.status_code)
        )
        _, meta = validate_paginated(
            api_client.list_members(ADMIN_HEADERS, limit=10, offset=0)
        )
        assert meta["total_count"] == 0, (
            "the rejected enum value must leave the collection empty, expected "
            "total_count 0, got {}".format(meta["total_count"])
        )


class TestFeatureSetRangeAndEnumInputs:
    """`test_case_count`'s 1..500 range is inclusive at both ends, and an enum
    violation is a different failure from a range violation."""

    def test_06_the_test_case_count_range_is_inclusive_at_both_ends(self):
        """0 and 501 are both rejected with 400 ERR_INVALID_REQUEST while 1 and 500
        are accepted, and the accepted row shows the false `security_relevant`
        default.

        PRD (§3.1): "Each feature set declares a `test_case_count`, at least 1 and
        at most 500, being the number of test cases it contributes to a test plan,
        and a `security_relevant` flag that defaults to false and is set true when
        the feature set covers device attestation, secure boot or firmware update
        behaviour."

        Design: Corner/entities/feature_set_range_and_enum_constraints_are_rejected
        """
        set_clock(PROGRAMME_START)
        specification = validate_success(
            api_client.create_specification(_minimal_specification_payload(), ADMIN_HEADERS),
            201,
        )
        spec_id = specification["id"]

        for feature_code, count in (("BAD_ZERO", 0), ("BAD_HIGH", 501)):
            response = api_client.create_feature_set(
                _minimal_feature_set_payload(spec_id, feature_code, test_case_count=count),
                ADMIN_HEADERS,
            )
            validate_error(response, ERR_INVALID_REQUEST)
            assert response.status_code == 400, (
                "test_case_count {} sits outside the declared range, expected HTTP "
                "400, got {}".format(count, response.status_code)
            )

        low = validate_success(
            api_client.create_feature_set(
                _minimal_feature_set_payload(spec_id, "EDGE_LOW", test_case_count=1),
                ADMIN_HEADERS,
            ),
            201,
        )
        high = validate_success(
            api_client.create_feature_set(
                _minimal_feature_set_payload(
                    spec_id, "EDGE_HIGH", obligation="OPTIONAL", test_case_count=500
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert low["test_case_count"] == 1, (
            "the inclusive lower bound must be accepted, expected test_case_count "
            "1, got {}".format(low["test_case_count"])
        )
        assert high["test_case_count"] == 500, (
            "the inclusive upper bound must be accepted, expected test_case_count "
            "500, got {}".format(high["test_case_count"])
        )
        assert low["security_relevant"] is False, (
            "security_relevant defaults to false when the create omits it, got "
            "{!r}".format(low["security_relevant"])
        )
        assert low["depends_on_feature_set_id"] is None, (
            "a MANDATORY feature set carries no dependency edge, expected null, got "
            "{!r}".format(low["depends_on_feature_set_id"])
        )

    def test_07_an_out_of_enum_obligation_or_device_type_is_a_422(self):
        """An obligation of REQUIRED and a device_type of CAMERA are both rejected
        with 422 ERR_INVALID_ENUM_VALUE, and the parent version counts only the two
        feature sets that survived.

        PRD (§2.8): "Every enum-typed input carries one of that field's declared
        values — otherwise `ERR_INVALID_ENUM_VALUE` (422)."

        Design: Corner/entities/feature_set_range_and_enum_constraints_are_rejected
        """
        set_clock(PROGRAMME_START)
        specification = validate_success(
            api_client.create_specification(_minimal_specification_payload(), ADMIN_HEADERS),
            201,
        )
        spec_id = specification["id"]

        bad_obligation = api_client.create_feature_set(
            _minimal_feature_set_payload(spec_id, "BAD_OBLIG", obligation="REQUIRED"),
            ADMIN_HEADERS,
        )
        bad_device_type = api_client.create_feature_set(
            _minimal_feature_set_payload(spec_id, "BAD_TYPE", device_type="CAMERA"),
            ADMIN_HEADERS,
        )

        validate_error(bad_obligation, ERR_INVALID_ENUM_VALUE)
        assert bad_obligation.status_code == 422, (
            "an obligation outside MANDATORY/OPTIONAL/CONDITIONAL answers HTTP 422, "
            "got {}".format(bad_obligation.status_code)
        )
        validate_error(bad_device_type, ERR_INVALID_ENUM_VALUE)
        assert bad_device_type.status_code == 422, (
            "a device_type outside the five declared classes answers HTTP 422, got "
            "{}".format(bad_device_type.status_code)
        )

        validate_success(
            api_client.create_feature_set(
                _minimal_feature_set_payload(spec_id, "EDGE_LOW", test_case_count=1),
                ADMIN_HEADERS,
            ),
            201,
        )
        validate_success(
            api_client.create_feature_set(
                _minimal_feature_set_payload(
                    spec_id, "EDGE_HIGH", obligation="OPTIONAL", test_case_count=500
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        parent = read_specification(spec_id)
        assert parent["feature_set_count"] == 2, (
            "only the two accepted feature sets increment the version's population, "
            "expected feature_set_count 2, got {}".format(parent["feature_set_count"])
        )


class TestLaboratoryArrayAndRangeInputs:
    """`authorized_device_types` carries array-shape constraints of its own, and
    `bench_capacity` carries a 1..32 range."""

    def test_08_empty_or_duplicate_bearing_arrays_and_out_of_range_capacity_fail(self):
        """An empty `authorized_device_types`, an array repeating one device class,
        and a `bench_capacity` of 0 or 33 are all shape failures answered with 400
        ERR_INVALID_REQUEST.

        PRD (§3.3): "The `authorized_device_types` array must be non-empty, must
        contain no duplicates, and must be a subset of `LIGHTING`, `THERMOSTAT`,
        `LOCK`, `SENSOR` and `HUB`; an empty or duplicate-bearing array is a shape
        failure and yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/laboratory_array_input_rejects_empty_and_duplicated_device_types
        """
        set_clock(PROGRAMME_START)
        rejected = {
            "an empty device-type array": laboratory_payload(
                name="Lab Empty", authorized_device_types=[]
            ),
            "a duplicated device-type element": laboratory_payload(
                name="Lab Dup", authorized_device_types=["LIGHTING", "LIGHTING"]
            ),
            "a bench_capacity below the range": laboratory_payload(
                name="Lab Zero", bench_capacity=0
            ),
            "a bench_capacity above the range": laboratory_payload(
                name="Lab Big", bench_capacity=33
            ),
        }

        for description, payload in rejected.items():
            response = api_client.create_test_laboratory(payload, ADMIN_HEADERS)
            validate_error(response, ERR_INVALID_REQUEST)
            assert response.status_code == 400, (
                "{} is a shape failure, expected HTTP 400, got {}".format(
                    description, response.status_code
                )
            )

    def test_09_the_accepted_registration_keeps_its_array_and_starts_provisional(self):
        """A laboratory registered with the inclusive capacity ceiling and two
        distinct device classes stores both inputs verbatim and starts PROVISIONAL
        with no competency review behind it.

        PRD (§3.3): "A newly registered laboratory sits in `accreditation_status`
        `PROVISIONAL` with `reserved_bench_minutes` 0 and with `competency_score`,
        `competency_variant` and `competency_reviewed_at` all null, because no
        competency review has yet been run against it."

        Design: Corner/entities/laboratory_array_input_rejects_empty_and_duplicated_device_types
        """
        set_clock(PROGRAMME_START)

        laboratory = validate_success(
            api_client.create_test_laboratory(
                laboratory_payload(
                    name="Lab Good",
                    bench_capacity=32,
                    authorized_device_types=["LIGHTING", "HUB"],
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_freshly_created(laboratory, "test laboratory")
        assert laboratory["bench_capacity"] == 32, (
            "32 is the inclusive upper bound of bench_capacity, expected 32, got "
            "{}".format(laboratory["bench_capacity"])
        )
        assert laboratory["authorized_device_types"] == ["LIGHTING", "HUB"], (
            "the submitted device-class array is stored as given, expected "
            "['LIGHTING', 'HUB'], got {!r}".format(laboratory["authorized_device_types"])
        )
        assert_states(
            laboratory,
            accreditation_status=LAB_PROVISIONAL,
            reserved_bench_minutes=0,
            competency_score=None,
            competency_variant=None,
            competency_reviewed_at=None,
        )
        stored = read_laboratory(laboratory["id"])
        assert stored["accreditation_status"] == LAB_PROVISIONAL, (
            "the stored row agrees with the create response, expected {}, got "
            "{}".format(LAB_PROVISIONAL, stored["accreditation_status"])
        )


def _minimal_submission_payload(member_id, specification_id, declared_codes, **overrides):
    """A submission create carrying only the source inputs, with `review_track`
    left out so its default is observable."""
    payload = submission_payload(member_id, specification_id, declared_codes)
    payload.pop("review_track")
    payload.update(overrides)
    return payload


class TestSubmissionCreateIgnoresSystemFieldInput:
    """Only the source inputs of a submission are honoured; state, fee and version
    inputs are discarded."""

    def test_10_supplied_state_fee_and_version_values_are_all_discarded(self):
        """A create that also supplies state, dac_state, certification_fee_cents,
        fee_escrowed_cents and version is accepted, and every one of those five
        values is replaced by the server's own.

        PRD (§3.4): "The **certification fee** is computed once, at creation, and
        pinned onto `certification_fee_cents`; it is never recomputed, so a member
        that later climbs from `PARTICIPANT` to `PROMOTER`, or a specification that
        is later amended, does not move an already-pinned fee."

        Design: Corner/entities/submission_create_system_field_input_ignored
        """
        ctx = build_program(stage="member", features=DEFAULT_FEATURES)

        submission = validate_success(
            api_client.create_submission(
                _minimal_submission_payload(
                    ctx.member_id,
                    ctx.specification_id,
                    ["CORE_ONOFF", "CORE_DIM"],
                    device_model="AL-100",
                    state="CERTIFIED",
                    dac_state="ISSUED",
                    certification_fee_cents=1,
                    fee_escrowed_cents=999999,
                    version=42,
                ),
                make_member_headers(ctx.member_id),
            ),
            201,
        )

        expected_fee = expected_certification_fee(
            "LIGHTING", 2, "SB1", "ADOPTER", "STANDARD"
        )
        assert_cents(
            submission["certification_fee_cents"],
            expected_fee,
            "pinned certification_fee_cents",
        )
        assert submission["certification_fee_cents"] == 150000, (
            "LIGHTING 120000 plus two declared features at 15000 with no SB1 "
            "surcharge, no ADOPTER discount and the STANDARD multiplier, expected "
            "150000, got {}".format(submission["certification_fee_cents"])
        )
        assert_states(
            submission,
            state=SUB_DRAFT,
            dac_state="NOT_ISSUED",
            fee_escrowed_cents=0,
            version=1,
        )

    def test_11_a_clean_create_lands_on_every_declared_initial_value(self):
        """A create carrying only the source inputs starts DRAFT with both review
        axes PENDING, no credential, the STANDARD review-track default, ten null
        outcome fields and three zero counters.

        PRD (§3.4): "A newly created submission sits in `state` `DRAFT` with all
        three review axes at their initial positions — `conformance_review_state`
        `PENDING`, `security_review_state` `PENDING`, `dac_state` `NOT_ISSUED` — and
        with `dac_serial`, `secure_boot_verified`,
        `verified_firmware_update_capability`, `conformance_reviewer_user_id`,
        `security_reviewer_user_id`, `provisional_readiness_score`,
        `final_readiness_score`, `submitted_at`, `review_started_at` and
        `certified_at` all null, and with `revision_round`, `fee_escrowed_cents` and
        `plugfest_credit_count` all 0."

        Design: Corner/entities/submission_create_system_field_input_ignored
        """
        ctx = build_program(stage="member", features=DEFAULT_FEATURES)

        submission = validate_success(
            api_client.create_submission(
                _minimal_submission_payload(
                    ctx.member_id,
                    ctx.specification_id,
                    ["CORE_ONOFF", "CORE_DIM"],
                    device_model="AL-100",
                ),
                make_member_headers(ctx.member_id),
            ),
            201,
        )

        assert_freshly_created(submission, "certification submission")
        assert_states(
            submission,
            state=SUB_DRAFT,
            conformance_review_state="PENDING",
            security_review_state="PENDING",
            dac_state="NOT_ISSUED",
            review_track="STANDARD",
            revision_round=0,
            fee_escrowed_cents=0,
            plugfest_credit_count=0,
        )
        for field in (
            "dac_serial",
            "secure_boot_verified",
            "verified_firmware_update_capability",
            "conformance_reviewer_user_id",
            "security_reviewer_user_id",
            "provisional_readiness_score",
            "final_readiness_score",
            "submitted_at",
            "review_started_at",
            "certified_at",
        ):
            assert submission[field] is None, (
                "{} has no value before the review chain runs, expected null, got "
                "{!r}".format(field, submission[field])
            )
        stored = read_submission(submission["id"])
        assert stored["review_track"] == "STANDARD", (
            "the omitted review_track defaults to STANDARD on the stored row, got "
            "{!r}".format(stored["review_track"])
        )


def _three_submissions_program():
    """One member with three submissions, the third of them already submitted so
    the collection holds two DRAFT rows and one SUBMITTED row."""
    ctx = build_program(
        stage="member", features=[feature("CORE_ONOFF", "MANDATORY", 20)]
    )
    ctx.submission_ids = []
    for device_model in ("AL-100", "AL-200", "AL-300"):
        created = new_submission(
            ctx.member_id,
            ctx.specification_id,
            ["CORE_ONOFF"],
            device_model=device_model,
        )
        ctx.submission_ids.append(created["id"])
    submit_submission(ctx.submission_ids[2], ctx.member_id)
    return ctx


class TestSubmissionListPagesAndFilters:
    """`total_count` is measured over the filtered set and `has_more` over what is
    left beyond the page."""

    def test_12_two_pages_partition_the_collection_and_report_has_more(self):
        """Page one of a two-row window reports three matches with rows remaining,
        page two returns the last row with none remaining, and a limit of 0 is
        rejected outright.

        PRD (§2.3): "The `meta` block of a list response carries `limit` and `offset`
        echoing the effective values used, `total_count` giving the number of rows
        that matched the filters before pagination was applied, and `has_more` set to
        true exactly when rows remain beyond the returned page."

        Design: Corner/entities/submission_list_filters_and_paginates_consistently
        """
        ctx = _three_submissions_program()

        first_response = api_client.list_submissions(ADMIN_HEADERS, limit=2, offset=0)
        second_response = api_client.list_submissions(ADMIN_HEADERS, limit=2, offset=2)
        page_one, meta_one = validate_paginated(first_response)
        page_two, meta_two = validate_paginated(second_response)

        assert first_response.json()["response_type"] == "array", (
            "a list response declares response_type 'array', got {!r}".format(
                first_response.json()["response_type"]
            )
        )
        assert len(page_one) == 2, (
            "a limit of 2 returns at most two rows, expected 2, got {}".format(
                len(page_one)
            )
        )
        assert meta_one["limit"] == 2 and meta_one["offset"] == 0, (
            "meta echoes the effective window, expected limit 2 offset 0, got "
            "limit {} offset {}".format(meta_one["limit"], meta_one["offset"])
        )
        assert meta_one["total_count"] == 3, (
            "three submissions exist, expected total_count 3, got {}".format(
                meta_one["total_count"]
            )
        )
        assert meta_one["has_more"] is True, (
            "one row remains beyond page one, expected has_more true, got "
            "{!r}".format(meta_one["has_more"])
        )

        assert len(page_two) == 1, (
            "the tail page holds the third row alone, expected 1, got {}".format(
                len(page_two)
            )
        )
        assert meta_two["total_count"] == 3, (
            "paging does not move total_count, expected 3, got {}".format(
                meta_two["total_count"]
            )
        )
        assert meta_two["has_more"] is False, (
            "nothing remains beyond page two, expected has_more false, got "
            "{!r}".format(meta_two["has_more"])
        )
        paged_ids = {row["id"] for row in page_one} | {row["id"] for row in page_two}
        assert paged_ids == set(ctx.submission_ids), (
            "the two pages must partition the collection, expected {}, got "
            "{}".format(sorted(ctx.submission_ids), sorted(paged_ids))
        )

        rejected = api_client.list_submissions(ADMIN_HEADERS, limit=0, offset=0)
        validate_error(rejected, ERR_INVALID_REQUEST)
        assert rejected.status_code == 400, (
            "a limit of 0 is below the declared minimum of 1, expected HTTP 400, got "
            "{}".format(rejected.status_code)
        )

    def test_13_a_state_filter_moves_total_count_onto_the_filtered_set(self):
        """Filtering by state DRAFT reports two matches rather than the collection's
        three, and combining state SUBMITTED with the owning member narrows the
        result to the one submitted row.

        PRD (§2.3): "Submissions accept `member_id`, `specification_id`, `state`,
        `dac_state` and `device_type`."

        Design: Corner/entities/submission_list_filters_and_paginates_consistently
        """
        ctx = _three_submissions_program()

        draft_rows, draft_meta = validate_paginated(
            api_client.list_submissions(ADMIN_HEADERS, state=SUB_DRAFT, limit=10, offset=0)
        )
        submitted_rows, submitted_meta = validate_paginated(
            api_client.list_submissions(
                ADMIN_HEADERS,
                state="SUBMITTED",
                member_id=ctx.member_id,
                limit=10,
                offset=0,
            )
        )

        assert draft_meta["total_count"] == 2, (
            "total_count counts only the rows matching state DRAFT, expected 2, got "
            "{}".format(draft_meta["total_count"])
        )
        assert {row["id"] for row in draft_rows} == set(ctx.submission_ids[:2]), (
            "the two untouched submissions are the DRAFT ones, expected {}, got "
            "{}".format(
                sorted(ctx.submission_ids[:2]), sorted(row["id"] for row in draft_rows)
            )
        )
        assert draft_meta["has_more"] is False, (
            "both DRAFT rows fit in a page of 10, expected has_more false, got "
            "{!r}".format(draft_meta["has_more"])
        )

        assert submitted_meta["total_count"] == 1, (
            "one submission has been submitted, expected total_count 1, got "
            "{}".format(submitted_meta["total_count"])
        )
        assert len(submitted_rows) == 1, (
            "the combined filter returns exactly one row, got {}".format(
                len(submitted_rows)
            )
        )
        assert submitted_rows[0]["id"] == ctx.submission_ids[2], (
            "the third submission is the submitted one, expected {}, got {}".format(
                ctx.submission_ids[2], submitted_rows[0]["id"]
            )
        )


class TestFeatureSetParentGate:
    """A feature set's parent must exist first, and only then is its status
    considered."""

    def test_14_an_unstored_parent_is_an_existence_failure_not_a_state_failure(self):
        """A create naming a specification id that was never stored answers 404
        ERR_SPECIFICATION_NOT_FOUND, even though the very same body would draw a
        state conflict against the real ratified parent.

        PRD (§2.6): "Foreign keys supplied inside a request body are resolved with
        the same discipline, and the same HTTP 404 error identifiers, immediately
        after path resolution succeeds."

        Design: Corner/entities/feature_set_parent_must_exist_and_still_be_draft
        """
        set_clock(PROGRAMME_START)
        build_specification(features=ONE_LIGHTING_MANDATORY, ratify=True)

        response = api_client.create_feature_set(
            _minimal_feature_set_payload(UNKNOWN_UUID, "CORE_DIM", test_case_count=10),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_SPECIFICATION_NOT_FOUND)
        assert response.status_code == 404, (
            "body-level reference resolution answers HTTP 404 before any state "
            "check runs, got {}".format(response.status_code)
        )

    def test_15_a_ratified_parent_freezes_its_feature_set_population(self):
        """Adding a feature set to a version that has been ratified is refused with
        409 ERR_INVALID_SPECIFICATION_STATE, and the frozen population is unchanged
        afterwards.

        PRD (§3.1): "Ratification stamps `ratified_at` with the logical clock's
        current instant and freezes the feature-set population permanently: from that
        moment every attempt to add a feature set to the version is refused with
        `ERR_INVALID_SPECIFICATION_STATE`."

        Design: Corner/entities/feature_set_parent_must_exist_and_still_be_draft
        """
        set_clock(PROGRAMME_START)
        ctx = build_specification(features=ONE_LIGHTING_MANDATORY, ratify=True)

        response = api_client.create_feature_set(
            _minimal_feature_set_payload(
                ctx.specification_id, "CORE_DIM", test_case_count=10
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_SPECIFICATION_STATE)
        assert response.status_code == 409, (
            "a parent that exists but is no longer DRAFT is a state conflict, "
            "expected HTTP 409, got {}".format(response.status_code)
        )
        specification = read_specification(ctx.specification_id)
        assert specification["status"] == SPEC_RATIFIED, (
            "the refused create leaves the version ratified, expected {}, got "
            "{}".format(SPEC_RATIFIED, specification["status"])
        )
        assert specification["feature_set_count"] == 1, (
            "the population froze at the single feature set added while DRAFT, "
            "expected 1, got {}".format(specification["feature_set_count"])
        )
        assert same_instant(specification["ratified_at"], PROGRAMME_START), (
            "ratified_at carries the logical clock instant of ratification, "
            "expected {}, got {!r}".format(PROGRAMME_START, specification["ratified_at"])
        )
        rows, meta = validate_paginated(
            api_client.list_feature_sets(
                ADMIN_HEADERS, specification_id=ctx.specification_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 1, (
            "the version still owns exactly one feature set, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )
        assert rows[0]["feature_code"] == "CORE_ONOFF", (
            "the surviving feature set is the one added before ratification, "
            "expected CORE_ONOFF, got {!r}".format(rows[0]["feature_code"])
        )


def _two_draft_specifications():
    """S1 with a LIGHTING and a THERMOSTAT feature set, S2 with a LIGHTING feature
    set of its own, both still DRAFT so edges can be created."""
    set_clock(PROGRAMME_START)
    first = build_specification(
        features=[
            feature("CORE_ONOFF", "MANDATORY", 20),
            feature("SETPOINT", "MANDATORY", 12, device_type="THERMOSTAT"),
        ],
        ratify=False,
    )
    second = build_specification(
        features=[feature("FOREIGN", "MANDATORY", 5)], ratify=False
    )
    return first, second


class TestFeatureDependencyEdgeScope:
    """A dependency edge lives inside one specification-and-device-class graph."""

    def test_16_an_edge_may_not_leave_its_specification_or_its_device_class(self):
        """An edge pointing at another device class of the same version, or at the
        same device class of another version, is rejected with 422
        ERR_FEATURE_DEPENDENCY_CYCLE, while an edge naming nothing stored at all is a
        404 instead.

        PRD (§3.1): "The target must share this row's `specification_id` and its
        `device_type`, and the resulting dependency graph — one graph per
        specification-and-device-class pair — must remain acyclic; a
        cross-specification target, a cross-device-class target, or an edge that would
        close a cycle is rejected with `ERR_FEATURE_DEPENDENCY_CYCLE`."

        Design: Corner/entities/feature_dependency_edges_cannot_leave_their_device_type
        """
        first, second = _two_draft_specifications()
        thermostat_target = first.feature_set_ids["THERMOSTAT:SETPOINT"]
        foreign_target = second.feature_set_ids["LIGHTING:FOREIGN"]

        cross_type = api_client.create_feature_set(
            _minimal_feature_set_payload(
                first.specification_id,
                "CROSS_TYPE",
                obligation="CONDITIONAL",
                test_case_count=6,
                depends_on_feature_set_id=thermostat_target,
            ),
            ADMIN_HEADERS,
        )
        cross_spec = api_client.create_feature_set(
            _minimal_feature_set_payload(
                first.specification_id,
                "CROSS_SPEC",
                obligation="CONDITIONAL",
                test_case_count=6,
                depends_on_feature_set_id=foreign_target,
            ),
            ADMIN_HEADERS,
        )
        unknown_target = api_client.create_feature_set(
            _minimal_feature_set_payload(
                first.specification_id,
                "UNKNOWN_EDGE",
                obligation="CONDITIONAL",
                test_case_count=6,
                depends_on_feature_set_id=UNKNOWN_UUID,
            ),
            ADMIN_HEADERS,
        )

        validate_error(cross_type, ERR_FEATURE_DEPENDENCY_CYCLE)
        assert cross_type.status_code == 422, (
            "a thermostat target for a lighting row leaves the graph, expected HTTP "
            "422, got {}".format(cross_type.status_code)
        )
        validate_error(cross_spec, ERR_FEATURE_DEPENDENCY_CYCLE)
        assert cross_spec.status_code == 422, (
            "a target in another specification leaves the graph, expected HTTP 422, "
            "got {}".format(cross_spec.status_code)
        )
        validate_error(unknown_target, ERR_FEATURE_SET_NOT_FOUND)
        assert unknown_target.status_code == 404, (
            "a target that resolves to nothing is an existence failure, expected "
            "HTTP 404, got {}".format(unknown_target.status_code)
        )

    def test_17_the_edge_is_required_for_conditional_and_forbidden_otherwise(self):
        """A CONDITIONAL feature set with no edge and an OPTIONAL feature set that
        carries one are both 400 ERR_INVALID_REQUEST, while the in-scope CONDITIONAL
        edge is stored and reverse-queryable.

        PRD (§3.1): "That dependency is carried by `depends_on_feature_set_id`, which
        is required when `obligation` is `CONDITIONAL` and must be null when
        `obligation` is `MANDATORY` or `OPTIONAL`."

        Design: Corner/entities/feature_dependency_edges_cannot_leave_their_device_type
        """
        first, _ = _two_draft_specifications()
        lighting_target = first.feature_set_ids["LIGHTING:CORE_ONOFF"]

        missing_edge = api_client.create_feature_set(
            _minimal_feature_set_payload(
                first.specification_id,
                "NO_EDGE",
                obligation="CONDITIONAL",
                test_case_count=6,
            ),
            ADMIN_HEADERS,
        )
        stray_edge = api_client.create_feature_set(
            _minimal_feature_set_payload(
                first.specification_id,
                "STRAY_EDGE",
                obligation="OPTIONAL",
                test_case_count=6,
                depends_on_feature_set_id=lighting_target,
            ),
            ADMIN_HEADERS,
        )

        validate_error(missing_edge, ERR_INVALID_REQUEST)
        assert missing_edge.status_code == 400, (
            "a CONDITIONAL row without its edge is a shape failure, expected HTTP "
            "400, got {}".format(missing_edge.status_code)
        )
        validate_error(stray_edge, ERR_INVALID_REQUEST)
        assert stray_edge.status_code == 400, (
            "an OPTIONAL row must leave the edge null, expected HTTP 400, got "
            "{}".format(stray_edge.status_code)
        )

        conditional = validate_success(
            api_client.create_feature_set(
                _minimal_feature_set_payload(
                    first.specification_id,
                    "GOOD_EDGE",
                    obligation="CONDITIONAL",
                    test_case_count=6,
                    depends_on_feature_set_id=lighting_target,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert conditional["obligation"] == "CONDITIONAL", (
            "the accepted row keeps its obligation, expected CONDITIONAL, got "
            "{!r}".format(conditional["obligation"])
        )
        assert conditional["depends_on_feature_set_id"] == lighting_target, (
            "the in-scope edge is stored as given, expected {}, got {!r}".format(
                lighting_target, conditional["depends_on_feature_set_id"]
            )
        )
        rows, meta = validate_paginated(
            api_client.list_feature_sets(
                ADMIN_HEADERS,
                depends_on_feature_set_id=lighting_target,
                limit=10,
                offset=0,
            )
        )
        assert meta["total_count"] == 1, (
            "only the accepted CONDITIONAL row depends on the lighting feature set, "
            "expected total_count 1, got {}".format(meta["total_count"])
        )
        assert rows[0]["id"] == conditional["id"], (
            "the reverse lookup finds the dependent row, expected {}, got {}".format(
                conditional["id"], rows[0]["id"]
            )
        )


def _plugfest_ready_program():
    """A draft submission of one member plus a plugfest hosted by an authorized
    laboratory whose registration deadline has not passed."""
    ctx = build_program(
        stage="draft",
        features=[feature("CORE_ONOFF", "MANDATORY", 20)],
        declared_codes=["CORE_ONOFF"],
    )
    ctx.plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start="2026-10-05T09:00:00Z",
        window_end="2026-10-05T17:00:00Z",
        registration_deadline="2026-10-01T00:00:00Z",
    )
    ctx.plugfest_id = ctx.plugfest["id"]
    return ctx


class TestParticipationJunctionReferences:
    """The junction carries three foreign keys, each resolvable forward and each
    reverse-reachable."""

    def test_18_each_dangling_reference_reports_its_own_collection(self):
        """A registration naming an unstored plugfest reports
        ERR_PLUGFEST_NOT_FOUND and one naming an unstored submission reports
        ERR_SUBMISSION_NOT_FOUND, so the two body references are never conflated.

        PRD (§2.6): "Foreign keys supplied inside a request body are resolved with
        the same discipline, and the same HTTP 404 error identifiers, immediately
        after path resolution succeeds."

        Design: Corner/entities/participation_junction_joins_plugfest_member_and_submission
        """
        ctx = _plugfest_ready_program()
        member_headers = make_member_headers(ctx.member_id)

        bad_plugfest = api_client.create_participation(
            participation_payload(
                UNKNOWN_UUID, ctx.member_id, ctx.submission_id, device_model="AL-100"
            ),
            member_headers,
        )
        bad_submission = api_client.create_participation(
            participation_payload(
                ctx.plugfest_id, ctx.member_id, UNKNOWN_UUID, device_model="AL-100"
            ),
            member_headers,
        )

        validate_error(bad_plugfest, ERR_PLUGFEST_NOT_FOUND)
        assert bad_plugfest.status_code == 404, (
            "an unstored plugfest_id is an existence failure, expected HTTP 404, got "
            "{}".format(bad_plugfest.status_code)
        )
        validate_error(bad_submission, ERR_SUBMISSION_NOT_FOUND)
        assert bad_submission.status_code == 404, (
            "an unstored submission_id is an existence failure, expected HTTP 404, "
            "got {}".format(bad_submission.status_code)
        )

    def test_19_the_accepted_row_is_reachable_from_all_three_directions(self):
        """The accepted registration starts REGISTERED with no interoperability
        passes and no outcome instant, is found by each of the three foreign-key
        filters, and refreshes the event's distinct vendor count.

        PRD (§3.7): "An accepted registration is stored in `state` `REGISTERED` with
        `interop_pass_count` 0 and `outcome_recorded_at` null, and the event's vendor
        count is recomputed."

        Design: Corner/entities/participation_junction_joins_plugfest_member_and_submission
        """
        ctx = _plugfest_ready_program()

        participation = validate_success(
            api_client.create_participation(
                participation_payload(
                    ctx.plugfest_id,
                    ctx.member_id,
                    ctx.submission_id,
                    device_model="AL-100",
                ),
                make_member_headers(ctx.member_id),
            ),
            201,
        )

        assert_freshly_created(participation, "plugfest participation")
        assert_states(
            participation,
            state=PARTICIPATION_REGISTERED,
            interop_pass_count=0,
            outcome_recorded_at=None,
        )

        for field, value in (
            ("plugfest_id", ctx.plugfest_id),
            ("member_id", ctx.member_id),
            ("submission_id", ctx.submission_id),
        ):
            rows, meta = validate_paginated(
                api_client.list_participations(
                    ADMIN_HEADERS, limit=10, offset=0, **{field: value}
                )
            )
            assert meta["total_count"] == 1, (
                "the {} filter finds the one junction row, expected total_count 1, "
                "got {}".format(field, meta["total_count"])
            )
            assert rows[0]["id"] == participation["id"], (
                "the {} filter must return the registration itself, expected {}, got "
                "{}".format(field, participation["id"], rows[0]["id"])
            )

        plugfest = read_plugfest(ctx.plugfest_id)
        assert plugfest["distinct_vendor_count"] == 1, (
            "one registered member is one distinct vendor, expected 1, got "
            "{}".format(plugfest["distinct_vendor_count"])
        )


class TestSpecificationSupersessionTarget:
    """A version may only replace a target that has already been ratified."""

    def test_20_the_same_body_fails_while_the_target_is_draft_and_passes_after(self):
        """Superseding a DRAFT version is a 409 and superseding an unstored id is a
        404, but once the target is ratified the identical body is accepted and the
        chain is reverse-queryable.

        PRD (§3.1): "A `supersedes_specification_id` names the version this one
        replaces and defaults to null for the first version in a chain; when supplied,
        the named version's `status` must already be `RATIFIED` or `DEPRECATED`,
        because a `DRAFT` version cannot be superseded before it has been ratified,
        and a violation is rejected with `ERR_INVALID_SPECIFICATION_STATE`."

        Design: Corner/entities/specification_supersession_target_must_be_ratified_first
        """
        set_clock(PROGRAMME_START)
        first = build_specification(features=ONE_LIGHTING_MANDATORY, ratify=False)

        successor_body = _minimal_specification_payload(
            version_label="SHIC-NEXT",
            security_baseline_level="SB2",
            effective_date="2026-10-01T00:00:00Z",
            supersedes_specification_id=first.specification_id,
        )
        draft_target = api_client.create_specification(dict(successor_body), ADMIN_HEADERS)
        validate_error(draft_target, ERR_INVALID_SPECIFICATION_STATE)
        assert draft_target.status_code == 409, (
            "a DRAFT target cannot be superseded, expected HTTP 409, got {}".format(
                draft_target.status_code
            )
        )

        # A dangling `supersedes_specification_id` is deliberately NOT asserted
        # here. §2.6 enumerates the nine operations body-level reference
        # resolution "applies to" — feature-set, submission, test-plan,
        # test-session, plugfest, plugfest-participation, listing,
        # noncompliance-case creation and IP-commitment execution — and
        # specification creation is not among them. A faithful reader may
        # therefore either resolve the reference (404) or fall straight through
        # to rung 13's status requirement (409); the PRD does not uniquely
        # determine which, so no expectation is pinned.

        ratify_specification(first.specification_id)
        successor = validate_success(
            api_client.create_specification(
                dict(successor_body, min_plugfest_credits=4), ADMIN_HEADERS
            ),
            201,
        )

        assert successor["supersedes_specification_id"] == first.specification_id, (
            "the accepted successor records its target, expected {}, got {!r}".format(
                first.specification_id, successor["supersedes_specification_id"]
            )
        )
        assert_states(successor, status=SPEC_DRAFT, min_plugfest_credits=4)
        rows, meta = validate_paginated(
            api_client.list_specifications(
                PUBLIC_HEADERS,
                supersedes_specification_id=first.specification_id,
                limit=10,
                offset=0,
            )
        )
        assert meta["total_count"] == 1, (
            "exactly one version replaces the ratified one, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )
        assert rows[0]["id"] == successor["id"], (
            "the reverse filter finds the successor, expected {}, got {}".format(
                successor["id"], rows[0]["id"]
            )
        )
        target = read_specification(first.specification_id)
        assert target["status"] == SPEC_RATIFIED, (
            "being superseded is not itself a transition, expected {}, got {}".format(
                SPEC_RATIFIED, target["status"]
            )
        )

    def test_21_a_sunset_date_at_or_before_the_effective_date_is_rejected(self):
        """A successor whose sunset_date precedes its effective_date is refused with
        422 ERR_INVALID_DATE_RANGE, and a later version reusing an existing
        version_label is refused with 409 ERR_DUPLICATE_NAME.

        PRD (§3.1): "A `sunset_date` records the instant after which the version is
        scheduled for retirement and defaults to null when unscheduled; when supplied
        it must be strictly after `effective_date`, and otherwise the create is
        rejected with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/specification_supersession_target_must_be_ratified_first
        """
        set_clock(PROGRAMME_START)
        first = build_specification(features=ONE_LIGHTING_MANDATORY, ratify=True)

        bad_dates = api_client.create_specification(
            _minimal_specification_payload(
                version_label="SHIC-NEXT",
                security_baseline_level="SB2",
                effective_date="2026-10-01T00:00:00Z",
                sunset_date="2026-09-30T00:00:00Z",
                supersedes_specification_id=first.specification_id,
            ),
            ADMIN_HEADERS,
        )
        validate_error(bad_dates, ERR_INVALID_DATE_RANGE)
        assert bad_dates.status_code == 422, (
            "a sunset_date before the effective_date is a date-range failure, "
            "expected HTTP 422, got {}".format(bad_dates.status_code)
        )

        successor = validate_success(
            api_client.create_specification(
                _minimal_specification_payload(
                    version_label="SHIC-NEXT",
                    security_baseline_level="SB2",
                    effective_date="2026-10-01T00:00:00Z",
                    sunset_date="2027-10-01T00:00:00Z",
                    supersedes_specification_id=first.specification_id,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert same_instant(successor["sunset_date"], "2027-10-01T00:00:00Z"), (
            "a sunset_date strictly after the effective_date is stored, expected "
            "2027-10-01T00:00:00Z, got {!r}".format(successor["sunset_date"])
        )

        duplicate_label = api_client.create_specification(
            _minimal_specification_payload(
                version_label="SHIC-NEXT",
                security_baseline_level="SB3",
                effective_date="2026-11-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        )
        validate_error(duplicate_label, ERR_DUPLICATE_NAME)
        assert duplicate_label.status_code == 409, (
            "version_label is unique across every version ever created, expected "
            "HTTP 409, got {}".format(duplicate_label.status_code)
        )
