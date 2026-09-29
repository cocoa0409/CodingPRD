"""Refusal codes that must stay distinguishable: the not-found family, the three
403 conditions, pagination bounds, the uniqueness family and the matching cluster.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_ATTAINMENT_NOT_FOUND,
    ERR_CASELOAD_CAP_EXCEEDED,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_COHORT_NOT_FOUND,
    ERR_CONTACT_LOG_NOT_FOUND,
    ERR_DISBURSEMENT_NOT_FOUND,
    ERR_DUPLICATE_ACTIVE_MATCH,
    ERR_DUPLICATE_ATTAINMENT,
    ERR_DUPLICATE_ATTENDANCE,
    ERR_DUPLICATE_CYCLE_INDEX,
    ERR_DUPLICATE_MILESTONE_CODE,
    ERR_DUPLICATE_SESSION_INDEX,
    ERR_DUPLICATE_SITE_CODE,
    ERR_FORBIDDEN_ROLE,
    ERR_IDENTITY_NOT_RESOLVED,
    ERR_INVALID_PAGINATION,
    ERR_MATCH_NOT_FOUND,
    ERR_MENTOR_CERT_STATE_INVALID,
    ERR_MENTOR_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_NOVICE_ALREADY_MATCHED,
    ERR_NOVICE_NOT_FOUND,
    ERR_NO_ELIGIBLE_MENTOR,
    ERR_OBSERVATION_CYCLE_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_SEMINAR_ATTENDANCE_NOT_FOUND,
    ERR_SEMINAR_SESSION_NOT_FOUND,
    ERR_SITE_MISMATCH,
    ERR_SITE_NOT_FOUND,
    ERR_SITE_SLOT_CAP_EXCEEDED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_pagination_defaults, ids_of
from test_helpers.fixtures import (
    activate_match,
    attainment_for,
    build_program,
    create_certified_mentor,
    create_cohort,
    create_mentor,
    create_novice,
    create_site,
    define_milestone,
    open_observation_cycle,
    propose_match,
    read_mentor,
    read_novice,
    read_session,
    read_site,
    record_attendance,
    schedule_seminar_session,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    headers_without_role,
    make_headers,
    make_mentor_headers,
    make_site_lead_headers,
)

UNRESOLVABLE_SITE_ID = "00000000-0000-4000-8000-0000000000b1"


class TestNotFoundFamily:
    """Thirteen collections, thirteen distinct 404 codes."""

    @pytest.mark.parametrize(
        "probe_id,reader,expected_error",
        [
            ("00000000-0000-4000-8000-0000000000a1", "get_site", ERR_SITE_NOT_FOUND),
            ("00000000-0000-4000-8000-0000000000a2", "get_mentor", ERR_MENTOR_NOT_FOUND),
            ("00000000-0000-4000-8000-0000000000a3", "get_cohort", ERR_COHORT_NOT_FOUND),
            ("00000000-0000-4000-8000-0000000000a4", "get_novice", ERR_NOVICE_NOT_FOUND),
            ("00000000-0000-4000-8000-0000000000a5", "get_match", ERR_MATCH_NOT_FOUND),
            (
                "00000000-0000-4000-8000-0000000000a6",
                "get_contact_log",
                ERR_CONTACT_LOG_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000a7",
                "get_observation_cycle",
                ERR_OBSERVATION_CYCLE_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000a8",
                "get_milestone",
                ERR_MILESTONE_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000a9",
                "get_attainment",
                ERR_ATTAINMENT_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000aa",
                "get_seminar_session",
                ERR_SEMINAR_SESSION_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000ab",
                "get_attendance",
                ERR_SEMINAR_ATTENDANCE_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000ac",
                "get_disbursement",
                ERR_DISBURSEMENT_NOT_FOUND,
            ),
            (
                "00000000-0000-4000-8000-0000000000ad",
                "get_packet",
                ERR_CERTIFICATION_NOT_FOUND,
            ),
        ],
    )
    def test_not_found_sweep_returns_entity_specific_codes(
        self,
        api: InductionApiClient,
        probe_id: str,
        reader: str,
        expected_error: str,
    ):
        """Each read reports its own collection's 404 rather than a shared generic one.

        The PRD enumerates the thirteen codes: "The path identifier resolves to an
        existing row of the addressed collection — otherwise the collection's own
        404: `ERR_SITE_NOT_FOUND`, `ERR_MENTOR_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`,
        `ERR_NOVICE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_CONTACT_LOG_NOT_FOUND`,
        `ERR_OBSERVATION_CYCLE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`,
        `ERR_ATTAINMENT_NOT_FOUND`, `ERR_SEMINAR_SESSION_NOT_FOUND`,
        `ERR_SEMINAR_ATTENDANCE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND` or
        `ERR_CERTIFICATION_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_returns_entity_specific_codes
        """
        site = create_site(api)

        response = getattr(api, reader)(probe_id, ADMIN)
        validate_error(response, expected_error, 404)
        body = response.json()
        assert body["response_type"] == "error", (
            f"a refusal carries the error envelope, got {body['response_type']}"
        )
        assert body["meta"].get("api_request_id"), "a refusal is still traceable"
        assert body["meta"].get("api_request_timestamp"), "a refusal is still timestamped"

        assert read_site(api, site["id"])["id"] == site["id"], (
            "the stored row is unaffected by the failed probes"
        )


class TestThreeHundredThreeConditions:
    """Unauthenticated, forbidden role, unresolved identity and ownership are four codes."""

    def test_identity_and_ownership_denials_are_distinct(self, api: InductionApiClient):
        """Same endpoint, four different denials, four different error ids.

        The ladder separates identity resolution from ownership: "For an
        entity-backed role, `X-User-ID` is present and resolves to a live row of its
        backing entity — otherwise `ERR_IDENTITY_NOT_RESOLVED`." Ownership is a
        later and different rung: "The resolved entity-backed identity owns the
        addressed resource — otherwise `ERR_OWNERSHIP_VIOLATION`. This applies to
        every endpoint whose authorized roles include `SiteInductionLead`, `Mentor`
        or `NoviceTeacher`."

        Design: Corner/errors/identity_and_ownership_denials_are_distinct
        """
        site_a = create_site(api)
        site_b = create_site(
            api, name="Southbank Middle", site_code="SB002", region_code="SOUTH"
        )
        mentor_a = create_mentor(api, site_a["id"])
        payload_a = f.mentor_payload(site_a["id"], full_name="Nils Berg")

        unresolved = api.create_mentor(
            payload_a, make_site_lead_headers(UNRESOLVABLE_SITE_ID)
        )
        validate_error(unresolved, ERR_IDENTITY_NOT_RESOLVED, 403)

        wrong_site = api.create_mentor(payload_a, make_site_lead_headers(site_b["id"]))
        validate_error(wrong_site, ERR_OWNERSHIP_VIOLATION, 403)

        foreign_read = api.get_mentor(mentor_a["id"], make_site_lead_headers(site_b["id"]))
        validate_error(foreign_read, ERR_OWNERSHIP_VIOLATION, 403)

        own_site = validate_success(
            api.create_mentor(
                f.mentor_payload(site_b["id"], full_name="Nils Berg"),
                make_site_lead_headers(site_b["id"]),
            ),
            201,
        )
        assert own_site["site_id"] == site_b["id"]
        assert own_site["certification_status"] == "UNCERTIFIED"

        no_role = api.create_mentor(payload_a, headers_without_role())
        validate_error(no_role, ERR_UNAUTHENTICATED, 401)

        undeclared_role = api.create_mentor(
            payload_a, make_headers("DistrictClerk", "u-clerk-1")
        )
        validate_error(undeclared_role, ERR_UNAUTHENTICATED, 401)

        wrong_role = api.create_site(f.site_payload(site_code="XX001"), make_mentor_headers(mentor_a["id"]))
        validate_error(wrong_role, ERR_FORBIDDEN_ROLE, 403)

        _, meta = validate_paginated(api.list_mentors(ADMIN, {"site_id": site_a["id"]}))
        assert meta["total_count"] == 1, (
            f"none of the refused calls stored a mentor, got {meta['total_count']}"
        )


class TestPaginationBounds:
    """Both ends of the limit range and the sign of the offset are enforced."""

    @pytest.mark.parametrize(
        "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}]
    )
    def test_pagination_bounds_rejected_on_list_reads(
        self, api: InductionApiClient, params: dict
    ):
        """limit 0, limit 101 and a negative offset are each refused.

        The PRD fixes the accepted range and the refusal: "`limit` caps the number
        of rows returned; when omitted it defaults to 10, and the accepted range is
        a minimum of 1 and a maximum of 100."

        Design: Corner/errors/pagination_bounds_rejected_on_list_reads
        """
        site = create_site(api)
        create_mentor(api, site["id"])

        validate_error(api.list_mentors(ADMIN, params), ERR_INVALID_PAGINATION, 400)

    def test_the_inclusive_upper_bound_and_the_declared_defaults_are_accepted(
        self, api: InductionApiClient
    ):
        """limit=100 is inside the range and an omitted window falls back to 10 and 0.

        The declared defaults are part of the same rule: "`offset` skips rows and
        defaults to 0, with no upper bound beyond the size of the collection."

        Design: Corner/errors/pagination_bounds_rejected_on_list_reads
        """
        site = create_site(api)
        create_mentor(api, site["id"])

        _, meta = validate_paginated(api.list_mentors(ADMIN, {"limit": 100, "offset": 0}))
        assert meta["limit"] == 100, (
            f"100 is inside the inclusive bound, got limit {meta['limit']}"
        )
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        _, default_meta = validate_paginated(api.list_mentors(ADMIN))
        assert_pagination_defaults(default_meta)


class TestUniquenessFamily:
    """One uniqueness rule, four differently scoped keys, four codes."""

    def test_duplicate_code_and_index_sweep(self, api: InductionApiClient):
        """A district-wide code, a config pair and two parent-scoped indices.

        The PRD groups them and keeps the codes apart: "The uniqueness family: no
        duplicate observation `cycle_index` on the match
        (`ERR_DUPLICATE_CYCLE_INDEX`), no duplicate `session_index` in the cohort
        (`ERR_DUPLICATE_SESSION_INDEX`), no duplicate attendance row for the same
        session and novice (`ERR_DUPLICATE_ATTENDANCE`), no duplicate `site_code`
        (`ERR_DUPLICATE_SITE_CODE`), no duplicate milestone `code` or
        `sequence_index` (`ERR_DUPLICATE_MILESTONE_CODE`), no `APPROVED` or `PAID`
        disbursement for the same mentor and `period_code`
        (`ERR_DUPLICATE_DISBURSEMENT_PERIOD`), and no duplicate attainment row for
        the same novice and milestone (`ERR_DUPLICATE_ATTAINMENT`) — all HTTP 409."

        Design: Corner/errors/duplicate_code_and_index_sweep
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        define_milestone(api, "IND_M1", 1, title="Orientation complete")
        open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
        schedule_seminar_session(
            api,
            program["cohort_id"],
            1,
            "2026-08-12T15:00:00Z",
            "2026-08-12T16:00:00Z",
            topic="Classroom routines and equitable participation",
        )

        duplicate_site = api.create_site(
            f.site_payload(name="Northgate Annex", site_code="NG001", mentor_slot_cap=4), ADMIN
        )
        validate_error(duplicate_site, ERR_DUPLICATE_SITE_CODE, 409)

        duplicate_code = api.create_milestone(
            f.milestone_payload("IND_M1", 5, title="Duplicate code, free sequence"), ADMIN
        )
        validate_error(duplicate_code, ERR_DUPLICATE_MILESTONE_CODE, 409)

        duplicate_index = api.create_milestone(
            f.milestone_payload("IND_M9", 1, title="Free code, duplicate sequence"), ADMIN
        )
        validate_error(duplicate_index, ERR_DUPLICATE_MILESTONE_CODE, 409)

        duplicate_cycle = api.create_observation_cycle(
            f.observation_cycle_payload(
                program["match_id"], 1, "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z"
            ),
            mentor_headers,
        )
        validate_error(duplicate_cycle, ERR_DUPLICATE_CYCLE_INDEX, 409)

        duplicate_session = api.create_seminar_session(
            f.seminar_session_payload(
                program["cohort_id"],
                1,
                "2026-08-13T15:00:00Z",
                "2026-08-13T16:00:00Z",
                topic="Family engagement",
            ),
            ADMIN,
        )
        validate_error(duplicate_session, ERR_DUPLICATE_SESSION_INDEX, 409)

        _, sites = validate_paginated(api.list_sites(ADMIN))
        assert sites["total_count"] == 1, "no second site was stored"
        _, milestones = validate_paginated(api.list_milestones(ADMIN))
        assert milestones["total_count"] == 1, "no second milestone was stored"
        _, cycles = validate_paginated(
            api.list_observation_cycles(ADMIN, {"match_id": program["match_id"]})
        )
        assert cycles["total_count"] == 1, "no second cycle was stored"
        _, sessions = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": program["cohort_id"]})
        )
        assert sessions["total_count"] == 1, "no second session was stored"

    def test_duplicate_attendance_and_attainment_rows_rejected(
        self, api: InductionApiClient
    ):
        """Two pair-scoped junction rows refuse a second copy without double-counting.

        The PRD scopes the attainment key to the pair: explicit creation "takes
        `novice_id`, `milestone_id` and an optional `evidence_note` (10 to 1000
        characters when supplied), initialises `revocation_count` to zero, and
        refuses a second row for the same novice-and-milestone pair with
        `ERR_DUPLICATE_ATTAINMENT`."

        Design: Corner/errors/duplicate_attendance_and_attainment_rows_rejected
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        milestone = define_milestone(api, "IND_M1", 1, title="Orientation complete")
        attainment = attainment_for(api, program["novice_id"], milestone["id"])
        session = schedule_seminar_session(
            api,
            program["cohort_id"],
            1,
            "2026-08-12T15:00:00Z",
            "2026-08-12T17:00:00Z",
            topic="Classroom routines and equitable participation",
        )
        attendance = record_attendance(
            api, session["id"], program["novice_id"], "PRESENT", 120, headers=lead
        )

        duplicate_attendance = api.create_attendance(
            f.attendance_payload(session["id"], program["novice_id"], "LATE", 90), lead
        )
        validate_error(duplicate_attendance, ERR_DUPLICATE_ATTENDANCE, 409)

        duplicate_attainment = api.create_attainment(
            f.attainment_payload(
                program["novice_id"],
                milestone["id"],
                evidence_note="Second copy of the orientation roster",
            ),
            ADMIN,
        )
        validate_error(duplicate_attainment, ERR_DUPLICATE_ATTAINMENT, 409)

        rows, meta = validate_paginated(
            api.list_attendances(ADMIN, {"session_id": session["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the pair keeps one row, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [attendance["id"]]
        assert rows[0]["credited"] is True
        assert read_session(api, session["id"])["credited_attendance_count"] == 1

        attainment_rows, attainment_meta = validate_paginated(
            api.list_attainments(ADMIN, {"novice_id": program["novice_id"]})
        )
        assert attainment_meta["total_count"] == 1, (
            f"and so does the attainment pair, got {attainment_meta['total_count']}"
        )
        assert ids_of(attainment_rows) == [attainment["id"]]
        assert attainment_rows[0]["status"] == "IN_PROGRESS"

        novice = read_novice(api, program["novice_id"])
        # "a credited row against a session still SCHEDULED shows up in the
        # session's count immediately but only lifts the novice's
        # credited_seminar_sessions once the session is marked held" — this
        # session was never held, so the novice's counter stays at zero.
        assert novice["credited_seminar_sessions"] == 0, (
            "the session is still SCHEDULED, so its credit has not reached the "
            f"novice yet, got {novice['credited_seminar_sessions']}"
        )
        assert novice["attained_milestone_count"] == 0


class TestMatchCreationRefusals:
    """Four rejections of one creation call, four distinct codes."""

    def test_match_creation_referential_and_uniqueness_errors(
        self, api: InductionApiClient
    ):
        """Cross-site, duplicate pair, already-matched novice and an empty candidate set.

        The PRD keeps the three graph refusals apart: "No match may already exist
        for the same mentor-and-novice pair in `PROPOSED`, `ACTIVE` or `SUSPENDED`,
        or the refusal is `ERR_DUPLICATE_ACTIVE_MATCH`; pairs whose earlier match
        reached `ENDED` or `REJECTED` may be re-proposed, so the uniqueness scope is
        state-qualified rather than absolute."

        Design: Corner/errors/match_creation_referential_and_uniqueness_errors
        """
        site_a = create_site(api)
        site_b = create_site(
            api, name="Southbank Middle", site_code="SB002", region_code="SOUTH"
        )
        cohort = create_cohort(api)
        mentor_one = create_certified_mentor(api, site_a["id"])
        mentor_two = create_certified_mentor(api, site_a["id"], full_name="Nils Berg")
        novice_here = create_novice(api, site_a["id"], cohort["id"], full_name="Dana Pike")
        novice_there = create_novice(api, site_b["id"], cohort["id"], full_name="Ira Vance")

        cross_site = api.create_match(
            f.match_payload(
                novice_there["id"],
                read_mentor(api, mentor_one["id"])["version"],
                mentor_one["id"],
            ),
            ADMIN,
        )
        validate_error(cross_site, ERR_SITE_MISMATCH, 422)

        match = validate_success(
            api.create_match(
                f.match_payload(
                    novice_here["id"],
                    read_mentor(api, mentor_one["id"])["version"],
                    mentor_one["id"],
                ),
                ADMIN,
            ),
            201,
        )
        assert match["match_status"] == "PROPOSED"
        assert match["selection_mode"] == "EXPLICIT"
        assert match["subject_match_tier"] == "EXACT"

        duplicate_pair = api.create_match(
            f.match_payload(
                novice_here["id"],
                read_mentor(api, mentor_one["id"])["version"],
                mentor_one["id"],
            ),
            ADMIN,
        )
        validate_error(duplicate_pair, ERR_DUPLICATE_ACTIVE_MATCH, 409)

        other_mentor = api.create_match(
            f.match_payload(
                novice_here["id"],
                read_mentor(api, mentor_two["id"])["version"],
                mentor_two["id"],
            ),
            ADMIN,
        )
        validate_error(other_mentor, ERR_NOVICE_ALREADY_MATCHED, 409)

        no_candidate = api.create_match(
            f.match_payload(novice_there["id"], read_mentor(api, mentor_one["id"])["version"]),
            ADMIN,
        )
        validate_error(no_candidate, ERR_NO_ELIGIBLE_MENTOR, 422)

        rows, meta = validate_paginated(
            api.list_matches(ADMIN, {"novice_id": novice_here["id"]})
        )
        assert meta["total_count"] == 1, (
            f"one match survives for the matched novice, got {meta['total_count']}"
        )
        assert ids_of(rows) == [match["id"]]
        _, other_meta = validate_paginated(
            api.list_matches(ADMIN, {"novice_id": novice_there["id"]})
        )
        assert other_meta["total_count"] == 0, (
            f"and none for the other site's novice, got {other_meta['total_count']}"
        )
        assert read_novice(api, novice_there["id"])["program_status"] == "ENROLLED"


class TestActivationCapPriority:
    """The mentor-level cap outranks the site-level one on the same call."""

    def test_activation_cap_errors_distinguish_caseload_from_slot(
        self, api: InductionApiClient
    ):
        """Both caps full reports the caseload; a free caseload exposes the slot.

        Activation re-checks both caps, and the PRD names them separately: it
        requires "the mentor's `active_caseload_count` to be strictly below
        `caseload_cap` (otherwise `ERR_CASELOAD_CAP_EXCEEDED` — a count exactly
        equal to the cap fails), the site's `active_match_count` to be strictly
        below `mentor_slot_cap` (otherwise `ERR_SITE_SLOT_CAP_EXCEEDED`), and the
        novice's `program_status` to be `MATCHED`."

        Design: Corner/errors/activation_cap_errors_distinguish_caseload_from_slot
        """
        site = create_site(api, mentor_slot_cap=1)
        cohort = create_cohort(api)
        narrow = create_certified_mentor(api, site["id"], caseload_cap=1)
        roomy = create_certified_mentor(
            api, site["id"], full_name="Nils Berg", caseload_cap=2
        )
        first = create_novice(api, site["id"], cohort["id"], full_name="Dana Pike")
        second = create_novice(api, site["id"], cohort["id"], full_name="Ira Vance")
        third = create_novice(api, site["id"], cohort["id"], full_name="Omar Reyes")

        match_one = propose_match(
            api, first["id"], read_mentor(api, narrow["id"])["version"], narrow["id"]
        )
        match_two = propose_match(
            api, second["id"], read_mentor(api, narrow["id"])["version"], narrow["id"]
        )
        match_three = propose_match(
            api, third["id"], read_mentor(api, roomy["id"])["version"], roomy["id"]
        )
        activate_match(api, match_one["id"])

        caseload_full = api.dispose_match(
            match_two["id"], f.disposition_payload("ACTIVATE"), ADMIN
        )
        refusal = validate_error(caseload_full, ERR_CASELOAD_CAP_EXCEEDED, 422)
        assert refusal["error_id"] != ERR_SITE_SLOT_CAP_EXCEEDED, (
            "the site slot is equally full, but the mentor-level rule is ranked first"
        )

        slot_full = api.dispose_match(
            match_three["id"], f.disposition_payload("ACTIVATE"), ADMIN
        )
        validate_error(slot_full, ERR_SITE_SLOT_CAP_EXCEEDED, 422)

        stalled = validate_success(api.get_match(match_two["id"], ADMIN))
        assert stalled["match_status"] == "PROPOSED"
        assert stalled["activated_at"] is None
        assert stalled["pinned_stipend_rate_cents_per_hour"] is None
        assert validate_success(api.get_match(match_three["id"], ADMIN))[
            "match_status"
        ] == "PROPOSED"

        assert read_mentor(api, narrow["id"])["active_caseload_count"] == 1
        assert read_mentor(api, roomy["id"])["active_caseload_count"] == 0
        assert read_site(api, site["id"])["active_match_count"] == 1
        assert read_novice(api, second["id"])["program_status"] == "MATCHED"
        assert read_novice(api, third["id"])["program_status"] == "MATCHED"


class TestCertificationActionStates:
    """One code guards four different from-state predicates on two endpoints."""

    def test_certification_action_state_errors(self, api: InductionApiClient):
        """Each illegal action is refused with the same code while the legal ones pass.

        The PRD makes the from-state predicate action-specific: "The mentor's
        `certification_status` permits the requested certification action —
        `UNCERTIFIED` or `LAPSED` for a certify action, `CERTIFIED` for recertify and
        suspend, `SUSPENDED` for reinstate, any non-`RETIRED` status for retire —
        otherwise `ERR_MENTOR_CERT_STATE_INVALID` (HTTP 409). The same rule refuses
        training credits posted to a `RETIRED` mentor."

        Design: Corner/errors/certification_action_state_errors
        """
        site = create_site(api)
        mentor = create_certified_mentor(api, site["id"])
        assert mentor["certification_status"] == "CERTIFIED"
        assert float(read_mentor(api, mentor["id"])["training_hours_current_cycle"]) == 0.00, (
            "certification reset the cycle ledger"
        )

        recertify_again = api.certification_action(
            mentor["id"], f.certification_payload("CERTIFY"), ADMIN
        )
        validate_error(recertify_again, ERR_MENTOR_CERT_STATE_INVALID, 409)

        early_reinstate = api.certification_action(
            mentor["id"], f.certification_payload("REINSTATE"), ADMIN
        )
        validate_error(early_reinstate, ERR_MENTOR_CERT_STATE_INVALID, 409)

        suspended = validate_success(
            api.certification_action(
                mentor["id"],
                f.certification_payload(
                    "SUSPEND",
                    reason="Site investigation opened into an unrelated incident",
                ),
                ADMIN,
            )
        )
        assert suspended["certification_status"] == "SUSPENDED"

        recertify_from_suspended = api.certification_action(
            mentor["id"], f.certification_payload("RECERTIFY"), ADMIN
        )
        validate_error(recertify_from_suspended, ERR_MENTOR_CERT_STATE_INVALID, 409)

        reinstated = validate_success(
            api.certification_action(
                mentor["id"], f.certification_payload("REINSTATE"), ADMIN
            )
        )
        assert reinstated["certification_status"] == "CERTIFIED", (
            f"reinstatement is legal from SUSPENDED, got {reinstated['certification_status']}"
        )
        assert reinstated["suspension_reason"] is None, (
            f"reinstatement clears the reason, got {reinstated['suspension_reason']}"
        )

        retired = validate_success(
            api.certification_action(
                mentor["id"],
                f.certification_payload(
                    "RETIRE", reason="Mentor retired from district service"
                ),
                ADMIN,
            )
        )
        assert retired["certification_status"] == "RETIRED"
        assert retired["certification_expires_on"] is None, (
            f"retirement drops the expiry, got {retired['certification_expires_on']}"
        )

        credit_after_retirement = api.post_training_credit(
            mentor["id"],
            f.training_credit_payload(
                module_code="RECERT_REFRESH", hours=6.00, completed_on="2026-07-20"
            ),
            ADMIN,
        )
        validate_error(credit_after_retirement, ERR_MENTOR_CERT_STATE_INVALID, 409)

        final = read_mentor(api, mentor["id"])
        assert float(final["training_hours_current_cycle"]) == 0.00, (
            "the refused credit was never banked, got "
            f"{final['training_hours_current_cycle']}"
        )
        assert final["training_modules_current_cycle"] == [], (
            f"and the module list stays empty, got {final['training_modules_current_cycle']}"
        )
