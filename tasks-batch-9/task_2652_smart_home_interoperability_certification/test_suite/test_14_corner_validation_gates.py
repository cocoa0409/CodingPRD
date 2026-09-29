"""Validation-ladder gates on the second half of the certification chain.

Each scenario here drives one request that violates several rules at once and
pins down exactly which rung answers: the laboratory-state and reviewable-history
gates on a competency review, result-line addressing against a plan's closure,
the duplicate-versus-closed-window pair on plugfest registration, coverage
completeness against the plugfest-credit minimum, and the shape, range, case-state
and remediation-deadline gates on a noncompliance advance.
"""

from test_helpers import (
    CASE_EVIDENCE_REVIEW,
    CASE_OPEN,
    CASE_REMEDIATION_ORDERED,
    CLOCK_PROGRAMME_START,
    COMPLIANCE_UNDER_INVESTIGATION,
    ERR_DUPLICATE_PARTICIPATION,
    ERR_INSUFFICIENT_PLUGFEST_CREDITS,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_LABORATORY_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SESSION_STATE,
    ERR_MANDATORY_COVERAGE_INCOMPLETE,
    ERR_NO_COMPLETED_SESSIONS,
    ERR_REGISTRATION_CLOSED,
    ERR_REMEDIATION_DEADLINE_PASSED,
    ERR_UNKNOWN_RESULT_FEATURE_SET,
    LAB_AUTHORIZED,
    LAB_PROVISIONAL,
    PARTICIPATION_REGISTERED,
    PLAN_COMPLETE,
    PUB_UNPUBLISHED,
    REVIEW_PENDING,
    SESSION_SCHEDULED,
    SUB_IN_REVIEW,
    advance_case,
    build_laboratory,
    build_program,
    feature,
    new_case,
    new_listing,
    new_participation,
    new_plugfest,
    new_submission,
    read_case,
    read_laboratory,
    read_listing,
    read_member,
    read_plugfest,
    read_readiness,
    read_session,
    read_submission,
    result_line,
    same_instant,
    set_clock,
    start_session,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_penalty,
    assert_score,
    expected_certification_fee,
)
from test_helpers.factories import (
    case_advance_payload,
    competency_review_payload,
    conformance_decision_payload,
    dispute_line_payload,
    participation_payload,
    results_payload,
)
from test_helpers.fixtures import read_test_plan
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    COMPLIANCE_HEADERS_2,
    CONFORMANCE_HEADERS,
    make_laboratory_headers,
    make_member_headers,
)

ONE_MANDATORY_LIGHTING_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]

#: A lighting baseline plus one undeclared optional lighting set and a mandatory
#: thermostat set, so two different kinds of out-of-closure feature set exist.
LIGHTING_PLUS_STRANGERS = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_EXTRA", "OPTIONAL", 5),
    feature("T_CORE", "MANDATORY", 10, device_type="THERMOSTAT"),
]


def _authorized_and_provisional_laboratories():
    """One AUTHORIZED laboratory and one left PROVISIONAL, with no session anywhere."""
    set_clock(CLOCK_PROGRAMME_START)
    authorized = build_laboratory()
    provisional = build_laboratory(authorize=False)
    return authorized, provisional


class TestCompetencyReviewGates:
    """A competency review needs an authorized laboratory and a reviewable history."""

    def test_01_a_provisional_laboratory_is_turned_away_on_state_not_on_history(self):
        """A PROVISIONAL laboratory that also has no completed session at all is
        refused on its accreditation status, because the laboratory-state rung is
        evaluated long before the reviewable-history rung.

        PRD (§2.8): "**Laboratory state.** `ERR_INVALID_LABORATORY_STATE` (409) when
        the target laboratory's `accreditation_status` does not permit the operation:
        authorizing requires `PROVISIONAL`; suspending requires `AUTHORIZED`;
        reinstating requires `SUSPENDED`; revoking requires `PROVISIONAL`,
        `AUTHORIZED` or `SUSPENDED`; and booking or starting a test session, or
        running a competency review, requires `AUTHORIZED`."

        Design: Corner/validations/competency_review_needs_an_authorized_lab_and_a_completed_session
        """
        authorized, provisional = _authorized_and_provisional_laboratories()

        response = api_client.competency_review(
            provisional.laboratory_id,
            competency_review_payload("ROLLING_90D"),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_LABORATORY_STATE)
        laboratory = read_laboratory(provisional.laboratory_id)
        assert laboratory["accreditation_status"] == LAB_PROVISIONAL, (
            "the refused review leaves the laboratory PROVISIONAL, got {}".format(
                laboratory["accreditation_status"]
            )
        )
        assert laboratory["competency_score"] is None, (
            "a refused review writes no competency_score, expected None, got "
            "{!r}".format(laboratory["competency_score"])
        )
        assert laboratory["competency_reviewed_at"] is None, (
            "a refused review stamps no competency_reviewed_at, expected None, got "
            "{!r}".format(laboratory["competency_reviewed_at"])
        )

    def test_02_an_authorized_laboratory_with_no_completed_session_is_refused(self):
        """An AUTHORIZED laboratory whose counted set is empty is refused under both
        declared variants, and neither refusal writes a score, a variant or a stamp.

        PRD (§3.3): "If the requested variant's counted set contains no `COMPLETE`
        session at all, no score is written and the review is refused with
        `ERR_NO_COMPLETED_SESSIONS`."

        Design: Corner/validations/competency_review_needs_an_authorized_lab_and_a_completed_session
        """
        authorized, provisional = _authorized_and_provisional_laboratories()

        rolling = api_client.competency_review(
            authorized.laboratory_id,
            competency_review_payload("ROLLING_90D"),
            ADMIN_HEADERS,
        )
        lifetime = api_client.competency_review(
            authorized.laboratory_id,
            competency_review_payload("LIFETIME"),
            ADMIN_HEADERS,
        )

        validate_error(rolling, ERR_NO_COMPLETED_SESSIONS)
        validate_error(lifetime, ERR_NO_COMPLETED_SESSIONS)
        laboratory = read_laboratory(authorized.laboratory_id)
        assert laboratory["competency_score"] is None, (
            "no refused review writes competency_score, expected None, got "
            "{!r}".format(laboratory["competency_score"])
        )
        assert laboratory["competency_variant"] is None, (
            "no refused review writes competency_variant, expected None, got "
            "{!r}".format(laboratory["competency_variant"])
        )
        assert laboratory["competency_reviewed_at"] is None, (
            "no refused review stamps competency_reviewed_at, expected None, got "
            "{!r}".format(laboratory["competency_reviewed_at"])
        )
        assert laboratory["accreditation_status"] == LAB_AUTHORIZED, (
            "the laboratory is still AUTHORIZED after two refusals, got {}".format(
                laboratory["accreditation_status"]
            )
        )

    def test_03_an_undeclared_variant_is_an_enum_failure_before_either_state_rule(self):
        """A variant outside the two declared values is an enumeration failure, and
        it answers ahead of both the empty-history rung and the laboratory-state rung.

        PRD (§2.8): "Every enum-typed input carries one of that field's declared
        values — otherwise `ERR_INVALID_ENUM_VALUE` (422). The enum-typed inputs are
        `device_type`, `obligation`, `tier`, `review_track`, `session_type`,
        `decision`, `disposition`, `outcome`, `variant`, `category`,
        `security_baseline_level` and `ip_commitment_type`."

        Design: Corner/validations/competency_review_needs_an_authorized_lab_and_a_completed_session
        """
        authorized, provisional = _authorized_and_provisional_laboratories()

        on_authorized = api_client.competency_review(
            authorized.laboratory_id,
            competency_review_payload("ROLLING_30D"),
            ADMIN_HEADERS,
        )
        on_provisional = api_client.competency_review(
            provisional.laboratory_id,
            competency_review_payload("ROLLING_30D"),
            ADMIN_HEADERS,
        )

        validate_error(on_authorized, ERR_INVALID_ENUM_VALUE)
        validate_error(on_provisional, ERR_INVALID_ENUM_VALUE)
        laboratory = read_laboratory(authorized.laboratory_id)
        assert laboratory["competency_variant"] is None, (
            "the rejected variant is never recorded, expected competency_variant "
            "None, got {!r}".format(laboratory["competency_variant"])
        )


def _scheduled_lighting_session():
    """A LIGHTING submission declaring only CORE_ONOFF, with an issued plan and a
    booked bench window that has not started yet."""
    return build_program(
        stage="scheduled",
        features=LIGHTING_PLUS_STRANGERS,
        declared_codes=["CORE_ONOFF"],
    )


def _in_progress_lighting_session():
    """The same programme, with the clock moved to the window's opening and the
    session started."""
    ctx = _scheduled_lighting_session()
    set_clock("2026-09-02T09:00:00Z")
    ctx.session = start_session(ctx.session_id, ctx.laboratory_id)
    return ctx


class TestResultLineAddressing:
    """Result lines and dispute indexes are checked against the plan's closure."""

    def test_04_result_lines_are_refused_before_the_window_and_outside_the_closure(self):
        """Results offered to a session that has not started are refused on session
        state; once it is running, a line naming the undeclared optional set or the
        other device class's mandatory set is refused on addressing.

        PRD (§3.6): "A `feature_set_id` that does not appear in the enclosing
        session's plan's `included_feature_set_ids` is rejected with
        `ERR_UNKNOWN_RESULT_FEATURE_SET`, and results submitted against a session
        that is not `IN_PROGRESS` are rejected with `ERR_INVALID_SESSION_STATE`."

        Design: Corner/validations/result_lines_outside_the_plan_and_bad_dispute_indexes_are_rejected
        """
        ctx = _scheduled_lighting_session()
        assert ctx.session["state"] == SESSION_SCHEDULED, (
            "the booked session starts out SCHEDULED, got {}".format(
                ctx.session["state"]
            )
        )

        too_early = api_client.append_results(
            ctx.session_id,
            results_payload([result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "h1")]),
            make_laboratory_headers(ctx.laboratory_id),
        )
        validate_error(too_early, ERR_INVALID_SESSION_STATE)

        set_clock("2026-09-02T09:00:00Z")
        start_session(ctx.session_id, ctx.laboratory_id)
        undeclared_optional = api_client.append_results(
            ctx.session_id,
            results_payload([result_line(ctx.feature_set_ids["CORE_EXTRA"], "PASS", "h2")]),
            make_laboratory_headers(ctx.laboratory_id),
        )
        other_device_class = api_client.append_results(
            ctx.session_id,
            results_payload(
                [result_line(ctx.feature_set_ids["THERMOSTAT:T_CORE"], "PASS", "h3")]
            ),
            make_laboratory_headers(ctx.laboratory_id),
        )

        validate_error(undeclared_optional, ERR_UNKNOWN_RESULT_FEATURE_SET)
        validate_error(other_device_class, ERR_UNKNOWN_RESULT_FEATURE_SET)
        plan = read_test_plan(ctx.plan_id)
        assert plan["included_feature_set_ids"] == [ctx.feature_set_ids["CORE_ONOFF"]], (
            "the closure holds CORE_ONOFF alone, expected [{}], got {}".format(
                ctx.feature_set_ids["CORE_ONOFF"], plan["included_feature_set_ids"]
            )
        )
        session = read_session(ctx.session_id)
        assert session["result_lines"] == [], (
            "no refused append is stored, expected [], got {}".format(
                session["result_lines"]
            )
        )

    def test_05_an_empty_result_lines_array_fails_the_shape_check(self):
        """An append carrying an empty `result_lines` array is a request-shape
        failure, since the array is declared non-empty.

        PRD (§2.8): "This rung also enforces the conditional requirements:
        `depends_on_feature_set_id` is required when `obligation` is `CONDITIONAL`
        and must be null when `obligation` is `MANDATORY` or `OPTIONAL`;
        `remediation_days` is required when `disposition` is `ORDER_REMEDIATION` and
        must be absent for every other disposition; `authorized_device_types` must be
        a non-empty array with no duplicate entries; `result_lines` must be a
        non-empty array of objects each carrying `feature_set_id`, `outcome` and
        `evidence_hash`; and `interop_pass_count`, whose declared range is 0 through
        8 for either outcome, must be at least 1 when `outcome` is `PASS`."

        Design: Corner/validations/result_lines_outside_the_plan_and_bad_dispute_indexes_are_rejected
        """
        ctx = _in_progress_lighting_session()

        response = api_client.append_results(
            ctx.session_id,
            results_payload([]),
            make_laboratory_headers(ctx.laboratory_id),
        )

        validate_error(response, ERR_INVALID_REQUEST)
        session = read_session(ctx.session_id)
        assert session["result_lines"] == [], (
            "the empty append leaves the session's lines untouched, expected [], "
            "got {}".format(session["result_lines"])
        )

    def test_06_an_undeclared_outcome_answers_before_the_addressing_rule(self):
        """An outcome outside the four declared values is an enumeration failure,
        and it answers even when the same line also names a feature set the plan's
        closure does not contain.

        PRD (§2.8): "Every enum-typed input carries one of that field's declared
        values — otherwise `ERR_INVALID_ENUM_VALUE` (422). The enum-typed inputs are
        `device_type`, `obligation`, `tier`, `review_track`, `session_type`,
        `decision`, `disposition`, `outcome`, `variant`, `category`,
        `security_baseline_level` and `ip_commitment_type`."

        Design: Corner/validations/result_lines_outside_the_plan_and_bad_dispute_indexes_are_rejected
        """
        ctx = _in_progress_lighting_session()

        on_a_planned_set = api_client.append_results(
            ctx.session_id,
            results_payload(
                [result_line(ctx.feature_set_ids["CORE_ONOFF"], "SKIPPED", "h4")]
            ),
            make_laboratory_headers(ctx.laboratory_id),
        )
        on_a_stranger_set = api_client.append_results(
            ctx.session_id,
            results_payload(
                [result_line(ctx.feature_set_ids["CORE_EXTRA"], "SKIPPED", "h5")]
            ),
            make_laboratory_headers(ctx.laboratory_id),
        )

        validate_error(on_a_planned_set, ERR_INVALID_ENUM_VALUE)
        validate_error(on_a_stranger_set, ERR_INVALID_ENUM_VALUE)
        session = read_session(ctx.session_id)
        assert session["result_lines"] == [], (
            "neither rejected append is stored, expected [], got {}".format(
                session["result_lines"]
            )
        )

    def test_07_a_dispute_index_past_the_end_is_refused_and_index_zero_lands(self):
        """One valid line is appended and stamped from the clock; disputing position
        5 of a one-line array is refused and changes nothing, while disputing
        position 0 flags the line and lifts the disputed count to one.

        PRD (§3.6): "A `line_index` that addresses no existing entry is rejected with
        `ERR_UNKNOWN_RESULT_FEATURE_SET`."

        Design: Corner/validations/result_lines_outside_the_plan_and_bad_dispute_indexes_are_rejected
        """
        ctx = _in_progress_lighting_session()

        accepted = api_client.append_results(
            ctx.session_id,
            results_payload([result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "h5")]),
            make_laboratory_headers(ctx.laboratory_id),
        )
        session = validate_success(accepted)
        assert len(session["result_lines"]) == 1, (
            "the valid append stores one line, expected 1, got {}".format(
                len(session["result_lines"])
            )
        )
        assert same_instant(session["result_lines"][0]["recorded_at"], "2026-09-02T09:00:00Z"), (
            "the line is stamped from the logical clock, expected "
            "2026-09-02T09:00:00Z, got {}".format(session["result_lines"][0]["recorded_at"])
        )
        assert session["result_lines"][0]["disputed"] is False, (
            "a fresh line starts undisputed, expected False, got {!r}".format(
                session["result_lines"][0]["disputed"]
            )
        )

        past_the_end = api_client.dispute_line(
            ctx.session_id, dispute_line_payload(5), CONFORMANCE_HEADERS
        )
        validate_error(past_the_end, ERR_UNKNOWN_RESULT_FEATURE_SET)
        untouched = read_session(ctx.session_id)
        assert untouched["disputed_line_count"] == 0, (
            "the out-of-range index disputes nothing, expected 0, got {}".format(
                untouched["disputed_line_count"]
            )
        )

        landed = api_client.dispute_line(
            ctx.session_id, dispute_line_payload(0), CONFORMANCE_HEADERS
        )
        disputed = validate_success(landed)
        assert disputed["result_lines"][0]["disputed"] is True, (
            "position 0 is flagged, expected True, got {!r}".format(
                disputed["result_lines"][0]["disputed"]
            )
        )
        assert disputed["disputed_line_count"] == 1, (
            "one line of one is disputed, expected disputed_line_count 1, got "
            "{}".format(disputed["disputed_line_count"])
        )


def _plugfest_with_three_draft_devices():
    """An authorized host laboratory, one member owning three draft devices, and an
    open event whose registration closes at 2026-10-01T00:00:00Z."""
    ctx = build_program(stage="laboratory", features=ONE_MANDATORY_LIGHTING_FEATURE)
    ctx.devices = [
        new_submission(ctx.member_id, ctx.specification_id, ["CORE_ONOFF"])["id"]
        for _ in range(3)
    ]
    ctx.plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.specification_id,
        window_start="2026-10-05T09:00:00Z",
        window_end="2026-10-05T17:00:00Z",
        registration_deadline="2026-10-01T00:00:00Z",
        min_distinct_vendors=2,
    )
    ctx.plugfest_id = ctx.plugfest["id"]
    return ctx


class TestPlugfestRegistrationGates:
    """The duplicate-pair rule, the calendar-overlap rule and the closed window."""

    def test_08_a_repeat_of_the_same_pair_is_a_duplicate_not_a_window_conflict(self):
        """The first registration lands and counts its vendor; repeating the same
        event-and-device pair while registration is open is refused as a duplicate,
        never as a calendar-date conflict with itself.

        PRD (§3.7): "Participations of the *requested* event are deliberately
        excluded from that check, so that a second registration of the same
        event-and-submission pair — which trivially shares every date with itself —
        instead falls through to the second rule."

        Design: Corner/validations/duplicate_participation_outranks_the_closed_registration_window
        """
        ctx = _plugfest_with_three_draft_devices()

        first = new_participation(ctx.plugfest_id, ctx.member_id, ctx.devices[0])
        repeat = api_client.create_participation(
            participation_payload(ctx.plugfest_id, ctx.member_id, ctx.devices[0]),
            make_member_headers(ctx.member_id),
        )

        assert first["state"] == PARTICIPATION_REGISTERED, (
            "an accepted registration opens in REGISTERED, got {}".format(first["state"])
        )
        validate_error(repeat, ERR_DUPLICATE_PARTICIPATION)
        plugfest = read_plugfest(ctx.plugfest_id)
        assert plugfest["distinct_vendor_count"] == 1, (
            "one member has registered, expected distinct_vendor_count 1, got "
            "{}".format(plugfest["distinct_vendor_count"])
        )

    def test_09_the_registration_deadline_is_inclusive_to_the_second(self):
        """A registration arriving at exactly the deadline instant is accepted, and
        one arriving a single second later is refused.

        PRD (§3.7): "The logical clock's current instant must be at or before the
        event's `registration_deadline`, or the registration is refused with
        `ERR_REGISTRATION_CLOSED`."

        Design: Corner/validations/duplicate_participation_outranks_the_closed_registration_window
        """
        ctx = _plugfest_with_three_draft_devices()

        set_clock("2026-10-01T00:00:00Z")
        on_the_deadline = api_client.create_participation(
            participation_payload(ctx.plugfest_id, ctx.member_id, ctx.devices[1]),
            make_member_headers(ctx.member_id),
        )
        accepted = validate_success(on_the_deadline, expected_status=201)

        set_clock("2026-10-01T00:00:01Z")
        one_second_late = api_client.create_participation(
            participation_payload(ctx.plugfest_id, ctx.member_id, ctx.devices[2]),
            make_member_headers(ctx.member_id),
        )

        assert accepted["state"] == PARTICIPATION_REGISTERED, (
            "the deadline-instant registration is stored REGISTERED, got {}".format(
                accepted["state"]
            )
        )
        validate_error(one_second_late, ERR_REGISTRATION_CLOSED)

    def test_10_the_duplicate_rule_answers_before_the_closed_window(self):
        """With the window shut and the pair already taken, both rules are violated
        at once and the duplicate rule is the one that answers, leaving exactly the
        two stored registrations behind.

        PRD (§2.8): "**Duplicate registration.** `ERR_DUPLICATE_PARTICIPATION` (409)
        when the same submission is already registered for the same plugfest."

        Design: Corner/validations/duplicate_participation_outranks_the_closed_registration_window
        """
        ctx = _plugfest_with_three_draft_devices()
        first = new_participation(ctx.plugfest_id, ctx.member_id, ctx.devices[0])
        set_clock("2026-10-01T00:00:00Z")
        new_participation(ctx.plugfest_id, ctx.member_id, ctx.devices[1])

        set_clock("2026-10-01T00:00:01Z")
        duplicate_after_close = api_client.create_participation(
            participation_payload(ctx.plugfest_id, ctx.member_id, ctx.devices[0]),
            make_member_headers(ctx.member_id),
        )

        validate_error(duplicate_after_close, ERR_DUPLICATE_PARTICIPATION)
        data, meta = validate_paginated(
            api_client.list_participations(ADMIN_HEADERS, submission_id=ctx.devices[0])
        )
        assert meta["total_count"] == 1, (
            "the refused repeat stored nothing, expected total_count 1, got "
            "{}".format(meta["total_count"])
        )
        assert data[0]["id"] == first["id"], (
            "the one stored participation for that device is the original, expected "
            "{}, got {}".format(first["id"], data[0]["id"])
        )
        plugfest = read_plugfest(ctx.plugfest_id)
        assert plugfest["distinct_vendor_count"] == 1, (
            "both registrations belong to one member, expected "
            "distinct_vendor_count 1, got {}".format(plugfest["distinct_vendor_count"])
        )


CREDIT_HUNGRY_SPECIFICATION = {"min_plugfest_credits": 1}


class TestConformanceApprovalGates:
    """Coverage completeness answers before the plugfest-credit minimum."""

    def test_11_a_missing_plan_answers_before_the_missing_plugfest_credit(self):
        """An APPROVE on a submission that has no test plan at all is refused on
        coverage completeness, even though the pinned specification's plugfest-credit
        minimum is unmet as well.

        PRD (§2.8): "**Coverage completeness.** `ERR_MANDATORY_COVERAGE_INCOMPLETE`
        (409), required in four contexts: a conformance decision requires the
        submission's non-`VOIDED` test plan to exist, to be `COMPLETE`, and to have
        every `MANDATORY` or `CONDITIONAL` feature set of `included_feature_set_ids`
        covered by at least one result line; issuing a plan requires its
        `required_case_count` to be at least 1; completing a session requires its
        `result_lines` to be non-empty; and ratifying a specification requires
        `feature_set_count` to be at least 1 and requires that, for every device class
        appearing among the specification's feature sets, at least one of that class's
        feature sets has `obligation` `MANDATORY`."

        Design: Corner/validations/coverage_completeness_outranks_the_plugfest_credit_minimum
        """
        ctx = build_program(
            stage="in_review",
            features=ONE_MANDATORY_LIGHTING_FEATURE,
            spec_overrides=CREDIT_HUNGRY_SPECIFICATION,
        )
        assert ctx.submission["plugfest_credit_count"] == 0, (
            "the device has attended no plugfest, expected plugfest_credit_count 0, "
            "got {}".format(ctx.submission["plugfest_credit_count"])
        )

        response = api_client.conformance_decision(
            ctx.submission_id, conformance_decision_payload("APPROVE"), CONFORMANCE_HEADERS
        )

        validate_error(response, ERR_MANDATORY_COVERAGE_INCOMPLETE)
        submission = read_submission(ctx.submission_id)
        assert submission["state"] == SUB_IN_REVIEW, (
            "the refused decision leaves the submission IN_REVIEW, got {}".format(
                submission["state"]
            )
        )
        assert submission["conformance_review_state"] == REVIEW_PENDING, (
            "the refused decision leaves conformance_review_state PENDING, got "
            "{}".format(submission["conformance_review_state"])
        )
        assert submission["final_readiness_score"] is None, (
            "a refused decision pins no final score, expected None, got {!r}".format(
                submission["final_readiness_score"]
            )
        )

    def test_12_with_the_plan_complete_the_credit_minimum_finally_answers(self):
        """Once the plan has bubbled to COMPLETE the identical APPROVE is refused on
        the plugfest-credit minimum, with the computed FINAL score far above the
        approval threshold and no escrow movement at all.

        PRD (§3.8): "An `APPROVE` additionally demands that the freshly computed
        final score be at or above the approval threshold of 65.00 — exactly 65.00 is
        sufficient, and a shortfall is refused with `ERR_READINESS_BELOW_THRESHOLD` —
        and that `plugfest_credit_count` be at least the pinned specification's
        `min_plugfest_credits`, with a shortfall refused as
        `ERR_INSUFFICIENT_PLUGFEST_CREDITS`."

        Design: Corner/validations/coverage_completeness_outranks_the_plugfest_credit_minimum
        """
        ctx = build_program(
            stage="plan_complete",
            features=ONE_MANDATORY_LIGHTING_FEATURE,
            spec_overrides=CREDIT_HUNGRY_SPECIFICATION,
        )
        assert ctx.plan["state"] == PLAN_COMPLETE, (
            "the completed session bubbles the plan to COMPLETE, got {}".format(
                ctx.plan["state"]
            )
        )

        response = api_client.conformance_decision(
            ctx.submission_id, conformance_decision_payload("APPROVE"), CONFORMANCE_HEADERS
        )

        validate_error(response, ERR_INSUFFICIENT_PLUGFEST_CREDITS)
        readiness = read_readiness(ctx.submission_id, variant="FINAL")
        assert_score(readiness["score"], "85.00", "FINAL readiness score")
        submission = read_submission(ctx.submission_id)
        assert submission["final_readiness_score"] is None, (
            "the score is computed but never pinned by a refused APPROVE, expected "
            "None, got {!r}".format(submission["final_readiness_score"])
        )
        assert submission["conformance_review_state"] == REVIEW_PENDING, (
            "conformance_review_state is untouched, expected PENDING, got {}".format(
                submission["conformance_review_state"]
            )
        )
        assert submission["state"] == SUB_IN_REVIEW, (
            "the submission is still IN_REVIEW, got {}".format(submission["state"])
        )
        fee = expected_certification_fee("LIGHTING", 1, "SB1", "ADOPTER", "STANDARD")
        assert_cents(submission["fee_escrowed_cents"], fee, "fee_escrowed_cents")
        member = read_member(ctx.member_id)
        assert_cents(
            member["credit_balance_cents"], 1000000 - fee, "credit_balance_cents"
        )


def _case_over_an_unpublished_listing():
    """A certified-but-unpublished listing under investigation for ten impacted
    units, with the clock left at the instant the case was opened."""
    ctx = build_program(
        stage="review_complete", features=ONE_MANDATORY_LIGHTING_FEATURE
    )
    ctx.listing = new_listing(ctx.submission_id)
    ctx.listing_id = ctx.listing["id"]
    ctx.case = new_case(
        ctx.listing_id,
        "CO1",
        category="INTEROP_DEFECT",
        claimed_impact_units=10,
        evidence_summary="Group pairing regression",
    )
    ctx.case_id = ctx.case["id"]
    return ctx


class TestNoncomplianceAdvanceGates:
    """Shape, range, case state and the remediation deadline on one investigation."""

    def test_13_a_forbidden_remediation_day_count_answers_before_the_case_state(self):
        """`remediation_days` is forbidden for every disposition other than
        ORDER_REMEDIATION, and that shape failure answers even when the disposition
        is one the case's current state does not admit either.

        PRD (§2.8): "This rung also enforces the conditional requirements:
        `depends_on_feature_set_id` is required when `obligation` is `CONDITIONAL`
        and must be null when `obligation` is `MANDATORY` or `OPTIONAL`;
        `remediation_days` is required when `disposition` is `ORDER_REMEDIATION` and
        must be absent for every other disposition; `authorized_device_types` must be
        a non-empty array with no duplicate entries; `result_lines` must be a
        non-empty array of objects each carrying `feature_set_id`, `outcome` and
        `evidence_hash`; and `interop_pass_count`, whose declared range is 0 through
        8 for either outcome, must be at least 1 when `outcome` is `PASS`."

        Design: Corner/validations/remediation_confirmation_past_its_deadline_and_out_of_state_dispositions_are_rejected
        """
        ctx = _case_over_an_unpublished_listing()
        assert ctx.case["state"] == CASE_OPEN, (
            "a filed case opens in OPEN, got {}".format(ctx.case["state"])
        )

        on_a_legal_disposition = api_client.advance_case(
            ctx.case_id,
            case_advance_payload("ESCALATE", remediation_days=30),
            COMPLIANCE_HEADERS,
        )
        on_an_illegal_disposition = api_client.advance_case(
            ctx.case_id,
            case_advance_payload("CONFIRM_REMEDIATION", remediation_days=30),
            COMPLIANCE_HEADERS,
        )

        validate_error(on_a_legal_disposition, ERR_INVALID_REQUEST)
        validate_error(on_an_illegal_disposition, ERR_INVALID_REQUEST)
        case = read_case(ctx.case_id)
        assert case["state"] == CASE_OPEN, (
            "neither refused advance moves the case, expected OPEN, got {}".format(
                case["state"]
            )
        )
        assert case["remediation_deadline_at"] is None, (
            "no deadline is set by a refused advance, expected None, got {!r}".format(
                case["remediation_deadline_at"]
            )
        )

    def test_14_the_case_state_admits_one_disposition_at_a_time(self):
        """Confirming remediation on an OPEN case is refused on case state; the first
        escalation is accepted and a second one is refused, so the trigger is not
        idempotent.

        PRD (§2.8): "**Case state.** `ERR_INVALID_CASE_STATE` (409) when the target
        case's `state` does not permit the requested `disposition`: `ESCALATE`
        requires `OPEN`; `ORDER_REMEDIATION` and `ORDER_WITHDRAWAL` require
        `EVIDENCE_REVIEW`; `CONFIRM_REMEDIATION` requires `REMEDIATION_ORDERED`; and
        a close requires `REMEDIATED` or `WITHDRAWAL_ORDERED`."

        Design: Corner/validations/remediation_confirmation_past_its_deadline_and_out_of_state_dispositions_are_rejected
        """
        ctx = _case_over_an_unpublished_listing()

        too_soon = api_client.advance_case(
            ctx.case_id, case_advance_payload("CONFIRM_REMEDIATION"), COMPLIANCE_HEADERS
        )
        validate_error(too_soon, ERR_INVALID_CASE_STATE)

        escalated = advance_case(ctx.case_id, "ESCALATE", "CO1")
        assert escalated["state"] == CASE_EVIDENCE_REVIEW, (
            "the first escalation moves the case to EVIDENCE_REVIEW, got {}".format(
                escalated["state"]
            )
        )

        again = api_client.advance_case(
            ctx.case_id, case_advance_payload("ESCALATE"), COMPLIANCE_HEADERS
        )
        validate_error(again, ERR_INVALID_CASE_STATE)
        case = read_case(ctx.case_id)
        assert case["state"] == CASE_EVIDENCE_REVIEW, (
            "the repeat escalation changes nothing, expected EVIDENCE_REVIEW, got "
            "{}".format(case["state"])
        )

    def test_15_the_remediation_day_count_is_range_checked_then_dated_exactly(self):
        """Four hundred days is outside the permitted range; one day is accepted and
        dates the deadline exactly 86400 seconds after the clock, leaving an
        unpublished listing's visibility untouched.

        PRD (§3.9): "`ORDER_REMEDIATION` moves it `EVIDENCE_REVIEW →
        REMEDIATION_ORDERED`, requires `remediation_days` to be present and between 1
        and 365 — an absent or out-of-range value being refused with
        `ERR_INVALID_DATE_RANGE` — sets `remediation_deadline_at` to the logical
        clock's current instant advanced by that many days, and, where the listing's
        `publication_status` is `PUBLISHED`, suppresses it."

        Design: Corner/validations/remediation_confirmation_past_its_deadline_and_out_of_state_dispositions_are_rejected
        """
        ctx = _case_over_an_unpublished_listing()
        advance_case(ctx.case_id, "ESCALATE", "CO1")

        out_of_range = api_client.advance_case(
            ctx.case_id,
            case_advance_payload("ORDER_REMEDIATION", remediation_days=400),
            COMPLIANCE_HEADERS,
        )
        validate_error(out_of_range, ERR_INVALID_DATE_RANGE)

        ordered = advance_case(ctx.case_id, "ORDER_REMEDIATION", "CO1", remediation_days=1)

        assert ordered["state"] == CASE_REMEDIATION_ORDERED, (
            "the accepted order moves the case to REMEDIATION_ORDERED, got "
            "{}".format(ordered["state"])
        )
        assert same_instant(ordered["remediation_deadline_at"], "2026-09-03T12:00:00Z"), (
            "one day past the 2026-09-02T12:00:00Z clock is 2026-09-03T12:00:00Z, "
            "got {}".format(ordered["remediation_deadline_at"])
        )
        listing = read_listing(ctx.listing_id)
        assert listing["publication_status"] == PUB_UNPUBLISHED, (
            "a listing that was never PUBLISHED is not suppressed, expected "
            "UNPUBLISHED, got {}".format(listing["publication_status"])
        )
        assert listing["compliance_status"] == COMPLIANCE_UNDER_INVESTIGATION, (
            "the enforcement axis stays UNDER_INVESTIGATION, got {}".format(
                listing["compliance_status"]
            )
        )

    def test_16_a_late_confirmation_strands_the_case_where_even_a_close_is_illegal(self):
        """One second past the deadline the confirmation is refused, and the case is
        left in a state that admits no close at all — refused on case state even for
        the officer who never opened it, so the state rung outranks segregation of
        duties.

        PRD (§3.9): "`CONFIRM_REMEDIATION` moves it `REMEDIATION_ORDERED →
        REMEDIATED`, requires the logical clock's current instant to be at or before
        `remediation_deadline_at` — an expired deadline being refused with
        `ERR_REMEDIATION_DEADLINE_PASSED`, with an instant exactly equal to the
        deadline accepted — and sets the listing's `compliance_status` to
        `REMEDIATED` while leaving `publication_status` at `SUPPRESSED`."

        Design: Corner/validations/remediation_confirmation_past_its_deadline_and_out_of_state_dispositions_are_rejected
        """
        ctx = _case_over_an_unpublished_listing()
        advance_case(ctx.case_id, "ESCALATE", "CO1")
        advance_case(ctx.case_id, "ORDER_REMEDIATION", "CO1", remediation_days=1)

        set_clock("2026-09-03T12:00:01Z")
        expired = api_client.advance_case(
            ctx.case_id, case_advance_payload("CONFIRM_REMEDIATION"), COMPLIANCE_HEADERS
        )
        validate_error(expired, ERR_REMEDIATION_DEADLINE_PASSED)

        close_by_another_officer = api_client.close_case(
            ctx.case_id, headers=COMPLIANCE_HEADERS_2
        )
        close_by_the_opener = api_client.close_case(
            ctx.case_id, headers=COMPLIANCE_HEADERS
        )

        validate_error(close_by_another_officer, ERR_INVALID_CASE_STATE)
        validate_error(close_by_the_opener, ERR_INVALID_CASE_STATE)
        case = read_case(ctx.case_id)
        assert case["state"] == CASE_REMEDIATION_ORDERED, (
            "the case is stranded in REMEDIATION_ORDERED, got {}".format(case["state"])
        )
        assert case["closed_by_user_id"] is None, (
            "no refused close records an officer, expected None, got {!r}".format(
                case["closed_by_user_id"]
            )
        )
        assert_penalty(case, 10, "INTEROP_DEFECT")
        listing = read_listing(ctx.listing_id)
        assert listing["compliance_status"] == COMPLIANCE_UNDER_INVESTIGATION, (
            "the failed confirmation never reaches REMEDIATED, expected "
            "UNDER_INVESTIGATION, got {}".format(listing["compliance_status"])
        )
