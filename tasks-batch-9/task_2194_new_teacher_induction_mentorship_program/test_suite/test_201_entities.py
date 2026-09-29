"""Entity surface: creation defaults, server-minted audit stamps, retrieval,
filtered listing and the referential shape of the flat entity graph.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NOVICE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_immutable_system_fields,
    assert_instant_equals,
    assert_system_fields,
    assert_two_decimals,
    ids_of,
)
from test_helpers.constants import CLOCK_INITIAL_UTC
from test_helpers.fixtures import (
    activate_match,
    create_certified_mentor,
    create_cohort,
    create_mentor,
    create_novice,
    create_site,
    post_certify_training,
    propose_match,
    read_cohort,
    read_mentor,
    read_novice,
    read_site,
    set_clock,
    submit_contact_log,
)
from test_helpers.test_users import ADMIN


class TestSiteCreation:
    """The site row a client gets back on creation."""

    def test_create_site_returns_envelope_and_system_defaults(
        self, api: InductionApiClient
    ):
        """A brand-new site is OPEN, holds no matches and starts at version 1.

        The PRD fixes the opening state of a site: "A site begins life with
        `status` `OPEN` and an `active_match_count` of 0. It also carries a
        `mentor_slot_cap`, the ceiling on how many mentoring relationships may be
        simultaneously live across all mentors of that site; the cap defaults to 6
        when the request omits it and must be at least 1 and no more than 40."

        Design: Corner/entities/create_site_returns_envelope_and_system_defaults
        """
        response = api.create_site(f.site_payload(), ADMIN)
        site = validate_success(response, 201)

        envelope = response.json()
        assert envelope["response_type"] == "object", (
            f"a single-row read is an object envelope, got {envelope['response_type']}"
        )
        assert envelope["meta"].get("api_request_id"), (
            "every response carries a meta.api_request_id"
        )
        assert envelope["meta"].get("api_request_timestamp"), (
            "every response carries a meta.api_request_timestamp"
        )

        assert_system_fields(site, expected_version=1)
        assert site["status"] == "OPEN", f"a new site is OPEN, got {site['status']}"
        assert site["active_match_count"] == 0, (
            f"a new site holds no live matches, got {site['active_match_count']}"
        )
        assert site["closed_at"] is None, (
            f"a new site has no closure instant, got {site['closed_at']}"
        )
        assert site["mentor_slot_cap"] == 6, (
            f"the requested cap of 6 is stored, got {site['mentor_slot_cap']}"
        )


class TestMentorReads:
    """Retrieval and listing of the mentor collection."""

    def test_retrieve_mentor_returns_stored_and_derived_fields(
        self, api: InductionApiClient
    ):
        """The three training posts total 18.00 hours while the mentor stays UNCERTIFIED.

        The PRD lists what registration stores and what it initialises: "The
        mentor's own capacity is set by `caseload_cap`, the maximum number of
        simultaneously `ACTIVE` mentoring relationships they may hold; it defaults
        to 2 when omitted and must be between 1 and 4 inclusive. Registration
        initialises `certification_status` to `UNCERTIFIED`,
        `certification_expires_on` and `suspension_reason` to null, and every
        counter — `active_caseload_count`, `training_hours_current_cycle`,
        `stipend_accrued_cents`, `stipend_paid_cents`, `stipend_clawed_back_cents`
        and `verified_minutes_lifetime` — to zero, with
        `training_modules_current_cycle` an empty array."

        Design: Corner/entities/retrieve_mentor_returns_stored_and_derived_fields
        """
        site = create_site(api)
        mentor = create_mentor(api, site["id"])
        post_certify_training(api, mentor["id"])

        stored = validate_success(api.get_mentor(mentor["id"], ADMIN))
        assert stored["site_id"] == site["id"], (
            f"the mentor is registered against its site, got {stored['site_id']}"
        )
        assert stored["subject_endorsements"] == ["MATH"], (
            f"the endorsement array is echoed back, got {stored['subject_endorsements']}"
        )
        assert stored["caseload_cap"] == 2, (
            f"the requested caseload cap is stored, got {stored['caseload_cap']}"
        )
        assert stored["certification_status"] == "UNCERTIFIED", (
            "posting training credits does not certify anybody, got "
            f"{stored['certification_status']}"
        )
        assert_two_decimals(
            stored["training_hours_current_cycle"], 18.00, "training_hours_current_cycle"
        )
        assert stored["active_caseload_count"] == 0, (
            f"an unmatched mentor carries no caseload, got {stored['active_caseload_count']}"
        )
        assert stored["certification_expires_on"] is None, (
            f"an uncertified mentor has no expiry, got {stored['certification_expires_on']}"
        )

    def test_list_mentors_returns_pagination_envelope(self, api: InductionApiClient):
        """Two pages of size two cover three mentors and report has_more honestly.

        The PRD fixes the page window and the meta fields: "`limit` caps the number
        of rows returned; when omitted it defaults to 10, and the accepted range is
        a minimum of 1 and a maximum of 100. `offset` skips rows and defaults to 0,
        with no upper bound beyond the size of the collection." List responses
        then "carry `limit`, `offset`, `total_count` and `has_more` in the `meta`
        object of the envelope."

        Design: Corner/entities/list_mentors_returns_pagination_envelope
        """
        site = create_site(api)
        first = create_mentor(api, site["id"], full_name="Rosa Alvarez")
        second = create_mentor(
            api, site["id"], full_name="Ken Ito", subject_endorsements=["SCIENCE"]
        )
        third = create_mentor(
            api, site["id"], full_name="Ana Ruiz", subject_endorsements=["ELA"]
        )

        page_one_response = api.list_mentors(ADMIN, {"limit": 2, "offset": 0})
        page_one, meta_one = validate_paginated(page_one_response)
        assert page_one_response.json()["response_type"] == "array", (
            "a collection read is an array envelope"
        )
        assert len(page_one) == 2, f"a limit of 2 returns 2 rows, got {len(page_one)}"
        assert meta_one["total_count"] == 3, (
            f"the total ignores the page window, got {meta_one['total_count']}"
        )
        assert meta_one["limit"] == 2, f"the limit is echoed, got {meta_one['limit']}"
        assert meta_one["offset"] == 0, f"the offset is echoed, got {meta_one['offset']}"
        assert meta_one["has_more"] is True, (
            f"one mentor is still unseen, got has_more {meta_one['has_more']}"
        )

        page_two, meta_two = validate_paginated(
            api.list_mentors(ADMIN, {"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1, f"only one row is left, got {len(page_two)}"
        assert meta_two["total_count"] == 3, (
            f"the total is unchanged, got {meta_two['total_count']}"
        )
        assert meta_two["offset"] == 2, f"the offset is echoed, got {meta_two['offset']}"
        assert meta_two["has_more"] is False, (
            f"the collection is exhausted, got has_more {meta_two['has_more']}"
        )

        assert set(ids_of(page_one) + ids_of(page_two)) == {
            first["id"],
            second["id"],
            third["id"],
        }, "the two pages together must cover the collection exactly once"


class TestNoviceTeacherRows:
    """Enrolment, its server-owned fields and its referential failures."""

    def test_system_fields_are_server_minted_on_novice_creation(
        self, api: InductionApiClient
    ):
        """Enrolment mints the audit stamps and the whole program-status block itself.

        The PRD reserves every one of these fields for the server: "Enrolment
        initialises `license_stage` to `PRELIMINARY`, `program_status` to
        `ENROLLED`, `license_advancement_status` to `NOT_ELIGIBLE`, and
        `retention_outcome` to `UNKNOWN`, with `retention_observed_on` and
        `withdrawn_reason` both null and every progress counter —
        `verified_contact_minutes`, `documented_observation_cycles`,
        `credited_seminar_sessions`, `attained_milestone_count`,
        `readiness_index_live` and `readiness_index_snapshot` — at zero."

        Design: Corner/entities/system_fields_are_server_minted_on_novice_creation
        """
        site = create_site(api)
        cohort = create_cohort(api)

        novice = validate_success(
            api.create_novice(f.novice_payload(site["id"], cohort["id"]), ADMIN), 201
        )

        assert_system_fields(novice, expected_version=1)
        assert_instant_equals(novice["created_at"], CLOCK_INITIAL_UTC, "created_at")
        assert novice["program_status"] == "ENROLLED", (
            f"enrolment starts at ENROLLED, got {novice['program_status']}"
        )
        assert novice["license_stage"] == "PRELIMINARY", (
            f"the licence starts PRELIMINARY, got {novice['license_stage']}"
        )
        assert novice["license_advancement_status"] == "NOT_ELIGIBLE", (
            f"nothing is recommended yet, got {novice['license_advancement_status']}"
        )
        assert novice["retention_outcome"] == "UNKNOWN", (
            f"retention is unknown a year ahead of time, got {novice['retention_outcome']}"
        )
        assert novice["verified_contact_minutes"] == 0, (
            f"no minutes are banked yet, got {novice['verified_contact_minutes']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 0.00, "readiness_index_live")

        assert read_cohort(api, cohort["id"])["enrolled_novice_count"] == 1, (
            "the cohort counter follows the enrolment"
        )

    def test_novice_subject_area_outside_enum_rejected(self, api: InductionApiClient):
        """PHYSICAL_EDUCATION is not one of the seven declared subject areas.

        The PRD lists the enum exhaustively: "Enrolling a **novice teacher**
        requires the `site_id` of the school where they teach, the `cohort_id` of
        their seminar cohort, a `full_name`, a `subject_area` drawn from `MATH`,
        `SCIENCE`, `ELA`, `SOCIAL_STUDIES`, `SPED`, `WORLD_LANGUAGE` and `CTE`, and
        an `induction_year` of either 1 or 2 marking which year of the two-year
        program they are in."

        Design: Corner/entities/novice_subject_area_outside_enum_rejected
        """
        site = create_site(api)
        cohort = create_cohort(api)

        response = api.create_novice(
            f.novice_payload(site["id"], cohort["id"], subject_area="PHYSICAL_EDUCATION"),
            ADMIN,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        assert read_cohort(api, cohort["id"])["enrolled_novice_count"] == 0, (
            "a rejected enrolment stores no novice, so the cohort counter stays at zero"
        )

    def test_get_novice_teacher_unknown_id_returns_not_found(
        self, api: InductionApiClient
    ):
        """An id that was never minted is a collection-specific 404, not a 400.

        The PRD assigns each collection its own not-found code: "The path
        identifier resolves to an existing row of the addressed collection —
        otherwise the collection's own 404: `ERR_SITE_NOT_FOUND`,
        `ERR_MENTOR_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_NOVICE_NOT_FOUND`,
        `ERR_MATCH_NOT_FOUND`, `ERR_CONTACT_LOG_NOT_FOUND`,
        `ERR_OBSERVATION_CYCLE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`,
        `ERR_ATTAINMENT_NOT_FOUND`, `ERR_SEMINAR_SESSION_NOT_FOUND`,
        `ERR_SEMINAR_ATTENDANCE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND` or
        `ERR_CERTIFICATION_NOT_FOUND`."

        Design: Corner/entities/get_novice_teacher_unknown_id_returns_not_found
        """
        create_site(api)
        create_cohort(api)

        response = api.get_novice(NON_EXISTENT_UUID, ADMIN)
        validate_error(response, ERR_NOVICE_NOT_FOUND, 404)
        assert response.json()["response_type"] == "error", (
            "a refusal uses the error envelope"
        )

    def test_novice_creation_with_unknown_cohort_id_returns_not_found(
        self, api: InductionApiClient
    ):
        """A fabricated body foreign key is an existence failure, not a bad request.

        The PRD puts body-key resolution one rung above type checking: "Every
        foreign key supplied in a request body resolves to an existing row of the
        entity it references, again reported through the referenced collection's
        404 code. Body keys are resolved in the order they are declared for that
        operation, and the first unresolvable one determines the error. This
        applies to mentor creation, novice enrolment, match proposal, contact-log
        creation, observation-cycle creation, milestone definition, attainment
        creation, seminar-session creation, attendance recording, disbursement
        drafting and packet creation."

        Design: Corner/entities/novice_creation_with_unknown_cohort_id_returns_not_found
        """
        site = create_site(api)

        response = api.create_novice(
            f.novice_payload(site["id"], NON_EXISTENT_UUID), ADMIN
        )
        error = validate_error(response, ERR_COHORT_NOT_FOUND, 404)
        assert error["error_id"] != ERR_INVALID_REQUEST, (
            "every other field is well formed, so the refusal is referential"
        )


class TestMentorRequiredFields:
    """Registration refuses an incomplete body and stores nothing."""

    def test_create_mentor_without_full_name_rejected(self, api: InductionApiClient):
        """Omitting full_name is a 400 and leaves the site with no mentors at all.

        The PRD names the required fields of a mentor: "A **mentor** is a veteran
        teacher registered against a `site_id` with a `full_name` and a non-empty
        `subject_endorsements` array whose members are drawn from `MATH`,
        `SCIENCE`, `ELA`, `SOCIAL_STUDIES`, `SPED`, `WORLD_LANGUAGE` and `CTE`,
        with no duplicates."

        Design: Corner/entities/create_mentor_without_full_name_rejected
        """
        site = create_site(api)

        response = api.create_mentor(
            f.mentor_payload(site["id"], full_name=None), ADMIN
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_mentors(ADMIN, {"site_id": site["id"]}))
        assert meta["total_count"] == 0, (
            f"a refused registration stores no mentor, got {meta['total_count']}"
        )


class TestCohortDefaults:
    """The cohort's omitted-field default and its opening counters."""

    def test_cohort_seminar_sessions_required_defaults_to_six(
        self, api: InductionApiClient
    ):
        """With the field omitted the seminar requirement lands on the declared six.

        The PRD states the default alongside its bounds: "A cohort also fixes
        `seminar_sessions_required`, the number of seminar sessions a novice of
        that cohort must have credited before a completion packet may be submitted
        to the state; it defaults to 6 and must be between 1 and 24 inclusive.
        Cohorts open in `FORMING` with `enrolled_novice_count` at 0 and `closed_at`
        null."

        Design: Corner/entities/cohort_seminar_sessions_required_defaults_to_six
        """
        set_clock(api, CLOCK_INITIAL_UTC)

        cohort = validate_success(
            api.create_cohort(f.cohort_payload(seminar_sessions_required=None), ADMIN),
            201,
        )
        assert cohort["seminar_sessions_required"] == 6, (
            "an omitted requirement takes the declared default, got "
            f"{cohort['seminar_sessions_required']}"
        )
        assert cohort["status"] == "FORMING", (
            f"a new cohort opens in FORMING, got {cohort['status']}"
        )
        assert cohort["enrolled_novice_count"] == 0, (
            f"nobody is enrolled yet, got {cohort['enrolled_novice_count']}"
        )
        assert cohort["closed_at"] is None, (
            f"a forming cohort has no closure instant, got {cohort['closed_at']}"
        )


class TestComputedCounters:
    """Slot counters that the server derives rather than the client supplying."""

    def test_site_active_match_count_is_computed_from_matches(
        self, api: InductionApiClient
    ):
        """Both slot counters read 0 under a PROPOSED match and 1 once it is ACTIVE.

        The PRD ties the mentor counter to the live match set: "`active_caseload_count`
        always reflects the number of that mentor's matches currently in
        `match_status` `ACTIVE`." Activation is what moves both: it "increments the
        mentor's `active_caseload_count` and the site's `active_match_count` by one
        each".

        Design: Corner/entities/site_active_match_count_is_computed_from_matches
        """
        site = create_site(api)
        cohort = create_cohort(api)
        mentor = create_certified_mentor(api, site["id"])
        novice = create_novice(api, site["id"], cohort["id"])
        match = propose_match(api, novice["id"], mentor["version"], mentor["id"])

        assert read_site(api, site["id"])["active_match_count"] == 0, (
            "a proposal occupies no slot at the site"
        )
        assert read_mentor(api, mentor["id"])["active_caseload_count"] == 0, (
            "a proposal occupies no slot on the mentor"
        )

        activated = activate_match(api, match["id"])
        assert activated["match_status"] == "ACTIVE", (
            f"the disposition activates the match, got {activated['match_status']}"
        )

        assert read_site(api, site["id"])["active_match_count"] == 1, (
            "activation consumes one of the site's slots"
        )
        assert read_mentor(api, mentor["id"])["active_caseload_count"] == 1, (
            "activation consumes one of the mentor's caseload slots"
        )


class TestMilestoneImmutability:
    """Milestone is the one entity carrying no version and no updated_at."""

    def test_milestone_is_immutable_config_without_version(
        self, api: InductionApiClient
    ):
        """A milestone definition exposes only id and created_at, and re-reads identically.

        The PRD carves out exactly this exception: "The single exception is the
        `Milestone` entity, which is immutable configuration: a milestone
        definition carries only `id` and `created_at`, and both `updated_at` and
        `version` are absent from it. There is no endpoint that updates or deletes
        a milestone definition."

        Design: Corner/entities/milestone_is_immutable_config_without_version
        """
        set_clock(api, CLOCK_INITIAL_UTC)

        created = validate_success(
            api.create_milestone(
                f.milestone_payload("IND_ENTRY", 1, title="Entry conference complete"),
                ADMIN,
            ),
            201,
        )
        assert_immutable_system_fields(created)
        assert created["code"] == "IND_ENTRY", (
            f"the code is stored as supplied, got {created['code']}"
        )
        assert created["sequence_index"] == 1, (
            f"the sequence index is stored as supplied, got {created['sequence_index']}"
        )
        assert created["prerequisite_milestone_id"] is None, (
            "the first milestone has no prerequisite, got "
            f"{created['prerequisite_milestone_id']}"
        )

        reread = validate_success(api.get_milestone(created["id"], ADMIN))
        assert_immutable_system_fields(reread)
        assert reread == created, (
            "an immutable definition must re-read field for field identically"
        )


class TestContactLogReverseReachability:
    """A child collection is reached by filtering, never by nesting."""

    def test_contact_log_match_fk_is_reverse_reachable(self, api: InductionApiClient):
        """?match_id= returns exactly that match's two logs and excludes the other's.

        The PRD makes filtered listing the only way down the graph: "Because the
        entity graph is flat — every collection is addressed at the root of the API
        and children are reached by filtering rather than by nesting — each foreign
        key declared anywhere in the model is reverse-reachable through a filtered
        list."

        Design: Corner/entities/contact_log_match_fk_is_reverse_reachable
        """
        site = create_site(api)
        cohort = create_cohort(api)
        mentor = create_certified_mentor(api, site["id"])
        novice_a = create_novice(api, site["id"], cohort["id"], full_name="Dana Pike")
        novice_b = create_novice(api, site["id"], cohort["id"], full_name="Eli Navarro")
        match_a = propose_match(api, novice_a["id"], mentor["version"], mentor["id"])
        activate_match(api, match_a["id"])
        match_b = propose_match(
            api, novice_b["id"], read_mentor(api, mentor["id"])["version"], mentor["id"]
        )
        activate_match(api, match_b["id"])
        set_clock(api, "2026-08-04T12:00:00Z")

        first = submit_contact_log(
            api,
            match_a["id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=mentor["id"],
            description="Planning conference with the first novice teacher",
        )
        second = submit_contact_log(
            api,
            match_a["id"],
            "2026-08-03T09:00:00Z",
            minutes=45,
            contact_type="CO_PLANNING",
            mentor_id=mentor["id"],
            description="Co-planning session with the first novice teacher",
        )
        other = submit_contact_log(
            api,
            match_b["id"],
            "2026-08-03T13:00:00Z",
            minutes=30,
            contact_type="DEBRIEF",
            mentor_id=mentor["id"],
            description="Debrief conversation with the second novice teacher",
        )

        rows, meta = validate_paginated(
            api.list_contact_logs(ADMIN, {"match_id": match_a["id"]})
        )
        assert meta["total_count"] == 2, (
            f"the filter narrows to one match's logs, got {meta['total_count']}"
        )
        assert set(ids_of(rows)) == {first["id"], second["id"]}, (
            f"exactly the two logs of that match come back, got {ids_of(rows)}"
        )
        assert other["id"] not in ids_of(rows), (
            "the second match's log must not leak into the first match's filter"
        )

        _, other_meta = validate_paginated(
            api.list_contact_logs(ADMIN, {"match_id": match_b["id"]})
        )
        assert other_meta["total_count"] == 1, (
            f"the other match owns exactly one log, got {other_meta['total_count']}"
        )

        assert read_novice(api, novice_b["id"])["program_status"] == "ACTIVE", (
            "both novices are on live matches, which is what let both logs be filed"
        )
