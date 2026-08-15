"""Appeal submission guards: standing, window, documents, ownership, and OCC."""
import pytest

from test_helpers import (
    AID_ADMIN, AID_OFFICER, REGISTRAR, appeal_payload, api_client,
    close_and_evaluate, close_grading, create_posted_enrollment, create_program,
    create_student, create_standard_terms, document_payload, get_student,
    list_audit_events, make_student_headers, official_evaluation, set_clock,
    setup_appeal_under_review, setup_submitted_appeal, setup_suspended_student,
    student_version, submit_appeal, validate_error, validate_paginated,
    validate_success,
)


def _appeal_count(api, student_id) -> int:
    _rows, meta = validate_paginated(
        api.list_appeals(AID_OFFICER, params={"student_id": student_id, "limit": 100}))
    return meta["total_count"]


class TestStateBeatsTemporalAfterReinstatement:
    """A reinstated student appealing a stale suspension hits the standing guard."""

    def _world(self, api):
        """Suspended at T2 (deadline 2026-08-15), then reinstated at T3 with the
        logical clock advanced past the T2 appeal deadline."""
        world = setup_suspended_student()
        student_id = world["student"]["id"]
        create_posted_enrollment(student_id, world["terms"][3]["id"], 12, 12, 48.0, 12)
        close_grading(world["terms"][3]["id"])
        set_clock("2026-08-21T00:00:00Z")
        api_client.evaluate_term(world["terms"][3]["id"], AID_OFFICER)
        world["student"] = get_student(student_id)
        return world

    def test_late_appeal_after_reinstatement_fails_state_check(self, api):
        """PRD section 2.4: "9. **Suspension precondition** — an appeal may be
        submitted only from `SUSPENSION`, else `ERR_STUDENT_NOT_SUSPENDED`."
        PRD section 2.4: "A single request can fail several rules at once, so the
        server evaluates guards in a fixed global order and reports the first failure
        encountered."
        PRD section 2.4: "13. **Appeal window** — the appeal deadline of the referenced
        evaluation must not have passed, else `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_late_appeal_after_reinstatement
        """
        world = self._world(api)
        student = world["student"]
        assert student["sap_status"] == "GOOD_STANDING", (
            "setup sanity: pace 75.00 / GPA 2.500 reinstated the student at T3")

        res = api.create_appeal(
            appeal_payload(world["evaluation"]["id"], student["version"],
                           statement="Late appeal"),
            make_student_headers(student["id"]))
        # The standing guard (earlier in the global order) beats the window check.
        validate_error(res, "ERR_STUDENT_NOT_SUSPENDED")

    def test_late_appeal_after_reinstatement_persists_nothing(self, api):
        """PRD section 2.4: "9. **Suspension precondition** — an appeal may be
        submitted only from `SUSPENSION`, else `ERR_STUDENT_NOT_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_late_appeal_after_reinstatement
        """
        world = self._world(api)
        student = world["student"]
        res = api.create_appeal(
            appeal_payload(world["evaluation"]["id"], student["version"],
                           reason_category="MEDICAL", statement="Late appeal"),
            make_student_headers(student["id"]))
        validate_error(res, "ERR_STUDENT_NOT_SUSPENDED")
        assert _appeal_count(api, student["id"]) == 0, (
            "a rejected submission must not persist an appeal row")


class TestTemporalBeatsDocumentation:
    """A late, undocumented appeal fails the window check before the docs check."""

    def _world(self, api):
        world = setup_suspended_student()
        # The suspension was evaluated at the startup clock 2026-08-01, so the
        # deadline is 2026-08-15; move one day past it.
        set_clock("2026-08-16T00:00:00Z")
        world["student_version"] = student_version(world["student"]["id"])
        return world

    def test_late_appeal_without_documents_fails_window_check(self, api):
        """PRD section 2.4: "a submission that arrives after the appeal deadline with
        an empty document array fails with `ERR_APPEAL_WINDOW_CLOSED`, never reaching
        the documentation check"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_late_appeal_without_documents
        """
        world = self._world(api)
        res = api.create_appeal(
            appeal_payload(world["evaluation"]["id"], world["student_version"],
                           reason_category="OTHER",
                           statement="Late and undocumented", documents=[]),
            make_student_headers(world["student"]["id"]))
        # The window check fires before the documentation check.
        validate_error(res, "ERR_APPEAL_WINDOW_CLOSED")

    def test_late_appeal_with_documents_still_fails_window_check(self, api):
        """PRD section 3.6: "the referenced evaluation's window must still be open,
        with the current logical time on or before `appeal_deadline_at` — the deadline
        instant itself still accepts submissions (`ERR_APPEAL_WINDOW_CLOSED`)"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_late_appeal_without_documents
        """
        world = self._world(api)
        res = api.create_appeal(
            appeal_payload(world["evaluation"]["id"], world["student_version"],
                           reason_category="MEDICAL", statement="Late but documented"),
            make_student_headers(world["student"]["id"]))
        validate_error(res, "ERR_APPEAL_WINDOW_CLOSED")
        assert _appeal_count(api, world["student"]["id"]) == 0


class TestAppealDeadlineInclusiveAtExactSecond:
    """The deadline instant itself still accepts submissions; one second later fails."""

    def _world(self, api):
        """Two students suspended by the same T2 run; both evaluations carry
        appeal_deadline_at == evaluated_at (2026-08-01) + 14 days."""
        program = create_program(code="BS-SOCI", name="Sociology", required_credits=120)
        terms = create_standard_terms(2)
        student_x = create_student(program["id"], student_number="S-9201",
                                   full_name="Xena OnTime")
        student_y = create_student(program["id"], student_number="S-9202",
                                   full_name="Yuri Late")
        for seq in (1, 2):
            for stu in (student_x, student_y):
                create_posted_enrollment(stu["id"], terms[seq]["id"], 6, 3, 6.0, 6)
            close_and_evaluate(terms[seq]["id"])
        ev_x = official_evaluation(student_x["id"], terms[2]["id"])
        ev_y = official_evaluation(student_y["id"], terms[2]["id"])
        return student_x, student_y, ev_x, ev_y

    def test_appeal_at_exact_deadline_accepted(self, api):
        """PRD section 3.6: "the referenced evaluation's window must still be open,
        with the current logical time on or before `appeal_deadline_at` — the deadline
        instant itself still accepts submissions (`ERR_APPEAL_WINDOW_CLOSED`)"
        PRD section 3.5: "it stamps `evaluated_at` from the logical clock and computes
        `appeal_deadline_at` as `evaluated_at` plus the program's `appeal_window_days`
        days."

        Design: Difficulty/boundary_precision_check/appeal_deadline_inclusive_at_exact_second
        """
        student_x, _student_y, ev_x, _ev_y = self._world(api)
        assert ev_x["appeal_deadline_at"].startswith("2026-08-15T00:00:00")

        set_clock("2026-08-15T00:00:00Z")
        appeal = submit_appeal(student_x["id"], ev_x["id"],
                               student_version(student_x["id"]),
                               statement="On-time appeal")
        assert appeal["status"] == "SUBMITTED", "the deadline instant is inclusive"

    def test_appeal_one_second_past_deadline_rejected(self, api):
        """PRD section 3.6: "the referenced evaluation's window must still be open,
        with the current logical time on or before `appeal_deadline_at` — the deadline
        instant itself still accepts submissions (`ERR_APPEAL_WINDOW_CLOSED`)"

        Design: Difficulty/boundary_precision_check/appeal_deadline_inclusive_at_exact_second
        """
        _student_x, student_y, _ev_x, ev_y = self._world(api)
        set_clock("2026-08-15T00:00:01Z")
        res = api.create_appeal(
            appeal_payload(ev_y["id"], student_version(student_y["id"]),
                           statement="One second late"),
            make_student_headers(student_y["id"]))
        validate_error(res, "ERR_APPEAL_WINDOW_CLOSED")


class TestAppealRequiresStudentSuspension:
    """A WARNING student holding a valid OFFICIAL evaluation cannot open an appeal."""

    def _world(self, api):
        """One failing term: GOOD_STANDING -> WARNING (no suspension, no window)."""
        program = create_program(code="BS-ART", name="Art", required_credits=120)
        terms = create_standard_terms(1)
        student = create_student(program["id"], student_number="S-9301",
                                 full_name="Gail Gated")
        create_posted_enrollment(student["id"], terms[1]["id"], 12, 6, 24.0, 12)
        close_and_evaluate(terms[1]["id"])
        evaluation = official_evaluation(student["id"], terms[1]["id"])
        return student, evaluation

    def test_warning_student_cannot_appeal(self, api):
        """PRD section 3.6: "the caller must currently stand in `SUSPENSION`
        (`ERR_STUDENT_NOT_SUSPENDED`)"

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_student_suspension
        """
        student, evaluation = self._world(api)
        assert get_student(student["id"])["sap_status"] == "WARNING"
        res = api.create_appeal(
            appeal_payload(evaluation["id"], student_version(student["id"]),
                           reason_category="OTHER",
                           statement="I want to appeal my warning"),
            make_student_headers(student["id"]))
        validate_error(res, "ERR_STUDENT_NOT_SUSPENDED")

    def test_warning_student_appeal_attempt_persists_nothing(self, api):
        """PRD section 3.6: "the caller must currently stand in `SUSPENSION`
        (`ERR_STUDENT_NOT_SUSPENDED`)"

        Design: Difficulty/cross_entity_state_dependency/appeal_requires_student_suspension
        """
        student, evaluation = self._world(api)
        res = api.create_appeal(
            appeal_payload(evaluation["id"], student_version(student["id"]),
                           reason_category="OTHER", statement="Appeal from warning"),
            make_student_headers(student["id"]))
        validate_error(res, "ERR_STUDENT_NOT_SUSPENDED")
        assert _appeal_count(api, student["id"]) == 0


def test_appeal_without_documents_rejected(api):
    """PRD section 3.6: "at least one document must be attached
    (`ERR_APPEAL_DOCS_REQUIRED`)"

    Design: Corner/validations/appeal_without_documents_rejected
    """
    world = setup_suspended_student()
    res = api.create_appeal(
        appeal_payload(world["evaluation"]["id"], world["student_version"],
                       statement="no docs attached", documents=[]),
        make_student_headers(world["student"]["id"]))
    validate_error(res, "ERR_APPEAL_DOCS_REQUIRED")
    assert _appeal_count(api, world["student"]["id"]) == 0


def test_appeal_second_while_under_review_rejected(api):
    """PRD section 3.6: "no appeal of theirs may already sit in `UNDER_REVIEW`
    (`ERR_APPEAL_UNDER_REVIEW`)"

    Design: Corner/validations/appeal_second_while_under_review_rejected
    """
    world = setup_appeal_under_review()
    student_id = world["student"]["id"]
    res = api.create_appeal(
        appeal_payload(world["evaluation"]["id"], student_version(student_id),
                       reason_category="FAMILY_EMERGENCY",
                       statement="second while under review"),
        make_student_headers(student_id))
    validate_error(res, "ERR_APPEAL_UNDER_REVIEW")

    assert _appeal_count(api, student_id) == 1, "no second row persisted"
    appeal = validate_success(api.get_appeal(world["appeal"]["id"], AID_OFFICER), 200)
    assert appeal["status"] == "UNDER_REVIEW"


def test_appeal_referencing_other_students_evaluation_rejected(api):
    """PRD section 3.6: "the referenced evaluation must be an `OFFICIAL` row belonging
    to the caller whose `result_standing` is `SUSPENSION` (`ERR_EVALUATION_MISMATCH`)"

    Design: Corner/validations/appeal_referencing_other_students_evaluation_rejected
    """
    program = create_program(code="BS-MM", name="Mismatch", required_credits=120)
    terms = create_standard_terms(2)
    student_1 = create_student(program["id"], student_number="S-3011",
                               full_name="One")
    student_2 = create_student(program["id"], student_number="S-3012",
                               full_name="Two")
    for seq in (1, 2):
        for stu in (student_1, student_2):
            create_posted_enrollment(stu["id"], terms[seq]["id"], 6, 3, 6.0, 6)
        close_and_evaluate(terms[seq]["id"])
    evaluation_2 = official_evaluation(student_2["id"], terms[2]["id"])

    res = api.create_appeal(
        appeal_payload(evaluation_2["id"], student_version(student_1["id"]),
                       statement="wrong evaluation"),
        make_student_headers(student_1["id"]))
    validate_error(res, "ERR_EVALUATION_MISMATCH")
    assert _appeal_count(api, student_1["id"]) == 0


def test_appeal_invalid_enum_reason_category_rejected(api):
    """PRD section 2.4: "22. **Body well-formedness** — required fields present, enums
    valid, dates coherent, else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/appeal_invalid_enum_reason_category_rejected
    """
    world = setup_suspended_student()
    res = api.create_appeal(
        appeal_payload(world["evaluation"]["id"], world["student_version"],
                       reason_category="ALIEN_ABDUCTION", statement="s"),
        make_student_headers(world["student"]["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_occ_appeal_create_stale_version_rejected(api):
    """PRD section 2.8: "An appeal-submission request — `POST /sap/appeals` — must
    carry `expected_student_version`, holding the `version` of the appealing student's
    record as the client last observed it. If the student's current `version` no longer
    matches the supplied value, the submission is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD section 3.6: "On success the appeal opens in `SUBMITTED` with `submitted_at`
    stamped from the logical clock and `decided_at` still null, the student's `version`
    increments by one, and `APPEAL_SUBMITTED` is audited."

    Design: Corner/complexity_layers/occ_appeal_create_stale_version_rejected
    """
    world = setup_suspended_student()
    student_id = world["student"]["id"]
    observed_version = world["student_version"]

    first = submit_appeal(student_id, world["evaluation"]["id"], observed_version,
                          statement="first appeal")
    assert first["status"] == "SUBMITTED"

    res = api.create_appeal(
        appeal_payload(world["evaluation"]["id"], observed_version,
                       reason_category="FAMILY_EMERGENCY",
                       statement="stale second appeal"),
        make_student_headers(student_id))
    # The first create advanced the student's version, so the same value is stale.
    validate_error(res, "ERR_STALE_VERSION")

    assert student_version(student_id) == observed_version + 1, (
        "a successful submission increments the student's version by exactly one")
    rows, meta = validate_paginated(
        api.list_appeals(AID_OFFICER, params={"student_id": student_id, "limit": 100}))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "SUBMITTED", (
        "the rejected stale write superseded nothing")


def test_appeal_supersede_replaces_submitted_appeal(api):
    """PRD section 3.6: "Submission also retires the student's older unfinished appeal:
    one still sitting in `SUBMITTED` moves `SUBMITTED` → `SUPERSEDED`, and one awaiting
    more documentation moves `MORE_INFO_REQUESTED` → `SUPERSEDED`, with
    `APPEAL_SUPERSEDED` appended beside the submission's audit row."

    Design: Corner/complexity_layers/appeal_supersede_replaces_submitted_appeal
    """
    world = setup_submitted_appeal()
    student_id = world["student"]["id"]
    first = world["appeal"]

    second = submit_appeal(student_id, world["evaluation"]["id"],
                           student_version(student_id),
                           reason_category="MILITARY",
                           statement="v2 with better docs",
                           documents=[document_payload("ORDERS", "n2")])
    assert second["status"] == "SUBMITTED"

    retired = validate_success(api.get_appeal(first["id"], AID_OFFICER), 200)
    assert retired["status"] == "SUPERSEDED"

    assert _appeal_count(api, student_id) == 2
    superseded, meta = validate_paginated(api.list_appeals(
        AID_OFFICER,
        params={"student_id": student_id, "status": "SUPERSEDED", "limit": 100}))
    assert meta["total_count"] == 1
    assert superseded[0]["id"] == first["id"]

    superseded_events = list_audit_events(
        {"student_id": student_id, "action": "APPEAL_SUPERSEDED"})
    assert len(superseded_events) == 1
    assert superseded_events[0]["entity_id"] == first["id"]
    submitted_events = list_audit_events(
        {"student_id": student_id, "action": "APPEAL_SUBMITTED"})
    assert len(submitted_events) == 2
