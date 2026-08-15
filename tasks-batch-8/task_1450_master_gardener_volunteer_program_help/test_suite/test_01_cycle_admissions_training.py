"""Program-cycle setup, admissions, and training-course workflows."""
import pytest

from test_helpers import (ApiErrorId, assert_same_instant,
                          create_active_volunteer,
                          create_and_open_cycle, create_application,
                          create_application_payload, create_cycle,
                          create_cycle_payload, create_enrollment_payload,
                          decide_application, get_success_data,
                          make_coordinator_headers, score_application,
                          setup_cycle_with_active_volunteer,
                          validate_error, validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]


class TestCycleCreationAndPosture:
    def test_cycle_create_applies_defaults_and_version(self, api):
        """PRD §3.1: "A new cycle begins in `DRAFT` with `accepted_count` and
        `enrolled_count` at zero and `version` at 1."
        PRD §2.5: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z, and the server must not fall back to wall-clock
        time under any circumstance."

        Design: Corner/entities/cycle_create_applies_defaults_and_version
        """
        resp = api.create_cycle(
            create_cycle_payload(priority_counties=["Harford"]), COORD)
        cycle = validate_success(resp, expected_status=201)
        assert cycle["status"] == "DRAFT"
        assert cycle["version"] == 1
        assert cycle["accepted_count"] == 0
        assert cycle["enrolled_count"] == 0
        # §2.5: created_at reads the logical clock (never wall clock);
        # compared at second precision per §2.7.
        assert_same_instant(cycle["created_at"], "2026-08-01T00:00:00Z")

    def test_invalid_cycle_state_on_second_open_returns_409(self, api):
        """PRD §3.1: "Opening the cycle moves `DRAFT → OPEN` and is valid only
        from `DRAFT` (otherwise `ERR_INVALID_CYCLE_STATE`)."

        Design: Corner/errors/invalid_cycle_state_on_second_open_returns_409
        """
        cycle = create_and_open_cycle()
        resp = api.open_cycle(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE)

    def test_begin_recert_before_window_returns_409(self, api):
        """PRD §3.1: "That transition requires the cycle to be `OPEN`
        (`ERR_INVALID_CYCLE_STATE` otherwise) and the logical clock to be at
        or past `recert_opens_at` (otherwise `ERR_RECERT_WINDOW_NOT_OPEN`)."

        Design: Corner/errors/begin_recert_before_window_returns_409
        """
        cycle = create_and_open_cycle()
        # Logical clock sits at the 2026-08-01 default, before the window.
        resp = api.begin_recertification(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_RECERT_WINDOW_NOT_OPEN)
        after = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert after["status"] == "OPEN"

    def test_cycle_posture_blocks_application_and_edit(self, api):
        """PRD §2.6: "Second, application creation, scoring, decision, and
        waitlist promotion require the cycle to be `DRAFT` or `OPEN`; against
        `RECERTIFICATION` or `CLOSED` they fail with
        `ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS` (HTTP 409). Third, cycle
        configuration edits are permitted only while the cycle is `DRAFT` or
        `OPEN`; attempted against `RECERTIFICATION` or `CLOSED` they fail with
        `ERR_CYCLE_NOT_EDITABLE` (HTTP 409)."

        Design: Corner/state_machines/cycle_posture_blocks_application_and_edit
        """
        cycle = create_and_open_cycle()
        resp = api.set_clock({"to_iso8601": "2026-11-02T00:00:00Z"}, COORD)
        get_success_data(resp)
        get_success_data(api.begin_recertification(cycle["id"], COORD))
        cur = get_success_data(api.get_cycle(cycle["id"], COORD))

        resp = api.create_application(
            create_application_payload(cycle["id"], applicant_name="Late Comer",
                                       email="late@example.org",
                                       prior_gardening_years=1), COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ACCEPTING_APPLICATIONS)

        resp = api.update_cycle(
            cycle["id"],
            {"expected_cycle_version": cur["version"],
             "hour_requirement": 30.0},
            COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_EDITABLE)

        final = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert final["hour_requirement"] == 40.0


class TestAdmissions:
    def test_composite_score_tiered_bonus_and_cap_weights(self, api):
        """PRD §3.1: "First the weighted component: the essay contributes
        forty percent of its score and the interview contributes sixty
        percent. Second, an experience bonus is added from
        `prior_gardening_years`: ten or more years earns eight points, five
        through nine years earns five points, two through four years earns
        three points, and fewer than two years earns nothing. Third, a county
        bonus of four points is added when the application's `county` appears
        in the cycle's `priority_counties`, and zero otherwise."

        Design: Difficulty/combinatorial_formula/composite_score_tiered_bonus_and_cap
        """
        cycle = create_cycle(priority_counties=["Harford"])
        a1 = create_application(cycle["id"], applicant_name="Alice Arbor",
                                email="alice@example.org", county="Harford",
                                prior_gardening_years=7)
        resp = api.score_application(
            a1["id"], {"essay_score": 80, "interview_score": 90}, COORD)
        scored = validate_success(resp)
        # 0.4*80 + 0.6*90 + 5 (years 5..9) + 4 (priority county) = 95.0
        assert scored["composite_score"] == pytest.approx(95.0, abs=0.01)
        assert scored["status"] == "SCORED"

    def test_composite_score_hard_cap_at_100(self, api):
        """PRD §3.1: "The weighted total plus both bonuses is rounded half-up
        to one decimal place, and the `composite_score` is the lesser of one
        hundred and that rounded total — a hard cap, never exceeded."

        Design: Difficulty/combinatorial_formula/composite_score_tiered_bonus_and_cap
        """
        cycle = create_cycle(priority_counties=["Harford"])
        a2 = create_application(cycle["id"], applicant_name="Carol Cedar",
                                email="carol@example.org", county="Harford",
                                prior_gardening_years=12)
        resp = api.score_application(
            a2["id"], {"essay_score": 100, "interview_score": 100}, COORD)
        scored = validate_success(resp)
        # 40 + 60 + 8 + 4 = 112.0 raw -> capped at exactly 100.0
        assert scored["composite_score"] == pytest.approx(100.0, abs=0.01)

    def test_application_create_missing_required_returns_invalid_request(
            self, api):
        """PRD §2.9: "(3) schema validation of required fields, types, enum
        membership, and static ranges — `ERR_INVALID_REQUEST` (HTTP 400) for
        missing fields, wrong types, invalid enum members, or malformed
        values"

        Design: Corner/entities/application_create_missing_required_returns_invalid_request
        """
        cycle = create_and_open_cycle()
        payload = {"cycle_id": cycle["id"], "applicant_name": "No Email",
                   "county": "Harford", "prior_gardening_years": 2}
        resp = api.create_application(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_application_create_ignores_client_supplied_id_input_ignored(
            self, api):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD §2.4: "`version` (integer): a system-managed integer that starts
        at 1 on creation and increments by one on every mutation, including
        mutations driven by system cascades and recomputed derived fields."

        Design: Corner/entities/application_create_ignores_client_supplied_id_input_ignored
        """
        cycle = create_and_open_cycle()
        payload = create_application_payload(cycle["id"])
        payload["id"] = "client-supplied-id"
        payload["version"] = 99
        resp = api.create_application(payload, COORD)
        app = validate_success(resp, expected_status=201)
        assert app["id"] != "client-supplied-id"
        assert app["version"] == 1

    def test_decide_on_terminal_application_rejected(self, api):
        """PRD §3.1: "Invoking a decision on an application in any other
        state, including a terminal one, fails with
        `ERR_APPLICATION_NOT_SCORED`."

        Design: Corner/state_machines/decide_on_terminal_application_rejected
        """
        cycle = create_and_open_cycle()
        app = create_application(cycle["id"])
        score_application(app["id"])
        decide_application(app["id"], "REJECT")
        resp = api.decide_application(app["id"], {"decision": "ACCEPT"}, COORD)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SCORED)
        after = get_success_data(api.get_application(app["id"], COORD))
        assert after["status"] == "REJECTED"
        cyc = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cyc["accepted_count"] == 0

    def test_promote_with_empty_waitlist_returns_409(self, api):
        """PRD §3.1: "With a seat free, the candidate set is the cycle's
        `WAITLISTED` applications; an empty set fails with
        `ERR_WAITLIST_EMPTY`."

        Design: Corner/errors/promote_with_empty_waitlist_returns_409
        """
        cycle = create_and_open_cycle(admission_capacity=2)
        resp = api.promote_waitlisted(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_WAITLIST_EMPTY)

    def test_accept_decision_without_seat_returns_409(self, api):
        """PRD §3.1: "Acceptance requires a free seat: when the cycle's
        `accepted_count` has reached its `admission_capacity`, the attempt
        fails with `ERR_NO_SEATS_AVAILABLE`."

        Design: Corner/errors/accept_decision_without_seat_returns_409
        """
        cycle = create_and_open_cycle(admission_capacity=1)
        a1 = create_application(cycle["id"], applicant_name="Alice Arbor",
                                email="alice@example.org")
        score_application(a1["id"])
        decide_application(a1["id"], "ACCEPT")
        a2 = create_application(cycle["id"], applicant_name="Bob Birch",
                                email="bob@example.org", county="Cecil",
                                prior_gardening_years=3)
        score_application(a2["id"])
        resp = api.decide_application(a2["id"], {"decision": "ACCEPT"}, COORD)
        validate_error(resp, ApiErrorId.ERR_NO_SEATS_AVAILABLE)
        after = get_success_data(api.get_application(a2["id"], COORD))
        assert after["status"] == "SCORED"
        cyc = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cyc["accepted_count"] == 1

    def test_waitlist_promotion_tie_breaks_by_created_at(self, api):
        """PRD §3.1: "Candidates are ranked by `composite_score` descending
        with ties broken by `created_at` ascending, and the top-ranked
        application is promoted to `ACCEPTED` with the same side effects as a
        direct acceptance."

        Design: Corner/cross_cutting_complexity_layers/waitlist_promotion_tie_breaks_by_created_at
        """
        cycle = create_and_open_cycle(admission_capacity=2,
                                      priority_counties=["Harford"])
        a1 = create_application(cycle["id"], applicant_name="Alice Arbor",
                                email="alice@example.org")
        score_application(a1["id"])
        decide_application(a1["id"], "ACCEPT")
        a2 = create_application(cycle["id"], applicant_name="Bob Birch",
                                email="bob@example.org")
        score_application(a2["id"])  # 95.0
        decide_application(a2["id"], "WAITLIST")
        a3 = create_application(cycle["id"], applicant_name="Carol Cedar",
                                email="carol@example.org")
        score_application(a3["id"])  # 95.0 as well (same inputs)
        decide_application(a3["id"], "WAITLIST")

        resp = api.promote_waitlisted(cycle["id"], COORD)
        promoted = validate_success(resp)
        assert promoted["id"] == a2["id"]
        assert promoted["status"] == "ACCEPTED"
        vols = get_success_data(api.list_volunteers(
            COORD, params={"application_id": a2["id"]}))
        assert vols and vols[0]["status"] == "TRAINEE"
        a3_after = get_success_data(api.get_application(a3["id"], COORD))
        assert a3_after["status"] == "WAITLISTED"


class TestTraining:
    def test_training_quiz_boundary_completion_vs_failure(self, api):
        """PRD §3.2: "if `modules_completed` is at least the cycle's
        `training_module_count` and `quiz_average` is at least the cycle's
        `training_pass_quiz_average`, the enrollment becomes `COMPLETED`;
        otherwise it becomes `FAILED`."

        Design: Corner/calculations/training_quiz_boundary_completion_vs_failure
        """
        cycle = create_and_open_cycle()
        v1 = create_active_volunteer(cycle["id"], quiz_average=70.0,
                                     applicant_name="Alice Arbor",
                                     email="alice@example.org")
        assert v1["status"] == "ACTIVE"

        # A second trainee who completes with 69.9 must FAIL and stay TRAINEE.
        from test_helpers import create_accepted_volunteer
        v2 = create_accepted_volunteer(cycle["id"], applicant_name="Bob Birch",
                                       email="bob@example.org", county="Cecil",
                                       prior_gardening_years=3)
        resp = api.create_enrollment(
            create_enrollment_payload(cycle["id"], v2["id"]), COORD)
        enr2 = get_success_data(resp)
        get_success_data(api.record_progress(
            enr2["id"], {"modules_completed": 5, "quiz_average": 69.9}, COORD))
        resp = api.complete_enrollment(enr2["id"], COORD)
        done = validate_success(resp)
        assert done["status"] == "FAILED"
        v2_after = get_success_data(api.get_volunteer(v2["id"], COORD))
        assert v2_after["status"] == "TRAINEE"

    def test_progress_on_failed_enrollment_returns_409(self, api):
        """PRD §3.2: "Progress updates require the enrollment to be `ENROLLED`
        (otherwise `ERR_ENROLLMENT_NOT_ENROLLED`) and the cycle `OPEN`."

        Design: Corner/errors/progress_on_failed_enrollment_returns_409
        """
        cycle = create_and_open_cycle()
        from test_helpers import create_accepted_volunteer
        vol = create_accepted_volunteer(cycle["id"])
        resp = api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD)
        enr = get_success_data(resp)
        get_success_data(api.record_progress(
            enr["id"], {"modules_completed": 5, "quiz_average": 50.0}, COORD))
        get_success_data(api.complete_enrollment(enr["id"], COORD))

        resp = api.record_progress(
            enr["id"], {"modules_completed": 5, "quiz_average": 90.0}, COORD)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ENROLLED)
        after = get_success_data(api.get_enrollment(enr["id"], COORD))
        assert after["status"] == "FAILED"
        assert after["quiz_average"] == pytest.approx(50.0, abs=0.01)

    def test_duplicate_enrollment_returns_409(self, api):
        """PRD §3.2: "a volunteer may hold at most one `ENROLLED` enrollment
        per cycle (a duplicate fails with `ERR_DUPLICATE_ENROLLMENT`)"

        Design: Corner/errors/duplicate_enrollment_returns_409
        """
        cycle = create_and_open_cycle()
        from test_helpers import create_accepted_volunteer
        vol = create_accepted_volunteer(cycle["id"])
        get_success_data(api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD))
        resp = api.create_enrollment(
            create_enrollment_payload(cycle["id"], vol["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)
        cyc = get_success_data(api.get_cycle(cycle["id"], COORD))
        assert cyc["enrolled_count"] == 1

    def test_training_full_returns_409(self, api):
        """PRD §3.2: "a cycle whose `enrolled_count` has reached its
        `training_capacity` accepts no more trainees (`ERR_TRAINING_FULL`)."

        Design: Corner/errors/training_full_returns_409
        """
        cycle = create_and_open_cycle(training_capacity=1)
        from test_helpers import create_accepted_volunteer
        v1 = create_accepted_volunteer(cycle["id"], applicant_name="Alice Arbor",
                                       email="alice@example.org")
        v2 = create_accepted_volunteer(cycle["id"], applicant_name="Bob Birch",
                                       email="bob@example.org", county="Cecil",
                                       prior_gardening_years=3)
        get_success_data(api.create_enrollment(
            create_enrollment_payload(cycle["id"], v1["id"]), COORD))
        resp = api.create_enrollment(
            create_enrollment_payload(cycle["id"], v2["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_TRAINING_FULL)

    def test_volunteer_and_application_state_errors(self, api):
        """PRD §3.8: "The reverse path is reactivation, a coordinator action
        valid only on an `INACTIVE` volunteer (otherwise
        `ERR_VOLUNTEER_NOT_INACTIVE`)"
        PRD §3.1: "Scoring records the reviewer's `essay_score` and
        `interview_score`, each an integer from 0 to 100, and is permitted
        only while the application is `SUBMITTED` (otherwise
        `ERR_APPLICATION_NOT_SUBMITTED`)"

        Design: Corner/state_machines/volunteer_and_application_state_errors
        """
        cycle = create_and_open_cycle(priority_counties=["Harford"])
        app = create_application(cycle["id"])
        score_application(app["id"])  # composite 95.0 with defaults
        decide_application(app["id"], "ACCEPT")
        vols = get_success_data(api.list_volunteers(
            COORD, params={"application_id": app["id"]}))
        vol = vols[0]

        resp = api.reactivate_volunteer(vol["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_INACTIVE)

        resp = api.score_application(
            app["id"], {"essay_score": 90, "interview_score": 90}, COORD)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)
        after = get_success_data(api.get_application(app["id"], COORD))
        assert after["composite_score"] == pytest.approx(95.0, abs=0.01)
