"""Elections, ballot language, publications, and the canvass cascade
(PRD §3.6, §3.7)."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, assert_district_publication,
    get_success_data, validate_error, validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    ballot_language_of_length, canvass_payload, canvass_result_entry,
    create_ballot_measure_payload, create_election_payload,
    create_publication_payload,
)
from test_helpers.fixtures import (
    CERTIFIER_USER_ID, DRAFTER_USER_ID, approve_board, canvass,
    certify_measure, create_ballot_measure, create_bond_proposal,
    create_election, add_project, set_clock,
    setup_approved_proposal, setup_certified_measure, setup_passed_proposal,
)
from test_helpers.test_users import TEST_USERS, make_board_clerk_headers

BC = TEST_USERS["board_clerk_headers"]
AU = TEST_USERS["auditor_headers"]

ELECTION = "2027-11-02"   # first Tuesday of November 2027


def _two_certified_measures(api):
    """Two BOARD_APPROVED 1,000,000 proposals, each with a certified measure
    on the 2027-11-02 election. Returns (fy, bm1, bm2, el)."""
    ctx_a = setup_approved_proposal(
        total_amount=1000000,
        projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
    fy = ctx_a["fy"]
    bp_b = create_bond_proposal(fy["id"], total_amount=1000000,
                                question_title="Bond Question B",
                                purpose="HVAC")
    add_project(bp_b["id"], "HVAC", "ES-02", 1000000, "2028-06-01",
                "2028-08-15", 1)
    approve_board(bp_b["id"])
    el = create_election(ELECTION)
    bm1 = create_ballot_measure(el["id"], ctx_a["bp"]["id"],
                                "Shall the District issue bonds for roof "
                                "repairs")
    bm2 = create_ballot_measure(el["id"], bp_b["id"],
                                "Shall the District issue bonds for HVAC "
                                "replacement")
    set_clock("2027-08-15T00:00:00Z", BC)
    certify_measure(bm1["id"])
    certify_measure(bm2["id"])
    return fy, bm1, bm2, el


class TestElectionCalendar:
    def test_non_statutory_election_date_rejected(self, api):
        """PRD §3.7: "Statute confines election days to the first Tuesday of
        March, June, or November of any year — computed by taking the first
        day of the month and advancing it to the first Tuesday — and any other
        date is rejected with `ERR_STATUTORY_ELECTION_DATE`."

        Design: Corner/validations/non_statutory_election_date_rejected
        """
        # 2027-11-03 is a Wednesday: not a statutory election day.
        resp = api.create_election(
            create_election_payload("2027-11-03", "REGULAR"), BC)
        validate_error(resp, ApiErrorId.ERR_STATUTORY_ELECTION_DATE, 409)
        # 2028-03-07 is the first Tuesday of March 2028.
        data = validate_success(api.create_election(
            create_election_payload("2028-03-07", "SPECIAL"), BC), 201)
        assert data["status"] == "SCHEDULED"
        assert data["canvassed_at"] is None

    def test_certification_deadline_exact_day_allowed_next_day_rejected(
            self, api):
        """PRD §3.7: "The calendar comes next: certification is permitted on
        any day up to and including the day 61 days before the
        `election_date`, and a later attempt fails with
        `ERR_CERTIFICATION_DEADLINE_PASSED`."

        Design: Corner/validations/certification_deadline_exact_day_allowed_next_day_rejected
        """
        ctx_a = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        bp_b = create_bond_proposal(ctx_a["fy"]["id"], total_amount=1000000,
                                    question_title="Bond Question B",
                                    purpose="HVAC")
        add_project(bp_b["id"], "HVAC", "ES-02", 1000000, "2028-06-01",
                    "2028-08-15", 1)
        approve_board(bp_b["id"])
        el = create_election(ELECTION)
        bm1 = create_ballot_measure(el["id"], ctx_a["bp"]["id"])
        bm2 = create_ballot_measure(el["id"], bp_b["id"])
        # Deadline day itself (2027-11-02 - 61 days = 2027-09-02): allowed.
        set_clock("2027-09-02T00:00:00Z", BC)
        certified = certify_measure(bm1["id"])
        assert certified["status"] == "LANGUAGE_CERTIFIED"
        # One day later: rejected.
        set_clock("2027-09-03T00:00:00Z", BC)
        resp = api.certify_ballot_measure(
            bm2["id"], make_board_clerk_headers(CERTIFIER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED, 409)

    def test_canvass_on_election_day_rejected(self, api):
        """PRD §3.7: "The canvass is permitted only when today is strictly
        later than the `election_date` — an attempt on or before election day
        fails with `ERR_CANVASS_BEFORE_ELECTION`".

        Design: Corner/validations/canvass_on_election_day_rejected
        """
        ctx = setup_certified_measure(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        set_clock("2027-11-02T18:00:00Z", BC)  # election day itself
        resp = api.canvass_election(ctx["el"]["id"], canvass_payload([
            canvass_result_entry(ctx["bm"]["id"], 5200, 4800)]), BC)
        validate_error(resp, ApiErrorId.ERR_CANVASS_BEFORE_ELECTION, 409)
        el = validate_success(api.get_election(ctx["el"]["id"], AU), 200)
        assert el["status"] == "SCHEDULED"


class TestBallotLanguage:
    def test_exactly_200_words_certifies(self, api):
        """PRD §3.7: "Finally, the `word_count` must not exceed 200 words,
        with an over-long question rejected as `ERR_BALLOT_LANGUAGE_TOO_LONG`."
        and "At drafting, the server computes the `word_count` as the number
        of whitespace-separated tokens in the `ballot_language`".

        Design: Difficulty/boundary_precision_check/ballot_language_exactly_200_words_allowed_201_rejected
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"],
                                   ballot_language_of_length(200))
        assert bm["word_count"] == 200
        set_clock("2027-08-15T00:00:00Z", BC)
        certified = certify_measure(bm["id"])
        assert certified["status"] == "LANGUAGE_CERTIFIED"

    def test_201_words_rejected(self, api):
        """PRD §3.7: "Finally, the `word_count` must not exceed 200 words,
        with an over-long question rejected as `ERR_BALLOT_LANGUAGE_TOO_LONG`."

        Design: Difficulty/boundary_precision_check/ballot_language_exactly_200_words_allowed_201_rejected
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"],
                                   ballot_language_of_length(201))
        assert bm["word_count"] == 201
        set_clock("2027-08-15T00:00:00Z", BC)
        resp = api.certify_ballot_measure(
            bm["id"], make_board_clerk_headers(CERTIFIER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_BALLOT_LANGUAGE_TOO_LONG, 422)
        bm_now = validate_success(api.get_ballot_measure(bm["id"], AU), 200)
        assert bm_now["status"] == "LANGUAGE_DRAFT"


class TestCertificationPriorityPair:
    def test_deadline_error_beats_word_count_error(self, api):
        """PRD §2.9: "Every mutation request passes a fixed validation
        pipeline, and the earliest failing stage determines the error
        returned" — stage 10 calendar rules (certification deadline) precede
        stage 11 uniqueness and structural constraints (ballot word limit).
        PRD §3.7: "Certification formalizes the language, and its three gates
        run in pipeline order." and "The calendar comes next: certification is
        permitted on any day up to and including the day 61 days before the
        `election_date`, and a later attempt fails with
        `ERR_CERTIFICATION_DEADLINE_PASSED`. Finally, the `word_count` must
        not exceed 200 words, with an over-long question rejected as
        `ERR_BALLOT_LANGUAGE_TOO_LONG`."

        Design: Difficulty/priority_pair_validation_conflict/certify_deadline_error_beats_word_count_error
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"],
                                   ballot_language_of_length(201))
        set_clock("2027-09-10T00:00:00Z", BC)  # past the 2027-09-02 deadline
        resp = api.certify_ballot_measure(
            bm["id"], make_board_clerk_headers(CERTIFIER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED, 409)
        bm_now = validate_success(api.get_ballot_measure(bm["id"], AU), 200)
        assert bm_now["status"] == "LANGUAGE_DRAFT"

    def test_deadline_error_fires_with_short_language_too(self, api):
        """PRD §3.7: "The calendar comes next: certification is permitted on
        any day up to and including the day 61 days before the
        `election_date`, and a later attempt fails with
        `ERR_CERTIFICATION_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/certify_deadline_error_beats_word_count_error
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"])  # short language
        set_clock("2027-09-10T00:00:00Z", BC)
        resp = api.certify_ballot_measure(
            bm["id"], make_board_clerk_headers(CERTIFIER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_DEADLINE_PASSED, 409)


class TestSegregationOfDuties:
    def test_certify_by_drafting_user_rejected(self, api):
        """PRD §3.7: "Segregation of duties comes first: the certifying
        `BoardClerk`'s `X-User-ID` must differ from `drafted_by_user_id`, and
        self-certification is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/certify_by_drafting_user_rejected_segregation_of_duties
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"],
                                   drafter_user_id=DRAFTER_USER_ID)
        set_clock("2027-08-15T00:00:00Z", BC)
        # The drafter attempts to certify their own draft.
        resp = api.certify_ballot_measure(
            bm["id"], make_board_clerk_headers(DRAFTER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        bm_now = validate_success(api.get_ballot_measure(bm["id"], AU), 200)
        assert bm_now["status"] == "LANGUAGE_DRAFT"
        assert bm_now["drafted_by_user_id"] == DRAFTER_USER_ID


class TestDuplicateMeasure:
    def test_duplicate_ballot_measure_rejected(self, api):
        """PRD §3.7: "A proposal may appear at most once per election: a
        second measure for the same proposal on the same election fails with
        `ERR_DUPLICATE_BALLOT_MEASURE`."

        Design: Corner/validations/duplicate_ballot_measure_rejected
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        create_ballot_measure(el["id"], ctx["bp"]["id"])
        resp = api.create_ballot_measure(
            el["id"],
            create_ballot_measure_payload(
                ctx["bp"]["id"], "Alternative wording for the same question"),
            make_board_clerk_headers(DRAFTER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT_MEASURE, 409)


class TestCampaignRestrictions:
    def test_campaign_window_and_promotional_prohibition(self, api):
        """PRD §3.7: "Advocacy is never permitted: a `PROMOTIONAL` publication
        is always rejected with `ERR_PROHIBITED_CAMPAIGN_ACTIVITY`, regardless
        of the calendar. Neutral information has its own window: a `FACTUAL`
        publication about a `LANGUAGE_CERTIFIED` measure is rejected with
        `ERR_CAMPAIGN_RESTRICTION_WINDOW` whenever today falls inside the
        campaign restriction window — the thirty days before the election's
        `election_date` through election day itself, inclusive."

        Design: Corner/validations/campaign_restriction_window_and_promotional_prohibition
        """
        ctx = setup_certified_measure(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        bm_id = ctx["bm"]["id"]
        # PROMOTIONAL is refused even outside the window (2027-08-20).
        set_clock("2027-08-20T00:00:00Z", BC)
        resp = api.create_publication(bm_id, create_publication_payload(
            "PROMOTIONAL", "Vote YES on the bond"), BC)
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_CAMPAIGN_ACTIVITY, 403)
        # FACTUAL outside the window is recorded.
        pub = validate_success(api.create_publication(
            bm_id, create_publication_payload("FACTUAL", "Bond fact sheet"),
            BC), 201)
        assert pub["status"] == "PUBLISHED"
        # Window start (election - 30 = 2027-10-03), inclusive.
        set_clock("2027-10-03T00:00:00Z", BC)
        resp = api.create_publication(bm_id, create_publication_payload(
            "FACTUAL", "Updated fact sheet"), BC)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_RESTRICTION_WINDOW, 409)
        # Election day itself, inclusive end.
        set_clock("2027-11-02T00:00:00Z", BC)
        resp = api.create_publication(bm_id, create_publication_payload(
            "FACTUAL", "Election day fact sheet"), BC)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_RESTRICTION_WINDOW, 409)

    def test_district_publication_is_append_only_record(self, api):
        """PRD §2.4: "A `DistrictPublication` is an append-only record: it
        carries only `id` and `created_at`, and both `updated_at` and
        `version` are absent." PRD §3.7: "A publication that passes these
        gates is recorded immediately in `PUBLISHED` status, stamped with the
        issuing operator's `published_by_user_id` and tied to its measure by
        `ballot_measure_id`; publications are append-only and are never edited
        or withdrawn."

        Design: Corner/entities/district_publication_is_immutable_without_version_field
        """
        ctx = setup_approved_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        el = create_election(ELECTION)
        bm = create_ballot_measure(el["id"], ctx["bp"]["id"])
        set_clock("2027-08-15T00:00:00Z", BC)
        resp = api.create_publication(bm["id"], create_publication_payload(
            "FACTUAL", "Bond fact sheet"), BC)
        data = validate_success(resp, 201)
        assert_district_publication(data)
        assert data["status"] == "PUBLISHED"
        assert data["published_by_user_id"] == "test-clerk-1"
        assert data["ballot_measure_id"] == bm["id"]


class TestCanvass:
    def test_canvass_incomplete_and_unknown_measure_rejected(self, api):
        """PRD §3.7: "the supplied `results` must cover every
        `LANGUAGE_CERTIFIED` measure of the election exactly once, with any
        gap, extra, or duplicate entry failing as `ERR_CANVASS_INCOMPLETE`".
        PRD §2.6: "an unknown `ballot_measure_id` inside a canvass `results`
        entry surfaces `ERR_BALLOT_MEASURE_NOT_FOUND`".

        Design: Corner/validations/canvass_incomplete_and_unknown_measure_rejected
        """
        _, bm1, bm2, el = _two_certified_measures(api)
        set_clock("2027-11-03T00:00:00Z", BC)
        # Gap: bm2 (LANGUAGE_CERTIFIED) is not covered.
        resp = api.canvass_election(el["id"], canvass_payload([
            canvass_result_entry(bm1["id"], 5200, 4800)]), BC)
        validate_error(resp, ApiErrorId.ERR_CANVASS_INCOMPLETE, 422)
        # Unknown measure identifier inside results.
        resp = api.canvass_election(el["id"], canvass_payload([
            canvass_result_entry(bm1["id"], 5200, 4800),
            canvass_result_entry(NON_EXISTENT_UUID, 10, 5)]), BC)
        validate_error(resp, ApiErrorId.ERR_BALLOT_MEASURE_NOT_FOUND, 404)
        el_now = validate_success(api.get_election(el["id"], AU), 200)
        assert el_now["status"] == "SCHEDULED"

    def test_canvass_tie_votes_fail_the_measure(self, api):
        """PRD §3.7: "Each covered measure is decided by strict plurality:
        `PASSED` when its `yes_votes` are strictly greater than its
        `no_votes`, otherwise `FAILED` — a tie fails the measure". PRD §3.6:
        "a passed proposal moves `REFERRED` → `PASSED`, stamps `passed_at`,
        and authorizes its projects — each `PLANNED` project moving to
        `AUTHORIZED` with its `authorized_amount` set to its `estimated_cost`
        — while a failed one moves `REFERRED` → `FAILED`."

        Design: Corner/calculations/canvass_tie_votes_fail_the_measure
        """
        ctx = setup_certified_measure(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        set_clock("2027-11-03T00:00:00Z", BC)
        canvass(ctx["el"]["id"], [canvass_result_entry(ctx["bm"]["id"],
                                                       5000, 5000)])
        bm = validate_success(api.get_ballot_measure(ctx["bm"]["id"], AU), 200)
        assert bm["status"] == "FAILED"
        assert bm["yes_votes"] == 5000 and bm["no_votes"] == 5000
        bp = validate_success(api.get_bond_proposal(ctx["bp"]["id"], AU), 200)
        assert bp["status"] == "FAILED"
        assert bp["passed_at"] is None
        projects, _ = validate_paginated(
            api.list_bond_projects(ctx["bp"]["id"], AU))
        assert projects[0]["status"] == "PLANNED"
        assert projects[0]["authorized_amount"] == 0

    def test_canvass_already_canvassed_election_rejected(self, api):
        """PRD §3.7: "The election itself moves `SCHEDULED` → `CANVASSED`,
        stamps `canvassed_at`, increments its `version`" — canvass exists only
        from SCHEDULED, so a second canvass is the generic from-state
        violation (`ERR_INVALID_STATE`, PRD §2.9 stage 8).

        Design: Corner/state_machines/canvass_already_canvassed_election_rejected
        """
        ctx = setup_passed_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        resp = api.canvass_election(ctx["el"]["id"], canvass_payload([
            canvass_result_entry(ctx["bm"]["id"], 5200, 4800)]), BC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        bm = validate_success(api.get_ballot_measure(ctx["bm"]["id"], AU), 200)
        assert bm["status"] == "PASSED"
        assert bm["yes_votes"] == 5200 and bm["no_votes"] == 4800

    def test_certify_passed_measure_rejected_invalid_state(self, api):
        """PRD §3.7: certification moves the measure `LANGUAGE_DRAFT` →
        `LANGUAGE_CERTIFIED` ("Certification records the certifier in
        `certified_by_user_id`, moves the measure `LANGUAGE_DRAFT` →
        `LANGUAGE_CERTIFIED`") — from PASSED the trigger does not exist, the
        generic from-state violation (`ERR_INVALID_STATE`, PRD §2.9 stage 8).

        Design: Corner/state_machines/certify_passed_measure_rejected_invalid_state
        """
        ctx = setup_passed_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        resp = api.certify_ballot_measure(
            ctx["bm"]["id"], make_board_clerk_headers(CERTIFIER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCanvassCascade:
    def test_canvass_decides_measure_and_reports_count(self, api):
        """PRD §3.7: "Each covered measure is decided by strict plurality:
        `PASSED` when its `yes_votes` are strictly greater than its
        `no_votes`, otherwise `FAILED`" and "The election itself moves
        `SCHEDULED` → `CANVASSED`, stamps `canvassed_at`, increments its
        `version`, and the response reports the number of measures decided as
        `canvassed_count`."

        Design: Difficulty/transitive_cascade/canvass_cascade_measure_to_proposal_to_projects
        """
        ctx = setup_certified_measure()  # 18,000,000 with three projects
        set_clock("2027-11-03T00:00:00Z", BC)
        data = canvass(ctx["el"]["id"], [canvass_result_entry(
            ctx["bm"]["id"], 5200, 4800)])
        assert data["canvassed_count"] == 1
        el = validate_success(api.get_election(ctx["el"]["id"], AU), 200)
        assert el["status"] == "CANVASSED"
        assert el["canvassed_at"] is not None
        bm = validate_success(api.get_ballot_measure(ctx["bm"]["id"], AU), 200)
        assert bm["status"] == "PASSED"
        assert bm["yes_votes"] == 5200 and bm["no_votes"] == 4800

    def test_canvass_cascade_passes_proposal_and_authorizes_projects(
            self, api):
        """PRD §3.7: "A passing measure pulls its proposal from `REFERRED` to
        `PASSED` and stamps `passed_at` with the current timestamp; a failing
        measure pulls its proposal from `REFERRED` to `FAILED`. Each newly
        passed proposal then authorizes its project list, moving every
        `PLANNED` project to `AUTHORIZED` with `authorized_amount` set to the
        project's `estimated_cost`."

        Design: Difficulty/transitive_cascade/canvass_cascade_measure_to_proposal_to_projects
        """
        ctx = setup_certified_measure(
            projects=[("Roof Replacement", "HS-01", 6000000, "2028-06-01",
                       "2028-08-15"),
                      ("HVAC Replacement", "HS-01", 5000000, "2028-09-01",
                       "2028-11-30"),
                      ("Gym Renovation", "ES-02", 7000000, "2028-06-01",
                       "2028-12-15")])  # 6M + 5M + 7M = 18M == total_amount
        set_clock("2027-11-03T00:00:00Z", BC)
        canvass(ctx["el"]["id"], [canvass_result_entry(ctx["bm"]["id"],
                                                       5200, 4800)])
        bp = validate_success(api.get_bond_proposal(ctx["bp"]["id"], AU), 200)
        assert bp["status"] == "PASSED"
        assert bp["passed_at"] is not None
        projects, _ = validate_paginated(
            api.list_bond_projects(ctx["bp"]["id"], AU))
        assert [p["status"] for p in projects] == ["AUTHORIZED"] * 3
        costs = sorted(p["estimated_cost"] for p in projects)
        auths = sorted(p["authorized_amount"] for p in projects)
        assert costs == [5000000, 6000000, 7000000]
        assert auths == costs
